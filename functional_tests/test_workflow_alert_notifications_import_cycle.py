#!/usr/bin/env python3
# test_workflow_alert_notifications_import_cycle.py
"""
Functional test for the import cycle CodeQL reports on functions_notifications.
Version: 0.261.235
Implemented in: 0.261.235

functions_notifications imports functions_group at module level, as it did before 0.261.235, and
from 0.261.235 also functions_group_workflow_policy and functions_workflow_alerts, for the
acknowledgment route and the workflow alert pop-up read. CodeQL's py/cyclic-import counts imports
made inside functions too, so it reports the chain functions_notifications -> functions_group ->
functions_settings -> content_screening.service -> functions_notifications. That chain closes only
through imports made when a function runs, so it can't fail while modules load.

This test ensures it stays that way: no module-level import cycle passes through
functions_notifications, and the real modules load cold, offline, in each order the application
reaches them (the web routes, the scheduler's workflow runner, settings, screening and the group
helpers first), with and without -O, binding the real group checks.
"""

import ast
import functools
import subprocess
import sys
from collections import deque
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(TESTS))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


NOTIFICATIONS = "functions_notifications"


def _module_name(path):
    dotted = ".".join(path.relative_to(APP).with_suffix("").parts)
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


def _module_level_imports(module, tree):
    """Dotted names imported while the module loads: its body, branches and classes, not functions."""
    package = module if (APP / Path(*module.split(".")) / "__init__.py").is_file() else module.rpartition(".")[0]
    found = []

    def resolve(node):
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        if not isinstance(node, ast.ImportFrom):
            return []
        if node.level:
            parts = package.split(".") if package else []
            base = ".".join(parts[: len(parts) - (node.level - 1)])
            prefix = f"{base}.{node.module}" if node.module else base
        else:
            prefix = node.module or ""
        return [prefix] + [f"{prefix}.{alias.name}" for alias in node.names]

    def walk(nodes):
        for node in nodes:
            found.extend(resolve(node))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            children = []
            for field in ("body", "orelse", "finalbody"):
                children.extend(getattr(node, field, None) or [])
            for handler in getattr(node, "handlers", None) or []:
                children.extend(handler.body)
            walk(children)

    walk(tree.body)
    return found


@functools.lru_cache(maxsize=1)
def _module_level_graph():
    modules = {_module_name(path): path for path in APP.rglob("*.py") if "__pycache__" not in path.parts}
    edges = {}
    for module, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        targets = set()
        for name in _module_level_imports(module, tree):
            # Importing a.b.c loads a and a.b first.
            parts = name.split(".")
            for end in range(1, len(parts) + 1):
                candidate = ".".join(parts[:end])
                if candidate in modules and candidate != module:
                    targets.add(candidate)
        edges[module] = targets
    return edges


def _module_level_cycle_through(edges, start):
    """A module-level import path from start back to itself, or None."""
    queue, seen = deque([[start]]), set()
    while queue:
        path = queue.popleft()
        for target in sorted(edges.get(path[-1], ())):
            if target == start:
                return path + [start]
            if target not in seen:
                seen.add(target)
                queue.append(path + [target])
    return None


def test_the_import_check_ships_in_this_version():
    assert_app_version_at_least("0.261.235")


def test_no_module_level_import_cycle_passes_through_notifications():
    edges = _module_level_graph()
    # The modules this release imports at module level are still reached that way.
    assert {"functions_group", "functions_group_workflow_policy", "functions_workflow_alerts"} <= edges[NOTIFICATIONS]
    cycle = _module_level_cycle_through(edges, NOTIFICATIONS)
    assert cycle is None, "A module-level import cycle passes through functions_notifications: " + " -> ".join(cycle)


# ---------------------------------------------------------------------------
# Cold imports
# ---------------------------------------------------------------------------

PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3].split(","):
        importlib.import_module(name)
    notifications = importlib.import_module("functions_notifications")
    group = importlib.import_module("functions_group")
    policy = importlib.import_module("functions_group_workflow_policy")
    # The acknowledgment and the pop-up read check membership with the real group helpers.
    if notifications.get_user_groups is not group.get_user_groups:
        raise AssertionError("functions_notifications.get_user_groups is not functions_group's")
    if notifications.assert_group_role is not group.assert_group_role:
        raise AssertionError("functions_notifications.assert_group_role is not functions_group's")
    if notifications.GROUP_WORKFLOW_MEMBER_ROLES is not policy.GROUP_WORKFLOW_MEMBER_ROLES:
        raise AssertionError("functions_notifications has its own group workflow member roles")
    for attribute in ("acknowledge_workflow_alert", "get_workflow_alert_popups", "create_workflow_priority_notification"):
        if not callable(getattr(notifications, attribute, None)):
            raise AssertionError(f"functions_notifications.{attribute} is missing")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: workflow alert notification cold imports")
'''

ORDERS = {
    "notifications-first": "functions_notifications,functions_group,functions_workflow_alerts,content_screening.service",
    "group-first": "functions_group,functions_notifications",
    "settings-first": "functions_settings,functions_notifications",
    "screening-first": "content_screening.service,functions_notifications",
    "workflow-alerts-first": "functions_workflow_alerts,functions_notifications",
    "scheduler-runner-first": "functions_workflow_runner",
    "web-routes-first": "route_backend_notifications",
}


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", list(ORDERS.values()), ids=list(ORDERS))
def test_the_modules_load_cold_offline_in_either_order(order, optimized):
    command = [sys.executable, "-B", *(["-O"] if optimized else []), "-c", PROBE, str(APP), str(TESTS), order]
    process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
