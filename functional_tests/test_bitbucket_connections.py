# test_bitbucket_connections.py
"""
Functional tests for private Bitbucket OAuth storage.
Version: 0.261.450
Implemented in: 0.261.450

Real Fernet encryption and SDK-shaped conditional Cosmos responses validate
single-use, session-bound state, refresh serialization, and disconnect fencing.
"""

import copy
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from cryptography.fernet import Fernet


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_bitbucket_connections import BitbucketConnections
from functions_bitbucket_operations import BitbucketError
from test_bitbucket_action_plugin import manifest, Response
from test_support.m365 import CosmosContainer


@pytest.fixture
def service():
    record = manifest()
    record["auth"] = {"type": "user", "identity": "client-id", "key": "client-secret"}
    record["additionalFields"]["auth_method"] = "oauth"
    key = Fernet(Fernet.generate_key())
    instance = BitbucketConnections(CosmosContainer("user_id"), lambda user, ref: copy.deepcopy(record),
                                   key_provider=lambda: key, clock=lambda: 1000)
    return instance


def start(service, user="actor", session="browser", ref="personal:actor:review"):
    result = service.start(user, ref, session, "https://simplechat.example.test/api/bitbucket/callback")
    return parse_qs(urlsplit(result["authorization_url"]).query)


def tokens(access="access-private", refresh="refresh-private"):
    return {"access_token": access, "refresh_token": refresh, "expires_in": 3600}


def connect(service):
    query = start(service)
    service.exchange = lambda manifest, data: tokens()
    service.complete("actor", query["state"][0], "code-private", "browser")


def test_oauth_sdk_owner_state_encryption_replay_and_session_binding(service):
    query = start(service)
    assert query["code_challenge_method"] == ["S256"] and "code_verifier" not in query
    state = query["state"][0]
    with pytest.raises(BitbucketError) as error:
        service.complete("actor", state, "code", "wrong-browser")
    assert error.value.code == "state_invalid"
    with pytest.raises(BitbucketError):
        service.complete("other-user", state, "code", "browser")
    calls = []

    def exchange(manifest, data):
        calls.append(data)
        return tokens()

    service.exchange = exchange
    service.complete("actor", state, "code-private", "browser")
    assert len(calls) == 1 and calls[0]["code_verifier"]
    status = service.status("actor", "personal:actor:review")
    saved = service.read("actor", status["connection_id"])
    assert type(saved) is dict and saved["_etag"]
    assert status["connected"]
    serialized = repr(service.container.items)
    assert "access-private" not in serialized and "refresh-private" not in serialized and "code-private" not in serialized
    token = service.token("actor", "personal:actor:review")
    assert token == "access-private"
    with pytest.raises(BitbucketError):
        service.complete("actor", state, "code-private", "browser")
    service.disconnect("actor", "personal:actor:review")
    status = service.status("actor", "personal:actor:review")
    assert not status["connected"]
    with pytest.raises(BitbucketError):
        service.token("actor", "personal:actor:review")


def test_expired_state_changed_policy_and_newer_connect_fence_old_flows(service):
    query = start(service)
    service.clock = lambda: 1601
    with pytest.raises(BitbucketError):
        service.complete("actor", query["state"][0], "code", "browser")
    service.clock = lambda: 1000
    query = start(service)
    newer = start(service)
    with pytest.raises(BitbucketError) as error:
        service.complete("actor", query["state"][0], "code", "browser")
    assert error.value.code == "connection_changed"
    service.exchange = lambda manifest, data: tokens()
    service.complete("actor", newer["state"][0], "code", "browser")
    original = service.authorize

    def changed(user, ref):
        record = original(user, ref)
        record["additionalFields"]["repositories"][0]["default_branch"] = "other"
        return record

    service.authorize = changed
    with pytest.raises(BitbucketError) as error:
        service.token("actor", "personal:actor:review")
    assert error.value.code == "reconnect_required"


def test_refresh_rotates_once_and_disconnect_wins_inflight_response(service):
    connect(service)
    service.clock = lambda: 5000
    calls = []

    def refresh(manifest, data):
        calls.append(data)
        with pytest.raises(BitbucketError) as error:
            service.token("actor", "personal:actor:review")
        assert error.value.code == "refresh_in_progress"
        return tokens("rotated-private", "rotated-refresh")

    service.exchange = refresh
    value = service.token("actor", "personal:actor:review")
    assert value == "rotated-private" and len(calls) == 1
    value = service.token("actor", "personal:actor:review")
    assert value == "rotated-private" and len(calls) == 1
    service.clock = lambda: 9000

    def disconnect(manifest, data):
        service.disconnect("actor", "personal:actor:review")
        return tokens("must-not-resurrect", "new-refresh")

    service.exchange = disconnect
    with pytest.raises(CosmosHttpResponseError):
        service.token("actor", "personal:actor:review")
    status = service.status("actor", "personal:actor:review")
    assert not status["connected"]


def test_failed_uncertain_refresh_is_not_replayed(service):
    connect(service)
    service.clock = lambda: 5000
    calls = []

    def failed(manifest, data):
        calls.append(data)
        raise BitbucketError("connection_failed", "Unavailable", 502)

    service.exchange = failed
    for _ in range(2):
        with pytest.raises(BitbucketError):
            service.token("actor", "personal:actor:review")
    assert len(calls) == 1


def test_disconnect_after_policy_edit_cannot_resurrect_old_connection(service):
    connect(service)
    original = service.authorize

    def changed(user, reference):
        record = original(user, reference)
        record["additionalFields"]["repositories"][0]["default_branch"] = "other"
        return record

    service.authorize = changed
    status = service.status("actor", "personal:actor:review")
    assert not status["connected"]
    service.disconnect("actor", "personal:actor:review")
    service.authorize = original
    with pytest.raises(BitbucketError) as error:
        service.token("actor", "personal:actor:review")
    assert error.value.code == "reconnect_required"


def test_cloud_callback_does_not_send_data_center_pkce_fields(service):
    original = service.authorize

    def cloud(user, reference):
        record = original(user, reference)
        record["endpoint"] = "https://api.bitbucket.org"
        record["additionalFields"]["edition"] = "cloud"
        return record

    service.authorize = cloud
    query = start(service)
    assert "code_challenge" not in query
    calls = []

    def exchange(manifest, data):
        calls.append(data)
        return tokens()

    service.exchange = exchange
    service.complete("actor", query["state"][0], "code-private", "browser")
    assert "code_verifier" not in calls[0]


def test_callback_disconnect_and_cipher_binding_prevent_resurrection(service):
    query = start(service)

    def disconnect(manifest, data):
        service.disconnect("actor", "personal:actor:review")
        return tokens()

    service.exchange = disconnect
    with pytest.raises(CosmosHttpResponseError):
        service.complete("actor", query["state"][0], "code", "browser")
    cipher = service.seal(tokens(), ["actor", "connection"])
    with pytest.raises(BitbucketError):
        service.open(cipher, ["other", "connection"])


@pytest.mark.parametrize("cloud", [False, True])
def test_token_exchange_wire_auth_and_redirects(service, cloud):
    record = service.authorize("actor", "ref")
    if cloud:
        record["endpoint"] = "https://api.bitbucket.org"
        record["additionalFields"]["edition"] = "cloud"
    response = Response({**tokens(), "token_type": "bearer"})
    calls = []

    class Http:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **options):
            calls.append((url, options))
            return response

    service.session_factory = Http
    result = service.exchange(record, {"grant_type": "refresh_token", "refresh_token": "private-refresh"})
    assert result == tokens() and response.closed
    url, options = calls[0]
    assert options["allow_redirects"] is False
    if cloud:
        assert url == "https://bitbucket.org/site/oauth2/access_token"
        assert options["auth"] == ("client-id", "client-secret")
        assert "client_secret" not in options["data"]
    else:
        assert url.endswith("/context/rest/oauth2/latest/token")
        assert options["data"]["client_secret"] == "client-secret"
