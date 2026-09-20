# test_workflow_authoring_history.py
"""
Compiler contracts for actual TypeScript workflow history replay.
Version: 0.261.123
Implemented in: 0.261.123

Validates exact replay-produced Save payloads and authored digests without
executing a workflow, accessing Azure, or serializing raw history as JSON.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))

# Pure compiler imports follow the local application path setup.
from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_flow import compile_workflow_flow


@pytest.fixture(scope="module")
def replay_payloads():
    result = subprocess.run(
        ["node", str(ROOT / "functional_tests" / "test_workflow_authoring_session.js"), "--emit-history-payloads"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("before,after", [("initial", "undone"), ("edited", "redone"), ("redone", "preview")])
def test_replay_restores_exact_compiler_meaning(replay_payloads, before, after):
    first = compile_workflow_flow(replay_payloads[before])
    second = compile_workflow_flow(replay_payloads[after])
    for key in (
        "flow", "tasks", "limits", "task_nodes", "successor", "dependencies",
        "definite_outputs", "possible_outputs", "node_loop_ids", "loop_item_schemas",
    ):
        assert second[key] == first[key], key
    assert workflow_definition_revision(replay_payloads[before]) == workflow_definition_revision(replay_payloads[after])


def test_history_never_advances_cas_or_serializes_editor_state(replay_payloads):
    original = replay_payloads["initial"]
    for payload in replay_payloads.values():
        assert payload["definition_revision"] == original["definition_revision"]
        assert payload["id"] == original["id"]
        assert not {"history", "fields", "repeatRows", "positions", "selectedId"} & payload.keys()
    assert workflow_definition_revision(replay_payloads["edited"]) != workflow_definition_revision(original)
    assert replay_payloads["undone"] == original
    assert replay_payloads["redone"] == replay_payloads["edited"]
    assert replay_payloads["redone"]["future_envelope"] == original["future_envelope"]
    assert "future_envelope" not in replay_payloads["preview"]
