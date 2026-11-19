# functions_outbound_http.py
"""Connection-bound HTTP transports for configurable actions, without app bootstrap."""

import asyncio
import socket
from contextlib import asynccontextmanager
from types import MethodType

import aiohttp
import anyio
import httpcore
import httpx
import requests
from requests.adapters import HTTPAdapter
from requests.utils import get_environ_proxies, select_proxy
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection

from functions_outbound_destinations import (
    OutboundDestinationError,
    normalize_outbound_url,
    resolve_outbound_addresses,
    validate_outbound_address,
    validate_outbound_headers,
    validate_outbound_redirect,
)


def _reject_forward_proxy(url, proxies=None, *, trust_env=True):
    selected = proxies if proxies is not None else get_environ_proxies(url) if trust_env else {}
    if select_proxy(url, selected):
        raise OutboundDestinationError(
            "Forward-proxy routing is not supported for guarded action connections."
        )


class _GuardedConnection:
    def _new_conn(self):
        addresses = resolve_outbound_addresses(self.host, self.port)
        last_error = None
        for address in addresses:
            try:
                return create_connection(
                    (address, self.port), self.timeout,
                    source_address=self.source_address, socket_options=self.socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise NewConnectionError(self, "The action service could not be reached.") from last_error


class _GuardedHTTPConnection(_GuardedConnection, HTTPConnection):
    pass


class _GuardedHTTPSConnection(_GuardedConnection, HTTPSConnection):
    pass


class _GuardedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _GuardedHTTPSConnection


class GuardedHTTPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _GuardedHTTPPool, "https": _GuardedHTTPSPool,
        }

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        raise OutboundDestinationError(
            "Forward-proxy routing is not supported for guarded action connections."
        )

    def send(self, request, **kwargs):
        target = validate_outbound_headers(request.url, request.headers)
        if target.scheme not in {"http", "https"}:
            raise OutboundDestinationError("This action requires an HTTP or HTTPS service URL.")
        _reject_forward_proxy(request.url, kwargs.get("proxies") or {}, trust_env=False)
        return super().send(request, **kwargs)


class _NoAmbientAuth(requests.auth.AuthBase):
    def __call__(self, request):
        return request


def guard_requests_session(session):
    """Install protection before an SDK performs login or any other HTTP request."""
    if getattr(session, "_simplechat_outbound_guarded", False) is True:
        return session
    session.mount("http://", GuardedHTTPAdapter())
    session.mount("https://", GuardedHTTPAdapter())
    session.max_redirects = min(session.max_redirects, 5)
    original_redirect = session.get_redirect_target
    original_prepare = session.prepare_request

    def prepare_request(self, request):
        if not request.auth and not self.auth:
            request.auth = _NoAmbientAuth()
        return original_prepare(request)

    def redirect_auth(self, request, response):
        validate_outbound_redirect(response.request.url, request.url)

    def redirect_target(self, response):
        location = original_redirect(response)
        if location:
            try:
                return validate_outbound_redirect(response.request.url, location)
            except OutboundDestinationError:
                response.close()
                raise
        return None

    session.get_redirect_target = MethodType(redirect_target, session)
    session.prepare_request = MethodType(prepare_request, session)
    session.rebuild_auth = MethodType(redirect_auth, session)
    session._simplechat_outbound_guarded = True
    return session


def create_guarded_session():
    return guard_requests_session(requests.Session())


def guarded_request(method, url, **kwargs):
    target = normalize_outbound_url(url)
    with create_guarded_session() as session:
        return session.request(method, target.url, **kwargs)


def guarded_probe_request(method, url, *, max_bytes=65536, **kwargs):
    """Keep connection probes bounded while returning normal response/JSON APIs."""
    target = normalize_outbound_url(url)
    with create_guarded_session() as session:
        response = session.request(method, target.url, stream=True, **kwargs)
        try:
            chunks = []
            size = 0
            if max_bytes:
                for chunk in response.iter_content(chunk_size=8192):
                    size += len(chunk)
                    if size > max_bytes:
                        raise OutboundDestinationError("The action connection test response is too large.")
                    chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
            return response
        finally:
            response.close()


def guard_login_credentials(credentials):
    """Protect SDK credential callbacks that run before its client is returned."""
    if credentials is None:
        return None

    class GuardedCredentials:
        def login(self, session, *args, **kwargs):
            guard_requests_session(session)
            return credentials.login(session, *args, **kwargs)

    return GuardedCredentials()


class GuardedTCPConnector(aiohttp.TCPConnector):
    async def _resolve_host(self, host, port, traces=None):
        normalize_outbound_url(f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}")
        addresses = await super()._resolve_host(host, port, traces=traces)
        for address in addresses:
            validate_outbound_address(address["host"])
        if not addresses:
            raise OutboundDestinationError("The action destination did not resolve to a usable address.")
        return addresses

    async def _create_proxy_connection(self, req, traces, timeout):
        raise OutboundDestinationError(
            "Forward-proxy routing is not supported for guarded action connections."
        )


def create_guarded_aiohttp_session(**kwargs):
    trace = aiohttp.TraceConfig()

    async def request_start(session, context, params):
        validate_outbound_headers(str(params.url), params.headers)

    async def request_redirect(session, context, params):
        try:
            validate_outbound_redirect(str(params.url), params.response.headers.get("Location", ""))
        except OutboundDestinationError:
            params.response.close()
            raise

    trace.on_request_start.append(request_start)
    trace.on_request_redirect.append(request_redirect)
    traces = [trace, *kwargs.pop("trace_configs", [])]
    return aiohttp.ClientSession(
        connector=GuardedTCPConnector(), trace_configs=traces, **kwargs,
    )


class _GuardedAsyncBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, backend):
        self.backend = backend

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            with anyio.fail_after(timeout):
                addresses = await anyio.to_thread.run_sync(
                    resolve_outbound_addresses, host, port, abandon_on_cancel=True,
                )
                last_error = None
                for address in addresses:
                    try:
                        return await self.backend.connect_tcp(
                            address, port, timeout=timeout, local_address=local_address,
                            socket_options=socket_options,
                        )
                    except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                        last_error = exc
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout("The action connection timed out.") from exc
        raise httpcore.ConnectError("The action service could not be reached.") from last_error

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise OutboundDestinationError("Unix sockets are not permitted for action HTTP connections.")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


class GuardedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, **kwargs):
        if kwargs.get("proxy") is not None or kwargs.get("uds") is not None:
            raise OutboundDestinationError("This guarded action transport requires a direct service connection.")
        super().__init__(**kwargs)
        self.trust_env = kwargs.get("trust_env", True)
        # HTTPX 0.28 delegates connections to this HTTP Core network backend.
        self._pool._network_backend = _GuardedAsyncBackend(self._pool._network_backend)

    async def handle_async_request(self, request):
        validate_outbound_headers(str(request.url), request.headers)
        _reject_forward_proxy(str(request.url), trust_env=self.trust_env)
        return await super().handle_async_request(request)


def create_guarded_httpx_client(headers=None, timeout=None, auth=None):
    async def response_received(response):
        if response.is_redirect and response.headers.get("location"):
            try:
                validate_outbound_redirect(str(response.request.url), response.headers["location"])
            except OutboundDestinationError:
                await response.aclose()
                raise

    return httpx.AsyncClient(
        headers=headers, auth=auth, timeout=timeout or httpx.Timeout(30, read=300),
        transport=GuardedAsyncHTTPTransport(), event_hooks={"response": [response_received]},
    )


@asynccontextmanager
async def guarded_websocket_connection(url, timeout=10):
    # MCP's native WebSocket helper has no client-factory hook; supply a vetted socket.
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    class CheckedConnect(connect):
        def process_redirect(self, exc):
            return exc

    for redirect_index in range(6):
        target = normalize_outbound_url(url)
        if target.scheme not in {"ws", "wss"}:
            raise OutboundDestinationError("This MCP transport requires a WebSocket URL.")
        _reject_forward_proxy(target.url.replace("wss:", "https:", 1).replace("ws:", "http:", 1))
        sock = None
        try:
            with anyio.fail_after(timeout):
                addresses = await anyio.to_thread.run_sync(
                    resolve_outbound_addresses, target.host, target.port, abandon_on_cancel=True,
                )
                for address in addresses:
                    family = socket.AF_INET6 if ":" in address else socket.AF_INET
                    sock = socket.socket(family, socket.SOCK_STREAM)
                    sock.setblocking(False)
                    try:
                        await asyncio.get_running_loop().sock_connect(sock, (address, target.port))
                        break
                    except OSError:
                        sock.close()
                        sock = None
            if sock is None:
                raise OSError("The MCP WebSocket service could not be reached.")
            options = {"server_hostname": target.host} if target.scheme == "wss" else {}
            try:
                connection = await CheckedConnect(
                    target.url, sock=sock, proxy=None, subprotocols=["mcp"],
                    open_timeout=timeout, **options,
                )
            except InvalidStatus as exc:
                location = exc.response.headers.get("Location")
                if exc.response.status_code not in {301, 302, 303, 307, 308} or not location:
                    raise
                if redirect_index == 5:
                    raise OutboundDestinationError("Too many MCP WebSocket redirects.") from exc
                url = validate_outbound_redirect(target.url, location)
                continue
            try:
                yield connection
            finally:
                await connection.close()
            return
        finally:
            if sock is not None:
                sock.close()
