# test_workflow_structured_publication.py
"""
Native Analyze and publication service integration for structured workflows.
Version: 0.261.116
Implemented in: 0.261.116

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
from functions_workflow_runtime_store import WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result


def test_actual_native_result_publishes_once_through_an_explicit_join(native_run, publication, monkeypatch):
    workflow = definition()
    workflow["tasks"][1]["output_contract"] = {"kind": "records"}
    workflow["tasks"][2].update(
        output_contract={"kind": "records"},
        document_action={"type": "analyze", "document_ids": ["native-source"]},
    )
    workflow["tasks"][0].update(
        publication={"artifact_format": "md", "workspace_scope": "personal"},
        output_contract={"kind": "json"},
    )
    workflow["flow"]["nodes"][1]["join"]["exports"][0]["expected_kind"] = "records"
    workflow, store, container, _ = create_structured_runtime(workflow, monkeypatch)
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

    result = execute()
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert result["publication"]["state"] == "queued"
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
