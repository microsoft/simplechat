# test_workflow_activity_dark_mode_layout_contract.py
#!/usr/bin/env python3
"""
Functional test for workflow activity dark mode and layout contract.
Version: 0.241.043
Implemented in: 0.241.043

This test ensures the workflow activity page ships explicit dark-mode styling
and a page-specific main-content layout override so the view remains readable
and spacious when the left sidebar is expanded.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = REPO_ROOT / "application" / "single_app" / "static" / "css" / "workflow-activity.css"
SCRIPT_PATH = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workflow" / "workflow-activity.js"


def assert_contains(content, expected, label):
    if expected not in content:
        raise AssertionError(f"{label}: expected to find {expected!r}")


def test_workflow_activity_dark_mode_and_layout_contract():
    print("Testing workflow activity dark mode and layout contract...")

    style_content = STYLE_PATH.read_text(encoding="utf-8")
    script_content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert_contains(style_content, '[data-bs-theme="dark"] .workflow-activity-page', "dark mode selector")
    assert_contains(style_content, '#main-content.workflow-activity-main-content', "main-content width override")
    assert_contains(style_content, '--workflow-activity-surface-start', "dark mode surface token")
    assert_contains(script_content, 'mainContentEl.classList.add("workflow-activity-main-content")', "layout mode activation")
    assert_contains(script_content, 'mainContentEl.classList.remove("workflow-activity-main-content")', "layout mode cleanup")

    print("Workflow activity dark mode and layout contract passed.")
    return True


if __name__ == "__main__":
    success = test_workflow_activity_dark_mode_and_layout_contract()
    raise SystemExit(0 if success else 1)