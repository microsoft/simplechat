# test_group_agent_apis.py
"""
Functional tests for the immutable-target group agent APIs.
Version: 0.261.138
Implemented in: 0.261.138

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
import uuid
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


LIST_PATH = "/api/groups/group-a/agents"
MASK = "***REDACTED***"


class AgentContainer:
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


def new_id():
    return str(uuid.uuid4())


def seed_agent(container, agent_id, group_id="group-a", **changes):
    doc = {
        "id": agent_id,
        "name": f"agent-{agent_id}",
        "display_name": f"Agent {agent_id}",
        "description": "A shared agent.",
        "instructions": "Be helpful.",
        "agent_type": "local",
        "actions_to_load": [],
        "other_settings": {},
        "group_id": group_id,
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "owner",
        "modified_at": "2026-01-01T00:00:00Z",
        "modified_by": "owner",
        "_rid": "cosmos-internal-rid",
    }
    doc.update(changes)
    return container.create_item(doc)


def _fake_prepare(user_id, group_id, agent, settings, existing):
    """A light stand-in for route_backend_agents._prepare_group_agent_payload.

    It exercises the real merge/preserve/conditional-write path without pulling in
    the heavy agent sanitize/knowledge/delegation chain: it only asserts a name
    and fills the same agent-shaped defaults the real preparer does.
    """
    prepared = {key: value for key, value in agent.items() if not key.startswith("_")}
    if not str(prepared.get("name") or "").strip():
        return None, (jsonify({"error": "A name is required."}), 400)
    prepared.setdefault("display_name", prepared.get("name"))
    prepared.setdefault("description", "")
    prepared.setdefault("instructions", "")
    prepared.setdefault("agent_type", "local")
    prepared.setdefault("actions_to_load", [])
    prepared.setdefault("other_settings", {})
    return prepared, None


@pytest.fixture
def environment(monkeypatch):
    settings = {
        "enable_group_workspaces": True,
        "enable_semantic_kernel": True,
        "per_user_semantic_kernel": True,
        "allow_group_agents": True,
        "allow_group_custom_endpoints": True,
        "allow_group_ai_foundry_agents": False,
        "allow_group_new_foundry_agents": False,
        "merge_global_semantic_kernel_with_workspace": False,
        "require_owner_for_group_agent_management": False,
        "enable_key_vault_secret_storage": False,
        "enable_key_vault_secret_expiration_reminders": True,
        "key_vault_secret_expiration_require_expiration": True,
        "key_vault_secret_expiration_default_lead_days": 45,
        "key_vault_secret_expiration_default_contact_email": "kv@example.com",
    }
    cache = SimpleNamespace(global_bumps=[], user_bumps=[])
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in group agent tests."))
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

        group_container = AgentContainer()
        global_container = AgentContainer()

        # --- config container seam ----------------------------------------
        config = module_stub("config")
        config.cosmos_group_agents_container = group_container
        config.cosmos_global_agents_container = global_container
        scoped.setitem(sys.modules, "config", config)

        # --- settings seam -------------------------------------------------
        settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        scoped.setitem(sys.modules, "functions_settings", module_stub(
            "functions_settings",
            get_settings=lambda: settings,
            enabled_required=settings_namespace["enabled_required"],
            sanitize_settings_for_user=lambda data: data,
            get_group_workflow_management_roles=lambda config: (
                ("Owner",) if config.get("require_owner_for_group_agent_management")
                else ("Owner", "Admin")
            ),
        ))

        # --- chat bootstrap cache seam ------------------------------------
        scoped.setitem(sys.modules, "functions_chat_bootstrap_cache", module_stub(
            "functions_chat_bootstrap_cache",
            bump_chat_bootstrap_global_cache_version=lambda *a, **k: cache.global_bumps.append((a, k)),
            bump_chat_bootstrap_user_cache_version=lambda *a, **k: cache.user_bumps.append((a, k)),
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
            "functions_ai_connections",
            filter_model_endpoints_by_capability=lambda endpoints, preserve_empty=False: endpoints,
        ))
        scoped.setitem(sys.modules, "functions_appinsights", module_stub(
            "functions_appinsights", log_event=Mock(),
        ))
        scoped.setitem(sys.modules, "functions_keyvault", module_stub(
            "functions_keyvault",
            redact_plugin_secret_values=lambda record: record,
            validate_secret_name_dynamic=lambda value: False,
            AGENT_SENSITIVE_SECRET_FIELDS=[],
        ))
        governance = module_stub(
            "functions_governance",
            is_governance_access_allowed=Mock(return_value=True),
            ensure_governance_access=Mock(),
            filter_governed_model_endpoints=lambda user_id, endpoints, key: endpoints,
        )
        scoped.setitem(sys.modules, "functions_governance", governance)
        scoped.setitem(sys.modules, "functions_agent_delegation", module_stub(
            "functions_agent_delegation",
            validate_agent_delegation_bindings=Mock(),
        ))
        scoped.setitem(sys.modules, "json_schema_validation", module_stub(
            "json_schema_validation", load_schema=lambda name: {},
        ))

        # --- lazily-imported group option/knowledge service seams ---------
        scoped.setitem(sys.modules, "route_backend_agents", module_stub(
            "route_backend_agents",
            build_combined_model_endpoints=lambda settings, user_id, group_id=None: [
                {"id": "global-1", "scope": "global", "models": ["gpt"], "azure_openai_gpt_key": "sk"},
                {"id": "group-1", "scope": "group", "models": ["gpt"], "azure_openai_gpt_key": "sk"},
                {"id": "user-1", "scope": "user", "models": ["gpt"], "azure_openai_gpt_key": "sk"},
            ],
        ))
        scoped.setitem(sys.modules, "functions_assigned_knowledge", module_stub(
            "functions_assigned_knowledge",
            build_assigned_knowledge_catalog=lambda *, user_id, agent_scope, group_id, is_admin: {
                "scope": agent_scope, "group_id": group_id, "items": [],
            },
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

        load_real("functions_group_agent_policy")
        load_real("functions_workspace_authoring")
        access = load_real("functions_group_agent_access")

        # --- route module executed without the heavy agent route import ---
        route_namespace = {
            "json": json, "wraps": wraps, "jsonify": jsonify, "request": request,
            "login_required": auth.login_required, "user_required": auth.user_required,
            "get_current_user_id": auth.get_current_user_id,
            "enabled_required": settings_namespace["enabled_required"],
            "swagger_route": lambda **_kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "GroupAgentError": access.GroupAgentError,
            "create_group_agent": access.create_group_agent,
            "delete_group_agent_record": access.delete_group_agent_record,
            "get_group_agent": access.get_group_agent,
            "get_group_agent_options": access.get_group_agent_options,
            "get_group_agent_knowledge": access.get_group_agent_knowledge,
            "group_agent_error_response": access.group_agent_error_response,
            "list_group_agents": access.list_group_agents,
            "update_group_agent": access.update_group_agent,
            "_prepare_group_agent_payload": _fake_prepare,
        }
        execute_functions("route_backend_group_agents_scoped.py", {
            "register_route_backend_group_agents_scoped", "_group_agent_boundary",
            "_reject_query_parameters", "_reject_request_body", "_read_json_body",
        }, route_namespace)

        app = Flask("group_agent_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_group_agents_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route_namespace["register_route_backend_group_agents_scoped"](blueprint)
        app.register_blueprint(blueprint)

        env = SimpleNamespace(
            settings=settings, groups=groups, group_container=group_container,
            global_container=global_container, access=access, app=app,
            client=app.test_client(), cache=cache, governance=governance,
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


def create_body(**updates):
    updates.setdefault("id", new_id())
    return {"updates": updates}


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


# --------------------------------------------------------------------------
# Reads: role and status
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_every_member_role_can_list_and_read(environment, role):
    seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["agents"]] == ["a1"]
    single = environment.client.get(f"{LIST_PATH}/a1")
    assert single.status_code == 200
    assert single.get_json()["record"]["id"] == "a1"


def test_list_envelope_and_single_resource_shape(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"agents"}
    item = body["agents"][0]
    assert item["id"] == "a1" and item["group_id"] == "group-a" and item["is_group"] is True
    assert "_rid" not in item and "_etag" not in item
    single = environment.client.get(f"{LIST_PATH}/a1").get_json()
    assert set(single) == {"record", "revision", "secret_paths", "read_only"}
    assert single["record"]["id"] == "a1"
    assert single["revision"]


def test_unknown_group_is_404_and_unknown_agent_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/agents").status_code == 404
    assert environment.client.get(f"{LIST_PATH}/ghost").status_code == 404


@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp"])
def test_read_only_statuses_are_readable(environment, group_id):
    environment.groups[group_id]  # ensure fixture present
    seed_agent(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    listing = environment.client.get(f"/api/groups/{group_id}/agents")
    assert listing.status_code == 200
    single = environment.client.get(f"/api/groups/{group_id}/agents/a1")
    assert single.status_code == 200
    # A read-only status advertises no management operations and marks read-only,
    # but chat (a catalogue property, not an edit right) remains.
    assert single.get_json()["record"]["agent_actions"] == ["chat"]
    assert single.get_json()["read_only"] is True


@pytest.mark.parametrize("group_id", ["inactive-grp", "haunted-grp"])
def test_inactive_and_unknown_statuses_are_denied(environment, group_id):
    seed_agent(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    assert environment.client.get(f"/api/groups/{group_id}/agents").status_code == 403
    assert environment.client.get(f"/api/groups/{group_id}/agents/a1").status_code == 403


# --------------------------------------------------------------------------
# Per-item action hints (edit/delete/chat)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writers_see_edit_delete_chat_in_active_group(environment, role):
    seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    item = environment.client.get(LIST_PATH).get_json()["agents"][0]
    assert item["agent_actions"] == ["edit", "delete", "chat"]


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writers_see_only_chat(environment, role):
    # chat is a catalogue property independent of edit rights, so every member
    # who may use group agents in chat sees it; non-writers get nothing more.
    seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    item = environment.client.get(LIST_PATH).get_json()["agents"][0]
    assert item["agent_actions"] == ["chat"]


def test_chat_hint_disappears_when_governance_denies_it(environment):
    seed_agent(environment.group_container, "a1")
    # Governance now denies group agents for this user: no availability, no chat.
    environment.governance.is_governance_access_allowed.return_value = False
    as_user(environment, "owner")
    # The whole surface is unavailable, so the list itself is refused.
    assert environment.client.get(LIST_PATH).status_code == 403


# --------------------------------------------------------------------------
# Writes: role policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writer_roles_can_create(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.post(LIST_PATH, json=create_body(name="created-by-writer"))
    assert response.status_code == 201
    body = response.get_json()
    assert body["record"]["name"] == "created-by-writer"
    assert body["record"]["is_group"] is True
    assert body["read_only"] is False


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writer_roles_cannot_create_edit_or_delete(environment, role):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    create = environment.client.post(LIST_PATH, json=create_body(name="x"))
    assert create.status_code == 403
    update = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="changed",
    ))
    assert update.status_code == 403
    delete = environment.client.delete(f"{LIST_PATH}/a1")
    assert delete.status_code == 403
    # Nothing was written.
    assert environment.group_container.records[("group-a", "a1")]["description"] == "A shared agent."


def test_owner_only_setting_refuses_admin_writes(environment):
    environment.settings["require_owner_for_group_agent_management"] = True
    seed_agent(environment.group_container, "a1")
    as_user(environment, "admin")
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    as_user(environment, "owner")
    assert environment.client.post(LIST_PATH, json=create_body(name="owner-write")).status_code == 201


# --------------------------------------------------------------------------
# Writes: status policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp", "inactive-grp"])
def test_writes_are_refused_outside_active_status(environment, group_id):
    seed = seed_agent(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    path = f"/api/groups/{group_id}/agents"
    assert environment.client.post(path, json=create_body(name="x")).status_code == 403
    update = environment.client.patch(f"{path}/a1", json=write_body(seed["_etag"], description="y"))
    assert update.status_code == 403
    assert environment.client.delete(f"{path}/a1").status_code == 403


# --------------------------------------------------------------------------
# Conditional writes and DELETE shape
# --------------------------------------------------------------------------

def test_update_requires_expected_revision(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json={"updates": {"description": "changed"}})
    assert response.status_code == 400


def test_update_with_stale_revision_conflicts_and_writes_nothing(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    stale = seed["_etag"]
    first = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(stale, description="first"))
    assert first.status_code == 200
    conflict = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(stale, description="second"))
    assert conflict.status_code == 409
    assert environment.group_container.records[("group-a", "a1")]["description"] == "first"


def test_update_success_returns_new_revision_and_persists(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="updated body",
    ))
    assert response.status_code == 200
    body = response.get_json()
    assert body["record"]["description"] == "updated body"
    assert body["revision"] != seed["_etag"]


def test_delete_takes_no_body_or_revision_and_removes_the_record(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/a1")
    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert ("group-a", "a1") not in environment.group_container.records


def test_create_requires_a_client_allocated_uuid(environment):
    as_user(environment, "owner")
    bad = environment.client.post(LIST_PATH, json={"updates": {"name": "no-id", "id": "not-a-uuid"}})
    assert bad.status_code == 400
    missing = environment.client.post(LIST_PATH, json={"updates": {"name": "no-id"}})
    assert missing.status_code == 400


# --------------------------------------------------------------------------
# Secret rules (mask keeps stored value, clear removes it)
# --------------------------------------------------------------------------

def test_stored_secret_is_masked_in_projection(environment):
    seed_agent(environment.group_container, "a1", azure_openai_gpt_key="sk-live-123")
    as_user(environment, "owner")
    record = environment.client.get(f"{LIST_PATH}/a1").get_json()
    assert record["record"]["azure_openai_gpt_key"] == MASK
    assert "/azure_openai_gpt_key" in record["secret_paths"]


def test_mask_preserves_stored_secret_on_update(environment):
    # A V1-created agent with a stored key is edited in V2 without re-entering the
    # key: sending the mask keeps the stored value (§2.1 round trip, edit half).
    seed = seed_agent(environment.group_container, "a1", azure_openai_gpt_key="sk-live-123")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="renamed", azure_openai_gpt_key=MASK,
    ))
    assert response.status_code == 200
    assert environment.group_container.records[("group-a", "a1")]["azure_openai_gpt_key"] == "sk-live-123"
    assert environment.group_container.records[("group-a", "a1")]["description"] == "renamed"


def test_clear_secret_paths_removes_the_stored_secret(environment):
    seed = seed_agent(environment.group_container, "a1", azure_openai_gpt_key="sk-live-123")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json={
        "updates": {}, "expected_revision": seed["_etag"], "clear_secret_paths": ["/azure_openai_gpt_key"],
    })
    assert response.status_code == 200
    assert "azure_openai_gpt_key" not in environment.group_container.records[("group-a", "a1")]


def test_editor_cannot_supply_a_secret_reference(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], azure_openai_gpt_key="https://vault.vault.azure.net/secrets/smuggled",
    ))
    assert response.status_code == 400


# --------------------------------------------------------------------------
# §2.2 cache bump on save and delete
# --------------------------------------------------------------------------

def test_save_and_delete_bump_the_bootstrap_cache(environment):
    as_user(environment, "owner")
    assert environment.cache.global_bumps == []
    created = environment.client.post(LIST_PATH, json=create_body(name="cache-agent"))
    assert created.status_code == 201
    assert len(environment.cache.global_bumps) == 1
    agent_id = created.get_json()["record"]["id"]
    revision = created.get_json()["revision"]
    updated = environment.client.patch(f"{LIST_PATH}/{agent_id}", json=write_body(revision, description="c"))
    assert updated.status_code == 200
    assert len(environment.cache.global_bumps) == 2
    deleted = environment.client.delete(f"{LIST_PATH}/{agent_id}")
    assert deleted.status_code == 200
    assert len(environment.cache.global_bumps) == 3


# --------------------------------------------------------------------------
# Transport hygiene: query parameters and request bodies
# --------------------------------------------------------------------------

def test_list_rejects_query_parameters(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?scope=global").status_code == 400


def test_delete_rejects_expected_revision_as_a_query_parameter(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/a1?expected_revision={seed['_etag']}")
    assert response.status_code == 400
    assert ("group-a", "a1") in environment.group_container.records


def test_read_rejects_a_request_body(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.get(
        f"{LIST_PATH}/a1", data=b"{}", content_type="application/json",
    )
    assert response.status_code == 400


def test_create_rejects_duplicate_fields(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH, data=b'{"updates": {"name": "a"}, "updates": {"name": "b"}}',
        content_type="application/json",
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Agent options: the group editor's options (a read capability)
# --------------------------------------------------------------------------

OPTIONS_PATH = "/api/groups/group-a/agent-options"


@pytest.mark.parametrize("role", READER_ROLES)
def test_agent_options_offered_to_every_member_role(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.get(OPTIONS_PATH)
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    body = response.get_json()
    assert set(body) >= {"agent_types", "settings", "model_endpoints", "builtin_actions"}


def test_agent_options_carry_no_personal_keys_or_endpoints(environment):
    as_user(environment, "owner")
    body = environment.client.get(OPTIONS_PATH).get_json()
    # No allow_user_* key anywhere in the settings block.
    assert not any(key.startswith("allow_user_") for key in body["settings"])
    # The group custom-endpoint flag is present (this is the group surface).
    assert "allow_group_custom_endpoints" in body["settings"]
    scopes = {endpoint.get("scope") for endpoint in body["model_endpoints"]}
    # A personal endpoint never appears on a group page.
    assert "user" not in scopes and "personal" not in scopes
    assert scopes <= {"global", "group"}


def test_agent_options_mask_endpoint_secrets(environment):
    as_user(environment, "owner")
    body = environment.client.get(OPTIONS_PATH).get_json()
    for endpoint in body["model_endpoints"]:
        assert endpoint.get("azure_openai_gpt_key") in (MASK, None)


def test_agent_options_non_manager_gets_no_models(environment):
    # A member with no write role gets an empty model list, gpt_model and default
    # selection, exactly as the personal builder does for non-managers.
    as_user(environment, "member")
    body = environment.client.get(OPTIONS_PATH).get_json()
    assert body["model_endpoints"] == []
    assert body["settings"]["gpt_model"] == {}
    assert body["settings"]["default_model_selection"] == {}


def test_agent_options_refused_when_unavailable(environment):
    environment.settings["allow_group_agents"] = False
    as_user(environment, "owner")
    assert environment.client.get(OPTIONS_PATH).status_code == 403


def test_agent_options_rejects_query_and_body(environment):
    as_user(environment, "owner")
    assert environment.client.get(f"{OPTIONS_PATH}?view=editor").status_code == 400
    assert environment.client.get(
        OPTIONS_PATH, data=b"{}", content_type="application/json",
    ).status_code == 400


# --------------------------------------------------------------------------
# Agent knowledge: assigned-knowledge catalogue for the named group
# --------------------------------------------------------------------------

KNOWLEDGE_PATH = "/api/groups/group-a/agent-knowledge"


@pytest.mark.parametrize("role", READER_ROLES)
def test_agent_knowledge_offered_to_every_member_role(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.get(KNOWLEDGE_PATH)
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    # The catalogue was resolved for THIS group, never the account's active group.
    body = response.get_json()
    assert body["scope"] == "group" and body["group_id"] == "group-a"


def test_agent_knowledge_ignores_the_active_group(environment):
    # group-b in the path resolves group-b's catalogue regardless of any active group.
    as_user(environment, "owner")
    body = environment.client.get("/api/groups/group-b/agent-knowledge").get_json()
    assert body["group_id"] == "group-b"


def test_agent_knowledge_refused_to_non_members(environment):
    as_user(environment, "stranger")
    assert environment.client.get(KNOWLEDGE_PATH).status_code == 403


def test_agent_knowledge_refused_for_inactive_group(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/inactive-grp/agent-knowledge").status_code == 403


# --------------------------------------------------------------------------
# Global merge (read-only)
# --------------------------------------------------------------------------

def _seed_global(environment, agent_id="g1"):
    return environment.global_container.create_item({
        "id": agent_id, "name": f"global-{agent_id}", "agent_type": "local", "is_enabled": True,
        "instructions": "Global agent.",
    })


def test_global_agents_are_listed_read_only_when_merge_is_enabled(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    seed_agent(environment.group_container, "a1")
    _seed_global(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    by_id = {item["id"]: item for item in body["agents"]}
    assert by_id["a1"]["is_group"] is True and by_id["a1"]["is_global"] is False
    assert by_id["g1"]["is_global"] is True and by_id["g1"]["is_group"] is False
    # A merged global agent carries no group per-item operations.
    assert by_id["g1"]["agent_actions"] == []


def test_single_read_of_a_merged_global_agent_is_read_only(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    _seed_global(environment)
    as_user(environment, "owner")
    response = environment.client.get(f"{LIST_PATH}/g1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["read_only"] is True
    assert body["record"]["is_global"] is True
    assert body["record"]["agent_actions"] == []


def test_single_read_of_a_global_id_is_404_when_merge_is_off(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = False
    _seed_global(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}/g1").status_code == 404


def test_writes_on_a_global_id_are_refused(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    _seed_global(environment)
    as_user(environment, "owner")
    update = environment.client.patch(f"{LIST_PATH}/g1", json=write_body('"etag-1"', description="x"))
    assert update.status_code == 404
    assert environment.client.delete(f"{LIST_PATH}/g1").status_code == 404
    assert ("g1", "g1") in environment.global_container.records


# --------------------------------------------------------------------------
# Cross-group isolation: the path group, never the active group
# --------------------------------------------------------------------------

def test_a_saved_agent_is_read_from_the_path_group_only(environment):
    seed_agent(environment.group_container, "a1", group_id="group-a")
    as_user(environment, "owner")
    # group-b in the path must not surface group-a's agent.
    assert environment.client.get("/api/groups/group-b/agents/a1").status_code == 404
    assert [item["id"] for item in environment.client.get(
        "/api/groups/group-b/agents").get_json()["agents"]] == []


# --------------------------------------------------------------------------
# Availability predicate: one gate for the section and every route
# --------------------------------------------------------------------------

AVAILABILITY_FLAGS = ["enable_semantic_kernel", "per_user_semantic_kernel", "allow_group_agents"]


@pytest.mark.parametrize("flag", AVAILABILITY_FLAGS)
def test_every_route_refuses_when_an_availability_flag_is_off(environment, flag):
    seed = seed_agent(environment.group_container, "a1")
    environment.settings[flag] = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/a1").status_code == 403
    assert environment.client.get(OPTIONS_PATH).status_code == 403
    assert environment.client.get(KNOWLEDGE_PATH).status_code == 403
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    assert environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="y")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403


def test_every_route_refuses_when_governance_denies(environment):
    seed = seed_agent(environment.group_container, "a1")
    environment.governance.is_governance_access_allowed.return_value = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/a1").status_code == 403
    assert environment.client.get(OPTIONS_PATH).status_code == 403
    assert environment.client.get(KNOWLEDGE_PATH).status_code == 403
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    assert environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="y")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403


def test_management_projection_is_empty_when_unavailable(environment):
    from functions_group_agent_policy import group_agent_management_operations
    active = environment.groups["group-a"]
    assert group_agent_management_operations("owner", active, "Owner", environment.settings) == [
        "create", "edit", "delete",
    ]
    environment.settings["allow_group_agents"] = False
    assert group_agent_management_operations("owner", active, "Owner", environment.settings) == []


def test_context_and_routes_call_the_same_availability_predicate():
    # Pin that the context section and the routes both resolve availability through
    # group_agents_available, so the two can never drift. Load the policy module
    # from APP_ROOT rather than a bare import so this passes without
    # application/single_app on sys.path, as the rest of the suite does.
    spec = importlib.util.spec_from_file_location(
        "functions_group_agent_policy", APP_ROOT / "functions_group_agent_policy.py",
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    access_source = (APP_ROOT / "functions_group_agent_access.py").read_text(encoding="utf-8")
    context_source = (APP_ROOT / "functions_workspace_context.py").read_text(encoding="utf-8")
    assert hasattr(policy, "group_agents_available")
    assert "group_agents_available" in access_source
    assert "group_agents_available" in context_source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
