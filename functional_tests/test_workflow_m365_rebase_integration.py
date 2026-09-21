# test_workflow_m365_rebase_integration.py
"""
Functional regressions for Development M365 and native/durable workflow integration.
Version: 0.261.122
Implemented in: 0.261.122

Real definition CAS, durable controllers, dispatch, result storage, and repeated
task identities run against isolated stores. Microsoft 365 interaction and model
I/O are closed boundaries; no external account or service is contacted.
"""

import ast
import copy
from contextlib import nullcontext
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from test_workflow_definition_store_integration import (
    WorkflowContainer, definition, load_group_store, load_personal_store,
)
from test_workflow_runtime_integration import integration
from test_workflow_repeat_dispatcher import dispatch, production_dispatcher
from test_workflow_repeat_execution import repeat_runtime
from test_workflow_repeat_schema import repeat_definition
from functions_m365_approvals import M365ApprovalRequired, M365PolicyError
from functions_m365_workflow_binding import (
    build_waiting_workflow_result, normalize_workflow_run_as, workflow_execution_fingerprint,
    workflow_result_is_waiting, workflow_result_runtime_status,
)
from functions_workflow_definition_store import save_workflow_definition_record, update_workflow_runtime_record
from functions_workflow_definitions import WorkflowDefinitionConflict
from functions_workflow_execution import current_workflow_execution
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result
from functions_workflow_runtime_store import WorkflowRuntimeConflict
from m365_interaction import M365_AUTH_INTERACTION_CODES, M365SignInRequired
import functions_workflow_runtime as runtime


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("durable", [False, True])
def test_m365_scheduler_uses_the_leased_engine_only_for_durable_workflows(group, durable):
    workflow = {
        "id": "workflow", "user_id": "owner", "group_id": "group" if group else "",
        "durable_execution": durable, "active_run_id": "run",
        "status": "awaiting_sign_in", "m365_run_as_user_id": "reader",
    }
    job = {
        "workflow_ref": {"workflow_id": "workflow"}, "run_id": "run",
        "user_id": "reader", "actor_user_id": "owner",
    }
    result = build_waiting_workflow_result(
        workflow, {"id": "run"}, {"status": "awaiting_sign_in"},
    )
    resume_durable, resume_legacy = Mock(return_value=result), Mock(return_value=result)
    release_lock, update_fields = Mock(), Mock()
    lock = {"id": "workflow-lease"}

    def dispatch_jobs(container, approvals, *, execute, can_resume, **kwargs):
        assert can_resume(job, None)
        return execute(job)

    names = (
        "configure_m365_execution", "configure_m365_connection_authorization",
        "configure_m365_file_runtime", "configure_m365_pending_delivery_runtime",
        "dispatch_due_m365_deliveries", "validate_m365_approval_decision",
        "validate_m365_workflow_execution", "resolve_m365_action_config",
        "resolve_m365_workflow_binding", "resolve_m365_action_selection",
        "validate_m365_workflow_context", "log_event",
    )
    namespace = {name: Mock() for name in names}
    namespace.update(
        get_m365_approval_service=lambda: SimpleNamespace(),
        _get_workflow_runner_app=lambda: SimpleNamespace(test_request_context=nullcontext),
        load_current_workflow=lambda reference: workflow,
        get_settings=lambda: {"allow_user_workflows": True},
        is_group_workflows_enabled_for_group=lambda settings, group_id: group_id == "group",
        acquire_distributed_task_lock=Mock(return_value=lock),
        release_distributed_task_lock=release_lock,
        resume_m365_durable_workflow_run=resume_durable,
        run_group_workflow=resume_legacy, run_personal_workflow=resume_legacy,
        update_group_workflow_runtime_fields=update_fields,
        update_personal_workflow_runtime_fields=update_fields,
        workflow_result_is_waiting=workflow_result_is_waiting,
        workflow_result_runtime_status=workflow_result_runtime_status,
        resume_pending_workflows=dispatch_jobs,
        cosmos_m365_execution_runs_container=object(),
        M365_ACTIVE_STATES={"awaiting_sign_in"},
    )
    path = Path(__file__).resolve().parents[1] / "application" / "single_app" / "background_tasks.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    entrypoint = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                      and node.name == "check_m365_workflow_continuations_once")
    exec(compile(ast.Module(body=[entrypoint], type_ignores=[]), str(path), "exec"), namespace)
    assert namespace[entrypoint.name]() is result
    release_lock.assert_called_once_with(lock)
    if durable:
        resume_durable.assert_called_once_with(workflow, job)
        resume_legacy.assert_not_called()
        update_fields.assert_not_called()
    else:
        resume_durable.assert_not_called()
        resume_legacy.assert_called_once_with(
            workflow, trigger_source="m365_approval", actor_user_id="owner", run_id="run",
        )
        update_fields.assert_called_once_with(
            "group" if group else "owner", "workflow", result["workflow_updates"],
        )


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_run_as_is_preserved_and_part_of_the_native_edit_revision(scope):
    helpers, container, _ = load_personal_store() if scope == "personal" else load_group_store()
    save = (
        lambda payload: helpers["save_personal_workflow"]("owner", payload)
    ) if scope == "personal" else (
        lambda payload: helpers["save_group_workflow"]("group-one", payload, "owner")
    )
    original = save({**definition(), "m365_run_as_user_id": "reader"})
    renamed = save({**original, "name": "Renamed"})
    assert renamed["m365_run_as_user_id"] == "reader"
    assert renamed["m365_revision"] == original["m365_revision"]
    changed = save({**renamed, "m365_run_as_user_id": "other-reader"})
    assert changed["definition_revision"] != renamed["definition_revision"]
    assert changed["m365_revision"] != renamed["m365_revision"]
    with pytest.raises(WorkflowDefinitionConflict):
        save({**renamed, "description": "Stale account selection"})
    cleared = save({**changed, "m365_run_as_user_id": ""})
    assert cleared["m365_run_as_user_id"] == ""


@pytest.mark.parametrize("material_change", [False, True])
def test_fresh_cas_record_controls_m365_approval_retention(material_change):
    container = WorkflowContainer("user_id")
    original = normalize_workflow_run_as(
        {"id": "workflow", "user_id": "owner", "task_prompt": "Read files"},
        {"m365_run_as_user_id": "reader"},
    )
    original = container.create_item(body=original)
    live = {
        **original, "status": "awaiting_approval", "active_run_id": "run",
        "m365_binding_approval_id": "concurrently-approved",
    }
    container.replace_item(item=live["id"], body=live, etag=original["_etag"], match_condition=None)
    candidate = {**original, "name": "New label"}
    if material_change:
        candidate["task_prompt"] = "Send mail"
    normalize_workflow_run_as(candidate, candidate, original)
    saved = save_workflow_definition_record(container, "owner", candidate, original)
    assert saved["m365_binding_approval_id"] == (None if material_change else "concurrently-approved")
    assert saved["active_run_id"] == ("" if material_change else "run")
    assert saved["status"] == ("idle" if material_change else "awaiting_approval")


@pytest.mark.parametrize("field,value", [
    ("definition_version", 3), ("reference_inputs", [{"id": "criteria", "document_id": "private"}]),
    ("durable_execution", True), ("flow", {"id": "root", "nodes": []}),
    ("limits", {"max_executions": 100}),
])
def test_modern_execution_fields_invalidate_m365_authorization(field, value):
    original = {"id": "workflow", "user_id": "owner", "m365_run_as_user_id": "reader"}
    assert workflow_execution_fingerprint(original) != workflow_execution_fingerprint({**original, field: value})


def test_active_native_run_remains_protected_from_definition_edits():
    container = WorkflowContainer("user_id")
    original = container.create_item(body={
        "id": "workflow", "user_id": "owner", "definition_version": 2,
        "m365_run_as_user_id": "reader", "active_run_id": "run", "status": "awaiting_approval",
    })
    with pytest.raises(WorkflowDefinitionConflict, match="active run"):
        save_workflow_definition_record(container, "owner", {**original, "m365_run_as_user_id": "other"}, original)


def approval_required():
    return M365ApprovalRequired({
        "id": "approval", "request_type": "m365_extended_analysis", "subject_user_id": "reader",
        "resume_key": "resume", "execution_status": "awaiting_approval", "status": "pending",
    })


def configure_m365_runtime(integration, monkeypatch, version):
    workflow, runner, services, make_store, clock, requests = integration
    workflow.update(m365_run_as_user_id="reader", conversation_id="conversation-inventory")
    container = make_store(workflow, "unused").container
    monkeypatch.setattr("functions_workflow_result_store._configured_store", lambda *args, **kwargs: WorkflowResultStore(container))
    if version == 3:
        workflow.update(definition_version=3, flow={
            "id": "root", "nodes": [
                {"id": "extract-node", "kind": "task", "task_id": "extract"},
                {"id": "consume-node", "kind": "task", "task_id": "consume"},
            ],
            "outputs": [{"name": "answer", "source": {"kind": "node_output", "node_id": "consume-node"}}],
        })
        workflow["tasks"][0].update(inputs=[], output_contract={"kind": "records"})
        workflow["tasks"][1]["inputs"] = [{
            "name": "inventory", "source": {"kind": "node_output", "node_id": "extract-node", "output": "records"},
        }]
        runner.update(
            persist_workflow_task_result=persist_workflow_task_result,
            authorize_workflow_task_result_read=authorize_workflow_task_result_read,
        )
    services["definitions"].upsert_item(workflow)
    completions = []
    runner.update({
        "workflow_m365_manifests": lambda wf: ([{"id": "closed-action"}], wf),
        "workflow_m365_context": lambda *args, **kwargs: nullcontext(),
        "M365PolicyError": M365PolicyError, "M365_AUTH_INTERACTION_CODES": M365_AUTH_INTERACTION_CODES,
        "build_waiting_workflow_result": build_waiting_workflow_result,
        "_get_workflow_run_record": lambda wf, run_id: services["runs"].read_item(item=run_id, partition_key="owner"),
        "complete_m365_request": lambda: completions.append(True),
    })
    return workflow, runner, services, make_store, clock, requests, completions


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("interaction", ["approval", "sign_in"])
@pytest.mark.parametrize("preflight", [False, True])
def test_m365_wait_and_continuation_reuse_the_leased_run_and_completed_tasks(
    integration, monkeypatch, version, interaction, preflight,
):
    workflow, runner, services, make_store, clock, requests, completions = configure_m365_runtime(
        integration, monkeypatch, version,
    )
    authorized = False
    dispatch_task = runner["_execute_workflow_dispatch"]

    def require_interaction():
        raise approval_required() if interaction == "approval" else M365SignInRequired("m365_connection_required")

    def m365_context(*args, **kwargs):
        if preflight and not authorized:
            require_interaction()
        return nullcontext()

    def dispatch_with_interaction(attempt_workflow, *args, **kwargs):
        if not preflight and not authorized and attempt_workflow["active_task"]["id"] == "consume":
            require_interaction()
        return dispatch_task(attempt_workflow, *args, **kwargs)

    runner.update(workflow_m365_context=m365_context, _execute_workflow_dispatch=dispatch_with_interaction)
    run_id = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")["run"]["id"]
    store = make_store(workflow, run_id)
    assert store.run_definition()["m365_run_as_user_id"] == "reader"
    waiting = runtime.continue_durable_workflow_run(workflow, run_id)
    state = "awaiting_approval" if interaction == "approval" else "awaiting_sign_in"
    assert waiting["status"] == state and waiting["completed_at"] is None
    control = store.read()
    assert control["state"] == state and control["lease"] is None
    assert control["gate"]["choices"] == ["cancel"]
    assert services["load_workflow"]()["active_run_id"] == run_id
    assert len(requests) == (0 if preflight else 1)
    for choice in ("resume", "approve"):
        with pytest.raises(WorkflowRuntimeConflict):
            store.decide(
                expected_version=control["version"], gate_id=control["gate"]["id"],
                choice=choice, actor_user_id="owner", request_id=f"not-m365-{choice}",
            )
    runtime.continue_durable_workflow_run(workflow, run_id)
    assert len(requests) == (0 if preflight else 1)
    job = {
        "id": run_id, "run_id": run_id, "workflow_id": workflow["id"],
        "user_id": "reader", "actor_user_id": "owner",
    }
    for field in ("id", "workflow_id", "user_id", "actor_user_id"):
        with pytest.raises(WorkflowRuntimeConflict):
            runtime.resume_m365_durable_workflow_run(workflow, {**job, field: "not-the-authorized-identity"})
    assert store.read()["version"] == control["version"]
    authorized = True
    result = runtime.resume_m365_durable_workflow_run(workflow, job)
    assert result["success"] is True and result["pending"] is False
    assert store.read()["state"] == "completed"
    assert len(requests) == 2 and completions == [True]
    if version == 3:
        assert store.read()["admitted_count"] == 2
    else:
        assert store.read()["units"]["task:consume"]["attempt"] == 1


@pytest.mark.parametrize("interrupt", [False, True])
def test_repeat_m365_checkpoints_and_agent_steps_are_scoped_to_execution(monkeypatch, interrupt):
    workflow, store, _, clock, _ = repeat_runtime(monkeypatch, definition=repeat_definition(maximum=3))
    runner, calls = production_dispatcher(lambda producer: {
        "ready": bool(producer["iteration_path"] and producer["iteration_path"][-1]["iteration"] == 1),
    })
    checkpoints, steps, interruptions = {}, [], []

    def task_context(key):
        assert key == f"execution:{current_workflow_execution().execution_id()}"
        steps.append(key)
        return nullcontext()

    def checkpoint(key, value):
        checkpoints[key] = copy.deepcopy(value)
        if interrupt and value["iteration_path"] and not interruptions:
            interruptions.append(key)
            raise SystemExit("Worker stopped after saving the M365 checkpoint.")

    runner.update({
        "m365_workflow_task_context": task_context,
        "read_m365_task_checkpoint": lambda key: copy.deepcopy(checkpoints.get(key)),
        "save_m365_task_checkpoint": checkpoint,
    })
    if interrupt:
        with pytest.raises(SystemExit, match="M365 checkpoint"):
            dispatch(runner, workflow, store)
        assert len(calls) == 2
        clock.advance()
    result = dispatch(runner, workflow, store)
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert len(calls) == len(checkpoints) == len(set(steps)) == 3
    assert set(checkpoints) == set(steps)
    assert len({item["execution_id"] for item in checkpoints.values()}) == 3
    for item in checkpoints.values():
        execution = store.journal_read("execution", item["execution_id"])["payload"]
        assert execution["state"] == "succeeded"
        assert execution["workflow_result"] == item["result"]["workflow_result"]


@pytest.mark.parametrize("version", [2, 3])
def test_cancellation_stops_pending_m365_work_and_rejects_late_continuation(integration, monkeypatch, version):
    workflow, runner, services, make_store, clock, requests, _ = configure_m365_runtime(
        integration, monkeypatch, version,
    )
    cancelled = []
    m365 = ModuleType("functions_m365_runtime")
    m365.cancel_m365_workflow_requests = lambda workflow_id, run_id: cancelled.append((workflow_id, run_id))
    monkeypatch.setitem(sys.modules, "functions_m365_runtime", m365)

    def require_sign_in(*args, **kwargs):
        raise M365SignInRequired("m365_connection_required")

    runner["workflow_m365_context"] = require_sign_in
    run_id = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")["run"]["id"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    result = runtime.cancel_durable_workflow_run(workflow, run_id, actor_user_id="owner")
    assert result["run"]["status"] == "cancelled"
    assert services["load_workflow"]()["active_run_id"] == ""
    assert cancelled == [(workflow["id"], run_id)]
    with pytest.raises(WorkflowRuntimeConflict):
        runtime.resume_m365_durable_workflow_run(workflow, {
            "id": run_id, "run_id": run_id, "workflow_id": workflow["id"],
            "user_id": "reader", "actor_user_id": "owner",
        })
    assert requests == []


def test_generated_m365_conversation_is_reused_after_sign_in(integration, monkeypatch):
    workflow, runner, services, make_store, clock, requests, _ = configure_m365_runtime(
        integration, monkeypatch, 2,
    )
    workflow["conversation_id"] = ""
    services["definitions"].upsert_item(workflow)
    personal = ModuleType("functions_personal_workflows")
    personal.update_personal_workflow_runtime_fields = lambda user_id, workflow_id, updates: update_workflow_runtime_record(
        services["definitions"], user_id, workflow_id, updates, runtime._now(),
    )
    group = ModuleType("functions_group_workflows")
    group.update_group_workflow_runtime_fields = lambda *args: pytest.fail("A personal run cannot update a group.")
    monkeypatch.setitem(sys.modules, "functions_personal_workflows", personal)
    monkeypatch.setitem(sys.modules, "functions_group_workflows", group)
    created, contexts = [], []
    authorized = False

    def conversation(workflow):
        conversation_id = workflow.get("conversation_id")
        if not conversation_id:
            created.append("conversation-inventory")
            conversation_id = created[-1]
        return {"id": conversation_id, "user_id": "owner"}

    def m365_context(workflow, run_id, conversation_id, **kwargs):
        contexts.append(conversation_id)
        if not authorized:
            raise M365SignInRequired("m365_connection_required")
        return nullcontext()

    runner.update(_ensure_workflow_conversation=conversation, workflow_m365_context=m365_context)
    run_id = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")["run"]["id"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    authorized = True
    result = runtime.resume_m365_durable_workflow_run(workflow, {
        "id": run_id, "run_id": run_id, "workflow_id": workflow["id"],
        "user_id": "reader", "actor_user_id": "owner",
    })
    assert result["success"] is True
    assert created == ["conversation-inventory"]
    assert contexts == ["conversation-inventory", "conversation-inventory"]
