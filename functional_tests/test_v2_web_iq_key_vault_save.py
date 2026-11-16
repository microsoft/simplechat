# test_v2_web_iq_key_vault_save.py
"""Web IQ admin Key Vault staging and publication regression tests.

Version: 0.261.405
Implemented in: 0.261.405

Execute the real route's persistence owner with a mocked vault and settings write boundary.
No provider/bootstrap clients or credentials are initialized.
"""

import ast
import copy
import re
from pathlib import Path

import pytest

from test_support.app_stubs import import_app_module


ROUTE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_v2.py"
ERROR = import_app_module("functions_keyvault_errors").KeyVaultSecretStorageError
PREFIX = "web-iq--model-endpoint--global--"


def persistence_owner(*, fail_field=None, write_result=True, raw_result=False):
    calls, writes, cleanup = [], [], []
    vault = {}

    def save(endpoint, scope_value, scope, existing_endpoint, stage_new_secrets):
        calls.append((copy.deepcopy(endpoint), scope_value, scope, copy.deepcopy(existing_endpoint), stage_new_secrets))
        auth = endpoint["auth"]
        field = "api_key" if auth["type"] == "api_key" else "client_secret"
        if field == fail_field:
            raise RuntimeError("private SDK diagnostics")
        value = auth[field]
        if raw_result or value.startswith(PREFIX):
            return endpoint
        reference = f"{PREFIX}s-{len(calls)}"
        vault[reference] = value
        return {"auth": {"type": auth["type"], field: reference}}

    def write(updates):
        writes.append(copy.deepcopy(updates))
        if isinstance(write_result, Exception):
            raise write_result
        return write_result

    namespace = {
        "copy": copy, "update_settings": write,
        "keyvault_model_endpoint_save_helper": save,
        "keyvault_model_endpoint_cleanup_helper": lambda old, new, owner, scope: cleanup.append((old, new, owner, scope)),
        "validate_secret_name_dynamic": lambda value: isinstance(value, str) and bool(re.fullmatch(r".+--.+--.+--.+", value)),
        "secret_reference_matches_context": lambda value, **kwargs: value.startswith(PREFIX)
            and kwargs == {"scope_value": "web-iq", "scope": "global", "allowed_sources": {"model-endpoint"}},
        "KeyVaultSecretStorageError": ERROR,
        "log_event": lambda *args, **kwargs: None,
        "logging": __import__("logging"),
    }
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_persist_v2_admin_settings")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROUTE), "exec"), namespace)
    return namespace["_persist_v2_admin_settings"], calls, writes, cleanup, vault


def settings():
    return {"enable_key_vault_secret_storage": True, "key_vault_name": "test-vault",
            "web_iq": {"authentication_type": "key", "key": "api-secret", "client_secret": "inactive-secret",
                       "client_id": "keep-client", "app_id": "keep-app"}}


def test_both_credentials_stage_once_before_reference_only_publication():
    persist, calls, writes, cleanup, vault = persistence_owner()
    current = settings()
    updates = {"web_iq": copy.deepcopy(current["web_iq"])}
    saved = persist(updates, current)
    assert saved
    assert len(calls) == 2 and len(writes) == 1
    assert [call[0]["auth"]["type"] for call in calls] == ["api_key", "service_principal"]
    assert all(call[1:3] == ("web-iq", "global") and call[-1] is True for call in calls)
    stored = writes[0]["web_iq"]
    assert stored["key"].startswith(PREFIX) and stored["client_secret"].startswith(PREFIX)
    assert vault[stored["key"]] == "api-secret"
    assert vault[stored["client_secret"]] == "inactive-secret"
    assert stored["client_id"] == "keep-client" and stored["app_id"] == "keep-app"
    assert not cleanup
    assert current["web_iq"]["key"] == "api-secret"


def test_existing_refs_survive_auth_switch_and_are_not_deleted():
    persist, calls, writes, cleanup, _ = persistence_owner()
    current = settings()
    current["web_iq"].update(key=PREFIX + "saved-key", client_secret=PREFIX + "saved-client")
    updates = {"web_iq": {**current["web_iq"], "authentication_type": "service_principal"}}
    saved = persist(updates, current)
    assert saved and len(calls) == 2
    assert writes[0]["web_iq"]["key"] == current["web_iq"]["key"]
    assert writes[0]["web_iq"]["client_secret"] == current["web_iq"]["client_secret"]
    assert not cleanup


def test_staging_failure_cleans_only_completed_scoped_new_names():
    persist, calls, writes, cleanup, _ = persistence_owner(fail_field="client_secret")
    with pytest.raises(ERROR):
        persist({"web_iq": settings()["web_iq"]}, settings())
    assert not writes
    assert len(cleanup) == 1 and cleanup[0][2:] == ("web-iq", "global")
    assert cleanup[0][0]["auth"] == {"api_key": PREFIX + "s-1"}


@pytest.mark.parametrize("result", [False, RuntimeError("uncertain commit")])
def test_uncertain_settings_publication_retains_staged_credentials(result):
    persist, calls, writes, cleanup, _ = persistence_owner(write_result=result)
    if isinstance(result, Exception):
        with pytest.raises(RuntimeError):
            persist({"web_iq": settings()["web_iq"]}, settings())
    else:
        saved = persist({"web_iq": settings()["web_iq"]}, settings())
        assert not saved
    assert len(writes) == 1 and writes[0]["web_iq"]["key"].startswith(PREFIX)
    assert not cleanup


def test_helper_plaintext_fallback_never_reaches_settings_publication():
    persist, calls, writes, cleanup, _ = persistence_owner(raw_result=True)
    with pytest.raises(ERROR):
        persist({"web_iq": settings()["web_iq"]}, settings())
    assert not writes and not cleanup


def test_foreign_existing_ref_rejected_before_vault_or_settings_effects():
    persist, calls, writes, cleanup, _ = persistence_owner()
    current = settings()
    current["web_iq"]["client_secret"] = "another--model-endpoint--global--secret"
    with pytest.raises(ERROR):
        persist({"web_iq": {**current["web_iq"], "key": "replacement"}}, current)
    assert not calls and not writes and not cleanup


@pytest.mark.parametrize("changes", [
    {"key_vault_name": "different-vault"},
    {"key_vault_identity": "different-identity"},
])
def test_draft_vault_changes_cannot_publish_credentials_staged_to_the_old_context(changes):
    persist, calls, writes, cleanup, _ = persistence_owner()
    with pytest.raises(ERROR):
        persist({"web_iq": settings()["web_iq"], **changes}, settings())
    assert not calls and not writes and not cleanup


def test_obsolete_owned_reference_deleted_only_after_successful_publication():
    persist, calls, writes, cleanup, _ = persistence_owner()
    current = settings()
    current["web_iq"].update(key=PREFIX + "old-key", client_secret=PREFIX + "keep-client")
    saved = persist({"web_iq": {**current["web_iq"], "key": "replacement"}}, current)
    assert saved and len(writes) == 1
    assert cleanup[0][0]["auth"] == {"api_key": PREFIX + "old-key"}
    assert "client_secret" not in cleanup[0][0]["auth"]


def test_real_route_stages_after_validation_and_before_write():
    source = ROUTE.read_text(encoding="utf-8")
    handler = source[source.index("    def v2_admin_patch_settings"):source.index('    @bp.route("/api/v2/admin/settings/test-connection"')]
    assert handler.index("validate_content_screening_settings") < handler.index("_persist_v2_admin_settings")
