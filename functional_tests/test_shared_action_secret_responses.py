# test_shared_action_secret_responses.py
"""Shared action response and credential-preservation regressions.

Version: 0.261.428
Implemented in: 0.261.428

Real legacy routes, authentication, membership checks and authoring helpers run
against SDK-default conditional Cosmos containers and an isolated Key Vault.
"""

from copy import deepcopy

import pytest

from test_support.shared_secret_responses import as_user, environment, seed, shared_routes


BASE = "/api/group/plugins"


@pytest.mark.parametrize("user", ["owner", "admin", "manager", "member"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_group_reads_never_return_inline_action_credentials(shared_routes, user, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    saved = seed(env, "actions", additionalFields={
        "password": "CANARY-sql-password", "connection_string": "CANARY-connection",
        "custom__Secret": "CANARY-custom",
    })
    before = deepcopy(env.containers["actions", "group"].items)
    as_user(env, user)
    for path in (BASE, f"{BASE}/{saved['id']}", f"{BASE}/{saved['name']}"):
        response = env.client.get(path)
        assert response.status_code == 200
        assert "CANARY-" not in response.get_data(as_text=True)
    assert env.containers["actions", "group"].items == before
    assert env.services.secret_reads == []


@pytest.mark.parametrize("user", ["manager", "member", "admin"])
def test_nonmanagers_receive_only_action_metadata(shared_routes, user):
    env = shared_routes
    env.services.settings["require_owner_for_group_agent_management"] = True
    saved = seed(env, "actions", metadata={"internal": "CANARY-metadata"})
    as_user(env, user)
    response = env.client.get(f"{BASE}/{saved['id']}?group_id=group-a")
    assert response.status_code == 200
    result = response.get_json()
    assert result["id"] == saved["id"]
    assert result["name"] == saved["name"]
    assert result["description"] == saved["description"]
    assert not {"auth", "additionalFields", "metadata", "endpoint", "secret_paths", "revision"} & result.keys()
    assert result["read_only"] is True


@pytest.mark.parametrize("user,roles", [
    ("outsider", ["User"]), ("foreign", ["User"]), ("outsider", ["Admin"]),
])
def test_unrelated_callers_cannot_read_group_actions(shared_routes, user, roles):
    env = shared_routes
    saved = seed(env, "actions")
    as_user(env, user, roles)
    for path in (BASE, f"{BASE}/{saved['id']}"):
        response = env.client.get(path + "?group_id=group-a")
        assert response.status_code == 403
        assert "CANARY-" not in response.get_data(as_text=True)


def test_shared_global_actions_are_metadata_only_in_both_lists(shared_routes):
    env = shared_routes
    env.services.settings["merge_global_semantic_kernel_with_workspace"] = True
    seed(env, "actions", scope="global")
    for path in (BASE, "/api/user/plugins"):
        response = env.client.get(path)
        assert response.status_code == 200
        rows = response.get_json()["actions"] if path == BASE else response.get_json()
        assert len(rows) == 1
        assert rows[0]["is_global"] is True
        assert "auth" not in rows[0]
        assert "endpoint" not in rows[0]
        assert "CANARY-" not in response.get_data(as_text=True)


@pytest.mark.parametrize("mode", ["omitted", "mask", "replace", "clear"])
@pytest.mark.parametrize("vault_enabled", [False, True])
def test_legacy_action_edits_preserve_or_explicitly_change_credentials(shared_routes, mode, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    saved = seed(env, "actions")
    read = env.client.get(f"{BASE}/{saved['id']}")
    assert read.status_code == 200
    resource = read.get_json()
    body = {"description": "Edited", "expected_revision": resource["revision"]}
    if mode == "mask":
        body["auth"] = {"type": "key", "key": resource["auth"]["key"]}
    elif mode == "replace":
        body["auth"] = {"type": "key", "key": "CANARY-replacement"}
    elif mode == "clear":
        body.update({
            "auth": {"type": "key", "key": ""}, "additionalFields": {"auth_method": "none"},
            "clear_secret_paths": ["/auth/key"],
        })
    response = env.client.patch(f"{BASE}/{saved['id']}", json=body)
    assert response.status_code == 200, (response.get_json(), env.routes["editor_error_response"].call_args)
    assert "CANARY-" not in response.get_data(as_text=True)
    stored = env.containers["actions", "group"].items["group-a", saved["id"]]
    assert stored["description"] == "Edited"
    if mode == "clear":
        assert not stored["auth"].get("key")
    else:
        value = stored["auth"]["key"]
        actual = env.services.vault[value] if vault_enabled else value
        assert actual == ("CANARY-replacement" if mode == "replace" else "CANARY-action-key")


def test_stale_action_edit_is_rejected_without_writing(shared_routes):
    env = shared_routes
    saved = seed(env, "actions")
    before = deepcopy(env.containers["actions", "group"].items)
    response = env.client.patch(f"{BASE}/{saved['id']}", json={
        "expected_revision": "stale", "description": "Should not save",
    })
    assert response.status_code == 409
    assert env.containers["actions", "group"].items == before
    assert env.services.secret_writes == []


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_action_references_are_never_hydrated_or_serialized(shared_routes, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    reference = env.keyvault.build_full_secret_name("canary-reference", "group-a", "action", "group")
    env.services.vault[reference] = "CANARY-resolved-value"
    saved = seed(env, "actions", auth={"type": "key", "key": reference})
    for path in (BASE, f"{BASE}/{saved['id']}"):
        response = env.client.get(path)
        assert response.status_code == 200
        assert reference not in response.get_data(as_text=True)
        assert "CANARY-" not in response.get_data(as_text=True)
    assert env.services.secret_reads == []


@pytest.mark.parametrize("value", ["***REDACTED***", "foreign-reference"])
def test_action_write_rejects_unconfigured_masks_and_foreign_references(shared_routes, value):
    env = shared_routes
    saved = seed(env, "actions")
    reference = env.keyvault.build_full_secret_name("foreign", "group-b", "action", "group")
    if value == "foreign-reference":
        response = env.client.patch(f"{BASE}/{saved['id']}", json={"auth": {"key": reference}})
    else:
        response = env.client.post(BASE, json={
            "name": "new_action", "type": "openapi", "description": "", "endpoint": "https://service.invalid",
            "auth": {"type": "key", "key": value}, "metadata": {}, "additionalFields": {},
        })
    assert response.status_code == 400
    assert env.services.secret_reads == []
    assert env.services.secret_writes == []


@pytest.mark.parametrize("user", ["member", "manager", "admin"])
def test_nonmanagers_cannot_write_even_with_explicit_group(shared_routes, user):
    env = shared_routes
    env.services.settings["require_owner_for_group_agent_management"] = True
    saved = seed(env, "actions")
    as_user(env, user)
    for method, path in (("post", BASE), ("patch", f"{BASE}/{saved['id']}")):
        response = getattr(env.client, method)(path + "?group_id=group-a", json={"description": "Not authorized"})
        assert response.status_code == 403
    assert env.services.secret_writes == []


def test_action_lookup_cannot_use_another_groups_id_or_name(shared_routes):
    env = shared_routes
    saved = seed(env, "actions", group_id="group-b")
    for identifier in (saved["id"], saved["name"]):
        response = env.client.get(f"{BASE}/{identifier}?group_id=group-a")
        assert response.status_code == 404


def test_anonymous_action_reads_are_rejected(shared_routes):
    env = shared_routes
    with env.client.session_transaction() as state:
        state.clear()
    response = env.client.get(BASE)
    assert response.status_code == 401


@pytest.mark.parametrize("vault_enabled", [False, True])
def test_created_action_response_is_write_only(shared_routes, vault_enabled):
    env = shared_routes
    env.services.settings["enable_key_vault_secret_storage"] = vault_enabled
    response = env.client.post(BASE + "?group_id=group-a", json={
        "name": "new_shared_action", "displayName": "New shared action", "description": "",
        "type": "openapi", "endpoint": "https://service.invalid",
        "auth": {"type": "key", "key": "CANARY-created-action"}, "metadata": {}, "additionalFields": {},
    })
    assert response.status_code == 201, response.get_json()
    assert "CANARY-" not in response.get_data(as_text=True)
    assert response.get_json()["auth"]["key"] == "***REDACTED***"
    assert response.get_json()["revision"]
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("value", [
    "***REDACTED***:***REDACTED***", "***REDACTED***:partial-replacement", "prefix-Stored_In_KeyVault",
])
def test_composed_secret_markers_are_rejected_without_overwriting_credentials(shared_routes, value):
    env = shared_routes
    saved = seed(env, "actions")
    before = deepcopy(env.containers["actions", "group"].items)
    response = env.client.patch(f"{BASE}/{saved['id']}", json={"auth": {"key": value}})
    assert response.status_code == 400
    assert value not in response.get_data(as_text=True)
    assert env.containers["actions", "group"].items == before
