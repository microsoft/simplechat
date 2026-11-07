# test_m365_chat_connection_persistence.py
"""
Functional regressions for independent, persistent Microsoft 365 chat connections.
Version: 0.261.355
Implemented in: 0.261.355

Real MSAL, AES-GCM, and SDK-default Cosmos responses exercise token expiry,
fresh app sessions, refresh rotation, revocation, and workflow isolation.
Only external I/O is replaced using the existing connection test fixtures.
"""

import copy
import json
import socket
import sys
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
import requests
from flask import Flask, session

import test_m365_connections as connection_fixtures
from test_m365_cosmos_sdk_contract import cosmos_factory  # noqa: F401
from functions_m365_data_lifecycle import is_live_m365_authorization, validate_m365_admin_record_edit

connections = connection_fixtures.connections


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Chat persistence tests must not contact external services.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def saved_chat():
    case = connection_fixtures.M365ConnectionTests()
    case.setUp()
    case.service.chat_readiness_provider = lambda: {"available": True, "message": ""}
    app = Flask(__name__)
    app.secret_key = "unit-test-only"
    try:
        with app.test_request_context():
            session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}
            yield case
    finally:
        case.doCleanups()


def connect_chat(case, sources=None):
    started = case.service.start_profile_chat_connection(
        "user-a", "tenant-a", sources or ["calendar", "email", "onedrive", "spo"],
        "https://simplechat.example.test/getAToken",
    )
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    case.http.nonce = query["nonce"][0]
    completed = case.service.complete_chat_connection(
        "user-a", "tenant-a", {"state": query["state"][0], "code": "chat-test-code"},
    )
    return completed


def fresh_session():
    session.clear()
    session["user"] = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"]}


def expire_saved_access_tokens(case):
    record, config = case.service._own_connection(
        case.service.connection_id("user-a", case.config, chat=True),
        "user-a", "tenant-a", chat=True,
    )
    envelope = record["encrypted_cache"]
    serialized = connections.decrypt_m365_cache(
        envelope, record, case.key_provider(envelope["key_version"], envelope["key_name"]),
    )
    cache = json.loads(serialized)
    for token in cache.get("AccessToken", {}).values():
        token["expires_on"] = "0"
    updated = dict(record)
    updated["encrypted_cache"] = connections.encrypt_m365_cache(
        json.dumps(cache), updated, case.key_provider(),
    )
    case.service._replace(record, updated)
    return config


def test_saved_sources_survive_expiry_fresh_login_and_narrow_refresh(saved_chat):
    case = saved_chat
    connect_chat(case)
    expire_saved_access_tokens(case)
    fresh_session()
    case.clock.advance(days=7)
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["status"] == "available"
    assert status["persistence"] == "saved"
    assert status["sources"] == ["calendar", "email", "onedrive", "spo"]
    posts_before = len(case.http.posts)
    token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token.get("access_token")
    assert len(case.http.posts) == posts_before + 1
    refreshed = case.service.read_chat_connection("user-a", "tenant-a")
    assert refreshed["sources"] == status["sources"]
    assert "token" not in json.dumps(refreshed)
    assert all(row["ttl"] == -1 for row in case.container.items.values())


def test_chat_and_workflow_credentials_are_distinct_and_disconnect_is_fenced(saved_chat):
    case = saved_chat
    workflow, _, _ = case.connect()
    connect_chat(case, ["email"])
    workflow_before = copy.deepcopy(case.container.items[("user-a", workflow["id"])])
    started = case.service.start_profile_chat_connection(
        "user-a", "tenant-a", ["email"], "https://simplechat.example.test/getAToken",
    )
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    case.http.nonce = query["nonce"][0]
    pending_flow = copy.deepcopy(session[connections.CHAT_AUTH_SESSION_KEY])
    disconnected = case.service.disconnect_chat("user-a", "tenant-a")
    assert disconnected["status"] == "not_connected"
    session[connections.CHAT_AUTH_SESSION_KEY] = pending_flow
    with pytest.raises(connections.M365ConnectionError) as stale:
        case.service.complete_chat_connection(
            "user-a", "tenant-a", {"state": query["state"][0], "code": "stale-callback"},
        )
    assert stale.value.code == "m365_connection_changed"
    fresh_session()
    session["token_cache"] = "stale-login-or-workflow-cache"
    rejected = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert rejected.get("error") in {"interactive_auth_required", "m365_reconnect_required"}
    assert case.container.items[("user-a", workflow["id"])] == workflow_before
    chat_rows = [row for row in case.container.items.values() if row["kind"] == "chat_connection"]
    assert len(chat_rows) == 1
    assert chat_rows[0]["encrypted_cache"] is None


def test_provider_interaction_is_durable_but_transient_errors_do_not_revoke(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    expire_saved_access_tokens(case)
    case.http.error = {"error": "temporarily_unavailable"}
    failure = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert failure["error"] == "m365_token_acquisition_failed"
    assert status["status"] == "available"
    case.http.error = {"error": "invalid_grant", "error_description": "Organization requires sign-in."}
    failure = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    fresh_session()
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert failure["error"] == "m365_reconnect_required"
    assert status["status"] == "reconnect_required"
    assert status["sources"] == ["email"]


def test_key_outage_never_downgrades_or_overwrites_saved_chat(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    rows = copy.deepcopy(case.container.items)
    case.service.chat_readiness_provider = lambda: {"available": False, "message": "Key Vault disabled."}
    fresh_session()
    with patch.object(case.service, "key_provider", side_effect=connections.M365ConnectionError(
        "m365_key_unavailable", "The connection key is unavailable.",
    )):
        failure = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert failure["error"] == "m365_key_unavailable"
    for key, row in rows.items():
        assert case.container.items[key]["encrypted_cache"] == row["encrypted_cache"]
    with pytest.raises(connections.M365ConnectionError):
        case.service.start_profile_chat_connection(
            "user-a", "tenant-a", ["email"], "https://simplechat.example.test/getAToken",
        )


def test_refresh_cannot_resurrect_concurrent_disconnect(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    expire_saved_access_tokens(case)
    original_factory = case.service.msal_factory

    def factory(cache, config):
        client = original_factory(cache, config)
        acquire = client.acquire_token_silent_with_error

        def disconnect_during_refresh(*args, **kwargs):
            result = acquire(*args, **kwargs)
            case.service.disconnect_chat("user-a", "tenant-a")
            return result

        client.acquire_token_silent_with_error = disconnect_during_refresh
        return client

    case.service.msal_factory = factory
    token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert "access_token" not in token
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["status"] == "not_connected"


def test_session_only_sources_do_not_disappear_when_access_tokens_expire(saved_chat):
    case = saved_chat
    case.service.chat_readiness_provider = lambda: {"available": False, "message": "Key Vault not configured."}
    connect_chat(case)
    raw = json.loads(session[connections.CHAT_CACHE_SESSION_KEY])
    for token in raw.get("AccessToken", {}).values():
        token["expires_on"] = "0"
    session[connections.CHAT_CACHE_SESSION_KEY] = json.dumps(raw)
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["persistence"] == "session"
    assert status["sources"] == ["calendar", "email", "onedrive", "spo"]
    assert "Key Vault" in status["persistence_message"]
    assert not case.container.items


def test_saved_chat_checks_exact_session_principal_and_deployment(saved_chat):
    case = saved_chat
    connect_chat(case)
    session["user"] = {"oid": "user-b", "tid": "tenant-a"}
    result = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert "access_token" not in result
    session["user"] = {"oid": "user-a", "tid": "foreign-tenant"}
    result = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert "access_token" not in result
    fresh_session()
    case.config = replace(case.config, cloud="different-cloud")
    result = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert "access_token" not in result


def test_corrupt_saved_cache_requires_reconnect_without_exposing_token(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    connection_id = case.service.connection_id("user-a", case.config, chat=True)
    case.container.items[("user-a", connection_id)]["encrypted_cache"]["ciphertext"] = "corrupt"
    result = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    fresh_session()
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert "access_token" not in result
    assert result["error"] == "m365_cache_unavailable"
    assert status["status"] == "reconnect_required"


def test_graph_rejection_marks_only_the_acquired_chat_generation(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token.get("access_token")
    context = SimpleNamespace(
        workflow_id=None, data_user_id="user-a", actor_user_id="user-a", tenant_id="tenant-a",
    )
    connections.mark_m365_chat_reconnect_required(context)
    fresh_session()
    rejected = case.service.read_chat_connection("user-a", "tenant-a")
    assert rejected["status"] == "reconnect_required"
    connect_chat(case, ["email"])
    fresh_session()
    connections.mark_m365_chat_reconnect_required(context)
    current = case.service.read_chat_connection("user-a", "tenant-a")
    assert current["status"] == "available"


def test_waiting_request_route_consumes_plain_query_rows():
    import test_m365_routes as route_cases

    case = route_cases.M365RouteTests()
    case.setUp()
    try:
        jobs = connection_fixtures.CosmosContainer("user_id")
        jobs.create_item(body={
            "id": "request-a", "user_id": "user-a", "type": "m365_execution_request",
            "status": "awaiting_sign_in", "conversation_id": "chat-a",
        })
        with patch.dict(sys.modules, {
            "config": route_cases.module_stub("config", cosmos_m365_execution_runs_container=jobs),
        }):
            response = case.client.get("/api/m365/requests")
        payload = response.get_json()
        assert response.status_code == 200
        assert payload["items"][0]["id"] == "request-a"
        assert payload["items"][0]["conversation_id"] == "chat-a"
        assert payload["csrf_token"]
    finally:
        case.doCleanups()


def test_failed_reconnect_preserves_previous_saved_credential(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    rows = copy.deepcopy(case.container.items)
    case.http.refresh_token = False
    with pytest.raises(connections.M365ConnectionError) as error:
        connect_chat(case, ["spo"])
    assert error.value.code == "m365_offline_consent_required"
    assert case.container.items == rows


def test_pre_upgrade_inflight_callback_requires_new_flow(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    rows = copy.deepcopy(case.container.items)
    started = case.service.start_profile_chat_connection(
        "user-a", "tenant-a", ["email"], "https://simplechat.example.test/getAToken",
    )
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    session[connections.CHAT_AUTH_SESSION_KEY].pop("persist")
    session[connections.CHAT_AUTH_SESSION_KEY].pop("generation")
    with pytest.raises(connections.M365ConnectionError) as error:
        case.service.complete_chat_connection(
            "user-a", "tenant-a", {"state": query["state"][0], "code": "old-flow"},
        )
    assert error.value.code == "m365_auth_state_invalid"
    assert case.container.items == rows


def test_real_sdk_chat_owner_preserves_encrypted_refresh_and_conditional_disconnect(saved_chat, cosmos_factory):
    case = saved_chat
    http, container = cosmos_factory("user_id")
    case.service.container_factory = lambda: container
    connect_chat(case, ["email"])
    fresh_session()
    token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token.get("access_token")
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["sources"] == ["email"]
    disconnected = case.service.disconnect_chat("user-a", "tenant-a")
    assert disconnected["status"] == "not_connected"
    records = list(http.records.values())
    assert len(records) == 1
    assert records[0]["kind"] == "chat_connection"
    assert records[0]["encrypted_cache"] is None
    writes = [headers for method, _, headers in http.calls if method == "PUT"]
    assert writes and all(headers.get("If-Match") for headers in writes)
    assert all(json.loads(headers["x-ms-documentdb-partitionkey"]) == ["user-a"] for headers in writes)
    workflow, _, _ = case.connect()
    assert workflow["status"] == "connected"
    assert workflow["id"] != records[0]["id"]


def test_silent_refresh_rotation_survives_another_service_instance(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    expire_saved_access_tokens(case)
    old_post = case.http.post

    def rotate(*args, **kwargs):
        response = old_post(*args, **kwargs)
        return connection_fixtures.HttpResponse({**response.payload, "refresh_token": "rotated-server-only"})

    with patch.object(case.http, "post", side_effect=rotate):
        token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token.get("access_token")
    row, _ = case.service._own_connection(
        case.service.connection_id("user-a", case.config, chat=True), "user-a", "tenant-a", chat=True,
    )
    envelope = row["encrypted_cache"]
    cache = connections.decrypt_m365_cache(
        envelope, row, case.key_provider(envelope["key_version"], envelope["key_name"]),
    )
    assert "rotated-server-only" in cache
    assert "rotated-server-only" not in json.dumps(row)
    new_service = connections.M365ConnectionService(
        container_factory=lambda: case.container, key_provider=case.key_provider,
        config_provider=lambda: case.config, msal_factory=case.msal_factory, clock=case.clock,
        chat_readiness_provider=lambda: {"available": True, "message": ""},
    )
    fresh_session()
    with patch.object(connections, "_service", new_service):
        token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token.get("access_token")


def test_network_failure_releases_lease_without_revoking_or_deleting(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    expire_saved_access_tokens(case)
    with patch.object(case.http, "post", side_effect=requests.Timeout):
        failure = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert failure["error"] == "m365_token_acquisition_failed"
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["status"] == "available"
    token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token.get("access_token")


def test_missing_returned_permissions_never_release_a_token(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    expire_saved_access_tokens(case)
    case.http.scope_transform = lambda scopes: "User.Read"
    token = connections.get_m365_access_token(["Mail.Read"], include_auth_url=False)
    assert token["error"] == "m365_consent_required"
    assert "access_token" not in token
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["status"] == "reconnect_required"
    assert status["sources"] == ["email"]


def test_chat_credentials_are_excluded_from_transfers_and_raw_editing(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    record = next(iter(case.container.items.values()))
    protected = is_live_m365_authorization(record)
    assert protected
    with pytest.raises(ValueError):
        validate_m365_admin_record_edit(record, {**record, "status": "connected"})


def test_in_chat_incremental_consent_keeps_previously_connected_sources(saved_chat):
    case = saved_chat
    connect_chat(case, ["email"])
    started = case.service.start_chat_connection(
        "user-a", "tenant-a", "request-id", "conversation-id",
        ["User.Read", "Files.Read.All", "Sites.Read.All"],
        "https://simplechat.example.test/getAToken",
    )
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    assert any(scope.endswith("/Mail.Read") for scope in query["scope"][0].split())
    case.http.nonce = query["nonce"][0]
    case.service.complete_chat_connection(
        "user-a", "tenant-a", {"state": query["state"][0], "code": "incremental-chat-code"},
    )
    status = case.service.read_chat_connection("user-a", "tenant-a")
    assert status["sources"] == ["email", "onedrive", "spo"]
