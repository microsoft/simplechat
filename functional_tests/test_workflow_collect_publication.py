# test_workflow_collect_publication.py
"""
Functional tests for real Collect-to-shared-export-to-publication execution.
Version: 0.261.119
Implemented in: 0.261.119

Native per-document results, frozen iteration, schema-2 replay, both result
backends, shared JSON rendering and the existing destination ledger execute
against closed stores. No live documents, permissions, workflows or models.
"""

from copy import deepcopy
import hashlib
import json

import pytest

from test_analyze_native_saved_integration import native_run
from test_analysis_artifact_publication import publication, normalizers
from test_workflow_loop_native_analysis import native_loop_flow
from test_workflow_saved_output_artifacts import artifact_services, saved_output_artifact
from test_workflow_for_each_execution import loop_definition
from functions_analysis_access import AnalysisResultUnavailable
from functions_artifact_publication_readiness import begin_publication_processing, finish_publication_processing
from functions_workflow_definitions import WorkflowDefinitionError
from functions_workflow_execution import WorkflowSuspended
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_identity import workflow_execution_id
from functions_workflow_node_results import open_workflow_record_input
from functions_workflow_readiness import workflow_outputs_ready


def publication_config(policy="submitted", scope="personal"):
    return {
        "source_kind": "saved_output", "artifact_format": "json", "workspace_scope": scope,
        **({"completion_policy": policy} if policy else {}),
        **({"group_id": "fixed-group"} if scope == "group" else {}),
        **({"public_workspace_id": "fixed-public"} if scope == "public" else {}),
    }


@pytest.mark.parametrize("native_loop_flow", [
    {"storage": storage, "join": join, "publication": publication_config()}
    for storage in ("cosmos", "blob") for join in (False, True)
], indirect=True)
def test_reloaded_native_collect_publishes_without_reanalysis(artifact_services, native_loop_flow):
    fixture, services = native_loop_flow, artifact_services
    services.bind(fixture["workflow"], fixture["store"])
    execute = fixture["execute"]

    def interrupt():
        raise SystemExit("closed-fixture restart after exact Collect, before file output")

    with pytest.raises(SystemExit):
        execute(before_publication=interrupt)
    assert len(fixture["calls"]) == 2 and len(fixture["native_run"].reads) == 6
    assert services.blobs.writes == 0
    completed = execute()
    assert completed["workflow_outcome"] == {"status": "completed", "success": True}
    assert completed["publication"]["policy_satisfied"] is True
    assert completed["publication"]["state"] == "submitted"
    file_card = completed["generated_tabular_outputs"][-1]
    assert file_card["capability"] == "file_export" and file_card["row_count"] == 300
    assert file_card["source_kind"] == "workflow_saved_output"
    assert not ({"blob_path", "blob_container", "source_binding", "analysis_producer"} & file_card.keys())
    artifact = services.publication.messages.records[file_card["artifact_message_id"]]
    binding = artifact["metadata"]["generated_artifact_source"]
    assert binding["producer"]["node_id"] == ("selected" if fixture["options"]["join"] else "collect")
    assert "task_id" not in binding["producer"]
    assert not artifact["metadata"].get("analysis_result_required")
    content = services.blobs.data[(artifact["blob_container"], artifact["blob_path"])]
    rows = json.loads(content)
    assert len(rows) == 300
    assert [record["values"] for record in rows[:150]] == fixture["native_run"].rows
    assert {record["document_id"] for record in rows[:150]} == {"native-source-a"}
    assert {record["document_id"] for record in rows[150:]} == {"native-source-b"}
    assert artifact["metadata"]["generated_artifact_content_sha256"] == hashlib.sha256(content).hexdigest()
    assert services.publication.calls["queue"][0]["file_content_bytes"] == content
    receipt = completed["_publication_request"]["source_receipt"]
    assert receipt["result_ref"]["storage"] == fixture["options"]["storage"]
    reader = open_workflow_record_input(
        fixture["workflow"], "run", receipt["producer"], receipt["result_ref"],
        output_name=receipt["output_name"],
    )
    assert not reader.manifest.get("analysis_origin")
    before = deepcopy(services.publication.calls)
    assert execute()["publication"] == completed["publication"]
    assert services.publication.calls["create"] == before["create"]
    assert services.publication.calls["queue"] == before["queue"]
    assert services.blobs.writes == 1
    assert len(fixture["calls"]) == 2 and len(fixture["native_run"].reads) == 6

    fixture["allowed"]["native-source-b"] = False
    with pytest.raises((PermissionError, AnalysisResultUnavailable, ValueError)):
        services.download("owner", "conversation-1", file_card["artifact_message_id"])
    assert len(services.publication.calls["create"]) == 1


@pytest.mark.parametrize("native_loop_flow", [
    {"storage": storage, "publication": publication_config("indexed_ready", scope)}
    for storage in ("cosmos", "blob") for scope in ("personal", "group", "public")
], indirect=True)
def test_generic_publication_reuses_native_readiness_and_completion(artifact_services, native_loop_flow, monkeypatch, tmp_path):
    fixture, services = native_loop_flow, artifact_services
    publication = services.publication
    services.bind(fixture["workflow"], fixture["store"])
    with pytest.raises(WorkflowSuspended):
        fixture["execute"]()
    initial = fixture["store"].read()
    assert initial["state"] == "waiting_output"
    scope = fixture["options"]["publication"]["workspace_scope"]
    document = deepcopy(next(iter(publication.destinations[scope].records.values())))
    if scope != "personal":
        assert initial["gate"]["publication"]["state"] == "waiting_approval"
        publication.state["group_role"] = "DocumentManager"
        publication.module.decide_artifact_publication("reviewer", document, "approved")
        document = deepcopy(publication.destinations[scope].records[document["id"]])
    artifact = next(item for item in publication.messages.records.values()
                    if item.get("metadata", {}).get("generated_artifact_source_required"))
    content = services.blobs.data[(artifact["blob_container"], artifact["blob_path"])]
    path = tmp_path / "accepted-records.json"
    path.write_bytes(content)
    begin_publication_processing(document, path)
    finish_publication_processing(document, indexed_chunks=2)
    indexed = {"count": 1}
    monkeypatch.setattr("functions_artifact_publication_readiness._index_count", lambda *args: indexed["count"])

    def resume():
        control = fixture["store"].read()
        assert workflow_outputs_ready(fixture["workflow"], control["gate"]["references"])
        fixture["store"].requeue_output(expected_version=control["version"], gate_id=control["gate"]["id"])
        return fixture["execute"]()

    for _ in range(2):
        with pytest.raises(WorkflowSuspended):
            resume()
        gate = fixture["store"].read()
        assert gate["gate"]["publication"]["state"] == "waiting_index"
        assert gate["admitted_count"] == initial["admitted_count"]
        assert gate["deadline_at"] == initial["deadline_at"]
        assert gate["gate"]["attempt"] == 1
    indexed["count"] = 2
    result = resume()
    assert result["publication"]["state"] == "indexed_ready" and result["publication"]["policy_satisfied"]
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert publication.calls["queue"][0]["file_content_bytes"] == content
    assert len(publication.calls["queue"]) == len(publication.calls["create"]) == 1
    assert services.blobs.writes == 1
    assert len(fixture["calls"]) == 2
    assert len(publication.calls["notify"]) == (0 if scope == "personal" else 3)
    snapshot = deepcopy(result["publication"])
    indexed["count"] = 0
    assert fixture["execute"]()["publication"] == snapshot


@pytest.mark.parametrize("policy", [None, "submitted", "approved"])
@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_non_analyze_records_use_the_same_receipts_and_explicit_policy(saved_output_artifact, policy, scope):
    fixture = saved_output_artifact
    artifact = fixture.materialize()
    publication = fixture.services.publication
    request = {
        "publication": publication_config(policy, scope),
        "artifact_reference": {
            "conversation_id": "conversation-1", "artifact_message_id": artifact["artifact_message_id"],
            "producer": {"kind": "workflow_saved_output", **fixture.receipt["producer"]},
        },
        "request_id": "workflow-publication:v3:publisher:collect:1",
        "source_receipt": fixture.receipt,
    }
    result = publication.module.publish_workflow_artifact("owner", **request)
    if scope == "personal":
        assert result["publication"]["state"] == (policy or "queued")
    elif policy == "approved":
        assert result["publication"]["state"] == "waiting_approval"
    else:
        assert result["publication"]["state"] == (policy or "pending_approval")
    assert len(publication.calls["create"]) == 1
    retry = publication.module.publish_workflow_artifact("owner", **request)
    assert retry["publication"] == result["publication"]
    assert len(publication.calls["create"]) == 1
    if scope != "personal":
        publication.state["group_role"] = "DocumentManager"
        document = deepcopy(next(iter(publication.destinations[scope].records.values())))
        assert document["generated_artifact_publication_binding"]["receipt_id"] == result["publication"]["id"]
        publication.module.decide_artifact_publication("reviewer", document, "approved")
        publication.module.decide_artifact_publication("reviewer", deepcopy(publication.destinations[scope].records[document["id"]]), "approved")
    assert len(publication.calls["queue"]) == 1


@pytest.mark.parametrize("native_loop_flow", [{"publication": publication_config("indexed_ready")}], indirect=True)
def test_lost_queue_ack_preserves_artifact_and_destination_without_unbounded_retry(artifact_services, native_loop_flow):
    fixture, services = native_loop_flow, artifact_services
    services.bind(fixture["workflow"], fixture["store"])
    services.publication.state["failure"] = "queue_after"
    with pytest.raises(WorkflowSuspended):
        fixture["execute"]()
    control = fixture["store"].read()
    assert control["state"] == "paused"
    assert control["gate"]["publication"]["state"] == "uncertain"
    for index in range(2):
        fixture["store"].decide(
            expected_version=control["version"], gate_id=control["gate"]["id"],
            choice="resume", actor_user_id="owner", request_id=f"resume-{index}",
        )
        with pytest.raises(WorkflowSuspended):
            fixture["execute"]()
        control = fixture["store"].read()
    assert len(services.publication.calls["create"]) == len(services.publication.calls["queue"]) == 1
    assert services.blobs.writes == 1 and len(fixture["calls"]) == 2
    assert control["gate"]["attempt"] == 1


@pytest.mark.parametrize("native_loop_flow", [
    {"publication": publication_config(), "partial": True, "accept_partial": accept}
    for accept in (False, True)
], indirect=True)
def test_runner_uses_the_explicit_partial_input_policy(artifact_services, native_loop_flow):
    fixture, services = native_loop_flow, artifact_services
    services.bind(fixture["workflow"], fixture["store"])
    if fixture["options"]["accept_partial"]:
        result = fixture["execute"]()
        assert result["workflow_outcome"]["status"] == "completed_partial"
        assert result["publication"]["policy_satisfied"]
        card = result["generated_tabular_outputs"][-1]
        assert card["row_count"] == 150 and "accepted_partial" in card["summary"]
        assert services.blobs.writes == 1
    else:
        with pytest.raises(WorkflowSuspended):
            fixture["execute"]()
        assert fixture["store"].read()["state"] == "paused"
        assert services.blobs.writes == 0 and not services.publication.calls["create"]
    assert len(fixture["calls"]) == 1


@pytest.mark.parametrize("policy", [None, "submitted"])
@pytest.mark.parametrize("stage,scope,effect,count", [
    ("create", "group", "create", 0),
    ("prepare", "group", "update", 0),
    ("queue", "personal", "queue", 0),
    ("workspace_notification", "group", "notify", 0),
    ("submitter_notification", "group", "notify", 1),
])
@pytest.mark.parametrize("revocation", ["source", "destination"])
def test_generic_publication_reauthorizes_after_stage_claims(
    saved_output_artifact, monkeypatch, policy, stage, scope, effect, count, revocation,
):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    publication = services.publication
    original = publication.module._stage

    def claimed(*args, **kwargs):
        acquired = original(*args, **kwargs)
        if args[2] == stage and not kwargs.get("complete"):
            if revocation == "source" or scope == "personal":
                services.state["workflow_allowed"] = False
            else:
                publication.state["workspace_status"] = "locked"
        return acquired

    monkeypatch.setattr(publication.module, "_stage", claimed)
    with pytest.raises((PermissionError, AnalysisResultUnavailable)):
        publication.module.publish_workflow_artifact(
            "owner", publication=publication_config(policy, scope),
            artifact_reference={
                "conversation_id": "conversation-1", "artifact_message_id": artifact["artifact_message_id"],
                "producer": {"kind": "workflow_saved_output", **fixture.receipt["producer"]},
            },
            request_id="closed-stage-race", source_receipt=fixture.receipt,
        )
    assert len(publication.calls[effect]) == count
    assert services.blobs.writes == 1


@pytest.mark.parametrize("boundary", ["byte_read", "decision", "approval_queue"])
def test_generic_approval_rechecks_source_before_each_handoff(saved_output_artifact, monkeypatch, boundary):
    fixture, services = saved_output_artifact, saved_output_artifact.services
    artifact = fixture.materialize()
    publication = services.publication
    result = publication.module.publish_workflow_artifact(
        "owner", publication=publication_config("indexed_ready", "group"),
        artifact_reference={
            "conversation_id": "conversation-1", "artifact_message_id": artifact["artifact_message_id"],
            "producer": {"kind": "workflow_saved_output", **fixture.receipt["producer"]},
        },
        request_id="closed-approval-race", source_receipt=fixture.receipt,
    )
    publication.state["group_role"] = "DocumentManager"
    document = deepcopy(next(iter(publication.destinations["group"].records.values())))
    assert document["generated_artifact_publication_receipt_id"] == result["publication"]["id"]
    if boundary == "byte_read":
        services.blobs.read_hook = lambda: services.state.update(workflow_allowed=False)
    elif boundary == "decision":
        original = publication.module._receipt_change

        def decision(*args, **kwargs):
            receipt, changed = original(*args, **kwargs)
            if changed and (receipt.get("decision") or {}).get("choice") == "approved":
                services.state["workflow_allowed"] = False
            return receipt, changed

        monkeypatch.setattr(publication.module, "_receipt_change", decision)
    else:
        original = publication.module._stage

        def queue_claim(*args, **kwargs):
            changed = original(*args, **kwargs)
            if args[2] == "approval_queue" and not kwargs.get("complete"):
                services.state["workflow_allowed"] = False
            return changed

        monkeypatch.setattr(publication.module, "_stage", queue_claim)
    with pytest.raises((PermissionError, RuntimeError)):
        publication.module.decide_artifact_publication("reviewer", document, "approved")
    assert publication.calls["queue"] == []
    current = publication.destinations["group"].records[document["id"]]
    assert current["generated_artifact_promotion_status"] == (
        "approval_failed" if boundary == "approval_queue" else "pending_approval"
    )


def test_publication_source_normalization_preserves_omission_and_rejects_unknown():
    normalize = normalizers()["normalize_workflow_publication"]
    native = {"artifact_format": "md", "workspace_scope": "personal"}
    assert normalize(native) == native
    assert normalize({**native, "source_kind": "native_analysis"})["source_kind"] == "native_analysis"
    assert normalize(publication_config()) == publication_config()
    for value in (None, "", "inferred", True):
        with pytest.raises(ValueError):
            normalize({**native, "source_kind": value})
    for value in ("md", "csv", "xml", "docx", "pdf", "pptx"):
        with pytest.raises(ValueError):
            normalize({**publication_config(), "artifact_format": value})


@pytest.mark.parametrize("mutation", [
    lambda wf: wf["tasks"][-1]["publication"].update(artifact_format="csv"),
    lambda wf: wf["tasks"][-1]["inputs"][0].update(required=False),
    lambda wf: wf["tasks"][-1]["inputs"][0].update(expected_kind="json"),
    lambda wf: wf["tasks"][-1]["inputs"].clear(),
    lambda wf: wf["tasks"][-1]["inputs"][0]["source"].update(output="text"),
    lambda wf: wf["tasks"][-1]["publication"].update(source_kind=None),
    lambda wf: wf.update(durable_execution=False),
])
def test_invalid_generic_source_contract_fails_in_the_compiler(mutation):
    workflow = loop_definition()
    workflow["tasks"].append({
        "id": "publish", "type": "instructions", "instructions": "Publish exact records.", "name": "Publish",
        "runner": {"type": "inherit"}, "document_action": {"type": "none"},
        "publication": publication_config(), "output_contract": {"kind": "json"},
        "inputs": [{
            "name": "deliverable",
            "source": {"kind": "node_output", "node_id": "collect", "output": "records"},
            "required": True, "expected_kind": "records",
        }],
    })
    workflow["flow"]["nodes"].append({"id": "publish-node", "kind": "task", "task_id": "publish"})
    compile_workflow_flow(workflow)
    mutation(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
