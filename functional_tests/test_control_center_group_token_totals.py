# test_control_center_group_token_totals.py
#!/usr/bin/env python3
"""
Functional test for Control Center group token totals.
Version: 0.241.112
Implemented in: 0.241.112

This test ensures that group token totals are aggregated in the Control Center
backend and surfaced by the group management table, modal, and CSV export UI.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_control_center.py"
CONTROL_CENTER_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "control-center.js"
CONTROL_CENTER_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "control_center.html"


def assert_contains(content, expected, description):
    """Assert that expected source exists and print a useful failure label."""
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_control_center_group_token_totals():
    """Validate source wiring for Control Center group token totals."""
    print("Testing Control Center group token total integration...")

    backend_source = BACKEND_FILE.read_text(encoding="utf-8")
    js_source = CONTROL_CENTER_JS.read_text(encoding="utf-8")
    template_source = CONTROL_CENTER_TEMPLATE.read_text(encoding="utf-8")

    assert_contains(backend_source, "def get_group_token_totals(group_ids):", "backend token aggregation helper")
    assert_contains(backend_source, "ARRAY_CONTAINS(@group_ids, c.workspace_context.group_id)", "paged group token aggregation")
    assert_contains(backend_source, "def attach_group_token_totals(groups):", "group token attachment helper")
    assert_contains(backend_source, "attach_group_token_totals(enhanced_groups)", "group list token attachment")
    assert_contains(backend_source, "attach_group_token_totals([enhanced_group])", "group detail token attachment")

    assert_contains(template_source, "data-sort=\"tokens\"", "sortable token total column")
    assert_contains(template_source, "id=\"modalGroupTokens\"", "group modal token total field")

    assert_contains(js_source, "getGroupTokenTotal(group)", "group token total formatter")
    assert_contains(js_source, "'Token Total'", "group CSV token total header")
    assert_contains(js_source, "tokenTotalFormatted", "group table token total rendering")

    print("Control Center group token total integration test passed.")
    return True


if __name__ == "__main__":
    try:
        success = test_control_center_group_token_totals()
    except Exception as ex:
        print(f"Test failed: {ex}")
        sys.exit(1)

    sys.exit(0 if success else 1)