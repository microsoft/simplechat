# test_tableau_action_plugin.py
#!/usr/bin/env python3
"""
Functional test for Tableau action plugin configuration.
Version: 0.250.030
Implemented in: 0.241.210

This test ensures the Tableau action factory, plugin, manifest validation,
reusable identity contract, and read-only content discovery work without
requiring a live Tableau Server or Tableau Cloud site.
"""

import os
import sys
import traceback
import types
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

simplechat_operations_stub = types.ModuleType("functions_simplechat_operations")
simplechat_operations_stub.SIMPLECHAT_DEFAULT_ENDPOINT = "simplechat://internal"
sys.modules.setdefault("functions_simplechat_operations", simplechat_operations_stub)


def plugin_function_logger(_plugin_name):
    def decorator(function):
        return function

    return decorator


plugin_invocation_logger_stub = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
plugin_invocation_logger_stub.plugin_function_logger = plugin_function_logger
sys.modules.setdefault("semantic_kernel_plugins.plugin_invocation_logger", plugin_invocation_logger_stub)

from functions_tableau_operations import (  # noqa: E402
    TABLEAU_AUTH_METHOD_PAT,
    TABLEAU_AUTH_METHOD_USERNAME_PASSWORD,
    TABLEAU_PLUGIN_TYPE,
    normalize_tableau_additional_fields,
    normalize_tableau_server_url,
)
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker  # noqa: E402
from semantic_kernel_plugins.tableau_plugin_factory import TableauPluginFactory  # noqa: E402
import semantic_kernel_plugins.tableau_plugin as tableau_plugin_module  # noqa: E402


class FakeTableauItem:
    """Small Tableau item stand-in for plugin result normalization tests."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class FakeRequestOptions:
    def __init__(self, pagesize=None):
        self.pagesize = pagesize


class FakeCollection:
    def __init__(self, items):
        self.items = items

    def get(self, _request_options=None):
        return self.items, None


class FakeWorkbooksCollection(FakeCollection):
    def get_by_id(self, workbook_id):
        for item in self.items:
            if item.id == workbook_id:
                return item
        raise LookupError("Workbook not found")

    def populate_views(self, workbook):
        workbook.views = [
            FakeTableauItem(id="view-1", name="Executive Summary", workbook_id=workbook.id),
            FakeTableauItem(id="view-2", name="Regional Detail", workbook_id=workbook.id),
        ]


class FakeAuthManager:
    def __init__(self):
        self.last_auth = None

    def sign_in(self, tableau_auth):
        self.last_auth = tableau_auth
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class FakeServer:
    last_instance = None

    def __init__(self, endpoint, use_server_version=True):
        self.endpoint = endpoint
        self.use_server_version = use_server_version
        self.http_options = {}
        self.auth = FakeAuthManager()
        self.projects = FakeCollection([
            FakeTableauItem(id="project-1", name="Finance", description="Finance analytics"),
        ])
        self.workbooks = FakeWorkbooksCollection([
            FakeTableauItem(id="wb-1", name="Sales Dashboard", project_name="Finance"),
            FakeTableauItem(id="wb-2", name="Inventory Overview", project_name="Operations"),
        ])
        self.views = FakeCollection([
            FakeTableauItem(id="view-1", name="Executive Summary", workbook_id="wb-1"),
        ])
        self.datasources = FakeCollection([
            FakeTableauItem(id="ds-1", name="Sales Extract", project_name="Finance"),
        ])
        FakeServer.last_instance = self

    def add_http_options(self, options):
        self.http_options.update(options)


class FakeTSC:
    RequestOptions = FakeRequestOptions
    Server = FakeServer

    class PersonalAccessTokenAuth:
        def __init__(self, token_name, personal_access_token, site_id=""):
            self.token_name = token_name
            self.personal_access_token = personal_access_token
            self.site_id = site_id

    class TableauAuth:
        def __init__(self, username, password, site_id=""):
            self.username = username
            self.password = password
            self.site_id = site_id

    @staticmethod
    def Pager(collection, _request_options):
        return iter(collection.items)


def build_manifest(**overrides):
    manifest = {
        "id": "tableau-action-id",
        "name": "tableau_read_only",
        "displayName": "Tableau Read Only",
        "type": TABLEAU_PLUGIN_TYPE,
        "description": "Read-only Tableau content discovery tools",
        "endpoint": "https://10ax.online.tableau.com",
        "auth": {
            "type": "key",
            "identity": "simplechat-agent",
            "key": "pat-secret",
        },
        "metadata": {
            "description": "Tableau action for tests",
        },
        "additionalFields": {
            "server_url": "https://10ax.online.tableau.com",
            "site_content_url": "customer-success",
            "auth_method": TABLEAU_AUTH_METHOD_PAT,
            "pat_name": "simplechat-agent",
            "page_size": 100,
            "max_results": 100,
            "timeout": 30,
            "use_server_version": True,
        },
    }
    manifest.update(overrides)
    return manifest


def test_tableau_defaults_and_factory_normalization():
    """Validate Tableau defaults, endpoint normalization, and factory metadata."""
    print("Testing Tableau defaults and factory normalization...")

    normalized_url = normalize_tableau_server_url("10ax.online.tableau.com/")
    assert normalized_url == "https://10ax.online.tableau.com"

    defaults = normalize_tableau_additional_fields({"page_size": "5000", "timeout": "bad"})
    assert defaults["auth_method"] == TABLEAU_AUTH_METHOD_PAT
    assert defaults["page_size"] == 1000
    assert defaults["max_results"] == 100
    assert defaults["timeout"] == 30
    assert defaults["use_server_version"] is True

    plugin = TableauPluginFactory.create_from_config(build_manifest(endpoint="10ax.online.tableau.com/"))
    assert plugin.endpoint == "https://10ax.online.tableau.com"
    assert plugin.site_content_url == "customer-success"
    assert plugin.pat_name == "simplechat-agent"
    assert plugin.metadata["type"] == TABLEAU_PLUGIN_TYPE
    assert plugin.get_functions() == [
        "search_tableau_content",
        "list_projects",
        "list_workbooks",
        "list_views",
        "list_datasources",
        "get_workbook_details",
    ]
    assert not any(function_name in plugin.get_functions() for function_name in ["publish_workbook", "delete_workbook"])

    print("Tableau defaults and factory normalization verified.")
    return True


def test_tableau_manifest_validation():
    """Validate health checker rules for Tableau manifests."""
    print("Testing Tableau manifest validation...")

    valid, errors = PluginHealthChecker.validate_plugin_manifest(build_manifest(), TABLEAU_PLUGIN_TYPE)
    assert valid, f"Expected valid Tableau manifest, got: {errors}"

    invalid_endpoint = build_manifest(endpoint="http://10ax.online.tableau.com")
    valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_endpoint, TABLEAU_PLUGIN_TYPE)
    assert not valid
    assert any("HTTPS" in error for error in errors)

    missing_pat_name = build_manifest(auth={"type": "key", "key": "pat-secret"}, additionalFields={
        "server_url": "https://10ax.online.tableau.com",
        "auth_method": TABLEAU_AUTH_METHOD_PAT,
    })
    valid, errors = PluginHealthChecker.validate_plugin_manifest(missing_pat_name, TABLEAU_PLUGIN_TYPE)
    assert not valid
    assert any("pat_name" in error for error in errors)

    invalid_auth_method = build_manifest(additionalFields={
        "server_url": "https://10ax.online.tableau.com",
        "auth_method": "oauth2",
        "pat_name": "simplechat-agent",
    })
    valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_auth_method, TABLEAU_PLUGIN_TYPE)
    assert not valid
    assert any("auth_method" in error for error in errors)

    reusable_identity_manifest = build_manifest(
        identity_id="workspace-identity-id",
        auth={"type": "identity", "identity": "workspace-identity-id"},
        additionalFields={
            "server_url": "https://10ax.online.tableau.com",
            "auth_method": TABLEAU_AUTH_METHOD_PAT,
            "identity_auth_type": "api_key",
            "pat_name": "simplechat-agent",
        },
    )
    valid, errors = PluginHealthChecker.validate_plugin_manifest(reusable_identity_manifest, TABLEAU_PLUGIN_TYPE)
    assert valid, f"Expected reusable identity Tableau manifest to be valid, got: {errors}"

    reusable_identity_missing_pat = build_manifest(
        identity_id="workspace-identity-id",
        auth={"type": "identity", "identity": "workspace-identity-id"},
        additionalFields={
            "server_url": "https://10ax.online.tableau.com",
            "auth_method": TABLEAU_AUTH_METHOD_PAT,
            "identity_auth_type": "api_key",
        },
    )
    valid, errors = PluginHealthChecker.validate_plugin_manifest(reusable_identity_missing_pat, TABLEAU_PLUGIN_TYPE)
    assert not valid
    assert any("additionalFields.pat_name" in error for error in errors)

    print("Tableau manifest validation verified.")
    return True


def test_tableau_read_only_content_discovery_with_fake_client():
    """Validate Tableau content discovery without a live Tableau site."""
    print("Testing Tableau read-only content discovery with fake client...")

    original_tsc = tableau_plugin_module.TSC
    tableau_plugin_module.TSC = FakeTSC
    try:
        plugin = TableauPluginFactory.create_from_config(build_manifest())
        search_result = plugin.search_tableau_content("workbook", query="sales", max_results=1)

        assert search_result["success"] is True
        assert search_result["count"] == 1
        assert search_result["items"][0]["name"] == "Sales Dashboard"
        assert FakeServer.last_instance.http_options == {"timeout": 30}
        assert FakeServer.last_instance.auth.last_auth.token_name == "simplechat-agent"
        assert FakeServer.last_instance.auth.last_auth.site_id == "customer-success"

        project_result = plugin.list_projects(query="finance")
        assert project_result["success"] is True
        assert project_result["items"][0]["content_type"] == "project"

        details_result = plugin.get_workbook_details("wb-1")
        assert details_result["success"] is True
        assert details_result["workbook"]["id"] == "wb-1"
        assert details_result["view_count"] == 2

        invalid_result = plugin.search_tableau_content("users")
        assert invalid_result["success"] is False
        assert invalid_result["error_type"] == "validation"
    finally:
        tableau_plugin_module.TSC = original_tsc

    print("Tableau read-only content discovery verified.")
    return True


def test_tableau_identity_and_modal_contract():
    """Validate source markers for Tableau identity hydration and custom modal wiring."""
    print("Testing Tableau identity and modal source contract...")

    identity_source = (APP_DIR / "functions_workspace_identities.py").read_text(encoding="utf-8")
    modal_source = (APP_DIR / "static" / "js" / "plugin_modal_stepper.js").read_text(encoding="utf-8")
    template_source = (APP_DIR / "templates" / "_plugin_modal.html").read_text(encoding="utf-8")
    requirements_source = (APP_DIR / "requirements.txt").read_text(encoding="utf-8")
    config_source = (APP_DIR / "config.py").read_text(encoding="utf-8")

    assert 'ACTION_IDENTITY_TABLEAU_AUTH_TYPES = {"api_key", "username_password"}' in identity_source
    assert 'action_auth["identity"] = additional_fields.get("pat_name", "")' in identity_source
    assert "tableau-config-section" in template_source
    assert "summary-tableau-section" in template_source
    assert "tableau-identity-select" in template_source
    assert "isTableauType" in modal_source
    assert "getTableauConfiguration" in modal_source
    assert "toggleTableauAuthFields" in modal_source
    assert "populateTableauSummary" in modal_source
    assert "tableauserverclient==0.40" in requirements_source
    assert 'VERSION = "0.250.030"' in config_source

    print("Tableau identity and modal source contract verified.")
    return True


if __name__ == "__main__":
    tests = [
        test_tableau_defaults_and_factory_normalization,
        test_tableau_manifest_validation,
        test_tableau_read_only_content_discovery_with_fake_client,
        test_tableau_identity_and_modal_contract,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)