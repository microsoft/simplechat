# test_agent_credential_reentry.py
"""Agent credential re-entry and destination selection regressions.

Version: 0.261.428
Implemented in: 0.261.428

The real persistence helpers run in the SDK-backed owner fixture. Selected
runtime function bodies avoid cloud bootstrap, not the credential boundary.
"""

import ast
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent_credential_contracts import (
    AGENT_CREDENTIAL_BINDINGS, AGENT_CREDENTIAL_STATUS,
    AgentCredentialReentryRequired, agent_credential_is_ready,
)
from functions_agent_payload import can_agent_use_default_multi_endpoint_model, sanitize_agent_payload
from functions_model_endpoint_urls import resolve_model_inference_endpoint
from test_workspace_authoring_backend import environment


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
PATH = ("azure_openai_gpt_key",)
OWNER = "owner-a"


def manifest(**updates):
    result = {
        "id": "agent-a", "name": "agent_a", "user_id": OWNER, "agent_type": "local",
        "azure_openai_gpt_endpoint": "https://owned.example.test",
        "azure_openai_gpt_key": "new-credential",
        "azure_openai_gpt_deployment": "model-a",
        "azure_openai_gpt_api_version": "2024-02-01",
    }
    result.update(updates)
    return result


def runtime(environment, stored):
    env = environment
    namespace = {
        "debug_print": Mock(), "log_event": Mock(),
        "get_execution_user_id": lambda: OWNER,
        "get_current_user_id_or_none": lambda: OWNER,
        "get_user_settings": lambda _: {"settings": {}},
        "get_personal_agent": Mock(return_value=deepcopy(stored)),
        "get_group_agent": Mock(return_value=deepcopy(stored)),
        "get_global_agent": Mock(return_value=deepcopy(stored)),
        "assert_group_role": Mock(), "ensure_governance_access": Mock(),
        "SecretReturnType": env.keyvault.SecretReturnType,
        "keyvault_agent_get_helper": env.keyvault.keyvault_agent_get_helper,
        "AgentCredentialReentryRequired": AgentCredentialReentryRequired,
        "can_agent_use_default_multi_endpoint_model": can_agent_use_default_multi_endpoint_model,
        "resolve_model_inference_endpoint": resolve_model_inference_endpoint,
        "validate_secret_name_dynamic": env.keyvault.validate_secret_name_dynamic,
        "retrieve_secret_from_key_vault_by_full_name": Mock(side_effect=AssertionError("Unscoped retrieval")),
        "first_if_comma": lambda value: value,
    }
    tree = ast.parse((APP / "semantic_kernel_loader.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "resolve_agent_config")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP / "semantic_kernel_loader.py"), "exec"), namespace)
    return namespace


def settings(env):
    return {
        **env.services.settings, "per_user_semantic_kernel": True,
        "allow_user_custom_endpoints": True, "allow_group_custom_endpoints": True,
        "azure_openai_gpt_endpoint": "https://approved.example.test",
        "azure_openai_gpt_key": "global-secret",
        "azure_openai_gpt_deployment": "global-model",
        "azure_openai_gpt_api_version": "2024-02-01",
    }


def test_partial_custom_destination_never_borrows_global_credential(environment):
    stored = manifest(azure_openai_gpt_key="")
    ns = runtime(environment, stored)
    with pytest.raises(AgentCredentialReentryRequired):
        ns["resolve_agent_config"](stored, settings(environment))
    ns["retrieve_secret_from_key_vault_by_full_name"].assert_not_called()


def test_inactive_foreign_key_is_never_resolved(environment):
    stored = manifest(enable_agent_gpt_apim=True, azure_openai_gpt_key="foreign--action--user--sample")
    ns = runtime(environment, stored)
    with pytest.raises(AgentCredentialReentryRequired):
        ns["resolve_agent_config"](stored, settings(environment))
    ns["retrieve_secret_from_key_vault_by_full_name"].assert_not_called()


def test_revoked_group_membership_blocks_credential_and_model_lookup(environment):
    stored = manifest(is_group=True, group_id="group-a")
    ns = runtime(environment, stored)
    ns["assert_group_role"].side_effect = PermissionError("Revoked membership")
    with pytest.raises(PermissionError):
        ns["resolve_agent_config"](stored, settings(environment))
    ns["get_group_agent"].assert_not_called()
    ns["retrieve_secret_from_key_vault_by_full_name"].assert_not_called()


def test_group_context_cannot_rebind_an_agent_from_another_group(environment):
    stored = manifest(is_group=True, group_id="group-a")
    ns = runtime(environment, stored)
    with pytest.raises(PermissionError):
        ns["resolve_agent_config"](stored, settings(environment), group_scope_id="group-b")
    ns["get_group_agent"].assert_not_called()


def test_reentry_uses_authoritative_record_destination_not_caller_override(environment):
    stored = environment.keyvault.keyvault_agent_save_helper(
        manifest(), "agent-a", scope="user", owner_id=OWNER,
    )
    ns = runtime(environment, stored)
    proposed = {**stored, "azure_openai_gpt_endpoint": "https://different.example.test"}
    resolved = ns["resolve_agent_config"](proposed, settings(environment))
    assert resolved["endpoint"] == "https://owned.example.test"
    assert resolved["key"] == "new-credential"
    assert resolved["token_provider"] is None
    assert "azure_openai_gpt_key" not in resolved
    assert AGENT_CREDENTIAL_BINDINGS not in resolved


def test_approved_default_keeps_its_own_endpoint_and_credential(environment):
    stored = {"id": "no-overrides", "name": "default_agent", "azure_openai_gpt_deployment": "chosen-model"}
    ns = runtime(environment, stored)
    resolved = ns["resolve_agent_config"](stored, settings(environment))
    assert resolved["endpoint"] == "https://approved.example.test"
    assert resolved["key"] == "global-secret"
    assert resolved["deployment"] == "chosen-model"
    ns["get_personal_agent"].assert_not_called()


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_editor_unrelated_edit_keeps_legacy_credentials_quarantined(environment, vault_enabled):
    env = environment
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    old = manifest()
    proposed = deepcopy(old)
    staged = []
    env.helper._stage_editor_secrets(
        proposed, "agents", OWNER, env.services.settings, staged, existing=old,
        credential_updates={"description": "Unrelated change"},
    )
    assert not proposed.get(AGENT_CREDENTIAL_BINDINGS)
    assert not staged
    assert proposed["azure_openai_gpt_key"] == old["azure_openai_gpt_key"]
    resource = env.helper.editor_resource(proposed, "agents")
    assert resource[AGENT_CREDENTIAL_STATUS][0]["label"] == "Azure OpenAI API key"


def test_editor_explicit_reentry_of_same_literal_establishes_new_binding(environment):
    env = environment
    old = manifest()
    proposed = deepcopy(old)
    env.helper._stage_editor_secrets(
        proposed, "agents", OWNER, env.services.settings, [], existing=old,
        credential_updates={"azure_openai_gpt_key": "new-credential"},
    )
    assert agent_credential_is_ready(proposed, PATH, "user", OWNER)


def test_client_cannot_set_readiness_metadata():
    record = manifest()
    record[AGENT_CREDENTIAL_BINDINGS] = {"/azure_openai_gpt_key": "forged"}
    record[AGENT_CREDENTIAL_STATUS] = []
    cleaned = sanitize_agent_payload(record)
    assert AGENT_CREDENTIAL_BINDINGS not in cleaned
    assert AGENT_CREDENTIAL_STATUS not in cleaned
