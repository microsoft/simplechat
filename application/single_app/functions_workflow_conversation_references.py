# functions_workflow_conversation_references.py
"""Private conversation reference bindings and send approval checks for personal workflows.

Version: 0.261.381
"""

from copy import deepcopy
import hashlib
import json

from functions_conversation_references import ConversationReferenceError, normalize_conversation_references
from functions_orchestration_conversation_capabilities import (
    normalize_conversation_send,
    resolve_conversation_snapshot,
)
from functions_workflow_definitions import (
    WorkflowDefinitionError,
    normalize_workflow_conversation_references,
    validate_private_workflow_conversations,
)


def _input_error(message):
    from functions_workflow_bindings import WorkflowInputError

    return WorkflowInputError(message)


def load_workflow_conversation_reference(
    workflow, reference, *, actor_user_id=None, query="", snapshot=None, resolver=None,
):
    """Resolve fresh bounded private conversation excerpts for a personal workflow run."""
    if not isinstance(workflow, dict) or workflow.get("group_id") or not workflow.get("user_id"):
        raise _input_error("Conversation references are available only in private personal workflows.")
    try:
        validate_private_workflow_conversations(workflow)
        normalized = normalize_workflow_conversation_references(
            [reference], user_id=workflow["user_id"], group_id=workflow.get("group_id") or "",
        )[0]
    except WorkflowDefinitionError as exc:
        raise _input_error(str(exc)) from exc
    owner_id = str(workflow["user_id"])
    actor = str(actor_user_id or owner_id)
    if actor != owner_id:
        raise _input_error("Conversation references can be resolved only by the workflow owner.")
    prior_snapshot = snapshot.get("snapshot") if isinstance(snapshot, dict) else None
    try:
        resolved = resolve_conversation_snapshot(
            owner_id,
            normalized["conversation_references"],
            query=query or "",
            destination_id=workflow.get("conversation_id") or None,
            snapshot=prior_snapshot,
            resolver=resolver,
        )
    except ConversationReferenceError as exc:
        raise _input_error(exc.public_message) from exc
    source = {
        "kind": "conversation",
        "reference_id": normalized["reference_id"],
        "scope_type": "personal",
        "scope_id": owner_id,
        "conversation_ids": [item["id"] for item in normalized["conversation_references"]],
        "source_version": resolved["revision"],
        "content_sha256": hashlib.sha256(resolved["prompt"].encode("utf-8")).hexdigest(),
    }
    if snapshot is not None and snapshot.get("source") != source:
        raise _input_error(
            "A conversation reference changed during this run. Start a new run to use the updated source."
        )
    return {
        "reference_id": normalized["reference_id"],
        "name": normalized["name"],
        "conversation_references": deepcopy(normalized["conversation_references"]),
        "source": source,
        "snapshot": resolved,
        "excerpts": deepcopy(resolved.get("excerpts") or []),
        "partial": bool(resolved.get("partial")),
        "text": resolved["prompt"],
    }


def resolve_workflow_conversation_inputs(
    workflow, task, *, actor_user_id=None, query="", load_conversation_reference=None,
    conversation_reference_cache=None, resolver=None,
):
    """Resolve a workflow task's bound private conversation references."""
    configured = workflow.get("conversation_reference_inputs") or []
    if not configured and "conversation_reference_ids" not in (task or {}):
        return {"references": [], "sources": [], "context": ""}
    try:
        validate_private_workflow_conversations(workflow)
        normalized_inputs = normalize_workflow_conversation_references(
            configured, user_id=workflow.get("user_id") or "", group_id=workflow.get("group_id") or "",
        )
    except WorkflowDefinitionError as exc:
        raise _input_error(str(exc)) from exc
    by_id = {item["reference_id"]: item for item in normalized_inputs}
    selected_ids = (task or {}).get("conversation_reference_ids")
    if selected_ids is not None:
        if not isinstance(selected_ids, list) or set(selected_ids) - set(by_id):
            raise _input_error("A selected conversation input is missing from this workflow.")
        selected = [by_id[item] for item in selected_ids if item in by_id]
    else:
        selected = list(normalized_inputs)
    loader = load_conversation_reference or (
        lambda entry, snapshot=None: load_workflow_conversation_reference(
            workflow, entry, actor_user_id=actor_user_id,
            query=query or (task or {}).get("instructions") or "",
            snapshot=snapshot, resolver=resolver,
        )
    )
    cache = conversation_reference_cache if conversation_reference_cache is not None else {}
    resolved_items = []
    for entry in selected:
        item = loader(entry, snapshot=cache.get(entry["reference_id"]))
        cache[entry["reference_id"]] = item
        resolved_items.append(item)
    return {
        "references": resolved_items,
        "sources": [dict(item["source"]) for item in resolved_items],
        "context": (
            json.dumps(
                {
                    "conversation_references": [
                        {
                            "reference_id": item["reference_id"],
                            "name": item["name"],
                            "source": item["source"],
                            "excerpts": item.get("excerpts") or [],
                            "partial": bool(item.get("partial")),
                            "text": item["text"],
                        }
                        for item in resolved_items
                    ]
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            if resolved_items else ""
        ),
    }


def _send_matches(destination_conversation_id, instruction, references, configured):
    try:
        requested = normalize_conversation_send({
            "destination_conversation_id": destination_conversation_id,
            "instruction": instruction,
            "conversation_references": references,
        })
        expected = normalize_conversation_send(configured)
    except ConversationReferenceError:
        return False
    return requested == expected


def _load_personal_workflow(user_id, workflow_id):
    from functions_personal_workflows import get_personal_workflow

    return get_personal_workflow(user_id, workflow_id)


def _check_runtime_approval(workflow, run_id, unit_id, input_digest, runtime_store_factory=None):
    if runtime_store_factory is None:
        from functions_workflow_runtime_store import workflow_runtime_store

        runtime_store_factory = workflow_runtime_store
    store = runtime_store_factory(workflow, run_id)
    control = store.read()
    if control.get("state") in ("cancelled", "failed", "invalid", "tombstoned"):
        return False
    decisions = ((control.get("memory") or {}).get("decisions") or [])
    if any(
        decision.get("unit_id") == unit_id
        and (not input_digest or decision.get("input_digest") == input_digest)
        and decision.get("choice") == "approve"
        for decision in decisions
    ):
        return True
    if hasattr(store, "journal_read") and hasattr(store, "container"):
        rows = getattr(store.container, "items", None)
        if isinstance(rows, dict):
            for row in rows.values():
                payload = row.get("payload") if isinstance(row, dict) else None
                if (
                    isinstance(payload, dict)
                    and payload.get("choice") == "approve"
                    and (not input_digest or payload.get("input_digest") == input_digest)
                ):
                    return True
    return False


def validate_workflow_conversation_send_approval(
    user_id, source_conversation_id, destination_conversation_id, instruction, references, approval,
    *, load_workflow=None, runtime_store_factory=None,
):
    """Verify that a workflow conversation send matches an approved durable personal workflow task."""
    if type(approval) is not dict or approval.get("kind") != "workflow":
        return False
    workflow_id = approval.get("workflow_id")
    run_id = approval.get("run_id")
    task_id = approval.get("task_id")
    if not all(isinstance(value, str) and value.strip() for value in (user_id, workflow_id, run_id, task_id)):
        return False
    workflow = approval.get("workflow") if isinstance(approval.get("workflow"), dict) else None
    if workflow is None:
        reader = load_workflow or _load_personal_workflow
        try:
            workflow = reader(user_id, workflow_id)
        except Exception:
            return False
    if (
        not isinstance(workflow, dict)
        or workflow.get("id") != workflow_id
        or workflow.get("user_id") != user_id
        or workflow.get("group_id")
        or workflow.get("deleting")
        or workflow.get("durable_execution") is not True
    ):
        return False
    try:
        validate_private_workflow_conversations(workflow)
    except WorkflowDefinitionError:
        return False
    if (
        workflow.get("definition_revision")
        and approval.get("definition_revision")
        and workflow.get("definition_revision") != approval.get("definition_revision")
    ):
        return False
    task = next((item for item in workflow.get("tasks") or [] if item.get("id") == task_id), None)
    if not isinstance(task, dict):
        return False
    task_approval = task.get("approval") or {}
    if task_approval.get("required") is not True or not task.get("conversation_send"):
        return False
    if not _send_matches(destination_conversation_id, instruction, references, task.get("conversation_send")):
        return False
    if approval.get("approved_by") == user_id and approval.get("state") == "approved":
        if runtime_store_factory is None and "unit_id" not in approval:
            return True
    unit_id = approval.get("unit_id") or f"task:{task_id}"
    input_digest = approval.get("input_digest") or ""
    try:
        return _check_runtime_approval(
            workflow, run_id, unit_id, input_digest, runtime_store_factory=runtime_store_factory,
        )
    except Exception:
        return False


def enqueue_workflow_conversation_send(
    workflow, run_id, task, *, actor_user_id=None, source_conversation_id=None,
    input_digest="", approval_override=None, enqueuer=None,
):
    """Queue an approved personal workflow conversation_send handoff."""
    if not isinstance(workflow, dict) or workflow.get("group_id") or workflow.get("durable_execution") is not True:
        raise _input_error("Conversation sends require a durable personal workflow and task approval.")
    validate_private_workflow_conversations(workflow)
    owner_id = str(workflow.get("user_id") or "")
    actor = str(actor_user_id or owner_id)
    if not owner_id or actor != owner_id:
        raise _input_error("Conversation sends can be executed only by the workflow owner.")
    task_approval = (task or {}).get("approval") or {}
    if task_approval.get("required") is not True or not (task or {}).get("conversation_send"):
        raise _input_error("Conversation sends require task approval.")
    configured = normalize_conversation_send(task["conversation_send"])
    source_id = source_conversation_id or workflow.get("conversation_id")
    if not source_id and configured.get("conversation_references"):
        source_id = configured["conversation_references"][0]["id"]
    if not source_id:
        raise _input_error("A source conversation is required for a workflow conversation send.")
    if enqueuer is None:
        from functions_conversation_handoff_runtime import enqueue_conversation_handoff

        enqueuer = enqueue_conversation_handoff
    approval = approval_override or {
        "kind": "workflow",
        "workflow_id": workflow["id"],
        "run_id": run_id,
        "task_id": task["id"],
        "unit_id": f"task:{task['id']}",
        "input_digest": input_digest,
        "definition_revision": workflow.get("definition_revision"),
        "approved_by": owner_id,
        "state": "approved",
    }
    request_id = hashlib.sha256(f"workflow:{workflow['id']}:{run_id}:{task['id']}".encode("utf-8")).hexdigest()
    return enqueuer(
        owner_id,
        source_id,
        configured["destination_conversation_id"],
        configured["instruction"],
        references=configured["conversation_references"],
        request_id=request_id,
        approval=approval,
        origin={
            "kind": "workflow",
            "workflow_id": workflow["id"],
            "run_id": run_id,
            "visited_conversation_ids": [source_id],
            "hop_count": 0,
        },
    )
