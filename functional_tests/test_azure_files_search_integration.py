#!/usr/bin/env python3
# test_azure_files_search_integration.py
"""
Functional test for Azure Files Search action integration with SimpleChat.
Version: 0.261.294
Implemented in: 0.261.294

This test ensures that the Azure Files Search action (type azure_files_index) is discovered and
matched by the action loader without colliding with Document Search, validated by the plugin
health checker, refused outside global scope at run time, wired to its search, file permission,
share, and identity dependencies, and that withheld results are recorded only for administrators:
an activity log entry when files are withheld and a deduplicated admin notification when files
could not be verified. It also checks the Control Center, route, schema, and notification wiring.
"""

import ast
import contextlib
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
FUNCTIONAL_TESTS_ROOT = REPO_ROOT / "functional_tests"
for _path in (str(APP_ROOT), str(FUNCTIONAL_TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_support.versioning import assert_app_version_at_least  # noqa: E402

SUBSCRIPTION = "11111111-2222-3333-4444-555555555555"
ACCOUNT_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-files/providers/Microsoft.Storage/storageAccounts/finfiles"
USER_SID = "S-1-12-1-1943430372-1249052806-2496021943-3034400218"


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _purge_cached_application_modules():
    """Drop cached application modules and stub-only azure modules other tests may have left behind.

    The caller restores its sys.modules snapshot afterwards, so other tests keep what they had.
    """
    application_modules = {path.stem for path in APP_ROOT.glob("*.py")} | {"semantic_kernel_plugins"}
    for name, module in list(sys.modules.items()):
        top_level = name.split(".")[0]
        if top_level in application_modules or (top_level == "azure" and getattr(module, "__spec__", None) is None):
            del sys.modules[name]


@contextlib.contextmanager
def _application_modules():
    """Import application modules against a stub config.py, then restore sys.modules."""
    saved_modules = dict(sys.modules)
    _purge_cached_application_modules()
    config_stub = types.ModuleType("config")
    config_stub._is_test_stub = True
    for node in ast.walk(ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))):
        names = []
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [(alias.asname or alias.name).split(".")[0] for alias in node.names if alias.name != "*"]
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        for name in names:
            if hasattr(config_stub, name):
                continue
            try:
                setattr(config_stub, name, __import__(name))
            except Exception:
                setattr(config_stub, name, MagicMock(name=f"config.{name}"))
    config_stub.AZURE_ENVIRONMENT = "public"
    config_stub.resource_manager = "https://management.azure.com"
    config_stub.search_resource_manager = "https://search.azure.com"
    sys.modules["config"] = config_stub
    try:
        import functions_activity_logging
        import functions_azure_files_search_runtime as runtime
        import functions_notifications
        from semantic_kernel_plugins import azure_files_index_plugin
        from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker

        yield types.SimpleNamespace(
            runtime=runtime,
            plugin_module=azure_files_index_plugin,
            health_checker=PluginHealthChecker,
            activity_logging=functions_activity_logging,
            notifications=functions_notifications,
        )
    finally:
        for name in list(sys.modules):
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)


@pytest.fixture(scope="module")
def app():
    with _application_modules() as modules:
        yield modules


@contextlib.contextmanager
def _replaced(target, name, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


@contextlib.contextmanager
def _injected_module(name, **attributes):
    saved = sys.modules.get(name)
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    try:
        yield module
    finally:
        if saved is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved


def _manifest(**fields):
    additional = {
        "index_name": "finance-files",
        "storage_shares": [{"storage_account_resource_id": ACCOUNT_ID, "share_name": "docs"}],
    }
    additional.update(fields)
    return {
        "id": "action-1",
        "name": "finance_files",
        "displayName": "Finance files",
        "type": "azure_files_index",
        "endpoint": "https://contoso-search.search.windows.net",
        "auth": {"type": "identity", "identity": "managed_identity"},
        "additionalFields": additional,
    }


def _global(manifest):
    """Bind the origin that the authorized global-action lookup attaches at run time."""
    from functions_action_manifest import bind_action_origin

    return bind_action_origin(manifest, "global", "global")


def _normalize(value):
    return value.replace("_", "").replace("-", "").replace("plugin", "").lower() if value else ""


def test_version():
    assert_app_version_at_least("0.261.294")


def test_plugin_metadata_and_loader_matching(app):
    plugin = app.plugin_module.AzureFilesIndexPlugin({})
    assert plugin.display_name == "Azure Files Search"
    assert plugin.metadata["type"] == "azure_files_index"
    assert plugin.get_functions() == ["search_files"]
    # The loader matches a manifest type to a class by normalized substring. The new class must
    # match its own type and must not capture the legacy Document Search "search" type.
    class_name = _normalize("AzureFilesIndexPlugin")
    assert _normalize("azure_files_index") in class_name
    for other_type in ("search", "document_search", "blob_storage", "cosmos_query", "text", "time", "math", "agent"):
        assert _normalize(other_type) not in class_name, other_type
    assert (APP_ROOT / "semantic_kernel_plugins" / "azure_files_index_plugin.py").is_file()


def test_health_checker_validates_configuration(app):
    valid, errors = app.health_checker.validate_plugin_manifest(_manifest(), "azure_files_index")
    assert valid, errors
    invalid, errors = app.health_checker.validate_plugin_manifest(
        {**_manifest(), "endpoint": "https://attacker.invalid"}, "azure_files_index",
    )
    assert not invalid and any("Azure AI Search" in error for error in errors)
    wrong_auth, errors = app.health_checker.validate_plugin_manifest(
        {**_manifest(), "auth": {"type": "connection_string", "key": "x"}}, "azure_files_index",
    )
    assert not wrong_auth


def test_runtime_refuses_unsafe_invocations(app):
    from functions_action_manifest import bind_action_origin

    runtime = app.runtime
    signed_out = runtime.execute_azure_files_search(_global(_manifest()), "budget", None, None, {})
    assert signed_out["results"] == [] and signed_out["error"] == runtime.SIGNED_OUT_MESSAGE
    for scope_type, scope_id in (("personal", "user-1"), ("group", "group-1")):
        scoped = bind_action_origin(_manifest(), scope_type, scope_id)
        refused = runtime.execute_azure_files_search(scoped, "budget", None, "user-1", {})
        assert refused["error"] == runtime.MISCONFIGURED_MESSAGE
    with _replaced(runtime, "_run_search_for", lambda config: pytest.fail("an unbound manifest must not reach the index")):
        unbound = runtime.execute_azure_files_search(_manifest(), "budget", None, "user-1", {})
    assert unbound["error"] == runtime.MISCONFIGURED_MESSAGE
    broken = runtime.execute_azure_files_search(
        _global({**_manifest(), "endpoint": "https://x.invalid"}), "q", None, "user-1", {},
    )
    assert broken["error"] == runtime.MISCONFIGURED_MESSAGE
    internal = runtime.execute_azure_files_search(
        _global(_manifest(index_name="simplechat-user-index")), "q", None, "user-1",
        {"azure_ai_search_endpoint": "https://contoso-search.search.windows.net"},
    )
    assert internal["error"] == runtime.MISCONFIGURED_MESSAGE


def test_user_membership_honors_builtin_users_flag(app):
    import functions_azure_files_acl as acl
    import functions_azure_files_search as afs
    from functions_azure_files_access import UserPrincipals

    runtime = app.runtime
    principals = UserPrincipals(user_id="user-1", sids=frozenset({USER_SID}), group_ids=frozenset())
    with _replaced(runtime, "get_valid_access_token", lambda: "token"), \
            _replaced(runtime, "get_graph_base_url", lambda: "https://graph"), \
            _replaced(runtime, "get_user_principals", lambda user_id, token, base: principals):
        opted_in = afs.normalize_azure_files_search_config(_manifest(treat_builtin_users_as_member=True))
        membership, reason = runtime.build_user_membership(opted_in, "user-1")
        assert reason == "" and membership(acl.BUILTIN_USERS_SID) == acl.MEMBER and membership(USER_SID) == acl.MEMBER
        default = afs.normalize_azure_files_search_config(_manifest())
        membership, _reason = runtime.build_user_membership(default, "user-1")
        assert membership(acl.BUILTIN_USERS_SID) == acl.UNKNOWN
    with _replaced(runtime, "get_valid_access_token", lambda: None):
        assert runtime.build_user_membership(default, "user-1") == (None, "identity_unavailable")


def test_review_is_recorded_only_for_withheld_files(app):
    import functions_azure_files_search as afs

    runtime = app.runtime
    config = afs.normalize_azure_files_search_config(_manifest())
    logged, notified = [], []
    with _injected_module("functions_activity_logging", log_azure_files_search_access=lambda **kwargs: logged.append(kwargs)), \
            _injected_module("functions_notifications", create_notification=lambda **kwargs: notified.append(kwargs)):
        runtime.record_azure_files_search_review(config, "user-1", afs.AzureFilesSearchOutcome(results=[{"file_name": "a"}], allowed_files=1, files_evaluated=1))
        assert logged == [] and notified == []
        runtime.record_azure_files_search_review(config, "user-1", afs.AzureFilesSearchOutcome(results=[], denied_files=1, files_evaluated=1))
        assert len(logged) == 1 and notified == []
        assert logged[0]["review"]["status"] == "denied"
        runtime.record_azure_files_search_review(config, "user-1", afs.AzureFilesSearchOutcome(results=[], unverified_files=2, files_evaluated=2, reasons={"sid_unresolved": 2}))
        assert len(logged) == 2 and len(notified) == 1
    notice = notified[0]
    assert notice["notification_type"] == "azure_files_search_access_unverified"
    assert notice["assignment"] == {"roles": ["Admin"]}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert notice["idempotency_key"] == f"azure-files-search-unverified:action-1:{today}"
    assert "withheld" in notice["message"] and "budget" not in json.dumps(notice)


def test_activity_log_record_has_no_content_or_query(app):
    container = app.activity_logging.cosmos_activity_logs_container
    container.create_item.reset_mock()
    review = {
        "action_id": "action-1", "action_name": "finance_files", "display_name": "Finance files",
        "search_service": "contoso-search.search.windows.net", "index_name": "finance-files",
        "permission_mode": "live_acl", "share_access_check": "rbac", "status": "unverified",
        "counts": {"candidates": 5, "files_evaluated": 4, "allowed_files": 1, "denied_files": 1, "unverified_files": 2, "results_returned": 1},
        "reasons": {"acl_no_allow": 1, "sid_unresolved": 2},
        "withheld_files": [{"file": "\\\\finfiles.file.core.windows.net\\docs\\merger.txt", "outcome": "unverified", "reason": "sid_unresolved"}],
        "withheld_files_truncated": False,
        "duration_ms": 120,
        "conversation_id": "conversation-1",
        "agent": {"id": "agent-1", "name": "finance_agent", "display_name": "Finance agent"},
    }
    app.activity_logging.log_azure_files_search_access(user_id="user-1", review=review)
    body = container.create_item.call_args.kwargs["body"]
    assert body["activity_type"] == "azure_files_search_access" and body["user_id"] == "user-1"
    assert body["description"] == "Azure Files Search withheld 3 of 4 files (1 denied, 2 unverified)"
    assert body["action_context"]["index_name"] == "finance-files"
    assert body["additional_context"]["reasons"] == {"acl_no_allow": 1, "sid_unresolved": 2}
    assert body["conversation_id"] == "conversation-1"
    assert body["agent"] == {"id": "agent-1", "name": "finance_agent", "display_name": "Finance agent"}
    assert "query" not in json.dumps(body)


def test_review_records_the_invoking_agent_and_conversation(app):
    import functions_azure_files_search as afs
    from flask import Flask, g

    runtime = app.runtime
    config = afs.normalize_azure_files_search_config(_manifest())
    outcome = afs.AzureFilesSearchOutcome(results=[], denied_files=1, files_evaluated=1)
    logged = []
    flask_app = Flask("azure_files_review_context")
    with _injected_module("functions_activity_logging", log_azure_files_search_access=lambda **kwargs: logged.append(kwargs)), \
            _injected_module("functions_notifications", create_notification=lambda **kwargs: None):
        runtime.record_azure_files_search_review(config, "user-1", outcome)
        assert logged[-1]["review"]["conversation_id"] == "" and logged[-1]["review"]["agent"] is None
        with flask_app.test_request_context("/"):
            g.conversation_id = "conversation-1"
            g.request_agent_name = "finance_agent"
            g.request_agent_info = {
                "id": "agent-1", "name": "finance_agent", "display_name": "Finance agent",
                "instructions": "Never copy agent configuration into the review.",
            }
            runtime.record_azure_files_search_review(config, "user-1", outcome)
            review = logged[-1]["review"]
            assert review["conversation_id"] == "conversation-1"
            assert review["agent"] == {"id": "agent-1", "name": "finance_agent", "display_name": "Finance agent"}
            assert "Never copy" not in json.dumps(review)
            frame = types.SimpleNamespace(identity=types.SimpleNamespace(conversation_id="conversation-frame"))
            with _replaced(runtime, "current_agent_execution", lambda: frame):
                runtime.record_azure_files_search_review(config, "user-1", outcome)
            assert logged[-1]["review"]["conversation_id"] == "conversation-frame"
            g.request_agent_info = None
            runtime.record_azure_files_search_review(config, "user-1", outcome)
            assert logged[-1]["review"]["agent"] == {"id": "", "name": "finance_agent", "display_name": "finance_agent"}


def test_execute_wires_dependencies_and_returns_only_allowed_files(app):
    import functions_azure_files_acl as acl

    runtime = app.runtime
    hits = [
        {"metadata_storage_path": "https://finfiles.file.core.windows.net/docs/allowed.txt", "metadata_storage_name": "allowed.txt", "@search.highlights": {"content": ["allowed text"]}},
        {"metadata_storage_path": "https://finfiles.file.core.windows.net/docs/secret.txt", "metadata_storage_name": "secret.txt", "@search.highlights": {"content": ["secret text"]}},
    ]
    sddl = {
        "allowed.txt": f"O:BAG:SYD:(A;;FR;;;{USER_SID})",
        "secret.txt": "O:BAG:SYD:(A;;FR;;;S-1-5-21-1-2-3-1500)",
    }
    reviews = []
    membership = acl.build_membership([USER_SID])
    with _replaced(runtime, "_run_search_for", lambda config: (lambda request: hits)), \
            _replaced(runtime, "read_file_sddl", lambda path: sddl[path.relative_path]), \
            _replaced(runtime, "_check_share_access_for", lambda user_id: (lambda share: (acl.MEMBER, "share_role_assignment"))), \
            _replaced(runtime, "build_user_membership", lambda config, user_id: (membership, "")), \
            _replaced(runtime, "record_azure_files_search_review", lambda config, user_id, outcome: reviews.append(outcome)):
        response = runtime.execute_azure_files_search(_global(_manifest()), "text", None, "user-1", {})
    assert [result["file_name"] for result in response["results"]] == ["allowed.txt"]
    assert "secret" not in json.dumps(response)
    assert reviews[0].unverified_files == 1


def test_connection_check_reports_actionable_failures(app):
    runtime = app.runtime

    def denied(config):
        def run(request):
            raise runtime.AzureFilesSearchUnavailable("search_access_denied", "Give SimpleChat's managed identity the Search Index Data Reader role.")
        return run

    with _replaced(runtime, "_run_search_for", denied):
        result = runtime.check_azure_files_search_connection(_manifest(), "admin-1", {})
    assert not result["success"]
    assert result["checks"][-1]["name"] == "search_access" and "Search Index Data Reader" in result["checks"][-1]["message"]

    hits = [{"metadata_storage_path": "https://finfiles.file.core.windows.net/docs/a.txt", "metadata_storage_name": "a.txt"}]

    def unreadable(path):
        raise RuntimeError("AuthorizationPermissionMismatch")

    import functions_azure_files_acl as acl

    with _replaced(runtime, "_run_search_for", lambda config: (lambda request: hits)), \
            _replaced(runtime, "build_user_membership", lambda config, user_id: (lambda sid: acl.UNKNOWN, "")), \
            _replaced(runtime, "_check_share_access_for", lambda user_id: (lambda share: (acl.MEMBER, "share_role_assignment"))), \
            _replaced(runtime, "read_file_sddl", unreadable):
        result = runtime.check_azure_files_search_connection(_manifest(), "admin-1", {})
    failures = {check["name"]: check["message"] for check in result["checks"] if check["status"] == "fail"}
    assert not result["success"]
    assert "Storage File Data Privileged Reader" in failures["file_permissions:finfiles/docs"]
    assert "AuthorizationPermissionMismatch" not in json.dumps(result)


def test_control_center_csv_formatter():
    source = _read("application/single_app/route_backend_control_center.py")
    function_node = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "format_activity_log_details_for_csv"
    )
    namespace = {}
    exec(compile(ast.Module(body=[function_node], type_ignores=[]), "formatter", "exec"), namespace)
    text = namespace["format_activity_log_details_for_csv"]({
        "activity_type": "azure_files_search_access",
        "action_context": {"display_name": "Finance files", "index_name": "finance-files"},
        "additional_context": {"counts": {"denied_files": 1, "unverified_files": 2, "files_evaluated": 4}, "reasons": {"sid_unresolved": 2}},
    })
    assert text == (
        "Action: Finance files; Index: finance-files; Agent: N/A; Conversation: N/A; "
        "Denied: 1; Unverified: 2; Files checked: 4; Reasons: sid_unresolved: 2"
    )
    with_context = namespace["format_activity_log_details_for_csv"]({
        "activity_type": "azure_files_search_access",
        "conversation_id": "conversation-1",
        "agent": {"id": "agent-1", "name": "finance_agent", "display_name": "Finance agent"},
        "action_context": {"display_name": "Finance files", "index_name": "finance-files"},
        "additional_context": {"counts": {"denied_files": 1, "unverified_files": 0, "files_evaluated": 2}, "reasons": {"acl_no_allow": 1}},
    })
    assert "Agent: Finance agent; Conversation: conversation-1;" in with_context


def test_v1_control_center_and_notification_wiring(app):
    template = _read("application/single_app/templates/control_center.html")
    script = _read("application/single_app/static/js/control-center.js")
    assert '<option value="azure_files_search_access">Azure Files Search Access</option>' in template
    assert "'azure_files_search_access': 'Azure Files Search Access'" in script
    assert script.count("case 'azure_files_search_access'") == 3
    for notification_type in ("file_sync_run_failed", "azure_files_search_access_unverified"):
        assert notification_type in app.notifications.NOTIFICATION_TYPES
        assert f"type === '{notification_type}'" in _read("application/v2_ui/src/lib/notifications.ts")


def test_routes_and_type_filters():
    plugins_routes = _read("application/single_app/route_backend_plugins.py")
    route_block = plugins_routes.split("@bpap.route('/api/plugins/test-azure-files-index-connection'", 1)[1].split("def ", 1)[0]
    assert "@swagger_route(security=get_auth_security())" in route_block
    assert "@login_required" in route_block and "@admin_required" in route_block
    assert "raise PermissionError('Azure Files Search actions are global actions.')" in plugins_routes
    assert plugins_routes.count("not is_global_only_action_type(action_type)") == 3
    for prepare_name in ("_prepare_personal_action_payload", "_prepare_group_action_payload"):
        prepare_block = plugins_routes.split(f"def {prepare_name}(", 1)[1].split("\ndef ", 1)[0]
        assert "if is_global_only_action_type(plugin_type):" in prepare_block, prepare_name
        assert "GlobalOnlyActionTypeError.public_message}), 403)" in prepare_block, prepare_name
    global_block = plugins_routes.split("def _prepare_global_action_payload(", 1)[1].split("\ndef ", 1)[0]
    assert "validate_azure_files_index_action(plugin_to_save, settings)" in global_block
    scoped = _read("application/single_app/route_backend_group_actions_scoped.py")
    assert "not is_global_only_action_type(action_type)" in scoped
    assert "validate_azure_files_index_action(action_data, get_settings())" in _read("application/single_app/functions_global_actions.py")


def test_schema_files_match_configuration():
    schema_dir = APP_ROOT / "static" / "json" / "schemas"
    definition = json.loads((schema_dir / "azure_files_index.definition.json").read_text(encoding="utf-8"))
    assert definition["allowedAuthTypes"] == ["identity", "key"]
    settings_schema = json.loads((schema_dir / "azure_files_index_plugin.additional_settings.schema.json").read_text(encoding="utf-8"))
    used_keys = set(re.findall(r'fields\.get\("([a-z_]+)"', _read("application/single_app/functions_azure_files_search.py")))
    used_keys.update(re.findall(r'configured\("([a-z_]+)"\)', _read("application/single_app/functions_azure_files_search.py")))
    assert used_keys <= set(settings_schema["properties"]), sorted(used_keys - set(settings_schema["properties"]))
    assert settings_schema["required"] == ["index_name"] and settings_schema["additionalProperties"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
