# test_orchestration_operation_imports.py
"""Real-module operation cold imports and mutable UUID accessor regressions.

Version: 0.261.322
Implemented in: 0.261.322

The existing graph includes deferred cycles. These tests verify import timing,
not removal of those cycles. External I/O is doubled and network access blocked.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest

from test_orchestration_result_imports import APP_PROBE


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
EARLY_PROBE = r'''
import builtins
import importlib
import socket
import sys
import uuid
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
real_import = builtins.__import__
forbidden = {
    "config", "functions_settings", "functions_orchestration_runs",
    "functions_orchestration_result_runtime", "functions_orchestration_results",
    "functions_m365_approvals", "functions_m365_execution",
    "functions_m365_pending_delivery",
}
network_attempts = []

def no_network(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError("Early operation access attempted network I/O")

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in forbidden:
        raise AssertionError("Early operation access imported its execution dependency: " + name)
    return real_import(name, globals, locals, fromlist, level)

with patch.object(socket.socket, "connect", no_network), patch.object(builtins, "__import__", guarded_import):
    for name in sys.argv[3:]:
        importlib.import_module(name)
    import functions_orchestration_operations as operations
    from test_support.m365 import CosmosContainer
    container = CosmosContainer("run_id")
    checks = []
    marker = uuid.UUID("00000000-0000-0000-0000-000000000123")
    with patch.object(uuid, "uuid4", return_value=marker):
        journal = operations.OperationJournal(
            container, "run", "step", "owner", "conversation",
            fingerprint="a" * 64, authorize=lambda: checks.append(True),
            sanitize=lambda value: value,
        )
    if journal.claim != marker.hex:
        raise AssertionError("Operation claims retained a stale UUID accessor")
    with operations.operation_journal_scope(journal):
        key, _ = journal.begin("operation", {"subject": "complete"})
        journal.finish(key, {"status": "confirmed"})
    if not checks or not container.items:
        raise AssertionError("Required claim operations disappeared")
    if operations.current_operation_journal() is not None:
        raise AssertionError("Operation scope leaked")
    recovered = operations.OperationJournal(
        container, "run", "step", "owner", "conversation",
        fingerprint="a" * 64, authorize=lambda: None, sanitize=lambda value: value,
    )
    _, cached = recovered.begin("operation", {"subject": "complete"})
    if cached != {"status": "confirmed"}:
        raise AssertionError("Confirmed result was not recovered")
    try:
        recovered.begin("changed", {"subject": "different"})
    except operations.OperationRecoveryError:
        pass
    else:
        raise AssertionError("Recovered operations allowed a changed effect")
    if forbidden.intersection(sys.modules) or network_attempts:
        raise AssertionError("Early access crossed the bootstrap boundary")
print("PASS: operation claims and early imports")
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
    ("functions_orchestration_operations", "functions_m365_operations", "functions_action_catalog"),
    ("functions_action_catalog", "functions_m365_operations", "functions_orchestration_operations"),
])
def test_operations_and_catalog_import_before_bootstrap(order, optimized):
    run_probe(EARLY_PROBE, order, optimized)


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_operations", "functions_m365_runtime", "app", "background_tasks"),
    ("functions_m365_runtime", "app", "functions_orchestration_operations", "background_tasks"),
    ("background_tasks", "functions_orchestration_operations"),
])
def test_operation_modules_preserve_real_web_and_scheduler_bootstrap(order, optimized):
    run_probe(APP_PROBE, order, optimized)


def test_execution_dependencies_remain_deferred_not_hoisted():
    source = (APP / "functions_orchestration_operations.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    eager = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            eager.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            eager.add(node.module)
    assert not {
        "config", "functions_orchestration_runs", "functions_orchestration_result_runtime",
        "functions_orchestration_results", "functions_m365_approvals",
        "functions_m365_execution", "functions_m365_pending_delivery",
    }.intersection(eager)
