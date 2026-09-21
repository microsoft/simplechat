# test_orchestration_result_imports.py
"""
Real-module result-store cold imports and web/scheduler compatibility.
Version: 0.261.125
Implemented in: 0.261.125

Fresh normal/optimized interpreters block network access. Only external I/O is
doubled; config, settings, app, scheduler and result modules are never replaced.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
EARLY_PROBE = r'''
import builtins
import importlib
import socket
import sys
from unittest.mock import patch
from azure.core.exceptions import AzureError

sys.path[:0] = sys.argv[1:3]
real_import = builtins.__import__
forbidden = {
    "config", "functions_settings", "functions_saved_analysis",
    "functions_generated_file_exports", "functions_artifact_publication",
    "route_backend_orchestration", "route_backend_chats",
}
network_attempts = []

def no_network(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError("Unexpected external I/O")

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in forbidden:
        raise AssertionError("Unexpected result owner import: " + name)
    return real_import(name, globals, locals, fromlist, level)

def check(condition, message):
    if not condition:
        raise AssertionError(message)

with patch.object(socket.socket, "connect", no_network), patch.object(builtins, "__import__", guarded_import):
    for name in sys.argv[3:]:
        importlib.import_module(name)
    from test_support.orchestration_results import ResultFixture, ROWS
    from functions_orchestration_result_contracts import TaskResult
    from functions_orchestration_results import OrchestrationResultAccess, ResultContractError
    fixture = ResultFixture(blob=True)
    saved = fixture.save(grounded=False)
    checkpoint = saved.to_dict()
    restored = TaskResult.from_dict(checkpoint)
    reader = fixture.restart().open_result(restored.output("findings"))
    records = list(reader.iter_records())
    check(records == ROWS, "Complete result changed during cold restart")
    check(records[-1]["id"] == "last", "Final record was not read")
    check(bool(fixture.blobs.uploads), "Required persistence disappeared under optimized Python")
    try:
        OrchestrationResultAccess(
            user_id="owner", conversation_id="conversation-1",
            read_conversation=None, read_run=None,
        )
    except ResultContractError:
        pass
    else:
        raise AssertionError("Uninitialized access silently bootstrapped")
    fixture.container.fail_writes = True
    try:
        fixture.save(grounded=False)
    except AzureError:
        pass
    else:
        raise AssertionError("Storage failure became a successful result")
    check(not network_attempts, "A blocked network failure was swallowed")
    check(not forbidden.intersection(sys.modules), "Lower-level result access imported a runtime owner")
print("PASS: exact retained results, failure paths and owner-free cold imports")
'''

APP_PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    results = importlib.import_module("functions_orchestration_results")
    store = importlib.import_module("functions_workflow_result_store")
    scheduler = importlib.import_module("background_tasks")
    if results.ResultRef is not contracts.ResultRef:
        raise AssertionError("Bootstrap replaced the result contract")
    if not callable(store.WorkflowResultStore.load_committed_orchestration_result):
        raise AssertionError("Shared store lost the generic result reader")
    if "app" in sys.argv[3:] and not hasattr(importlib.import_module("app"), "app"):
        raise AssertionError("Normal web bootstrap did not complete")
    if not callable(scheduler.check_m365_workflow_continuations_once):
        raise AssertionError("Normal scheduler bootstrap did not complete")
    if environment.network_attempts:
        raise AssertionError("Cold import swallowed a network attempt")
print("PASS: real web and scheduler imports with result foundation")
'''


def run_probe(probe, order, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        command + ["-c", probe, str(APP), str(TESTS), *order],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_results", "functions_workflow_result_store"),
    ("functions_workflow_result_store", "functions_orchestration_results"),
])
def test_early_real_modules_and_injected_storage_work_in_both_import_orders(order, optimized):
    run_probe(EARLY_PROBE, order, optimized)


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_results", "app", "background_tasks"),
    ("app", "functions_orchestration_results", "background_tasks"),
    ("background_tasks", "functions_orchestration_results"),
])
def test_real_web_and_scheduler_imports_are_unchanged(order, optimized):
    run_probe(APP_PROBE, order, optimized)


def test_new_result_modules_do_not_add_reverse_owner_imports_even_locally():
    forbidden = {
        "config", "functions_settings", "functions_saved_analysis",
        "functions_generated_file_exports", "functions_artifact_publication",
    }
    for name in ("functions_orchestration_result_contracts", "functions_orchestration_results"):
        tree = ast.parse((APP / f"{name}.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not forbidden.intersection(imports)
        assert not any(name.startswith("route_") for name in imports)
