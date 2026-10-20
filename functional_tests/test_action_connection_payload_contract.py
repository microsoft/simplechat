# test_action_connection_payload_contract.py
"""Real V2 payload producer to Flask action-test/discovery contracts.

Version: 0.261.354
Implemented in: 0.261.354

Execute the shipping TypeScript builder with Node and the actual route bodies,
manifest validator and credential-clear helper with scoped repository seams.
Sockets are blocked; only the external connector tester/probe is replaced.
This is a request contract, not an application bootstrap/import-cycle test.
"""

import asyncio
import json
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from flask import Blueprint

from test_support.agent_delegation import execute_functions
from test_support import cosmos_network_guard
from test_workspace_authoring_backend import environment  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = """
import './functional_tests/test_support/tsResolve.mjs';
import { readFileSync } from 'node:fs';
const { buildConnectorSupportPayload, changeConnectorAuthMethod } =
    await import('./application/v2_ui/src/lib/workspaceActionConnectors.ts');
const input = JSON.parse(readFileSync(0, 'utf8'));
const draft = changeConnectorAuthMethod(input.draft, input.kind, 'none');
const payload = buildConnectorSupportPayload(draft, input.original, input.kind, input.purpose, input.scope);
console.log(JSON.stringify(payload));
"""
PATHS = [
    "/api/plugins/test-openapi-connection",
    "/api/plugins/test-mcp-connection",
    "/api/plugins/mcp/discover",
]


@pytest.fixture
def contract(environment, monkeypatch):
    env = environment
    monkeypatch.setattr("socket.socket.connect", cosmos_network_guard._connect)
    monkeypatch.setattr("socket.socketpair", cosmos_network_guard._socketpair)
    monkeypatch.setattr("socket.getaddrinfo", cosmos_network_guard._blocked)
    tester = Mock(return_value={"success": True, "status": 200, "message": "Synthetic probe reached."})
    probe = AsyncMock(return_value={
        "tools": [], "prompts": [], "fingerprints": {
            "manifest_hash": "a" * 64, "discovered_at": "2026-10-19T00:00:00Z",
            "tools": {}, "prompts": {},
        },
    })
    namespace = env.namespace
    namespace.update({
        "bpap": Blueprint("action_payload_contract", __name__),
        "test_openapi_connection": tester, "test_mcp_connection": tester,
        "asyncio": asyncio, "time": time,
        "McpPluginFactory": SimpleNamespace(probe_server_from_config=probe),
        "build_mcp_destination_log_context": Mock(return_value={}),
        "WORKSPACE_IDENTITY_SCOPE_GROUP": "group", "WORKSPACE_IDENTITY_SCOPE_GLOBAL": "global",
        "find_group_by_id": lambda group_id: {"id": group_id} if group_id == "group-b" else None,
        "get_user_role_in_group": lambda group, user_id: env.services.roles.get((user_id, group["id"])),
        "group_action_management_operations": lambda user_id, group, role, settings: {"test"} if role == "Owner" else set(),
        "get_group_action": lambda group_id, identifier, **kwargs: deepcopy(
            env.services.records["actions", "group"].get((group_id, identifier))),
        "get_global_action": lambda identifier, **kwargs: deepcopy(
            env.services.records["actions", "global"].get((identifier, identifier))),
    })
    execute_functions("route_backend_plugins.py", {
        "_run_action_connection_test", "test_openapi_action_connection",
        "test_mcp_action_connection", "discover_mcp_tools", "_resolve_group_for_test",
        "_build_mcp_discovery_log_context", "_elapsed_mcp_discovery_ms",
    }, namespace)
    env.app.register_blueprint(namespace["bpap"])
    return SimpleNamespace(env=env, tester=tester, probe=probe)


def produce(draft, original, kind, purpose="test", scope=None):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PRODUCER],
        input=json.dumps({
            "draft": draft, "original": original, "kind": kind, "purpose": purpose, "scope": scope,
        }), cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def action(kind):
    fields = {"auth_method": "none"}
    if kind == "openapi":
        fields.update({
            "openapi_source_type": "content", "base_url": "https://api.example.test",
            "openapi_spec_content": {
                "openapi": "3.0.3", "info": {"title": "Synthetic API", "version": "1"},
                "paths": {"/status": {"get": {"operationId": "getStatus", "responses": {"200": {"description": "OK"}}}}},
            },
        })
    else:
        fields["transport"] = "streamable_http"
    return {
        "name": "generic-connector", "displayName": "Generic connector", "description": "Read-only contract",
        "type": kind, "endpoint": "https://api.example.test",
        "auth": {"type": "key" if kind == "openapi" else "NoAuth"},
        "metadata": {}, "additionalFields": fields,
    }


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("state", ["new", "saved_empty", "saved_key", "saved_aliases"])
@pytest.mark.parametrize("path", PATHS)
def test_actual_producer_reaches_shared_test_or_discovery(contract, scope, state, path):
    env = contract.env
    kind = "openapi" if "openapi" in path else "mcp"
    purpose = "discover" if path.endswith("/discover") else "test"
    draft, original = action(kind), None
    expected_clears = set()
    if state != "new":
        if state != "saved_empty":
            fields = ["key"] if state == "saved_key" else ["key", "identity", "tenantId", "token", "value", "password"]
            draft["auth"] = {"type": "key", **{field: f"synthetic-{field}-credential" for field in fields}}
        stored = env.services.add("actions", scope, "group-b" if scope == "group" else "actor", {
            **draft, "id": "contract-action",
        })
        original = env.helper.editor_resource(stored, "actions", read_only=False)
        expected_clears = set(original["secret_paths"])
        draft = deepcopy(original["record"])
    payload = produce(draft, original, kind, purpose, {"id": "group-b"} if scope == "group" else {"global": True} if scope == "global" else None)
    assert set(payload["clear_secret_paths"]) == expected_clears
    assert payload["action_scope"] == scope
    if scope == "group":
        assert payload["group_id"] == "group-b"
    before = deepcopy(env.services.records)
    with env.client.session_transaction() as session:
        session["user"] = {**session["user"], "roles": ["User", "Admin"]}
    response = env.client.post(path, json=payload)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] is True
    manifest = contract.probe.call_args.args[0] if purpose == "discover" else contract.tester.call_args.args[0]
    assert not any(manifest["auth"].get(field) for field in ("key", "identity", "tenantId", "token", "value", "password"))
    assert env.services.secret_reads == []
    assert env.services.records == before
    assert env.services.writes == []
    if purpose == "discover":
        assert contract.probe.await_count == 1
        contract.tester.assert_not_called()
    else:
        assert contract.tester.call_count == 1
        contract.probe.assert_not_called()


@pytest.mark.parametrize("path", PATHS)
def test_invalid_clear_intent_is_specific_and_stops_before_io(contract, path):
    env = contract.env
    kind = "openapi" if "openapi" in path else "mcp"
    payload = produce(action(kind), None, kind, "discover" if path.endswith("/discover") else "test")
    payload["clear_secret_paths"] = ["/auth/key"]
    response = env.client.post(path, json=payload)
    body = response.get_json()
    assert response.status_code == 400
    assert body["success"] is False
    assert body["error"] == "A saved action is required to clear stored test credentials."
    assert body["error_type"] == "invalid_editor_configuration"
    assert body["details"]["stage"] == "request_preparation"
    if path.endswith("/discover"):
        assert body["mcp_operation_id"]
    rejected = env.services.appinsights.log_event.call_args
    assert rejected.kwargs["extra"]["failure_stage"] == "request_preparation"
    assert not rejected.kwargs.get("debug_only")
    contract.tester.assert_not_called()
    contract.probe.assert_not_called()


@pytest.mark.parametrize("pointer", ["/description", "/auth/missing", "/user_id", "/auth/bad~2pointer", 3])
@pytest.mark.parametrize("path", PATHS)
def test_saved_invalid_paths_remain_fail_closed(contract, pointer, path):
    env = contract.env
    kind = "openapi" if "openapi" in path else "mcp"
    stored = env.services.add("actions", "personal", "actor", {**action(kind), "id": "owned"})
    payload = produce(action(kind), env.helper.editor_resource(stored, "actions", read_only=False), kind)
    payload["clear_secret_paths"] = [pointer]
    response = env.client.post(path, json=payload)
    assert response.status_code == 400
    assert response.get_json()["error_type"] == "invalid_editor_configuration"
    contract.tester.assert_not_called()
    contract.probe.assert_not_called()
    assert env.services.records["actions", "personal"]["actor", "owned"] == stored


@pytest.mark.parametrize("path", PATHS)
def test_plain_value_errors_do_not_leak_credentials(contract, monkeypatch, path):
    env = contract.env
    secret = "private-credential-that-must-not-be-logged"
    monkeypatch.setitem(env.namespace, "_load_existing_plugin_for_test", Mock(side_effect=ValueError(secret)))
    response = env.client.post(path, json=action("openapi" if "openapi" in path else "mcp"))
    assert response.status_code == 400
    assert secret not in response.get_data(as_text=True)
    assert secret not in str(env.services.appinsights.log_event.call_args_list)
    contract.tester.assert_not_called()
    contract.probe.assert_not_called()


@pytest.mark.parametrize("path", PATHS)
def test_unexpected_connector_errors_do_not_leak_credentials(contract, path):
    secret = "provider-password=synthetic-private-secret"
    contract.tester.side_effect = RuntimeError(secret)
    contract.probe.side_effect = RuntimeError(secret)
    kind = "openapi" if "openapi" in path else "mcp"
    payload = produce(action(kind), None, kind)
    response = contract.env.client.post(path, json=payload)
    assert response.status_code == 500
    assert secret not in response.get_data(as_text=True)
    assert secret not in str(contract.env.services.appinsights.log_event.call_args_list)


@pytest.mark.parametrize("path", PATHS[1:])
def test_no_auth_preserves_one_owned_header_while_clearing_another(contract, path):
    env = contract.env
    draft = action("mcp")
    draft["auth"] = {"type": "key", "key": "synthetic-inactive-key"}
    draft["additionalFields"]["custom_headers"] = {
        "X-Keep": "synthetic-kept-header", "X-Remove": "synthetic-removed-header",
    }
    stored = env.services.add("actions", "personal", "actor", {**draft, "id": "headers"})
    original = env.helper.editor_resource(stored, "actions", read_only=False)
    draft = deepcopy(original["record"])
    del draft["additionalFields"]["custom_headers"]["X-Remove"]
    payload = produce(draft, original, "mcp", "discover" if path.endswith("/discover") else "test")
    assert set(payload["clear_secret_paths"]) == {
        "/auth/key", "/additionalFields/custom_headers/X-Remove",
    }
    response = env.client.post(path, json=payload)
    assert response.status_code == 200, response.get_json()
    manifest = contract.probe.call_args.args[0] if path.endswith("/discover") else contract.tester.call_args.args[0]
    assert manifest["auth"] == {"type": "NoAuth"}
    assert manifest["additionalFields"]["custom_headers"] == {"X-Keep": "synthetic-kept-header"}
    assert env.services.records["actions", "personal"]["actor", "headers"] == stored
    assert env.services.writes == []
