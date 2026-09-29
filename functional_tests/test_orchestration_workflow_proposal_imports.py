#!/usr/bin/env python3
# test_orchestration_workflow_proposal_imports.py
"""
Functional test for cold imports of the workflow proposal decisions module.
Version: 0.261.206
Implemented in: 0.261.206

This test ensures that the workflow proposal module, which the orchestration routes import
lazily, loads in fresh normal and optimized interpreters in every order the application uses:
after the web bootstrap, after the orchestration routes and after the settings module. Only
Cosmos DB is doubled; every network socket is blocked.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    proposals = importlib.import_module("functions_orchestration_workflow_proposals")
    route = importlib.import_module("route_backend_orchestration")
    runs = importlib.import_module("functions_orchestration_runs")
    if route._workflow_proposals() is not proposals:
        raise AssertionError("The routes resolved a different proposal module")
    if proposals.WORKFLOW_PROPOSAL_DECISIONS_FIELD != runs.WORKFLOW_PROPOSAL_DECISIONS_FIELD:
        raise AssertionError("The decision field drifted from the run store's")
    refusal = proposals.ProposalError("proposal_busy")
    if refusal.status != 409 or refusal.payload() != {
        "error": proposals.ERROR_MESSAGES["proposal_busy"], "code": "proposal_busy", "errors": [],
    }:
        raise AssertionError("The proposal refusal changed")
    if "app" in sys.argv[3:] and not hasattr(importlib.import_module("app"), "app"):
        raise AssertionError("The web bootstrap did not complete")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: workflow proposal module cold imports")
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


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("app", "functions_orchestration_workflow_proposals"),
    ("route_backend_orchestration", "functions_orchestration_workflow_proposals"),
    ("functions_settings", "functions_orchestration_workflow_proposals", "route_backend_orchestration"),
])
def test_the_proposal_module_loads_in_every_application_import_order(order, optimized):
    run_probe(order, optimized)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
