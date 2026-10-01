#!/usr/bin/env python3
# test_workflow_result_privacy_import_cycle.py
"""
Functional test for where saved analysis and Follow up find the chat privacy check.
Version: 0.261.214
Implemented in: 0.261.214

This test ensures that saved analysis and Follow up ask whether a chat is private through the
orchestration memory module, which defines the check beside the audience rule it relies on,
instead of through the workflow planning context, whose imports reach back to saved analysis and
closed an import cycle. Both imports stay lazy, the planning context reuses the one definition,
the memory module imports none of the modules that ask it, and each module still loads cold in
either order, with and without -O, without any network access.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(TESTS))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


MEMORY = "functions_orchestration_memory"
PLANNING_CONTEXT = "functions_orchestration_workflow_context"
CHECK = "conversation_is_private"
# Saved analysis, the Follow up modules and the planning context. The memory module imports none of
# them, so asking it whether a chat is private can't close an import cycle.
CALLER_SIDE = {
    "functions_saved_analysis",
    "functions_workflow_result_followup",
    "functions_workflow_result_reader",
    "functions_workflow_result_masking",
    PLANNING_CONTEXT,
}


def _tree(module):
    return ast.parse((APP / f"{module}.py").read_text(encoding="utf-8"))


def _definition(tree, *qualname):
    nodes, found = tree.body, None
    for name in qualname:
        found = next((
            node for node in nodes
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ), None)
        if found is None:
            return None
        nodes = found.body
    return found


def _sources_of(node, name):
    """The module of every `from <module> import <name>` under node, in source order."""
    return [
        child.module for child in ast.walk(node)
        if isinstance(child, ast.ImportFrom) and any(alias.name == name for alias in child.names)
    ]


def _imported_modules(tree):
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_the_move_ships_in_this_version():
    assert_app_version_at_least("0.261.214")


@pytest.mark.parametrize("module, qualname", [
    ("functions_saved_analysis", ("_WorkflowResultLineage", "_private")),
    ("functions_workflow_result_followup", ("_default_is_private",)),
], ids=["saved-analysis", "follow-up"])
def test_the_privacy_check_is_imported_lazily_from_the_memory_module(module, qualname):
    tree = _tree(module)
    function = _definition(tree, *qualname)
    assert function is not None, f"{module}.{'.'.join(qualname)} moved"
    assert _sources_of(function, CHECK) == [MEMORY]
    # The whole file holds that one import, so it is still made only when a chat is checked.
    assert _sources_of(tree, CHECK) == [MEMORY]
    assert PLANNING_CONTEXT not in _imported_modules(tree)


def test_the_planning_context_reuses_the_memory_definition():
    memory = _tree(MEMORY)
    context = _tree(PLANNING_CONTEXT)
    definitions = [node.name for node in memory.body if isinstance(node, ast.FunctionDef) and node.name == CHECK]
    assert definitions == [CHECK]
    assert _definition(context, CHECK) is None
    module_level = [
        node.module for node in context.body
        if isinstance(node, ast.ImportFrom) and any(alias.name == CHECK for alias in node.names)
    ]
    assert module_level == [MEMORY]


def test_the_memory_module_imports_nothing_from_the_caller_side():
    assert not _imported_modules(_tree(MEMORY)) & CALLER_SIDE


# ---------------------------------------------------------------------------
# Cold imports
# ---------------------------------------------------------------------------

PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

MEMORY = "functions_orchestration_memory"
PLANNING_CONTEXT = "functions_orchestration_workflow_context"
CALLERS = ("functions_saved_analysis", "functions_workflow_result_followup", PLANNING_CONTEXT)
OWNER = "owner-1"
CHATS = {
    "private": {"id": "private", "user_id": OWNER},
    "converted": {"id": "converted", "user_id": OWNER, "converted_to_collaboration_at": "2026-06-02T09:02:00Z"},
    "shared": {"id": "shared", "user_id": OWNER, "collaboration_conversation_id": "collaboration-1"},
    "someone_else": {"id": "someone_else", "user_id": "someone-else"},
}
EXPECTED = {"private": True, "converted": False, "shared": False, "someone_else": False}


def check(label, is_private):
    answers = {chat: is_private(chat) for chat in CHATS}
    if answers != EXPECTED:
        raise AssertionError(f"{label} answered {answers}")


with offline_app_imports() as environment:
    if sys.argv[3] == "memory":
        memory = importlib.import_module(MEMORY)
        check(MEMORY, lambda chat: memory.conversation_is_private(CHATS[chat], OWNER))
        loaded = [name for name in CALLERS if name in sys.modules]
        if loaded:
            raise AssertionError(f"The memory module loaded {loaded}")
    else:
        for name in sys.argv[3].split(","):
            module = importlib.import_module(name)
            context_was_loaded = PLANNING_CONTEXT in sys.modules
            if name == "functions_saved_analysis":
                lineage = module._WorkflowResultLineage(
                    OWNER, result_reader=lambda *args, **kwargs: None, conversation_reader=CHATS.__getitem__,
                )
                check(name, lineage._private)
            elif name == "functions_workflow_result_followup":
                check(name, lambda chat: module._default_is_private(CHATS[chat], OWNER))
            if MEMORY not in sys.modules:
                raise AssertionError(f"{name} checked a chat without the memory module")
            if not context_was_loaded and PLANNING_CONTEXT in sys.modules:
                raise AssertionError(f"{name} loaded the workflow planning context to check a chat")
        if sys.modules[PLANNING_CONTEXT].conversation_is_private is not sys.modules[MEMORY].conversation_is_private:
            raise AssertionError("The workflow planning context has its own privacy check")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: privacy check cold imports")
'''

ORDERS = {
    "memory-alone": "memory",
    "callers-first": "functions_saved_analysis,functions_workflow_result_followup,functions_orchestration_workflow_context",
    "planning-context-first": "functions_orchestration_workflow_context,functions_workflow_result_followup,functions_saved_analysis",
}


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", list(ORDERS.values()), ids=list(ORDERS))
def test_each_module_loads_cold_and_checks_privacy_in_either_order(order, optimized):
    command = [sys.executable, "-B", *(["-O"] if optimized else []), "-c", PROBE, str(APP), str(TESTS), order]
    process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
