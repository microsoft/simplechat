# test_group_prompt_action_hint_seam.py
"""
Functional test for the backend/frontend seam on per-prompt action hints.
Version: 0.261.136
Implemented in: 0.261.136

Two public read-only-era constants shipped as live defects earlier in this
programme: ``document_actions = []`` and ``file_downloads_enabled = False`` were
left hardcoded after the milestones that were meant to rewire them. Each survived
because the backend suite pinned the stale constant while the frontend fixture
mocked a populated value, so neither side ever saw the other's shape.

The group prompt projector must not repeat that. ``prompt_actions`` is in
``PRIVATE_GROUP_PROMPT_FIELDS``, so any stored copy is stripped and the projector
is the only place the array is produced. This test pins the seam: the projector
must compute ``prompt_actions`` from a policy call, never from a constant.
"""

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.append(str(Path(__file__).resolve().parent))

ACCESS_FILE = "functions_group_prompt_access.py"
PROJECTOR = "_project_group_prompt"
ACTION_FIELD = "prompt_actions"
POLICY_FUNCTION = "group_prompt_actions"


def _projector():
    tree = ast.parse((APP_DIR / ACCESS_FILE).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == PROJECTOR:
            return node
    raise AssertionError(f"{ACCESS_FILE} no longer defines {PROJECTOR}")


def _assignments(function, field):
    """Every value assigned to ``projected[field]`` anywhere in the function."""
    values = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name) and target.value.id == "projected"
                and isinstance(target.slice, ast.Constant) and target.slice.value == field
            ):
                values.append(node.value)
    return values


def test_projector_never_hardcodes_an_empty_action_hint():
    """A literal ``[]`` would gate every group prompt edit and delete off."""
    hardcoded = [
        value for value in _assignments(_projector(), ACTION_FIELD)
        if isinstance(value, ast.List) and not value.elts
    ]

    assert hardcoded == [], (
        f"{ACCESS_FILE} hardcodes projected[{ACTION_FIELD!r}] = []. The explorer "
        "gates every per-prompt operation on this array, so an empty literal "
        "disables them all against the real backend."
    )


def test_projector_computes_action_hint_from_policy():
    """The array must be a call to the policy function, computed per request."""
    values = _assignments(_projector(), ACTION_FIELD)

    assert values, (
        f"{PROJECTOR} never assigns {ACTION_FIELD}. Because the field is in "
        "PRIVATE_GROUP_PROMPT_FIELDS, any stored copy is stripped, so an "
        "unassigned field reaches the client as undefined and gates every "
        "operation off."
    )
    for value in values:
        assert isinstance(value, ast.Call), (
            f"{PROJECTOR} assigns {ACTION_FIELD} from something other than a call"
        )
        assert isinstance(value.func, ast.Name) and value.func.id == POLICY_FUNCTION, (
            f"{PROJECTOR} must compute {ACTION_FIELD} from {POLICY_FUNCTION}()"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
