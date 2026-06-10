# test_msgraph_access_test_route.py
#!/usr/bin/env python3
"""
Functional test for Microsoft Graph access testing route.
Version: 0.241.179
Implemented in: 0.241.179

This test ensures the user-scoped Microsoft Graph access test endpoint verifies
granted scopes after consent, returns actionable consent metadata when access is
still missing, and rejects unsupported scopes.
"""

from pathlib import Path
import sys
import types

from flask import Flask
import werkzeug


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if "olefile" not in sys.modules:
    sys.modules["olefile"] = types.ModuleType("olefile")

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3"


import route_backend_msgraph_pending_actions as route_module  # noqa: E402


def identity_decorator(function):
    return function


def swagger_identity_decorator(*args, **kwargs):
    del args, kwargs
    return identity_decorator


def test_msgraph_access_test_route():
    """Verify Graph access testing success, consent, and validation responses."""
    print("Testing Microsoft Graph access test route...")

    original_token_helper = route_module.get_valid_access_token_for_plugins
    original_login_required = route_module.login_required
    original_user_required = route_module.user_required
    original_swagger_route = route_module.swagger_route
    original_get_auth_security = route_module.get_auth_security

    token_calls = []

    def fake_token_helper(scopes=None):
        token_calls.append(scopes)
        if scopes == ["Mail.Send"]:
            return {"access_token": "fake-token"}
        return {
            "error": "consent_required",
            "message": "User consent is required to access Microsoft 365 resources like Outlook email, Calendar, OneDrive, or SharePoint.",
            "consent_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=test",
            "scopes": scopes,
        }

    try:
        route_module.get_valid_access_token_for_plugins = fake_token_helper
        route_module.login_required = identity_decorator
        route_module.user_required = identity_decorator
        route_module.swagger_route = swagger_identity_decorator
        route_module.get_auth_security = lambda: []

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.secret_key = "test-secret"
        route_module.register_route_backend_msgraph_pending_actions(app)
        client = app.test_client()

        success_response = client.post("/api/msgraph/test-access", json={"scopes": ["Mail.Send"]})
        if success_response.status_code != 200:
            print(
                f"Expected success response, got {success_response.status_code}: "
                f"{success_response.get_json()}"
            )
            return False
        success_payload = success_response.get_json() or {}
        if success_payload.get("access_granted") is not True or success_payload.get("scopes") != ["Mail.Send"]:
            print(f"Expected access_granted payload, got: {success_payload}")
            return False

        consent_response = client.post("/api/msgraph/test-access", json={"scopes": ["Calendars.ReadWrite"]})
        if consent_response.status_code != 401:
            print(
                f"Expected consent response status 401, got {consent_response.status_code}: "
                f"{consent_response.get_json()}"
            )
            return False
        consent_payload = consent_response.get_json() or {}
        if consent_payload.get("error") != "consent_required" or not consent_payload.get("consent_url"):
            print(f"Expected consent metadata, got: {consent_payload}")
            return False
        if "Microsoft 365" not in consent_payload.get("message", ""):
            print(f"Expected user-friendly Microsoft 365 consent message, got: {consent_payload}")
            return False

        invalid_response = client.post("/api/msgraph/test-access", json={"scopes": ["Directory.Read.All"]})
        invalid_payload = invalid_response.get_json() or {}
        if invalid_response.status_code != 400 or invalid_payload.get("error") != "invalid_scopes":
            print(
                f"Expected invalid scope rejection, got {invalid_response.status_code}: "
                f"{invalid_response.get_json()}"
            )
            return False

        empty_response = client.post("/api/msgraph/test-access", json={"scopes": []})
        empty_payload = empty_response.get_json() or {}
        if empty_response.status_code != 400 or empty_payload.get("error") != "invalid_parameters":
            print(
                f"Expected empty scope rejection, got {empty_response.status_code}: "
                f"{empty_response.get_json()}"
            )
            return False

        if token_calls != [["Mail.Send"], ["Calendars.ReadWrite"]]:
            print(f"Expected token helper only for valid scopes, got: {token_calls}")
            return False

        print("Microsoft Graph access test route validates access and consent safely")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        route_module.get_valid_access_token_for_plugins = original_token_helper
        route_module.login_required = original_login_required
        route_module.user_required = original_user_required
        route_module.swagger_route = original_swagger_route
        route_module.get_auth_security = original_get_auth_security


if __name__ == "__main__":
    success = test_msgraph_access_test_route()
    sys.exit(0 if success else 1)