# test_public_identity_apis.py
"""
Functional tests for the immutable-target public workspace identity APIs (M10B).
Version: 0.261.179
Implemented in: 0.261.179

The real public identity policy, access, projection, storage and route modules
run unchanged over the shared ``public_identity_harness``: an in-memory Cosmos
stub that honours ETag conditional writes, an in-memory Key Vault, the real
``functions_keyvault`` staging helpers and the real public workspace role logic.
The workspace is always taken from the path, so a stale active workspace can
never redirect or widen a request.

Public identities are a manager-only surface for reads and writes, exactly like
the group family. The scope differences pinned here are: the projection carries
``public_workspace_id`` (never ``group_id``); the readable-status gate is an
explicit allowlist so an unrecognized status is denied rather than treated as
active; the surface rests solely on File Sync (a public workspace has no Semantic
Kernel actions); and the only reference that can block a delete is a File Sync
source. Network access is prohibited by the harness.
"""

import importlib.util
import json

import pytest

from test_support.public_identity_harness import (  # noqa: F401  (environment is a pytest fixture)
    APP_ROOT,
    CosmosHttpResponseError,
    LIST_PATH,
    PLACEHOLDER,
    MANAGER_ROLES,
    NON_MANAGER_ROLES,
    ROLE_USER,
    as_user,
    environment,
    read_etag,
    seed_identity,
)


# --------------------------------------------------------------------------
# Reads: role, membership, workspace resolution
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_manager_roles_can_list_and_read(environment, role):
    identity = seed_identity(environment)
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["identities"]] == [identity["id"]]
    single = environment.client.get(f"{LIST_PATH}/{identity['id']}")
    assert single.status_code == 200
    assert single.get_json()["identity"]["id"] == identity["id"]


@pytest.mark.parametrize("role", NON_MANAGER_ROLES)
def test_non_manager_roles_cannot_read(environment, role):
    seed_identity(environment)
    as_user(environment, ROLE_USER[role])
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/whatever").status_code == 403


def test_non_member_is_forbidden(environment):
    seed_identity(environment)
    as_user(environment, "stranger")
    assert environment.client.get(LIST_PATH).status_code == 403


def test_unknown_workspace_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/public-workspaces/no-such-ws/identities").status_code == 404


def test_reading_another_workspaces_identity_through_this_path_is_404(environment):
    other = seed_identity(environment, workspace_id="public-b")
    as_user(environment, "owner")
    response = environment.client.get(f"{LIST_PATH}/{other['id']}")
    assert response.status_code == 404


def test_list_never_leaks_another_workspaces_identities(environment):
    here = seed_identity(environment, name="Here", workspace_id="public-a")
    seed_identity(environment, name="Elsewhere", workspace_id="public-b")
    as_user(environment, "owner")
    ids = [item["id"] for item in environment.client.get(LIST_PATH).get_json()["identities"]]
    assert ids == [here["id"]]


def test_list_envelope_and_single_resource_shape(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"identities", "identity_management"}
    assert body["identity_management"] == {
        "schema_version": 1, "operations": ["create", "edit", "delete"],
    }
    item = body["identities"][0]
    assert item["id"] == identity["id"] and item["public_workspace_id"] == "public-a"
    assert item["etag"] and item["identity_actions"] == ["edit", "delete"]
    assert "auth" not in item and "_etag" not in item and "_rid" not in item
    assert "group_id" not in item and "user_id" not in item
    assert "credentials" in item
    single = environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()
    assert set(single) == {"identity"}
    assert single["identity"]["id"] == identity["id"]


# --------------------------------------------------------------------------
# Reads: status matrix and availability
# --------------------------------------------------------------------------

@pytest.mark.parametrize("workspace_id,status,readable", [
    ("public-a", "active", True),
    ("locked-ws", "locked", True),
    ("upload-disabled-ws", "upload_disabled", True),
    ("inactive-ws", "inactive", False),
    ("haunted-ws", "haunted", False),
])
def test_read_status_matrix(environment, workspace_id, status, readable):
    seed_identity(environment, workspace_id=workspace_id)
    as_user(environment, "owner")
    response = environment.client.get(f"/api/public-workspaces/{workspace_id}/identities")
    assert response.status_code == (200 if readable else 403)


def test_feature_gate_off_refuses_every_route(environment):
    environment.settings["enable_public_workspaces"] = False
    seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 400
    assert environment.client.post(LIST_PATH, json=_create_body()).status_code == 400


def test_surface_unavailable_when_file_sync_off(environment):
    environment.state.file_sync_enabled = False
    seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 403
    assert response.get_json()["error"] == "Identities require File Sync."


def test_surface_available_when_file_sync_on(environment):
    environment.state.file_sync_enabled = True
    seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 200


# --------------------------------------------------------------------------
# Writes: role and status
# --------------------------------------------------------------------------

def _create_body(name="New identity"):
    return {
        "name": name,
        "provider": "generic",
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }


@pytest.mark.parametrize("role", NON_MANAGER_ROLES)
def test_non_manager_cannot_create(environment, role):
    as_user(environment, ROLE_USER[role])
    assert environment.client.post(LIST_PATH, json=_create_body()).status_code == 403


@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_every_manager_role_may_create(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.post(LIST_PATH, json=_create_body())
    assert response.status_code == 201


def test_create_returns_201_with_etag_and_actions(environment):
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json=_create_body())
    assert response.status_code == 201
    identity = response.get_json()["identity"]
    assert identity["name"] == "New identity"
    assert identity["public_workspace_id"] == "public-a"
    assert identity["etag"] and identity["identity_actions"] == ["edit", "delete"]
    assert "auth" not in identity


@pytest.mark.parametrize("workspace_id", ["locked-ws", "upload-disabled-ws"])
def test_writes_refused_on_readable_but_non_active_status(environment, workspace_id):
    as_user(environment, "owner")
    response = environment.client.post(f"/api/public-workspaces/{workspace_id}/identities", json=_create_body())
    assert response.status_code == 403


@pytest.mark.parametrize("workspace_id", ["inactive-ws", "haunted-ws"])
def test_writes_refused_on_unreadable_status(environment, workspace_id):
    as_user(environment, "owner")
    response = environment.client.post(f"/api/public-workspaces/{workspace_id}/identities", json=_create_body())
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Conditional writes
# --------------------------------------------------------------------------

def test_update_requires_expected_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed"})
    assert response.status_code == 400


def test_update_succeeds_with_current_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 200
    assert response.get_json()["identity"]["name"] == "Renamed"


def test_update_stale_etag_conflicts_without_writing(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    writes_before = list(environment.public_container.calls)
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "etag_conflict"
    assert environment.public_container.calls == writes_before


def test_update_race_with_delete_is_404_and_never_recreates(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])

    def land_delete(records, key):
        records.pop(key, None)

    environment.public_container.before_replace = land_delete
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 404
    assert ("public-a", identity["id"]) not in environment.public_container.records


def test_update_race_with_concurrent_edit_is_409(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])

    def land_edit(records, key):
        records[key]["_etag"] = '"moved-on"'

    environment.public_container.before_replace = land_edit
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 409


def test_delete_requires_expected_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={}).status_code == 400


def test_delete_stale_etag_conflicts(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{identity['id']}", json={"expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert ("public-a", identity["id"]) in environment.public_container.records


def test_delete_succeeds_with_current_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 200
    assert ("public-a", identity["id"]) not in environment.public_container.records


# --------------------------------------------------------------------------
# Strict request handling
# --------------------------------------------------------------------------

def test_query_parameters_are_rejected(environment):
    seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?page=2").status_code == 400


def test_unknown_top_level_field_is_rejected(environment):
    as_user(environment, "owner")
    body = _create_body()
    body["auth"] = {"auth_type": "api_key", "secret": "smuggled"}
    assert environment.client.post(LIST_PATH, json=body).status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    raw = '{"name": "a", "name": "b"}'
    response = environment.client.post(LIST_PATH, data=raw, content_type="application/json")
    assert response.status_code == 400


def test_read_does_not_accept_a_body(environment):
    seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH, data=b"{}", content_type="application/json")
    assert response.status_code == 400


_STRICT_WRITE_FIELDS = {
    "name", "description", "provider", "source_type",
    "usage_contexts", "supported_source_types", "metadata", "credentials",
}


def test_every_strict_write_field_is_accepted(environment):
    as_user(environment, "owner")
    body = {
        "name": "Full", "description": "d", "provider": "generic", "source_type": "generic",
        "usage_contexts": ["file_sync"], "supported_source_types": ["generic"], "metadata": {"k": "v"},
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    assert set(body) == _STRICT_WRITE_FIELDS
    assert environment.client.post(LIST_PATH, json=body).status_code == 201


@pytest.mark.parametrize("field", ["auth", "auth_type", "scope_id", "group_id", "public_workspace_id", "id", "etag"])
def test_forbidden_top_level_write_fields_are_rejected(environment, field):
    as_user(environment, "owner")
    body = _create_body()
    body[field] = {"auth_type": "api_key"} if field == "auth" else "x"
    assert environment.client.post(LIST_PATH, json=body).status_code == 400


def test_patch_rejects_auth_alias(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    body = {"name": "Renamed", "auth": {"auth_type": "api_key"}, "expected_etag": etag}
    assert environment.client.patch(f"{LIST_PATH}/{identity['id']}", json=body).status_code == 400


def test_delete_body_must_be_exactly_expected_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(
        f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag, "force": True},
    )
    assert response.status_code == 400
    assert ("public-a", identity["id"]) in environment.public_container.records


def test_response_row_carries_the_native_additions_without_leaks(environment):
    identity = seed_identity(environment, usage_contexts=["file_sync"])
    as_user(environment, "owner")
    for row in (
        environment.client.get(LIST_PATH).get_json()["identities"][0],
        environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()["identity"],
    ):
        assert isinstance(row["etag"], str) and row["etag"]
        assert set(row["identity_actions"]) <= {"edit", "delete"}
        assert row["usage_contexts"] == ["file_sync"]
        assert "auth" not in row and "auth_type" not in row
        assert "scope_id" not in row and "_etag" not in row


# --------------------------------------------------------------------------
# Placeholder round trip and secret handling (Key Vault off)
# --------------------------------------------------------------------------

def test_placeholder_keeps_the_stored_secret(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}",
        json={
            "name": "Renamed",
            "credentials": {"auth_type": "username_password", "username": "svc", "password": PLACEHOLDER},
            "expected_etag": etag,
        },
    )
    assert response.status_code == 200
    credentials = response.get_json()["identity"]["credentials"]
    assert credentials["password_stored"] is True and credentials["password"] == PLACEHOLDER
    stored = environment.identities.get_workspace_identity("public", "public-a", identity["id"])
    assert stored["auth"].get("password") == "p@ss"


def test_storage_off_response_never_returns_the_inline_value(environment):
    as_user(environment, "owner")
    body = environment.client.post(LIST_PATH, json=_create_body()).get_json()
    dumped = json.dumps(body)
    assert "p@ss" not in dumped
    assert "auth" not in body["identity"]
    assert body["identity"]["credentials"]["password"] == PLACEHOLDER


# --------------------------------------------------------------------------
# Key Vault positive controls (storage enabled): stored in the public scope,
# never echoed, retained, replaced and cleared.
# --------------------------------------------------------------------------

def _enable_key_vault(env):
    env.settings["enable_key_vault_secret_storage"] = True
    env.settings["key_vault_name"] = "test-only-vault"


def test_create_stores_secret_under_the_public_scope_name(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    expected = f"public-a--identity--public--workspace-identity-{identity['id']}-password"
    assert (expected, "p@ss") in environment.state.secret_writes
    stored = environment.identities.get_workspace_identity("public", "public-a", identity["id"])
    assert stored["auth"].get("password_secret_name") == expected
    assert "p@ss" not in json.dumps(environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json())


def test_auth_type_change_removes_the_superseded_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"public-a--identity--public--workspace-identity-{identity['id']}-password"
    assert password_name in environment.state.vault

    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}",
        json={
            "credentials": {"auth_type": "connection_string", "connection_string": "Server=x;"},
            "expected_etag": etag,
        },
    )
    assert response.status_code == 200
    assert password_name in environment.state.secret_deletes
    assert password_name not in environment.state.vault
    stored = environment.identities.get_workspace_identity("public", "public-a", identity["id"])
    fresh_name = stored["auth"]["secret_secret_name"]
    assert fresh_name.startswith("public-a--identity--public--identity-")
    assert fresh_name in environment.state.vault


def test_delete_removes_the_identity_secrets(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"public-a--identity--public--workspace-identity-{identity['id']}-password"
    assert password_name in environment.state.vault

    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 200
    assert password_name in environment.state.secret_deletes
    assert password_name not in environment.state.vault


def test_a_write_landing_mid_flight_refuses_and_keeps_the_live_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"public-a--identity--public--workspace-identity-{identity['id']}-password"
    assert environment.state.vault[password_name] == "p@ss"
    etag = read_etag(environment, identity["id"])

    def land_concurrent_write(records, key):
        records[key]["_etag"] = '"etag-conflict"'
    environment.public_container.before_replace = land_concurrent_write

    writes_before = len(environment.state.secret_writes)
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}",
        json={
            "credentials": {"auth_type": "username_password", "username": "svc", "password": "attacker"},
            "expected_etag": etag,
        },
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "etag_conflict"
    assert environment.state.vault[password_name] == "p@ss"
    staged = [name for (name, _value) in environment.state.secret_writes[writes_before:]]
    assert staged, "the refused write should have staged a fresh secret"
    for name in staged:
        assert name.startswith("public-a--identity--public--identity-")
        assert name in environment.state.secret_deletes
        assert name not in environment.state.vault
    stored = environment.identities.get_workspace_identity("public", "public-a", identity["id"])
    assert stored["auth"]["password_secret_name"] == password_name


def test_a_successful_password_change_stages_fresh_and_deletes_the_superseded(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    original_name = f"public-a--identity--public--workspace-identity-{identity['id']}-password"
    assert original_name in environment.state.vault

    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}",
        json={
            "credentials": {"auth_type": "username_password", "username": "svc", "password": "n3wp@ss"},
            "expected_etag": etag,
        },
    )
    assert response.status_code == 200
    stored = environment.identities.get_workspace_identity("public", "public-a", identity["id"])
    fresh_name = stored["auth"]["password_secret_name"]
    assert fresh_name != original_name
    assert fresh_name.startswith("public-a--identity--public--identity-")
    assert (fresh_name, "n3wp@ss") in environment.state.secret_writes
    assert environment.state.vault[fresh_name] == "n3wp@ss"
    assert original_name in environment.state.secret_deletes
    assert original_name not in environment.state.vault


def test_a_failed_create_discards_the_stored_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")

    def explode(body):
        raise CosmosHttpResponseError(500)
    environment.public_container.create_item = explode

    response = environment.client.post(LIST_PATH, json=_create_body())
    assert response.status_code == 500
    assert environment.state.secret_writes, "the create should have stored a secret first"
    for name, _value in environment.state.secret_writes:
        assert name in environment.state.secret_deletes
        assert name not in environment.state.vault


# --------------------------------------------------------------------------
# Reviewed validation messages surface; every other error stays generic
# --------------------------------------------------------------------------

@pytest.mark.parametrize("credentials,message", [
    ({"auth_type": "telepathy"}, "Unsupported workspace identity authentication type"),
    ({"auth_type": "username_password", "username": "svc"},
     "Username/password identities require a password"),
    ({"auth_type": "connection_string"}, "This identity type requires a secret value"),
])
def test_reviewed_validation_messages_reach_the_client(environment, credentials, message):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH, json={"name": "Bad", "provider": "generic", "credentials": credentials}
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == message


def test_a_public_validation_error_maps_to_its_own_400(environment):
    error = environment.identities.WorkspaceIdentityValidationError("A reviewed, data-free message.")
    with environment.app.test_request_context():
        response, status = environment.access.public_identity_error_response(error)
        assert status == 400
        assert response.get_json()["error"] == "A reviewed, data-free message."


def test_an_unexpected_value_error_stays_generic(environment):
    with environment.app.test_request_context():
        response, status = environment.access.public_identity_error_response(ValueError("secret=hunter2"))
        assert status == 400
        assert response.get_json()["error"] == "The workspace identity details are not valid."
        assert "hunter2" not in json.dumps(response.get_json())


def test_an_unexpected_failure_stays_a_generic_500(environment):
    with environment.app.test_request_context():
        response, status = environment.access.public_identity_error_response(RuntimeError("boom secret"))
        assert status == 500
        assert "secret" not in json.dumps(response.get_json()).replace("Unable", "")
        assert response.get_json()["error"] == "Unable to complete the workspace identity request."


# --------------------------------------------------------------------------
# Delete while in use: only File Sync sources can block a public identity
# --------------------------------------------------------------------------

def test_delete_refused_when_a_file_source_references_the_identity(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    environment.state.file_sync_sources = [
        {"id": "src-1", "name": "Nightly sync", "identity_id": identity["id"]},
        {"id": "src-2", "name": "Other", "identity_id": "someone-else"},
    ]
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "identity_in_use"
    assert body["references"] == [{"kind": "file_source", "id": "src-1", "name": "Nightly sync"}]
    assert ("public-a", identity["id"]) in environment.public_container.records
    environment.reference_block.assert_called_once()


# --------------------------------------------------------------------------
# identity_actions seam
# --------------------------------------------------------------------------

def test_identity_actions_are_empty_on_a_read_only_workspace(environment):
    identity = seed_identity(environment, workspace_id="locked-ws")
    as_user(environment, "owner")
    single = environment.client.get(f"/api/public-workspaces/locked-ws/identities/{identity['id']}").get_json()
    assert single["identity"]["identity_actions"] == []


# --------------------------------------------------------------------------
# Normalized usage_contexts in every response (shared normalizer)
# --------------------------------------------------------------------------

_MISSING = object()


def seed_raw(env, identity_id, usage_contexts, workspace_id="public-a"):
    """Insert a stored record directly, bypassing write-time normalization, so a
    response can be checked against an older or aliased ``usage_contexts`` shape."""
    record = {
        "id": identity_id, "identity_id": identity_id, "type": "workspace_identity",
        "scope_type": "public", "public_workspace_id": workspace_id,
        "name": f"Identity {identity_id}", "provider": "generic", "source_type": "generic",
        "supported_source_types": ["action"], "metadata": {},
        "auth": {"auth_type": "api_key", "secret_secret_name": "x"},
    }
    if usage_contexts is not _MISSING:
        record["usage_contexts"] = usage_contexts
    env.public_container.create_item(record)
    return record


@pytest.mark.parametrize("stored_usage,expected", [
    (_MISSING, ["action"]),
    (["agent"], ["action"]),
    (["general"], ["action"]),
    (["file_sync"], ["file_sync"]),
    (["file_sync", "action"], ["file_sync", "action"]),
])
def test_response_usage_contexts_are_normalized_like_supports_usage(environment, stored_usage, expected):
    seed_raw(environment, "raw-1", stored_usage)
    as_user(environment, "owner")
    single = environment.client.get(f"{LIST_PATH}/raw-1").get_json()["identity"]
    assert single["usage_contexts"] == expected
    listed = environment.client.get(LIST_PATH).get_json()["identities"][0]
    assert listed["usage_contexts"] == expected


# --------------------------------------------------------------------------
# One availability predicate, shared by the context and the routes
# --------------------------------------------------------------------------

def test_context_and_access_share_the_availability_predicate():
    context_source = (APP_ROOT / "functions_workspace_context.py").read_text(encoding="utf-8")
    access_source = (APP_ROOT / "functions_public_identity_access.py").read_text(encoding="utf-8")
    assert "public_identities_available" in context_source
    assert "public_identities_available" in access_source


def test_availability_predicate_behaviour():
    spec = importlib.util.spec_from_file_location(
        "_public_identity_policy_probe", APP_ROOT / "functions_public_identity_policy.py",
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)

    assert policy.public_identities_available({}, "public-a", file_sync_enabled=True) == (True, None)
    available, reason = policy.public_identities_available({}, "public-a", file_sync_enabled=False)
    assert available is False and reason == "Identities require File Sync."


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
