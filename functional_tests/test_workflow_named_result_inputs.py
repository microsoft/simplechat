# test_workflow_named_result_inputs.py
"""
Functional tests for source-authorized named workflow result inputs.
Version: 0.261.107
Implemented in: 0.261.107

Final representations retain exact receipts. Partial data requires an explicit
opt-in, and no caller can bind pending output or diagnostics as final task data.
"""

import json

import pytest

from test_workflow_result_contract import RUN_ID, TASK, WORKFLOW, SerializedSections
from functions_analysis_access import AnalysisResultUnavailable, build_analysis_access
from functions_workflow_results import (
    WorkflowResultNotReadyError,
    build_workflow_task_result,
    load_workflow_task_input,
    persist_workflow_task_result,
    workflow_result_summary,
)


def saved(store, *, state="succeeded", validation="valid", sources=None):
    envelope = build_workflow_task_result(
        {
            "reply": "Readable report.",
            "authoritative_result": {"kind": "records", "value": [{"finding": "Needs an owner."}]},
        },
        workflow=WORKFLOW, run_id=RUN_ID, task=TASK,
    )
    envelope["execution"]["status"] = state
    envelope["validation"] = {"status": validation, "limitations": ["No independent factual review."]}
    if sources is not None:
        envelope["analysis_access"] = build_analysis_access(sources)
    manifest, reference = persist_workflow_task_result(
        envelope, workflow=WORKFLOW, run_id=RUN_ID, task_id=TASK["id"], save_result=store.save,
    )
    return manifest, reference


@pytest.mark.parametrize("name,kind,value", [
    ("authoritative", "records", [{"finding": "Needs an owner."}]),
    ("records", "records", [{"finding": "Needs an owner."}]),
    ("text", "text", "Readable report."),
])
def test_named_final_output_preserves_its_exact_receipt(name, kind, value):
    store = SerializedSections()
    manifest, reference = saved(store)
    prompt, receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, TASK["id"], reference, output_name=name, load_result=store.load,
    )
    payload = json.loads(prompt)
    assert payload["kind"] == kind
    assert payload["value"] == value
    assert receipt["output_name"] == ("records" if name == "authoritative" else name)
    assert receipt["output_ref"] == manifest["outputs"][receipt["output_name"]]["result_ref"]
    assert receipt["result_ref"] == reference
    assert payload["consumed_result"] == receipt


@pytest.mark.parametrize("state", ["succeeded", "incomplete"])
def test_completed_partial_output_requires_an_explicit_opt_in(state):
    store = SerializedSections()
    _, reference = saved(store, state=state, validation="partial")
    with pytest.raises(WorkflowResultNotReadyError):
        load_workflow_task_input(WORKFLOW, RUN_ID, TASK["id"], reference, load_result=store.load)
    prompt, _ = load_workflow_task_input(
        WORKFLOW, RUN_ID, TASK["id"], reference, allow_partial=True, load_result=store.load,
    )
    assert json.loads(prompt)["validation"]["status"] == "partial"
    assert json.loads(prompt)["validation"]["limitations"] == ["No independent factual review."]


@pytest.mark.parametrize("state,validation", [
    ("pending", "partial"), ("pending", "valid"), ("succeeded", "pending"),
    ("succeeded", "invalid"), ("incomplete", "invalid"), ("failed", "partial"),
])
def test_allow_partial_never_admits_pending_or_invalid_results(state, validation):
    store = SerializedSections()
    _, reference = saved(store, state=state, validation=validation)
    with pytest.raises(WorkflowResultNotReadyError):
        load_workflow_task_input(
            WORKFLOW, RUN_ID, TASK["id"], reference, allow_partial=True, load_result=store.load,
        )
    assert store.reads == [reference["sha256"]]


@pytest.mark.parametrize("output_name", ["diagnostics", "presentation", "evidence", "validation", {}, "not-stored"])
def test_nonfinal_or_unknown_bindings_are_rejected(output_name):
    store = SerializedSections()
    _, reference = saved(store)
    with pytest.raises(ValueError):
        load_workflow_task_input(
            WORKFLOW, RUN_ID, TASK["id"], reference, output_name=output_name, load_result=store.load,
        )


@pytest.mark.parametrize("output_name", ["authoritative", "records", "text"])
def test_every_named_output_requires_current_reference_source_access(output_name):
    store = SerializedSections()
    source = {
        "document_id": "reference", "scope_type": "group", "scope_id": "group-1",
        "source_version": "1", "content_sha256": "a" * 64,
    }
    _, reference = saved(store, sources=[source])
    with pytest.raises(AnalysisResultUnavailable):
        load_workflow_task_input(
            WORKFLOW, RUN_ID, TASK["id"], reference, output_name=output_name, load_result=store.load,
            source_resolver=lambda ids, **kwargs: [{
                "document_id": "reference", "scope": "group", "scope_id": "group-1",
                "authorization_status": "unresolved",
            }],
        )
    assert store.reads == [reference["sha256"]]


def test_source_bound_raw_model_output_is_not_an_original_analyze_run():
    envelope = build_workflow_task_result(
        {
            "reply": "An answer based on a reference document.",
            "analysis_access": build_analysis_access([{
                "document_id": "reference", "scope_type": "group", "scope_id": "group-1",
                "source_version": "1", "content_sha256": "a" * 64,
            }]),
        },
        workflow=WORKFLOW, run_id=RUN_ID, task=TASK,
    )
    assert envelope["analysis_access"]["sources"][0]["document_id"] == "reference"
    assert envelope["analysis_origin"] is False
    summary = workflow_result_summary(envelope, {"sha256": "a" * 64})
    assert summary["analysis_result"] is True
    assert summary["analysis_origin"] is False


def test_malformed_explicit_access_policy_does_not_disappear():
    with pytest.raises(AnalysisResultUnavailable):
        build_workflow_task_result(
            {"reply": "A reference-derived answer.", "analysis_access": {}},
            workflow=WORKFLOW, run_id=RUN_ID, task=TASK,
        )
