# test_group_action_saved_test_role_policy.py
"""
Functional test for the M4 §2 saved-group-action test role fix.
Version: 0.261.137
Implemented in: 0.261.137

Testing a SAVED group action loads its stored configuration, credentials
included, so it is an editor capability, not a reader one. Before M4, both
``_resolve_action_identity_context`` and ``_load_existing_plugin_for_test``
admitted the four-role reader set (Owner/Admin/DocumentManager/User) when a test
referenced a saved group action, while a group edit needs Owner/Admin (Owner
only when ``require_owner_for_group_agent_management`` is set). This pins the
narrowed policy on both saved-group branches, so a later change cannot re-widen
a saved-action test back to ordinary members. The transient no-saved-action
branch is likewise narrowed to the edit roles (M4 §9.1), because its four callers
hydrate a group identity's stored credentials, and that narrowing is asserted
separately.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
ROUTES = APP_DIR / "route_backend_plugins.py"

OWNER_ONLY_SETTING = "require_owner_for_group_agent_management"
READER_TUPLE_MARKER = '"DocumentManager", "User"'


def _function_node(name):
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"route_backend_plugins.py no longer defines {name}")


def _segment(name, start_marker, end_marker):
    """Return the source of one branch of a function, between two markers."""
    node = _function_node(name)
    lines = ROUTES.read_text(encoding="utf-8").splitlines()[node.lineno - 1: node.end_lineno]
    body = "\n".join(lines)
    start = body.index(start_marker)
    end = body.index(end_marker, start + len(start_marker)) if end_marker else len(body)
    return body[start:end]


def test_resolve_identity_saved_group_branch_requires_edit_roles():
    """The existing-plugin group branch must gate on the owner-only setting, not on readers."""
    segment = _segment(
        "_resolve_action_identity_context",
        'if origin.scope_type == "group":',
        'if origin.scope_type == "global":',
    )
    assert "assert_group_role" in segment
    assert OWNER_ONLY_SETTING in segment
    assert READER_TUPLE_MARKER not in segment


def test_load_existing_plugin_group_branch_requires_edit_roles():
    """Loading a saved group action for a test must gate on the owner-only setting."""
    segment = _segment(
        "_load_existing_plugin_for_test",
        "if plugin_scope == 'group':",
        "elif plugin_scope == 'global':",
    )
    assert "assert_group_role" in segment
    assert OWNER_ONLY_SETTING in segment
    assert READER_TUPLE_MARKER not in segment


def test_transient_group_identity_branch_requires_edit_roles():
    """A transient group test (no saved action, no group_id) requires the edit roles.

    All four callers of this branch hydrate a group identity's stored credentials
    with ``SecretReturnType.VALUE``, and members can read an ``identity_id``, so a
    reader must not be able to trigger one (M4 §9.1). The legacy no-``group_id``
    branch now gates on the owner-only setting exactly as the saved branch does,
    never on the four-role reader set.
    """
    # The no-existing-plugin group branch follows the existing-plugin handling and
    # precedes the global branch that ends the requested-scope resolution.
    segment = _segment(
        "_resolve_action_identity_context",
        'if requested_scope == "group":',
        'if requested_scope == "global":',
    )
    assert "assert_group_role" in segment
    assert OWNER_ONLY_SETTING in segment
    assert READER_TUPLE_MARKER not in segment


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
