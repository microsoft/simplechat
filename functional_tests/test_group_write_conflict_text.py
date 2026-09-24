# test_group_write_conflict_text.py
"""
Functional test for the one group write conflict answer.
Version: 0.261.156
Implemented in: 0.261.156

When the group document keeps changing while a change to it is being saved
(``GroupDocumentWriteConflict``), every group route answers 409 with the
``error_code`` ``group_write_conflict`` and one reviewed sentence. Three sentences
existed before this: the group directory, settings and classic settings writers had
one, the membership routes another, and the model endpoint routes a third. Now the
code and the sentence both live in ``functions_group``, beside the exception, as
``GROUP_WRITE_CONFLICT_CODE`` and ``GROUP_WRITE_CONFLICT_MESSAGE``.

This test pins, statically, across the application:

- each literal appears exactly once, as that constant's value in ``functions_group.py``;
- no other "The group changed while ..." sentence exists;
- the names other modules use for the sentence and the code are ``functions_group``'s
  constants, not copies;
- the V2 client's fallback and the browser fixtures carry the same sentence.

The routes' answers themselves are pinned by their own suites, which all expect this
sentence.
"""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
SENTENCE = "The group changed while your request was being saved. Try again."
CODE = "group_write_conflict"


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def string_constants(tree):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


@pytest.fixture(scope="module")
def modules():
    return {path.relative_to(APP_ROOT).as_posix(): parse(path) for path in sorted(APP_ROOT.rglob("*.py"))}


def module_assignment(tree, name):
    return next(
        node.value for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    )


def imports_from(tree, module_name):
    return {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == module_name
        for alias in node.names
    }


@pytest.mark.parametrize("literal,name", [(SENTENCE, "GROUP_WRITE_CONFLICT_MESSAGE"), (CODE, "GROUP_WRITE_CONFLICT_CODE")])
def test_each_literal_is_defined_once_in_functions_group(modules, literal, name):
    found = [
        (module_name, node.lineno) for module_name, tree in modules.items()
        for node in string_constants(tree) if node.value == literal
    ]
    assert [module_name for module_name, _line in found] == ["functions_group.py"], found
    value = module_assignment(modules["functions_group.py"], name)
    assert isinstance(value, ast.Constant) and value.value == literal


def test_no_other_group_conflict_sentence_exists(modules):
    sentences = {
        node.value for tree in modules.values() for node in string_constants(tree)
        if node.value.startswith("The group changed while")
    }
    assert sentences == {SENTENCE}


def test_the_constants_sit_beside_the_conflict_exception(modules):
    body = modules["functions_group.py"].body
    names = [
        node.name if isinstance(node, ast.ClassDef) else
        next((t.id for t in node.targets if isinstance(t, ast.Name)), None) if isinstance(node, ast.Assign) else None
        for node in body
    ]
    exception = names.index("GroupDocumentWriteConflict")
    assert names[exception + 1:exception + 3] == ["GROUP_WRITE_CONFLICT_CODE", "GROUP_WRITE_CONFLICT_MESSAGE"]


@pytest.mark.parametrize("module_name", [
    "functions_group_directory.py", "functions_group_membership.py", "functions_group_endpoint_access.py",
    "functions_group_settings.py", "route_backend_retention_policy.py",
])
def test_the_group_modules_import_the_constants(modules, module_name):
    assert {"GROUP_WRITE_CONFLICT_CODE", "GROUP_WRITE_CONFLICT_MESSAGE"} <= imports_from(modules[module_name], "functions_group")


@pytest.mark.parametrize("module_name,name", [
    ("functions_group_membership.py", "WRITE_CONFLICT_MESSAGE"),
    ("functions_group_endpoint_access.py", "GROUP_ENDPOINT_WRITE_CONFLICT_MESSAGE"),
])
def test_the_older_names_are_the_constant_itself(modules, module_name, name):
    value = module_assignment(modules[module_name], name)
    assert isinstance(value, ast.Name) and value.id == "GROUP_WRITE_CONFLICT_MESSAGE"


def test_the_classic_group_routes_answer_with_the_constants(modules):
    tree = modules["route_backend_groups.py"]
    assert any(
        isinstance(node, ast.ImportFrom) and node.module == "functions_group" and node.names[0].name == "*"
        for node in tree.body
    )
    response = module_assignment(tree, "GROUP_WRITE_CONFLICT_RESPONSE")
    assert {ast.literal_eval(key): value.id for key, value in zip(response.keys, response.values)} == {
        "error": "GROUP_WRITE_CONFLICT_MESSAGE", "error_code": "GROUP_WRITE_CONFLICT_CODE",
    }


def test_the_v2_client_fallback_is_the_same_sentence():
    source = (ROOT / "application" / "v2_ui" / "src" / "lib" / "modelConnections.ts").read_text(encoding="utf-8")
    start = source.index("export class GroupWriteConflictError")
    assert f"constructor(message = '{SENTENCE}')" in source[start:start + 300]


def test_the_browser_fixtures_carry_the_same_sentence():
    workspace = parse(ROOT / "ui_tests" / "fixtures" / "group_workspace.py")
    assert ast.literal_eval(module_assignment(workspace, "GROUP_WRITE_CONFLICT_ERROR")) == SENTENCE
    members = parse(ROOT / "ui_tests" / "fixtures" / "group_members.py")
    reader = module_assignment(members, "WRITE_CONFLICT_MESSAGE")
    assert isinstance(reader, ast.Call) and reader.func.id == "_app_constant"
    assert [ast.literal_eval(arg) for arg in reader.args] == ["functions_group.py", "GROUP_WRITE_CONFLICT_MESSAGE"]
