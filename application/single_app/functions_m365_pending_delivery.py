# functions_m365_pending_delivery.py
"""Claimed M365 delivery using reviewed material and current subject authorization."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from functions_m365_approvals import M365ApprovalRequired, M365PolicyError, material_fingerprint
from functions_m365_execution import get_m365_execution_context
from functions_m365_transport import M365ProviderError, M365Transport
from m365_interaction import M365_AUTH_INTERACTION_CODES


_dependencies = {}
_CONTEXT_FIELDS = (
    "actor_user_id", "data_user_id", "tenant_id", "conversation_id", "shared",
    "request_id", "workflow_id", "run_id", "step_id", "audience_version",
    "binding_id", "workflow_fingerprint", "connection_id", "group_id", "agent_id",
)
_TERMINAL = {"sent", "cancelled", "failed", "recovery_required"}
DELIVERY_BINDING_VERSION = 1
DELIVERY_RECOVERY_GRACE_SECONDS = 120


def configure_m365_pending_delivery(
    *, container, context_scope, log_event, transport_factory=M365Transport, notification_sender=None,
    capture_agent_reference=None, view_authorizer=None, conversation_authorizer=None,
):
    _dependencies.update(
        container=container, context_scope=context_scope, log_event=log_event,
        transport_factory=transport_factory,
        notification_sender=notification_sender,
        capture_agent_reference=capture_agent_reference,
        view_authorizer=view_authorizer,
        conversation_authorizer=conversation_authorizer,
    )


def notify_m365_pending_delivery(action):
    if not action.get("m365_notification_pending"):
        return action
    sender = _dependencies.get("notification_sender")
    if sender is None:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery notifications are not configured.")
    try:
        if sender(action) is None:
            _dependencies["log_event"](
                "[MS_GRAPH_PENDING_ACTIONS] Delivery notification remains pending.",
                {"action_id": action["id"]},
            )
            return action
        container = _dependencies["container"]
        latest = container.read_item(action["id"], partition_key=action["user_id"])
        if not latest.get("m365_notification_pending"):
            return latest
        latest["m365_notification_pending"] = False
        return container.replace_item(
            latest["id"], body=latest,
            etag=latest["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    except AzureError as error:
        # The saved action remains authoritative even when its notice needs retrying.
        _dependencies["log_event"](
            "[MS_GRAPH_PENDING_ACTIONS] Delivery notification could not be acknowledged.",
            {"action_id": action["id"], "exception_type": type(error).__name__},
        )
        return action


def capture_workflow_delivery(user_id, action_id, workflow_id, run_id):
    """Capture a server-authorized workflow or interactive origin, not client hints."""
    context = get_m365_execution_context()
    if context is None:
        raise M365PolicyError(
            "m365_delivery_context_invalid",
            "An authorized Microsoft 365 execution is required to prepare an outgoing action.",
        )
    if (
        user_id != context.data_user_id
        or (workflow_id or None) != context.workflow_id
        or (run_id or None) != context.run_id or not action_id
    ):
        raise M365PolicyError("m365_delivery_context_invalid", "The pending delivery requires its original authorized context.")
    delivery = {
        "version": DELIVERY_BINDING_VERSION,
        "kind": "workflow" if context.workflow_id else "chat",
        "context": {field: getattr(context, field) for field in _CONTEXT_FIELDS},
        "action_id": action_id,
        "action_type": (context.action_configs.get(action_id) or {}).get("type"),
    }
    if context.workflow_id:
        if not context.binding_id:
            raise M365PolicyError("m365_delivery_context_invalid", "An approved Run as binding is required.")
        delivery["workflow_ref"] = {
            "id": context.workflow_id, "user_id": context.actor_user_id, "group_id": context.group_id,
        }
    else:
        capture = _dependencies.get("capture_agent_reference")
        if capture is None or not context.conversation_id or not context.request_id:
            raise M365PolicyError("m365_delivery_context_invalid", "A selected conversation agent is required for action review.")
        delivery["agent_ref"] = capture(context, action_id)
    return delivery


def pending_delivery_fingerprint(action):
    """Bind reviewed content and execution origin, excluding mutable delivery state."""
    return material_fingerprint({
        name: action.get(name)
        for name in (
            "id", "user_id", "operation", "graph_resource_type", "action_mode",
            "graph_payload", "graph_message_id", "graph_draft_version", "summary",
            "conversation_id", "workflow_id", "run_id", "request_id",
            "auto_send_at_utc", "m365_execution", "graph_endpoint",
        )
    })


def has_verified_delivery_binding(action):
    delivery = action.get("m365_execution")
    if not isinstance(delivery, dict) or not isinstance(delivery.get("context"), dict):
        return False
    snapshot = delivery["context"]
    allowed_operations = {
        "msgraph": {"send_mail", "create_calendar_invite"},
        "m365_email": {"send_mail"},
        "m365_calendar": {"create_calendar_invite"},
    }
    return bool(
        delivery.get("version") == DELIVERY_BINDING_VERSION
        and delivery.get("kind") in {"chat", "workflow"} and delivery.get("action_id")
        and delivery.get("action_type") in {"msgraph", "m365_email", "m365_calendar"}
        and action.get("operation") in allowed_operations[delivery["action_type"]]
        and snapshot.get("data_user_id") == action.get("user_id")
        and snapshot.get("conversation_id") == action.get("conversation_id")
        and snapshot.get("tenant_id") and action.get("material_fingerprint")
        and action.get("graph_payload")
    )


def authorize_pending_action_view(action, viewer_user_id):
    authorize = _dependencies.get("view_authorizer")
    if authorize is None:
        raise M365PolicyError("m365_delivery_unavailable", "Action review authorization is not configured.")
    return authorize(action, viewer_user_id)


def authorize_pending_action_conversation(viewer_user_id, conversation_id):
    authorize = _dependencies.get("conversation_authorizer")
    if authorize is None:
        raise M365PolicyError("m365_delivery_unavailable", "Conversation action review is not configured.")
    return authorize(viewer_user_id, conversation_id)


def _delivery_error(code, message, **details):
    return {"error": code, "message": message, **details}


def _read_delivery(container, user_id, action_id):
    try:
        return container.read_item(action_id, partition_key=user_id)
    except CosmosResourceNotFoundError:
        return None


def _save_claimed_outcome(container, action_id, claimed, completed):
    try:
        saved = container.replace_item(
            action_id, body=completed, etag=claimed["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    except CosmosHttpResponseError as error:
        if error.status_code != 412:
            raise
        latest = _read_delivery(container, claimed["user_id"], action_id)
        return latest, _delivery_error(
            "delivery_outcome_unknown",
            "The remote outcome could not be recorded safely. Check Microsoft 365 before retrying.",
        )
    saved = notify_m365_pending_delivery(saved)
    return saved, None


def _mail_draft_matches(transport, action):
    version = action.get("graph_draft_version")
    draft_id = action.get("graph_message_id")
    if not isinstance(version, str) or not version or not draft_id:
        raise M365PolicyError("m365_action_review_required", "Recreate this email to review its current content before sending.")
    draft = transport.request_json(
        "GET", f"/v1.0/me/messages/{quote(draft_id, safe='')}", ["Mail.ReadWrite"],
        params={"$select": "id,changeKey,isDraft"},
    )
    if draft.get("isDraft") is not True or draft.get("changeKey") != version:
        raise M365PolicyError(
            "m365_action_material_changed",
            "The Outlook draft changed or is no longer a draft. Review or recreate it before sending.",
        )


def dispatch_m365_pending_delivery(
    user_id, action_id, *, cancel=False, expected_version=None, automatic=False,
    token_provider=None,
):
    """Claim one reviewed action; uncertain writes are never automatically replayed."""
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Microsoft 365 delivery is not configured.")
    container = _dependencies["container"]
    action = _read_delivery(container, user_id, action_id)
    if action is None or action.get("user_id") != user_id:
        return None, _delivery_error("not_found", "The pending Microsoft 365 action was not found.")
    status = action.get("status")
    if status in _TERMINAL:
        if status in {"failed", "recovery_required"}:
            return action, _delivery_error(
                "delivery_outcome_unknown" if status == "recovery_required" else "delivery_failed",
                "Check Microsoft 365 before preparing another action. This delivery cannot be retried.",
            )
        return action, None
    if status == "sending":
        return action, _delivery_error("delivery_in_progress", "Delivery is already in progress. Refresh its status.")
    if expected_version is not None and expected_version != action.get("_etag"):
        return action, _delivery_error("pending_action_changed", "This action changed. Review the refreshed card before continuing.")
    now = datetime.now(timezone.utc)
    if cancel:
        cancelled = {
            **action, "status": "cancelled", "cancelled_at": now.isoformat(),
            "updated_at": now.isoformat(), "delivery_claim_expires_at": None,
            "error": "", "error_code": "",
            "delivery_note": "Delivery stopped. An existing Outlook draft is not deleted.",
        }
        try:
            saved = container.replace_item(
                action_id, body=cancelled, etag=action["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except CosmosHttpResponseError as error:
            if error.status_code != 412:
                raise
            return _read_delivery(container, user_id, action_id), _delivery_error(
                "delivery_in_progress", "Another request changed this action. Refresh its current state.",
            )
        return saved, None
    if not has_verified_delivery_binding(action):
        return action, _delivery_error(
            "m365_action_review_required",
            "This older action cannot be safely rebound. Cancel it and prepare a new action for review.",
        )
    if action["material_fingerprint"] != pending_delivery_fingerprint(action):
        return action, _delivery_error("m365_action_material_changed", "The prepared material changed. Recreate it for review.")
    if automatic:
        if action.get("action_mode") != "delayed" or status != "scheduled":
            return action, _delivery_error("delivery_not_scheduled", "This action is not authorized for automatic delivery.")
        due = datetime.fromisoformat(action["auto_send_at_utc"].replace("Z", "+00:00"))
        if due > now:
            return action, _delivery_error("delivery_not_due", "The scheduled delivery time has not arrived.")
        if (action["m365_execution"].get("kind") == "chat"
                and now > due + timedelta(seconds=DELIVERY_RECOVERY_GRACE_SECONDS)):
            return action, _delivery_error("delivery_schedule_expired", "The delivery window expired. Review and send it manually.")
    delivery = action["m365_execution"]
    operation = action.get("operation")
    source = "email" if operation == "send_mail" else "calendar"
    scopes = ["Mail.Send", "Mail.ReadWrite"] if operation == "send_mail" else ["Calendars.ReadWrite"]
    remote_started = False
    claimed = None

    def mark_remote_started():
        nonlocal remote_started
        remote_started = True

    try:
        with _dependencies["context_scope"](action, automatic=automatic):
            transport_options = {"token_provider": token_provider} if token_provider is not None else {}
            transport = _dependencies["transport_factory"](source, delivery["action_id"], **transport_options)
            with transport.operation_context(operation):
                transport.get_token(scopes)
                if operation == "send_mail":
                    _mail_draft_matches(transport, action)
                    path = "/v1.0/me/sendMail"
                    payload = deepcopy(action["graph_payload"])
                elif operation == "create_calendar_invite":
                    path = "/v1.0/me/events"
                    payload = deepcopy(action["graph_payload"])
                    payload.setdefault("transactionId", action["id"])
                else:
                    raise M365PolicyError("unsupported_operation", "This pending operation is not supported.")
                claimed = {
                    **action, "status": "sending", "updated_at": now.isoformat(),
                    "delivery_claim_expires_at": (now + timedelta(minutes=5)).isoformat(),
                    "error": "", "error_code": "",
                }
                try:
                    claimed = container.replace_item(
                        action_id, body=claimed, etag=action["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                except CosmosHttpResponseError as error:
                    if error.status_code != 412:
                        raise
                    return _read_delivery(container, user_id, action_id), _delivery_error(
                        "delivery_in_progress", "Another request already claimed or changed this action.",
                    )
                with transport.callback_context(mark_remote_started, None):
                    result = transport.request_json(
                        "POST", path, scopes, json_body=payload,
                        expect_json=operation == "create_calendar_invite",
                    )
                if operation == "create_calendar_invite" and (
                    not isinstance(result, dict)
                    or not isinstance(result.get("id"), str) or not result["id"].strip()
                ):
                    raise M365ProviderError(
                        "incomplete_response", "Microsoft 365 did not return the created event identifier.",
                    )
        completed = {
            **claimed, "status": "sent", "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": "", "error_code": "", "delivery_claim_expires_at": None,
        }
        if operation == "send_mail":
            completed["delivery_note"] = (
                "Microsoft 365 accepted the reviewed message for sending. "
                "The original Outlook draft remains; do not send it again."
            )
        else:
            completed["graph_event_id"] = result.get("id") or ""
            completed["web_link"] = result.get("webLink") or ""
    except (M365PolicyError, M365ProviderError, PermissionError, LookupError, ValueError, AzureError) as error:
        code = getattr(error, "code", "delivery_not_authorized")
        status_code = getattr(error, "status_code", None)
        details = getattr(error, "details", None) or getattr(error, "payload", None) or {}
        safe_details = {key: details[key] for key in ("scopes", "retry_after_seconds") if key in details}
        retry_after = getattr(error, "retry_after_seconds", None)
        if retry_after is not None:
            safe_details["retry_after_seconds"] = retry_after
        auth_required = code in M365_AUTH_INTERACTION_CODES
        uncertain = remote_started and status_code not in {400, 401, 403, 404, 409, 412, 429}
        if auth_required:
            message = "Reconnect Microsoft 365, then return to this card and choose Send again."
        elif uncertain:
            message = "The delivery outcome is uncertain. Check Microsoft 365 before preparing another action."
        elif code in {"m365_action_material_changed", "m365_action_review_required"}:
            message = "The reviewed draft changed. Recreate the action before sending."
        else:
            message = "Delivery could not be authorized or completed. Review the action and current access."
        response_error = _delivery_error(
            code, message, auth_required=auth_required, sources=[source], **safe_details,
        )
        if isinstance(error, M365ApprovalRequired):
            response_error.update({
                key: error.payload[key] for key in ("approval_id", "approvals", "request_type")
                if key in error.payload
            })
            response_error["approval_required"] = True
        _dependencies["log_event"](
            "[MS_GRAPH_PENDING_ACTIONS] Microsoft 365 delivery did not complete.",
            {"action_id": action_id, "error_code": code, "remote_started": remote_started},
        )
        if claimed is None:
            updated = {
                **action, "error": message, "error_code": code,
                "auth_scopes": safe_details.get("scopes", []),
                "status": "pending" if auth_required and not automatic else "review_required",
                "updated_at": now.isoformat(), "m365_notification_pending": automatic,
            }
            saved, persistence_error = _save_claimed_outcome(container, action_id, action, updated)
            return saved, persistence_error or response_error
        retryable = auth_required or status_code == 429
        completed = {
            **claimed, "status": "recovery_required" if uncertain else "pending" if retryable else "failed",
            "error": message, "error_code": code, "failed_at": now.isoformat(),
            "auth_scopes": safe_details.get("scopes", []),
            "delivery_claim_expires_at": None, "m365_notification_pending": not retryable,
        }
        saved, persistence_error = _save_claimed_outcome(container, action_id, claimed, completed)
        return saved, persistence_error or response_error
    saved, persistence_error = _save_claimed_outcome(container, action_id, claimed, completed)
    return saved, persistence_error


def dispatch_due_m365_deliveries(*, limit=25):
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery is not configured.")
    container = _dependencies["container"]
    now = datetime.now(timezone.utc)
    actions = container.query_items(
        query=(
            "SELECT TOP @limit * FROM c WHERE c.type = 'msgraph_pending_action' "
            "AND ((c.status = 'scheduled' AND c.auto_send_at_utc <= @now) "
            "OR (c.status = 'sending' AND (NOT IS_DEFINED(c.delivery_claim_expires_at) "
            "OR IS_NULL(c.delivery_claim_expires_at) OR c.delivery_claim_expires_at <= @now)) "
            "OR (c.m365_notification_pending = true "
            "AND c.status IN ('pending', 'review_required', 'failed', 'recovery_required')))"
        ),
        parameters=[{"name": "@limit", "value": limit}, {"name": "@now", "value": now.isoformat()}],
        enable_cross_partition_query=True,
    )
    for action in actions:
        action = notify_m365_pending_delivery(action)
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
                updated_at=now.isoformat(),
            )
            try:
                saved = container.replace_item(
                    action["id"], body=action,
                    etag=action["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            except CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
                continue
            notify_m365_pending_delivery(saved)
            continue
        delivery = action.get("m365_execution")
        delivery = delivery if isinstance(delivery, dict) else {}
        if delivery.get("kind") == "chat":
            due = datetime.fromisoformat(action["auto_send_at_utc"].replace("Z", "+00:00"))
            if due + timedelta(seconds=DELIVERY_RECOVERY_GRACE_SECONDS) > now:
                continue
            paused = {
                **action, "status": "review_required", "m365_notification_pending": True,
                "error_code": "delivery_schedule_expired",
                "error": "The delivery timer did not complete. Review this action and send it manually.",
                "updated_at": now.isoformat(),
            }
            try:
                saved = container.replace_item(
                    action["id"], body=paused, etag=action["_etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
            except CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
                continue
            notify_m365_pending_delivery(saved)
            continue
        if not has_verified_delivery_binding(action):
            paused = {
                **action, "status": "review_required",
                "error": "This older delivery needs renewed review before it can be sent.",
                "error_code": "m365_action_review_required",
                "m365_notification_pending": bool(action.get("m365_execution")),
                "updated_at": now.isoformat(),
            }
            try:
                saved = container.replace_item(action["id"], body=paused, etag=action["_etag"], match_condition=MatchConditions.IfNotModified)
            except CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
                continue
            notify_m365_pending_delivery(saved)
            continue
        dispatch_m365_pending_delivery(action["user_id"], action["id"], automatic=True)


def cancel_m365_run_deliveries(workflow_id, run_id):
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Workflow delivery is not configured.")
    actions = _dependencies["container"].query_items(
        query=(
            "SELECT * FROM c WHERE IS_OBJECT(c.m365_execution) "
            "AND c.workflow_id = @workflow_id AND c.run_id = @run_id "
            "AND c.status IN ('pending', 'scheduled', 'review_required')"
        ),
        parameters=[{"name": "@workflow_id", "value": workflow_id}, {"name": "@run_id", "value": run_id}],
        enable_cross_partition_query=True,
    )
    _cancel_pending_deliveries(actions)


def cancel_m365_conversation_deliveries(conversation_id):
    """Stop unsent intents after the lifecycle owner authorizes this exact conversation."""
    if not isinstance(conversation_id, str) or not conversation_id:
        raise M365PolicyError("invalid_parameters", "A conversation is required to stop its outgoing actions.")
    if not _dependencies:
        raise M365PolicyError("m365_delivery_unavailable", "Microsoft 365 delivery is not configured.")
    actions = _dependencies["container"].query_items(
        query=(
            "SELECT * FROM c WHERE c.type = 'msgraph_pending_action' "
            "AND c.conversation_id = @conversation_id "
            "AND c.status IN ('pending', 'scheduled', 'review_required')"
        ),
        parameters=[{"name": "@conversation_id", "value": conversation_id}],
        enable_cross_partition_query=True,
    )
    _cancel_pending_deliveries(actions)


def _cancel_pending_deliveries(actions):
    for action in actions:
        for _attempt in range(3):
            saved, error = dispatch_m365_pending_delivery(action["user_id"], action["id"], cancel=True)
            if not error or error["error"] == "not_found":
                break
            if saved and saved.get("status") in {"pending", "scheduled", "review_required"}:
                continue
            if not saved or saved.get("status") not in _TERMINAL | {"sending"}:
                raise M365PolicyError(
                    "m365_delivery_cleanup_conflict",
                    "The outgoing action state could not be confirmed. Refresh it before retrying cancellation.",
                )
            _dependencies["log_event"](
                "[MS_GRAPH_PENDING_ACTIONS] Cleanup found a completed or already-claimed delivery.",
                {"action_id": action["id"], "conversation_id": action.get("conversation_id"), "error_code": error["error"]},
            )
            break
        else:
            raise M365PolicyError(
                "m365_delivery_cleanup_conflict",
                "An outgoing action is changing. Retry cancellation after its status refreshes.",
            )
