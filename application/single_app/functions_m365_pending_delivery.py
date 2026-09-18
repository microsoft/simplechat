# functions_m365_pending_delivery.py
"""Claimed workflow delivery using fresh Run as authorization, never saved tokens."""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from functions_m365_approvals import M365ApprovalRequired, M365PolicyError, get_m365_approval_service
from functions_m365_execution import get_m365_execution_context
from functions_m365_transport import M365ProviderError, M365Transport


_dependencies = {}
_CONTEXT_FIELDS = (
    "actor_user_id", "data_user_id", "tenant_id", "conversation_id", "shared",
    "request_id", "workflow_id", "run_id", "step_id", "audience_version",
    "binding_id", "workflow_fingerprint", "connection_id", "group_id",
)
_TERMINAL = {"sent", "cancelled", "failed", "recovery_required"}


def configure_m365_pending_delivery(
    *, container, context_scope, log_event, transport_factory=M365Transport, notification_sender=None,
):
    _dependencies.update(
        container=container, context_scope=context_scope, log_event=log_event,
        transport_factory=transport_factory,
        notification_sender=notification_sender,
    )


def notify_m365_pending_delivery(action):
    if not action.get("m365_notification_pending"):
        return
    sender = _dependencies.get("notification_sender")
    if sender is None:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery notifications are not configured.")
    if sender(action) is None:
        _dependencies["log_event"](
            "[MS_GRAPH_PENDING_ACTIONS] Workflow delivery notification remains pending.",
            {"action_id": action["id"]},
        )
        return
    container = _dependencies["container"]
    latest = container.read_item(action["id"], partition_key=action["user_id"])
    if not latest.get("m365_notification_pending"):
        return
    latest["m365_notification_pending"] = False
    container.replace_item(
        latest["id"], body=latest,
        etag=latest["_etag"], match_condition=MatchConditions.IfNotModified,
    )


def capture_workflow_delivery(user_id, action_id, workflow_id, run_id):
    context = get_m365_execution_context()
    if context is None or not context.workflow_id:
        return None
    if (
        user_id != context.data_user_id or workflow_id != context.workflow_id
        or run_id != context.run_id or not action_id or not context.binding_id
    ):
        raise M365PolicyError("m365_delivery_context_invalid", "The pending delivery requires its approved Run as context.")
    return {
        "context": {field: getattr(context, field) for field in _CONTEXT_FIELDS},
        "action_id": action_id,
        "workflow_ref": {
            "id": context.workflow_id, "user_id": context.actor_user_id, "group_id": context.group_id,
        },
    }


def dispatch_m365_pending_delivery(user_id, action_id, *, cancel=False):
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery is not configured.")
    container = _dependencies["container"]
    try:
        action = container.read_item(action_id, partition_key=user_id)
    except CosmosResourceNotFoundError:
        return None, {"error": "not_found", "message": "The pending workflow delivery no longer exists."}
    delivery = action.get("m365_execution") or {}
    snapshot = delivery.get("context") or {}
    if (
        action.get("user_id") != user_id or snapshot.get("data_user_id") != user_id
        or snapshot.get("workflow_id") != action.get("workflow_id")
        or snapshot.get("run_id") != action.get("run_id")
        or not snapshot.get("workflow_id")
    ):
        raise M365PolicyError("m365_delivery_context_invalid", "This delivery belongs to a different approved execution.")
    status = action.get("status")
    if status in _TERMINAL:
        if status in {"failed", "recovery_required"}:
            return action, {
                "error": action.get("error_code") or "delivery_failed",
                "message": action.get("error") or "This workflow delivery did not complete.",
            }
        return action, None
    if status == "sending":
        return action, {
            "error": "delivery_in_progress",
            "message": "Delivery is already claimed. Check its outcome before starting another action.",
        }
    now = datetime.now(timezone.utc)
    claimed = {
        **action, "status": "cancelled" if cancel else "sending",
        "delivery_claim_expires_at": (now + timedelta(minutes=5)).isoformat(),
        "updated_at": now.isoformat(),
    }
    if cancel:
        claimed["cancelled_at"] = now.isoformat()
        claimed["delivery_note"] = "Automatic delivery stopped. An existing Outlook draft is not deleted."
    try:
        claimed = container.replace_item(
            action_id, body=claimed,
            etag=action["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except CosmosHttpResponseError as error:
        if error.status_code != 412:
            raise
        return action, {"error": "delivery_in_progress", "message": "Another worker changed this delivery."}
    if cancel:
        return claimed, None
    remote_started = False
    try:
        with _dependencies["context_scope"](claimed):
            operation = claimed.get("operation")
            if operation == "send_mail":
                draft_id = claimed.get("graph_message_id")
                if not draft_id:
                    raise ValueError("A saved draft is required.")
                source, scopes = "email", ["Mail.Send"]
                path = f"/v1.0/me/messages/{quote(draft_id, safe='')}/send"
                payload = None
            elif operation == "create_calendar_invite":
                source, scopes = "calendar", ["Calendars.ReadWrite"]
                path = "/v1.0/me/events"
                payload = claimed.get("graph_payload")
                if not isinstance(payload, dict) or not payload:
                    raise ValueError("A saved event is required.")
            else:
                raise ValueError("Unsupported pending workflow operation.")
            transport = _dependencies["transport_factory"](source, delivery["action_id"])
            remote_started = True
            result = transport.request_json(
                "POST", path, scopes, json_body=payload,
                expect_json=operation == "create_calendar_invite",
            )
        completed = {
            **claimed, "status": "sent", "completed_at": now.isoformat(),
            "error": "", "delivery_claim_expires_at": None,
        }
        if operation == "create_calendar_invite":
            completed["graph_event_id"] = result.get("id") or ""
            completed["web_link"] = result.get("webLink") or ""
    except (M365PolicyError, M365ProviderError, PermissionError, LookupError, ValueError, AzureError) as error:
        if isinstance(error, M365ApprovalRequired):
            get_m365_approval_service().record_execution_status(
                error.approval_id, user_id, snapshot["request_id"], "cancelled",
            )
        code = getattr(error, "code", "delivery_not_authorized")
        uncertain = remote_started and not isinstance(error, (M365PolicyError, PermissionError, ValueError))
        message = (
            "The delivery outcome is uncertain. Check Microsoft 365 before starting a new action."
            if uncertain else "Workflow delivery requires renewed authorization. Reconnect or start a newly approved run."
        )
        completed = {
            **claimed, "status": "recovery_required" if uncertain else "failed",
            "error": message, "error_code": code, "failed_at": now.isoformat(),
            "delivery_claim_expires_at": None,
            "m365_notification_pending": True,
        }
        _dependencies["log_event"](
            "[MS_GRAPH_PENDING_ACTIONS] Workflow delivery did not complete.",
            {"action_id": action_id, "error_code": code, "status": completed["status"]},
        )
    saved = container.replace_item(
        action_id, body=completed,
        etag=claimed["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    notify_m365_pending_delivery(saved)
    return saved, (
        {"error": saved["error_code"], "message": saved["error"]}
        if saved["status"] != "sent" else None
    )


def dispatch_due_m365_deliveries(*, limit=25):
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery is not configured.")
    container = _dependencies["container"]
    now = datetime.now(timezone.utc)
    actions = container.query_items(
        query=(
            "SELECT TOP @limit * FROM c WHERE IS_OBJECT(c.m365_execution) "
            "AND ((c.status IN ('scheduled', 'sending') AND c.auto_send_at_utc <= @now) "
            "OR (c.m365_notification_pending = true AND c.status IN ('pending', 'failed', 'recovery_required')))"
        ),
        parameters=[{"name": "@limit", "value": limit}, {"name": "@now", "value": now.isoformat()}],
        enable_cross_partition_query=True,
    )
    for action in actions:
        notify_m365_pending_delivery(action)
        if action["status"] not in {"scheduled", "sending"}:
            continue
        if action["status"] == "sending":
            expires = action.get("delivery_claim_expires_at")
            if expires and datetime.fromisoformat(expires) > now:
                continue
            action.update(
                status="recovery_required",
                error="The delivery worker stopped. Check Microsoft 365 before starting another action.",
                error_code="delivery_outcome_unknown",
                m365_notification_pending=True,
            )
            try:
                container.replace_item(
                    action["id"], body=action,
                    etag=action["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            except CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
            continue
        dispatch_m365_pending_delivery(action["user_id"], action["id"])


def cancel_m365_run_deliveries(workflow_id, run_id):
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery is not configured.")
    actions = _dependencies["container"].query_items(
        query=(
            "SELECT * FROM c WHERE IS_OBJECT(c.m365_execution) "
            "AND c.workflow_id = @workflow_id AND c.run_id = @run_id "
            "AND c.status IN ('pending', 'scheduled')"
        ),
        parameters=[{"name": "@workflow_id", "value": workflow_id}, {"name": "@run_id", "value": run_id}],
        enable_cross_partition_query=True,
    )
    for action in actions:
        dispatch_m365_pending_delivery(action["user_id"], action["id"], cancel=True)
