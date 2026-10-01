#!/usr/bin/env python3
# test_orchestration_workflow_run_imports.py
"""
Functional test for cold imports of the chat workflow run modules.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that the workflow run module and its links module load in fresh normal and
optimized interpreters in the orders the application uses: during the web bootstrap, between the
settings module and the orchestration routes, after the scheduler that runs background
continuations, before and after the plan schema, and with the links module first. Each order then
resolves every import made inside a function of the run or links module, and every one into the
run module, as a run step, the queue and the links would. Only Cosmos DB is doubled; every
network socket is blocked. It also checks that the schema reaches the run module only to check a
run step, so naming a plan's workflows does not import the run module back.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
RUNS_MODULE = "functions_orchestration_workflow_runs"
PROBE = r'''
import ast
import importlib
from pathlib import Path
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

RUNS_MODULE = "functions_orchestration_workflow_runs"
LINKS_MODULE = "functions_orchestration_workflow_run_links"


def lazy_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        (node.module, alias.name)
        for function in ast.walk(tree) if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function) if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }


with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    runs = importlib.import_module(RUNS_MODULE)
    links = importlib.import_module(LINKS_MODULE)
    schema = importlib.import_module("functions_orchestration_schema")
    if runs.workflow_run_catalog_entry is not schema.workflow_run_catalog_entry:
        raise AssertionError("The run checks and the approval card resolved different catalog lookups")
    if links.started_workflow_run_id is not runs.started_workflow_run_id:
        raise AssertionError("The links resolved a different run module")
    app_dir = Path(sys.argv[1])
    edges = set()
    for path in sorted(app_dir.glob("functions_orchestration_*.py")):
        edges |= {
            edge for edge in lazy_imports(path)
            if path.stem in (RUNS_MODULE, LINKS_MODULE) or edge[0] == RUNS_MODULE
        }
    if not any(module == RUNS_MODULE for module, _ in edges) or not any(module != RUNS_MODULE for module, _ in edges):
        raise AssertionError("The lazy imports into and out of the run modules were not found")
    for module, attribute in sorted(edges):
        if not hasattr(importlib.import_module(module), attribute):
            raise AssertionError(f"A lazy import of {module}.{attribute} does not resolve")
    if "route_backend_orchestration" in sys.argv[3:]:
        route = importlib.import_module("route_backend_orchestration")
        if route._workflow_run_links() is not links:
            raise AssertionError("The routes resolved a different links module")
    if "app" in sys.argv[3:] and not hasattr(importlib.import_module("app"), "app"):
        raise AssertionError("The web bootstrap did not complete")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: workflow run modules cold imports")
'''


def run_probe(order, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        command + ["-c", PROBE, str(APP), str(TESTS), *order],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", [
    ("app",),
    ("functions_settings", RUNS_MODULE, "route_backend_orchestration"),
    ("functions_orchestration_scheduler",),
    ("functions_orchestration_schema", RUNS_MODULE),
    (RUNS_MODULE, "functions_orchestration_schema"),
    ("functions_orchestration_workflow_run_links",),
], ids=lambda order: "+".join(name.removeprefix("functions_orchestration_") for name in order))
def test_the_run_modules_load_in_every_application_import_order(order, optimized):
    run_probe(order, optimized)


def _module(name):
    return ast.parse((APP / f"{name}.py").read_text(encoding="utf-8"))


def _functions(tree):
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_the_schema_reaches_the_run_module_only_to_check_a_run_step():
    schema = _module("functions_orchestration_schema")
    runs = _module(RUNS_MODULE)
    reached = [
        (alias.name, node in schema.body)
        for node in ast.walk(schema)
        if isinstance(node, ast.ImportFrom) and node.module == RUNS_MODULE
        for alias in node.names
    ]
    assert reached == [("prepare_workflow_run_arguments", False)]
    # One catalog lookup, in the schema, which the run module imports at load time.
    assert "workflow_run_catalog_entry" in _functions(schema)
    assert "workflow_run_catalog_entry" not in _functions(runs)
    assert any(
        isinstance(node, ast.ImportFrom) and node.module == "functions_orchestration_schema"
        and "workflow_run_catalog_entry" in {alias.name for alias in node.names}
        for node in runs.body
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
