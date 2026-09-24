# group_agent_harness.py
"""Shared, isolated harness for the native group agent endpoint tests (M4C).

Version: 0.261.157
Implemented in: 0.261.138

Extracted verbatim from ``test_group_agent_apis.py`` so the API suite and the
per-route fixture shape parity test (``test_group_agent_fixture_parity.py``)
drive the same real backend. The real policy, access, projection and route
modules run against the real personal-editor authoring engine
(``functions_workspace_authoring``), executed unchanged over an in-memory Cosmos
stub that honours ETag conditional writes. Group membership, status and settings
are local test seams; the group is always taken from the path, so a stale active
group can never redirect or widen a request. Key Vault storage is disabled, so no
live secret backend is required, and network access is prohibited.

Exports: the ``environment`` pytest fixture (function-scoped, monkeypatch-based),
the ``AgentContainer`` etag-enforcing Cosmos stub, the route paths, the
role constants, and the seed/body helpers the suites share. The one addition to
the extracted code is ``environment.routes``, the namespace the route module runs
in, so a test can substitute a closer stand-in for ``_prepare_group_agent_payload``;
the API suite does not use it.
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


LIST_PATH = "/api/groups/group-a/agents"
MASK = "***REDACTED***"
OPTIONS_PATH = "/api/groups/group-a/agent-options"
KNOWLEDGE_PATH = "/api/groups/group-a/agent-knowledge"


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
        appinsights = module_stub("functions_appinsights", log_event=Mock())
        scoped.setitem(sys.modules, "functions_appinsights", appinsights)
        activity = module_stub(
            "functions_activity_logging",
            log_agent_creation=Mock(), log_agent_update=Mock(), log_agent_deletion=Mock(),
            log_action_creation=Mock(), log_action_update=Mock(), log_action_deletion=Mock(),
        )
        scoped.setitem(sys.modules, "functions_activity_logging", activity)
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

        # The group agent options builder consults the real template submission
        # predicate; load only that pure function so the harness exercises the
        # shipped gate logic without the module's Cosmos/notification imports.
        templates_namespace = {}
        execute_functions(
            "functions_agent_templates.py",
            {"agent_template_submission_decision"},
            templates_namespace,
        )
        scoped.setitem(sys.modules, "functions_agent_templates", module_stub(
            "functions_agent_templates",
            agent_template_submission_decision=templates_namespace["agent_template_submission_decision"],
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
            activity=activity, appinsights=appinsights, routes=route_namespace,
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
