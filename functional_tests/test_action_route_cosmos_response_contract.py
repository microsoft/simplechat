# test_action_route_cosmos_response_contract.py
"""Runtime evidence for unchanged Cosmos owners in the edited action route module.

Version: 0.261.354
Implemented in: 0.261.354

The inventory invalidates module-wide source-only evidence after any route-module
edit. Execute the three real owners with the shared SDK-default container and
real legacy-update validator. No production storage behavior is changed.
"""

import builtins
import logging
import os
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Flask, current_app, jsonify, request, session
import pytest

import json_schema_validation as validation
from test_support.agent_delegation import execute_functions
from test_support.m365 import CosmosContainer


@pytest.fixture
def routes(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    monkeypatch.setattr(builtins, "kernel_reload_needed", False, raising=False)
    passthrough = lambda function: function
    namespace = {
        **vars(validation), "request": request, "session": session,
        "jsonify": jsonify, "current_app": current_app, "logging": logging, "os": os,
        "builtins": builtins, "bpap": SimpleNamespace(route=lambda *args, **kwargs: passthrough),
        "swagger_route": lambda **kwargs: passthrough, "get_auth_security": lambda: [],
        "login_required": passthrough, "user_required": passthrough, "admin_required": passthrough,
        "enabled_required": lambda feature: passthrough,
        "get_current_user_id": lambda: "actor", "log_event": Mock(), "debug_print": Mock(),
        "azure_cosmos": SimpleNamespace(exceptions=exceptions),
        "SecretReturnType": SimpleNamespace(NAME="name"),
        "LEGACY_ACTION_PREFIX": "legacy-action:",
        "get_global_actions": Mock(return_value=[]),
        "get_personal_actions": Mock(return_value=[]),
        "list_legacy_personal_actions": Mock(return_value=[]),
        "is_retired_mcp_stdio": lambda action: False,
        "_prepare_personal_action_payload": Mock(side_effect=lambda user, payload, **kwargs: (payload, None)),
        "_apply_plugin_runtime_defaults": Mock(),
        "apply_plugin_validation_defaults": lambda payload: payload,
        "resolve_action_type": lambda payload: payload["type"],
        "discover_plugin_types": lambda **kwargs: {"msgraph"},
        "validate_plugin": lambda payload: None,
        "validate_legacy_action_update": Mock(wraps=validation.validate_legacy_action_update),
        "PluginHealthChecker": SimpleNamespace(validate_plugin_manifest=lambda *args: (True, [])),
        "get_merged_plugin_settings": lambda kind, payload, directory: payload,
        "_validate_action_identity_for_scope": Mock(),
        "_enforce_mcp_destination_policy": Mock(),
        "WORKSPACE_IDENTITY_SCOPE_GLOBAL": "global",
        "McpDestinationPolicyError": type("McpDestinationPolicyError", (ValueError,), {}),
        "save_personal_action": Mock(), "save_global_action": Mock(),
        "log_action_update": Mock(), "_redact_plugin_for_logging": lambda value: value,
        "McpConfigurationError": type("McpConfigurationError", (ValueError,), {}),
    }
    execute_functions("route_backend_plugins.py", {"set_user_plugins", "edit_plugin", "test_cosmos_connection"}, namespace)
    return app, namespace


@pytest.mark.parametrize("scope", ["personal", "global"])
def test_action_route_point_reads_reach_real_legacy_validator_as_sdk_documents(routes, scope):
    app, namespace = routes
    container = CosmosContainer("user_id" if scope == "personal" else "id")
    record = {"id": "owned", "name": "legacy", "type": "msgraph", "user_id": "actor", "additionalFields": {}}
    saved = container.create_item(record)
    assert isinstance(saved, CosmosDict)
    namespace[f"cosmos_{scope}_actions_container"] = container
    namespace["get_personal_actions" if scope == "personal" else "get_global_actions"].return_value = [dict(saved)]
    with app.test_request_context("/actions", method="POST", json=[record] if scope == "personal" else record):
        response = namespace["set_user_plugins"]() if scope == "personal" else namespace["edit_plugin"]("legacy")
    assert response.status_code == 200, response.get_json()
    observed = namespace["validate_legacy_action_update"].call_args.args[1]
    assert isinstance(observed, CosmosDict)
    assert observed["_etag"] == saved["_etag"]
    assert observed["user_id"] == "actor"
    assert observed["id"] == "owned"
    writer = namespace["save_personal_action" if scope == "personal" else "save_global_action"]
    assert writer.call_count == 1
    assert container.items[container._key(record)] == dict(saved)


@pytest.mark.parametrize("scope", ["personal", "global"])
def test_action_route_missing_exact_point_read_cannot_fall_back_to_a_name(routes, scope):
    app, namespace = routes
    namespace[f"cosmos_{scope}_actions_container"] = CosmosContainer("user_id" if scope == "personal" else "id")
    record = {"id": "missing", "name": "legacy", "type": "msgraph", "additionalFields": {}}
    with app.test_request_context("/actions", method="POST", json=[record] if scope == "personal" else record):
        result = namespace["set_user_plugins"]() if scope == "personal" else namespace["edit_plugin"]("legacy")
    response, status = result
    assert status == 400
    assert response.get_json()["error"] == validation.LEGACY_ACTION_CREATION_MESSAGE
    namespace["save_personal_action"].assert_not_called()
    namespace["save_global_action"].assert_not_called()


def test_cosmos_connection_drains_query_rows_without_treating_them_as_documents(routes):
    app, namespace = routes
    container = Mock()
    container.read.return_value = CosmosDict({"id": "records"}, response_headers={})
    rows = iter(["synthetic-record"])
    container.query_items.return_value = rows
    database = Mock()
    database.read.return_value = CosmosDict({"id": "database"}, response_headers={})
    database.get_container_client.return_value = container
    client = Mock()
    client.get_database_client.return_value = database
    namespace.update({
        "azure_cosmos": SimpleNamespace(CosmosClient=Mock(return_value=client)),
        "CosmosHttpResponseError": exceptions.CosmosHttpResponseError,
        "validate_azure_cosmos_endpoint": lambda endpoint: endpoint,
        "_load_existing_plugin_for_test": lambda *args, **kwargs: None,
        "_resolve_plugin_secret_context": lambda *args: ("actor", "personal"),
        "_resolve_secret_value_for_action_test": lambda value, *args: value,
        "ACTION_AUTH_SECRET_SOURCES": {"action"}, "ui_trigger_word": "Stored_In_KeyVault",
    })
    payload = {
        "endpoint": "https://cosmos.example.test", "database_name": "database",
        "container_name": "records", "auth_type": "key", "auth_key": "synthetic-key",
    }
    with app.test_request_context("/test", method="POST", json=deepcopy(payload)):
        response = namespace["test_cosmos_connection"]()
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] is True
    assert list(rows) == []
    assert container.query_items.call_args.kwargs["query"] == "SELECT TOP 1 VALUE c.id FROM c"
    assert client.get_database_client.call_args.args == ("database",)
    assert database.get_container_client.call_args.args == ("records",)
