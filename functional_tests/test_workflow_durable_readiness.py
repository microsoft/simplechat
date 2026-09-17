# test_workflow_durable_readiness.py
"""
Functional tests for workflow child-output readiness gates.
Version: 0.261.111
Implemented in: 0.261.111

Already-submitted child runs are inspected without resubmission. Pending,
unavailable and failed output never become success-shaped preview handoffs.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Import the standalone readiness adapter after adding the worktree modules.
from functions_workflow_readiness import (
    WorkflowOutputUnavailable,
    pending_workflow_output_references,
    reconcile_workflow_pending_output,
    workflow_outputs_ready,
)
from functions_native_analysis_results import adapt_native_analysis_result
from test_analyze_native_saved_integration import native_run


WORKFLOW = {"id": "workflow", "user_id": "owner"}
SOURCE = {
    "document_id": "source", "scope": "personal", "scope_id": "owner", "source_version": 1,
    "source_revision": "source-etag", "file_name": "inventory.csv", "source_kind": "tabular",
}
RESULT = {
    "reply": "The analysis is being prepared.",
    "generated_tabular_outputs": [{"export_run_id": "native-run", "background_export": True}],
    "analysis_result": {"execution_status": "pending", "analysis_sources": [SOURCE]},
}


def status(state="completed"):
    return {
        "run_id": "native-run", "conversation_id": "conversation", "status": state,
        "row_count": 2, "output_format": "json",
        "structured_export_artifact": {"artifact_message_id": "final-output", "output_format": "json"},
    }


def read_result(result=RESULT, state="completed"):
    def adapter(**kwargs):
        return adapt_native_analysis_result(
            **kwargs, native_reader=lambda *args: {
                "run_id": "native-run", "status": "completed", "kind": "records",
                "value": [{"id": "one"}, {"id": "two"}], "source_row_count": 2,
            },
        )

    return reconcile_workflow_pending_output(
        WORKFLOW, result, conversation_id="conversation", actor_user_id="owner",
        get_status=lambda workflow, reference: status(state),
        native_adapter=adapter,
        source_resolver=lambda ids, **kwargs: [{**SOURCE, "authorization_status": "authorized"}],
    )


def test_pending_output_stays_waiting_without_reading_a_preview():
    def unreadable(*args, **kwargs):
        pytest.fail("Pending artifacts must not be read.")

    assert reconcile_workflow_pending_output(
        WORKFLOW, RESULT, conversation_id="conversation", actor_user_id="owner",
        get_status=lambda *args: status("running"), native_adapter=unreadable,
    ) is None
    assert not workflow_outputs_ready(
        WORKFLOW, pending_workflow_output_references(RESULT), get_status=lambda *args: status("running"),
    )


def test_completed_child_supplies_final_records_not_a_summary():
    result = read_result()
    assert result["authoritative_result"]["kind"] == "records"
    assert [record["values"] for record in result["authoritative_result"]["value"]] == [{"id": "one"}, {"id": "two"}]
    assert result["execution_status"] == "succeeded"
    assert result["analysis_result"]["native_result_references"][0]["run_id"] == "native-run"


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_failed_child_cannot_satisfy_readiness(state):
    with pytest.raises(WorkflowOutputUnavailable, match="failed or was cancelled"):
        read_result(state=state)


def test_unsupported_mixed_composition_is_explicit_not_a_summary_fallback():
    with pytest.raises(WorkflowOutputUnavailable, match="final composition"):
        read_result({**RESULT, "deferred_composition": {"status": "continuation_unavailable"}})


def test_child_cannot_substitute_another_conversations_output():
    with pytest.raises(PermissionError):
        reconcile_workflow_pending_output(
            WORKFLOW, RESULT, conversation_id="expected-conversation", actor_user_id="owner",
            get_status=lambda *args: status(), native_adapter=lambda **kwargs: {},
        )


def test_workflow_reads_actual_complete_native_checkpoints_without_resubmission(native_run):
    producer = {"kind": "workflow", "workflow_id": "workflow", "run_id": "workflow-run", "task_id": "analyze"}
    workflow = {**WORKFLOW, "user_id": native_run.source["scope_id"], "_analysis_producer": producer}
    result = {
        **RESULT, "analysis_result": {"execution_status": "pending", "analysis_sources": [native_run.source]},
    }
    refreshed = reconcile_workflow_pending_output(
        workflow, result, conversation_id="conversation-1", actor_user_id=workflow["user_id"],
        run_id="workflow-run", source_resolver=native_run.resolve,
        get_status=lambda *args: {**status(), "conversation_id": "conversation-1"},
    )
    assert native_run.reads == ["batch-1", "batch-2", "batch-3"]
    assert [row["values"] for row in refreshed["authoritative_result"]["value"]] == native_run.rows
    assert refreshed["analysis_result"]["native_result_references"][0]["run_id"] == "native-run"
