# test_orchestration_collaboration_codeql_alerts.py
#!/usr/bin/env python3
"""
Functional test for shared Orchestrate CodeQL alert remediation.
Version: 0.261.270
Implemented in: 0.261.270

This test ensures that the shared Orchestrate collaboration helpers keep the
CodeQL fixes for tuple arity and a single collaboration import style, and that
the real modules, whose collaboration imports are deliberately lazy, load cold
and offline in either order, in normal and optimized Python.
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


COLLABORATION = "functions_collaboration"
ORCHESTRATION_COLLABORATION = "functions_orchestration_collaboration"


def _tree(module):
    return ast.parse((APP / f"{module}.py").read_text(encoding="utf-8-sig"))


def _function(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} was not found")


def _return_tuple_lengths(function):
    lengths = []
    for node in ast.walk(function):
        if isinstance(node, ast.Return):
            value = node.value
            if isinstance(value, ast.Tuple):
                lengths.append(len(value.elts))
            else:
                lengths.append(None)
    return lengths


def test_the_codeql_remediation_ships_in_this_version():
    assert_app_version_at_least("0.261.270")


def test_mirror_source_message_to_collaboration_returns_three_values():
    """Callers unpack (message, conversation, created) from every return path."""
    tree = _tree(COLLABORATION)
    lengths = _return_tuple_lengths(_function(tree, "mirror_source_message_to_collaboration"))

    assert lengths and all(length == 3 for length in lengths), lengths


def test_save_collaboration_message_doc_returns_two_values():
    tree = _tree(COLLABORATION)
    lengths = _return_tuple_lengths(_function(tree, "_save_collaboration_message_doc"))

    assert lengths and all(length == 2 for length in lengths), lengths


def test_orchestration_collaboration_uses_one_collaboration_import_style():
    tree = _tree(ORCHESTRATION_COLLABORATION)

    module_imports = [
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == COLLABORATION
    ]
    top_level_from_imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == COLLABORATION
    ]

    assert module_imports == []
    assert top_level_from_imports == []


PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3].split(","):
        module = importlib.import_module(name)
        if name == "functions_collaboration" and not callable(getattr(module, "mirror_source_message_to_collaboration", None)):
            raise AssertionError("functions_collaboration mirror helper is missing")
        if name == "functions_orchestration_collaboration" and not callable(getattr(module, "delete_orchestration_backing", None)):
            raise AssertionError("functions_orchestration_collaboration delete helper is missing")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: shared Orchestrate collaboration cold imports")
'''


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", [
    "functions_orchestration_collaboration,functions_collaboration",
    "functions_collaboration,functions_orchestration_collaboration",
], ids=["orchestration-first", "collaboration-first"])
def test_real_modules_load_cold_offline_in_either_order(order, optimized):
    command = [sys.executable, "-B", *(["-O"] if optimized else []), "-c", PROBE, str(APP), str(TESTS), order]
    process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)

    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
