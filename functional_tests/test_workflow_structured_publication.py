# test_workflow_structured_publication.py
"""
Native Analyze and publication service integration for structured workflows.
Version: 0.261.118
Implemented in: 0.261.116
Publication completion implemented in: 0.261.118

Actual final-checkpoint adaptation, result persistence, source-authorized joins,
task dispatch and publication receipts operate over fictional service doubles.
No Analyze origin flags are fabricated and no live document is published.
"""

import copy
import hashlib
import sys
from types import SimpleNamespace

import pytest

from test_analysis_artifact_publication import publication  # noqa: F401
from test_analyze_native_saved_integration import native, native_run  # noqa: F401
from test_analyze_backend_saved_integration import saved
from test_workflow_structured_flow import create_structured_runtime, definition
from test_workflow_task_result_handoff import build_inventory_run
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution import workflow_execution_scope
from functions_workflow_execution import WorkflowSuspended
from functions_workflow_runtime_store import WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result
from functions_workflow_result_store import WorkflowResultStore
from test_workflow_result_store import FakeBlobService
from functions_artifact_publication_readiness import begin_publication_processing, finish_publication_processing
from functions_workflow_readiness import workflow_outputs_ready


@pytest.fixture
def publication_flow(native_run, publication, monkeypatch, request):
    options = getattr(request, "param", None) or {}
    if isinstance(options, str):
        options = {"policy": options}
    workflow = definition()
    if options.get("continue_on_error"):
        workflow["error_handling"] = {"strategy": "continue", "retry_count": 0}
    workflow["tasks"][1]["output_contract"] = {"kind": "records"}
    workflow["tasks"][2].update(
        output_contract={"kind": "records"},
        document_action={"type": "analyze", "document_ids": ["native-source"]},
    )
    workflow["tasks"][0].update(
        publication={"artifact_format": "md", "workspace_scope": "personal"},
        output_contract={"kind": "json"},
    )
    if options.get("policy"):
        workflow["tasks"][0]["publication"]["completion_policy"] = options["policy"]
    scope = options.get("scope", "personal")
    workflow["tasks"][0]["publication"].update(
        workspace_scope=scope, **(
            {"group_id": "fixed-group"} if scope == "group" else
            {"public_workspace_id": "fixed-public"} if scope == "public" else {}
        ),
    )
    workflow["flow"]["nodes"][1]["join"]["exports"][0]["expected_kind"] = "records"
    workflow, store, container, _ = create_structured_runtime(workflow, monkeypatch)
    if options.get("storage") == "blob":
        blobs = FakeBlobService()
        configured = lambda *args, **kwargs: WorkflowResultStore(container, blobs, "private-chat-results")
        monkeypatch.setattr("functions_workflow_result_store._configured_store", configured)
        monkeypatch.setattr("functions_workflow_result_store._configured_result_store", configured)
    native_run.source["scope_id"] = "owner"
    native_run.run["user_id"] = "owner"
    monkeypatch.setitem(sys.modules, "functions_saved_analysis", saved)
    runner, _, _, _, _, _ = build_inventory_run()
    calls = []

    def source_resolver(ids, **kwargs):
        assert kwargs["user_id"] == "owner"
        return native_run.resolve(ids, **kwargs)

    def authorize(*args, **kwargs):
        return authorize_workflow_task_result_read(*args, source_resolver=source_resolver, **kwargs)

    def dispatch(execution_workflow, *args, **kwargs):
        calls.append(execution_workflow["active_task"]["id"])
        if calls[-1] == "classify":
            return {"reply": '{"pass":true}'}
        assert calls[-1] == "yes", "Publication must never invoke a model or run the unselected task."
        producer = execution_workflow["_analysis_producer"]
        analysis = native.adapt_native_analysis_result(
            user_id="owner", conversation_id="conversation-1", source=native_run.source,
            generated_outputs=[{"run_id": "native-run", "status": "completed"}],
            source_resolver=source_resolver, analysis_producer=producer,
        )
        assert len(analysis["authoritative_result"]["value"]) == 150
        artifact = copy.deepcopy(publication.artifact)
        artifact["metadata"].update(saved.analysis_artifact_metadata(producer))
        publication.state["content"] = analysis["analysis_reply"].encode("utf-8")
        artifact["metadata"]["generated_artifact_content_sha256"] = hashlib.sha256(publication.state["content"]).hexdigest()
        publication.messages.put(artifact)
        return {
            "reply": analysis["reply"], "analysis_result": analysis,
            "generated_analysis_artifacts": [{
                "artifact_message_id": artifact["id"], "conversation_id": "conversation-1",
                "output_format": "md", "capability": "analyze",
            }],
        }

    publication.conversations.put({"id": "conversation-1", "user_id": "owner"})
    publication.state["parents"] = []
    monkeypatch.setitem(sys.modules, "functions_artifact_publication", publication.module)
    monkeypatch.setitem(sys.modules, "functions_workflow_runner", SimpleNamespace(
        _workflow_task_run_item_id=runner["_workflow_task_run_item_id"],
    ))
    personal = sys.modules["functions_personal_workflows"]
    monkeypatch.setattr(personal, "get_personal_workflow", lambda user, key: copy.deepcopy(workflow) if user == "owner" and key == workflow["id"] else None, raising=False)
    monkeypatch.setattr(personal, "get_personal_workflow_run", lambda user, key: {
        "id": "run", "workflow_id": workflow["id"], "conversation_id": "conversation-1",
    } if user == "owner" and key == "run" else None, raising=False)
    monkeypatch.setattr(personal, "get_personal_workflow_run_item", lambda run_id, key: copy.deepcopy(container.items.get((run_id, key))), raising=False)
    monkeypatch.setitem(sys.modules, "functions_group_workflows", SimpleNamespace(
        get_group_workflow=lambda *args: None, get_group_workflow_run=lambda *args: None,
        get_group_workflow_run_item=lambda *args: None,
    ))
    monkeypatch.setattr("functions_workflow_runtime_store.workflow_runtime_store", lambda *args: store)
    monkeypatch.setattr(saved, "authorize_workflow_task_result_read", authorize)
    monkeypatch.setattr(publication.module, "authorize_analysis_artifact", saved.authorize_analysis_artifact)
    monkeypatch.setattr("functions_workflow_node_results.authorize_analysis_sources", lambda user, sources, **kwargs: (
        saved.authorize_analysis_sources(user, sources, resolver=source_resolver)
    ))
    runner.update(
        _execute_workflow_dispatch=dispatch,
        authorize_workflow_task_result_read=authorize,
        persist_workflow_task_result=persist_workflow_task_result,
    )

    def execute():
        with WorkflowRuntimeLease(store, owner_id="worker") as lease:
            controller = StructuredWorkflowExecution(store, lease, workflow, "run")
            with workflow_execution_scope(controller):
                return runner["_execute_workflow_task_sequence"](workflow, {}, "conversation-1", "run", None, {}, actor_user_id="owner")

    return SimpleNamespace(
        execute=execute, store=store, workflow=workflow, container=container, calls=calls,
        native_run=native_run, publication=publication, options=options,
    )


@pytest.mark.parametrize("publication_flow", [None, "submitted", "approved"], indirect=True)
def test_actual_native_result_publishes_once_through_an_explicit_join(publication_flow):
    fixture = publication_flow
    execute, calls, native_run, publication, workflow = (
        fixture.execute, fixture.calls, fixture.native_run, fixture.publication, fixture.workflow,
    )
    result = execute()
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert result["publication"]["state"] == fixture.options.get("policy", "queued")
    assert calls == ["classify", "yes"]
    assert native_run.reads == ["batch-1", "batch-2", "batch-3"]
    assert len(publication.calls["create"]) == len(publication.calls["queue"]) == 1
    assert publication.calls["queue"][0]["file_content_bytes"] == publication.state["content"]
    producer = result["task_results"][1]["workflow_result"]["producer"]
    assert producer["node_id"] == "yes-node" and producer["attempt"] == 1
    assert result["task_results"][1]["workflow_result"]["analysis_origin"] is True
    assert publication.messages.records["artifact-1"]["metadata"]["analysis_producer"]["execution_id"] == producer["execution_id"]
    replay = execute()
    assert replay["publication"] == result["publication"]
    assert calls == ["classify", "yes"] and len(publication.calls["create"]) == 1

    native_run.state["allowed"] = False
    before = copy.deepcopy(publication.calls)
    with pytest.raises(AnalysisResultUnavailable):
        publication.module.publish_workflow_analysis_artifact(
            "owner", publication=workflow["tasks"][0]["publication"],
            artifact_reference={
                "conversation_id": "conversation-1", "artifact_message_id": "artifact-1",
                "producer": {"kind": "workflow", **producer},
            }, request_id="forbidden-new-copy",
        )
    assert publication.calls == before


@pytest.mark.parametrize("publication_flow", [
    {"policy": "indexed_ready", "scope": scope, "storage": storage}
    for scope in ("personal", "group", "public") for storage in ("cosmos", "blob")
], indirect=True)
def test_native_publication_restarts_and_waits_for_exact_readiness(publication_flow, monkeypatch, tmp_path):
    fixture, publication = publication_flow, publication_flow.publication
    with pytest.raises(WorkflowSuspended):
        fixture.execute()
    first_control = fixture.store.read()
    assert first_control["state"] == "waiting_output" and first_control["lease"] is None
    first_gate = first_control["gate"]
    assert first_gate["execution_id"] and first_gate["attempt"] == 1 and first_gate["input_digest"]
    assert first_gate["iteration_path"] == []
    assert first_gate["publication"]["policy_satisfied"] is False
    assert first_gate["choices"] == []
    assert fixture.calls == ["classify", "yes"]
    assert len(publication.calls["create"]) == 1
    scope = fixture.options["scope"]
    container = publication.destinations[scope]
    target = copy.deepcopy(next(iter(container.records.values())))
    if scope != "personal":
        assert first_gate["publication"]["state"] == "waiting_approval"
        publication.state["group_role"] = "DocumentManager"
        publication.module.decide_artifact_publication("reviewer", target, "approved")
        target = copy.deepcopy(container.records[target["id"]])
    source = tmp_path / "actual-native-artifact.md"
    source.write_bytes(publication.state["content"])
    begin_publication_processing(target, source)
    finish_publication_processing(target, indexed_chunks=2)
    index = {"count": 1}
    monkeypatch.setattr("functions_artifact_publication_readiness._index_count", lambda *args: index["count"])

    def continue_run():
        control = fixture.store.read()
        assert workflow_outputs_ready(fixture.workflow, control["gate"]["references"])
        fixture.store.requeue_output(expected_version=control["version"], gate_id=control["gate"]["id"])
        return fixture.execute()

    for _ in range(2):
        with pytest.raises(WorkflowSuspended):
            continue_run()
        control = fixture.store.read()
        assert control["gate"]["publication"]["state"] == "waiting_index"
        assert control["gate"]["attempt"] == 1
        assert control["admitted_count"] == first_control["admitted_count"]
        assert control["deadline_at"] == first_control["deadline_at"]
    index["count"] = 2
    completed = continue_run()
    assert completed["workflow_outcome"] == {"status": "completed", "success": True}
    assert completed["publication"]["state"] == "indexed_ready"
    assert completed["publication"]["policy_satisfied"] is True
    assert completed["task_results"][-1]["workflow_result"]["result_ref"]["storage"] == fixture.options["storage"]
    assert fixture.calls == ["classify", "yes"]
    assert fixture.native_run.reads == ["batch-1", "batch-2", "batch-3"]
    assert len(publication.calls["create"]) == len(publication.calls["queue"]) == 1
    assert len(publication.calls["notify"]) == (0 if scope == "personal" else 3)


@pytest.mark.parametrize("publication_flow", [{"policy": "indexed_ready", "continue_on_error": True}], indirect=True)
def test_unmet_policy_pauses_instead_of_continue_on_error(publication_flow):
    fixture = publication_flow
    fixture.publication.state["failure"] = "queue_after"
    with pytest.raises(WorkflowSuspended):
        fixture.execute()
    control = fixture.store.read()
    assert control["state"] == "paused"
    assert control["gate"]["publication"]["state"] == "uncertain"
    assert control["gate"]["choices"] == ["resume", "cancel"]
    assert control["gate"]["publication"]["policy_satisfied"] is False
    for index in range(2):
        fixture.store.decide(
            expected_version=control["version"], gate_id=control["gate"]["id"], choice="resume",
            actor_user_id="owner", request_id=f"resume-publication-{index}",
        )
        with pytest.raises(WorkflowSuspended):
            fixture.execute()
        control = fixture.store.read()
        assert control["gate"]["attempt"] == 1
    assert fixture.calls == ["classify", "yes"]
    assert len(fixture.publication.calls["queue"]) == 1


@pytest.mark.parametrize("publication_flow", [
    {"policy": "submitted", "scope": scope, "storage": storage}
    for scope in ("group", "public") for storage in ("cosmos", "blob")
], indirect=True)
@pytest.mark.parametrize("decision", ["approved", "rejected", "cancelled", "deleted"])
def test_crash_after_success_preserves_the_achieved_publication_snapshot(publication_flow, monkeypatch, decision):
    fixture = publication_flow
    cache = StructuredWorkflowExecution.cache
    interrupted = {"value": False}
    class WorkerRestart(BaseException):
        pass
    def crash_before_cache(execution, key, value):
        if key == "task-result:report" and not interrupted["value"]:
            interrupted["value"] = True
            raise WorkerRestart()
        return cache(execution, key, value)
    monkeypatch.setattr(StructuredWorkflowExecution, "cache", crash_before_cache)
    with pytest.raises(WorkerRestart):
        fixture.execute()
    publication_row = next(
        row for row in fixture.container.items.values()
        if row.get("record_kind") == "execution" and row["payload"].get("task_id") == "report"
    )["payload"]
    assert publication_row["state"] == "succeeded"
    committed = copy.deepcopy(publication_row["workflow_result"])
    assert committed["publication"]["state"] == "submitted"
    assert committed["publication"]["approval"] == "pending"
    publication = fixture.publication
    publication.state["group_role"] = "DocumentManager"
    destination = publication.destinations[fixture.options["scope"]]
    target = copy.deepcopy(next(iter(destination.records.values())))
    def delete(**kwargs):
        assert kwargs["document_id"] == target["id"] and kwargs["delete_mode"] == "current_only"
        del destination.records[target["id"]]
    monkeypatch.setattr(sys.modules["functions_documents"], "delete_document_revision", delete, raising=False)
    if decision == "deleted":
        del destination.records[target["id"]]
    else:
        publication.module.decide_artifact_publication("owner" if decision == "cancelled" else "reviewer", target, decision)
    for _ in range(2):
        recovered = fixture.execute()
        assert recovered["workflow_outcome"] == {"status": "completed", "success": True}
        assert recovered["task_results"][-1]["workflow_result"] == committed
        assert recovered["publication"]["approval"] == "pending"
    assert fixture.calls == ["classify", "yes"]
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["queue"]) == (1 if decision == "approved" else 0)
