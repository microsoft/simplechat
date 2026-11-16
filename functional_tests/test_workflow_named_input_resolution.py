# test_workflow_named_input_resolution.py
"""
Functional tests for explicit task data and reusable reference resolution.
Version: 0.261.108
Implemented in: 0.261.108

Source access is rechecked even for frozen references. Upstream data is selected
by task identity, never by the previous reply or an untrusted storage path.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Worktree application imports follow module-path setup.
from functions_workflow_bindings import (
    WorkflowInputError,
    authorize_workflow_reference,
    load_workflow_reference,
    resolve_workflow_task_inputs,
)


WORKFLOW = {"id": "workflow", "user_id": "owner"}
REFERENCE = {
    "id": "criteria", "name": "criteria", "document_id": "reference-document",
    "scope_type": "personal", "scope_id": "owner",
}


def document_context(**kwargs):
    return {"scope": "personal", "document": {"id": "reference-document", "user_id": "owner", "version": "v1"}}


def document_chunks(**kwargs):
    return {
        "scope": "personal", "scope_id": "owner",
        "chunk_count": 2, "returned_chunk_count": 2,
        "chunks": [{"chunk_text": "Shared reference criteria."}, {"chunk_text": "Use every inventory record."}],
    }


def binding(task_id="extract", **kwargs):
    return {
        "name": "inventory", "task_id": task_id, "output": "records",
        "expected_kind": "records", "required": True, **kwargs,
    }


def producer(task_id):
    return {
        "run_id": "run", "result_ref": {"sha256": task_id},
        "outputs": {"records": {"kind": "records"}},
    }


def test_explicit_binding_loads_nonadjacent_producer_with_exact_output():
    calls = []

    def load_output(workflow, run_id, task_id, reference, *, output_name):
        calls.append((workflow, run_id, task_id, reference, output_name))
        return json.dumps({"kind": "records", "value": [{"id": "final"}]}), {
            "producer": {"task_id": task_id, "run_id": run_id},
            "output_name": output_name,
            "result_ref": reference,
        }

    result = resolve_workflow_task_inputs(
        WORKFLOW, {"inputs": [binding()]}, {"extract": producer("extract"), "explain": producer("explain")},
        previous_task_id="explain", load_output=load_output,
    )
    assert calls[0][2:] == ("extract", {"sha256": "extract"}, "records")
    assert json.loads(result["task_context"])["inputs"][0]["result"]["value"] == [{"id": "final"}]
    assert result["consumed_inputs"][0]["producer"]["task_id"] == "extract"
    assert result["consumed_inputs"][0]["input_name"] == "inventory"


def test_explicit_empty_input_list_does_not_inject_the_previous_reply():
    def forbidden(*args, **kwargs):
        pytest.fail("Explicit empty bindings must not load a previous output.")

    result = resolve_workflow_task_inputs(
        WORKFLOW, {"inputs": []}, {"extract": producer("extract")}, previous_task_id="extract", load_output=forbidden,
    )
    assert result["task_context"] == ""
    assert result["consumed_inputs"] == []


def test_missing_required_producer_cannot_fall_back_to_last_success():
    with pytest.raises(WorkflowInputError, match="required input"):
        resolve_workflow_task_inputs(
            WORKFLOW, {"inputs": [binding("failed-task")]}, {"extract": producer("extract")},
            previous_task_id="extract", load_output=lambda *args: pytest.fail("No fallback read"),
        )


def test_optional_missing_input_is_visible_data_not_silent_default():
    result = resolve_workflow_task_inputs(
        WORKFLOW, {"inputs": [binding("not-produced", required=False)]}, {},
        load_output=lambda *args: pytest.fail("Unavailable input must not be loaded."),
    )
    assert json.loads(result["task_context"]) == {"inputs": [{"name": "inventory", "status": "unavailable"}]}


def test_optional_named_output_may_be_absent_but_denied_access_never_silently_succeeds():
    item = producer("extract")
    item["outputs"] = {"text": {"kind": "text"}}
    result = resolve_workflow_task_inputs(
        WORKFLOW, {"inputs": [binding(required=False)]}, {"extract": item},
        load_output=lambda *args: pytest.fail("Missing output must not be loaded."),
    )
    assert json.loads(result["task_context"])["inputs"][0]["status"] == "unavailable"

    def denied(*args, **kwargs):
        raise PermissionError("Source access revoked.")

    with pytest.raises(PermissionError):
        resolve_workflow_task_inputs(
            WORKFLOW, {"inputs": [binding(required=False)]}, {"extract": producer("extract")}, load_output=denied,
        )


def test_actual_output_kind_is_checked_at_consumption():
    with pytest.raises(WorkflowInputError, match="required output kind"):
        resolve_workflow_task_inputs(
            WORKFLOW, {"inputs": [binding()]}, {"extract": producer("extract")},
            load_output=lambda *args, **kwargs: (json.dumps({"kind": "text", "value": "Not records."}), {}),
        )


def test_invalid_producer_output_is_not_consumed():
    item = {**producer("extract"), "workflow_validation": {"status": "invalid", "eligible": False}}
    with pytest.raises(WorkflowInputError, match="output requirements"):
        resolve_workflow_task_inputs(
            WORKFLOW, {"inputs": [binding()]}, {"extract": item},
            load_output=lambda *args: pytest.fail("Invalid output must not be loaded."),
        )


def test_partial_policy_is_passed_explicitly_to_the_authorized_loader():
    requests = []
    item = {**producer("extract"), "workflow_validation": {"status": "accepted_partial", "eligible": True}}

    def loader(*args, **kwargs):
        requests.append(kwargs)
        return json.dumps({"kind": "records", "value": [], "limitations": ["missing source"]}), {}

    result = resolve_workflow_task_inputs(WORKFLOW, {"inputs": [binding()]}, {"extract": item}, load_output=loader)
    assert requests == [{"output_name": "records", "allow_partial": True}]
    assert json.loads(result["task_context"])["inputs"][0]["result"]["limitations"] == ["missing source"]


def test_reference_is_full_text_separate_from_task_output_inputs():
    snapshot = load_workflow_reference(
        WORKFLOW, REFERENCE, resolve_document=document_context, load_chunks=document_chunks,
    )
    assert snapshot["text"] == "Shared reference criteria.\n\nUse every inventory record."
    assert snapshot["source"]["source_version"] == "v1"
    result = resolve_workflow_task_inputs(
        {**WORKFLOW, "reference_inputs": [REFERENCE]}, {"inputs": []}, {},
        load_output=lambda *args: pytest.fail("No task output binding."),
        load_reference=lambda ref, **kwargs: snapshot,
    )
    assert result["task_context"] == ""
    assert json.loads(result["reference_context"])["shared_references"][0]["name"] == "criteria"
    assert result["reference_sources"] == [snapshot["source"]]


def test_cached_reference_rechecks_current_access_without_reloading_unchanged_content():
    snapshot = load_workflow_reference(
        WORKFLOW, REFERENCE, resolve_document=document_context, load_chunks=document_chunks,
    )
    assert load_workflow_reference(
        WORKFLOW, REFERENCE, snapshot=snapshot, resolve_document=document_context,
        load_chunks=lambda **kwargs: pytest.fail("Unchanged content is frozen."),
    ) == snapshot
    with pytest.raises(WorkflowInputError, match="not available"):
        load_workflow_reference(
            WORKFLOW, REFERENCE, snapshot=snapshot, resolve_document=lambda **kwargs: None,
            load_chunks=lambda **kwargs: pytest.fail("Access must be checked before reading."),
        )


def test_changed_reference_requires_a_new_run():
    snapshot = load_workflow_reference(
        WORKFLOW, REFERENCE, resolve_document=document_context, load_chunks=document_chunks,
    )

    def changed_context(**kwargs):
        context = document_context()
        context["document"]["version"] = "v2"
        return context

    with pytest.raises(WorkflowInputError, match="changed during"):
        load_workflow_reference(
            WORKFLOW, REFERENCE, snapshot=snapshot, resolve_document=changed_context, load_chunks=document_chunks,
        )


def test_reference_scope_cannot_fall_back_to_a_chat_upload_or_another_owner():
    with pytest.raises(WorkflowInputError):
        authorize_workflow_reference(
            WORKFLOW, REFERENCE, resolve_document=lambda **kwargs: {
                "scope": "chat", "document": {"id": "reference-document", "user_id": "owner"},
            },
        )
    with pytest.raises(WorkflowInputError):
        authorize_workflow_reference(
            WORKFLOW, REFERENCE, resolve_document=lambda **kwargs: {
                "scope": "personal", "document": {"id": "reference-document", "user_id": "someone-else"},
            },
        )


def test_partial_document_payload_is_not_a_full_reference():
    with pytest.raises(WorkflowInputError, match="complete shared reference"):
        load_workflow_reference(
            WORKFLOW, REFERENCE, resolve_document=document_context,
            load_chunks=lambda **kwargs: {**document_chunks(), "chunk_count": 3},
        )
