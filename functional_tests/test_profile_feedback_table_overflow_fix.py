# test_profile_feedback_table_overflow_fix.py
"""
Functional test for the profile feedback table overflow fix.
Version: 0.241.034
Implemented in: 0.241.034

This test ensures that the profile My Feedback table uses the compact column
set while retaining AI response and admin action details in the detail modal.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "profile.html"
PROFILE_SCRIPT = REPO_ROOT / "application" / "single_app" / "static" / "js" / "profile" / "profile-tabs.js"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
EXPECTED_VERSION = "0.241.034"


def _read_file(path):
    return path.read_text(encoding="utf-8")


def _extract_function(source, function_name):
    pattern = re.compile(rf"function {function_name}\([^)]*\) \{{(?P<body>.*?)\n    \}}", re.DOTALL)
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"Could not find {function_name} in profile-tabs.js")
    return match.group("body")


def test_profile_feedback_table_contract():
    """Validate compact profile feedback table markup, renderer, and version."""
    print("Testing profile feedback compact table contract...")

    profile_html = _read_file(PROFILE_TEMPLATE)
    profile_script = _read_file(PROFILE_SCRIPT)
    config_py = _read_file(CONFIG_FILE)
    render_feedback_body = _extract_function(profile_script, "renderFeedbackTableRows")
    load_feedback_body = _extract_function(profile_script, "loadProfileFeedbackTable")

    assert f'VERSION = "{EXPECTED_VERSION}"' in config_py
    assert "profile-feedback-table-wrapper" in profile_html
    assert "#profile-feedback-table" in profile_html
    assert "<th>Timestamp</th>" in profile_html
    assert "<th>Prompt</th>" in profile_html
    assert "<th>Feedback</th>" in profile_html
    assert "<th>Reason</th>" in profile_html
    assert "<th>Acknowledged</th>" in profile_html
    assert "<th>AI Response</th>" not in profile_html
    assert "<th>Admin Action</th>" not in profile_html
    assert 'colspan="6"' in profile_html
    assert 'colspan="8"' not in profile_html

    assert "item.aiResponse" not in render_feedback_body
    assert "adminReview.actionTaken" not in render_feedback_body
    assert "renderTableMessageRow(tbody, 6" in render_feedback_body
    assert "renderTableMessageRow(tbody, 6" in load_feedback_body

    assert "profile-feedback-detail-response" in profile_html
    assert "profile-feedback-detail-action" in profile_html
    assert "selectedItem.aiResponse" in profile_script
    assert "adminReview.actionTaken" in profile_script

    print("Profile feedback compact table contract passed.")


if __name__ == "__main__":
    try:
        test_profile_feedback_table_contract()
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)