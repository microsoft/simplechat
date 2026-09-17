# test_yamcs_user_auth_runtime.py
#!/usr/bin/env python3
"""
Functional tests for invocation-local Yamcs authentication.
Version: 0.261.107
Implemented in: 0.261.107

Use the pinned SDK, native Requests preparation/redirect handling, and intercepted
HTTP adapters. No live server, account credentials, or application config is used.
Private repair fallbacks preserve action attribution and propagate storage failures.
"""

import copy
import importlib
import importlib.metadata
import io
import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import requests
from requests.adapters import HTTPAdapter
from yamcs.client import APIKeyCredentials, BasicAuthCredentials, Credentials, YamcsClient
from yamcs.protobuf.instances import instances_pb2, instances_service_pb2
from yamcs.protobuf.server import server_service_pb2

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
# These modules deliberately have no config.py or storage imports.
action_auth = importlib.import_module("functions_action_auth")
action_catalog = importlib.import_module("functions_action_catalog")
client_helpers = importlib.import_module("functions_yamcs_client")
execution = importlib.import_module("agent_execution_context")
BASE_URL = "https://yamcs.example.test/service"


def manifest(profile="yamcs_login", **overrides):
    result = {
        "id": "c8258859-2703-419c-ac22-095562dd07bc",
        "name": "global_yamcs",
        "type": "yamcs",
        "scope": "global",
        "endpoint": BASE_URL,
        "auth": {"type": "username_password"},
        "additionalFields": {
            "server_url": BASE_URL,
            "instance": "simulator",
            "auth_method": "username_password",
            "tls_verify": True,
            "timeout": 7,
            "max_rows": 2,
        },
        "credential_requirement": {
            "id": "406d8440-c675-4438-afd6-89565f3d4935",
            "source": "current_user",
            "identity_name": "Yamcs",
            "profile": profile,
        },
    }
    result.update(overrides)
    return result


def identity_auth(profile, actor="alice"):
    if profile in {"yamcs_login", "http_basic"}:
        return {
            "auth_type": "username_password",
            "username": f"synthetic-{actor}",
            "password": f"synthetic-password-{actor}",
        }
    return {"auth_type": profile, "secret": f"synthetic-secret-{actor}"}


def inline_manifest(profile):
    action = action_auth.normalize_action_credential_requirement(manifest(profile))
    action.pop("credential_requirement")
    credentials = identity_auth(profile)
    action["auth"]["key"] = credentials.get("secret") or credentials.get("password")
    if "username" in credentials:
        action["auth"]["identity"] = credentials["username"]
    return action


class TrackedResponse(requests.Response):
    def __init__(self, request, status, content, headers):
        super().__init__()
        self.request = request
        self.url = request.url
        self.status_code = status
        self.headers.update(headers)
        self._content = content
        self._content_consumed = True
        self.raw = io.BytesIO(content)
        self.closed = False

    def close(self):
        self.closed = True
        self.raw.close()
        super().close()


class FakeService:
    """Intercept only the final transport, preserving all native SDK/auth behavior."""

    def __init__(self):
        self.requests = []
        self.responses = []
        self.sessions = []
        self.closed_sessions = []
        self.routes = {}
        self.instances = ["simulator"]
        self.ambient_auth = False

    def send(self, _adapter, request, **kwargs):
        self.requests.append({
            "method": request.method,
            "url": request.url,
            "headers": dict(request.headers),
            "body": request.body,
            **kwargs,
        })
        route = self.routes.get(request.url)
        if isinstance(route, Exception):
            raise route
        if route:
            status, content, headers = route
        elif urlsplit(request.url).path.endswith("/auth/token"):
            status, headers = 200, {"Content-Type": "application/json"}
            content = json.dumps({
                "access_token": "synthetic-exchanged-access-token",
                "refresh_token": "synthetic-exchanged-refresh-token",
                "expires_in": 600,
            }).encode()
        elif urlsplit(request.url).path.endswith("/api/instances"):
            message = instances_service_pb2.ListInstancesResponse()
            for name in self.instances:
                message.instances.add(name=name)
            status, content, headers = 200, message.SerializeToString(), {}
        elif "/api/instances/" in urlsplit(request.url).path:
            instance = unquote(urlsplit(request.url).path.rsplit("/api/instances/", 1)[1])
            if instance in self.instances:
                message = instances_pb2.YamcsInstance(name=instance)
                status, content, headers = 200, message.SerializeToString(), {}
            else:
                status, content, headers = 404, b"", {}
        else:
            status, headers = 200, {}
            content = server_service_pb2.GetServerInfoResponse().SerializeToString()
        response = TrackedResponse(request, status, content, headers)
        self.responses.append(response)
        return response


@pytest.fixture
def service(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", lambda _url: None)
    fake = FakeService()
    original_init = requests.Session.__init__
    original_close = requests.Session.close

    def initialize(session):
        original_init(session)
        fake.sessions.append(session)
        if fake.ambient_auth:
            session.auth = requests.auth.HTTPBasicAuth("ambient-user", "ambient-password")
            session.headers.update({"Authorization": "Bearer ambient-token", "x-api-key": "ambient-key"})
            session.proxies["https"] = "https://ambient-proxy.invalid"

    def close(session):
        fake.closed_sessions.append(session)
        original_close(session)

    monkeypatch.setattr(requests.Session, "__init__", initialize)
    monkeypatch.setattr(requests.Session, "close", close)
    monkeypatch.setattr(HTTPAdapter, "send", lambda adapter, request, **kwargs: fake.send(adapter, request, **kwargs))
    return fake


@pytest.fixture
def plugin_module(monkeypatch):
    invocation_logger = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
    invocation_logger.plugin_function_logger = lambda _name: lambda function: function
    monkeypatch.setitem(sys.modules, "semantic_kernel_plugins.plugin_invocation_logger", invocation_logger)
    yield import_app_module("semantic_kernel_plugins.yamcs_plugin")


def test_pinned_sdk_and_implementation_version():
    assert importlib.metadata.version("yamcs-client") == "2.1.0"
    assert_app_version_at_least("0.261.107")


@pytest.mark.parametrize("profile", ["yamcs_login", "http_basic", "bearer_token", "api_key"])
def test_native_profiles_use_distinct_protocols(profile, service, monkeypatch):
    action = manifest(profile)
    before = copy.deepcopy(action)
    credentials = identity_auth(profile)
    resolver = Mock(side_effect=AssertionError("Explicit identity must bypass actor resolution."))
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    client = client_helpers.create_yamcs_client(action, identity_auth=credentials)
    assert isinstance(client, YamcsClient)
    client.get_server_info()
    session = client.ctx.session
    if profile == "yamcs_login":
        assert type(client.ctx.credentials) is Credentials
        assert [request["method"] for request in service.requests] == ["POST", "GET"]
        token_request = service.requests[0]
        assert token_request["url"] == f"{BASE_URL}/auth/token"
        assert parse_qs(token_request["body"]) == {
            "grant_type": ["password"],
            "username": [credentials["username"]],
            "password": [credentials["password"]],
        }
        assert service.requests[-1]["headers"]["Authorization"] == "Bearer synthetic-exchanged-access-token"
        assert "Authorization" not in token_request["headers"]
    elif profile == "http_basic":
        assert type(client.ctx.credentials) is BasicAuthCredentials
        expected = requests.auth._basic_auth_str(credentials["username"], credentials["password"])
        assert service.requests[0]["headers"]["Authorization"] == expected
        assert [request["method"] for request in service.requests] == ["GET"]
    elif profile == "bearer_token":
        assert type(client.ctx.credentials) is Credentials
        assert service.requests[0]["headers"]["Authorization"] == f"Bearer {credentials['secret']}"
        assert [request["method"] for request in service.requests] == ["GET"]
    else:
        assert type(client.ctx.credentials) is APIKeyCredentials
        assert service.requests[0]["headers"]["x-api-key"] == credentials["secret"]
        assert "Authorization" not in service.requests[0]["headers"]
        assert [request["method"] for request in service.requests] == ["GET"]
    assert all(request["timeout"] == 7 and request["verify"] is True for request in service.requests)
    assert client.ctx._session_renewer is None
    client.close()
    assert service.closed_sessions == [session]
    assert all(response.closed for response in service.responses)
    assert "Authorization" not in session.headers and "x-api-key" not in session.headers
    assert action == before
    resolver.assert_not_called()


@pytest.mark.parametrize("profile", ["yamcs_login", "http_basic", "bearer_token", "api_key"])
def test_ambient_auth_cannot_override_explicit_native_credentials(profile, service, monkeypatch):
    service.ambient_auth = True
    netrc = Mock(side_effect=AssertionError("Ambient accounts must not be consulted."))
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", netrc)
    client = client_helpers.create_yamcs_client(manifest(profile), identity_auth=identity_auth(profile))
    client.get_server_info()
    client.close()
    assert all("ambient" not in json.dumps(request["headers"]) for request in service.requests)
    assert all(request["proxies"]["https"] == "https://ambient-proxy.invalid" for request in service.requests)
    assert service.sessions[0].trust_env is True
    netrc.assert_not_called()


@pytest.mark.parametrize("per_user", [False, True], ids=["legacy", "personal"])
@pytest.mark.parametrize("profile", ["yamcs_login", "http_basic", "bearer_token", "api_key"])
def test_environment_proxy_and_ca_reach_native_authenticated_requests(
    per_user, profile, service, monkeypatch
):
    proxy = "http://enterprise-proxy.example.test:8080"
    ca_bundle = str(APP_DIR / "enterprise-test-ca.pem")
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", ca_bundle)
    netrc = Mock(side_effect=AssertionError("Ambient netrc identity must not be used."))
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", netrc)
    action = manifest(profile) if per_user else inline_manifest(profile)
    client = client_helpers.create_yamcs_client(
        action, identity_auth=identity_auth(profile) if per_user else None
    )
    client.get_server_info()
    client.close()
    assert all(request["proxies"]["https"] == proxy for request in service.requests)
    assert all(request["verify"] == ca_bundle for request in service.requests)
    assert all(request["timeout"] == 7 for request in service.requests)
    assert service.sessions[0].trust_env is True
    assert service.closed_sessions == service.sessions
    netrc.assert_not_called()


@pytest.mark.parametrize("per_user", [False, True], ids=["legacy", "personal"])
@pytest.mark.parametrize("profile", ["yamcs_login", "http_basic", "bearer_token", "api_key"])
def test_redirect_auth_cannot_use_netrc_but_preserves_proxy_and_ca(
    per_user, profile, service, monkeypatch
):
    proxy = "http://enterprise-proxy.example.test:8080"
    ca_bundle = str(APP_DIR / "enterprise-test-ca.pem")
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", ca_bundle)
    netrc = Mock(side_effect=AssertionError("Redirects must not replace explicit credentials with netrc."))
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", netrc)
    native_rebuild_auth = requests.Session.rebuild_auth
    if profile == "yamcs_login":
        source, target = f"{BASE_URL}/auth/token", f"{BASE_URL}/gateway/auth/token"
    else:
        source, target = f"{BASE_URL}/api", f"{BASE_URL}/api/metadata"
    service.routes[source] = (307, b"", {"Location": target})
    action = manifest(profile) if per_user else inline_manifest(profile)
    client = client_helpers.create_yamcs_client(
        action, identity_auth=identity_auth(profile) if per_user else None
    )
    client.get_server_info()
    client.close()
    assert len(service.requests) == (3 if profile == "yamcs_login" else 2)
    assert service.requests[1]["url"] == target
    if profile == "yamcs_login":
        assert service.requests[0]["body"] == service.requests[1]["body"]
        assert "Authorization" not in service.requests[1]["headers"]
    else:
        header = "x-api-key" if profile == "api_key" else "Authorization"
        assert service.requests[0]["headers"][header] == service.requests[1]["headers"][header]
    assert all(request["proxies"]["https"] == proxy for request in service.requests)
    assert all(request["verify"] == ca_bundle for request in service.requests)
    assert all(request["timeout"] == 7 for request in service.requests)
    assert requests.Session.rebuild_auth is native_rebuild_auth
    assert service.closed_sessions == service.sessions
    netrc.assert_not_called()


def test_enterprise_transport_does_not_weaken_personal_redirect_policy(service, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://enterprise-proxy.example.test:8080")
    ca_bundle = str(APP_DIR / "enterprise-test-ca.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", ca_bundle)
    service.routes[f"{BASE_URL}/auth/token"] = (
        307, b"", {"Location": "https://unapproved.example.test/auth/token"}
    )
    with pytest.raises(client_helpers.YamcsConnectionError):
        client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    assert len(service.requests) == 1
    assert service.requests[0]["verify"] == ca_bundle
    assert service.closed_sessions == service.sessions


@pytest.mark.parametrize("status,error_type", [
    (401, client_helpers.YamcsAuthenticationError),
    (403, client_helpers.YamcsPermissionError),
    (500, client_helpers.YamcsConnectionError),
])
@pytest.mark.parametrize("profile", ["yamcs_login", "http_basic", "api_key"])
def test_provider_errors_are_typed_safe_and_close_resources(status, error_type, profile, service):
    path = "/auth/token" if profile == "yamcs_login" else "/api"
    service.routes[f"{BASE_URL}{path}"] = (
        status, b"upstream echoed synthetic-password-alice and Authorization contents", {}
    )
    client = None
    try:
        with pytest.raises(error_type) as caught:
            client = client_helpers.create_yamcs_client(manifest(profile), identity_auth=identity_auth(profile))
            client.get_server_info()
        assert str(caught.value) == str(error_type())
        assert "synthetic" not in str(caught.value)
    finally:
        if client is not None:
            client.close()
    assert service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)


def test_initial_login_timeout_is_applied_before_any_sdk_request(service):
    service.routes[f"{BASE_URL}/auth/token"] = requests.Timeout("synthetic-password-alice")
    with pytest.raises(client_helpers.YamcsConnectionError) as caught:
        client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    assert service.requests[0]["timeout"] == 7
    assert "synthetic" not in str(caught.value)
    assert service.closed_sessions == service.sessions


def test_malformed_login_response_closes_failed_constructor(service):
    service.routes[f"{BASE_URL}/auth/token"] = (200, b'{"unexpected":"synthetic-password-alice"}', {})
    with pytest.raises(client_helpers.YamcsConnectionError) as caught:
        client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    assert "synthetic" not in str(caught.value)
    assert service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)


def test_failure_after_native_login_still_closes_constructor_resources(service, monkeypatch):
    original_init = YamcsClient.__init__

    def fail_after_login(client, *args, **kwargs):
        original_init(client, *args, **kwargs)
        raise RuntimeError("synthetic-password-alice")

    monkeypatch.setattr(YamcsClient, "__init__", fail_after_login)
    with pytest.raises(client_helpers.YamcsConnectionError):
        client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)


def test_native_token_refresh_is_guarded_without_background_threads(service):
    client = client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    client.ctx.credentials.expiry = datetime.now(timezone.utc) - timedelta(seconds=1)
    client.get_server_info()
    assert client.ctx._session_renewer is None
    client.close()
    assert [request["method"] for request in service.requests] == ["POST", "POST", "GET"]
    assert parse_qs(service.requests[1]["body"])["grant_type"] == ["refresh_token"]
    assert all(request["timeout"] == 7 and request["verify"] is True for request in service.requests)
    assert service.closed_sessions == service.sessions


def test_per_request_timeout_and_tls_cannot_weaken_personal_auth_policy(service):
    client = client_helpers.create_yamcs_client(manifest("api_key"), identity_auth=identity_auth("api_key"))
    client.ctx.get_proto("", timeout=(999, None), verify=False)
    client.close()
    assert service.requests[0]["timeout"] == (7, 7)
    assert service.requests[0]["verify"] is True


@pytest.mark.parametrize("target", [
    "https://other.example.test/service/auth/token",
    "https://yamcs.example.test:8443/service/auth/token",
    "http://yamcs.example.test/service/auth/token",
    "https://yamcs.example.test/outside/auth/token",
    "https://user:password@yamcs.example.test/service/auth/token",
    "https://yamcs.example.test/service/auth/token?recipient=other",
    "https://yamcs.example.test/service/auth/token#fragment",
    "https://yamcs.example.test/service/%2e%2e/outside/auth/token",
])
@pytest.mark.parametrize("status", [302, 307, 308])
def test_initial_login_rejects_unapproved_redirect_before_forwarding(target, status, service):
    service.routes[f"{BASE_URL}/auth/token"] = (status, b"", {"Location": target})
    with pytest.raises(client_helpers.YamcsConnectionError):
        client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)


@pytest.mark.parametrize("profile", ["http_basic", "bearer_token", "api_key"])
def test_later_reads_reject_cross_target_redirects(profile, service):
    service.routes[f"{BASE_URL}/api"] = (307, b"", {"Location": "https://other.example.test/api"})
    client = client_helpers.create_yamcs_client(manifest(profile), identity_auth=identity_auth(profile))
    try:
        with pytest.raises(client_helpers.YamcsConnectionError):
            client.get_server_info()
    finally:
        client.close()
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions


def test_same_approved_target_redirect_keeps_native_basic_header(service):
    service.routes[f"{BASE_URL}/api"] = (307, b"", {"Location": f"{BASE_URL}/api/metadata"})
    client = client_helpers.create_yamcs_client(manifest("http_basic"), identity_auth=identity_auth("http_basic"))
    client.get_server_info()
    client.close()
    assert len(service.requests) == 2
    assert service.requests[0]["headers"]["Authorization"] == service.requests[1]["headers"]["Authorization"]
    assert all(request["timeout"] == 7 and request["verify"] is True for request in service.requests)


def test_initial_login_allows_only_same_approved_target_redirect(service):
    service.routes[f"{BASE_URL}/auth/token"] = (
        307, b"", {"Location": f"{BASE_URL}/gateway/auth/token"}
    )
    client = client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    client.get_server_info()
    client.close()
    assert [request["method"] for request in service.requests] == ["POST", "POST", "GET"]
    assert service.requests[0]["body"] == service.requests[1]["body"]
    assert all(request["timeout"] == 7 and request["verify"] is True for request in service.requests)


def test_redirect_loops_are_bounded_and_closed(service):
    service.routes[f"{BASE_URL}/auth/token"] = (307, b"", {"Location": f"{BASE_URL}/auth/token"})
    with pytest.raises(client_helpers.YamcsConnectionError):
        client_helpers.create_yamcs_client(manifest(), identity_auth=identity_auth("yamcs_login"))
    assert len(service.requests) <= 4
    assert service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)


@pytest.mark.parametrize("url", [
    "http://localhost:8090",
    "https://user:password@yamcs.example.test/service",
    f"{BASE_URL}?credential=not-allowed",
    f"{BASE_URL}#fragment",
    "https://yamcs.example.test/service/../outside",
])
def test_unsafe_requirement_destinations_fail_without_resolving(url, service, monkeypatch):
    action = manifest(endpoint=url)
    action["additionalFields"]["server_url"] = url
    resolver = Mock(side_effect=AssertionError("Invalid destinations must not read identities."))
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    with pytest.raises(ValueError):
        client_helpers.create_yamcs_client(action)
    assert not service.sessions and not service.requests
    resolver.assert_not_called()


@pytest.mark.parametrize("requirement", [
    None, {}, [], "current_user",
    {"source": "current_user", "identity_name": "Yamcs", "profile": "oauth"},
    {"source": "owner", "identity_name": "Yamcs", "profile": "http_basic"},
    {"source": "current_user", "identity_name": "Yamcs", "profile": ["http_basic"]},
    {"source": "current_user", "identity_name": "Yamcs", "profile": "api_key", "identity_id": "not-allowed"},
])
def test_invalid_requirements_fail_closed_without_inline_fallback(requirement, service, monkeypatch):
    action = manifest(credential_requirement=requirement)
    resolver = Mock()
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    with pytest.raises(ValueError):
        client_helpers.create_yamcs_client(action)
    resolver.assert_not_called()
    assert not service.sessions


@pytest.mark.parametrize("override", [
    {"auth": {"type": "basic", "identity": "forbidden", "key": "forbidden"}},
    {"identity_id": "forbidden"},
    {"scope": "personal"},
    {"group_id": "forbidden"},
    {"user_id": "forbidden"},
])
def test_personal_requirement_rejects_mixed_credentials_and_scopes(override, service):
    with pytest.raises(ValueError):
        client_helpers.create_yamcs_client(manifest(**override), identity_auth=identity_auth("yamcs_login"))
    assert not service.sessions


def test_tls_cannot_be_disabled_for_personal_auth(service):
    action = manifest()
    action["additionalFields"]["tls_verify"] = False
    with pytest.raises(ValueError):
        client_helpers.create_yamcs_client(action, identity_auth=identity_auth("yamcs_login"))
    assert not service.sessions


def test_missing_execution_actor_fails_before_network(service, plugin_module):
    with pytest.raises(PermissionError):
        client_helpers.create_yamcs_client(manifest())
    result = plugin_module.YamcsPlugin(manifest()).list_instances()
    assert result["success"] is False and result["error_type"] == "permission"
    assert not service.sessions


def test_missing_owned_identity_control_signal_propagates_unchanged(service, plugin_module, monkeypatch):
    signal = action_auth.ActionCredentialsRequired({"request_id": "private-request"})
    resolver = Mock(side_effect=signal)
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    plugin = plugin_module.YamcsPlugin(manifest())
    resolver.assert_not_called()
    with pytest.raises(action_auth.ActionCredentialsRequired) as caught:
        plugin.list_instances()
    assert caught.value is signal
    assert not service.requests and not service.sessions


def test_shared_plugin_resolves_each_actor_without_mutation(service, plugin_module, monkeypatch):
    credentials = {actor: identity_auth("api_key", actor) for actor in ("alice", "bob")}
    barrier = Barrier(2)
    resolved = []

    def resolve(actor, _action):
        resolved.append(actor)
        barrier.wait(timeout=10)
        return credentials[actor]

    state = importlib.import_module("functions_action_auth_state")
    monkeypatch.setattr(state, "_resolve_action_credentials", resolve)
    original = manifest("api_key")
    original_snapshot = copy.deepcopy(original)
    plugin = plugin_module.YamcsPlugin(original)
    shared_snapshot = copy.deepcopy(plugin.manifest)
    assert resolved == []

    def invoke(actor):
        frame = execution.AgentExecutionFrame(
            identity=execution.ExecutionIdentity(user_id=actor, conversation_id="shared-owned-by-alice"),
            caller={"id": "delegated-agent", "user_id": "agent-owner"},
            budget=execution.DelegationBudget(),
        )
        with execution.agent_execution(frame):
            return plugin.list_instances()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(invoke, ("alice", "bob")))
    assert all(result["success"] for result in results)
    assert set(resolved) == {"alice", "bob"}
    assert {request["headers"]["x-api-key"] for request in service.requests} == {
        credentials["alice"]["secret"], credentials["bob"]["secret"],
    }
    assert len({id(session) for session in service.sessions}) == 2
    assert len(service.closed_sessions) == 2
    assert original == original_snapshot and plugin.manifest == shared_snapshot
    assert "secret" not in json.dumps(plugin.__dict__, default=str)


@pytest.mark.parametrize("status,error_type", [(403, "permission"), (500, "connection")])
def test_non_authentication_failure_never_invalidates_personal_credentials(
    status, error_type, service, plugin_module, monkeypatch
):
    service.routes[f"{BASE_URL}/api/instances"] = (status, b"synthetic-secret-alice", {})
    invalidate = Mock()
    monkeypatch.setattr(action_auth, "invalidate_action_auth_credentials", invalidate)
    resolver = Mock(return_value=identity_auth("api_key"))
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    result = plugin_module.YamcsPlugin(manifest("api_key")).list_instances()
    assert result["success"] is False and result["error_type"] == error_type
    assert "synthetic" not in json.dumps(result)
    invalidate.assert_not_called()
    assert resolver.call_count == 1
    assert service.closed_sessions == service.sessions


def test_confirmed_rejection_invalidates_actor_binding_and_propagates_private_repair(
    service, plugin_module, monkeypatch
):
    service.routes[f"{BASE_URL}/api/instances"] = (401, b"synthetic-secret-alice", {})
    signal = action_auth.ActionCredentialsRequired({"request_id": "private-repair-request"})
    resolver = Mock(side_effect=[identity_auth("api_key"), signal])
    invalidator = Mock()
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    monkeypatch.setattr(action_auth, "invalidate_action_auth_credentials", invalidator)
    plugin = plugin_module.YamcsPlugin(manifest("api_key"))
    before = copy.deepcopy(plugin.manifest)
    with pytest.raises(action_auth.ActionCredentialsRequired) as caught:
        plugin.list_instances()
    assert caught.value is signal
    assert invalidator.call_count == 1
    assert resolver.call_count == 2
    assert plugin.manifest == before
    assert service.closed_sessions == service.sessions
    assert "synthetic" not in json.dumps(caught.value.to_payload())


def test_concurrent_repair_does_not_replay_a_rejected_tool_call(service, plugin_module, monkeypatch):
    service.routes[f"{BASE_URL}/api/instances"] = (401, b"", {})
    repaired_credentials = identity_auth("api_key", "repaired")
    monkeypatch.setattr(
        action_auth, "resolve_action_auth_credentials",
        Mock(side_effect=[identity_auth("api_key"), repaired_credentials]),
    )
    monkeypatch.setattr(action_auth, "invalidate_action_auth_credentials", Mock())
    action = manifest("api_key")
    with pytest.raises(action_auth.ActionCredentialsRequired) as caught:
        plugin_module.YamcsPlugin(action).list_instances()
    assert repaired_credentials == {}
    assert caught.value.action_ref == action_catalog._action_ref("global", "global", action["id"])
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions


def test_invalidation_conflict_remains_a_private_control_signal(service, plugin_module, monkeypatch):
    service.routes[f"{BASE_URL}/api/instances"] = (401, b"", {})
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", lambda _action: identity_auth("api_key"))
    monkeypatch.setattr(
        action_auth, "invalidate_action_auth_credentials", Mock(side_effect=action_auth.ActionAuthConflict())
    )
    action = manifest("api_key")
    with pytest.raises(action_auth.ActionCredentialsRequired) as caught:
        plugin_module.YamcsPlugin(action).list_instances()
    assert caught.value.action_ref == action_catalog._action_ref("global", "global", action["id"])
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions


def test_stale_second_resolution_preserves_fallback_action_reference(service, plugin_module, monkeypatch):
    service.routes[f"{BASE_URL}/api/instances"] = (401, b"", {})
    monkeypatch.setattr(
        action_auth, "resolve_action_auth_credentials",
        Mock(side_effect=[identity_auth("api_key"), action_auth.ActionAuthConflict()]),
    )
    monkeypatch.setattr(action_auth, "invalidate_action_auth_credentials", Mock())
    action = manifest("api_key")
    with pytest.raises(action_auth.ActionCredentialsRequired) as caught:
        plugin_module.YamcsPlugin(action).list_instances()
    assert caught.value.action_ref == action_catalog._action_ref("global", "global", action["id"])
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions


def test_unsaved_draft_fallback_never_fabricates_an_action_reference(service, plugin_module, monkeypatch):
    service.routes[f"{BASE_URL}/api/instances"] = (401, b"", {})
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", lambda _action: identity_auth("api_key"))
    monkeypatch.setattr(action_auth, "invalidate_action_auth_credentials", Mock())
    action = manifest("api_key")
    action.pop("id")
    with pytest.raises(action_auth.ActionCredentialsRequired) as caught:
        plugin_module.YamcsPlugin(action).list_instances()
    assert caught.value.action_ref is None
    assert len(service.requests) == 1
    assert service.closed_sessions == service.sessions


@pytest.mark.parametrize("stage", ["initial_resolution", "invalidation", "repair_resolution"])
def test_credential_storage_failures_propagate_unchanged(stage, service, plugin_module, monkeypatch):
    service.routes[f"{BASE_URL}/api/instances"] = (401, b"", {})
    failure = action_auth.ActionAuthStorageError()
    if stage == "initial_resolution":
        resolver = Mock(side_effect=failure)
    elif stage == "repair_resolution":
        resolver = Mock(side_effect=[identity_auth("api_key"), failure])
    else:
        resolver = Mock(return_value=identity_auth("api_key"))
    invalidator = Mock(side_effect=failure) if stage == "invalidation" else Mock()
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    monkeypatch.setattr(action_auth, "invalidate_action_auth_credentials", invalidator)
    with pytest.raises(action_auth.ActionAuthStorageError) as caught:
        plugin_module.YamcsPlugin(manifest("api_key")).list_instances()
    assert caught.value is failure
    assert len(service.requests) == (0 if stage == "initial_resolution" else 1)
    assert service.closed_sessions == service.sessions


def test_connection_validation_is_bounded_and_never_resolves_explicit_auth(service, monkeypatch):
    resolver = Mock(side_effect=AssertionError("Explicit test credentials must not recursively resolve."))
    monkeypatch.setattr(action_auth, "resolve_action_auth_credentials", resolver)
    service.instances = ["simulator", "second", "third"]
    action = manifest("http_basic")
    action["additionalFields"]["timeout"] = 300
    before = copy.deepcopy(action)
    result = client_helpers.validate_yamcs_credentials(action, identity_auth("http_basic"))
    assert result == {
        "success": True,
        "message": "Successfully connected to Yamcs.",
        "instance": "simulator",
        "instance_count": 2,
        "truncated": True,
    }
    assert [request["method"] for request in service.requests] == ["GET", "GET", "GET"]
    assert service.requests[1]["url"] == f"{BASE_URL}/api/instances/simulator"
    assert all(request["timeout"] == 30 for request in service.requests)
    assert service.closed_sessions == service.sessions
    assert action == before
    resolver.assert_not_called()


def test_unavailable_instance_is_not_mislabeled_as_bad_credentials(service):
    service.instances = ["another-instance"]
    with pytest.raises(client_helpers.YamcsConnectionError):
        client_helpers.validate_yamcs_credentials(manifest("api_key"), identity_auth("api_key"))
    assert service.requests[-1]["url"] == f"{BASE_URL}/api/instances/simulator"
    assert service.responses[-1].status_code == 404
    assert service.closed_sessions == service.sessions


def test_configured_instance_beyond_discovery_limit_is_validated_directly(service):
    service.instances = ["other", "simulator"]
    action = manifest("api_key")
    action["additionalFields"]["max_rows"] = 1
    result = client_helpers.validate_yamcs_credentials(action, identity_auth("api_key"))
    assert result == {
        "success": True,
        "message": "Successfully connected to Yamcs.",
        "instance": "simulator",
        "instance_count": 1,
        "truncated": True,
    }
    assert [request["url"] for request in service.requests] == [
        f"{BASE_URL}/api",
        f"{BASE_URL}/api/instances/simulator",
        f"{BASE_URL}/api/instances",
    ]
    assert all(request["method"] == "GET" for request in service.requests)
    assert service.closed_sessions == service.sessions
    assert all(response.closed for response in service.responses)


@pytest.mark.parametrize("credentials", [
    {}, {"auth_type": "client_secret", "secret": "synthetic-secret"},
    {"auth_type": "api_key", "secret": ""},
    {"auth_type": "api_key", "secret": {"value": "not-a-string"}},
])
def test_incompatible_identity_auth_is_rejected_before_client_creation(credentials, service):
    with pytest.raises(ValueError):
        client_helpers.create_yamcs_client(manifest("api_key"), identity_auth=credentials)
    assert not service.requests and not service.sessions


def test_legacy_inline_and_hydrated_identity_modes_keep_native_behavior(service):
    action = manifest("http_basic")
    action.pop("credential_requirement")
    action["auth"] = {"type": "basic", "identity": "synthetic-alice", "key": "synthetic-password-alice"}
    action["additionalFields"]["identity_auth_type"] = "username_password"
    client = client_helpers.create_yamcs_client(action)
    client.get_server_info()
    client.close()
    assert [request["method"] for request in service.requests] == ["GET"]
    assert service.requests[0]["headers"]["Authorization"].startswith("Basic ")
    action["identity_id"] = "existing-same-scope-identity"
    action["auth"]["type"] = "username_password"
    client = client_helpers.create_yamcs_client(action)
    client.get_server_info()
    client.close()
    assert [request["method"] for request in service.requests][-2:] == ["POST", "GET"]


def test_legacy_anonymous_local_development_remains_supported(service):
    action = manifest()
    action.pop("credential_requirement")
    action["endpoint"] = "http://localhost:8090"
    action["additionalFields"].update({"server_url": action["endpoint"], "tls_verify": False})
    action["auth"] = {"type": "NoAuth"}
    client = client_helpers.create_yamcs_client(action)
    client.get_server_info()
    client.close()
    assert service.requests[0]["verify"] is False
    assert "Authorization" not in service.requests[0]["headers"]
    assert service.sessions[0].trust_env is True
    assert service.requests[0]["timeout"] == 7


def test_unexpected_errors_never_reach_outputs_or_logs(service, plugin_module, monkeypatch):
    log = Mock()
    monkeypatch.setattr(plugin_module, "log_event", log)
    monkeypatch.setattr(
        action_auth, "resolve_action_auth_credentials", lambda _manifest: identity_auth("api_key")
    )
    plugin = plugin_module.YamcsPlugin(manifest("api_key"))

    def fail(_client):
        raise RuntimeError("synthetic-secret-alice Authorization: unsafe upstream exception")

    result = plugin._run("list_instances", fail)
    assert result["error"] == "The Yamcs request failed."
    assert "synthetic" not in json.dumps(result)
    assert "synthetic" not in str(log.call_args_list)
    assert not any(call.kwargs.get("exceptionTraceback") for call in log.call_args_list)
    assert service.closed_sessions == service.sessions


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
