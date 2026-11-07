#!/usr/bin/env python3
# test_orchestration_workflow_results_imports.py
"""
Functional test for cold imports of the chat workflow results module.
Version: 0.261.217
Implemented in: 0.261.217

This test ensures that the workflow results module loads in fresh normal and optimized
interpreters in the orders the application uses: during the web bootstrap, between settings and
the orchestration routes, after the scheduler that runs background continuations, before and after
the plan schema and workflow context, before and after the Phase 6a follow-up module, and through
the adapters registry. Each order resolves every function-local import into or out of the results
module and checks shared symbols keep a single identity. Only Cosmos DB is doubled; every network
socket is blocked. It also pins the reader and follow-up modules as lazy runtime dependencies, and
statically checks that the schema and orchestration callers reach the results module only from
function bodies.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(TESTS))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


RESULTS_MODULE = "functions_orchestration_workflow_results"
READER_MODULE = "functions_workflow_result_reader"
FOLLOWUP_MODULE = "functions_workflow_result_followup"
PROBE = r'''
import ast
import importlib
from pathlib import Path
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

RESULTS_MODULE = "functions_orchestration_workflow_results"
READER_MODULE = "functions_workflow_result_reader"
FOLLOWUP_MODULE = "functions_workflow_result_followup"


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
    results = importlib.import_module(RESULTS_MODULE)
    schema = importlib.import_module("functions_orchestration_schema")
    workflow_context = importlib.import_module("functions_orchestration_workflow_context")
    registry = importlib.import_module("functions_orchestration_registry")
    adapters = importlib.import_module("functions_orchestration_adapters")
    if results.workflow_run_catalog_entry is not schema.workflow_run_catalog_entry:
        raise AssertionError("The results checks and the approval card resolved different catalog lookups")
    if results.refresh_workflow_planning_privacy is not workflow_context.refresh_workflow_planning_privacy:
        raise AssertionError("The results module resolved a different workflow privacy refresher")
    if results.workflow_results_gate is not workflow_context.workflow_results_gate:
        raise AssertionError("The results module resolved a different workflow results gate")
    if results.resolve_turn_time_zone is not workflow_context.resolve_turn_time_zone:
        raise AssertionError("The results module resolved a different turn time zone resolver")
    if results.CAPABILITY_WORKFLOW_RESULTS != registry.CAPABILITY_WORKFLOW_RESULTS:
        raise AssertionError("The results module and registry resolved different capability names")
    if registry.CAPABILITY_WORKFLOW_RESULTS != "workflow_results":
        raise AssertionError("The workflow results capability name changed")
    if adapters.ADAPTER_REGISTRY[registry.CAPABILITY_WORKFLOW_RESULTS] is not adapters.run_workflow_results:
        raise AssertionError("The adapters registry resolved a different workflow results adapter")
    app_dir = Path(sys.argv[1])
    edges = set()
    for path in sorted(app_dir.glob("functions_orchestration_*.py")):
        edges |= {
            edge for edge in lazy_imports(path)
            if path.stem == RESULTS_MODULE or edge[0] == RESULTS_MODULE
        }
    if not any(module == RESULTS_MODULE for module, _ in edges):
        raise AssertionError("The lazy imports into the results module were not found")
    for required in (READER_MODULE, FOLLOWUP_MODULE, "config"):
        if not any(module == required for module, _ in edges):
            raise AssertionError(f"The lazy imports out of the results module to {required} were not found")
    for module, attribute in sorted(edges):
        if not hasattr(importlib.import_module(module), attribute):
            raise AssertionError(f"A lazy import of {module}.{attribute} does not resolve")
    reader = importlib.import_module(READER_MODULE)
    if results._reader_unavailable_type() is not reader.WorkflowResultUnavailable:
        raise AssertionError("The results module resolved a different workflow result reader exception")
    if "app" in sys.argv[3:] and not hasattr(importlib.import_module("app"), "app"):
        raise AssertionError("The web bootstrap did not complete")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: workflow results module cold imports")
'''

LAZY_RUNTIME_PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

RESULTS_MODULE = "functions_orchestration_workflow_results"
READER_MODULE = "functions_workflow_result_reader"
FOLLOWUP_MODULE = "functions_workflow_result_followup"
CALLERS = (
    "functions_orchestration_adapters",
    "functions_orchestration_schema",
    "functions_orchestration_planner",
    "functions_orchestration_execution",
    "functions_orchestration_composition",
    "functions_orchestration_executor",
    "functions_orchestration_scheduler",
    "route_backend_orchestration",
)


def require_absent(stage):
    loaded = [
        name for name in (RESULTS_MODULE, READER_MODULE, FOLLOWUP_MODULE)
        if name in sys.modules
    ]
    if loaded:
        raise AssertionError(f"{stage} loaded lazy workflow results modules too early: {loaded}")


with offline_app_imports() as environment:
    for name in CALLERS:
        importlib.import_module(name)
        require_absent(name)
    results = importlib.import_module(RESULTS_MODULE)
    for name in (READER_MODULE, FOLLOWUP_MODULE):
        if name in sys.modules:
            raise AssertionError(f"Importing the results module eagerly loaded {name}")
    nonce = results._new_nonce()
    if not isinstance(nonce, str) or not nonce:
        raise AssertionError("The workflow result fence nonce wrapper did not return a non-empty string")
    if FOLLOWUP_MODULE not in sys.modules:
        raise AssertionError("The nonce wrapper did not lazy-load the workflow result follow-up module")
    if environment.network_attempts:
        raise AssertionError("A lazy runtime import swallowed a network attempt")
print("PASS: workflow results lazy runtime imports")
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


def run_lazy_runtime_probe(optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        command + ["-c", LAZY_RUNTIME_PROBE, str(APP), str(TESTS)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


def _module(name):
    return ast.parse((APP / f"{name}.py").read_text(encoding="utf-8"))


def _functions(tree):
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _function_node_ids(tree):
    return {
        id(child)
        for function in ast.walk(tree) if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for child in ast.walk(function)
    }


def _imports_module(node, module_name):
    if isinstance(node, ast.ImportFrom):
        return node.module == module_name
    if isinstance(node, ast.Import):
        return any(alias.name == module_name for alias in node.names)
    return False


def _imports_any_module(node, module_names):
    return any(_imports_module(node, module_name) for module_name in module_names)


def _import_nodes(tree):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]


def test_version_is_at_least_workflow_results_imports_release():
    assert_app_version_at_least("0.261.217")


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", [
    ("app",),
    ("functions_settings", RESULTS_MODULE, "route_backend_orchestration"),
    ("functions_orchestration_scheduler",),
    ("functions_orchestration_schema", RESULTS_MODULE),
    (RESULTS_MODULE, "functions_orchestration_schema"),
    ("functions_orchestration_workflow_context", RESULTS_MODULE),
    (RESULTS_MODULE, "functions_orchestration_workflow_context"),
    (FOLLOWUP_MODULE, RESULTS_MODULE),
    (RESULTS_MODULE, FOLLOWUP_MODULE),
    ("functions_orchestration_adapters",),
], ids=lambda order: "+".join(name.removeprefix("functions_orchestration_") for name in order))
def test_the_results_module_loads_in_every_application_import_order(order, optimized):
    run_probe(order, optimized)


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
def test_the_results_reader_and_followup_stay_lazy_until_runtime_wrappers(optimized):
    run_lazy_runtime_probe(optimized)


def test_the_schema_reaches_the_results_module_only_to_prepare_results_arguments():
    schema = _module("functions_orchestration_schema")
    results = _module(RESULTS_MODULE)
    reached = [
        (alias.name, node in schema.body)
        for node in ast.walk(schema)
        if isinstance(node, ast.ImportFrom) and node.module == RESULTS_MODULE
        for alias in node.names
    ]
    assert reached == [("prepare_workflow_results_arguments", False)]
    assert "workflow_run_catalog_entry" in _functions(schema)
    assert "workflow_run_catalog_entry" not in _functions(results)
    assert any(
        isinstance(node, ast.ImportFrom) and node.module == "functions_orchestration_schema"
        and "workflow_run_catalog_entry" in {alias.name for alias in node.names}
        for node in results.body
    )


def test_no_application_module_imports_results_at_module_level():
    module_level_imports = []
    lazy_importers = set()
    for path in sorted(APP.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function_ids = _function_node_ids(tree)
        for node in _import_nodes(tree):
            if not _imports_module(node, RESULTS_MODULE):
                continue
            if id(node) in function_ids:
                lazy_importers.add(path.stem)
            else:
                module_level_imports.append(path.name)

    assert module_level_imports == []
    assert {
        "functions_orchestration_schema",
        "functions_orchestration_planner",
        "functions_orchestration_execution",
        "functions_orchestration_composition",
        "functions_orchestration_executor",
        "functions_orchestration_adapters",
    } <= lazy_importers


def test_results_runtime_dependencies_are_imported_only_inside_functions():
    results = _module(RESULTS_MODULE)
    function_ids = _function_node_ids(results)
    dependencies = {READER_MODULE, FOLLOWUP_MODULE, "config"}
    module_level_imports = [
        node for node in _import_nodes(results)
        if _imports_any_module(node, dependencies) and id(node) not in function_ids
    ]
    lazy_imports = {
        node.module
        for node in _import_nodes(results)
        if isinstance(node, ast.ImportFrom)
        and node.module in dependencies
        and id(node) in function_ids
    }
    lazy_imports |= {
        alias.name
        for node in _import_nodes(results)
        if isinstance(node, ast.Import)
        and id(node) in function_ids
        for alias in node.names
        if alias.name in dependencies
    }

    assert module_level_imports == []
    assert dependencies <= lazy_imports


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
