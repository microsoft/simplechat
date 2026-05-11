# test_msgraph_auth_consent_flow.py
"""
Functional test for Microsoft Graph incremental auth flow.
Version: 0.239.175
Implemented in: 0.239.175

This test ensures plugin-requested Microsoft Graph scopes survive the OAuth
callback and that interactive reauthentication does not force consent unless
Microsoft Entra explicitly reports missing consent.
"""

from pathlib import Path
import sys

from flask import Flask, session


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


import functions_authentication as auth_module  # noqa: E402
import functions_settings  # noqa: E402
import route_frontend_authentication as route_module  # noqa: E402


class FakeTokenCache:
    """Minimal MSAL token cache stub for callback tests."""

    has_state_changed = False


class FakeMsalApp:
    """Simple MSAL stub that records interactive and callback requests."""

    def __init__(self, silent_result=None, auth_code_result=None):
        self.silent_result = silent_result
        self.auth_code_result = auth_code_result or {
            "id_token_claims": {
                "name": "Test User",
                "oid": "oid",
                "sub": "sub",
            },
            "access_token": "fake-token",
        }
        self.authorization_requests = []
        self.auth_code_requests = []
        self.token_cache = FakeTokenCache()

    def get_accounts(self, username=None):
        return [{"home_account_id": "oid.tid", "username": username}]

    def acquire_token_silent_with_error(self, scopes, account=None):
        self.last_silent_request = {
            "scopes": list(scopes),
            "account": account,
        }
        return self.silent_result

    def get_authorization_request_url(self, scopes, **kwargs):
        self.authorization_requests.append(
            {
                "scopes": list(scopes),
                **kwargs,
            }
        )
        prompt_value = kwargs.get("prompt", "none")
        return f"https://login.example.test/authorize?prompt={prompt_value}&scopes={','.join(scopes)}"

    def acquire_token_by_authorization_code(self, code=None, scopes=None, redirect_uri=None):
        self.auth_code_requests.append(
            {
                "code": code,
                "scopes": list(scopes or []),
                "redirect_uri": redirect_uri,
            }
        )
        return self.auth_code_result


def test_plugin_auth_uses_interactive_sign_in_without_forced_consent() -> bool:
    """Verify a silent token miss stores scopes and does not force prompt=consent."""
    print("Testing Microsoft Graph interactive auth without forced consent...")

    app = Flask(__name__)
    app.secret_key = "test-secret"
    fake_msal_app = FakeMsalApp(silent_result=None)
    original_builder = auth_module._build_msal_app

    try:
        auth_module._build_msal_app = lambda cache=None, authority_override=None: fake_msal_app

        with app.test_request_context("/", base_url="https://example.test"):
            session["user"] = {
                "oid": "oid",
                "tid": "tid",
                "preferred_username": "user@example.com",
            }

            result = auth_module.get_valid_access_token_for_plugins(["MailboxSettings.Read"])

            if result.get("error") != "interactive_auth_required":
                print(f"Expected interactive_auth_required, got: {result}")
                return False
            if auth_module.get_requested_oauth_scopes() != ["MailboxSettings.Read"]:
                print(f"Expected stored requested scopes, got: {auth_module.get_requested_oauth_scopes()}")
                return False
            if not fake_msal_app.authorization_requests:
                print("Expected an interactive auth URL request to be generated")
                return False
            if fake_msal_app.authorization_requests[0].get("prompt") is not None:
                print(f"Expected no forced prompt for silent token miss, got: {fake_msal_app.authorization_requests[0]}")
                return False

        print("Microsoft Graph interactive auth avoids forced consent when reauth is enough")
        return True
    finally:
        auth_module._build_msal_app = original_builder


def test_plugin_auth_only_forces_consent_when_entra_requires_it() -> bool:
    """Verify explicit consent errors still request prompt=consent."""
    print("Testing Microsoft Graph explicit consent handling...")

    app = Flask(__name__)
    app.secret_key = "test-secret"
    fake_msal_app = FakeMsalApp(
        silent_result={
            "error": "invalid_grant",
            "error_description": "AADSTS65001: consent_required",
        }
    )
    original_builder = auth_module._build_msal_app

    try:
        auth_module._build_msal_app = lambda cache=None, authority_override=None: fake_msal_app

        with app.test_request_context("/", base_url="https://example.test"):
            session["user"] = {
                "oid": "oid",
                "tid": "tid",
                "preferred_username": "user@example.com",
            }

            result = auth_module.get_valid_access_token_for_plugins(["Calendars.Read"])

            if result.get("error") != "consent_required":
                print(f"Expected consent_required, got: {result}")
                return False
            if fake_msal_app.authorization_requests[0].get("prompt") != "consent":
                print(f"Expected prompt=consent for explicit consent errors, got: {fake_msal_app.authorization_requests[0]}")
                return False

        print("Microsoft Graph consent flow still forces consent when Entra requires it")
        return True
    finally:
        auth_module._build_msal_app = original_builder


def test_oauth_callback_redeems_requested_plugin_scopes() -> bool:
    """Verify the OAuth callback uses the stored plugin scopes instead of base login scopes."""
    print("Testing OAuth callback scope redemption for plugin auth...")

    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/")
    def index():
        return "ok"

    route_module.register_route_frontend_authentication(app)

    fake_msal_app = FakeMsalApp()
    original_builder = route_module._build_msal_app
    original_load_cache = route_module._load_cache
    original_save_cache = route_module._save_cache
    original_get_settings = functions_settings.get_settings

    try:
        route_module._build_msal_app = lambda cache=None: fake_msal_app
        route_module._load_cache = lambda: None
        route_module._save_cache = lambda cache: None
        functions_settings.get_settings = lambda: {"enable_front_door": False}

        with app.test_request_context("/getAToken?code=fake-code", base_url="https://example.test"):
            session[auth_module.REQUESTED_SCOPES_SESSION_KEY] = ["MailboxSettings.Read"]

            response = app.view_functions["authorized"]()

            if response.status_code != 302:
                print(f"Expected callback redirect, got status {response.status_code}")
                return False
            if not fake_msal_app.auth_code_requests:
                print("Expected acquire_token_by_authorization_code to be called")
                return False
            if fake_msal_app.auth_code_requests[0].get("scopes") != ["MailboxSettings.Read"]:
                print(f"Expected callback to redeem requested plugin scopes, got: {fake_msal_app.auth_code_requests[0]}")
                return False
            if auth_module.REQUESTED_SCOPES_SESSION_KEY in session:
                print(f"Expected requested scope state to be cleared, got: {dict(session)}")
                return False

        print("OAuth callback redeems the requested plugin scopes and clears session state")
        return True
    finally:
        route_module._build_msal_app = original_builder
        route_module._load_cache = original_load_cache
        route_module._save_cache = original_save_cache
        functions_settings.get_settings = original_get_settings


if __name__ == "__main__":
    tests = [
        test_plugin_auth_uses_interactive_sign_in_without_forced_consent,
        test_plugin_auth_only_forces_consent_when_entra_requires_it,
        test_oauth_callback_redeems_requested_plugin_scopes,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(tests)} tests passed")
    sys.exit(0 if success else 1)