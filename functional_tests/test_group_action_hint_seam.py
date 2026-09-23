# test_group_action_hint_seam.py
"""
Functional test for the backend/frontend seam on per-action hints.
Version: 0.261.137
Implemented in: 0.261.137

Two public read-only-era constants shipped as live defects earlier in this
programme: ``document_actions = []`` and ``file_downloads_enabled = False`` were
left hardcoded after the milestones that were meant to rewire them. Each survived
because the backend suite pinned the stale constant while the frontend fixture
mocked a populated value, so neither side ever saw the other's shape.

The group action projectors must not repeat that. ``action_actions`` is produced
only by the projection layer and is recomputed on every request. This test pins
the seam at both projection sites: the per-item value must be computed from the
``group_action_actions`` policy function, never from a bare constant. A global
action legitimately gets ``[]`` (it is read-only in group scope), but the group
branch must always resolve through policy.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"

ACCESS_FILE = "functions_group_action_access.py"
PROJECTORS = ("_project_group_action", "_group_action_resource")
ACTION_FIELD = "action_actions"
POLICY_FUNCTION = "group_action_actions"


def _function(name):
    tree = ast.parse((APP_DIR / ACCESS_FILE).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{ACCESS_FILE} no longer defines {name}")


def _action_field_assignments(function, field):
    """Every value assigned to a subscript whose key is ``field`` in ``function``."""
    values = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == field
            ):
                values.append(node.value)
    return values


def _calls_policy(value):
    """True when the assigned value tree contains a call to the policy function."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == POLICY_FUNCTION
        for node in ast.walk(value)
    )


@pytest.mark.parametrize("projector", PROJECTORS)
def test_projector_never_hardcodes_a_bare_action_hint(projector):
    """A bare literal (``[]`` or a list of constants) would ignore live policy."""
    hardcoded = [
        value for value in _action_field_assignments(_function(projector), ACTION_FIELD)
        if isinstance(value, ast.List)
    ]
    assert hardcoded == [], (
        f"{ACCESS_FILE}:{projector} assigns {ACTION_FIELD} from a bare list literal. "
        "The explorer gates every per-action operation on this array, so a constant "
        "here silently overrides the group action policy."
    )


@pytest.mark.parametrize("projector", PROJECTORS)
def test_projector_computes_action_hint_from_policy(projector):
    """Each assignment must resolve through the policy function, computed per request."""
    values = _action_field_assignments(_function(projector), ACTION_FIELD)
    assert values, (
        f"{projector} never assigns {ACTION_FIELD}; the client would read it as "
        "undefined and gate every per-action operation off."
    )
    for value in values:
        assert _calls_policy(value), (
            f"{projector} must compute {ACTION_FIELD} from {POLICY_FUNCTION}(), "
            "not from a constant or an unrelated expression."
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
