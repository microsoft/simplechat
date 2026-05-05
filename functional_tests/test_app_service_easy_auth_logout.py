# test_app_service_easy_auth_logout.py
"""
Functional test for Azure App Service Easy Auth logout recovery.
Version: 0.241.095
Implemented in: 0.241.095

This test ensures Azure-hosted logout routes clear the upstream App Service
authentication session by redirecting through /.auth/logout before re-entering
the Flask login flow.
"""

from pathlib import Path
import os
import sys
from unittest.mock import patch

from flask import Flask, session


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


import route_frontend_authentication as route_module  # noqa: E402


EXPECTED_EASY_AUTH_LOGOUT = "/.auth/logout?post_logout_redirect_uri=%2Flogin"


def _build_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/")
    def index():
        return "ok"

    route_module.register_route_frontend_authentication(app)
    return app


def test_local_logout_uses_app_service_easy_auth_logout():
    """Verify local logout clears the Easy Auth session when App Service auth is active."""
    print("Testing App Service Easy Auth local logout redirect...")

    app = _build_test_app()

    with patch.dict(
        os.environ,
        {
            "WEBSITE_HOSTNAME": "example.azurewebsites.net",
            "WEBSITE_AUTH_AAD_ALLOWED_TENANTS": "tenant-id",
        },
        clear=False,
    ):
        with app.test_request_context(
            "/logout/local",
            base_url="https://example.azurewebsites.net",
            headers={"X-MS-CLIENT-PRINCIPAL-ID": "user-oid"},
        ):
            session["user"] = {"name": "Test User"}

            response = app.view_functions["local_logout"]()

            assert response.status_code == 302, f"Expected redirect response, got {response.status_code}"
            assert response.headers.get("Location") == EXPECTED_EASY_AUTH_LOGOUT, (
                f"Unexpected local logout redirect: {response.headers.get('Location')}"
            )
            assert "user" not in session, f"Expected Flask session to be cleared, got {dict(session)}"

    print("App Service Easy Auth local logout redirects through /.auth/logout")


def test_full_logout_uses_app_service_easy_auth_logout():
    """Verify full logout clears the Easy Auth session when App Service auth is active."""
    print("Testing App Service Easy Auth full logout redirect...")

    app = _build_test_app()

    with patch.dict(
        os.environ,
        {
            "WEBSITE_HOSTNAME": "example.azurewebsites.net",
            "WEBSITE_AUTH_AAD_ALLOWED_TENANTS": "tenant-id",
        },
        clear=False,
    ):
        with app.test_request_context(
            "/logout",
            base_url="https://example.azurewebsites.net",
            headers={"X-MS-CLIENT-PRINCIPAL-ID": "user-oid"},
        ):
            session["user"] = {
                "name": "Test User",
                "preferred_username": "user@example.com",
            }

            response = app.view_functions["logout"]()

            assert response.status_code == 302, f"Expected redirect response, got {response.status_code}"
            assert response.headers.get("Location") == EXPECTED_EASY_AUTH_LOGOUT, (
                f"Unexpected full logout redirect: {response.headers.get('Location')}"
            )
            assert not session, f"Expected Flask session to be cleared, got {dict(session)}"

    print("App Service Easy Auth full logout redirects through /.auth/logout")


if __name__ == "__main__":
    tests = [
        test_local_logout_uses_app_service_easy_auth_logout,
        test_full_logout_uses_app_service_easy_auth_logout,
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
    sys.exit(0 if success else 1)
