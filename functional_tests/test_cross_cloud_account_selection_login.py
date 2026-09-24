# test_cross_cloud_account_selection_login.py
"""
Functional test for cross-cloud account-selection login.
Version: 0.261.030
Implemented in: 0.261.028

This test ensures the normal Entra login remains unchanged, the explicit
account-selection flow requests only prompt=select_account, and users denied
by app-role authorization can choose another account from the landing page.
"""

from pathlib import Path
import sys
from unittest.mock import patch

from flask import Blueprint, Flask, session


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
INDEX_TEMPLATE = APP_DIR / "templates" / "index.html"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


import route_frontend_authentication as route_module  # noqa: E402
from functions_authentication import get_signed_in_account_display  # noqa: E402


class RecordingMsalApp:
    """Record authorization URL arguments without contacting Microsoft Entra."""

    def __init__(self):
        self.authorization_requests = []

    def get_authorization_request_url(self, **kwargs):
        self.authorization_requests.append(kwargs)
        return "https://login.example.test/authorize"


def _build_test_app(recording_msal_app):
    """Create a minimal Flask app around the authentication Blueprint."""
    app = Flask(__name__)
    app.secret_key = "test-secret"

    auth_blueprint = Blueprint("frontend_authentication", __name__)
    route_module.register_route_frontend_authentication(auth_blueprint)
    app.register_blueprint(auth_blueprint)
    return app


def _request_login(query_string=""):
    """Request the login route and return its recorded MSAL arguments and session."""
    recording_msal_app = RecordingMsalApp()
    app = _build_test_app(recording_msal_app)

    with (
        patch.object(route_module, "_build_msal_app", return_value=recording_msal_app),
        patch.object(route_module, "get_settings", return_value={"enable_front_door": False}),
        patch.object(route_module, "get_terms_of_use_config", return_value={"enabled": False}),
        app.test_client() as client,
    ):
        with client.session_transaction() as flask_session:
            flask_session["user"] = {"oid": "existing-user"}
            flask_session["token_cache"] = "existing-cache"
            flask_session["last_activity_epoch"] = 123

        response = client.get(f"/login{query_string}")

        with client.session_transaction() as flask_session:
            remaining_session = dict(flask_session)

    assert response.status_code == 302
    assert response.headers["Location"] == "https://login.example.test/authorize"
    assert len(recording_msal_app.authorization_requests) == 1
    return recording_msal_app.authorization_requests[0], remaining_session


def test_normal_login_does_not_request_an_oauth_prompt():
    """Verify ordinary login preserves the current prompt-free MSAL request."""
    authorization_request, remaining_session = _request_login()

    assert "prompt" not in authorization_request
    assert "user" not in remaining_session
    assert "token_cache" not in remaining_session
    assert "last_activity_epoch" not in remaining_session


def test_account_selection_login_requests_select_account_prompt():
    """Verify the controlled query flag requests the Entra account picker."""
    authorization_request, _ = _request_login("?select_account=1")

    assert authorization_request.get("prompt") == "select_account"


def test_invalid_values_cannot_inject_an_oauth_prompt():
    """Verify arbitrary prompt and loose boolean values are ignored."""
    invalid_queries = (
        "?select_account=true",
        "?select_account=consent",
        "?select_account=0&prompt=consent",
        "?prompt=login",
    )

    for query_string in invalid_queries:
        authorization_request, _ = _request_login(query_string)
        assert "prompt" not in authorization_request, query_string


def test_access_denied_page_links_to_account_selection_login():
    """Verify signed-in users without an app role can choose another account."""
    template_source = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert "Sign in with another account" in template_source
    assert "url_for('frontend_authentication.login', select_account=1)" in template_source


def test_unauthenticated_sign_in_link_remains_ordinary_login():
    """Verify the normal unauthenticated sign-in link does not force selection."""
    template_source = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert (
        "Please <a href=\"{{ url_for('frontend_authentication.login') }}\">sign in</a> to continue."
        in template_source
    )


def test_access_denied_account_display_uses_safe_identity_claims():
    """Verify account labels prefer real email claims and suppress #EXT# UPNs."""
    native_gov_account = get_signed_in_account_display({
        "name": "Gov Administrator",
        "preferred_username": "admin@govtenant.onmicrosoft.us",
    })
    cross_cloud_account = get_signed_in_account_display({
        "name": "Commercial User",
        "mail": "user@commercial.example",
        "preferred_username": "user_domain#EXT#@govtenant.onmicrosoft.com",
    })
    guest_upn_only = get_signed_in_account_display({
        "name": "External User",
        "preferred_username": "user_domain#EXT#@govtenant.onmicrosoft.com",
    })

    assert native_gov_account == {
        "name": "Gov Administrator",
        "account": "admin@govtenant.onmicrosoft.us",
    }
    assert cross_cloud_account == {
        "name": "Commercial User",
        "account": "user@commercial.example",
    }
    assert guest_upn_only == {"name": "External User", "account": ""}


if __name__ == "__main__":
    tests = [
        test_normal_login_does_not_request_an_oauth_prompt,
        test_account_selection_login_requests_select_account_prompt,
        test_invalid_values_cannot_inject_an_oauth_prompt,
        test_access_denied_page_links_to_account_selection_login,
        test_unauthenticated_sign_in_link_remains_ordinary_login,
        test_access_denied_account_display_uses_safe_identity_claims,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except AssertionError as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(tests)} tests passed")
    raise SystemExit(0 if success else 1)