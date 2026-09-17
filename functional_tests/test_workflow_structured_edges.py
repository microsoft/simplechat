# test_workflow_structured_edges.py
"""
Regression coverage for M4A schema, limits, source snapshots and exact gates.
Version: 0.261.116
Implemented in: 0.261.116

Exercises production code through isolated existing storage and dispatcher
fixtures. No workflow, document, model or publication service is invoked live.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production helpers follow the worktree path setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_bindings import WorkflowInputError, load_workflow_reference
from functions_workflow_definitions import WorkflowDefinitionError
from functions_workflow_execution import WorkflowSuspended, workflow_execution_scope
from functions_workflow_execution_history import workflow_execution_history
from functions_workflow_flow import compile_workflow_flow, evaluate_predicate, normalize_predicate
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution
from test_workflow_definition_store_integration import load_group_store, load_personal_store
from test_workflow_structured_flow import definition, runtime, run_flow  # noqa: F401
from test_workflow_task_result_handoff import build_inventory_run
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_v3_save_roundtrips_nested_limits_and_server_metadata(scope):
    helpers, container, _ = load_group_store() if scope == "group" else load_personal_store()
    payload = {
        **definition(), "name": "Structured audit", "trigger_type": "manual",
        "limits": {"max_executions": 17, "deadline_seconds": 900},
    }
    save = helpers["save_group_workflow"] if scope == "group" else helpers["save_personal_workflow"]
    scope_id = "group-one" if scope == "group" else "owner"
    saved = save(scope_id, payload, "owner")
    key = (scope_id, saved["id"])
    container.items[key]["metadata"] = {"retained": "existing non-executable settings"}
    loaded = helpers["get_group_workflow" if scope == "group" else "get_personal_workflow"](scope_id, saved["id"])
    updated = save(scope_id, {**loaded, "description": "Edited safely"}, "owner")
    assert updated["limits"] == payload["limits"]
    assert "max_executions" not in updated and "deadline_seconds" not in updated
    assert updated["flow"] == saved["flow"] and updated["tasks"] == saved["tasks"]
    assert updated["metadata"] == loaded["metadata"]
    assert updated["created_at"] == saved["created_at"]
    assert updated["definition_revision"] != saved["definition_revision"]
    with pytest.raises(WorkflowDefinitionError):
        save(scope_id, {**updated, "future_executable": {"jump": "unknown"}}, "owner")


@pytest.mark.parametrize("change", [
    {"limits": None}, {"limits": {"max_executions": False}},
    {"limits": {"max_executions": 5001}}, {"limits": {"deadline_seconds": 0}},
    {"limits": {"deadline_seconds": 1.5}}, {"limits": {"future_budget": 3}},
    {"max_executions": 3}, {"deadline_seconds": 3},
])
def test_only_canonical_bounded_limits_are_accepted(change):
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow({**definition(), **change})


def test_conditions_reject_undeclared_or_nonscalar_fields_and_wrong_numeric_types():
    for field in ("/not_declared", ""):
        workflow = definition()
        workflow["flow"]["nodes"][1]["condition"]["left"]["path"] = field
        with pytest.raises(WorkflowDefinitionError):
            compile_workflow_flow(workflow)
    workflow = definition()
    workflow["flow"]["nodes"][1]["condition"]["op"] = "gt"
    workflow["flow"]["nodes"][1]["condition"]["right"] = {"literal": 1}
    with pytest.raises(WorkflowDefinitionError, match="numeric"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("value,expected", [(None, False), (0, False), (4, True)])
def test_null_guard_remains_distinct_from_missing_and_numeric_values(value, expected):
    condition = normalize_predicate({
        "op": "all", "conditions": [
            {"op": "exists", "value": {"input": "data", "path": "/quantity"}},
            {"op": "ne", "left": {"input": "data", "path": "/quantity"}, "right": {"literal": None}},
            {"op": "gt", "left": {"input": "data", "path": "/quantity"}, "right": {"literal": 0}},
        ],
    }, [{"name": "data"}])
    assert evaluate_predicate(condition, {"data": {"quantity": value}}) is expected
    assert evaluate_predicate(condition, {"data": {}}) is False


def test_shared_reference_snapshot_is_run_scoped_and_reauthorized_after_restart(runtime):
    workflow, store, _, clock = runtime
    reference = {"id": "criteria", "name": "criteria", "document_id": "source", "scope_type": "personal", "scope_id": "owner"}
    state = {"version": "v1", "allowed": True, "reads": 0}

    def resolve(**kwargs):
        assert kwargs["document_id"] == "source" and kwargs["user_id"] == "owner"
        if not state["allowed"]:
            raise AnalysisResultUnavailable()
        return {"scope": "personal", "document": {"id": "source", "user_id": "owner", "_etag": state["version"]}}

    def chunks(**kwargs):
        state["reads"] += 1
        return {
            "scope": "personal", "scope_id": "owner", "returned_chunk_count": 1, "chunk_count": 1,
            "chunks": [{"chunk_text": f"Frozen criteria {state['version']}"}],
        }

    def read(**kwargs):
        return load_workflow_reference(workflow, reference, actor_user_id="owner", resolve_document=resolve, load_chunks=chunks, **kwargs)

    with WorkflowRuntimeLease(store, owner_id="first") as lease:
        controller = StructuredWorkflowExecution(store, lease, workflow, "run")
        controller.set_node(workflow["flow"]["nodes"][0], "root")
        with workflow_execution_scope(controller):
            original = controller.freeze_reference(reference, read)
    clock.advance()
    with WorkflowRuntimeLease(store, owner_id="second") as lease:
        controller = StructuredWorkflowExecution(store, lease, workflow, "run")
        controller.set_node(workflow["flow"]["nodes"][-1], "root")
        with workflow_execution_scope(controller):
            assert controller.freeze_reference(reference, read) == original
            assert state["reads"] == 1
            state["version"] = "v2"
            with pytest.raises(WorkflowInputError, match="changed"):
                controller.freeze_reference(reference, read)
            state["version"], state["allowed"] = "v1", False
            with pytest.raises(AnalysisResultUnavailable):
                controller.freeze_reference(reference, read)


def test_approval_history_rechecks_predicate_and_shared_reference_sources(runtime, monkeypatch):
    workflow, store, _, _ = runtime
    with pytest.raises(SystemExit):
        run_flow(workflow, store, crash_after_choice=True)
    producer = next(item for item in store.journal_page("execution")["items"] if item["node_id"] == "classify-node")["workflow_result"]
    receipt = {
        "producer": producer["producer"], "result_ref": producer["result_ref"],
        "output_name": "json", "output_ref": producer["outputs"]["json"]["result_ref"],
    }
    node = workflow["flow"]["nodes"][-1]
    with WorkflowRuntimeLease(store, owner_id="gate-owner") as lease:
        controller = StructuredWorkflowExecution(store, lease, workflow, "run")
        controller.set_node(node, "root")
        with workflow_execution_scope(controller), pytest.raises(WorkflowSuspended):
            controller.run_unit(
                "task:report", lambda: pytest.fail("Approval must precede effects."),
                inputs={"consumed_inputs": [receipt], "references": [{
                    "document_id": "criteria", "scope_type": "personal", "scope_id": "owner", "source_version": 1,
                }]}, approval={"required": True},
            )
    gate = store.read()["gate"]
    execution = store.journal_read("execution", gate["execution_id"])["payload"]
    assert execution["consumed_inputs"] == [receipt]
    assert execution["reference_sources"][0]["document_id"] == "criteria"
    monkeypatch.setattr("functions_workflow_execution_history.workflow_runtime_store", lambda *_: store)
    monkeypatch.setattr("functions_workflow_execution_history.authorize_analysis_sources", lambda *args, **kwargs: (_ for _ in ()).throw(AnalysisResultUnavailable()))
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(workflow, "run", reader_user_id="owner")


def test_invalid_selected_output_is_visible_in_exact_attempt_history(runtime):
    workflow, store, _, _ = runtime
    runner, _, _, _, _, _ = build_inventory_run()
    runner.update({
        "_execute_workflow_dispatch": lambda *args, **kwargs: {"reply": "Not the required JSON object."},
        "persist_workflow_task_result": persist_workflow_task_result,
        "authorize_workflow_task_result_read": authorize_workflow_task_result_read,
    })
    with WorkflowRuntimeLease(store, owner_id="invalid-task") as lease:
        controller = StructuredWorkflowExecution(store, lease, workflow, "run")
        with workflow_execution_scope(controller):
            result = runner["_execute_workflow_task_sequence"](workflow, {}, "conversation", "run", None, {})
    assert result["workflow_outcome"] == {"status": "invalid", "success": False}
    execution = store.journal_page("execution")["items"][0]
    assert execution["state"] == "invalid"
    attempts = store.journal_page("attempt", execution_id=execution["execution_id"])["items"]
    assert attempts[0]["workflow_validation"]["status"] == "invalid"
    assert attempts[0]["workflow_result"]["producer"]["attempt"] == 1


def test_deadline_expiration_is_idempotent_and_cannot_resume(runtime):
    _, store, _, clock = runtime
    with WorkflowRuntimeLease(store, owner_id="waiting") as lease:
        store.wait(lease.token, state="waiting_approval", gate={"id": "gate", "kind": "approval", "choices": ["approve", "reject"]})
    clock.now = clock.now.replace(year=clock.now.year + 1)
    expired = store.expire_deadline()
    again = store.expire_deadline()
    assert expired == again and expired["state"] == "paused"
    assert expired["gate"]["choices"] == ["cancel"]
    with pytest.raises(WorkflowRuntimeConflict):
        store.resume(expected_version=expired["version"], actor_user_id="owner", request_id="reset")
    assert store.read()["deadline_at"] == expired["deadline_at"]


def test_restart_after_completed_skip_does_not_create_task_attempts(runtime):
    workflow, store, _, clock = runtime
    run_flow(workflow, store)
    skipped = next(item for item in store.journal_page("execution")["items"] if item["state"] == "skipped")
    assert skipped["attempt"] == 0
    assert store.journal_page("attempt", execution_id=skipped["execution_id"])["items"] == []
    admitted = store.read()["admitted_count"]
    clock.advance()
    _, calls = run_flow(workflow, store)
    assert not calls and store.read()["admitted_count"] == admitted
    assert store.journal_page("attempt", execution_id=skipped["execution_id"])["items"] == []
