# test_orchestration_composition_metadata_recovery.py
"""Keep committed reasoning intact when a later composition cannot verify metadata.

Version: 0.261.127
Implemented in: 0.261.127

Real headless execution, composition, checkpoints and retained readers run with
the existing Azure/model transport doubles. Actual current-configuration reads
fail during the second model invocation, after the first result is committed.
"""

from copy import deepcopy
import json

import pytest

from functions_orchestration_execution import HarnessExecutionError
from functions_orchestration_result_contracts import TaskResult
from test_orchestration_harness_execution import (
    current_metadata, harness, initialized_application,  # noqa: F401
)
from test_support.orchestration_harness_execution import compose_step, input_binding


@pytest.mark.parametrize("fault,retryable", [
    ("service", True),
    ("timeout", True),
    ("throttled", True),
    ("invalid", False),
    ("limit", False),
])
def test_current_metadata_failure_preserves_committed_sibling_without_publication(
    harness, current_metadata, fault, retryable,
):
    observed = {}
    source = current_metadata
    content = "The complete original prepared input."

    def require_current_metadata():
        observed["run"] = deepcopy(harness.read())
        source.arm(fault)
        source.read()
        raise AssertionError("Unavailable metadata must stop the model invocation.")

    harness.create(
        steps=[
            compose_step("retained"),
            compose_step("finish", inputs={
                "prepared": {"binding": input_binding("retained"), "allow_partial": False},
            }),
        ],
        replies=[content, require_current_metadata],
        final_response=input_binding("finish"),
    )
    execution = harness.prepare()
    try:
        with pytest.raises(HarnessExecutionError) as raised:
            execution.execute()
    finally:
        execution.close()

    before = observed["run"]
    saved = harness.read()
    messages = harness.assistant_messages()
    service = harness.services()
    task = TaskResult.from_dict(saved["task_results"]["retained"])
    reader = service.results.open_result(task.output("answer"), require_current_sources=True)
    retained = reader.read_text()

    assert raised.value.code == "message_not_saved" and raised.value.retryable is retryable
    assert raised.value.final_frames == [] and raised.value.durable_status is None
    assert saved["status"] == before["status"] == "running"
    assert saved["task_results"] == before["task_results"]
    assert set(saved["task_results"]) == {"retained"} and task.status == "complete"
    assert saved["attempt_index"] == before["attempt_index"]
    assert saved["execution_deadline_at"] == before["execution_deadline_at"]
    assert saved["execution_lease"] is None and execution.lease.stopped.is_set()
    assert not saved.get("failure") and not saved.get("completed_at")
    assert retained == content and messages == []
    assert len(source.observed) == 1 and len(harness.model_calls) == 2
    assert harness.blobs.file_uploads == 0
    assert "PRIVATE_" not in raised.value.message
    assert "PRIVATE_" not in json.dumps([saved, messages, raised.value.final_frames])
