# test_v2_public_source_imports.py
"""Cold public-source imports, actual web/scheduler wiring and startup refusal.

Version: 0.261.373
Implemented in: 0.261.373
External I/O is blocked or stubbed by the existing offline bootstrap environment.
Real config, settings, storage-owner and consumer modules are never replaced.
"""

import ast
from pathlib import Path

import pytest

from test_orchestration_harness_execution import run_probe


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
PROBE = r'''
import importlib
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support import offline_bootstrap
from test_support.orchestration_harness_execution import project_session_cache
with patch.object(offline_bootstrap, "TemporaryDirectory", project_session_cache):
    with offline_bootstrap.offline_app_imports() as environment:
        for name in sys.argv[3:]:
            importlib.import_module(name)
        access = importlib.import_module("public_source_access")
        owner = importlib.import_module("functions_public_workspaces")
        web = importlib.import_module("app")
        scheduler = importlib.import_module("background_tasks")
        if access._resolver is not owner.get_public_source_workspace_ids:
            raise AssertionError("The real public storage owner did not configure discovery.")
        if not callable(scheduler.check_m365_workflow_continuations_once):
            raise AssertionError("The real scheduler did not initialize.")
        with web.app.test_request_context("/api/v2/scope"):
            ids = access.get_public_source_workspace_ids(
                "bootstrap-reader", settings={"enable_public_workspaces": False},
            )
        if ids != [] or environment.network_attempts:
            raise AssertionError("Discovery bypassed disabled settings or attempted external I/O.")
        with patch.object(access, "_resolver", None):
            try:
                access.get_public_source_workspace_ids("bootstrap-reader")
            except RuntimeError as error:
                if "not been initialized" not in str(error):
                    raise
            else:
                raise AssertionError("Uninitialized discovery silently succeeded.")
print("PASS: real public-source import and owner wiring")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_public_workspaces", "functions_search"),
    ("functions_search", "functions_public_workspaces"),
    ("public_source_access", "functions_search_service", "app", "background_tasks"),
    ("app", "background_tasks", "functions_public_workspaces"),
])
def test_real_public_source_import_orders_and_owner_wiring(order, optimized):
    process = run_probe(PROBE, order, optimized)
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS: real public-source import and owner wiring" in process.stdout


def test_public_source_boundary_has_no_reverse_owner_import():
    tree = ast.parse((APP / "public_source_access.py").read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imports.intersection({
        "config", "functions_public_workspaces", "functions_search",
        "functions_settings", "functions_search_service",
    })


@pytest.mark.parametrize("value, expected", [
    (None, []),
    (" a, b,a, ,c ", ["a", "b", "c"]),
    (["a", " b ", "a", ""], ["a", "b"]),
    (12, ["12"]),
])
def test_pure_search_identifier_normalization_preserves_existing_contract(value, expected):
    from search_scope_utils import normalize_search_id_list

    actual = normalize_search_id_list(value)
    assert actual == expected
