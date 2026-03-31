# test_control_center_token_filters.py
"""
Functional test for Control Center token filters.
Version: 0.239.164
Implemented in: 0.239.164

This test ensures that the Control Center token filters are wired through the
backend APIs, dashboard template, and client-side request handling.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def read_text(relative_path: str) -> str:
    """Read a repository file as UTF-8 text."""
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_backend_token_filter_routes_and_helpers_present() -> bool:
    """Validate the control center backend exposes token filter support."""
    print("Testing control center token filter backend wiring...")
    backend_content = read_text("application/single_app/route_backend_control_center.py")

    required_snippets = [
        "/api/admin/control-center/token-filters",
        "def extract_token_filters(source):",
        "def append_token_usage_filters(query_conditions, parameters, token_filters):",
        "def build_token_usage_query_context(start_date, end_date, token_filters=None):",
        "token_filters = extract_token_filters(request.args)",
        "token_filters = extract_token_filters(data)",
        "c.usage.model = @token_model",
        "c.workspace_context.group_id = @token_group_id",
        "c.workspace_context.public_workspace_id = @token_public_workspace_id"
    ]

    for snippet in required_snippets:
        if snippet not in backend_content:
            print(f"Missing backend snippet: {snippet}")
            return False

    print("Backend token filter support found.")
    return True


def test_control_center_template_contains_token_filter_controls() -> bool:
    """Validate the dashboard template includes token filter controls."""
    print("Testing control center token filter template controls...")
    template_content = read_text("application/single_app/templates/control_center.html")

    required_ids = [
        'id="tokenUserFilter"',
        'id="tokenWorkspaceTypeFilter"',
        'id="tokenGroupFilter"',
        'id="tokenPublicWorkspaceFilter"',
        'id="tokenModelFilter"',
        'id="tokenTypeFilter"',
        'id="tokenApplyFiltersBtn"',
        'id="tokenResetFiltersBtn"'
    ]

    for element_id in required_ids:
        if element_id not in template_content:
            print(f"Missing template element: {element_id}")
            return False

    print("Template token filter controls found.")
    return True


def test_control_center_javascript_wires_token_filter_requests() -> bool:
    """Validate the client script loads and forwards token filters."""
    print("Testing control center token filter JavaScript wiring...")
    js_content = read_text("application/single_app/static/js/control-center.js")

    required_snippets = [
        "this.tokenFilters = this.getDefaultTokenFilters();",
        "loadTokenFilterOptions()",
        "getTokenFilterRequestPayload()",
        "applyTokenFilters()",
        "resetTokenFilters()",
        "syncTokenFiltersFromControls()",
        "params.append(key, value);",
        "exportData.token_filters = tokenFilters;",
        "chatData.token_filters = tokenFilters;",
        "'/api/admin/control-center/token-filters'"
    ]

    for snippet in required_snippets:
        if snippet not in js_content:
            print(f"Missing JavaScript snippet: {snippet}")
            return False

    print("JavaScript token filter wiring found.")
    return True


def test_config_version_bumped_for_token_filters() -> bool:
    """Validate the repository version bump for the feature."""
    print("Testing config version bump...")
    config_content = read_text("application/single_app/config.py")

    if 'VERSION = "0.239.164"' not in config_content:
        print("Config version was not bumped to 0.239.164")
        return False

    print("Config version bump found.")
    return True


if __name__ == "__main__":
    checks = [
        test_backend_token_filter_routes_and_helpers_present,
        test_control_center_template_contains_token_filter_controls,
        test_control_center_javascript_wires_token_filter_requests,
        test_config_version_bumped_for_token_filters,
    ]

    results = []
    for check in checks:
        print(f"\nRunning {check.__name__}...")
        results.append(check())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} checks passed")
    raise SystemExit(0 if success else 1)