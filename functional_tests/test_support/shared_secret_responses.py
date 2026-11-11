# shared_secret_responses.py
"""Offline services for real legacy shared-resource routes and credential writes.

Version: 0.261.428
Implemented in: 0.261.428
"""

import importlib
import os
import sys
import uuid
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import Mock

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions
from flask import Blueprint, Flask, current_app

from test_support.agent_delegation import execute_functions
from test_support.group_action_harness import group
from test_support.m365 import CosmosContainer
from test_workspace_authoring_backend import environment


class SharedContainer(CosmosContainer):
    """Keep the SDK-shaped container's CAS semantics and filter scoped names."""

    def query_items(self, query, parameters=None, **kwargs):
        rows = list(super().query_items(query, parameters, **kwargs))
        values = {item["name"]: item["value"] for item in parameters or []}
        for field in ("name", "group_id", "user_id"):
            if f"@{field}" in values:
                expected = values[f"@{field}"]
                rows = [
                    row for row in rows
                    if (
                        str(row.get(field, "")).lower() == str(expected).lower()
                        if field == "name" and "STRINGEQUALS" in query
                        else row.get(field) == expected
                    )
                ]
        return rows

    def patch_item(self, item, partition_key, patch_operations, *, etag, match_condition):
        with self.lock:
            record = self.read_item(item, partition_key)
            for operation in patch_operations:
                if operation["op"] != "set" or operation["path"] != "/metadata/key_vault_secret_reminder_sync":
                    raise AssertionError("Unexpected editor reminder patch.")
                record.setdefault("metadata", {})["key_vault_secret_reminder_sync"] = deepcopy(operation["value"])
            return self.replace_item(item, record, etag=etag, match_condition=match_condition)

    def delete_item(self, item, partition_key, *, etag, match_condition):
        with self.lock:
            record = self.read_item(item, partition_key)
            if record["_etag"] != etag or match_condition != MatchConditions.IfNotModified:
                raise exceptions.CosmosHttpResponseError(status_code=412, message="ETag conflict.")
            return super().delete_item(item, partition_key)


def as_user(env, user_id, roles=("User",)):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}


def seed(env, kind, *, scope="group", group_id="group-a", **changes):
    record = {
        "id": str(uuid.uuid4()),
        "name": f"shared_{kind}",
        "description": "Shared capability",
        "enabled": True,
    }
    if kind == "actions":
        record.update({
            "type": "openapi", "displayName": "Shared action",
            "endpoint": "https://service.invalid", "auth": {"type": "key", "key": "CANARY-action-key"},
            "metadata": {}, "additionalFields": {},
        })
    else:
        record.update({
            "agent_type": "local", "display_name": "Shared agent",
            "instructions": "Internal instructions", "actions_to_load": [], "other_settings": {},
            "azure_openai_gpt_key": "CANARY-model-key",
        })
    if scope == "group":
        record["group_id"] = group_id
    record.update(changes)
    return env.containers[kind, scope].create_item(record)


@pytest.fixture
def shared_routes(environment):
    """Undo child SDK seams before the parent's ExitStack restores real modules."""
    with pytest.MonkeyPatch.context() as scoped:
        yield _build_shared_routes(environment, scoped)


def _build_shared_routes(environment, monkeypatch):
    env = environment
    services = env.services
    monkeypatch.setattr(env.identities, "WORKSPACE_IDENTITY_SCOPE_GROUP", "group", raising=False)
    services.settings.update({
        "merge_global_semantic_kernel_with_workspace": False,
        "allow_group_custom_endpoints": True,
        "allow_group_ai_foundry_agents": True,
        "allow_group_new_foundry_agents": True,
    })
    groups = {"group-a": group("group-a"), "group-b": group("group-b")}
    groups["group-b"]["users"] = [{"userId": "foreign"}]
    containers = {}
    for kind in ("actions", "agents"):
        for scope in ("group", "global"):
            container = SharedContainer("group_id" if scope == "group" else "id")
            containers[kind, scope] = container
            services.containers[kind, scope] = container
            services.records[kind, scope] = container.items
            monkeypatch.setattr(services.modules["config"], f"cosmos_{scope}_{kind}_container", container)
    monkeypatch.setitem(sys.modules, "azure.cosmos.exceptions", exceptions)
    monkeypatch.setattr(sys.modules["azure.core"], "MatchConditions", MatchConditions)
    services.modules["azure.cosmos"].exceptions = exceptions
    namespace = {
        **env.namespace, **vars(env.helper),
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Iterable": Iterable,
        "os": os, "current_app": current_app,
        "exceptions": exceptions, "azure_cosmos": SimpleNamespace(exceptions=exceptions),
        "find_group_by_id": lambda group_id: deepcopy(groups.get(group_id)),
        "functions_settings": services.settings_module,
        "resolve_delegation_group_scope": sys.modules["functions_agent_delegation"].resolve_delegation_group_scope,
        "get_group_workflow_management_roles": lambda settings: (
            ("Owner",) if settings.get("require_owner_for_group_agent_management") else ("Owner", "Admin")
        ),
        "WORKSPACE_IDENTITY_SCOPE_GROUP": "group",
        "cosmos_group_actions_container": containers["actions", "group"],
        "cosmos_group_agents_container": containers["agents", "group"],
        "keyvault_plugin_get_helper": env.keyvault.keyvault_plugin_get_helper,
        "keyvault_agent_get_helper": env.keyvault.keyvault_agent_get_helper,
        "hydrate_action_identity_reference": lambda record, *args, **kwargs: record,
        "is_global_action_access_allowed": lambda user_id, record: True,
        "filter_governed_model_endpoints": services.governance.filter_governed_model_endpoints,
        "is_governance_access_allowed": lambda feature, user_id: feature not in services.denied_features,
        "editor_error_response": Mock(wraps=env.helper.editor_error_response),
        "validate_mcp_tool_pinning_for_save": importlib.import_module(
            "functions_mcp_tool_pinning",
        ).validate_mcp_tool_pinning_for_save,
    }
    execute_functions("functions_group.py", {
        "get_user_role_in_group", "assert_group_role", "require_active_group",
    }, namespace)
    for name in ("assert_group_role", "find_group_by_id", "get_user_role_in_group", "require_active_group"):
        monkeypatch.setattr(services.groups, name, namespace[name], raising=False)
    monkeypatch.setattr(
        services.settings_module, "get_group_workflow_management_roles",
        namespace["get_group_workflow_management_roles"], raising=False,
    )
    execute_functions("functions_group_action_policy.py", {
        "group_action_write_roles", "group_action_management_operations",
    }, namespace)
    namespace["GROUP_ACTION_ADMIN_ROLES"] = ("Owner", "Admin")
    namespace["GROUP_ACTION_OPERATIONS"] = ("create", "edit", "delete", "test")
    namespace["group_actions_available"] = lambda user_id, settings: (True, None)
    execute_functions("functions_group_agent_policy.py", {
        "group_agent_write_roles", "group_agent_management_operations",
    }, namespace)
    namespace["GROUP_AGENT_OPERATIONS"] = ("create", "edit", "delete")
    namespace["group_agents_available"] = lambda user_id, settings: (True, None)
    execute_functions("functions_governance.py", {
        "filter_actions_by_action_type_access", "filter_governed_global_actions_for_user",
    }, namespace)
    execute_functions("functions_group_actions.py", {
        "get_group_actions", "get_governed_group_actions", "get_group_action", "_clean_action",
    }, namespace)
    execute_functions("functions_group_agents.py", {
        "get_group_agents", "get_group_agent", "_clean_agent",
    }, namespace)
    namespace["get_global_actions"] = lambda **kwargs: [
        env.keyvault.keyvault_plugin_get_helper(
            deepcopy(record), scope_value=record["id"], scope="global",
            return_type=kwargs.get("return_type", env.keyvault.SecretReturnType.TRIGGER),
        )
        for record in containers["actions", "global"].items.values()
    ]
    namespace["get_global_agents"] = lambda: [
        deepcopy(record) for record in containers["agents", "global"].items.values()
    ]
    namespace.update({
        "get_governed_personal_actions": lambda user_id: [],
        "list_legacy_personal_actions": lambda user_id: [],
        "log_action_creation": services.activity.log_action_creation,
        "log_action_update": services.activity.log_action_update,
        "log_agent_creation": services.activity.log_agent_creation,
        "log_agent_update": services.activity.log_agent_update,
    })
    namespace["bpap"] = Blueprint("shared_action_legacy", __name__)
    namespace["bpa"] = Blueprint("shared_agent_legacy", __name__)
    execute_functions("route_backend_plugins.py", {
        "get_group_actions_route", "get_group_action_route",
        "create_group_action_route", "update_group_action_route",
        "_normalize_group_action", "_normalize_global_action", "_merge_group_and_global_actions",
        "_prepare_group_action_payload", "get_user_plugins",
    }, namespace)
    execute_functions("route_backend_agents.py", {
        "get_group_agents_route", "get_group_agent_route",
        "create_group_agent_route", "update_group_agent_route",
        "_prepare_group_agent_payload", "get_global_agent_settings",
        "get_group_agent_settings", "get_global_agent_settings_for_users", "get_user_agents",
    }, namespace)
    app = Flask("shared_legacy_routes", root_path=env.app.root_path)
    app.config.update(TESTING=True, SECRET_KEY="synthetic-shared-route-session")
    app.register_blueprint(namespace["bpap"])
    app.register_blueprint(namespace["bpa"])
    result = SimpleNamespace(**{
        **vars(env), "app": app, "client": app.test_client(),
        "containers": containers, "groups": groups, "routes": namespace,
    })
    as_user(result, "owner")
    return result
