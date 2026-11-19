# test_shared_agent_secret_responses.py
"""Shared agent metadata and write-only credential response regressions.

Version: 0.261.432
Implemented in: 0.261.428
Owner-bound runtime integration covered in: 0.261.432

These tests cover legacy group readers, shared global settings and safe edits
without hydrating real credentials or contacting a provider.
"""

from copy import deepcopy

import pytest

from test_support.shared_secret_responses import as_user, environment, seed, shared_routes
from test_workspace_authoring_backend import agent_payload


BASE = "/api/group/agents"


@pytest.mark.parametrize("user", ["owner", "admin", "manager", "member"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_group_reads_never_return_inline_agent_credentials(shared_routes, user, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    saved = seed(
        env, "agents", azure_agent_apim_gpt_subscription_key="CANARY-apim-key",
        azure_apim_gpt_subscription_key="CANARY-legacy-apim-key",
        other_settings={"azure_ai_foundry": {"client_secret": "CANARY-foundry-secret"}},
    )
    before = deepcopy(env.containers["agents", "group"].items)
    as_user(env, user)
    for path in (BASE, f"{BASE}/{saved['id']}"):
        response = env.client.get(path)
        assert response.status_code == 200
        assert "CANARY-" not in response.get_data(as_text=True)
    assert env.containers["agents", "group"].items == before
    assert env.services.secret_reads == []


@pytest.mark.parametrize("user", ["member", "manager", "admin"])
def test_nonmanagers_receive_only_agent_metadata(shared_routes, user):
    env = shared_routes
    env.services.settings["require_owner_for_group_agent_management"] = True
    saved = seed(env, "agents")
    as_user(env, user)
    response = env.client.get(f"{BASE}/{saved['id']}?group_id=group-a")
    assert response.status_code == 200
    result = response.get_json()
    assert result["name"] == saved["name"]
    assert not {"instructions", "other_settings", "azure_openai_gpt_key", "secret_paths", "revision"} & result.keys()
    assert result["read_only"] is True


@pytest.mark.parametrize("path", ["/api/user/agent/settings", "/api/group/agent/settings", "/api/user/agents"])
def test_global_agent_consumers_receive_metadata_not_configuration(shared_routes, path):
    env = shared_routes
    env.services.settings["merge_global_semantic_kernel_with_workspace"] = True
    saved = seed(env, "agents", scope="global", other_settings={
        "new_foundry": {"client_secret": "CANARY-nested-global"},
    })
    env.services.settings["global_selected_agent"] = dict(saved)
    as_user(env, "member")
    response = env.client.get(path)
    assert response.status_code == 200
    assert "CANARY-" not in response.get_data(as_text=True)
    body = response.get_json()
    rows = body["semantic_kernel_agents"] if isinstance(body, dict) else body
    assert len(rows) == 1
    assert rows[0]["name"] == saved["name"]
    assert "other_settings" not in rows[0]
    assert "instructions" not in rows[0]
    if isinstance(body, dict):
        assert "other_settings" not in body["global_selected_agent"]


def test_dedicated_admin_settings_contract_remains_unchanged(shared_routes):
    env = shared_routes
    seed(env, "agents", scope="global")
    with env.app.test_request_context("/api/admin/agent/settings"):
        response = env.routes["get_global_agent_settings"](include_admin_extras=True)
    assert response.get_json()["semantic_kernel_agents"][0]["azure_openai_gpt_key"] == "CANARY-model-key"


def test_agent_manager_response_preserves_safe_reentry_metadata_only(shared_routes):
    env = shared_routes
    saved = seed(env, "agents", **{
        "_agent_credential_bindings": {"private": "CANARY-binding"},
        "credential_reentry_required": [{
            "path": "/azure_openai_gpt_key", "label": "Model API key", "private": "CANARY-extra",
        }],
    })
    response = env.client.get(f"{BASE}/{saved['id']}")
    assert response.status_code == 200
    result = response.get_json()
    assert "_agent_credential_bindings" not in result
    assert result["credential_reentry_required"] == [{
        "path": "/azure_openai_gpt_key", "label": "Azure OpenAI API key",
    }]
    assert "CANARY-" not in response.get_data(as_text=True)


@pytest.mark.parametrize("mode", ["omitted", "mask", "replace", "clear"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_legacy_agent_edits_preserve_or_explicitly_change_credentials(shared_routes, mode, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    saved = seed(env, "agents")
    read = env.client.get(f"{BASE}/{saved['id']}")
    assert read.status_code == 200
    resource = read.get_json()
    body = {"description": "Edited", "expected_revision": resource["revision"]}
    if mode == "mask":
        body["azure_openai_gpt_key"] = resource["azure_openai_gpt_key"]
    elif mode == "replace":
        body["azure_openai_gpt_key"] = "CANARY-replacement"
    elif mode == "clear":
        body["clear_secret_paths"] = ["/azure_openai_gpt_key"]
    response = env.client.patch(f"{BASE}/{saved['id']}", json=body)
    assert response.status_code == 200, (response.get_json(), env.routes["editor_error_response"].call_args)
    assert "CANARY-" not in response.get_data(as_text=True)
    stored = env.containers["agents", "group"].items["group-a", saved["id"]]
    assert stored["description"] == "Edited"
    if mode == "clear":
        assert not stored.get("azure_openai_gpt_key")
    else:
        value = stored["azure_openai_gpt_key"]
        if mode in {"omitted", "mask"}:
            assert value == saved["azure_openai_gpt_key"]
            assert env.services.secret_writes == []
            assert env.services.secret_reads == []
            assert response.get_json()["credential_reentry_required"] == [{
                "path": "/azure_openai_gpt_key", "label": "Azure OpenAI API key",
            }]
        else:
            actual = env.services.vault[value] if vault_enabled else value
            assert actual == "CANARY-replacement"
            assert response.get_json()["credential_reentry_required"] == []


@pytest.mark.parametrize("user,roles", [
    ("outsider", ["User"]), ("foreign", ["User"]), ("outsider", ["Admin"]),
])
def test_unrelated_callers_cannot_read_group_agents(shared_routes, user, roles):
    env = shared_routes
    saved = seed(env, "agents")
    as_user(env, user, roles)
    for path in (BASE, f"{BASE}/{saved['id']}"):
        response = env.client.get(path + "?group_id=group-a")
        assert response.status_code == 403
        assert "CANARY-" not in response.get_data(as_text=True)


@pytest.mark.parametrize("user", ["member", "manager", "admin"])
def test_nonmanagers_cannot_write_group_agents(shared_routes, user):
    env = shared_routes
    env.services.settings["require_owner_for_group_agent_management"] = True
    saved = seed(env, "agents")
    as_user(env, user)
    for method, path in (("post", BASE), ("patch", f"{BASE}/{saved['id']}")):
        response = getattr(env.client, method)(path + "?group_id=group-a", json={"description": "Not authorized"})
        assert response.status_code == 403


def test_agent_lookup_rejects_another_groups_id(shared_routes):
    env = shared_routes
    saved = seed(env, "agents", group_id="group-b")
    response = env.client.get(f"{BASE}/{saved['id']}?group_id=group-a")
    assert response.status_code == 404


def test_empty_global_selection_stays_empty(shared_routes):
    env = shared_routes
    env.services.settings["global_selected_agent"] = {}
    response = env.client.get("/api/user/agent/settings")
    assert response.status_code == 200
    assert response.get_json()["global_selected_agent"] == {}


def test_legacy_projection_preserves_native_reentry_envelope(shared_routes, monkeypatch):
    env = shared_routes
    saved = seed(env, "agents")
    original = env.helper.editor_resource
    required = [{"path": "/azure_openai_gpt_key", "label": "Model API key"}]

    def resource_with_reentry(*args, **kwargs):
        return {**original(*args, **kwargs), "credential_reentry_required": required}

    monkeypatch.setattr(env.helper, "editor_resource", resource_with_reentry)
    response = env.client.get(f"{BASE}/{saved['id']}")
    assert response.status_code == 200
    assert response.get_json()["credential_reentry_required"] == required


def test_cleaned_agent_rows_retain_the_backend_readiness_state(shared_routes, monkeypatch):
    env = shared_routes
    row = {
        "id": "bound-agent", "name": "bound_agent", "group_id": "group-a",
        "azure_openai_gpt_key": "***REDACTED***", "credential_reentry_required": [],
    }
    original = env.helper.editor_resource

    def raw_record_readiness(*args, **kwargs):
        return {**original(*args, **kwargs), "credential_reentry_required": [{
            "path": "/azure_openai_gpt_key", "label": "Model API key",
        }]}

    with monkeypatch.context() as scoped:
        scoped.setattr(env.helper, "editor_resource", raw_record_readiness)
        result = env.helper.project_shared_record(row, "agents", can_manage=True, group_scope=True)
    assert result["credential_reentry_required"] == []


@pytest.mark.parametrize("bound", [False, True])
def test_shared_agent_raw_and_cleaned_projections_keep_real_runtime_readiness(shared_routes, bound):
    env = shared_routes
    saved = seed(env, "agents")
    if bound:
        saved = env.keyvault.keyvault_agent_save_helper(
            saved, saved["id"], scope="group", owner_id="group-a",
        )
    raw = env.helper.project_shared_record(saved, "agents", can_manage=True, group_scope=True)
    cleaned = env.routes["_clean_agent"](saved, "group-a")
    projected = env.helper.project_shared_record(cleaned, "agents", can_manage=True, group_scope=True)
    expected = [] if bound else [{
        "path": "/azure_openai_gpt_key", "label": "Azure OpenAI API key",
    }]
    assert raw["credential_reentry_required"] == expected
    assert projected["credential_reentry_required"] == expected
    assert "_agent_credential_bindings" not in raw
    assert "_agent_credential_bindings" not in projected
    assert "CANARY-" not in str(raw)
    assert "CANARY-" not in str(projected)
    assert env.services.secret_reads == []


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_created_agent_response_is_write_only(shared_routes, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    response = env.client.post(BASE + "?group_id=group-a", json={
        "name": "new_shared_agent", "display_name": "New shared agent", "description": "",
        "instructions": "Be helpful.", "agent_type": "local", "actions_to_load": [], "other_settings": {},
        "azure_openai_gpt_endpoint": "https://fixture.openai.azure.com",
        "azure_openai_gpt_deployment": "gpt-4o", "azure_openai_gpt_api_version": "2024-10-21",
        "azure_openai_gpt_key": "CANARY-created-agent",
    })
    assert response.status_code == 201, (response.get_json(), env.routes["editor_error_response"].call_args)
    assert "CANARY-" not in response.get_data(as_text=True)
    assert response.get_json()["azure_openai_gpt_key"] == "***REDACTED***"
    assert response.get_json()["revision"]
    assert response.headers["Cache-Control"] == "no-store"


def test_existing_legacy_agent_id_survives_rename_and_masked_save(shared_routes):
    env = shared_routes
    saved = seed(env, "agents", id="legacy-group-agent")
    read = env.client.get(f"{BASE}/{saved['id']}")
    assert read.status_code == 200
    body = read.get_json()
    body["name"] = "renamed_legacy_agent"
    response = env.client.patch(f"{BASE}/{saved['id']}", json=body)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["id"] == "legacy-group-agent"
    assert result["name"] == "renamed_legacy_agent"
    assert result["azure_openai_gpt_key"] == "***REDACTED***"


def test_legacy_id_compatibility_does_not_weaken_new_ids_or_other_fields(shared_routes):
    env = shared_routes
    payload = agent_payload()
    payload.update(id="legacy-group-agent", is_global=False, is_group=True)
    strict_error = env.schema.validate_agent(payload)
    unchanged_error = env.schema.validate_agent(payload, existing_id=payload["id"])
    changed_error = env.schema.validate_agent(payload, existing_id="different-agent")
    invalid_error = env.schema.validate_agent({**payload, "instructions": 42}, existing_id=payload["id"])
    assert strict_error is not None
    assert unchanged_error is None
    assert changed_error is not None
    assert invalid_error is not None
