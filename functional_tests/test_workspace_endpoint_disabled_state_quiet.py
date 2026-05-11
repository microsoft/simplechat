# test_workspace_endpoint_disabled_state_quiet.py
#!/usr/bin/env python3
"""
Functional test for workspace endpoint disabled-state suppression.
Version: 0.240.005
Implemented in: 0.240.005

This test ensures the workspace endpoint module only loads when the endpoints
UI is rendered and quietly suppresses disabled-feature responses instead of
showing user-facing errors.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
WORKSPACE_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_model_endpoints.js"
WORKSPACE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"
GROUP_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"


def test_workspace_endpoint_disabled_state_quiet():
    """Verify endpoint management stays quiet when the feature is unavailable."""
    config_content = CONFIG_FILE.read_text(encoding="utf-8")
    js_content = WORKSPACE_JS.read_text(encoding="utf-8")
    workspace_template = WORKSPACE_TEMPLATE.read_text(encoding="utf-8")
    group_template = GROUP_TEMPLATE.read_text(encoding="utf-8")

    assert 'VERSION = "0.240.005"' in config_content, "Expected config.py version 0.240.005"
    assert "function hasEndpointManagementUi()" in js_content, (
        "Expected workspace_model_endpoints.js to detect whether the endpoints UI exists."
    )
    assert "return Boolean(endpointsWrapper && endpointsTbody);" in js_content, (
        "Expected workspace_model_endpoints.js to require the endpoints wrapper and table body before initializing."
    )
    assert "if (!hasEndpointManagementUi()) {" in js_content, (
        "Expected workspace_model_endpoints.js to skip initialization when the endpoints UI is absent."
    )
    assert "function isEndpointsFeatureDisabled(error)" in js_content, (
        "Expected workspace_model_endpoints.js to recognize disabled endpoint-feature responses."
    )
    assert 'console.info("[WorkspaceEndpoints] Endpoint management is disabled; skipping endpoint load.");' in js_content, (
        "Expected disabled endpoint loads to be logged quietly instead of shown as a toast."
    )
    assert (
        "{% if settings.per_user_semantic_kernel and settings.enable_semantic_kernel and settings.allow_user_custom_endpoints and settings.enable_multi_model_endpoints %}"
        in workspace_template
    ), "Expected workspace.html to gate the endpoint module behind the same conditions as the endpoints tab."
    assert (
        "{% if settings.enable_semantic_kernel and settings.allow_group_custom_endpoints and settings.enable_multi_model_endpoints %}"
        in group_template
    ), "Expected group_workspaces.html to gate the endpoint module behind the same conditions as the group endpoints tab."


if __name__ == "__main__":
    test_workspace_endpoint_disabled_state_quiet()
    print("✅ Workspace endpoint disabled-state suppression verified.")