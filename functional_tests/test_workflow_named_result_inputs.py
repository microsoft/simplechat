# test_workflow_named_result_inputs.py
"""
Functional tests for source-authorized named workflow result inputs.
Version: 0.261.110
Implemented in: 0.261.107

Final representations retain exact receipts. Partial data requires an explicit
opt-in, and no caller can bind pending output or diagnostics as final task data.
"""

import json
import inspect
from copy import deepcopy

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


@pytest.mark.parametrize("output_name", ["authoritative", "records", "text", "json", "documents"])
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


def test_access_policy_without_an_origin_marker_never_claims_analyze_provenance():
    envelope = build_workflow_task_result(
        {
            "reply": "A reference-derived answer.",
            "analysis_access": build_analysis_access([{
                "document_id": "reference", "scope_type": "group", "scope_id": "group-1",
                "source_version": "1", "content_sha256": "a" * 64,
            }]),
        },
        workflow=WORKFLOW, run_id=RUN_ID, task=TASK,
    )
    envelope.pop("analysis_origin")
    summary = workflow_result_summary(envelope, {"sha256": "a" * 64})
    assert summary["analysis_result"] is True
    assert summary["source_count"] == 1
    assert summary["analysis_origin"] is False


def test_malformed_explicit_access_policy_does_not_disappear():
    with pytest.raises(AnalysisResultUnavailable):
        build_workflow_task_result(
            {"reply": "A reference-derived answer.", "analysis_access": {}},
            workflow=WORKFLOW, run_id=RUN_ID, task=TASK,
        )


@pytest.mark.parametrize("top_level_access", [None, {
    "version": "analysis-source-access-v1",
    "sources": [{"document_id": "reference", "scope": "group", "scope_id": "group-1",
                 "source_version": "1", "source_revision": "etag-1"}],
}])
def test_empty_nested_access_policy_cannot_fall_back_to_another_policy(top_level_access):
    with pytest.raises(AnalysisResultUnavailable):
        build_workflow_task_result({
            "reply": "A reference-derived answer.",
            "analysis_access": top_level_access,
            "analysis_result": {"analysis_reply": "Final data.", "analysis_access": {}},
        }, workflow=WORKFLOW, run_id=RUN_ID, task=TASK)


@pytest.mark.parametrize("allow_partial", ["true", "false", 1, None])
def test_partial_opt_in_requires_an_explicit_boolean(allow_partial):
    store = SerializedSections()
    _, reference = saved(store, validation="partial")
    with pytest.raises(ValueError, match="boolean"):
        load_workflow_task_input(
            WORKFLOW, RUN_ID, TASK["id"], reference, allow_partial=allow_partial, load_result=store.load,
        )


@pytest.mark.parametrize("name,kind,value", [
    ("json", "json", {"accepted": [{"amount": "12.3400"}]}),
    ("documents", "document_results", [{
        "document_id": "source-1", "kind": "records", "value": [{"amount": "12.3400"}],
    }]),
])
def test_json_and_document_selectors_read_the_named_complete_representation(name, kind, value):
    store = SerializedSections()
    manifest, _ = saved(store)
    section_ref = store.save(WORKFLOW, RUN_ID, TASK["id"], {
        "contract_version": manifest["contract_version"], "producer": manifest["identity"],
        "output_name": name, "kind": kind, "value": value,
    })
    manifest["outputs"][name] = {"kind": kind, "result_ref": section_ref}
    reference = store.save(WORKFLOW, RUN_ID, TASK["id"], manifest)
    prompt, receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, TASK["id"], reference, output_name=name, load_result=store.load,
    )
    assert json.loads(prompt)["value"] == value
    assert json.loads(prompt)["kind"] == kind
    assert receipt["output_name"] == name and receipt["output_ref"] == section_ref
    assert store.reads == [reference["sha256"], section_ref["sha256"]]


def test_default_authoritative_selection_stays_identical():
    store = SerializedSections()
    _, reference = saved(store)
    default = load_workflow_task_input(WORKFLOW, RUN_ID, TASK["id"], reference, load_result=store.load)
    explicit = load_workflow_task_input(
        WORKFLOW, RUN_ID, TASK["id"], reference, output_name="authoritative", load_result=store.load,
    )
    assert default == explicit
    parameters = inspect.signature(load_workflow_task_input).parameters
    assert parameters["output_name"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["output_name"].default == "authoritative"
    assert parameters["allow_partial"].default is False


def test_named_binding_cannot_redirect_to_diagnostics():
    store = SerializedSections()
    manifest, _ = saved(store)
    manifest["outputs"]["text"]["result_ref"] = manifest["outputs"]["diagnostics"]["result_ref"]
    reference = store.save(WORKFLOW, RUN_ID, TASK["id"], manifest)
    with pytest.raises(ValueError, match="does not match"):
        load_workflow_task_input(
            WORKFLOW, RUN_ID, TASK["id"], reference, output_name="text", load_result=store.load,
        )


def test_named_binding_kind_must_match_the_representation():
    store = SerializedSections()
    manifest, _ = saved(store)
    manifest["outputs"]["text"]["kind"] = "evidence"
    reference = store.save(WORKFLOW, RUN_ID, TASK["id"], manifest)
    with pytest.raises(ValueError, match="authoritative output binding"):
        load_workflow_task_input(
            WORKFLOW, RUN_ID, TASK["id"], reference, output_name="text", load_result=store.load,
        )


def test_explicit_text_does_not_become_an_ancestor_record_reader():
    store = SerializedSections()
    _, parent_ref = saved(store, sources=[{
        "document_id": "reference", "scope_type": "group", "scope_id": "group-1",
        "source_version": "1", "content_sha256": "a" * 64,
    }])
    def resolve(ids, **kwargs):
        return [{
            "document_id": "reference", "scope": "group", "scope_id": "group-1",
            "source_version": "1", "authorization_status": "authorized",
        }]
    _, parent_receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, TASK["id"], parent_ref, load_result=store.load, source_resolver=resolve,
    )
    envelope = build_workflow_task_result(
        {"reply": "This complete report text is explicitly selected."},
        workflow=WORKFLOW, run_id=RUN_ID, task={"id": "explain"},
    )
    envelope["consumed_inputs"] = [parent_receipt]
    _, reference = persist_workflow_task_result(
        envelope, workflow=WORKFLOW, run_id=RUN_ID, task_id="explain", save_result=store.save,
    )
    prompt, receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, "explain", reference, output_name="text", bounded=True, load_result=store.load,
        source_resolver=resolve,
    )
    assert isinstance(prompt, str)
    assert json.loads(prompt)["value"] == "This complete report text is explicitly selected."
    assert receipt["producer"]["task_id"] == "explain"


def test_workflow_validation_does_not_replace_analysis_validation_or_receipts():
    store = SerializedSections()
    manifest, _ = saved(store, state="incomplete", validation="partial")
    separate_validation = {
        "version": "workflow-validation-v1", "status": "checked", "eligible": False,
        "reason_codes": ["needs_review"], "counts": {"accepted": 1},
    }
    manifest["workflow_validation"] = deepcopy(separate_validation)
    reference = store.save(WORKFLOW, RUN_ID, TASK["id"], manifest)
    prompt, receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, TASK["id"], reference, allow_partial=True, load_result=store.load,
    )
    data = json.loads(prompt)
    assert data["validation"]["status"] == "partial"
    assert data["accepted_subset_only"] is True
    assert receipt["result_ref"] == reference
    assert manifest["workflow_validation"] == separate_validation
