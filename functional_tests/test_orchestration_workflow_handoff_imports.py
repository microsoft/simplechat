#!/usr/bin/env python3
# test_orchestration_workflow_handoff_imports.py
"""
Functional test for cold imports of the chat workflow hand-off modules.
Version: 0.261.233
Implemented in: 0.261.233

This test ensures that the workflow hand-off step module and the one-time workflow builder load in
fresh normal and optimized interpreters in the orders the application uses: during the web
bootstrap, between the settings module and the orchestration routes, after the scheduler that runs
background continuations, before and after the plan schema and the executor, and before and after
the draft service, with the builder loaded first. The hand-off decisions module behind the
accept-and-run routes loads after the settings module, before and after the routes, the step module
and the proposal decisions, and the routes' accessor returns that same module. Each order then
resolves every import made inside a function of a hand-off module, and every one into a hand-off
module, as a plan check, a step, a recovery, a decision and the reply would once the settings are
loaded. The draft service and the decisions module cannot load before the settings module on any
branch (a cycle through the document actions that predates hand-off), so the probe never loads
them first. Only Cosmos DB is doubled; every network socket is blocked. It also checks that the
schema, the executor, the reply, the planner and the step adapter reach the step module only from
inside a function, so loading any of them never imports the step module back, and that the proposal
decisions reach it the same way.

Checks use explicit raises, so they hold under ``python -O``.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
HANDOFFS_MODULE = "functions_orchestration_workflow_handoffs"
BUILDER_MODULE = "functions_workflow_handoff_builder"
DECISIONS_MODULE = "functions_orchestration_workflow_handoff_decisions"
PROPOSALS_MODULE = "functions_orchestration_workflow_proposals"
PROBE = r'''
import ast
import importlib
from pathlib import Path
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

HANDOFF_MODULES = (
    "functions_orchestration_workflow_handoffs",
    "functions_workflow_handoff_builder",
    "functions_orchestration_workflow_handoff_decisions",
)


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
    handoffs = importlib.import_module(HANDOFF_MODULES[0])
    builder = importlib.import_module(HANDOFF_MODULES[1])
    # A step, a plan check, a recovery, a decision and the reply run after the application loaded
    # its settings, and the draft service and the decisions load only after them, as they do in the
    # application.
    importlib.import_module("functions_settings")
    drafts = importlib.import_module("functions_workflow_drafts")
    schema = importlib.import_module("functions_orchestration_schema")
    registry = importlib.import_module("functions_orchestration_registry")
    decisions = importlib.import_module(HANDOFF_MODULES[2])
    proposals = importlib.import_module("functions_orchestration_workflow_proposals")
    workflow_runs = importlib.import_module("functions_orchestration_workflow_runs")
    routes = importlib.import_module("route_backend_orchestration")
    if drafts.build_handoff_definition is not builder.build_handoff_definition:
        raise AssertionError("The draft service resolved a different builder")
    if handoffs.WORKFLOW_HANDOFF_INVALID_CODE != schema.WORKFLOW_HANDOFF_INVALID_CODE:
        raise AssertionError("The step and the schema resolved different hand-off codes")
    if handoffs.CAPABILITY_WORKFLOW_HANDOFF != registry.CAPABILITY_WORKFLOW_HANDOFF:
        raise AssertionError("The step and the registry resolved different capability ids")
    if decisions.workflow_handoff_id is not handoffs.workflow_handoff_id:
        raise AssertionError("The decisions resolved a different hand-off id")
    if decisions.chat_delivery_seed_for is not workflow_runs.chat_delivery_seed_for:
        raise AssertionError("The decisions resolved a different chat delivery seed")
    if decisions.URL_ACCESS_NOTE != proposals.URL_ACCESS_NOTE:
        raise AssertionError("The decisions resolved a different URL access note")
    if routes._workflow_handoffs() is not decisions:
        raise AssertionError("The routes resolved a different decisions module")
    app_dir = Path(sys.argv[1])
    edges = set()
    for path in sorted(app_dir.glob("functions_*.py")):
        edges |= {
            edge for edge in lazy_imports(path)
            if path.stem in HANDOFF_MODULES or edge[0] in HANDOFF_MODULES
        }
    if not any(module in HANDOFF_MODULES for module, _ in edges):
        raise AssertionError("The lazy imports into the hand-off modules were not found")
    if not any(module not in HANDOFF_MODULES for module, _ in edges):
        raise AssertionError("The lazy imports out of the hand-off modules were not found")
    for module, attribute in sorted(edges):
        if not hasattr(importlib.import_module(module), attribute):
            raise AssertionError(f"A lazy import of {module}.{attribute} does not resolve")
    if "app" in sys.argv[3:] and not hasattr(importlib.import_module("app"), "app"):
        raise AssertionError("The web bootstrap did not complete")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: workflow hand-off modules cold imports")
'''


def run_probe(order, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        command + ["-c", PROBE, str(APP), str(TESTS), *order],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if process.returncode != 0 or "PASS:" not in process.stdout:
        raise AssertionError(process.stdout[-8000:] + process.stderr[-8000:])


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", [
    ("app",),
    ("functions_settings", HANDOFFS_MODULE, "route_backend_orchestration"),
    ("functions_orchestration_scheduler",),
    ("functions_orchestration_schema", HANDOFFS_MODULE),
    (HANDOFFS_MODULE, "functions_orchestration_schema"),
    ("functions_orchestration_executor", HANDOFFS_MODULE),
    (BUILDER_MODULE, "functions_settings", "functions_workflow_drafts"),
    ("functions_settings", "functions_workflow_drafts", BUILDER_MODULE),
    ("functions_settings", DECISIONS_MODULE, "route_backend_orchestration"),
    ("functions_settings", "route_backend_orchestration", DECISIONS_MODULE),
    ("functions_settings", HANDOFFS_MODULE, DECISIONS_MODULE),
    ("functions_settings", DECISIONS_MODULE, HANDOFFS_MODULE),
    ("functions_settings", PROPOSALS_MODULE, DECISIONS_MODULE),
    ("functions_settings", DECISIONS_MODULE, PROPOSALS_MODULE),
], ids=lambda order: "+".join(
    name.removeprefix("functions_orchestration_").removeprefix("functions_") for name in order
))
def test_the_hand_off_modules_load_in_every_application_import_order(order, optimized):
    run_probe(order, optimized)


def _module(name):
    return ast.parse((APP / f"{name}.py").read_text(encoding="utf-8"))


def _imports_of(tree, module):
    """``(name, at_load_time)`` for each name ``tree`` imports from ``module``."""
    return sorted(
        (alias.name, node in tree.body)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    )


def test_the_plan_modules_reach_the_step_module_only_from_inside_a_function():
    expected = {
        "functions_orchestration_schema": [("prepare_workflow_handoff_arguments", False)],
        "functions_orchestration_executor": [("rebuild_workflow_handoff", False)],
        "functions_orchestration_execution": [("workflow_handoff_note", False)],
        "functions_orchestration_adapters": [("adapter_workflow_handoff", False)],
    }
    for name, reached in expected.items():
        found = _imports_of(_module(name), HANDOFFS_MODULE)
        if found != reached:
            raise AssertionError(f"{name} reaches the step module as {found}, not {reached}")
    planner = _imports_of(_module("functions_orchestration_planner"), HANDOFFS_MODULE)
    if not planner or any(at_load for _name, at_load in planner):
        raise AssertionError(f"The planner reaches the step module as {planner}")
    proposals = _imports_of(_module(PROPOSALS_MODULE), HANDOFFS_MODULE)
    if proposals != [("workflow_handoff_id", False)]:
        raise AssertionError(f"The proposal decisions reach the step module as {proposals}")


def test_the_routes_reach_the_decisions_module_only_through_their_accessor():
    tree = _module("route_backend_orchestration")
    found = sorted(
        (owner.name if owner is not tree else "<module>")
        for owner in [tree, *(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef))]
        for node in (owner.body if owner is not tree else tree.body)
        if (isinstance(node, ast.Import) and any(alias.name == DECISIONS_MODULE for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module == DECISIONS_MODULE)
    )
    if found != ["_workflow_handoffs"]:
        raise AssertionError(f"The routes reach the decisions module from {found}")


def test_the_builder_imports_no_application_service():
    tree = _module(BUILDER_MODULE)
    modules = sorted(
        {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    )
    if modules != ["copy", "functions_workflow_limits", "functions_workflow_loop_schema"]:
        raise AssertionError(f"The builder imports {modules}")
    context = _module("functions_orchestration_workflow_context")
    reached = _imports_of(context, BUILDER_MODULE)
    if not reached or any(at_load for _name, at_load in reached):
        raise AssertionError(f"The planning context reaches the builder as {reached}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
