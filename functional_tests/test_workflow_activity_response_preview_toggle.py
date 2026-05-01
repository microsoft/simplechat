# test_workflow_activity_response_preview_toggle.py
#!/usr/bin/env python3
"""
Functional test for workflow activity response preview toggle.
Version: 0.241.042
Implemented in: 0.241.042

This test ensures that the workflow activity page exposes a collapsed-by-default
response preview toggle so users can reclaim vertical space until they choose to
open the preview panel.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "application" / "single_app" / "templates" / "workflow_activity.html"
SCRIPT_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workflow" / "workflow-activity.js"
STYLE_PATH = REPO_ROOT / "application" / "single_app" / "static" / "css" / "workflow-activity.css"


def assert_contains(content, expected, label):
    if expected not in content:
        raise AssertionError(f"{label}: expected to find {expected!r}")


def test_workflow_activity_response_toggle_contract():
    print("Testing workflow activity response preview toggle contract...")

    template_content = TEMPLATE_PATH.read_text(encoding="utf-8")
    script_content = SCRIPT_PATH.read_text(encoding="utf-8")
    style_content = STYLE_PATH.read_text(encoding="utf-8")

    assert_contains(template_content, 'id="workflow-activity-response-toggle"', "toggle button id")
    assert_contains(template_content, 'id="workflow-activity-response-toggle-label"', "toggle label id")
    assert_contains(template_content, 'Show response preview', "default toggle label")
    assert_contains(template_content, 'aria-controls="workflow-activity-response"', "toggle aria controls")

    assert_contains(script_content, 'responseExpanded: false', "default collapsed state")
    assert_contains(script_content, 'function syncResponseBlockVisibility()', "response sync function")
    assert_contains(script_content, 'responseEl.dataset.hasContent = "true"', "response content marker")
    assert_contains(script_content, 'pageState.responseExpanded = !pageState.responseExpanded;', "toggle click behavior")

    assert_contains(style_content, '.workflow-activity-response-toggle[aria-expanded="true"] .workflow-activity-response-toggle-icon', "toggle icon expanded style")

    print("Workflow activity response preview toggle contract passed.")
    return True


if __name__ == "__main__":
    success = test_workflow_activity_response_toggle_contract()
    raise SystemExit(0 if success else 1)
