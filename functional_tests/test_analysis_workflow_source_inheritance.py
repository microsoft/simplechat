# test_analysis_workflow_source_inheritance.py
"""
Functional tests for Analyze source access inherited by workflow results.
Version: 0.261.109
Implemented in: 0.261.109

Saved explanations must not bypass contributor permissions, and workflow
materialization must authorize before reading final record values.
"""

import json
from copy import deepcopy

import pytest

from test_support.app_stubs import import_app_module
from test_workflow_result_contract import RUN_ID, WORKFLOW, SerializedSections


results = import_app_module("functions_workflow_results")
access = import_app_module("functions_analysis_access")


def build_source():
    return {
        "document_id": "source-1",
        "scope": "group",
        "scope_id": "source-group",
        "source_version": "1",
        "source_revision": "etag-1",
        "authorization_status": "authorized",
    }


def build_analysis():
    return {
        "reply": "A readable answer.",
        "analysis_result": {
            "analysis_result_version": "analyze-final-v1",
            "analysis_reply": "The controls need an accountable owner.",
            "source_manifest": [build_source()],
            "authoritative_result": {
                "kind": "records",
                "value": [{"record_id": "record-1", "values": {"finding": "An owner is not assigned."}}],
            },
            "analysis_validation": {
                "status": "partial",
                "limitations": ["One finding could not be finalized."],
            },
            "analysis_evidence": [{"evidence_id": "evidence-1", "quote": "Owner: unassigned"}],
        },
    }


def save(store, result, task_id, consumed=None):
    envelope = results.build_workflow_task_result(
        result, workflow=WORKFLOW, run_id=RUN_ID, task={"id": task_id}
    )
    envelope["consumed_inputs"] = list(consumed or [])
    return results.persist_workflow_task_result(
        envelope, workflow=WORKFLOW, run_id=RUN_ID, task_id=task_id, save_result=store.save
    )


def current_sources(allowed=True, calls=None):
    def resolve(document_ids, **context):
        if calls is not None:
            calls.append(context)
        return [
            {**build_source(), "authorization_status": "authorized" if allowed else "unresolved"}
            for _ in document_ids
        ]

    return resolve


def test_new_analyze_separates_evidence_and_preserves_validation():
    store = SerializedSections()
    manifest, reference = save(store, build_analysis(), "analyze")
    assert manifest["validation"]["status"] == "partial"
    assert manifest["outputs"]["evidence"]["kind"] == "evidence"
    assert manifest["authoritative_output"] == "records"
    assert manifest["analysis_access"]["sources"][0]["source_revision"] == "etag-1"
    prompt, consumed = results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", reference,
        load_result=store.load, source_resolver=current_sources(), allow_partial=True,
    )
    assert json.loads(prompt)["validation"]["status"] == "partial"
    assert consumed["analysis_result"] is True
    assert results.workflow_result_summary(manifest, reference)["analysis_result"] is True


def test_revoked_source_blocks_before_final_records_are_loaded():
    store = SerializedSections()
    manifest, reference = save(store, build_analysis(), "analyze")
    with pytest.raises(access.AnalysisResultUnavailable):
        results.load_workflow_task_input(
            WORKFLOW, RUN_ID, "analyze", reference,
            load_result=store.load, source_resolver=current_sources(False),
        )
    assert store.reads == [reference["sha256"]]
    assert manifest["outputs"]["records"]["result_ref"]["sha256"] not in store.reads


def test_saved_explanation_inherits_transitive_source_access():
    store = SerializedSections()
    _, analysis_ref = save(store, build_analysis(), "analyze")
    _, consumed = results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", analysis_ref,
        load_result=store.load, source_resolver=current_sources(), allow_partial=True,
    )
    _, explanation_ref = save(store, {"reply": "A later explanation."}, "explain", [consumed])
    _, explanation_consumed = results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "explain", explanation_ref,
        load_result=store.load, source_resolver=current_sources(),
    )
    assert explanation_consumed["analysis_result"] is True
    _, final_ref = save(store, {"reply": "Another explanation."}, "explain-again", [explanation_consumed])
    with pytest.raises(access.AnalysisResultUnavailable):
        results.load_workflow_task_input(
            WORKFLOW, RUN_ID, "explain-again", final_ref,
            load_result=store.load, source_resolver=current_sources(False),
        )


def test_group_reader_is_authorized_as_the_actual_reader_not_workflow_owner():
    store = SerializedSections()
    _, reference = save(store, build_analysis(), "analyze")
    calls = []
    results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", reference, reader_user_id="another-member",
        load_result=store.load, source_resolver=current_sources(calls=calls), allow_partial=True,
    )
    assert calls[0]["user_id"] == "another-member"


@pytest.mark.parametrize("changed", ["producer", "output_ref"])
def test_forged_consumption_identity_cannot_skip_parent_access(changed):
    store = SerializedSections()
    _, reference = save(store, build_analysis(), "analyze")
    _, consumed = results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", reference,
        load_result=store.load, source_resolver=current_sources(), allow_partial=True,
    )
    forged = deepcopy(consumed)
    if changed == "producer":
        forged["producer"]["workflow_id"] = "foreign-workflow"
    else:
        forged["output_ref"] = {"sha256": "not-the-consumed-section"}
    _, child_ref = save(store, {"reply": "A purported explanation."}, "explain", [forged])
    with pytest.raises(access.AnalysisResultUnavailable):
        results.load_workflow_task_input(
            WORKFLOW, RUN_ID, "explain", child_ref,
            load_result=store.load, source_resolver=current_sources(),
        )


def test_new_analysis_without_source_lineage_cannot_be_saved_as_complete():
    result = build_analysis()
    result["analysis_result"]["source_manifest"] = []
    with pytest.raises(access.AnalysisResultUnavailable):
        save(SerializedSections(), result, "analyze")


def test_shared_ancestors_are_loaded_once_per_authorized_traversal():
    store = SerializedSections()
    _, root_ref = save(store, build_analysis(), "analyze")
    _, root_input = results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", root_ref,
        load_result=store.load, source_resolver=current_sources(), allow_partial=True,
    )
    parents = []
    for task_id in ("first-explanation", "second-explanation"):
        _, reference = save(store, {"reply": "A saved explanation."}, task_id, [root_input])
        _, consumed = results.load_workflow_task_input(
            WORKFLOW, RUN_ID, task_id, reference,
            load_result=store.load, source_resolver=current_sources(),
        )
        parents.append(consumed)
    _, final_ref = save(store, {"reply": "A combined explanation."}, "final", parents)
    store.reads.clear()
    results.authorize_workflow_task_result_read(
        WORKFLOW, RUN_ID, "final", final_ref,
        load_result=store.load, source_resolver=current_sources(),
    )
    assert len(store.reads) == 4
    assert store.reads.count(root_ref["sha256"]) == 1


def test_ordinary_ancestor_flags_cannot_hide_analyze_lineage():
    store = SerializedSections()
    _, root_ref = save(store, build_analysis(), "analyze")
    _, consumed = results.load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", root_ref,
        load_result=store.load, source_resolver=current_sources(), allow_partial=True,
    )
    consumed.pop("analysis_result")
    _, child_ref = save(store, {"reply": "A saved explanation."}, "explain", [consumed])
    with pytest.raises(access.AnalysisResultUnavailable):
        results.authorize_workflow_task_result_read(
            WORKFLOW, RUN_ID, "explain", child_ref,
            load_result=store.load, source_resolver=current_sources(False),
        )
