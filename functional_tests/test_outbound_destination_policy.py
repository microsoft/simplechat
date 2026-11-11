# test_outbound_destination_policy.py
"""Destination and real-client transport regressions for configurable actions.

Version: 0.261.435
Implemented in: 0.261.435

All DNS and external connection boundaries are synthetic. Enterprise private
destinations remain valid; loopback, metadata, rebinding and retargeting do not.
"""

import asyncio
import os
import socket
import ssl
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import httpcore
import httpx
import pytest
import requests
import urllib3.connection

import functions_outbound_destinations as policy
import functions_outbound_http as transport


@pytest.mark.parametrize("url", [
    "http://localhost", "https://service.localhost", "http://127.0.0.2",
    "https://169.254.169.254", "http://168.63.129.16", "http://100.100.100.200",
    "http://[::1]", "http://[::ffff:127.0.0.1]", "http://[fd00:ec2::254]",
    "http://0.1.2.3", "http://224.0.0.1", "http://127.1", "http://2130706433",
    "http://0x7f000001", "http://0177.0.0.1", "file:///etc/hosts",
    "https://user:password@api.example.test", "https://api.example.test\\@localhost",
])
def test_forbidden_literal_targets_are_rejected(url):
    with pytest.raises(policy.OutboundDestinationError):
        policy.normalize_outbound_url(url)


@pytest.mark.parametrize("changes", [
    {"endpoint": "https://[invalid"}, {"additionalFields": []},
])
def test_invalid_connection_signatures_have_stable_validation_errors(changes):
    with pytest.raises(policy.OutboundDestinationError):
        policy.action_connection_signature({
            "type": "openapi", "endpoint": "https://service.corp.internal", **changes,
        })


@pytest.mark.parametrize("url", [
    "https://yamcs.corp.internal:8443", "http://192.168.10.20:8090",
    "https://10.2.3.4", "https://172.20.30.40", "https://[fd12::1234]",
    "https://service.public.example", "wss://mcp.corp.internal:9443",
])
def test_private_and_public_service_targets_remain_valid(url):
    target = policy.normalize_outbound_url(url)
    assert target.host


def dns_answer(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443)


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["169.254.169.254"], ["::ffff:127.0.0.1"],
    ["192.168.1.20", "169.254.169.254"], ["fd12::1234", "::1"],
])
def test_all_dns_answers_must_be_safe(monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: list(map(dns_answer, addresses)))
    with pytest.raises(policy.OutboundDestinationError):
        policy.resolve_outbound_addresses("service.corp.internal", 443)


def test_requests_connects_to_vetted_ip_without_changing_tls_hostname(monkeypatch):
    resolver = Mock(return_value=[dns_answer("192.168.4.20")])
    connect = Mock(return_value=Mock())
    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    monkeypatch.setattr(transport, "create_connection", connect)
    session = transport.create_guarded_session()
    try:
        adapter = session.get_adapter("https://")
        pool = adapter.poolmanager.connection_from_url("https://yamcs.corp.internal")
        connection = pool._new_conn()
        connection._new_conn()
        assert connect.call_args.args[0] == ("192.168.4.20", 443)
        assert connection.host == "yamcs.corp.internal"
        assert pool.host == "yamcs.corp.internal"
        assert resolver.call_args.args[:2] == ("yamcs.corp.internal", 443)
    finally:
        session.close()


def test_rebinding_at_requests_connection_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=[
        [dns_answer("192.168.4.20")], [dns_answer("127.0.0.1")],
    ]))
    addresses = policy.resolve_outbound_addresses("service.corp.internal", 443)
    assert addresses == ("192.168.4.20",)
    connect = Mock()
    monkeypatch.setattr(transport, "create_connection", connect)
    with pytest.raises(policy.OutboundDestinationError):
        transport._GuardedHTTPSConnection("service.corp.internal")._new_conn()
    connect.assert_not_called()


@pytest.mark.parametrize("destination", [
    "http://127.0.0.1/status", "http://169.254.169.254", "https://different.example.test",
    "http://service.corp.internal/status",
])
def test_redirects_cannot_retarget_or_downgrade(destination):
    with pytest.raises(policy.OutboundDestinationError):
        policy.validate_outbound_redirect("https://service.corp.internal/start", destination)


def test_requests_rejects_redirect_before_following_or_forwarding_credentials():
    session = transport.create_guarded_session()
    response = requests.Response()
    response.status_code = 302
    response.headers["Location"] = "https://other.example.test"
    response.request = requests.Request(
        "GET", "https://yamcs.corp.internal", headers={"X-API-Key": "synthetic-secret"},
    ).prepare()
    response.close = Mock()
    try:
        with pytest.raises(policy.OutboundDestinationError):
            session.get_redirect_target(response)
        response.close.assert_called_once()
    finally:
        session.close()


def test_safe_redirect_and_default_port_tls_upgrade_are_preserved():
    same = policy.validate_outbound_redirect("https://service.corp.internal/a", "/b")
    upgraded = policy.validate_outbound_redirect("http://service.corp.internal/a", "https://service.corp.internal/b")
    assert same == "https://service.corp.internal/b"
    assert upgraded == same


def test_httpx_connects_to_vetted_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [dns_answer("10.2.3.4")])
    backend = Mock(connect_tcp=AsyncMock(return_value=Mock()))
    guarded = transport._GuardedAsyncBackend(backend)
    asyncio.run(guarded.connect_tcp("yamcs.corp.internal", 443))
    assert backend.connect_tcp.call_args.args[:2] == ("10.2.3.4", 443)


def test_httpx_rejects_forbidden_dns_before_tcp(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [dns_answer("169.254.169.254")])
    backend = Mock(connect_tcp=AsyncMock())
    with pytest.raises(policy.OutboundDestinationError):
        asyncio.run(transport._GuardedAsyncBackend(backend).connect_tcp("service.example.test", 443))
    backend.connect_tcp.assert_not_called()


def test_aiohttp_checks_the_addresses_used_by_connector(monkeypatch):
    original = AsyncMock(return_value=[{
        "hostname": "yamcs.corp.internal", "host": "127.0.0.1", "port": 443,
        "family": socket.AF_INET, "proto": socket.IPPROTO_TCP, "flags": 0,
    }])
    monkeypatch.setattr(aiohttp.TCPConnector, "_resolve_host", original)

    async def probe():
        async with transport.GuardedTCPConnector() as connector:
            with pytest.raises(policy.OutboundDestinationError):
                await connector._resolve_host("yamcs.corp.internal", 443)

    asyncio.run(probe())


def test_authority_headers_cannot_override_the_service():
    with pytest.raises(policy.OutboundDestinationError):
        policy.validate_outbound_headers("https://service.corp.internal", {"Host": "localhost"})


def test_forward_proxy_is_rejected_explicitly_not_silently_disabled(monkeypatch):
    monkeypatch.setattr(transport, "get_environ_proxies", lambda url: {"https": "http://proxy.example.test:3128"})
    with pytest.raises(policy.OutboundDestinationError, match="Forward-proxy"):
        transport._reject_forward_proxy("https://service.corp.internal")


def test_requests_keeps_original_sni_and_enabled_verification(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [dns_answer("192.168.4.20")])
    sock = Mock()
    connect = Mock(return_value=sock)
    tls = Mock(return_value=SimpleNamespace(socket=sock, is_verified=True))
    monkeypatch.setattr(transport, "create_connection", connect)
    monkeypatch.setattr(urllib3.connection, "_ssl_wrap_socket_and_match_hostname", tls)
    connection = transport._GuardedHTTPSConnection("yamcs.corp.internal", cert_reqs=ssl.CERT_REQUIRED)
    connection.connect()
    assert connect.call_args.args[0] == ("192.168.4.20", 443)
    assert tls.call_args.kwargs["server_hostname"] == "yamcs.corp.internal"
    assert tls.call_args.kwargs["cert_reqs"] == ssl.CERT_REQUIRED
    connection.close()


def test_full_httpx_request_preserves_host_sni_and_auth_on_private_connection(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [dns_answer("10.2.3.4")])
    monkeypatch.setattr(transport, "get_environ_proxies", lambda url: {})
    writes = []
    handshakes = []

    class MemoryStream:
        async def write(self, buffer, timeout=None):
            writes.append(buffer)

        async def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            handshakes.append((ssl_context.verify_mode, server_hostname))
            return self

        async def aclose(self):
            pass

        def get_extra_info(self, name):
            return False if name == "is_readable" else None

    backend = Mock(connect_tcp=AsyncMock(return_value=MemoryStream()))

    async def probe():
        client = transport.create_guarded_httpx_client(headers={"Authorization": "Basic synthetic"})
        client._transport._pool._network_backend = transport._GuardedAsyncBackend(backend)
        async with client:
            response = await client.get("https://yamcs.corp.internal/status")
            return response.status_code

    status = asyncio.run(probe())
    assert status == 200
    assert backend.connect_tcp.call_args.args[:2] == ("10.2.3.4", 443)
    assert handshakes == [(ssl.CERT_REQUIRED, "yamcs.corp.internal")]
    wire = b"".join(writes).lower()
    assert b"host: yamcs.corp.internal" in wire
    assert b"authorization: basic synthetic" in wire


def test_connection_probes_limit_body_reads_and_close_responses(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response.raw = BytesIO(b"x" * 100)
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.request.return_value = response
    close = Mock(wraps=response.close)
    monkeypatch.setattr(response, "close", close)
    monkeypatch.setattr(transport, "create_guarded_session", lambda: session)
    with pytest.raises(policy.OutboundDestinationError, match="too large"):
        transport.guarded_probe_request("GET", "https://service.corp.internal", max_bytes=8)
    close.assert_called_once()


@pytest.mark.parametrize("header", ["service.corp.internal:443", "SERVICE.CORP.INTERNAL"])
def test_equivalent_authority_headers_remain_usable(header):
    target = policy.validate_outbound_headers("https://service.corp.internal/status", {"Host": header})
    assert target.host == "service.corp.internal"


def test_mapped_and_nat64_private_addresses_are_allowed_but_forbidden_targets_are_not():
    private = policy.normalize_outbound_url("https://[64:ff9b::a00:1]")
    assert private.host == "64:ff9b::a00:1"
    with pytest.raises(policy.OutboundDestinationError):
        policy.normalize_outbound_url("https://[64:ff9b::7f00:1]")


def test_guarded_session_does_not_change_other_azure_sdk_or_requests_sessions():
    guarded = transport.create_guarded_session()
    ordinary = requests.Session()
    try:
        guarded_pool = guarded.get_adapter("https://").poolmanager.connection_from_url("https://service.corp.internal")
        ordinary_pool = ordinary.get_adapter("https://").poolmanager.connection_from_url("https://service.corp.internal")
        guarded_connection = guarded_pool._new_conn()
        ordinary_connection = ordinary_pool._new_conn()
        assert isinstance(guarded_connection, transport._GuardedHTTPSConnection)
        assert not isinstance(ordinary_connection, transport._GuardedHTTPSConnection)
    finally:
        guarded.close()
        ordinary.close()


def test_guarded_requests_never_add_server_netrc_credentials(monkeypatch):
    netrc = Mock(return_value=("ambient-user", "ambient-password"))
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", netrc)
    session = transport.create_guarded_session()
    try:
        prepared = session.prepare_request(requests.Request("GET", "https://service.corp.internal"))
        assert "Authorization" not in prepared.headers
        response = requests.Response()
        response.request = prepared
        redirect = requests.Request("GET", "https://service.corp.internal/next").prepare()
        session.rebuild_auth(redirect, response)
        assert "Authorization" not in redirect.headers
        netrc.assert_not_called()
        explicit = session.prepare_request(requests.Request(
            "GET", "https://service.corp.internal", auth=("explicit-user", "explicit-password"),
        ))
        assert explicit.headers["Authorization"].startswith("Basic ")
    finally:
        session.close()


def test_websocket_connects_to_vetted_private_ip_and_keeps_sni(monkeypatch):
    # Import the optional protocol only for these connector tests.
    import websockets.asyncio.client

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [dns_answer("10.2.3.4")])
    monkeypatch.setattr(transport, "get_environ_proxies", lambda url: {})
    connection = SimpleNamespace(close=AsyncMock())
    opened = []

    class OpenSocket:
        def __init__(self, url, **kwargs):
            opened.append((url, kwargs))

        def __await__(self):
            async def connected():
                return connection
            return connected().__await__()

    monkeypatch.setattr(websockets.asyncio.client, "connect", OpenSocket)

    async def probe():
        connect = AsyncMock()
        monkeypatch.setattr(asyncio.get_running_loop(), "sock_connect", connect)
        async with transport.guarded_websocket_connection("wss://mcp.corp.internal/endpoint") as active:
            assert active is connection
        assert connect.call_args.args[1] == ("10.2.3.4", 443)

    asyncio.run(probe())
    assert opened[0][1]["server_hostname"] == "mcp.corp.internal"
    assert opened[0][1]["proxy"] is None
    assert opened[0][1]["sock"].fileno() == -1
    connection.close.assert_awaited_once()


def test_websocket_checks_dns_again_after_same_origin_redirect(monkeypatch):
    import websockets.asyncio.client
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response

    monkeypatch.setattr(transport, "get_environ_proxies", lambda url: {})
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=[
        [dns_answer("10.2.3.4")], [dns_answer("169.254.169.254")],
    ]))

    class RedirectSocket:
        def __init__(self, url, **kwargs):
            pass

        def __await__(self):
            async def redirected():
                raise InvalidStatus(Response(302, "Found", Headers({"Location": "/new-endpoint"}), b""))
            return redirected().__await__()

    monkeypatch.setattr(websockets.asyncio.client, "connect", RedirectSocket)

    async def probe():
        connect = AsyncMock()
        monkeypatch.setattr(asyncio.get_running_loop(), "sock_connect", connect)
        with pytest.raises(policy.OutboundDestinationError):
            async with transport.guarded_websocket_connection("wss://mcp.corp.internal/endpoint"):
                raise AssertionError("A forbidden redirect must not open a WebSocket")
        assert connect.await_count == 1

    asyncio.run(probe())


@pytest.mark.parametrize("module_name", ["test_yamcs_action_plugin", "test_yamcs_basic_auth"])
def test_yamcs_bootstrap_doubles_use_native_sdk_contracts_in_isolated_processes(module_name):
    # Legacy standalone modules bootstrap config at import; never leak their stubs into other suites.
    script = r'''
import importlib
import sys
from azure.cosmos._cosmos_responses import CosmosDict
from test_support import cosmos_network_guard

cosmos_network_guard.pytest_sessionstart(None)
module = importlib.import_module(sys.argv[1])
result = module.test_bootstrap_container_sdk_contract()
if result is False:
    raise AssertionError("The bootstrap SDK double contract failed")
container = module.FakeConfigCosmosContainer()
initial = container.read_item("app_settings", "app_settings")
saved = container.upsert_item({**initial, "settings": {"test": True}})
rows = list(container.query_items("SELECT * FROM c", partition_key="app_settings"))
if not isinstance(initial, CosmosDict) or not isinstance(saved, CosmosDict):
    raise AssertionError("Bootstrap point responses must use the installed SDK")
if initial["_etag"] == saved["_etag"] or not rows or type(rows[0]) is not dict:
    raise AssertionError("Bootstrap ETags/query rows must retain the SDK-default contract")
cosmos_network_guard.pytest_sessionfinish(None, 0)
'''
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", script, module_name], cwd=root,
        capture_output=True, text=True, timeout=120,
        env={
            **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join((str(root / "application" / "single_app"), str(root / "functional_tests"))),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
