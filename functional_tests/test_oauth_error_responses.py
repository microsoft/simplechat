# test_oauth_error_responses.py
"""
Functional HTTP regressions for the registered OAuth callback error responses.
Version: 0.261.423
Implemented in: 0.261.423

Real Flask callback registration exercises hostile provider parameters, unchanged
missing-code behavior, sign-in, and Microsoft 365 prefix dispatch. Existing M365
fixtures supply real MSAL state/nonce checks, AES-GCM, and SDK-default Cosmos
responses without Azure or Graph calls. Startup I/O and login token exchange are
scoped seams; this is not live browser or full application-bootstrap validation.
"""

import copy
import importlib.util
import logging
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit
from unittest.mock import Mock, patch

import msal
import pytest
from flask import Blueprint, Flask, jsonify, redirect, render_template, request, session, url_for

import test_m365_connections as connection_fixtures
import test_m365_routes as route_fixtures


APP_DIR = route_fixtures.APP_DIR
LOGIN_FAILURE_MESSAGE = "Login failed. Please try signing in again."
USER = {"oid": "user-a", "tid": "tenant-a", "roles": ["User"], "name": "Test User"}
HOSTILE_DESCRIPTION = '<img src=x onerror="window.oauthErrorExecuted=true"><script>alert("provider")</script>'
SESSION_VALUES = {
    "user": USER,
    "token_cache": "existing-login-cache",
    "requested_oauth_scopes": ["User.Read"],
    "m365_chat_token_cache": "existing-chat-cache",
    "m365_workflow_oauth_binding": "existing-workflow-binding",
}


def _load_routes(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _set_session(client, values):
    with client.session_transaction() as saved:
        saved.clear()
        saved.update(copy.deepcopy(values))


def _read_session(client):
    with client.session_transaction() as saved:
        return copy.deepcopy(dict(saved))


@pytest.fixture
def callbacks():
    """Register both real route modules with the existing scoped M365 seams."""
    app = Flask(
        __name__, template_folder=str(APP_DIR / "templates"),
        static_folder=str(APP_DIR / "static"),
    )
    app.config.update(TESTING=True, SECRET_KEY="oauth-test-only")
    logger = Mock()
    cache = msal.SerializableTokenCache()
    token_client = Mock(token_cache=cache)
    builder = Mock(return_value=token_client)
    load_cache = Mock(return_value=cache)
    save_cache = Mock()
    scopes = Mock(return_value=["User.Read"])
    settings = Mock(return_value={})
    login_activity = Mock()
    dependencies = {
        "config": route_fixtures.module_stub(
            "config", request=request, session=session, jsonify=jsonify,
            redirect=redirect, render_template=render_template, url_for=url_for,
            time=time, quote=quote, LOGIN_REDIRECT_URL=None, HOME_REDIRECT_URL=None,
            DISABLE_APP_SERVICE_EASY_AUTH_LOGOUT=False, ENABLE_TEAMS_SSO=False,
            CLIENT_ID="client-a", TENANT_ID="tenant-a", SCOPE=["User.Read"],
        ),
        "functions_appinsights": route_fixtures.module_stub("functions_appinsights", log_event=logger),
        "functions_authentication": route_fixtures.module_stub(
            "functions_authentication", _build_msal_app=builder,
            _load_cache=load_cache, _save_cache=save_cache,
            clear_requested_oauth_scopes=Mock(), get_requested_oauth_scopes=scopes,
            create_ci_bearer_session=Mock(),
            get_graph_authority=lambda: "https://login.microsoftonline.com/tenant-a",
            get_graph_endpoint=lambda path: f"https://graph.microsoft.com{path}",
            login_required=route_fixtures.login_guard, user_required=route_fixtures.user_guard,
            user_required_blueprint=route_fixtures.blueprint_guard,
        ),
        "functions_activity_logging": route_fixtures.module_stub(
            "functions_activity_logging", log_user_login=login_activity,
            record_user_login_session_activity=Mock(),
        ),
        "functions_terms_of_use": route_fixtures.module_stub(
            "functions_terms_of_use", apply_pending_pre_auth_terms_of_use=Mock(),
            get_terms_of_use_config=lambda value: {"enabled": False},
            has_terms_of_use_acceptance=lambda value: True,
        ),
        "functions_debug": route_fixtures.module_stub("functions_debug", debug_print=Mock()),
        "functions_settings": route_fixtures.module_stub(
            "functions_settings", get_settings=settings,
            sanitize_settings_for_user=lambda value: dict(value),
        ),
        "swagger_wrapper": route_fixtures.module_stub(
            "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function,
            get_auth_security=lambda: [],
        ),
        "functions_m365_request_resume": route_fixtures.module_stub(
            "functions_m365_request_resume",
            get_m365_chat_request=Mock(side_effect=AssertionError("Profile sign-in must not resume a request.")),
        ),
        "functions_m365_runtime": route_fixtures.module_stub(
            "functions_m365_runtime",
            _conversation_access=Mock(side_effect=AssertionError("Profile sign-in must not resume a conversation.")),
        ),
    }
    with patch.dict(sys.modules, dependencies):
        frontend = _load_routes("oauth_test_frontend", "route_frontend_authentication.py")
        backend = _load_routes("oauth_test_m365_backend", "route_backend_m365.py")
        sys.modules["route_backend_m365"] = backend
        blueprint = Blueprint("frontend_authentication", __name__)
        frontend.register_route_frontend_authentication(blueprint)
        app.register_blueprint(blueprint)
        public = Blueprint("public_app", __name__)
        public.add_url_rule("/", endpoint="index", view_func=lambda: "Sign in")
        app.register_blueprint(public)
        client = app.test_client()
        _set_session(client, SESSION_VALUES)
        yield SimpleNamespace(
            app=app, client=client, frontend=frontend, backend=backend,
            logger=logger, builder=builder, load_cache=load_cache, save_cache=save_cache,
            scopes=scopes, settings=settings, token_client=token_client,
            cache=cache, login_activity=login_activity,
        )


@pytest.mark.parametrize("callback", ["/getAToken", "/getATokenApi"])
@pytest.mark.parametrize(
    "query, diagnostic",
    [
        ({"error": "access_denied", "error_description": HOSTILE_DESCRIPTION}, "access_denied"),
        ({"error": HOSTILE_DESCRIPTION, "error_description": '"><svg onload=alert(1)>'}, "unrecognized_error"),
        ({"error": "access_denied"}, "access_denied"),
        ({"error": "server_error", "error_description": 'secret=do-not-return\r\n"provider detail"'}, "server_error"),
        ({
            "error": 'secret=do-not-log-"<provider>',
            "error_description": HOSTILE_DESCRIPTION, "code": "must-not-exchange", "state": "ordinary-login",
        }, "unrecognized_error"),
    ],
)
def test_provider_error_is_a_fixed_plain_text_400(callbacks, capsys, callback, query, diagnostic):
    """Provider markup, quotes, descriptions, and secrets never reach HTML or logs."""
    before = _read_session(callbacks.client)
    response = callbacks.client.get(callback, query_string=query, headers={"Accept": "text/html"})
    body = response.get_data(as_text=True)
    after = _read_session(callbacks.client)
    output = capsys.readouterr()

    assert response.status_code == 400
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert body == LOGIN_FAILURE_MESSAGE
    assert after == before
    callbacks.builder.assert_not_called()
    callbacks.load_cache.assert_not_called()
    callbacks.save_cache.assert_not_called()
    callbacks.scopes.assert_not_called()
    callbacks.settings.assert_not_called()
    callbacks.logger.assert_called_once_with(
        "[AUTH_CALLBACK] OAuth sign-in was not completed.",
        extra={
            "path": callback, "oauth_error": diagnostic,
            "error_description_present": bool(query.get("error_description")),
        },
        level=logging.WARNING,
    )
    assert not output.out
    assert not output.err


@pytest.mark.parametrize("callback", ["/getAToken", "/getATokenApi"])
@pytest.mark.parametrize("query", [{}, {"error": ""}, {"error_description": HOSTILE_DESCRIPTION}])
def test_missing_code_behavior_is_unchanged_at_http_boundary(callbacks, callback, query):
    """A missing/empty error is not a provider failure or a token exchange."""
    before = _read_session(callbacks.client)
    response = callbacks.client.get(callback, query_string=query)
    after = _read_session(callbacks.client)
    body = response.get_data(as_text=True)

    if callback == "/getAToken":
        assert response.status_code == 302
        assert response.headers["Location"] == "/"
    else:
        assert response.status_code == 400
        assert body == "Authorization code not found"
    assert HOSTILE_DESCRIPTION not in body
    assert after == before
    callbacks.builder.assert_not_called()
    callbacks.load_cache.assert_not_called()
    callbacks.save_cache.assert_not_called()


@pytest.mark.parametrize("callback", ["/getAToken", "/getATokenApi"])
def test_successful_login_and_api_callback_contracts_are_unchanged(callbacks, callback):
    """The app login still saves identity/cache; the API flow remains separate."""
    claims = {**USER, "name": "Signed-in User"}
    result = {"id_token_claims": claims, "access_token": "test-only-api-token"}
    callbacks.token_client.acquire_token_by_authorization_code.return_value = result
    response = callbacks.client.get(callback, query_string={"code": "test-only-code"})
    saved = _read_session(callbacks.client)

    callbacks.builder.assert_called_once_with(
        cache=callbacks.cache, authority_override="https://login.microsoftonline.com/tenant-a",
    )
    callbacks.scopes.assert_called_once_with(clear_after_read=True)
    callbacks.token_client.acquire_token_by_authorization_code.assert_called_once_with(
        code="test-only-code", scopes=["User.Read"], redirect_uri="https://localhost/getAToken",
    )
    if callback == "/getAToken":
        assert response.status_code == 302
        assert response.headers["Location"] == "/"
        assert saved["user"] == claims
        assert isinstance(saved["last_activity_epoch"], int)
        callbacks.save_cache.assert_called_once_with(callbacks.cache)
        callbacks.login_activity.assert_called_once_with("user-a", "azure_ad")
    else:
        assert response.status_code == 200
        assert response.get_json() == [result, 200]
        assert saved["user"] == USER
        callbacks.save_cache.assert_not_called()
        callbacks.login_activity.assert_not_called()
    assert saved["m365_chat_token_cache"] == SESSION_VALUES["m365_chat_token_cache"]
    assert saved["m365_workflow_oauth_binding"] == SESSION_VALUES["m365_workflow_oauth_binding"]


@pytest.fixture
def m365_case(callbacks):
    """Reuse test_support.m365-backed real MSAL/encryption/account fixtures."""
    case = connection_fixtures.M365ConnectionTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def _begin_m365(callbacks, case, kind, completion="page"):
    connections = connection_fixtures.connections
    with callbacks.app.test_request_context():
        session.update(copy.deepcopy(SESSION_VALUES))
        if kind == "chat":
            started = case.service.start_profile_chat_connection(
                "user-a", "tenant-a", ["email"], "https://localhost/getAToken", completion=completion,
            )
        else:
            started = case.service.start_connection(
                "user-a", "tenant-a", ["email"], "https://localhost/getAToken",
                SESSION_VALUES["m365_workflow_oauth_binding"], completion=completion,
            )
        values = copy.deepcopy(dict(session))
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    case.http.nonce = query["nonce"][0]
    state = query["state"][0]
    prefix = connections.CHAT_AUTH_STATE_PREFIX if kind == "chat" else connections.WORKFLOW_AUTH_STATE_PREFIX
    assert state.startswith(prefix)
    _set_session(callbacks.client, values)
    return state


@pytest.mark.parametrize("kind", ["chat", "workflow"])
def test_m365_provider_errors_keep_their_separate_completion_flow(callbacks, m365_case, kind):
    """Prefix dispatch precedes the generic error response and preserves identity."""
    state = _begin_m365(callbacks, m365_case, kind)
    response = callbacks.client.get("/getAToken", query_string={
        "state": state, "error": "access_denied", "error_description": HOSTILE_DESCRIPTION,
    })
    saved = _read_session(callbacks.client)
    body = response.get_data(as_text=True)

    assert response.status_code == 400
    assert response.mimetype == "text/html"
    assert '"code": "m365_consent_required"' in body
    assert HOSTILE_DESCRIPTION not in body
    assert LOGIN_FAILURE_MESSAGE not in body
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert saved["user"] == USER
    assert saved["token_cache"] == SESSION_VALUES["token_cache"]
    assert saved["m365_chat_token_cache"] == SESSION_VALUES["m365_chat_token_cache"]
    assert m365_case.http.posts == []
    callbacks.builder.assert_not_called()
    callbacks.save_cache.assert_not_called()
    callbacks.logger.assert_not_called()


@pytest.mark.parametrize("kind", ["chat", "workflow"])
@pytest.mark.parametrize(
    "guard, status, code",
    [
        ("state", 400, "m365_auth_state_invalid"),
        ("session", 400, "m365_auth_state_invalid"),
        ("account", 403, "m365_account_mismatch"),
        ("nonce", 400, "m365_auth_validation_failed"),
    ],
)
def test_m365_callback_guards_still_run_through_getatoken(callbacks, m365_case, kind, guard, status, code):
    """Invalid state/session/account/nonce cannot publish another credential."""
    state = _begin_m365(callbacks, m365_case, kind)
    if guard == "state":
        state += "different"
    elif guard == "session":
        with callbacks.client.session_transaction() as saved:
            if kind == "chat":
                saved.pop(connection_fixtures.connections.CHAT_AUTH_SESSION_KEY)
            else:
                saved["m365_workflow_oauth_binding"] = "another-session-binding"
    elif guard == "account":
        m365_case.http.claim_overrides = {"oid": "another-user"}
    else:
        m365_case.http.claim_overrides = {"nonce": "wrong-nonce"}
    response = callbacks.client.get("/getAToken", query_string={"state": state, "code": "test-only-code"})
    saved = _read_session(callbacks.client)
    body = response.get_data(as_text=True)

    assert response.status_code == status
    assert f'"code": "{code}"' in body
    assert saved["user"] == USER
    assert saved["token_cache"] == SESSION_VALUES["token_cache"]
    assert saved["m365_chat_token_cache"] == SESSION_VALUES["m365_chat_token_cache"]
    assert all(not row.get("encrypted_cache") for row in m365_case.container.items.values())
    if guard in {"state", "session"}:
        assert m365_case.http.posts == []
    callbacks.builder.assert_not_called()
    callbacks.save_cache.assert_not_called()


@pytest.mark.parametrize("kind", ["chat", "workflow"])
@pytest.mark.parametrize("completion", ["page", "popup"])
def test_successful_m365_callbacks_preserve_principal_and_distinct_caches(callbacks, m365_case, kind, completion):
    """Actual prefixed callbacks finish real MSAL flows, not the app login flow."""
    state = _begin_m365(callbacks, m365_case, kind, completion)
    response = callbacks.client.get("/getAToken", query_string={"state": state, "code": "test-only-code"})
    saved = _read_session(callbacks.client)
    body = response.get_data(as_text=True)

    assert response.status_code == (302 if completion == "page" else 200)
    if completion == "page":
        expected = (
            callbacks.backend.CLASSIC_CHAT_CONNECTED_URL if kind == "chat"
            else callbacks.backend.CLASSIC_WORKFLOW_CONNECTED_URL
        )
        assert response.headers["Location"] == expected
    else:
        message_type = "m365-profile-reconnected" if kind == "chat" else "m365-workflow-connected"
        assert f'"type": "{message_type}"' in body
    assert response.headers["Cache-Control"] == "private, no-store"
    assert saved["user"] == USER
    assert saved["token_cache"] == SESSION_VALUES["token_cache"]
    assert "access-token-must-stay-server-side" not in body
    assert "refresh-token-must-stay-server-side" not in body
    if kind == "chat":
        assert "refresh-token-must-stay-server-side" in saved["m365_chat_token_cache"]
        assert not m365_case.container.items
    else:
        assert saved["m365_chat_token_cache"] == SESSION_VALUES["m365_chat_token_cache"]
        assert any(row.get("encrypted_cache") for row in m365_case.container.items.values())
    callbacks.builder.assert_not_called()
    callbacks.save_cache.assert_not_called()
    callbacks.login_activity.assert_not_called()


def test_teams_token_exchange_remains_a_separate_session_flow(callbacks, monkeypatch):
    """The Teams endpoint still uses OBO and its own session identity contract."""
    monkeypatch.setattr(callbacks.frontend, "ENABLE_TEAMS_SSO", True)
    graph = Mock(return_value={})
    monkeypatch.setattr(callbacks.frontend, "_fetch_graph_me", graph)
    claims = {**USER, "preferred_username": "user-a@example.test"}
    callbacks.token_client.acquire_token_on_behalf_of.return_value = {
        "id_token_claims": claims, "access_token": "test-only-teams-token",
    }
    response = callbacks.client.post("/auth/teams/token-exchange", json={"token": "test-only-teams-assertion"})
    saved = _read_session(callbacks.client)

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True, "user": {"name": "Test User", "email": "user-a@example.test", "id": "user-a"},
    }
    assert saved["user"]["oid"] == "user-a"
    assert saved["user"]["tid"] == "tenant-a"
    callbacks.token_client.acquire_token_on_behalf_of.assert_called_once_with(
        user_assertion="test-only-teams-assertion", scopes=["User.Read"],
    )
    graph.assert_called_once_with("test-only-teams-token")
    callbacks.save_cache.assert_called_once_with(callbacks.cache)
    callbacks.login_activity.assert_called_once_with("user-a", "teams_sso")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "test_support.cosmos_network_guard"]))
