# test_control_center_token_export_workspace_names.py
#!/usr/bin/env python3
"""
Functional test for Control Center token export workspace names.
Version: 0.241.115
Implemented in: 0.241.115

This test ensures that token usage CSV exports include friendly group and public
workspace names alongside their scoped IDs.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_control_center.py"


def assert_contains(content, expected, description):
    """Assert that expected source exists and print a useful failure label."""
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_token_export_workspace_names():
    """Validate source wiring for token export workspace name fields."""
    print("Testing Control Center token export workspace names...")

    backend_source = BACKEND_FILE.read_text(encoding="utf-8")

    assert_contains(backend_source, "def get_group_name_map(group_ids):", "group name resolver")
    assert_contains(backend_source, "def get_public_workspace_name_map(public_workspace_ids):", "public workspace name resolver")
    assert_contains(backend_source, "group_name_map = get_group_name_map", "token export group name map")
    assert_contains(backend_source, "public_workspace_name_map = get_public_workspace_name_map", "token export public workspace name map")
    assert_contains(backend_source, "'group_name': group_name_map.get(group_id, '')", "token record group name")
    assert_contains(backend_source, "'public_workspace_name': public_workspace_name_map.get(public_workspace_id, '')", "token record public workspace name")
    assert_contains(backend_source, "'Group Name', 'Public Workspace ID', 'Public Workspace Name'", "token CSV name headers")
    assert_contains(backend_source, "record.get('group_name', '')", "token CSV group name value")
    assert_contains(backend_source, "record.get('public_workspace_name', '')", "token CSV public workspace name value")

    print("Control Center token export workspace name test passed.")
    return True


if __name__ == "__main__":
    try:
        success = test_token_export_workspace_names()
    except Exception as ex:
        print(f"Test failed: {ex}")
        sys.exit(1)

    sys.exit(0 if success else 1)