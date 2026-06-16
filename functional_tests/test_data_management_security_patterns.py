#!/usr/bin/env python3
# test_data_management_security_patterns.py
"""
Functional test for Data Management security patterns.
Version: 0.241.211
Implemented in: 0.241.211

This test ensures Data Management admin routes require authenticated admin
access, secrets stay redacted in frontend responses, and the admin browser
controller avoids XSS-prone rendering sinks.
"""

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTE_FILE = APP_ROOT / "route_backend_data_management.py"
FUNCTIONS_FILE = APP_ROOT / "functions_data_management.py"
ADMIN_JS = APP_ROOT / "static" / "js" / "admin" / "admin_data_management.js"
ADMIN_TEMPLATE = APP_ROOT / "templates" / "admin_settings.html"
SIDEBAR_TEMPLATE = APP_ROOT / "templates" / "_sidebar_nav.html"
CONFIG_FILE = APP_ROOT / "config.py"


def read_text(path):
    return path.read_text(encoding="utf-8")


def route_functions_with_decorators():
    parsed = ast.parse(read_text(ROUTE_FILE), filename=str(ROUTE_FILE))
    route_functions = []
    for node in ast.walk(parsed):
        if not isinstance(node, ast.FunctionDef):
            continue
        decorator_names = []
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr == "route":
                    decorator_names.append("app.route")
                elif decorator.func.attr:
                    decorator_names.append(decorator.func.attr)
            elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                decorator_names.append(decorator.func.id)
            elif isinstance(decorator, ast.Name):
                decorator_names.append(decorator.id)
        if "app.route" in decorator_names:
            route_functions.append((node.name, decorator_names))
    return route_functions


def test_version_and_container_registration():
    """Validate the Data Management version and Cosmos job container registrations."""
    config_source = read_text(CONFIG_FILE)

    assert 'VERSION = "0.241.211"' in config_source
    assert 'cosmos_data_management_jobs_container_name = "data_management_jobs"' in config_source
    assert 'partition_key=PartitionKey(path="/id")' in config_source
    assert 'cosmos_data_management_job_items_container_name = "data_management_job_items"' in config_source
    assert 'partition_key=PartitionKey(path="/job_id")' in config_source


def test_admin_routes_require_login_admin_and_swagger_security():
    """Validate every Data Management route has the required admin security stack."""
    routes = route_functions_with_decorators()
    assert len(routes) == 6

    for function_name, decorators in routes:
        assert "swagger_route" in decorators, f"{function_name} missing swagger_route"
        assert "login_required" in decorators, f"{function_name} missing login_required"
        assert "admin_required" in decorators, f"{function_name} missing admin_required"

    source = read_text(ROUTE_FILE)
    assert 'from swagger_wrapper import get_auth_security, swagger_route' in source
    assert '/api/admin/data-management/settings' in source
    assert '/api/admin/data-management/jobs' in source
    assert 'current_app._get_current_object()' in source


def test_settings_secrets_are_redacted_for_frontend():
    """Validate backup settings secrets are redacted before returning to the browser."""
    source = read_text(FUNCTIONS_FILE)

    for field_name in [
        '"backup_storage_connection_string"',
        '"encryption_key_reference"',
        '"target_cosmos_key"',
    ]:
        assert field_name in source

    assert 'DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS' in source
    assert 'DATA_MANAGEMENT_REDACTED_VALUE = "***REDACTED***"' in source
    assert 'sanitize_data_management_settings_for_admin' in source
    assert 'sanitized[field_name] = DATA_MANAGEMENT_REDACTED_VALUE' in source
    assert 'if payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:' in source


def test_admin_javascript_uses_safe_dom_patterns():
    """Validate Data Management browser code avoids common XSS sinks."""
    source = read_text(ADMIN_JS)
    forbidden_patterns = [
        r"\.innerHTML\b",
        r"\.outerHTML\b",
        r"insertAdjacentHTML\s*\(",
        r"setAttribute\s*\(\s*['\"]on",
        r"javascript:",
        r"\bonclick\b",
        r"\bonerror\b",
        r"\bonload\b",
    ]

    for pattern in forbidden_patterns:
        assert not re.search(pattern, source), f"Unsafe browser sink found: {pattern}"

    for required_snippet in [
        'document.createElement("tr")',
        'document.createElement("td")',
        'badge.textContent = status.replace(/_/g, " ");',
        'cell.textContent = text ?? "";',
        'addEventListener("click"',
        'credentials: "same-origin"',
    ]:
        assert required_snippet in source


def test_admin_ui_exposes_data_management_without_external_assets():
    """Validate the admin UI has the tab, warning, controls, and local asset reference."""
    template = read_text(ADMIN_TEMPLATE)
    sidebar = read_text(SIDEBAR_TEMPLATE)

    for marker in [
        'id="data-management-tab"',
        'id="data-management"',
        'id="data-management-save-settings-btn"',
        'id="data-management-operational-warning"',
        'We suggest not running backups, restores, or migrations during your operational business hours.',
        'id="data_management_full_frequency"',
        'id="data_management_scheduled_time_utc" value="03:00"',
        'id="data_management_partial_enabled"',
        'id="data_management_target_cosmos_endpoint"',
        'id="data-management-jobs-tbody"',
        "static', filename='js/admin/admin_data_management.js'",
    ]:
        assert marker in template

    assert 'cdn.jsdelivr.net' not in read_text(ADMIN_JS)
    assert 'data-tab="data-management"' in sidebar
    assert 'data-section="data-management-target-cosmos-section"' in sidebar


if __name__ == "__main__":
    test_version_and_container_registration()
    test_admin_routes_require_login_admin_and_swagger_security()
    test_settings_secrets_are_redacted_for_frontend()
    test_admin_javascript_uses_safe_dom_patterns()
    test_admin_ui_exposes_data_management_without_external_assets()
    print("Data Management security pattern tests passed")