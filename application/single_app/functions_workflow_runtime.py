# functions_workflow_runtime.py
"""Submission and background continuation for durable workflow runs."""

import logging
import os
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError

from functions_appinsights import log_event
from functions_workflow_definitions import (
    WORKFLOW_DEFINITION_FIELDS, validate_workflow_publication_completion, workflow_definition_revision,
)
from functions_workflow_execution import DurableWorkflowExecution, WorkflowSuspended, workflow_execution_scope
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_readiness import WorkflowOutputUnavailable, workflow_outputs_ready
from functions_workflow_result_store import delete_workflow_run_results, load_workflow_task_result, save_workflow_task_result
from functions_workflow_result_store import load_workflow_runtime_result, save_workflow_runtime_result
from functions_workflow_runtime_store import (
    WorkflowRuntimeConflict,
    WorkflowRuntimeLease,
    RuntimeUnavailable,
    workflow_runtime_projection,
    workflow_runtime_store,
)


RUNTIME_TERMINAL_STATES = frozenset({
    "completed", "completed_partial", "failed", "invalid", "incomplete", "cancelled", "skipped",
})
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow-runtime")
_worker_lock = threading.Lock()
_active_workers = {}


def _services(workflow):
    # Runtime workers resolve fresh application clients/settings rather than
    # serializing Flask contexts or credentials in a checkpoint.
    import config
    from functions_group_workflows import get_group_workflow
    from functions_personal_workflows import get_personal_workflow
    from functions_settings import get_settings

    group_id = workflow.get("group_id")
    return {
        "definitions": config.cosmos_group_workflows_container if group_id else config.cosmos_personal_workflows_container,
        "runs": config.cosmos_group_workflow_runs_container if group_id else config.cosmos_personal_workflow_runs_container,
        "partition": group_id or workflow["user_id"],
        "load_workflow": lambda: (
            get_group_workflow(group_id, workflow["id"]) if group_id
            else get_personal_workflow(workflow["user_id"], workflow["id"])
        ),
        "settings": get_settings,
    }


def _now():
    return datetime.now(timezone.utc).isoformat()


def _authorize_execution(workflow, actor_user_id, settings):
    # Resolve current access helpers at worker admission, without import cycles.
    from functions_group import assert_group_role
    from functions_group_workflows import GROUP_WORKFLOW_MEMBER_ROLES
    from functions_settings import is_group_workflows_enabled_for_group

    validate_workflow_publication_completion(workflow)
    if workflow.get("deleting"):
        raise WorkflowRuntimeConflict("workflow_deleting", "This workflow is being deleted.")
    if workflow.get("group_id"):
        assert_group_role(actor_user_id, workflow["group_id"], allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES)
        if not settings.get("enable_group_workspaces") or not is_group_workflows_enabled_for_group(settings, workflow["group_id"]):
            raise PermissionError("Group workflows are no longer available.")
    elif actor_user_id != workflow["user_id"] or not settings.get("allow_user_workflows"):
        raise PermissionError("Personal workflows are no longer available.")


def _snapshot(workflow):
    return {
        **{field: deepcopy(workflow[field]) for field in WORKFLOW_DEFINITION_FIELDS if field in workflow},
        **{field: deepcopy(workflow[field]) for field in (
            "id", "user_id", "group_id", "conversation_id", "model_binding_summary",
            "url_access_authorized", "url_access_authorized_by", "url_access_authorized_at",
        ) if field in workflow},
        "definition_revision": workflow_definition_revision(workflow),
    }


def _bind_active_run(services, workflow, run_id, *, runtime_version=1):
    for _attempt in range(5):
        try:
            current = services["definitions"].read_item(item=workflow["id"], partition_key=services["partition"])
        except CosmosResourceNotFoundError as exc:
            raise WorkflowRuntimeConflict("workflow_deleted", "This workflow was deleted.") from exc
        if current.get("deleting"):
            raise WorkflowRuntimeConflict("workflow_deleting", "This workflow is being deleted.")
        if current.get("active_run_id") == run_id and int(current.get("active_runtime_version") or 0) >= runtime_version:
            return current
        if current.get("active_run_id") not in (None, "", run_id):
            raise WorkflowRuntimeConflict("workflow_already_running")
        if workflow_definition_revision(current) != workflow_definition_revision(workflow):
            raise WorkflowRuntimeConflict("workflow_definition_changed")
        body = {key: value for key, value in current.items() if not key.startswith("_")}
        body.update(active_run_id=run_id, status="queued", cancellation_requested_at=None,
                    cancellation_requested_by="", active_runtime_version=runtime_version, updated_at=_now())
        try:
            return services["definitions"].replace_item(
                item=current["id"], body=body, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
    raise WorkflowRuntimeConflict("workflow_definition_changed")


def queue_durable_workflow_run(workflow, *, actor_user_id, trigger_source="manual", request_id=None, invocation_metadata=None):
    services = _services(workflow)
    settings = services["settings"]()
    current = services["load_workflow"]()
    if not current:
        raise LookupError("Workflow not found.")
    if current.get("durable_execution") is not True:
        raise ValueError("Durable execution is not enabled for this workflow.")
    _authorize_execution(current, actor_user_id, settings)
    if type(current.get("definition_version", 1)) is not int or current.get("definition_version", 1) not in {1, 2, 3}:
        raise ValueError("This workflow definition requires a newer execution engine.")
    if current.get("definition_version") == 3:
        compile_workflow_flow(current)
        from functions_workflow_loop_runners import validate_workflow_loop_runners

        validate_workflow_loop_runners(current, actor_user_id=actor_user_id, settings=settings)
    if request_id is not None and not isinstance(request_id, str):
        raise ValueError("A workflow request identifier must be a UUID string.")
    request_id = str(uuid.UUID(request_id)) if request_id is not None else str(uuid.uuid4())
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{services['partition']}:{current['id']}:{request_id}"))
    if current.get("active_run_id") not in (None, "", run_id):
        raise WorkflowRuntimeConflict("workflow_already_running")
    snapshot = _snapshot(current)
    store = workflow_runtime_store(current, run_id)
    try:
        existing_control = store.read(allow_deleted=True)
    except WorkflowRuntimeConflict as exc:
        if exc.code != "not_found":
            raise
        existing_control = None
    if existing_control is not None:
        if existing_control.get("deleted"):
            raise WorkflowRuntimeConflict("tombstoned", "This workflow run was deleted.")
        snapshot_ref = existing_control["snapshot_ref"]
        snapshot = store.run_definition() if existing_control.get("schema_version") == 2 else load_workflow_task_result(current, run_id, "runtime:definition", snapshot_ref)
    else:
        snapshot_ref = (
            save_workflow_runtime_result(snapshot, run_id, snapshot, settings=settings)
            if snapshot.get("definition_version") == 3 else
            save_workflow_task_result(current, run_id, "runtime:definition", snapshot, settings=settings)
        )
    loop_policy = None
    if snapshot.get("definition_version") == 3:
        from functions_workflow_limits import get_workflow_loop_item_limit

        loop_policy = {"max_items": get_workflow_loop_item_limit(settings)}
    control = store.initialize(
        snapshot_ref=snapshot_ref, definition_revision=snapshot["definition_revision"],
        actor_user_id=actor_user_id, request_id=request_id,
        **({"loop_policy": loop_policy} if loop_policy is not None else {}),
    )
    if control["state"] in RUNTIME_TERMINAL_STATES:
        run = services["runs"].read_item(item=run_id, partition_key=services["partition"])
        return {"success": True, "run": run, "workflow": current, "runtime": workflow_runtime_projection(control)}
    run = {
        "id": run_id, "workflow_id": current["id"], "workflow_name": current.get("name"),
        "user_id": current["user_id"], "group_id": current.get("group_id"),
        "workspace_type": "group" if current.get("group_id") else "personal",
        "trigger_source": trigger_source, "triggered_by": actor_user_id,
        "durable_execution": True, "status": control["state"], "success": False,
        "definition_version": snapshot.get("definition_version", 1),
        "started_at": control.get("created_at") or _now(), "completed_at": None,
        "definition_revision": snapshot["definition_revision"],
    }
    if invocation_metadata is not None:
        run["mcp_invocation"] = deepcopy(invocation_metadata)
    try:
        saved = services["runs"].read_item(item=run_id, partition_key=services["partition"])
    except CosmosResourceNotFoundError:
        try:
            saved = services["runs"].create_item(body=run)
        except CosmosResourceExistsError:
            saved = services["runs"].read_item(item=run_id, partition_key=services["partition"])
    try:
        bound = _bind_active_run(services, current, run_id, runtime_version=control["version"])
    except WorkflowRuntimeConflict:
        store.tombstone()
        delete_workflow_run_results(current, run_id)
        try:
            services["runs"].delete_item(item=run_id, partition_key=services["partition"])
        except CosmosResourceNotFoundError:
            pass
        raise
    return {"success": True, "run": saved, "workflow": bound, "runtime": workflow_runtime_projection(control)}


def _project_runtime_run(services, workflow, run_id, control, *, result=None, attempt=0):
    latest = workflow_runtime_store(workflow, run_id).read()
    if latest["version"] > control["version"]:
        control, result = latest, None
    if result is None and control.get("completion_ref"):
        result = (
            load_workflow_runtime_result(workflow, run_id, control, control["completion_ref"])
            if control.get("schema_version") == 2 else
            load_workflow_task_result(workflow, run_id, "runtime:completion", control["completion_ref"])
        )
    existing = services["runs"].read_item(item=run_id, partition_key=services["partition"])
    body = {key: value for key, value in existing.items() if not key.startswith("_")}
    if result:
        body.update(result.get("run") or {})
    body.update(
        durable_execution=True, status=control["state"],
        runtime=workflow_runtime_projection(control),
    )
    if control["state"] not in RUNTIME_TERMINAL_STATES:
        body.update(success=False, completed_at=None)
    elif control["state"] == "cancelled":
        body.update(success=False, completed_at=_now())
    if int(existing.get("runtime_version") or 0) > control["version"]:
        return existing
    body["runtime_version"] = control["version"]
    try:
        services["runs"].replace_item(
            item=run_id, body=body, etag=existing["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except CosmosHttpResponseError as exc:
        if exc.status_code == 412:
            if attempt >= 3:
                raise WorkflowRuntimeConflict("workflow_projection_changed") from exc
            return _project_runtime_run(
                services, workflow, run_id, workflow_runtime_store(workflow, run_id).read(),
                attempt=attempt + 1,
            )
        raise
    for _attempt in range(5):
        current = services["definitions"].read_item(item=workflow["id"], partition_key=services["partition"])
        if current.get("deleting"):
            return body
        if current.get("active_run_id") != run_id:
            return body
        if int(current.get("active_runtime_version") or 0) > control["version"]:
            return body
        updated = {key: value for key, value in current.items() if not key.startswith("_")}
        if control["state"] in RUNTIME_TERMINAL_STATES:
            updated.update(
                active_run_id="", status="idle", last_run_id=run_id,
                last_run_at=body.get("completed_at") or _now(), last_run_status=control["state"],
                last_run_response_preview=body.get("response_preview") or "", last_run_error=body.get("error") or "",
                cancellation_requested_at=None, cancellation_requested_by="",
            )
            if current.get("last_run_id") != run_id:
                updated["run_count"] = int(current.get("run_count") or 0) + 1
        else:
            updated.update(status=control["state"], last_run_status=control["state"])
        updated["updated_at"] = _now()
        updated["active_runtime_version"] = control["version"]
        updated["last_run_started_at"] = body.get("started_at")
        updated["last_run_trigger_source"] = body.get("trigger_source")
        if body.get("conversation_id"):
            updated["conversation_id"] = body["conversation_id"]
        try:
            services["definitions"].replace_item(
                item=current["id"], body=updated, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return body
        except CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
    raise WorkflowRuntimeConflict("workflow_projection_changed")


def workflow_runtime_status(workflow, run_id, *, reader_user_id):
    from functions_workflow_results import authorize_workflow_run_read

    services = _services(workflow)
    run = services["runs"].read_item(item=run_id, partition_key=services["partition"])
    if run.get("workflow_id") != workflow["id"] or run.get("durable_execution") is not True:
        raise LookupError("Durable workflow run not found.")
    authorize_workflow_run_read(workflow, run_id, reader_user_id=reader_user_id)
    store = workflow_runtime_store(workflow, run_id)
    control = store.read()
    gate = control.get("gate") or {}
    if gate.get("publication"):
        # Polling UI has the same source and destination boundary as exact result inspection.
        from functions_artifact_publication import authorize_publication_status_read
        from functions_workflow_execution_history import authorize_execution_payload

        snapshot = store.run_definition()
        row = store.journal_read("execution", gate.get("execution_id"))
        if row is None:
            raise LookupError("Publication execution not found.")
        authorize_execution_payload(snapshot, run_id, row["payload"], reader_user_id=reader_user_id)
        authorize_publication_status_read(
            reader_user_id, gate["publication"], actor_user_id=control["actor_user_id"],
        )
    return workflow_runtime_projection(control)


def decide_workflow_runtime(workflow, run_id, data, *, actor_user_id, resume=False):
    services = _services(workflow)
    workflow_runtime_status(workflow, run_id, reader_user_id=actor_user_id)
    store = workflow_runtime_store(workflow, run_id)
    control = store.read()
    snapshot = store.run_definition() if control.get("schema_version") == 2 else load_workflow_task_result(workflow, run_id, "runtime:definition", control["snapshot_ref"])
    if snapshot.get("definition_version") == 3:
        compile_workflow_flow(snapshot)
    current = services["load_workflow"]()
    if not current or workflow_definition_revision(current) != control["definition_revision"]:
        raise WorkflowRuntimeConflict("workflow_definition_changed")
    _authorize_execution(current, control["actor_user_id"], services["settings"]())
    if current.get("active_run_id") not in (None, "", run_id):
        raise WorkflowRuntimeConflict("workflow_already_running")
    request_id = str(uuid.UUID(data.get("request_id", "")))
    if resume:
        control = store.resume(
            expected_version=data.get("expected_version"), actor_user_id=actor_user_id, request_id=request_id,
        )
    else:
        control = store.decide(
            expected_version=data.get("expected_version"), gate_id=data.get("gate_id"),
            choice=data.get("choice"), actor_user_id=actor_user_id, request_id=request_id,
        )
    if control["state"] == "queued":
        _bind_active_run(services, snapshot, run_id, runtime_version=control["version"])
    _project_runtime_run(services, current, run_id, control)
    return workflow_runtime_projection(control)


def cancel_durable_workflow_run(workflow, run_id, *, actor_user_id):
    services = _services(workflow)
    store = workflow_runtime_store(workflow, run_id)
    control = store.request_cancel(actor_user_id=actor_user_id, request_id=str(uuid.uuid4()))
    run = _project_runtime_run(services, workflow, run_id, control)
    current = services["load_workflow"]()
    if current is None:
        raise LookupError("Workflow not found.")
    return {"run": run, "workflow": current}


def continue_durable_workflow_run(workflow, run_id):
    """A bounded scheduler unit: wait states release ownership, never hold a web request."""
    from functions_workflow_runner import run_personal_workflow

    services = _services(workflow)
    store = workflow_runtime_store(workflow, run_id)
    control = store.read()
    control = store.expire_deadline()
    current = services["load_workflow"]()
    if not current or current.get("active_run_id") != run_id:
        return None
    settings = services["settings"]()
    if control["state"] in RUNTIME_TERMINAL_STATES:
        return _project_runtime_run(services, current, run_id, control)
    if control["state"] == "waiting_output":
        try:
            ready = workflow_outputs_ready(current, (control.get("gate") or {}).get("references") or [])
        except WorkflowOutputUnavailable:
            ready = True
        if ready:
            control = store.requeue_output(expected_version=control["version"], gate_id=control["gate"]["id"])
    if control["state"].startswith("waiting") or control["state"] == "paused":
        return _project_runtime_run(services, current, run_id, control)
    owner_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
    with WorkflowRuntimeLease(store, owner_id=owner_id) as lease:
        if not lease.token:
            return None
        control = lease.check()
        try:
            _authorize_execution(current, control["actor_user_id"], settings)
        except PermissionError:
            control = store.wait(lease.token, state="paused", gate={
                "id": uuid.uuid4().hex, "kind": "pause", "unit_id": "authorization",
                "input_digest": control["definition_revision"],
                "reason": "The initiating user's current workflow access must be restored before this run can continue.",
                "choices": ["resume", "cancel"],
            })
            return _project_runtime_run(services, current, run_id, control)
        snapshot = store.run_definition() if control.get("schema_version") == 2 else load_workflow_task_result(current, run_id, "runtime:definition", control["snapshot_ref"])
        if workflow_definition_revision(snapshot) != control["definition_revision"]:
            raise WorkflowRuntimeConflict("workflow_definition_changed")
        if snapshot.get("definition_version") == 3:
            compile_workflow_flow(snapshot)
        if not snapshot.get("tasks"):
            snapshot["tasks"] = [{
                "id": "legacy-task", "name": "Workflow task", "type": "instructions",
                "instructions": snapshot["task_prompt"], "runner": {"type": "inherit"},
            }]
        controller = StructuredWorkflowExecution if snapshot.get("definition_version") == 3 else DurableWorkflowExecution
        execution = controller(store, lease, snapshot, run_id, settings=settings)
        result = None
        with workflow_execution_scope(execution):
            try:
                result = run_personal_workflow(
                    snapshot,
                    trigger_source=services["runs"].read_item(item=run_id, partition_key=services["partition"])["trigger_source"],
                    actor_user_id=control["actor_user_id"], run_id=run_id,
                )
                execution.check()
                reference = (
                    save_workflow_runtime_result(snapshot, run_id, result, settings=settings)
                    if snapshot.get("definition_version") == 3 else
                    save_workflow_task_result(snapshot, run_id, "runtime:completion", result, settings=settings)
                )
                final_state = (result.get("run") or {}).get("status") or "failed"
                if final_state not in RUNTIME_TERMINAL_STATES:
                    final_state = "failed"
                store.transition(lease.token, state=final_state, completion_ref=reference)
            except WorkflowSuspended:
                pass
        return _project_runtime_run(services, current, run_id, store.read(), result=result)


def check_durable_workflows_once(limit=20):
    """Discover active checkpoints, including manual runs orphaned by worker restart."""
    import config

    processed = []
    with _worker_lock:
        for run_id, future in list(_active_workers.items()):
            if future.done():
                del _active_workers[run_id]
                try:
                    future.result()
                except (AzureError, WorkflowRuntimeConflict, RuntimeUnavailable, PermissionError, LookupError, ValueError) as exc:
                    log_event(
                        "[WORKFLOW_SCHEDULER] Durable worker stopped",
                        extra={"run_id": run_id, "error_type": type(exc).__name__}, level=logging.ERROR,
                    )
    for container in (config.cosmos_personal_workflows_container, config.cosmos_group_workflows_container):
        candidates = container.query_items(
            query=(
                "SELECT TOP @limit * FROM c WHERE c.durable_execution = true "
                "AND IS_DEFINED(c.active_run_id) AND c.active_run_id != '' "
                "AND (c.status IN ('queued','running','cancelling','waiting_output') "
                "OR (c.definition_version = 3 AND c.status IN ('waiting_approval','waiting_recovery'))) ORDER BY c.updated_at ASC"
            ),
            parameters=[{"name": "@limit", "value": limit}],
            enable_cross_partition_query=True,
        )
        for workflow in candidates:
            run_id = workflow["active_run_id"]
            with _worker_lock:
                if run_id in _active_workers or len(_active_workers) >= 2:
                    continue
                _active_workers[run_id] = _workers.submit(continue_durable_workflow_run, workflow, run_id)
            processed.append(run_id)
    return processed
