# test_plugin_routes_cosmos_contract.py
"""Runtime evidence for the plugin route owners' Cosmos response contracts.

Version: 0.261.353
Implemented in: 0.261.352

Execute unchanged route and legacy-validator definitions with the installed SDK's
CosmosDict point responses and offline external services. This covers the owners
whose module fingerprints changed with PR #1787's SQL diagnostics.
"""

import ast
import builtins
from copy import deepcopy
import logging
import os
import re
from types import SimpleNamespace
from unittest.mock import Mock

from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Blueprint, Flask, current_app, jsonify, request
import pytest

from functions_action_manifest import McpConfigurationError, is_retired_mcp_stdio, resolve_action_type
from test_support.agent_delegation import APP_ROOT, execute_functions
from test_support.m365 import CosmosContainer
from test_support.offline_bootstrap import OfflineCosmos


@pytest.fixture
def plugin_routes(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    namespace = {
        "__name__": __name__,
        "bpap": Blueprint("plugin_cosmos_contract", __name__),
        "jsonify": jsonify, "request": request, "current_app": current_app,
        "logging": logging, "os": os, "re": re, "builtins": builtins,
        "login_required": lambda function: function,
        "user_required": lambda function: function,
        "admin_required": lambda function: function,
        "enabled_required": lambda *args: lambda function: function,
        "swagger_route": lambda **kwargs: lambda function: function,
        "get_auth_security": lambda: [],
        "get_current_user_id": lambda: "actor",
        "log_event": Mock(),
        "log_action_update": Mock(),
        "log_action_creation": Mock(),
        "log_action_deletion": Mock(),
        "azure_cosmos": SimpleNamespace(exceptions=exceptions),
        "CosmosHttpResponseError": exceptions.CosmosHttpResponseError,
        "McpConfigurationError": McpConfigurationError,
        "is_retired_mcp_stdio": is_retired_mcp_stdio,
        "resolve_action_type": resolve_action_type,
    }
    # Load the real validator and its constants without unrelated app bootstrap.
    tree = ast.parse((APP_ROOT / "json_schema_validation.py").read_text(encoding="utf-8"))
    validator_names = {
        "LegacyActionCreationError", "LEGACY_ACTION_CREATION_MESSAGE",
        "ACTION_MIGRATION_ID_PREFIX", "is_legacy_msgraph_type", "validate_legacy_action_update",
    }
    definitions = [
        node for node in tree.body
        if getattr(node, "name", None) in validator_names
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in validator_names for target in node.targets)
        )
    ]
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "json_schema_validation.py", "exec"), namespace)
    namespace["validate_legacy_action_update"] = Mock(wraps=namespace["validate_legacy_action_update"])
    execute_functions(
        "route_backend_plugins.py", {"set_user_plugins", "edit_plugin", "test_cosmos_connection"}, namespace,
    )
    monkeypatch.setattr(builtins, "kernel_reload_needed", False, raising=False)
    app.register_blueprint(namespace["bpap"])
    return app.test_client(), namespace


@pytest.mark.parametrize("owner", ["actor", "another-user", None])
def test_personal_legacy_update_consumes_sdk_point_response(plugin_routes, owner):
    client, namespace = plugin_routes
    container = CosmosContainer(partition_field="user_id")
    action = {"id": "action-id", "name": "historical", "type": "msgraph", "user_id": "actor"}
    stored = None
    if owner is not None:
        stored = container.create_item({**action, "user_id": owner})
        assert isinstance(stored, CosmosDict)
    saved = Mock()
    namespace.update({
        "cosmos_personal_actions_container": container,
        "get_global_actions": lambda: [],
        "get_personal_actions": lambda *args, **kwargs: [deepcopy(action)],
        "list_legacy_personal_actions": lambda *args: [],
        "SecretReturnType": SimpleNamespace(NAME="name"),
        "LEGACY_ACTION_PREFIX": "legacy-action-",
        "_prepare_personal_action_payload": lambda *args, **kwargs: (deepcopy(action), None),
        "save_personal_action": saved,
    })

    response = client.post("/api/user/plugins", json=[action])
    existing = namespace["validate_legacy_action_update"].call_args.args[1]

    if owner == "actor":
        assert response.status_code == 200
        assert response.json == {"success": True}
        assert isinstance(stored, CosmosDict)
        assert isinstance(existing, CosmosDict)
        assert existing["_etag"] == stored["_etag"]
        assert type(existing["user_id"]) is str
        saved.assert_called_once_with("actor", action)
    else:
        assert response.status_code == 400
        assert existing is None
        saved.assert_not_called()


@pytest.mark.parametrize("stored_name", ["historical", "different-name", None])
def test_global_legacy_update_consumes_sdk_point_response(plugin_routes, stored_name):
    client, namespace = plugin_routes
    container = CosmosContainer(partition_field="id")
    action = {"id": "action-id", "name": "historical", "type": "msgraph"}
    stored = None
    if stored_name is not None:
        stored = container.create_item({**action, "name": stored_name})
        assert isinstance(stored, CosmosDict)
    saved = Mock()
    namespace.update({
        "cosmos_global_actions_container": container,
        "get_global_actions": lambda **kwargs: [deepcopy(action)],
        "_apply_plugin_runtime_defaults": lambda action: None,
        "apply_plugin_validation_defaults": lambda action: action,
        "discover_plugin_types": lambda **kwargs: ["msgraph"],
        "validate_plugin": lambda action: None,
        "PluginHealthChecker": SimpleNamespace(validate_plugin_manifest=lambda *args: (True, [])),
        "_enforce_mcp_destination_policy": lambda *args, **kwargs: None,
        "WORKSPACE_IDENTITY_SCOPE_GLOBAL": "global",
        "get_merged_plugin_settings": lambda *args: {},
        "_validate_action_identity_for_scope": lambda *args: None,
        "save_global_action": saved,
        "_redact_plugin_for_logging": lambda action: {"type": action["type"]},
    })

    response = client.put("/api/admin/plugins/historical", json=action)
    existing = namespace["validate_legacy_action_update"].call_args.args[1]

    if stored_name == "historical":
        assert response.status_code == 200
        assert response.json == {"success": True}
        assert isinstance(stored, CosmosDict)
        assert isinstance(existing, CosmosDict)
        assert existing["_etag"] == stored["_etag"]
        saved.assert_called_once_with({**action, "metadata": {}, "additionalFields": {}}, user_id="actor")
    else:
        assert response.status_code == (404 if stored_name else 400)
        if stored_name:
            assert isinstance(existing, CosmosDict)
        else:
            assert existing is None
        saved.assert_not_called()


@pytest.mark.parametrize("rows", [[], ["existing-document-id"]])
def test_cosmos_connection_consumes_lazy_query_results(plugin_routes, monkeypatch, rows):
    client, namespace = plugin_routes
    cosmos = OfflineCosmos()
    container = cosmos.database.get_container_client("records")
    consumed = []

    def query_items(*, query, enable_cross_partition_query, max_item_count, response_hook):
        assert query == "SELECT TOP 1 VALUE c.id FROM c"
        assert enable_cross_partition_query is True
        assert max_item_count == 1
        yield from rows
        response_hook({"x-ms-request-charge": "1.5"}, None)
        consumed.append(True)

    monkeypatch.setattr(container, "query_items", query_items)
    constructor = Mock(return_value=cosmos)
    credential = object()
    namespace.update({
        "azure_cosmos": SimpleNamespace(CosmosClient=constructor, exceptions=exceptions),
        "DefaultAzureCredential": lambda: credential,
        "validate_azure_cosmos_endpoint": lambda endpoint: endpoint,
        "_load_existing_plugin_for_test": lambda *args, **kwargs: None,
    })

    response = client.post("/api/plugins/test-cosmos-connection", json={
        "endpoint": "https://offline.documents.azure.com",
        "database_name": "database", "container_name": "records", "timeout": 100,
    })

    assert response.status_code == 200
    assert response.json["success"] is True
    assert consumed == [True]
    constructor.assert_called_once_with(
        "https://offline.documents.azure.com", credential=credential, timeout=30, connection_timeout=30,
    )
    assert namespace["log_event"].call_args.kwargs["extra"]["request_charge"] == "1.5"
