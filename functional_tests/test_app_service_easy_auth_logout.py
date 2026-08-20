# test_app_service_easy_auth_logout.py
"""
Functional test for Azure App Service Easy Auth logout recovery.
Version: 0.250.225
Implemented in: 0.241.095

This test ensures Azure-hosted logout routes clear the upstream App Service
authentication session by redirecting through /.auth/logout before re-entering
the Flask login flow, while development-mode deployments avoid a missing
/.auth/logout platform endpoint.
"""

from pathlib import Path
import importlib
import os
import sys
import types
from unittest.mock import patch, Mock

from flask import Blueprint, Flask, session


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class FakeConfigCosmosContainer:
    """Minimal Cosmos container stand-in for config.py import-time setup."""

    def read(self):
        return {}


class FakeConfigCosmosDatabase:
    """Minimal Cosmos database stand-in for importing config.py without live I/O."""

    def __init__(self):
        self.containers = {}

    def create_container_if_not_exists(self, id, **kwargs):
        if id not in self.containers:
            self.containers[id] = FakeConfigCosmosContainer()
        return self.containers[id]

    def get_container_client(self, id):
        return self.containers.setdefault(id, FakeConfigCosmosContainer())


class FakeConfigCosmosClient:
    """Minimal Cosmos client stand-in for config.py import-time container setup."""

    def __init__(self, *args, **kwargs):
        self.database = FakeConfigCosmosDatabase()

    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database


def import_module_without_live_cosmos(module_name):
    """Import app modules without letting config.py connect to live Cosmos."""
    if module_name in sys.modules:
        return sys.modules[module_name]

    import azure.cosmos as azure_cosmos

    original_cosmos_client = azure_cosmos.CosmosClient
    azure_cosmos.CosmosClient = FakeConfigCosmosClient
    stub_modules = _install_route_dependency_stubs()
    try:
        return importlib.import_module(module_name)
    finally:
        azure_cosmos.CosmosClient = original_cosmos_client
        for stub_name in stub_modules:
            sys.modules.pop(stub_name, None)


def _install_route_dependency_stubs():
    """Install lightweight stubs for dependencies unrelated to logout routing."""
    stub_modules = {}

    functions_activity_logging = types.ModuleType("functions_activity_logging")
    functions_activity_logging.log_user_login = Mock()
    functions_activity_logging.record_user_login_session_activity = Mock()
    stub_modules["functions_activity_logging"] = functions_activity_logging

    functions_terms_of_use = types.ModuleType("functions_terms_of_use")
    functions_terms_of_use.apply_pending_pre_auth_terms_of_use = Mock()
    functions_terms_of_use.get_terms_of_use_config = Mock(return_value={"enabled": False})
    functions_terms_of_use.has_terms_of_use_acceptance = Mock(return_value=True)
    stub_modules["functions_terms_of_use"] = functions_terms_of_use

    functions_authentication = types.ModuleType("functions_authentication")
    functions_authentication._build_msal_app = Mock()
    functions_authentication._load_cache = Mock(return_value=None)
    functions_authentication._save_cache = Mock()
    functions_authentication.clear_requested_oauth_scopes = Mock()
    functions_authentication.create_ci_bearer_session = Mock(return_value=("", 204))
    functions_authentication.get_graph_authority = Mock(return_value="https://graph.microsoft.com")
    functions_authentication.get_graph_endpoint = Mock(side_effect=lambda path: f"https://graph.microsoft.com/v1.0{path}")
    functions_authentication.get_requested_oauth_scopes = Mock(return_value=[])
    stub_modules["functions_authentication"] = functions_authentication

    functions_debug = types.ModuleType("functions_debug")
    functions_debug.debug_print = Mock()
    stub_modules["functions_debug"] = functions_debug

    functions_settings = types.ModuleType("functions_settings")
    functions_settings.get_settings = Mock(return_value={})
    functions_settings.sanitize_settings_for_user = Mock(side_effect=lambda settings: settings)
    stub_modules["functions_settings"] = functions_settings

    swagger_wrapper = types.ModuleType("swagger_wrapper")
    swagger_wrapper.swagger_route = Mock(side_effect=lambda *args, **kwargs: (lambda function: function))
    swagger_wrapper.get_auth_security = Mock(return_value=[])
    stub_modules["swagger_wrapper"] = swagger_wrapper

    for stub_name, stub_module in stub_modules.items():
        sys.modules[stub_name] = stub_module

    return stub_modules


route_module = import_module_without_live_cosmos("route_frontend_authentication")


EXPECTED_EASY_AUTH_LOGOUT = "/.auth/logout?post_logout_redirect_uri=%2Flogin"


def _build_test_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"

    def index():
        return "ok"

    app.add_url_rule("/", endpoint="public_app.index", view_func=index)

    auth_blueprint = Blueprint("frontend_authentication", __name__)
    route_module.register_route_frontend_authentication(auth_blueprint)
    app.register_blueprint(auth_blueprint)
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
    ), patch.object(route_module, "IS_DEVELOPMENT", False):
        with app.test_request_context(
            "/logout/local",
            base_url="https://example.azurewebsites.net",
            headers={"X-MS-CLIENT-PRINCIPAL-ID": "user-oid"},
        ):
            session["user"] = {"name": "Test User"}

            response = app.view_functions["frontend_authentication.local_logout"]()

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
    ), patch.object(route_module, "IS_DEVELOPMENT", False):
        with app.test_request_context(
            "/logout",
            base_url="https://example.azurewebsites.net",
            headers={"X-MS-CLIENT-PRINCIPAL-ID": "user-oid"},
        ):
            session["user"] = {
                "name": "Test User",
                "preferred_username": "user@example.com",
            }

            response = app.view_functions["frontend_authentication.logout"]()

            assert response.status_code == 302, f"Expected redirect response, got {response.status_code}"
            assert response.headers.get("Location") == EXPECTED_EASY_AUTH_LOGOUT, (
                f"Unexpected full logout redirect: {response.headers.get('Location')}"
            )
            assert not session, f"Expected Flask session to be cleared, got {dict(session)}"

    print("App Service Easy Auth full logout redirects through /.auth/logout")


def test_development_mode_does_not_use_app_service_easy_auth_logout():
    """Verify development mode skips Easy Auth logout even when Azure hosting variables exist."""
    print("Testing development-mode logout avoids App Service Easy Auth redirect...")

    app = _build_test_app()

    with patch.dict(
        os.environ,
        {
            "WEBSITE_HOSTNAME": "oigchat-dev.dhs-oig.gov",
            "WEBSITE_AUTH_AAD_ALLOWED_TENANTS": "tenant-id",
        },
        clear=False,
    ), patch.object(route_module, "IS_DEVELOPMENT", True), patch.object(route_module, "get_settings", Mock(return_value={})):
        with app.test_request_context(
            "/logout/local",
            base_url="https://oigchat-dev.dhs-oig.gov",
            headers={"X-MS-CLIENT-PRINCIPAL-ID": "user-oid"},
        ):
            session["user"] = {"name": "Test User"}

            response = app.view_functions["frontend_authentication.local_logout"]()

            assert response.status_code == 302, f"Expected redirect response, got {response.status_code}"
            assert response.headers.get("Location") == "/", (
                f"Unexpected development local logout redirect: {response.headers.get('Location')}"
            )
            assert "user" not in session, f"Expected Flask session to be cleared, got {dict(session)}"

    print("Development-mode local logout avoids /.auth/logout")


if __name__ == "__main__":
    tests = [
        test_local_logout_uses_app_service_easy_auth_logout,
        test_full_logout_uses_app_service_easy_auth_logout,
        test_development_mode_does_not_use_app_service_easy_auth_logout,
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
