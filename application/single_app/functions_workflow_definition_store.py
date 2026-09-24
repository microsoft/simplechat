# functions_workflow_definition_store.py
"""Conditional workflow definition writes which do not erase runtime progress."""

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError

from functions_m365_workflow_binding import normalize_workflow_run_as
from functions_workflow_definitions import (
    WorkflowDefinitionConflict,
    WorkflowDeletedConflict,
    workflow_definition_for_editor,
    workflow_definition_revision,
)


WORKFLOW_RUNTIME_FIELDS = frozenset({
    "status", "last_run_started_at", "last_run_at", "last_run_status", "last_run_error",
    "last_run_response_preview", "last_run_trigger_source", "run_count", "active_run_id",
    "cancellation_requested_at", "cancellation_requested_by", "next_run_at", "conversation_id", "last_run_id",
    "active_runtime_version", "deleting",
})


def refuse_save_of_deleted_workflow(container, partition_key, workflow_data, existing):
    """Refuse an editor save that would recreate a workflow deleted after the editor opened it.

    Only a payload naming an ``id`` and carrying the ``definition_revision`` it was opened at is
    refused, and only when nothing is stored for that id. Creates, and classic saves, which send no
    revision, keep their current behaviour. Call this before any other save work: it writes nothing.
    """
    workflow_data = workflow_data if isinstance(workflow_data, dict) else {}
    workflow_id = str(workflow_data.get("id") or "").strip()
    revision = str(workflow_data.get("definition_revision") or "").strip()
    if not workflow_id or not revision or existing:
        return
    try:
        # The caller's lookup also returns None on a transient failure, so confirm the record is gone.
        container.read_item(item=workflow_id, partition_key=partition_key)
    except CosmosResourceNotFoundError as exc:
        raise WorkflowDeletedConflict() from exc


def save_workflow_definition_record(container, partition_key, workflow, existing=None):
    if not existing:
        try:
            created = container.create_item(body=workflow)
        except CosmosResourceExistsError as exc:
            raise WorkflowDefinitionConflict("This workflow already exists. Reload it before saving.") from exc
        return workflow_definition_for_editor(created)
    expected = workflow_definition_revision(existing)
    for _attempt in range(3):
        try:
            current = container.read_item(item=workflow["id"], partition_key=partition_key)
        except CosmosResourceNotFoundError as exc:
            raise WorkflowDeletedConflict() from exc
        if current.get("deleting"):
            raise WorkflowDefinitionConflict("This workflow is being deleted. Your draft was not saved.")
        if workflow_definition_revision(current) != expected:
            raise WorkflowDefinitionConflict("This workflow changed since it was opened. Reload it before saving.")
        if workflow.get("definition_version") in {2, 3} and current.get("active_run_id"):
            raise WorkflowDefinitionConflict("An active run started while editing. Wait or cancel it before saving.")
        body = {key: value for key, value in current.items() if not key.startswith("_")}
        body.update(workflow)
        body.update({key: current[key] for key in WORKFLOW_RUNTIME_FIELDS if key in current})
        # A schedule edit intentionally computes a new next run; preserve the
        # live scheduler value only when its authored inputs stayed the same.
        if any(workflow.get(field) != existing.get(field) for field in ("schedule", "trigger_type", "is_enabled")):
            body["next_run_at"] = workflow.get("next_run_at")
        if workflow.get("conversation_id") != existing.get("conversation_id"):
            body["conversation_id"] = workflow.get("conversation_id")
        normalize_workflow_run_as(body, workflow, current)
        try:
            saved = container.replace_item(
                item=workflow["id"], body=body, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return workflow_definition_for_editor(saved)
        except CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
    raise WorkflowDefinitionConflict("This workflow is being updated. Reload it before saving.")


def update_workflow_runtime_record(container, partition_key, workflow_id, updates, updated_at):
    """Retry only read/replace conflicts; never replace a newly edited definition."""
    if set(updates) - WORKFLOW_RUNTIME_FIELDS:
        raise ValueError("Unsupported workflow runtime fields.")
    for _attempt in range(3):
        try:
            current = container.read_item(item=workflow_id, partition_key=partition_key)
        except CosmosResourceNotFoundError as exc:
            raise LookupError("Workflow not found.") from exc
        body = {**current, **updates, "updated_at": updated_at}
        try:
            saved = container.replace_item(
                item=workflow_id, body=body, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return workflow_definition_for_editor(saved)
        except CosmosHttpResponseError as exc:
            if exc.status_code == 404:
                raise LookupError("Workflow not found.") from exc
            if exc.status_code != 412:
                raise
    raise WorkflowDefinitionConflict("Workflow progress changed concurrently. Retry the operation.")
