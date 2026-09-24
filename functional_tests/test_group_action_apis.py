# test_group_action_apis.py
"""
Functional tests for the immutable-target group action APIs.
Version: 0.261.157
Implemented in: 0.261.137
Backend harness extracted to test_support/group_action_harness.py: 0.261.157

The real policy, access, projection and route modules run against the real
personal-editor authoring engine (``functions_workspace_authoring``), executed
unchanged over an in-memory Cosmos stub that honours ETag conditional writes.
Group membership, status and settings are local test seams; the group is always
taken from the path, so a stale active group can never redirect or widen a
request. Key Vault storage is disabled, so no live secret backend is required,
and network access is prohibited.
"""

import importlib.util
import sys
from unittest.mock import Mock

import pytest

from test_support.agent_delegation import APP_ROOT, module_stub
from test_support.group_action_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    NON_WRITER_ROLES,
    OPTIONS_PATH,
    READER_ROLES,
    ROLE_USER,
    WRITER_ROLES,
    as_user,
    environment,
    seed_action,
    write_body,
)
from test_support.versioning import assert_app_version_at_least


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.137")


# --------------------------------------------------------------------------
# Reads: role and status
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_every_member_role_can_list_and_read(environment, role):
    seed_action(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["actions"]] == ["a1"]
    single = environment.client.get(f"{LIST_PATH}/a1")
    assert single.status_code == 200
    assert single.get_json()["record"]["id"] == "a1"


def test_list_envelope_and_single_resource_shape(environment):
    seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"actions"}
    item = body["actions"][0]
    assert item["id"] == "a1" and item["group_id"] == "group-a" and item["is_group"] is True
    assert "_rid" not in item and "_etag" not in item
    single = environment.client.get(f"{LIST_PATH}/a1").get_json()
    assert set(single) == {"record", "revision", "secret_paths", "read_only"}
    assert single["record"]["id"] == "a1"
    assert single["revision"]


def test_unknown_group_is_404_and_unknown_action_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/actions").status_code == 404
    assert environment.client.get(f"{LIST_PATH}/ghost").status_code == 404


@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp"])
def test_read_only_statuses_are_readable(environment, group_id):
    environment.groups[group_id]  # ensure fixture present
    seed_action(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    listing = environment.client.get(f"/api/groups/{group_id}/actions")
    assert listing.status_code == 200
    single = environment.client.get(f"/api/groups/{group_id}/actions/a1")
    assert single.status_code == 200
    # A read-only status advertises no per-item operations and marks the resource read-only.
    assert single.get_json()["record"]["action_actions"] == []
    assert single.get_json()["read_only"] is True


@pytest.mark.parametrize("group_id", ["inactive-grp", "haunted-grp"])
def test_inactive_and_unknown_statuses_are_denied(environment, group_id):
    seed_action(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    assert environment.client.get(f"/api/groups/{group_id}/actions").status_code == 403
    assert environment.client.get(f"/api/groups/{group_id}/actions/a1").status_code == 403


# --------------------------------------------------------------------------
# Per-item action hints
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writers_see_edit_delete_test_actions_in_active_group(environment, role):
    seed_action(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    item = environment.client.get(LIST_PATH).get_json()["actions"][0]
    assert item["action_actions"] == ["edit", "delete", "test"]


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writers_see_no_action_hints(environment, role):
    seed_action(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    item = environment.client.get(LIST_PATH).get_json()["actions"][0]
    assert item["action_actions"] == []


# --------------------------------------------------------------------------
# Writes: role policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writer_roles_can_create(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.post(LIST_PATH, json=write_body(
        name="created-by-writer", type="openapi", endpoint="https://api.example.test",
    ))
    assert response.status_code == 201
    body = response.get_json()
    assert body["record"]["name"] == "created-by-writer"
    assert body["record"]["is_group"] is True
    assert body["read_only"] is False


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writer_roles_cannot_create_edit_or_delete(environment, role):
    seed = seed_action(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    create = environment.client.post(LIST_PATH, json=write_body(name="x", type="openapi"))
    assert create.status_code == 403
    update = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="changed",
    ))
    assert update.status_code == 403
    delete = environment.client.delete(f"{LIST_PATH}/a1")
    assert delete.status_code == 403
    # Nothing was written.
    assert environment.group_container.records[("group-a", "a1")]["description"] == "A shared action."


def test_owner_only_setting_refuses_admin_writes(environment):
    environment.settings["require_owner_for_group_agent_management"] = True
    seed_action(environment.group_container, "a1")
    as_user(environment, "admin")
    assert environment.client.post(LIST_PATH, json=write_body(name="x", type="openapi")).status_code == 403
    as_user(environment, "owner")
    assert environment.client.post(LIST_PATH, json=write_body(
        name="owner-write", type="openapi", endpoint="https://api.example.test",
    )).status_code == 201


# --------------------------------------------------------------------------
# Writes: status policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp", "inactive-grp"])
def test_writes_are_refused_outside_active_status(environment, group_id):
    seed = seed_action(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    path = f"/api/groups/{group_id}/actions"
    assert environment.client.post(path, json=write_body(name="x", type="openapi")).status_code == 403
    update = environment.client.patch(f"{path}/a1", json=write_body(seed["_etag"], description="y"))
    assert update.status_code == 403
    assert environment.client.delete(f"{path}/a1").status_code == 403


# --------------------------------------------------------------------------
# Conditional writes
# --------------------------------------------------------------------------

def test_update_requires_expected_revision(environment):
    seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json={"updates": {"description": "changed"}})
    assert response.status_code == 400


def test_update_with_stale_revision_conflicts_and_writes_nothing(environment):
    seed = seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    stale = seed["_etag"]
    # A concurrent edit moves the stored revision forward.
    first = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(stale, description="first"))
    assert first.status_code == 200
    conflict = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(stale, description="second"))
    assert conflict.status_code == 409
    assert environment.group_container.records[("group-a", "a1")]["description"] == "first"


def test_update_success_returns_new_revision_and_persists(environment):
    seed = seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="updated body",
    ))
    assert response.status_code == 200
    body = response.get_json()
    assert body["record"]["description"] == "updated body"
    assert body["revision"] != seed["_etag"]


def test_delete_removes_the_record(environment):
    seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/a1")
    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert ("group-a", "a1") not in environment.group_container.records


# --------------------------------------------------------------------------
# Transport hygiene: query parameters and request bodies
# --------------------------------------------------------------------------

def test_list_rejects_query_parameters(environment):
    seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?scope=global").status_code == 400


def test_delete_rejects_expected_revision_as_a_query_parameter(environment):
    seed = seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/a1?expected_revision={seed['_etag']}")
    assert response.status_code == 400
    # The stray query parameter must be rejected, not honoured: the record survives.
    assert ("group-a", "a1") in environment.group_container.records


def test_read_rejects_a_request_body(environment):
    seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.get(
        f"{LIST_PATH}/a1", data=b"{}", content_type="application/json",
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Action types (a read capability)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_types_are_offered_to_every_member_role(environment, role):
    # The V2 collection and details page render type labels for every viewer, so
    # the catalogue is a read capability, not a write one (M4 §8 B2).
    as_user(environment, ROLE_USER[role])
    response = environment.client.get(f"{LIST_PATH}/types")
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    types = response.get_json()["types"]
    assert [entry["type"] for entry in types] == ["openapi", "sql_schema"]
    # The editor catalogue is enriched, not raw discovery (M4 §8 B1).
    for entry in types:
        assert set(entry) >= {"allowed_auth_types", "additional_fields_schema", "metadata_schema"}


def test_types_are_refused_to_non_members_and_inactive_groups(environment):
    as_user(environment, "stranger")
    assert environment.client.get(f"{LIST_PATH}/types").status_code == 403
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/inactive-grp/actions/types").status_code == 403


# --------------------------------------------------------------------------
# Action options: tenant Key Vault reminder defaults (a read capability, §9.2)
# --------------------------------------------------------------------------

REMINDER_KEYS = {"storage_enabled", "reminders_enabled", "require_expiration", "lead_days", "contact_email"}


@pytest.mark.parametrize("role", READER_ROLES)
def test_action_options_offered_to_every_member_role(environment, role):
    # The group editor reads only these five reminder defaults here, so the surface
    # is a read capability gated like the list, not a personal agent-settings read.
    as_user(environment, ROLE_USER[role])
    response = environment.client.get(OPTIONS_PATH)
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    reminders = response.get_json()["secret_reminders"]
    assert set(reminders) == REMINDER_KEYS
    # The block carries no allow_user_* key or any other option leakage.
    assert not any(key.startswith("allow_user_") for key in reminders)
    assert reminders["reminders_enabled"] is True
    assert reminders["require_expiration"] is True
    assert reminders["lead_days"] == 45
    assert reminders["contact_email"] == "kv@example.com"


def test_action_options_refused_to_non_members(environment):
    as_user(environment, "stranger")
    assert environment.client.get(OPTIONS_PATH).status_code == 403


def test_action_options_refused_for_inactive_group(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/inactive-grp/action-options").status_code == 403


def test_action_options_refused_when_unavailable(environment):
    environment.settings["allow_group_plugins"] = False
    as_user(environment, "owner")
    assert environment.client.get(OPTIONS_PATH).status_code == 403


def test_action_options_readable_for_locked_and_upload_disabled(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/locked-grp/action-options").status_code == 200
    assert environment.client.get("/api/groups/upload-disabled-grp/action-options").status_code == 200


def test_action_options_lead_days_is_clamped(environment):
    as_user(environment, "owner")
    environment.settings["key_vault_secret_expiration_default_lead_days"] = 99999
    high = environment.client.get(OPTIONS_PATH).get_json()["secret_reminders"]
    assert high["lead_days"] == 3650
    environment.settings["key_vault_secret_expiration_default_lead_days"] = 0
    low = environment.client.get(OPTIONS_PATH).get_json()["secret_reminders"]
    assert low["lead_days"] == 1
    environment.settings["key_vault_secret_expiration_default_lead_days"] = "not-a-number"
    fallback = environment.client.get(OPTIONS_PATH).get_json()["secret_reminders"]
    assert fallback["lead_days"] == 30


def test_action_options_contact_email_is_capped(environment):
    as_user(environment, "owner")
    environment.settings["key_vault_secret_expiration_default_contact_email"] = "a" * 500
    reminders = environment.client.get(OPTIONS_PATH).get_json()["secret_reminders"]
    assert len(reminders["contact_email"]) == 254


def test_action_options_rejects_query_and_body(environment):
    as_user(environment, "owner")
    assert environment.client.get(f"{OPTIONS_PATH}?view=editor").status_code == 400
    assert environment.client.get(
        OPTIONS_PATH, data=b"{}", content_type="application/json",
    ).status_code == 400


# --------------------------------------------------------------------------
# Global merge (read-only)
# --------------------------------------------------------------------------

def _seed_global(environment, action_id="g1"):
    return environment.global_container.create_item({
        "id": action_id, "name": f"global-{action_id}", "type": "openapi", "is_enabled": True,
        "endpoint": "https://global.example.test", "auth": {"type": "identity"},
    })


def test_global_actions_are_listed_read_only_when_merge_is_enabled(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    seed_action(environment.group_container, "a1")
    _seed_global(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    by_id = {item["id"]: item for item in body["actions"]}
    assert by_id["a1"]["is_group"] is True and by_id["a1"]["is_global"] is False
    assert by_id["g1"]["is_global"] is True and by_id["g1"]["is_group"] is False
    # A merged global action carries no group per-item operations.
    assert by_id["g1"]["action_actions"] == []


def test_single_read_of_a_merged_global_action_is_read_only(environment):
    # A provided (global) row a member sees in the list must open, read-only, not 404 (M4 §8 B4).
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    _seed_global(environment)
    as_user(environment, "owner")
    response = environment.client.get(f"{LIST_PATH}/g1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["read_only"] is True
    assert body["record"]["is_global"] is True
    assert body["record"]["action_actions"] == []


def test_single_read_of_a_global_id_is_404_when_merge_is_off(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = False
    _seed_global(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}/g1").status_code == 404


def test_writes_on_a_global_id_are_refused(environment):
    # A global id is not a group action; PATCH and DELETE must refuse and write nothing.
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    _seed_global(environment)
    as_user(environment, "owner")
    update = environment.client.patch(f"{LIST_PATH}/g1", json=write_body('"etag-1"', description="x"))
    assert update.status_code == 404
    assert environment.client.delete(f"{LIST_PATH}/g1").status_code == 404
    assert ("g1", "g1") in environment.global_container.records


# --------------------------------------------------------------------------
# Availability predicate (B3): one gate for the section and all six routes
# --------------------------------------------------------------------------

AVAILABILITY_FLAGS = ["enable_semantic_kernel", "per_user_semantic_kernel", "allow_group_agents", "allow_group_plugins"]


@pytest.mark.parametrize("flag", AVAILABILITY_FLAGS)
def test_every_route_refuses_when_an_availability_flag_is_off(environment, flag):
    seed = seed_action(environment.group_container, "a1")
    environment.settings[flag] = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/a1").status_code == 403
    assert environment.client.get(f"{LIST_PATH}/types").status_code == 403
    assert environment.client.post(LIST_PATH, json=write_body(name="x", type="openapi")).status_code == 403
    assert environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="y")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403


def test_every_route_refuses_when_governance_denies(environment, monkeypatch):
    seed = seed_action(environment.group_container, "a1")
    monkeypatch.setitem(
        sys.modules, "functions_governance", module_stub(
            "functions_governance",
            ensure_action_type_access=Mock(),
            ensure_global_action_access=Mock(),
            is_action_scope_access_allowed=Mock(return_value=False),
        ),
    )
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/a1").status_code == 403
    assert environment.client.get(f"{LIST_PATH}/types").status_code == 403
    assert environment.client.post(LIST_PATH, json=write_body(name="x", type="openapi")).status_code == 403
    assert environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="y")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403


def test_management_projection_is_empty_when_unavailable(environment):
    # The context's action_management block and the routes share one predicate, so a
    # disabled tenant offers no operations rather than advertising management it forbids.
    from functions_group_action_policy import group_action_management_operations
    active = environment.groups["group-a"]
    assert group_action_management_operations("owner", active, "Owner", environment.settings) == [
        "create", "edit", "delete", "test",
    ]
    environment.settings["allow_group_plugins"] = False
    assert group_action_management_operations("owner", active, "Owner", environment.settings) == []


def test_context_and_routes_call_the_same_availability_predicate():
    # Pin that the context section and the routes both resolve availability through
    # group_actions_available, so the two can never drift (like the publication pin).
    # Load the policy module from APP_ROOT rather than a bare import so this passes
    # without application/single_app on sys.path, as the rest of the suite does.
    spec = importlib.util.spec_from_file_location(
        "functions_group_action_policy", APP_ROOT / "functions_group_action_policy.py",
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    source = (APP_ROOT / "functions_group_action_access.py").read_text(encoding="utf-8")
    context_source = (APP_ROOT / "functions_workspace_context.py").read_text(encoding="utf-8")
    assert hasattr(policy, "group_actions_available")
    assert "group_actions_available" in source
    assert "group_actions_available" in context_source


# --------------------------------------------------------------------------
# B1: activity logging for committed group action writes (M4C §8)
# --------------------------------------------------------------------------

def test_create_logs_action_creation_with_group_scope(environment):
    as_user(environment, "owner")
    created = environment.client.post(LIST_PATH, json=write_body(
        name="logged-create", type="openapi", endpoint="https://api.example.test",
    ))
    assert created.status_code == 201
    action_id = created.get_json()["record"]["id"]
    environment.activity.log_action_creation.assert_called_once()
    kwargs = environment.activity.log_action_creation.call_args.kwargs
    assert kwargs["scope"] == "group" and kwargs["group_id"] == "group-a"
    assert kwargs["action_id"] == action_id and kwargs["action_name"] == "logged-create"
    assert kwargs["action_type"] == "openapi"
    environment.activity.log_action_update.assert_not_called()
    environment.activity.log_action_deletion.assert_not_called()


def test_update_logs_action_update_with_group_scope(environment):
    seed = seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="edited"))
    assert response.status_code == 200
    environment.activity.log_action_update.assert_called_once()
    kwargs = environment.activity.log_action_update.call_args.kwargs
    assert kwargs["scope"] == "group" and kwargs["group_id"] == "group-a" and kwargs["action_id"] == "a1"


def test_delete_logs_action_deletion_with_group_scope(environment):
    seed_action(environment.group_container, "a1")
    as_user(environment, "owner")
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 200
    environment.activity.log_action_deletion.assert_called_once()
    kwargs = environment.activity.log_action_deletion.call_args.kwargs
    assert kwargs["scope"] == "group" and kwargs["group_id"] == "group-a" and kwargs["action_id"] == "a1"


def test_a_raising_action_logger_never_fails_a_committed_write(environment):
    environment.activity.log_action_creation.side_effect = RuntimeError("logger down")
    as_user(environment, "owner")
    created = environment.client.post(LIST_PATH, json=write_body(
        name="still-created", type="openapi", endpoint="https://api.example.test",
    ))
    assert created.status_code == 201
    action_id = created.get_json()["record"]["id"]
    assert ("group-a", action_id) in environment.group_container.records
    warning = [
        call for call in environment.appinsights.log_event.call_args_list
        if call.args and "[WORKSPACE_ACTIVITY]" in str(call.args[0])
    ]
    assert warning, "A logging failure must emit the WORKSPACE_ACTIVITY warning."


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_a_refused_action_write_logs_nothing(environment, role):
    seed = seed_action(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    assert environment.client.post(LIST_PATH, json=write_body(name="x", type="openapi")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403
    as_user(environment, "owner")
    environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="first"))
    conflict = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="second"))
    assert conflict.status_code == 409
    environment.activity.log_action_creation.assert_not_called()
    environment.activity.log_action_deletion.assert_not_called()
    assert environment.activity.log_action_update.call_count == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
