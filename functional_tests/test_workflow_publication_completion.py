# test_workflow_publication_completion.py
"""
Functional tests for explicit workflow publication completion.
Version: 0.261.118
Implemented in: 0.261.118

Production normalization, receipt decisions and native lifecycle observations use
closed fictional storage/processing boundaries. Native Analyze-to-runner coverage
is in test_workflow_structured_publication.py; no live files are published.
"""

from copy import deepcopy
import hashlib
import sys

from flask import Flask, jsonify
import pytest

from test_analysis_artifact_publication import load_functions, normalizers, publication, publish  # noqa: F401
from test_workflow_structured_flow import definition
from functions_workflow_definitions import (
    WorkflowDefinitionError, validate_workflow_publication_completion, workflow_definition_revision,
)
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_readiness import validate_publication_reference, workflow_outputs_ready, WorkflowOutputUnavailable
from functions_artifact_publication_readiness import (
    PUBLICATION_BINDING, PUBLICATION_PROCESSING, begin_publication_processing,
    finish_publication_processing, inspect_publication_readiness, public_publication_status,
)
from content_screening.access import public_document_payload, reject_screening_fields
from content_screening.contracts import DocumentHeldError, ScreeningValidationError


SOURCE_RECEIPT = {
    "producer": {"workflow_id": "workflow", "run_id": "run", "task_id": "analyze",
                 "node_id": "analyze", "execution_id": "a" * 64, "attempt": 1, "iteration_path": []},
    "output_name": "records", "result_ref": {"sha256": "b" * 64},
    "output_ref": {"sha256": "c" * 64}, "analysis_result": True,
}


def submit(fixture, policy="submitted", scope="personal", **kwargs):
    return publish(fixture, scope, completion_policy=policy, source_receipt=deepcopy(SOURCE_RECEIPT), **kwargs)


def receipt(fixture, result):
    return deepcopy(fixture.messages.records["artifact-1"]["metadata"][
        fixture.module.RECEIPTS_FIELD
    ][result["publication"]["id"]])


def document(fixture, result):
    return deepcopy(fixture.destinations[result["workspace_scope"]].records[result["document"]["id"]])


def request(fixture, result):
    saved = receipt(fixture, result)
    return {
        "publication": {"artifact_format": "md", **saved["destination"], "completion_policy": saved["completion_policy"]},
        "artifact_reference": {**saved["artifact_reference"], "producer": fixture.artifact["metadata"]["analysis_producer"]},
        "request_id": saved["request_id"], "receipt_id": saved["id"], "source_receipt": saved["source_receipt"],
    }


def observe(fixture, result, *, reconcile=False):
    return fixture.module.read_workflow_artifact_publication(
        "actor", request(fixture, result), reconcile=reconcile,
        execution_check=lambda: None,
    )


@pytest.mark.parametrize("policy", ["submitted", "approved", "indexed_ready"])
def test_additive_policy_is_strict_and_changes_authored_revision(policy):
    normalize = normalizers()["normalize_workflow_publication"]
    original = {"artifact_format": "md", "workspace_scope": "personal"}
    assert normalize(original) == original
    assert normalize({**original, "completion_policy": policy}) == {**original, "completion_policy": policy}
    workflow = definition()
    before = workflow_definition_revision(workflow)
    workflow["tasks"][0]["publication"] = {**original, "completion_policy": policy}
    compile_workflow_flow(workflow)
    assert workflow_definition_revision(workflow) != before
    for version in (1, 2):
        with pytest.raises(WorkflowDefinitionError, match="version-3"):
            validate_workflow_publication_completion({**workflow, "definition_version": version})
    with pytest.raises(WorkflowDefinitionError, match="version-3"):
        validate_workflow_publication_completion({**workflow, "durable_execution": False})


@pytest.mark.parametrize("policy", [None, "", True, 1, {}, [], "ready", "Submitted", " submitted "])
def test_unknown_policy_never_becomes_legacy_or_success(policy):
    with pytest.raises(WorkflowDefinitionError):
        normalizers()["normalize_workflow_publication"]({
            "artifact_format": "md", "workspace_scope": "personal", "completion_policy": policy,
        })


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
@pytest.mark.parametrize("policy", ["submitted", "approved", "indexed_ready"])
def test_levels_do_not_confuse_submission_approval_and_readiness(publication, scope, policy):
    result = submit(publication, policy, scope)
    status = result["publication"]
    assert status["submission"] == "confirmed"
    assert status["approval"] == ("not_required" if scope == "personal" else "pending")
    assert status["policy_satisfied"] is (policy == "submitted" or scope == "personal" and policy == "approved")
    assert status["index"] != "ready"
    expected = policy if status["policy_satisfied"] else "waiting_processing" if scope == "personal" else "waiting_approval"
    assert status["state"] == expected
    assert submit(publication, policy, scope)["publication"] == status
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["queue"]) == (1 if scope == "personal" else 0)
    assert len(publication.calls["notify"]) == (0 if scope == "personal" else 2)


def test_native_completion_and_full_exact_index_count_are_both_required(publication, tmp_path):
    result = submit(publication, "indexed_ready")
    target, saved = document(publication, result), receipt(publication, result)
    target["status"] = "Processing complete"
    target["percentage_complete"] = 100
    assert inspect_publication_readiness(saved, target)["processing"] == "not_started"
    source = tmp_path / "artifact.md"
    source.write_bytes(publication.state["content"])
    assert begin_publication_processing(target, source)
    running = document(publication, result)
    assert inspect_publication_readiness(saved, running)["processing"] == "running"
    with pytest.raises(RuntimeError, match="already"):
        begin_publication_processing(running, source)
    finish_publication_processing(running, indexed_chunks=3)
    complete = document(publication, result)
    reader = lambda *args, **kwargs: document(publication, result)
    partial = inspect_publication_readiness(saved, complete, available_reader=reader, index_count=lambda *args: 2)
    assert partial["processing"] == "complete" and partial["index"] == "pending"
    assert inspect_publication_readiness(
        saved, complete, available_reader=reader, index_count=lambda *args: 3,
    )["index"] == "ready"
    assert begin_publication_processing(complete, source) is False
    assert len(publication.calls["queue"]) == 1


def test_changed_native_input_is_rejected_before_indexing(publication, tmp_path):
    result = submit(publication, "indexed_ready")
    source = tmp_path / "changed.md"
    source.write_bytes(b"not the original artifact")
    with pytest.raises(ValueError, match="original artifact"):
        begin_publication_processing(document(publication, result), source)
    current = document(publication, result)
    status = inspect_publication_readiness(receipt(publication, result), current)
    assert status["processing"] == "failed" and status["reason_code"] == "publication_content_changed"


@pytest.mark.parametrize("state", [None, "future-state", 1])
def test_unknown_screening_state_is_explicitly_unavailable(publication, state):
    result = submit(publication, "indexed_ready")
    target = document(publication, result)
    target["content_screening"] = {"state": state}
    assert inspect_publication_readiness(receipt(publication, result), target)["reason_code"] == "publication_screening_unavailable"


@pytest.mark.parametrize("chunks", [0, None, True])
def test_empty_or_unproven_index_projection_is_not_ready(publication, chunks):
    result = submit(publication, "indexed_ready")
    target, saved = document(publication, result), receipt(publication, result)
    target[PUBLICATION_PROCESSING] = {"binding": target[PUBLICATION_BINDING], "state": "complete", "indexed_chunks": chunks}
    status = inspect_publication_readiness(saved, target, index_count=lambda *args: pytest.fail("No unproven Search read"))
    assert status["reason_code"] == "publication_no_indexed_content" and status["index"] == "unavailable"


@pytest.mark.parametrize("state,expected", [
    ("pending_scan", "pending"), ("publishing", "pending"), ("pending_review", "held"),
    ("scan_error", "held"), ("rejected", "rejected"),
])
def test_screening_holds_are_never_index_readiness(publication, state, expected):
    result = submit(publication, "indexed_ready")
    target = document(publication, result)
    target["content_screening"] = {"state": state}
    status = inspect_publication_readiness(
        receipt(publication, result), target, index_count=lambda *args: pytest.fail("Held content cannot qualify"),
    )
    assert status["screening"] == expected and status["index"] != "ready"


@pytest.mark.parametrize("state", ["cleared", "approved_with_flags"])
def test_screened_readiness_requires_unchanged_bytes_and_current_release(publication, state):
    result = submit(publication, "indexed_ready")
    target, saved = document(publication, result), receipt(publication, result)
    target.update(num_chunks=2, content_screening={
        "state": state, "source_revision": "1", "sanitized": False,
        "active_blob": {"content_hash": saved["content_sha256"]},
    })
    read = lambda *args, **kwargs: deepcopy(target)
    assert inspect_publication_readiness(saved, target, available_reader=read, index_count=lambda *args: 2)["index"] == "ready"
    target["content_screening"]["sanitized"] = True
    assert inspect_publication_readiness(saved, target)["reason_code"] == "publication_content_changed"
    target["content_screening"]["sanitized"] = False
    target["content_screening"]["active_blob"]["content_hash"] = "altered"
    assert inspect_publication_readiness(saved, target)["reason_code"] == "publication_content_changed"


@pytest.mark.parametrize("field,value", [("receipt_id", "wrong"), ("content_sha256", "wrong"), ("document_version", 2)])
def test_wrong_native_binding_cannot_satisfy_readiness(publication, field, value):
    result = submit(publication, "indexed_ready")
    target = document(publication, result)
    target[PUBLICATION_BINDING][field] = value
    assert inspect_publication_readiness(receipt(publication, result), target)["reason_code"] == "publication_revision_changed"


def test_changed_bytes_cannot_retarget_a_started_request(publication):
    first = submit(publication)
    artifact = deepcopy(publication.messages.records["artifact-1"])
    publication.state["content"] = b"changed bytes"
    artifact["metadata"]["generated_artifact_content_sha256"] = hashlib.sha256(publication.state["content"]).hexdigest()
    publication.messages.put(artifact)
    with pytest.raises(ValueError, match="different artifact bytes"):
        submit(publication)
    assert len(publication.calls["create"]) == 1
    assert first["document"]["id"] in publication.destinations["personal"].records


@pytest.mark.parametrize("failure", ["create_after", "prepare_after", "notification_after"])
def test_lost_submission_ack_is_reconciled_without_duplicate_documents_or_notices(publication, failure):
    publication.state["failure"] = failure
    first = submit(publication, "submitted", "group")
    second = submit(publication, "submitted", "group")
    assert first["publication"]["policy_satisfied"] and second["publication"]["policy_satisfied"]
    assert len(publication.calls["create"]) == 1 and len(publication.calls["notify"]) == 2


def test_unknown_queue_ack_needs_actual_native_evidence_not_a_status_string(publication, tmp_path):
    publication.state["failure"] = "queue_after"
    result = submit(publication)
    target = document(publication, result)
    target["status"] = "Content screening pending"
    publication.destinations["personal"].put(target)
    for _ in range(3):
        assert observe(publication, result, reconcile=True)["publication"]["state"] == "uncertain"
    source = tmp_path / "artifact.md"
    source.write_bytes(publication.state["content"])
    begin_publication_processing(target, source)
    assert observe(publication, result, reconcile=True)["publication"]["state"] == "submitted"
    assert len(publication.calls["queue"]) == 1


@pytest.mark.parametrize("scope", ["group", "public"])
def test_receipt_approval_is_durable_and_does_not_imply_indexed(publication, scope):
    result = submit(publication, "approved", scope)
    publication.state["group_role"] = "DocumentManager"
    publication.module.decide_artifact_publication("reviewer", document(publication, result), "approved")
    publication.module.decide_artifact_publication("reviewer", document(publication, result), "approved")
    status = observe(publication, result)["publication"]
    assert status["policy_satisfied"] and status["approval"] == "approved"
    assert status["index"] == "pending" and status["processing"] != "complete"
    assert len(publication.calls["queue"]) == 1
    assert len(publication.calls["notify"]) == 3
    with pytest.raises(ValueError, match="different"):
        publication.module.decide_artifact_publication("reviewer", document(publication, result), "rejected")


@pytest.mark.parametrize("choice", ["rejected", "cancelled"])
def test_negative_decision_survives_destination_deletion(publication, monkeypatch, choice):
    result = submit(publication, "indexed_ready", "group")
    publication.state["group_role"] = "DocumentManager"
    def delete(**kwargs):
        assert kwargs["delete_mode"] == "current_only"
        del publication.destinations["group"].records[kwargs["document_id"]]
    monkeypatch.setattr(sys.modules["functions_documents"], "delete_document_revision", delete, raising=False)
    publication.module.decide_artifact_publication("actor", document(publication, result), choice)
    status = observe(publication, result)["publication"]
    assert status["state"] == choice and not status["policy_satisfied"]
    assert submit(publication, "indexed_ready", "group")["publication"]["state"] == choice
    assert len(publication.calls["create"]) == 1 and not publication.calls["queue"]


def test_current_source_and_destination_authority_is_required_to_observe(publication):
    result = submit(publication, "approved", "group")
    publication.state["source_allowed"] = False
    with pytest.raises(PermissionError):
        observe(publication, result)
    publication.state["source_allowed"] = True
    publication.state["group_role"] = "Removed"
    with pytest.raises(PermissionError):
        observe(publication, result)
    assert len(publication.calls["create"]) == 1


def test_personal_destination_is_not_disclosed_to_another_workflow_viewer(publication):
    result = submit(publication)
    with pytest.raises(PermissionError, match="private"):
        publication.module.authorize_publication_status_read("another-member", result["publication"], actor_user_id="actor")


@pytest.mark.parametrize("policy", ["submitted", "approved"])
def test_weaker_policy_reports_actual_screening_without_waiting_for_it(publication, monkeypatch, policy):
    def queue(**kwargs):
        publication.calls["queue"].append(kwargs)
        target = publication.destinations["personal"].records[kwargs["document_id"]]
        target["content_screening"] = {"state": "pending_scan"}
        publication.destinations["personal"].put(target)
    monkeypatch.setattr(publication.module, "queue_generated_document_processing", queue)
    status = submit(publication, policy)["publication"]
    assert status["policy_satisfied"] is True
    assert status["screening"] == "pending"
    assert status["state"] == policy


def test_public_projection_excludes_private_ledger_and_destination_fields(publication):
    result = submit(publication)
    status = deepcopy(result["publication"])
    status.update(blob_path="private", source_receipt=SOURCE_RECEIPT)
    status["destination"]["secret"] = "private"
    public = public_publication_status(status)
    assert "blob_path" not in public and "source_receipt" not in public
    assert "secret" not in public["destination"]
    exposed_document = public_document_payload(document(publication, result))
    assert PUBLICATION_BINDING not in exposed_document and PUBLICATION_PROCESSING not in exposed_document


@pytest.mark.parametrize("field", [PUBLICATION_BINDING, PUBLICATION_PROCESSING])
def test_browser_cannot_supply_native_publication_evidence(field):
    with pytest.raises(ScreeningValidationError):
        reject_screening_fields({"nested": {field: {"state": "complete"}}})


def test_publication_poll_requeues_only_the_existing_observer():
    reference = {"kind": "artifact_publication", "version": 1, "execution_id": "a" * 64,
                 "attempt": 1, "request_id": "workflow-publication:v3:exact", "receipt_id": "b" * 64}
    assert workflow_outputs_ready({}, [reference], get_status=lambda *args: pytest.fail("Do not poll a tabular run"))
    for changed in ({**reference, "attempt": True}, {**reference, "version": 2}, {**reference, "blob_path": "private"}):
        with pytest.raises(WorkflowOutputUnavailable):
            validate_publication_reference(changed)


@pytest.mark.parametrize("stage,scope,effect,count", [
    ("create", "personal", "create", 0),
    ("prepare", "personal", "update", 0),
    ("queue", "personal", "queue", 0),
    ("workspace_notification", "group", "notify", 0),
    ("submitter_notification", "group", "notify", 1),
])
def test_ownership_loss_during_stage_claim_prevents_the_external_effect(
    publication, monkeypatch, stage, scope, effect, count,
):
    lost = {"value": False}
    original = publication.module._stage
    def claim(*args, **kwargs):
        acquired = original(*args, **kwargs)
        if args[2] == stage and not kwargs.get("complete"):
            lost["value"] = True
        return acquired
    def owned():
        if lost["value"]:
            raise RuntimeError("The workflow lost ownership.")
    monkeypatch.setattr(publication.module, "_stage", claim)
    with pytest.raises(RuntimeError, match="ownership"):
        submit(publication, "submitted", scope, execution_check=owned)
    assert len(publication.calls[effect]) == count


@pytest.mark.parametrize("scope", ["group", "public"])
@pytest.mark.parametrize("action,choice", [("approve", "approved"), ("deny", "rejected"), ("cancel", "cancelled")])
def test_existing_destination_routes_use_the_durable_receipt(publication, monkeypatch, scope, action, choice):
    result = submit(publication, "indexed_ready", scope)
    publication.state["group_role"] = "DocumentManager"
    actor = "actor" if action == "cancel" else "reviewer"
    target_id = result["document"]["id"]
    scope_id = f"fixed-{scope}"
    container = publication.destinations[scope]
    def delete(**kwargs):
        assert kwargs["document_id"] == target_id and kwargs["delete_mode"] == "current_only"
        del container.records[target_id]
    monkeypatch.setattr(sys.modules["functions_documents"], "delete_document_revision", delete, raising=False)
    def metadata(**kwargs):
        assert kwargs["document_id"] == target_id
        assert kwargs["group_id" if scope == "group" else "public_workspace_id"] == scope_id
        return deepcopy(container.records[target_id])
    def active_group(user, **kwargs):
        publication.module.assert_group_role(user, scope_id, **kwargs)
        return scope_id
    route_name = f"api_{action}_{scope}_generated_artifact"
    helpers = load_functions(f"route_backend_{scope}_documents.py", {route_name}, {
        "jsonify": jsonify, "get_current_user_id": lambda: actor,
        "require_active_group": active_group,
        "require_active_public_workspace": lambda user: (scope_id, {"id": scope_id, "name": "Target"}, "DocumentManager"),
        "find_group_by_id": lambda **kwargs: {"id": scope_id, "name": "Target"},
        "check_group_status_allows_operation": lambda *args: (True, ""),
        "check_public_workspace_status_allows_operation": lambda *args: (True, ""),
        "assert_group_role": publication.module.assert_group_role,
        "get_document_metadata": metadata,
        "decide_artifact_publication": publication.module.decide_artifact_publication,
        "_cleanup_group_generated_artifact_notifications": lambda *args: None,
        "_cleanup_public_generated_artifact_notifications": lambda *args: None,
        "invalidate_group_search_cache": lambda *args: None,
        "invalidate_public_workspace_search_cache": lambda *args: None,
    })
    app = Flask(__name__)
    app.add_url_rule("/decision", view_func=lambda: helpers[route_name](target_id), methods=["POST"])
    response = app.test_client().post("/decision", json={"group_id": "not-the-selected-destination"})
    assert response.status_code == 200, response.get_json()
    assert receipt(publication, result)["decision"]["choice"] == choice
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["queue"]) == (1 if choice == "approved" else 0)


def test_approval_rechecks_source_authority_after_byte_read(publication, monkeypatch):
    result = submit(publication, "approved", "group")
    publication.state["group_role"] = "DocumentManager"
    def revoked(*args):
        publication.state["source_allowed"] = False
        return publication.state["content"]
    monkeypatch.setattr(publication.module, "download_blob_content", revoked)
    with pytest.raises(PermissionError):
        publication.module.decide_artifact_publication("reviewer", document(publication, result), "approved")
    assert "decision" not in receipt(publication, result)
    assert not publication.calls["queue"]


def test_lost_approval_queue_ack_does_not_dispatch_a_second_job(publication, tmp_path):
    result = submit(publication, "indexed_ready", "group")
    publication.state["group_role"] = "DocumentManager"
    publication.state["failure"] = "queue_after"
    with pytest.raises(RuntimeError, match="confirmed"):
        publication.module.decide_artifact_publication("reviewer", document(publication, result), "approved")
    assert observe(publication, result)["publication"]["state"] == "approval_failed"
    source = tmp_path / "original.md"
    source.write_bytes(publication.state["content"])
    begin_publication_processing(document(publication, result), source)
    for _ in range(2):
        assert observe(publication, result, reconcile=True)["publication"]["state"] == "waiting_processing"
    assert len(publication.calls["queue"]) == 1


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
@pytest.mark.parametrize("valid_release", [False, True])
def test_native_screening_release_reconciles_an_unacknowledged_handoff(publication, monkeypatch, scope, valid_release):
    if scope == "personal":
        publication.state["failure"] = "queue_after"
    result = submit(publication, "indexed_ready", scope)
    if scope != "personal":
        publication.state["group_role"] = "DocumentManager"
        publication.state["failure"] = "queue_after"
        with pytest.raises(RuntimeError):
            publication.module.decide_artifact_publication("reviewer", document(publication, result), "approved")
    saved = receipt(publication, result)
    target = document(publication, result)
    assert PUBLICATION_PROCESSING not in target
    target.update(num_chunks=2, content_screening={
        "state": "cleared", "source_revision": str(saved["document_version"]),
        "active_blob": {"content_hash": saved["content_sha256"]}, "sanitized": False,
    })
    publication.destinations[scope].put(target)
    def available(*args, **kwargs):
        if not valid_release:
            raise DocumentHeldError()
        return document(publication, result)
    monkeypatch.setattr("functions_artifact_publication_readiness.assert_document_available", available)
    monkeypatch.setattr("functions_artifact_publication_readiness._index_count", lambda *args: 2)
    status = observe(publication, result, reconcile=True)["publication"]
    assert status["policy_satisfied"] is valid_release
    if valid_release:
        assert status["state"] == "indexed_ready" and status["unresolved_stages"] == []
        assert submit(publication, "indexed_ready", scope)["publication"]["policy_satisfied"]
    assert len(publication.calls["queue"]) == len(publication.calls["create"]) == 1


@pytest.mark.parametrize("read_number", [1, 2])
@pytest.mark.parametrize("field,value", [("is_current_version", False), ("search_visibility_state", "archived")])
def test_readiness_rejects_archival_on_either_fresh_read(publication, read_number, field, value):
    result = submit(publication, "indexed_ready")
    target = document(publication, result)
    target[PUBLICATION_PROCESSING] = {"binding": target[PUBLICATION_BINDING], "state": "complete", "indexed_chunks": 1}
    reads = {"count": 0}
    def read(*args, **kwargs):
        reads["count"] += 1
        current = deepcopy(target)
        if reads["count"] >= read_number:
            current[field] = value
        return current
    status = inspect_publication_readiness(
        receipt(publication, result), target, available_reader=read, index_count=lambda *args: 1,
    )
    assert status["reason_code"] == "publication_revision_changed" and status["index"] != "ready"
