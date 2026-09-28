# test_document_action_hint_seam.py
"""
Functional test for the backend/frontend seam on per-document action hints.
Version: 0.261.133
Implemented in: 0.261.134

The V2 explorer gates every per-document operation on the inline
``document_actions`` array, and gates collaboration decisions on the inline
``document_collaboration_actions`` array. The backend read projector is the only
place those arrays are produced, because both fields are in
``PRIVATE_DOCUMENT_FIELDS`` and any stored copy is stripped before projection.

M3B shipped with the public projector hardcoding ``document_actions = []``, left
over from the read-only M3A slice. Every public delete, download, edit, extract,
reprocess and bulk-tag was therefore gated off against the real backend. It
survived because each slice was green against its own assumption: the backend
suite pinned the empty list, while the frontend fixture mocked a populated one.
Neither ever saw the other's shape.

These tests pin the seam itself rather than either side's assumption. The group
projector is included as a control: it computes both arrays from policy, so if
the group checks ever fail, the test is wrong rather than the code.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
UI_LIB = REPO_ROOT / "application" / "v2_ui" / "src" / "lib"

sys.path.append(str(Path(__file__).resolve().parent))

ACTION_FIELDS = ("document_actions", "document_collaboration_actions")

PROJECTORS = {
    "group": ("functions_group_document_reads.py", "_project_group_document"),
    "public": ("functions_public_document_reads.py", "_project_public_document"),
}


def _projector(scope):
    filename, function_name = PROJECTORS[scope]
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"{filename} no longer defines {function_name}")


def _assignments(function, field):
    """Every value assigned to ``payload[field]`` anywhere in the function."""
    values = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name) and target.value.id == "payload"
                and isinstance(target.slice, ast.Constant) and target.slice.value == field
            ):
                values.append(node.value)
    return values


def _is_hardcoded_empty(value):
    return isinstance(value, ast.List) and not value.elts


# --- control: group computes both arrays from policy -------------------------

@pytest.mark.parametrize("field", ACTION_FIELDS)
def test_group_projector_computes_action_hints_from_policy(field):
    """Control. If this fails, the seam test is wrong, not the application."""
    values = _assignments(_projector("group"), field)

    assert values, f"group projector no longer assigns {field}"
    assert all(isinstance(value, ast.Call) for value in values), (
        f"group projector assigns {field} from something other than a policy call"
    )


# --- the regression: public must do the same ---------------------------------

@pytest.mark.parametrize("field", ACTION_FIELDS)
def test_public_projector_never_hardcodes_an_empty_action_hint(field):
    """The exact M3B defect: a literal ``[]`` gates every public operation off."""
    hardcoded = [
        value for value in _assignments(_projector("public"), field)
        if _is_hardcoded_empty(value)
    ]

    assert hardcoded == [], (
        f"functions_public_document_reads.py hardcodes payload[{field!r}] = []. "
        "The explorer gates every per-document operation on this array, so an "
        "empty literal disables them all against the real backend."
    )


@pytest.mark.parametrize("field", ACTION_FIELDS)
def test_public_projector_computes_action_hints_from_policy(field):
    """Public must mirror group: compute each array from current authorization."""
    values = _assignments(_projector("public"), field)

    assert values, (
        f"public projector never assigns {field}. Because the field is in "
        "PRIVATE_DOCUMENT_FIELDS, any stored copy is stripped, so an unassigned "
        "field reaches the client as undefined and gates every operation off."
    )
    assert all(isinstance(value, ast.Call) for value in values), (
        f"public projector assigns {field} from something other than a policy call"
    )


# --- why the backend obligation exists ---------------------------------------

@pytest.mark.parametrize("module, field", [
    ("documentOperations.ts", "document_actions"),
    ("documentCollaboration.ts", "document_collaboration_actions"),
])
def test_explorer_gates_on_the_inline_action_array(module, field):
    """The client gate is correct and must stay: it is what makes the seam load-bearing.

    Do not "fix" an empty array on the client by falling back to enabling the
    operation. That converts a visible defect into a silent client-side bypass
    of the server's per-document authorization hint.
    """
    source = (UI_LIB / module).read_text(encoding="utf-8")

    assert re.search(rf"document\.{field}\.includes\(", source), (
        f"{module} no longer gates operations on the inline {field} array"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
