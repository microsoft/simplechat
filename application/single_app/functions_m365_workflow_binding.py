# functions_m365_workflow_binding.py
"""Pure Microsoft 365 workflow revision and continuation contracts."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any


M365_WAITING_STATES = frozenset({
    "awaiting_approval",
    "awaiting_sharing_approval",
    "awaiting_analysis_approval",
    "awaiting_run_as_approval",
    "awaiting_sign_in",
})
M365_ACTIVE_STATES = M365_WAITING_STATES | {"ready_to_resume", "resuming"}
M365_WORKFLOW_FIELDS = (
    "id",
    "user_id",
    "group_id",
    "task_prompt",
    "tasks",
    "runner_type",
    "selected_agent",
    "conversation_id",
    "schedule",
    "trigger_type",
    "document_action",
    "file_sync",
    "chat_capabilities_enabled",
    "url_access_enabled",
    "model_endpoint_id",
    "model_id",
)


def workflow_execution_fingerprint(
    workflow: Mapping[str, Any],
    actions: list[dict[str, Any]] | None = None,
) -> str:
    """Hash material execution settings without persisting credential values."""
    execution = {key: workflow.get(key) for key in M365_WORKFLOW_FIELDS}
    execution.update({
        key: workflow[key] for key in (
            "definition_version", "reference_inputs", "durable_execution", "flow", "limits",
        ) if key in workflow
    })
    execution["m365_run_as_user_id"] = str(
        workflow.get("m365_run_as_user_id") or ""
    ).strip()
    if actions is not None:
        execution["actions"] = sorted(
            (
                {
                    "id": action.get("id"),
                    "name": action.get("name"),
                    "type": action.get("type"),
                    "enabled_functions": action.get("enabled_functions"),
                    "m365_capabilities": action.get("m365_capabilities"),
                    "msgraph_capabilities": action.get("msgraph_capabilities"),
                    "additionalFields": action.get("additionalFields") or {},
                }
                for action in actions
            ),
            key=lambda action: str(action.get("id") or action.get("name") or ""),
        )
    encoded = json.dumps(
        execution, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_workflow_run_as(
    workflow: dict[str, Any],
    payload: Mapping[str, Any],
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve the explicit account selection, never infer it from ownership."""
    previous = existing or {}
    selected = payload.get(
        "m365_run_as_user_id", previous.get("m365_run_as_user_id", "")
    )
    if not isinstance(selected, str):
        raise ValueError("Microsoft 365 Run as must be a user identifier.")
    selected = selected.strip()
    if len(selected) > 128 or any(character.isspace() for character in selected):
        raise ValueError("Microsoft 365 Run as is not a valid user identifier.")
    workflow["m365_run_as_user_id"] = selected
    workflow["m365_revision"] = workflow_execution_fingerprint(workflow)
    if selected and workflow["m365_revision"] == previous.get("m365_revision"):
        workflow["m365_binding_approval_id"] = previous.get(
            "m365_binding_approval_id"
        )
    else:
        workflow["m365_binding_approval_id"] = None
        if previous.get("status") in M365_ACTIVE_STATES:
            workflow["status"] = "idle"
            workflow["active_run_id"] = ""
    return workflow


def workflow_result_is_waiting(result: Mapping[str, Any]) -> bool:
    run = result.get("run")
    return isinstance(run, Mapping) and run.get("status") in M365_ACTIVE_STATES


def workflow_result_runtime_status(result: Mapping[str, Any]) -> str:
    """Keep a paused run nonterminal instead of advancing it to idle."""
    if workflow_result_is_waiting(result):
        return str(result["run"]["status"])
    return "idle"


def build_waiting_workflow_result(
    workflow: Mapping[str, Any],
    run: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(approval.get("status") or "awaiting_approval")
    if status not in M365_WAITING_STATES:
        status = "awaiting_approval"
    waiting_run = dict(run)
    waiting_run.update({
        "status": status,
        "success": False,
        "completed_at": None,
        "m365_approval": dict(approval),
    })
    return {
        "success": False,
        "pending": True,
        "run": waiting_run,
        "approval": dict(approval),
        "workflow_updates": {
            "status": status,
            "active_run_id": waiting_run.get("id"),
            "last_run_status": status,
            "last_run_error": "",
            "conversation_id": waiting_run.get("conversation_id")
            or workflow.get("conversation_id"),
        },
    }
