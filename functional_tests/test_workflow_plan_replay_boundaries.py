#!/usr/bin/env python3
# test_workflow_plan_replay_boundaries.py
"""
Functional test for the workflow plan replay import and scheduler boundaries.
Version: 0.261.305
Implemented in: 0.261.305

This test ensures that the plan replay module never imports the web layer, so a scheduled run
cannot reach request state, and that the runner, the personal and group workflow stores and the
orchestration routes reach it only from inside a function. Fresh normal and optimized interpreters
load it in the orders the application uses, then resolve every import made inside a function into
or out of it, with Cosmos DB doubled and every network socket blocked. It also checks that the
orchestration scheduler never drives a replay: the due-run query excludes it, and a replay that
reaches the scheduler anyway is deferred before any service is built or any lease is taken.

Checks use explicit raises, so they hold under ``python -O``.
"""

import ast
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
REPLAY_MODULE = "functions_workflow_plan_replay"

with patch.object(sys, "path", [str(APP), str(TESTS), *sys.path]):
    import functions_orchestration_scheduler as scheduler
    from test_orchestration_harness_execution import initialized_application  # noqa: F401
    from test_support.versioning import assert_app_version_at_least


PROBE = r'''
import ast
import importlib
from pathlib import Path
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

REPLAY = "functions_workflow_plan_replay"


def lazy_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.ImportFrom) and node.module:
                found |= {(node.module, alias.name) for alias in node.names}
            elif isinstance(node, ast.Import):
                found |= {(alias.name, None) for alias in node.names}
    return found


with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    # A save, a run and a chat request happen after the application loaded its settings.
    importlib.import_module("functions_settings")
    replay = importlib.import_module(REPLAY)
    runner = importlib.import_module("functions_workflow_runner")
    importlib.import_module("functions_personal_workflows")
    importlib.import_module("functions_group_workflows")
    routes = importlib.import_module("route_backend_orchestration")
    if routes._plan_replay() is not replay:
        raise AssertionError("The routes resolved a different replay module")
    if replay.PLAN_REPLAY_TASK_TYPE != "plan_replay":
        raise AssertionError("The replay task type changed")
    app_dir = Path(sys.argv[1])
    edges = set()
    for path in sorted([*app_dir.glob("functions_*.py"), *app_dir.glob("route_*.py")]):
        edges |= {
            edge for edge in lazy_imports(path)
            if path.stem == REPLAY or edge[0] == REPLAY
        }
    if not any(module == REPLAY for module, _ in edges):
        raise AssertionError("The lazy imports into the replay module were not found")
    if not any(module != REPLAY for module, _ in edges):
        raise AssertionError("The lazy imports out of the replay module were not found")
    for module, attribute in sorted(edges, key=lambda edge: (edge[0], edge[1] or "")):
        loaded = importlib.import_module(module)
        if attribute is not None and not hasattr(loaded, attribute):
            raise AssertionError(f"A lazy import of {module}.{attribute} does not resolve")
    if "app" in sys.argv[3:] and not hasattr(importlib.import_module("app"), "app"):
        raise AssertionError("The web bootstrap did not complete")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: workflow plan replay cold imports")
'''


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def test_version_includes_plan_replay():
    assert_app_version_at_least("0.261.305")


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
    ("functions_settings", REPLAY_MODULE, "route_backend_orchestration"),
    ("functions_settings", "route_backend_orchestration", REPLAY_MODULE),
    ("functions_settings", "functions_workflow_runner", REPLAY_MODULE),
    ("functions_orchestration_scheduler",),
], ids=lambda order: "+".join(name.removeprefix("functions_") for name in order))
def test_the_replay_module_loads_in_every_application_import_order(order, optimized):
    run_probe(order, optimized)


def _module(name):
    return ast.parse((APP / f"{name}.py").read_text(encoding="utf-8"))


def _imported_modules(tree):
    return {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}


def _imports_of(tree, module):
    """``(name, at_load_time)`` for each name ``tree`` imports from ``module``."""
    return sorted(
        (alias.name, node in tree.body)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    )


def test_the_replay_module_never_imports_the_web_layer():
    modules = _imported_modules(_module(REPLAY_MODULE))
    forbidden = sorted(
        name for name in modules
        if name.split(".")[0] in {"flask", "werkzeug", "app", "functions_authentication"}
        or name.startswith("route_")
    )
    require(not forbidden, f"The replay module imports the web layer: {forbidden}")


def test_the_application_reaches_the_replay_module_only_from_inside_a_function():
    expected = {
        "functions_workflow_runner": [("PLAN_REPLAY_TASK_TYPE", False), ("execute_plan_replay_task", False)],
        "functions_group_workflows": [("PlanReplaySaveError", False)],
    }
    for name, reached in expected.items():
        found = _imports_of(_module(name), REPLAY_MODULE)
        require(found == reached, f"{name} reaches the replay module as {found}, not {reached}")
    personal = _imports_of(_module("functions_personal_workflows"), REPLAY_MODULE)
    require(personal and not any(at_load for _name, at_load in personal),
            f"The personal store reaches the replay module as {personal}")
    routes = _module("route_backend_orchestration")
    owners = sorted(
        (owner.name if owner is not routes else "<module>")
        for owner in [routes, *(item for item in ast.walk(routes) if isinstance(item, ast.FunctionDef))]
        for node in (owner.body if owner is not routes else routes.body)
        if (isinstance(node, ast.Import) and any(alias.name == REPLAY_MODULE for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module == REPLAY_MODULE)
    )
    require(owners == ["_plan_replay"], f"The routes reach the replay module from {owners}")


def test_the_due_run_query_excludes_workflow_replays():
    class Container:
        def query_items(self, **kwargs):
            self.call = kwargs
            return iter(())

    container = Container()
    scheduler.enumerate_due_runs(container, now=datetime(2030, 1, 1, tzinfo=timezone.utc), limit=4)
    require(
        "AND (NOT IS_DEFINED(c.workflow_replay) OR IS_NULL(c.workflow_replay)) " in container.call["query"],
        "The scheduler's due-run query must never select a workflow plan replay.",
    )


def test_a_replay_that_reaches_the_scheduler_is_deferred_untouched(initialized_application):
    record = {
        "id": "run-1", "run_id": "run-1", "user_id": "owner", "conversation_id": "workflow-conversation",
        "planner_contract_version": 2, "status": "waiting",
        "plan": {"plan_id": "plan-1", "run_id": "run-1", "planner_contract_version": 2, "steps": []},
        "workflow_replay": {"workflow_id": "workflow-1", "workflow_run_id": "workflow-run-1", "task_id": "task-1"},
    }
    touched = []

    def must_not_build(*args, **kwargs):
        touched.append("services")
        raise AssertionError("The scheduler built services for a workflow replay")

    resources = scheduler.OrchestrationSchedulerResources(
        runs_container=None, messages_container=None, settings={},
        read_conversation=lambda user_id, conversation_id: {"id": conversation_id, "user_id": user_id},
        read_run=lambda run_id, user_id, conversation_id: dict(record),
        build_services=must_not_build, build_cleanup_service=must_not_build,
        log=lambda message, **kwargs: touched.append(("log", message)),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    tick = scheduler._Tick(resources)
    tick.process_run({"run_id": "run-1", "user_id": "owner", "conversation_id": "workflow-conversation"})
    require(tick.result["runs"] == [{
        "run_id": "run-1", "user_id": "owner", "conversation_id": "workflow-conversation",
        "action": "deferred", "state": "workflow_replay",
    }], tick.result)
    require(tick.result["ok"] and not tick.result["errors"], tick.result)
    require(touched == [], f"The scheduler touched a workflow replay: {touched}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:langsmith_plugin", "-p", "no:cacheprovider"]))
