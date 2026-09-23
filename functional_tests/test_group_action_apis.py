# test_group_action_apis.py
"""
Functional tests for the immutable-target group action APIs.
Version: 0.261.137
Implemented in: 0.261.137

The real policy, access, projection and route modules run against the real
personal-editor authoring engine (``functions_workspace_authoring``), executed
unchanged over an in-memory Cosmos stub that honours ETag conditional writes.
Group membership, status and settings are local test seams; the group is always
taken from the path, so a stale active group can never redirect or widen a
request. Key Vault storage is disabled, so no live secret backend is required,
and network access is prohibited.
"""

import importlib.util
import json
import re
import socket
import sys
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace
from typing import Iterable
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import (
    APP_ROOT,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
    MatchConditions,
    execute_functions,
    module_stub,
)
from test_support.versioning import assert_app_version_at_least


LIST_PATH = "/api/groups/group-a/actions"


class ActionContainer:
    """An in-memory Cosmos stub for a single (kind, scope) that enforces ETags."""

    def __init__(self):
        self.records = {}
        self._sequence = 0

    def _next_etag(self):
        self._sequence += 1
        return f'"etag-{self._sequence}"'

    def create_item(self, body):
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        key = (doc.get("group_id") or doc["id"], doc["id"])
        if key in self.records:
            raise CosmosHttpResponseError(409)
        self.records[key] = doc
        return deepcopy(doc)

    def read_item(self, item, partition_key):
        doc = self.records.get((partition_key, item))
        if doc is None:
            raise CosmosResourceNotFoundError()
        return deepcopy(doc)

    def replace_item(self, item, body, etag=None, match_condition=None):
        key = (body.get("group_id") or item, item)
        current = self.records.get(key)
        if current is None:
            raise CosmosHttpResponseError(404)
        if etag is not None and current.get("_etag") != etag:
            raise CosmosHttpResponseError(412)
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        self.records[key] = doc
        return deepcopy(doc)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        key = (partition_key, item)
        current = self.records.get(key)
        if current is None:
            raise CosmosHttpResponseError(404)
        if etag is not None and current.get("_etag") != etag:
            raise CosmosHttpResponseError(412)
        del self.records[key]

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in (parameters or [])}
        rows = [
            deepcopy(record) for (partition, _), record in self.records.items()
            if partition_key is None or partition == partition_key
        ]
        for field, param in re.findall(r"c\.(\w+)\s*=\s*(@\w+)", query):
            if param in values:
                rows = [record for record in rows if record.get(field) == values[param]]
        if "STRINGEQUALS" in query and "@name" in values:
            expected = str(values["@name"]).lower()
            rows = [record for record in rows if str(record.get("name") or "").lower() == expected]
        if "SELECT c.id" in query:
            rows = [{"id": record["id"]} for record in rows]
        return rows


def group(group_id, status="active"):
    return {
        "id": group_id,
        "name": f"Group {group_id}",
        "status": status,
        "owner": {"id": "owner"},
        "admins": ["admin"],
        "documentManagers": ["manager"],
        "users": [{"userId": "member"}],
    }


def seed_action(container, action_id, group_id="group-a", **changes):
    doc = {
        "id": action_id,
        "name": f"action-{action_id}",
        "displayName": f"Action {action_id}",
        "description": "A shared action.",
        "type": "openapi",
        "endpoint": "https://api.example.test",
        "auth": {"type": "identity"},
        "additionalFields": {},
        "metadata": {},
        "group_id": group_id,
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "owner",
        "modified_at": "2026-01-01T00:00:00Z",
        "modified_by": "owner",
        "_rid": "cosmos-internal-rid",
    }
    doc.update(changes)
    return container.create_item(doc)


def _fake_prepare(user_id, group_id, plugin, settings, existing):
    """A light stand-in for route_backend_plugins._prepare_group_action_payload.

    It exercises the real merge/preserve/conditional-write path without pulling
    in the heavy plugin governance chain: it only asserts a name and type and
    fills the same defaults the real preparer does.
    """
    prepared = {key: value for key, value in plugin.items() if not key.startswith("_")}
    if not str(prepared.get("name") or "").strip():
        return None, (jsonify({"error": "A name is required."}), 400)
    prepared.setdefault("type", "openapi")
    prepared.setdefault("displayName", prepared.get("name"))
    prepared.setdefault("description", "")
    prepared.setdefault("metadata", {})
    prepared.setdefault("additionalFields", {})
    prepared.setdefault("endpoint", "")
    return prepared, None


@pytest.fixture
def environment(monkeypatch):
    settings = {
        "enable_group_workspaces": True,
        "enable_semantic_kernel": True,
        "per_user_semantic_kernel": True,
        "allow_group_agents": True,
        "allow_group_plugins": True,
        "merge_global_semantic_kernel_with_workspace": False,
        "require_owner_for_group_agent_management": False,
        "enable_key_vault_secret_storage": False,
        "enable_key_vault_secret_expiration_reminders": True,
        "key_vault_secret_expiration_require_expiration": True,
        "key_vault_secret_expiration_default_lead_days": 45,
        "key_vault_secret_expiration_default_contact_email": "kv@example.com",
    }
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in group action tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        groups = {
            "group-a": group("group-a"),
            "group-b": group("group-b"),
            "locked-grp": group("locked-grp", status="locked"),
            "upload-disabled-grp": group("upload-disabled-grp", status="upload_disabled"),
            "inactive-grp": group("inactive-grp", status="inactive"),
            "haunted-grp": group("haunted-grp", status="haunted"),
        }

        group_container = ActionContainer()
        global_container = ActionContainer()

        # --- config container seam ----------------------------------------
        config = module_stub("config")
        config.cosmos_group_actions_container = group_container
        config.cosmos_global_actions_container = global_container
        scoped.setitem(sys.modules, "config", config)

        # --- settings seam -------------------------------------------------
        settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        scoped.setitem(sys.modules, "functions_settings", module_stub(
            "functions_settings",
            get_settings=lambda: settings,
            enabled_required=settings_namespace["enabled_required"],
            sanitize_settings_for_user=lambda data: data,
        ))

        # --- chat bootstrap cache seam ------------------------------------
        scoped.setitem(sys.modules, "functions_chat_bootstrap_cache", module_stub(
            "functions_chat_bootstrap_cache",
            bump_chat_bootstrap_global_cache_version=Mock(),
            bump_chat_bootstrap_user_cache_version=Mock(),
        ))

        # --- group membership seam (real role/status logic) ---------------
        group_namespace = {
            "Iterable": Iterable,
            "find_group_by_id": lambda group_id: deepcopy(groups.get(group_id)),
        }
        execute_functions("functions_group.py", {
            "get_user_role_in_group", "assert_group_role", "check_group_status_allows_operation",
        }, group_namespace)
        scoped.setitem(sys.modules, "functions_group", module_stub(
            "functions_group",
            find_group_by_id=group_namespace["find_group_by_id"],
            get_user_role_in_group=group_namespace["get_user_role_in_group"],
            assert_group_role=group_namespace["assert_group_role"],
            check_group_status_allows_operation=group_namespace["check_group_status_allows_operation"],
        ))

        # --- authoring-engine service seams (Key Vault disabled) ----------
        scoped.setitem(sys.modules, "functions_ai_connections", module_stub(
            "functions_ai_connections", filter_model_endpoints_by_capability=Mock(return_value=[]),
        ))
        scoped.setitem(sys.modules, "functions_appinsights", module_stub(
            "functions_appinsights", log_event=Mock(),
        ))
        scoped.setitem(sys.modules, "functions_keyvault", module_stub(
            "functions_keyvault",
            redact_plugin_secret_values=lambda record: record,
            validate_secret_name_dynamic=lambda value: False,
        ))
        scoped.setitem(sys.modules, "functions_governance", module_stub(
            "functions_governance",
            ensure_action_type_access=Mock(),
            ensure_global_action_access=Mock(),
            is_action_scope_access_allowed=Mock(return_value=True),
        ))
        scoped.setitem(sys.modules, "functions_agent_delegation", module_stub(
            "functions_agent_delegation",
            validate_agent_action_for_scope=lambda record, **kwargs: record,
        ))
        scoped.setitem(sys.modules, "functions_workspace_identities", module_stub(
            "functions_workspace_identities",
            validate_action_identity_reference=Mock(),
            WORKSPACE_IDENTITY_SCOPE_GROUP="group",
        ))
        scoped.setitem(sys.modules, "json_schema_validation", module_stub(
            "json_schema_validation", load_schema=lambda name: {},
        ))

        # --- azure seams --------------------------------------------------
        azure = module_stub("azure")
        azure_core = module_stub("azure.core", MatchConditions=MatchConditions)
        azure_cosmos = module_stub("azure.cosmos")
        azure_exceptions = module_stub(
            "azure.cosmos.exceptions",
            CosmosHttpResponseError=CosmosHttpResponseError,
            CosmosResourceNotFoundError=CosmosResourceNotFoundError,
        )
        azure.core, azure.cosmos = azure_core, azure_cosmos
        azure_cosmos.exceptions = azure_exceptions
        for name, module in {
            "azure": azure, "azure.core": azure_core,
            "azure.cosmos": azure_cosmos, "azure.cosmos.exceptions": azure_exceptions,
        }.items():
            scoped.setitem(sys.modules, name, module)

        # --- authentication seam ------------------------------------------
        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "get_current_user_id",
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        auth = module_stub("functions_authentication", **auth_namespace)
        scoped.setitem(sys.modules, "functions_authentication", auth)

        scoped.setitem(sys.modules, "swagger_wrapper", module_stub(
            "swagger_wrapper",
            swagger_route=lambda **_kwargs: (lambda function: function),
            get_auth_security=lambda: [{"sessionAuth": []}],
        ))

        def load_real(name):
            spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            scoped.setitem(sys.modules, name, module)
            spec.loader.exec_module(module)
            return module

        load_real("functions_group_action_policy")
        load_real("functions_workspace_authoring")
        access = load_real("functions_group_action_access")

        # --- route module executed without the heavy plugins import -------
        route_namespace = {
            "json": json, "wraps": wraps, "jsonify": jsonify, "request": request,
            "login_required": auth.login_required, "user_required": auth.user_required,
            "get_current_user_id": auth.get_current_user_id,
            "enabled_required": settings_namespace["enabled_required"],
            "swagger_route": lambda **_kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "GroupActionError": access.GroupActionError,
            "create_group_action": access.create_group_action,
            "delete_group_action": access.delete_group_action,
            "get_group_action": access.get_group_action,
            "get_group_action_options": access.get_group_action_options,
            "group_action_error_response": access.group_action_error_response,
            "list_group_actions": access.list_group_actions,
            "require_group_action_types_context": access.require_group_action_types_context,
            "update_group_action": access.update_group_action,
            "_prepare_group_action_payload": _fake_prepare,
            "get_plugin_types": lambda allowed_type_filter=None: jsonify([
                {"type": "openapi"}, {"type": "sql_schema"},
            ]),
            "build_action_editor_types": lambda types: [
                {
                    **entry,
                    "allowed_auth_types": ["identity", "key"],
                    "additional_fields_schema": {"type": "object"},
                    "metadata_schema": {"type": "object"},
                }
                for entry in types
            ],
            "is_action_type_access_allowed": lambda *args, **kwargs: True,
        }
        execute_functions("route_backend_group_actions_scoped.py", {
            "register_route_backend_group_actions_scoped", "_group_action_boundary",
            "_reject_query_parameters", "_reject_request_body", "_read_json_body",
        }, route_namespace)

        app = Flask("group_action_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_group_actions_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route_namespace["register_route_backend_group_actions_scoped"](blueprint)
        app.register_blueprint(blueprint)

        env = SimpleNamespace(
            settings=settings, groups=groups, group_container=group_container,
            global_container=global_container, access=access, app=app, client=app.test_client(),
        )
        as_user(env, "owner")
        yield env
        network.assert_not_called()


def as_user(env, user_id, roles=("User",)):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}


# Role -> the seeded user id that holds it in every group fixture.
ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "member"}
READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
WRITER_ROLES = ("Owner", "Admin")
NON_WRITER_ROLES = ("DocumentManager", "User")


def write_body(existing_revision=None, **updates):
    body = {"updates": updates}
    if existing_revision is not None:
        body["expected_revision"] = existing_revision
    return body


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

OPTIONS_PATH = "/api/groups/group-a/action-options"
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
