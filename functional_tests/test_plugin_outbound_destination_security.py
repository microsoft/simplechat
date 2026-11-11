# test_plugin_outbound_destination_security.py
"""Functional tests for action destination, authoring and credential boundaries.

Version: 0.261.432
Implemented in: 0.261.432

Real route/merge bodies and validators run with scoped storage seams. HTTP
connectors are synthetic; DNS and physical connection tests use blocked I/O.
"""

import socket
import sys
import os
import subprocess
from contextlib import ExitStack
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from flask import Blueprint, session

import functions_outbound_http as transport
from test_support.agent_delegation import execute_functions
from test_workspace_authoring_backend import _load_module, action_payload, create, environment


@pytest.fixture
def routes(environment):
    env = environment
    probe = Mock(return_value={"success": True, "status": 200})
    http = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"status": "ok"}))
    ns = env.namespace
    ns.update({
        "bpap": Blueprint("outbound_security", __name__),
        "test_openapi_connection": probe, "guarded_probe_request": http,
    })
    execute_functions("route_backend_plugins.py", {
        "_run_action_connection_test", "test_openapi_action_connection", "test_rocksdb_connection",
    }, ns)
    env.app.register_blueprint(ns["bpap"])
    return SimpleNamespace(env=env, probe=probe, http=http)


@pytest.mark.parametrize("target", [
    "http://127.0.0.1", "http://169.254.169.254", "http://[::1]",
])
def test_rocksdb_rejects_forbidden_targets_before_http(routes, target):
    response = routes.env.client.post("/api/plugins/test-rocksdb-connection", json={
        "base_url": target, "auth_scheme": "none",
    })
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    routes.http.assert_not_called()
    assert routes.env.services.secret_reads == []


@pytest.mark.parametrize("target", [
    "http://192.168.10.20:8090", "https://yamcs.corp.internal:8443", "https://api.public.example",
])
def test_rocksdb_preserves_private_and_public_connection_tests(routes, target):
    response = routes.env.client.post("/api/plugins/test-rocksdb-connection", json={
        "base_url": target, "auth_scheme": "none",
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] is True
    assert routes.http.call_args.args[:2] == ("GET", f"{target}/health")


@pytest.mark.parametrize("path,payload", [
    ("/api/plugins/test-rocksdb-connection", {"base_url": "https://service.corp.internal"}),
    ("/api/plugins/test-openapi-connection", {"endpoint": "https://service.corp.internal"}),
])
def test_disabled_personal_authoring_stops_tests_before_credentials_or_network(routes, path, payload):
    routes.env.services.settings["allow_user_plugins"] = False
    response = routes.env.client.post(path, json=payload)
    assert response.status_code == 403
    routes.probe.assert_not_called()
    routes.http.assert_not_called()
    assert routes.env.services.secret_reads == []


def test_denied_action_type_cannot_use_the_test_endpoint(routes):
    routes.env.services.denied_types.add("rocksdb")
    response = routes.env.client.post("/api/plugins/test-rocksdb-connection", json={
        "base_url": "https://service.corp.internal",
    })
    assert response.status_code == 403
    routes.http.assert_not_called()


def test_dns_alias_to_metadata_is_rejected_by_real_http_transport(routes, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("169.254.169.254", 80)),
    ])
    connect = Mock()
    monkeypatch.setattr(transport, "create_connection", connect)
    routes.env.namespace["guarded_probe_request"] = transport.guarded_probe_request
    response = routes.env.client.post("/api/plugins/test-rocksdb-connection", json={
        "base_url": "http://service.corp.internal", "auth_scheme": "none",
    })
    assert response.status_code == 400, response.get_json()
    connect.assert_not_called()


@pytest.mark.parametrize("replacement,expected_status", [
    ("***REDACTED***", 400), ("", 400), ("fresh-test-credential", 200),
])
def test_changed_test_origin_cannot_inherit_an_opaque_saved_key(routes, replacement, expected_status):
    env = routes.env
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload(), "id": "owned-action", "endpoint": "https://original.corp.internal",
    })
    before = deepcopy(env.services.records)
    response = env.client.post("/api/plugins/test-openapi-connection", json={
        "plugin_context": {"scope": "personal", "id": stored["id"]},
        "endpoint": "https://changed.corp.internal",
        "auth": {"type": "key", "key": replacement}, "additionalFields": {},
    })
    assert response.status_code == expected_status, response.get_json()
    if expected_status == 400:
        routes.probe.assert_not_called()
    else:
        assert routes.probe.call_args.args[0]["auth"]["key"] == replacement
    assert env.services.records == before
    assert env.services.writes == []


def test_same_origin_masked_connection_test_still_works(routes):
    env = routes.env
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload(), "id": "owned-action", "endpoint": "https://service.corp.internal",
    })
    response = env.client.post("/api/plugins/test-openapi-connection", json={
        "plugin_context": {"scope": "personal", "id": stored["id"]},
        "endpoint": "https://service.corp.internal", "auth": {"type": "key", "key": "***REDACTED***"},
    })
    assert response.status_code == 200, response.get_json()
    assert routes.probe.call_args.args[0]["auth"]["key"] == stored["auth"]["key"]


@pytest.mark.parametrize("saved_context", [False, True])
def test_test_requests_cannot_dereference_arbitrary_same_scope_vault_names(routes, saved_context):
    env = routes.env
    env.services.settings["enable_key_vault_secret_storage"] = True
    reference = env.keyvault.build_full_secret_name("other-action-key", "actor", "action", "user")
    env.services.vault[reference] = "synthetic-other-action-key"
    payload = {
        "endpoint": "https://service.corp.internal",
        "auth": {"type": "key", "key": reference}, "additionalFields": {},
    }
    if saved_context:
        stored = env.services.add("actions", "personal", "actor", {
            **action_payload(), "id": "owned-action", "endpoint": payload["endpoint"],
        })
        payload["plugin_context"] = {"scope": "personal", "id": stored["id"]}
    response = env.client.post("/api/plugins/test-openapi-connection", json=payload)
    assert response.status_code == 400
    assert env.services.secret_reads == []
    routes.probe.assert_not_called()


def test_matching_saved_vault_field_can_still_be_tested(routes):
    env = routes.env
    env.services.settings["enable_key_vault_secret_storage"] = True
    reference = env.keyvault.build_full_secret_name("owned-action-key", "actor", "action", "user")
    env.services.vault[reference] = "synthetic-owned-key"
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload(), "id": "owned-action", "endpoint": "https://service.corp.internal",
        "auth": {"type": "key", "key": reference},
    })
    response = env.client.post("/api/plugins/test-openapi-connection", json={
        "endpoint": stored["endpoint"], "plugin_context": {"scope": "personal", "id": stored["id"]},
        "auth": {"type": "key", "key": "***REDACTED***"},
    })
    assert response.status_code == 200, response.get_json()
    assert routes.probe.call_args.args[0]["auth"]["key"] == "synthetic-owned-key"


@pytest.mark.parametrize("replacement,expected_status", [
    (None, 400), ("***REDACTED***", 400), ("fresh-test-credential", 200),
])
def test_save_then_runtime_cannot_bypass_destination_binding(environment, replacement, expected_status):
    env = environment
    resource = create(env, "plugins", action_payload())
    identifier = resource["record"]["id"]
    before = deepcopy(env.services.records)
    updates = {"endpoint": "https://changed.corp.internal"}
    if replacement is not None:
        updates["auth"] = {"key": replacement}
    response = env.client.patch(f"/api/user/plugins/{identifier}?view=editor", json={
        "updates": updates, "expected_revision": resource["revision"],
    })
    assert response.status_code == expected_status, response.get_json()
    if expected_status == 400:
        assert env.services.records == before
    else:
        assert response.get_json()["record"]["auth"]["key"] == "***REDACTED***"


def test_connector_mismatch_is_rejected_before_hydration(routes):
    env = routes.env
    stored = env.services.add("actions", "personal", "actor", {**action_payload(), "id": "openapi-action"})
    response = env.client.post("/api/plugins/test-rocksdb-connection", json={
        "base_url": "https://service.corp.internal",
        "existing_plugin": {"scope": "personal", "id": stored["id"]},
    })
    assert response.status_code == 403
    routes.http.assert_not_called()
    assert env.services.secret_reads == []


def test_legacy_databricks_type_keeps_its_connection_test_permission(environment):
    env = environment
    stored = env.services.add("actions", "personal", "actor", {
        **action_payload("databricks_table"), "id": "legacy-databricks",
    })
    loaded = env.namespace["_load_existing_plugin_for_test"](
        {"scope": "personal", "id": stored["id"]}, "actor",
    )
    with env.app.test_request_context():
        scope = env.namespace["_authorize_action_test_scope"]({}, loaded, "actor", "databricks")
    assert scope == ("personal", "actor")
    assert env.services.secret_reads == []


@pytest.mark.parametrize("auth_method", ["none", "api_key"])
def test_native_yamcs_sdk_keeps_reverse_proxy_authentication_and_tls(environment, monkeypatch, auth_method):
    env = environment
    captured = []
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)

    def send(adapter, request, **kwargs):
        captured.append((request, kwargs))
        response = requests.Response()
        response.status_code = 200
        response.url, response.request = request.url, request
        response._content = b""
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with patch.dict(sys.modules), ExitStack() as stack:
        # Older standalone tests install fake SDK modules; restore the installed SDK here.
        for name in list(sys.modules):
            if name == "yamcs" or name.startswith("yamcs."):
                sys.modules.pop(name)
        sdk = import_module("yamcs.client")
        module = _load_module(stack, "semantic_kernel_plugins.yamcs_plugin", r"semantic_kernel_plugins\yamcs_plugin.py")
        plugin = module.YamcsPlugin({
            "name": "proxy", "type": "yamcs", "endpoint": "https://yamcs.corp.internal:8090",
            "auth": {"type": "NoAuth"} if auth_method == "none" else {"type": "key", "key": "synthetic-api-key"},
            "additionalFields": {
                "instance": "simulator", "auth_method": auth_method, "enable_basic_auth": True,
                "basic_auth_username": "operator", "basic_auth_password": "synthetic-proxy-password",
                "tls_verify": False, "timeout": 7,
            },
        })
        client = plugin._connect()
        try:
            assert isinstance(client, sdk.YamcsClient)
            client.get_server_info()
            request, options = captured[-1]
            assert request.url.startswith("https://yamcs.corp.internal:8090/")
            assert request.headers["Authorization"] == module.build_yamcs_basic_auth_header(
                "operator", "synthetic-proxy-password",
            )
            if auth_method == "api_key":
                assert request.headers["x-api-key"] == "synthetic-api-key"
            assert options["verify"] is False
            assert options["timeout"] == 7
            assert isinstance(client.ctx.session.get_adapter("https://"), transport.GuardedHTTPAdapter)
        finally:
            client.close()


def test_native_tableau_installs_guard_before_server_version_discovery(environment, monkeypatch):
    env = environment
    captured = []
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)

    def send(adapter, request, **kwargs):
        captured.append((adapter, request, kwargs))
        response = requests.Response()
        response.status_code = 200
        response.url, response.request = request.url, request
        response._content = (
            b'<tsResponse xmlns="http://tableau.com/api"><serverInfo>'
            b'<productVersion build="10000.0">2025.1</productVersion>'
            b'<restApiVersion>3.25</restApiVersion></serverInfo></tsResponse>'
        )
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with patch.dict(sys.modules), ExitStack() as stack:
        for name in list(sys.modules):
            if name == "tableauserverclient" or name.startswith("tableauserverclient."):
                sys.modules.pop(name)
        module = _load_module(stack, "semantic_kernel_plugins.tableau_plugin", r"semantic_kernel_plugins\tableau_plugin.py")
        plugin = module.TableauPlugin({
            "name": "tableau", "type": "tableau", "endpoint": "https://tableau.corp.internal",
            "auth": {"type": "key", "identity": "operator", "key": "synthetic-pat"},
            "additionalFields": {"use_server_version": True, "timeout": 9},
        })
        server = plugin._create_server()
        try:
            adapter, request, options = captured[0]
            assert isinstance(adapter, transport.GuardedHTTPAdapter)
            assert request.url.startswith("https://tableau.corp.internal/")
            assert options["timeout"] == 9
            assert server.version == "3.25"
        finally:
            server._session.close()


def test_native_mcp_connectors_receive_guarded_transports():
    # Native Pydantic/SK generic caches need a fresh process, not sys.modules reloads.
    script = r'''
import sys
import types
from unittest.mock import Mock
from flask import Flask, session
from test_support import cosmos_network_guard

cosmos_network_guard.pytest_sessionstart(None)
for name, values in {
    "functions_appinsights": {"log_event": Mock()},
    "functions_debug": {"debug_print": Mock()},
    "functions_mcp_preconfigurations": {"authorize_mcp_action": Mock()},
    "semantic_kernel_plugins.mcp_plugin": {"McpPlugin": Mock()},
}.items():
    module = types.ModuleType(name)
    module.__dict__.update(values)
    sys.modules[name] = module

from functions_action_manifest import McpActionOrigin
from functions_outbound_http import create_guarded_httpx_client
from semantic_kernel.connectors.mcp import MCPSsePlugin, MCPStreamableHttpPlugin
from semantic_kernel_plugins.mcp_guarded_transport import GuardedMcpWebsocketPlugin
from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory

McpPluginFactory._get_current_settings = staticmethod(lambda: {})
app = Flask("native_mcp_transport")
app.secret_key = "synthetic-only"
with app.test_request_context():
    session["user"] = {"oid": "actor"}
    for protocol, expected in (
        ("sse", MCPSsePlugin), ("streamable_http", MCPStreamableHttpPlugin),
        ("websocket", GuardedMcpWebsocketPlugin),
    ):
        connector = McpPluginFactory.create_connector({
            "name": "mcp", "type": "mcp",
            "endpoint": "wss://mcp.corp.internal" if protocol == "websocket" else "https://mcp.corp.internal",
            "auth": {"type": "NoAuth"},
            "additionalFields": {"transport": protocol, "auth_method": "none", "connect_timeout": 12},
        }, origin=McpActionOrigin("personal", "actor"))
        if not isinstance(connector, expected):
            raise AssertionError("The native MCP connector type changed")
        if protocol == "websocket":
            if connector.connect_timeout != 12:
                raise AssertionError("The guarded WebSocket timeout was not retained")
        elif connector._client_kwargs.get("httpx_client_factory") is not create_guarded_httpx_client:
            raise AssertionError("The native MCP HTTP client factory was not guarded")

import anyio
import json
from contextlib import asynccontextmanager
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage
from semantic_kernel_plugins import mcp_guarded_transport as bridge

async def check_wire_contract():
    sent = []
    completed = anyio.Event()
    closed = []

    class WireConnection:
        def __aiter__(self):
            async def incoming():
                yield '{"jsonrpc":"2.0","method":"notifications/test"}'
                await anyio.sleep_forever()
            return incoming()

        async def send(self, value):
            sent.append(json.loads(value))
            completed.set()

    @asynccontextmanager
    async def open_wire(url, timeout):
        try:
            yield WireConnection()
        finally:
            closed.append(True)

    bridge.guarded_websocket_connection = open_wire
    async with bridge.guarded_mcp_websocket_client("wss://mcp.corp.internal", 12) as (incoming, outgoing):
        received = await incoming.receive()
        if not isinstance(received, SessionMessage) or received.message.root.method != "notifications/test":
            raise AssertionError("The guarded WebSocket lost the native receive contract")
        await outgoing.send(SessionMessage(JSONRPCMessage.model_validate(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )))
        await completed.wait()
    if sent != [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}] or closed != [True]:
        raise AssertionError("The guarded WebSocket lost its native send or cleanup contract")

anyio.run(check_wire_contract)
if "config" in sys.modules:
    raise AssertionError("Connector construction must not bootstrap Azure storage")
cosmos_network_guard.pytest_sessionfinish(None, 0)
'''
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True, timeout=120,
        env={
            **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join((str(root / "application" / "single_app"), str(root / "functional_tests"))),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
