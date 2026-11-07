# test_group_identity_apis.py
"""
Functional tests for the immutable-target group identity APIs.
Version: 0.261.139
Implemented in: 0.261.139

The real policy, access, projection, storage and route modules run against the
real Key Vault helpers, executed unchanged over an in-memory Cosmos stub that
honours ETag conditional writes and an in-memory Key Vault. The group is always
taken from the path, so a stale active group can never redirect or widen a
request. Group identities are a manager-only surface for both reads and writes.
Network access is prohibited.
"""

import importlib.util
import json

import pytest

from test_support.versioning import assert_app_version_at_least
from test_support.group_identity_harness import (  # noqa: F401  (environment is a pytest fixture)
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
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.139")


# --------------------------------------------------------------------------
# Reads: role, status, availability
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


def test_unknown_group_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/identities").status_code == 404


def test_list_envelope_and_single_resource_shape(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"identities", "identity_management"}
    assert body["identity_management"] == {
        "schema_version": 1, "operations": ["create", "edit", "delete"],
    }
    item = body["identities"][0]
    assert item["id"] == identity["id"] and item["group_id"] == "group-a"
    assert item["etag"] and item["identity_actions"] == ["edit", "delete"]
    assert "auth" not in item and "_etag" not in item and "_rid" not in item
    assert "credentials" in item
    single = environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()
    assert set(single) == {"identity"}
    assert single["identity"]["id"] == identity["id"]


@pytest.mark.parametrize("group_id,status,readable", [
    ("group-a", "active", True),
    ("locked-grp", "locked", True),
    ("upload-disabled-grp", "upload_disabled", True),
    ("inactive-grp", "inactive", False),
    ("haunted-grp", "haunted", False),
])
def test_read_status_matrix(environment, group_id, status, readable):
    seed_identity(environment, group_id=group_id)
    as_user(environment, "owner")
    response = environment.client.get(f"/api/groups/{group_id}/identities")
    assert response.status_code == (200 if readable else 403)


def test_surface_unavailable_when_semantic_kernel_and_file_sync_off(environment):
    environment.settings["enable_semantic_kernel"] = False
    environment.state.file_sync_enabled = False
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 403
    assert "File Sync or Semantic Kernel" in response.get_json()["error"]


def test_surface_available_via_file_sync_when_semantic_kernel_off(environment):
    environment.settings["enable_semantic_kernel"] = False
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


def test_create_returns_201_with_etag_and_actions(environment):
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json=_create_body())
    assert response.status_code == 201
    identity = response.get_json()["identity"]
    assert identity["name"] == "New identity"
    assert identity["etag"] and identity["identity_actions"] == ["edit", "delete"]
    assert "auth" not in identity


@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp"])
def test_writes_refused_on_readable_but_non_active_status(environment, group_id):
    as_user(environment, "owner")
    response = environment.client.post(f"/api/groups/{group_id}/identities", json=_create_body())
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
    writes_before = list(environment.group_container.calls)
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert environment.group_container.calls == writes_before


def test_update_race_with_delete_is_404_and_never_recreates(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])

    def land_delete(records, key):
        records.pop(key, None)

    environment.group_container.before_replace = land_delete
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 404
    assert (("group-a", identity["id"])) not in environment.group_container.records


def test_update_race_with_concurrent_edit_is_409(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])

    def land_edit(records, key):
        records[key]["_etag"] = '"moved-on"'

    environment.group_container.before_replace = land_edit
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
    assert ("group-a", identity["id"]) in environment.group_container.records


def test_delete_succeeds_with_current_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 200
    assert ("group-a", identity["id"]) not in environment.group_container.records


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


# --------------------------------------------------------------------------
# Exact response and request shapes (addendum §10)
# --------------------------------------------------------------------------

_STRICT_WRITE_FIELDS = {
    "name", "description", "provider", "source_type",
    "usage_contexts", "supported_source_types", "metadata", "credentials",
}


def test_every_strict_write_field_is_accepted(environment):
    as_user(environment, "owner")
    body = {
        "name": "Full", "description": "d", "provider": "generic", "source_type": "generic",
        "usage_contexts": ["action"], "supported_source_types": ["generic"], "metadata": {"k": "v"},
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    assert set(body) == _STRICT_WRITE_FIELDS
    assert environment.client.post(LIST_PATH, json=body).status_code == 201


@pytest.mark.parametrize("field", ["auth", "auth_type", "scope_id", "group_id", "id", "etag"])
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
    assert ("group-a", identity["id"]) in environment.group_container.records


def test_response_row_carries_the_native_additions_without_leaks(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    for row in (
        environment.client.get(LIST_PATH).get_json()["identities"][0],
        environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()["identity"],
    ):
        assert isinstance(row["etag"], str) and row["etag"]
        assert set(row["identity_actions"]) <= {"edit", "delete"}
        assert row["usage_contexts"] == ["action"]
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
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    assert stored["auth"].get("password") == "p@ss"


def test_storage_off_response_never_returns_the_inline_value(environment):
    as_user(environment, "owner")
    body = environment.client.post(LIST_PATH, json=_create_body()).get_json()
    dumped = json.dumps(body)
    assert "p@ss" not in dumped
    assert "auth" not in body["identity"]
    assert body["identity"]["credentials"]["password"] == PLACEHOLDER


# --------------------------------------------------------------------------
# Key Vault positive controls (storage enabled)
# --------------------------------------------------------------------------

def _enable_key_vault(env):
    env.settings["enable_key_vault_secret_storage"] = True
    env.settings["key_vault_name"] = "test-only-vault"


def test_create_stores_secret_under_the_exact_full_name(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    expected = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
    assert (expected, "p@ss") in environment.state.secret_writes
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    assert stored["auth"].get("password_secret_name") == expected
    assert "p@ss" not in json.dumps(environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json())


def test_auth_type_change_removes_the_superseded_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
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
    # The switched-away password secret is removed.
    assert password_name in environment.state.secret_deletes
    assert password_name not in environment.state.vault
    # The new secret is staged under a fresh, non-conventional name (B1), so a
    # refused CAS can never overwrite the live credential's conventional name.
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    fresh_name = stored["auth"]["secret_secret_name"]
    assert fresh_name.startswith("group-a--identity--group--identity-")
    assert fresh_name in environment.state.vault


def test_delete_removes_the_identity_secrets(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
    assert password_name in environment.state.vault

    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 200
    assert password_name in environment.state.secret_deletes
    assert password_name not in environment.state.vault


# --------------------------------------------------------------------------
# B1: fresh-name staging isolates a refused conditional write
# --------------------------------------------------------------------------

def test_a_write_landing_mid_flight_refuses_and_keeps_the_live_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
    assert environment.state.vault[password_name] == "p@ss"
    etag = read_etag(environment, identity["id"])

    def land_concurrent_write(records, key):
        # Bump the stored etag so the conditional replace fails its precondition.
        records[key]["_etag"] = '"etag-conflict"'
    environment.group_container.before_replace = land_concurrent_write

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
    # The refused value never becomes the current version of the stored reference.
    assert environment.state.vault[password_name] == "p@ss"
    # The fresh staged secret was written, then discarded, leaving no orphan.
    staged = [name for (name, _value) in environment.state.secret_writes[writes_before:]]
    assert staged, "the refused write should have staged a fresh secret"
    for name in staged:
        assert name.startswith("group-a--identity--group--identity-")
        assert name in environment.state.secret_deletes
        assert name not in environment.state.vault
    # The stored reference still points at the untouched conventional name.
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    assert stored["auth"]["password_secret_name"] == password_name


def test_a_successful_password_change_stages_fresh_and_deletes_the_superseded(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    original_name = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
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
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    fresh_name = stored["auth"]["password_secret_name"]
    assert fresh_name != original_name
    assert fresh_name.startswith("group-a--identity--group--identity-")
    assert (fresh_name, "n3wp@ss") in environment.state.secret_writes
    assert environment.state.vault[fresh_name] == "n3wp@ss"
    # The superseded conventional secret is removed only after the write commits.
    assert original_name in environment.state.secret_deletes
    assert original_name not in environment.state.vault


def test_a_failed_create_discards_the_stored_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")

    def explode(body):
        raise CosmosHttpResponseError(500)
    environment.group_container.create_item = explode

    response = environment.client.post(LIST_PATH, json=_create_body())
    assert response.status_code == 500
    assert environment.state.secret_writes, "the create should have stored a secret first"
    for name, _value in environment.state.secret_writes:
        assert name in environment.state.secret_deletes
        assert name not in environment.state.vault


def test_fresh_and_conventional_secret_names_stay_within_the_key_vault_limit(environment):
    _enable_key_vault(environment)
    group_id = "g" * 36
    payload = {
        "name": "Long ids",
        "provider": "generic",
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    created = environment.identities.create_workspace_identity("group", group_id, payload, "owner")
    # The deterministic create name is the longest conventional case.
    create_name = next(name for name, _ in environment.state.secret_writes)
    assert create_name.startswith(f"{group_id}--identity--group--workspace-identity-")
    assert len(create_name) <= 127

    stored = environment.identities.get_workspace_identity("group", group_id, created["identity_id"])
    updated = environment.identities.update_workspace_identity_conditional(
        "group", group_id, created["identity_id"],
        {"credentials": {"auth_type": "username_password", "username": "svc", "password": "rotated"}},
        "owner", stored["_etag"],
    )
    fresh_name = updated["auth"]["password_secret_name"]
    assert fresh_name.startswith(f"{group_id}--identity--group--identity-")
    assert len(fresh_name) <= 127


# --------------------------------------------------------------------------
# B3: reviewed validation messages surface; every other ValueError stays generic
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


def test_auth_type_not_available_for_usage_reaches_the_client(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH,
        json={
            "name": "SMB with api key",
            "provider": "smb",
            "usage_contexts": ["file_sync"],
            "credentials": {"auth_type": "api_key", "key": "abc"},
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Selected authentication type is not available for the selected identity uses"


def test_a_public_validation_error_maps_to_its_own_400(environment):
    error = environment.identities.WorkspaceIdentityValidationError("A reviewed, data-free message.")
    with environment.app.test_request_context():
        response, status = environment.access.group_identity_error_response(error)
        assert status == 400
        assert response.get_json()["error"] == "A reviewed, data-free message."


def test_an_unexpected_value_error_stays_generic(environment):
    with environment.app.test_request_context():
        response, status = environment.access.group_identity_error_response(ValueError("secret=hunter2"))
        assert status == 400
        assert response.get_json()["error"] == "The workspace identity details are not valid."
        assert "hunter2" not in json.dumps(response.get_json())


# --------------------------------------------------------------------------
# B5: supported_source_types has one normalizer shared by gate and projection
# --------------------------------------------------------------------------

def test_supported_source_types_defaults_to_the_provider(environment):
    assert environment.identities.normalize_identity_supported_source_types({"provider": "smb"}) == ["smb"]


def test_supported_source_types_without_a_provider_defaults_to_generic(environment):
    assert environment.identities.normalize_identity_supported_source_types({}) == ["generic"]


def test_generic_supported_source_type_matches_any_requested_source(environment):
    identity = {"usage_contexts": ["file_sync"], "supported_source_types": ["generic"]}
    assert environment.identities.identity_supports_usage(identity, "file_sync", source_type="azure_files")
    assert environment.identities.identity_supports_usage(identity, "file_sync", source_type="smb")
    specific = {"usage_contexts": ["file_sync"], "supported_source_types": ["smb"]}
    assert environment.identities.identity_supports_usage(specific, "file_sync", source_type="smb")
    assert not environment.identities.identity_supports_usage(specific, "file_sync", source_type="azure_files")


def test_projection_backfills_supported_source_types_for_older_records(environment):
    identity = seed_identity(environment, provider="smb", usage_contexts=["file_sync"])
    # Simulate a record written before supported_source_types existed.
    environment.group_container.records[("group-a", identity["id"])].pop("supported_source_types", None)
    as_user(environment, "owner")
    item = environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()["identity"]
    assert item["supported_source_types"] == ["smb"]


# --------------------------------------------------------------------------
# Delete while in use
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
    assert ("group-a", identity["id"]) in environment.group_container.records
    environment.reference_block.assert_called_once()


def test_delete_refused_when_an_action_references_the_identity(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    environment.state.group_actions = [
        {"id": "act-1", "displayName": "SQL report", "identity_id": identity["id"]},
    ]
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "identity_in_use"
    assert body["references"] == [{"kind": "action", "id": "act-1", "name": "SQL report"}]
    assert ("group-a", identity["id"]) in environment.group_container.records


# --------------------------------------------------------------------------
# identity_actions seam
# --------------------------------------------------------------------------

def test_identity_actions_are_empty_on_a_read_only_group(environment):
    identity = seed_identity(environment, group_id="locked-grp")
    as_user(environment, "owner")
    single = environment.client.get(f"/api/groups/locked-grp/identities/{identity['id']}").get_json()
    assert single["identity"]["identity_actions"] == []


# --------------------------------------------------------------------------
# Normalized usage_contexts in every response (addendum §9)
# --------------------------------------------------------------------------

_MISSING = object()


def seed_raw(env, identity_id, usage_contexts, group_id="group-a"):
    """Insert a stored record directly, bypassing write-time normalization, so a
    response can be checked against an older or aliased ``usage_contexts`` shape."""
    record = {
        "id": identity_id, "identity_id": identity_id, "type": "workspace_identity",
        "scope_type": "group", "group_id": group_id,
        "name": f"Identity {identity_id}", "provider": "generic", "source_type": "generic",
        "supported_source_types": ["action"], "metadata": {},
        "auth": {"auth_type": "api_key", "secret_secret_name": "x"},
    }
    if usage_contexts is not _MISSING:
        record["usage_contexts"] = usage_contexts
    env.group_container.create_item(record)
    return record


@pytest.mark.parametrize("stored_usage,expected", [
    (_MISSING, ["action"]),
    (["agent"], ["action"]),
    (["plugin"], ["action"]),
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
    # The equivalence the frontend action filter relies on.
    stored = environment.identities.get_workspace_identity("group", "group-a", "raw-1")
    supports_action = environment.identities.identity_supports_usage(stored, "action")
    assert ("action" in single["usage_contexts"]) == supports_action


def test_projection_and_supports_usage_share_one_normalizer():
    access_source = (APP_ROOT / "functions_group_identity_access.py").read_text(encoding="utf-8")
    identities_source = (APP_ROOT / "functions_workspace_identities.py").read_text(encoding="utf-8")
    assert "normalize_identity_usage_contexts" in access_source
    # identity_supports_usage must delegate to the shared helper, not re-inline it.
    gate = identities_source.split("def identity_supports_usage", 1)[1].split("\ndef ", 1)[0]
    assert "normalize_identity_usage_contexts(identity)" in gate


# --------------------------------------------------------------------------
# One availability predicate, shared by the context and the routes
# --------------------------------------------------------------------------

def test_context_and_access_share_the_availability_predicate():
    context_source = (APP_ROOT / "functions_workspace_context.py").read_text(encoding="utf-8")
    access_source = (APP_ROOT / "functions_group_identity_access.py").read_text(encoding="utf-8")
    assert "group_identities_available" in context_source
    assert "group_identities_available" in access_source


def test_availability_predicate_behaviour():
    spec = importlib.util.spec_from_file_location(
        "_identity_policy_probe", APP_ROOT / "functions_group_identity_policy.py",
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)

    assert policy.group_identities_available({"enable_semantic_kernel": True}, "group-a") == (True, None)
    assert policy.group_identities_available(
        {"enable_semantic_kernel": False}, "group-a", file_sync_enabled=True,
    ) == (True, None)
    available, reason = policy.group_identities_available(
        {"enable_semantic_kernel": False}, "group-a", file_sync_enabled=False,
    )
    assert available is False and "File Sync or Semantic Kernel" in reason


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
