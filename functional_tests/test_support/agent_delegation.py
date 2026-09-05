# agent_delegation.py
"""Isolated external-service seams for the real agent delegation contract.

Version: 0.261.093
Implemented in: 0.261.093

The application helper is executed unchanged. Only Cosmos, settings, governance,
group membership, cache invalidation, and audit services are replaced.
"""

import ast
import builtins
import importlib.util
import logging
import sys
import types
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Blueprint, Flask, jsonify, request, session
import werkzeug


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"


class CosmosHttpResponseError(Exception):
    def __init__(self, status_code=500, message="private provider diagnostic"):
        super().__init__(message)
        self.status_code = status_code


class CosmosResourceNotFoundError(CosmosHttpResponseError):
    def __init__(self):
        super().__init__(404)


class MatchConditions:
    IfNotModified = object()


def reference(agent_id="target-id", scope_type="personal", scope_id="actor"):
    return {"id": agent_id, "scope_type": scope_type, "scope_id": scope_id}


def manifest(target=None, **overrides):
    result = {
        "id": "action-id",
        "name": "delegate_task",
        "displayName": "Call specialist",
        "type": "agent",
        "endpoint": "internal://agent",
        "auth": {"type": "user"},
        "additionalFields": {"target_agent": target or reference()},
        "is_enabled": True,
    }
    result.update(overrides)
    return result


def module_stub(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


class DelegationServices:
    def __init__(self):
        self.settings = {
            "enable_semantic_kernel": True,
            "allow_user_agents": True,
            "allow_user_plugins": True,
            "allow_group_agents": True,
            "allow_group_plugins": True,
            "enable_group_workspaces": True,
            "merge_global_semantic_kernel_with_workspace": True,
            "require_owner_for_group_agent_management": False,
        }
        self.records = {}
        self.containers = {}
        self.roles = {("actor", "group-a"): "Owner", ("actor", "group-b"): "Owner"}
        self.denied_features = set()
        self.denied_actions = set()
        self.denied_agents = set()
        self.governance = module_stub(
            "functions_governance",
            ensure_governance_access=Mock(side_effect=self.check_governance),
            ensure_action_type_access=Mock(side_effect=self.check_action_type),
            ensure_global_action_access=Mock(side_effect=self.check_global_action),
        )
        self.groups = module_stub(
            "functions_group",
            assert_group_role=Mock(side_effect=self.check_group_role),
            require_active_group=Mock(return_value="group-a"),
            update_active_group_for_user=Mock(),
        )
        self.settings_module = module_stub(
            "functions_settings",
            get_settings=Mock(side_effect=lambda: deepcopy(self.settings)),
            get_user_settings=Mock(return_value={"settings": {"activeGroupOid": "group-a"}}),
            update_user_settings=Mock(),
        )
        self.activity = module_stub("functions_activity_logging", log_agent_update=Mock())
        self.appinsights = module_stub("functions_appinsights", log_event=Mock())
        self.cache = module_stub(
            "functions_chat_bootstrap_cache",
            bump_chat_bootstrap_global_cache_version=Mock(),
            bump_chat_bootstrap_user_cache_version=Mock(),
        )
        config = module_stub("config")
        for kind in ("agents", "actions"):
            for scope in ("personal", "group", "global"):
                container = Mock()
                self.records[kind, scope] = {}
                container.read_item.side_effect = self.reader(kind, scope)
                container.query_items.side_effect = self.query(kind, scope)
                self.containers[kind, scope] = container
                setattr(config, f"cosmos_{scope}_{kind}_container", container)
        azure = module_stub("azure")
        core = module_stub("azure.core", MatchConditions=MatchConditions)
        cosmos = module_stub("azure.cosmos")
        exceptions = module_stub(
            "azure.cosmos.exceptions",
            CosmosHttpResponseError=CosmosHttpResponseError,
            CosmosResourceNotFoundError=CosmosResourceNotFoundError,
        )
        azure.core, azure.cosmos, cosmos.exceptions = core, cosmos, exceptions
        self.modules = {
            module.__name__: module for module in (
                config, azure, core, cosmos, exceptions, self.governance,
                self.groups, self.settings_module, self.activity, self.appinsights, self.cache,
            )
        }

    def reader(self, kind, scope):
        def read_item(*, item, partition_key):
            record = self.records[kind, scope].get((partition_key, item))
            if record is None:
                raise CosmosResourceNotFoundError()
            return deepcopy(record)
        return read_item

    def query(self, kind, scope):
        def query_items(*, query, parameters, **kwargs):
            values = {value["name"]: value["value"] for value in parameters}
            records = self.records[kind, scope].values()
            return [
                deepcopy(record) for record in records
                if ("@type" not in values or record.get("type") == values["@type"])
                and (
                    "@scope_id" not in values
                    or record.get("user_id" if scope == "personal" else "group_id") == values["@scope_id"]
                )
            ]
        return query_items

    def check_group_role(self, user_id, group_id, *, allowed_roles):
        role = self.roles.get((user_id, group_id))
        if role not in allowed_roles:
            raise PermissionError("private membership diagnostic")
        return role

    def check_governance(self, feature, user_id, **kwargs):
        if feature in self.denied_features or kwargs.get("item_id") in self.denied_agents:
            raise PermissionError("private governance diagnostic")

    def check_action_type(self, feature, user_id, action_type, scope_type):
        if feature in self.denied_features:
            raise PermissionError("private action policy diagnostic")

    def check_global_action(self, user_id, action):
        if action["id"] in self.denied_actions:
            raise PermissionError("private global action diagnostic")

    def add(self, kind, scope, scope_id, record):
        record = deepcopy(record)
        if scope == "personal":
            record.setdefault("user_id", scope_id)
        elif scope == "group":
            record.setdefault("group_id", scope_id)
        record.setdefault("_etag", '"stored-etag"')
        partition = record["id"] if scope == "global" else scope_id
        self.records[kind, scope][partition, record["id"]] = record
        return record

    def add_agent(self, agent_id="target-id", scope="personal", scope_id="actor", **fields):
        return self.add("agents", scope, scope_id, {
            "id": agent_id, "name": "shared_name", "display_name": "Specialist",
            "agent_type": "local", "is_enabled": True, **fields,
        })

    def add_action(self, scope="personal", scope_id="actor", target=None, **fields):
        return self.add("actions", scope, scope_id, manifest(target, **fields))


@contextmanager
def delegation_environment():
    services = DelegationServices()
    spec = importlib.util.spec_from_file_location(
        "_tested_functions_agent_delegation", APP_ROOT / "functions_agent_delegation.py",
    )
    helper = importlib.util.module_from_spec(spec)
    with ExitStack() as stack:
        stack.enter_context(patch.dict(sys.modules, services.modules))
        stack.enter_context(patch.object(builtins, "kernel_reload_needed", False, create=True))
        # Flask 2's client reads this version attribute, removed by Werkzeug 3.
        if not hasattr(werkzeug, "__version__"):
            stack.enter_context(patch.object(werkzeug, "__version__", version("werkzeug"), create=True))
        spec.loader.exec_module(helper)
        yield helper, services


def execute_functions(filename, names, namespace, *, blueprint=None):
    """Execute actual definitions/decorators without importing unrelated Azure routes."""
    tree = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"))
    selected = []
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif blueprint and isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == blueprint for target in node.targets):
                selected.append(node)
        elif blueprint and isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            function = node.value.func
            if (
                isinstance(function, ast.Attribute) and function.attr == "before_request"
                and isinstance(function.value, ast.Name) and function.value.id == blueprint
            ):
                selected.append(node)
    assert found == set(names), f"Missing executable definitions: {set(names) - found}"
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)


def delegation_route_app(helper, services, configure=None):
    app = Flask("agent_delegation_contract_tests")
    app.config.update(TESTING=True, SECRET_KEY="test-only-session-signing")
    namespace = {
        "__name__": __name__, "Blueprint": Blueprint, "jsonify": jsonify,
        "request": request, "session": session, "wraps": wraps,
        "debug_print": Mock(), "log_event": Mock(), "logging": logging,
        "get_settings": services.settings_module.get_settings,
        "check_user_access_status": Mock(return_value=(True, None)),
        "CosmosHttpResponseError": CosmosHttpResponseError,
        "AgentDelegationConflictError": helper.AgentDelegationConflictError,
        "update_agent_delegation_bindings": helper.update_agent_delegation_bindings,
        "build_agent_delegation_catalog": helper.build_agent_delegation_catalog,
        "swagger_route": Mock(side_effect=lambda **kwargs: lambda function: function),
        "get_auth_security": Mock(return_value=[{"sessionAuth": []}]),
    }
    execute_functions("functions_authentication.py", {
        "apply_blueprint_auth", "login_required_blueprint", "login_required",
        "user_required", "admin_required", "get_current_user_id",
    }, namespace)
    execute_functions("functions_settings.py", {"enabled_required"}, namespace)
    execute_functions("route_backend_agents.py", {
        "_save_agent_action_bindings_response",
        "update_personal_agent_action_bindings",
        "update_group_agent_action_bindings",
        "update_global_agent_action_bindings",
    }, namespace, blueprint="bpa")
    execute_functions(
        "route_backend_plugins.py", {"get_agent_action_targets"}, namespace, blueprint="bpap",
    )
    if configure is not None:
        configure(namespace)
    app.register_blueprint(namespace["bpa"])
    app.register_blueprint(namespace["bpap"])
    return app, namespace
