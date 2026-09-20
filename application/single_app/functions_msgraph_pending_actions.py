# functions_msgraph_pending_actions.py

"""User-owned pending Microsoft Graph action helpers."""

import base64
from copy import deepcopy
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict
from azure.cosmos import exceptions

from config import cosmos_msgraph_pending_actions_container
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_msgraph_operations import MSGRAPH_DEFAULT_ENDPOINT
from functions_m365_action_cards import record_pending_action_reference
from functions_m365_pending_delivery import (
    capture_workflow_delivery, dispatch_m365_pending_delivery, notify_m365_pending_delivery,
    authorize_pending_action_conversation, authorize_pending_action_view,
    has_verified_delivery_binding, pending_delivery_fingerprint,
)
from functions_m365_context import M365PolicyError, material_fingerprint
from m365_interaction import M365_AUTH_INTERACTION_CODES


MSGRAPH_PENDING_ACTION_TYPE = 'msgraph_pending_action'
MSGRAPH_PENDING_STATUS_PENDING = 'pending'
MSGRAPH_PENDING_STATUS_SCHEDULED = 'scheduled'
MSGRAPH_PENDING_STATUS_SENT = 'sent'
MSGRAPH_PENDING_STATUS_CANCELLED = 'cancelled'
MSGRAPH_PENDING_STATUS_FAILED = 'failed'
MSGRAPH_PENDING_TERMINAL_STATUSES = {
    MSGRAPH_PENDING_STATUS_SENT,
    MSGRAPH_PENDING_STATUS_CANCELLED,
    MSGRAPH_PENDING_STATUS_FAILED,
    'sending',
    'recovery_required',
}

MSGRAPH_PENDING_OPERATION_SEND_MAIL = 'send_mail'
MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE = 'create_calendar_invite'

MSGRAPH_PENDING_ACTION_MANUAL = 'manual'
MSGRAPH_PENDING_ACTION_DELAYED = 'delayed'

MSGRAPH_PENDING_RESOURCE_MAIL = 'mail'
MSGRAPH_PENDING_RESOURCE_CALENDAR = 'calendar'

MSGRAPH_PENDING_TIMER_MAX_SECONDS = 600
MSGRAPH_PENDING_PREVIEW_CHARACTERS = 4000

_scheduled_timer_lock = threading.Lock()
_scheduled_timers: Dict[str, threading.Timer] = {}


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().replace(microsecond=0).isoformat()


def _normalize_text(value):
    return str(value or '').strip()


def _coerce_datetime(value):
    normalized_value = _normalize_text(value)
    if not normalized_value:
        return None
    try:
        return datetime.fromisoformat(normalized_value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _strip_cosmos_metadata(document):
    if not isinstance(document, dict):
        return {}
    result = {key: value for key, value in document.items() if not str(key).startswith('_')}
    if document.get("_etag"):
        result["version"] = document["_etag"]
    return result


def _extract_email_address(recipient):
    if not isinstance(recipient, dict):
        return ''
    email_address = recipient.get('emailAddress') if isinstance(recipient.get('emailAddress'), dict) else {}
    return _normalize_text(email_address.get('address'))


def _extract_recipient_addresses(recipients):
    addresses = []
    for recipient in recipients or []:
        address = _extract_email_address(recipient)
        if address and address not in addresses:
            addresses.append(address)
    return addresses


def build_mail_pending_action_summary(message_payload):
    """Build a client-safe summary for a pending mail action."""
    payload = message_payload if isinstance(message_payload, dict) else {}
    return {
        'subject': _normalize_text(payload.get('subject')),
        'to_recipients': _extract_recipient_addresses(payload.get('toRecipients')),
        'cc_recipients': _extract_recipient_addresses(payload.get('ccRecipients')),
        'bcc_recipient_count': len(payload.get('bccRecipients') or []),
        'bcc_recipients': _extract_recipient_addresses(payload.get('bccRecipients')),
        'body_preview': str((payload.get('body') or {}).get('content') or ''),
        'content_type': _normalize_text((payload.get('body') or {}).get('contentType')) or 'Text',
    }


def build_calendar_pending_action_summary(event_payload):
    """Build a client-safe summary for a pending calendar invite action."""
    payload = event_payload if isinstance(event_payload, dict) else {}
    start_payload = payload.get('start') if isinstance(payload.get('start'), dict) else {}
    end_payload = payload.get('end') if isinstance(payload.get('end'), dict) else {}
    location_payload = payload.get('location') if isinstance(payload.get('location'), dict) else {}
    return {
        'subject': _normalize_text(payload.get('subject')),
        'start_datetime': _normalize_text(start_payload.get('dateTime')),
        'end_datetime': _normalize_text(end_payload.get('dateTime')),
        'timezone': _normalize_text(start_payload.get('timeZone')),
        'location': _normalize_text(location_payload.get('displayName')),
        'attendee_recipients': _extract_recipient_addresses(payload.get('attendees')),
        'body_preview': str((payload.get('body') or {}).get('content') or ''),
        'content_type': _normalize_text((payload.get('body') or {}).get('contentType')) or 'Text',
        'teams_meeting_requested': payload.get('isOnlineMeeting') is True,
    }


def sanitize_msgraph_pending_action_for_client(
    action, *, viewer_user_id=None, include_preview=True, include_full_review=False,
):
    """Return a browser-safe pending action payload without stored Graph request bodies."""
    action = action if isinstance(action, dict) else {}
    status = _normalize_text(action.get('status')) or MSGRAPH_PENDING_STATUS_PENDING
    action_mode = _normalize_text(action.get('action_mode')) or MSGRAPH_PENDING_ACTION_MANUAL
    graph_resource_type = _normalize_text(action.get('graph_resource_type'))
    terminal = status in MSGRAPH_PENDING_TERMINAL_STATUSES
    due_at = _normalize_text(action.get('auto_send_at_utc'))
    can_manage = viewer_user_id is not None and viewer_user_id == action.get('user_id')
    bound = has_verified_delivery_binding(action)
    needs_recreation = not terminal and (
        not bound or action.get("material_fingerprint") != pending_delivery_fingerprint(action)
        or action.get("error_code") in {
            "m365_action_material_changed", "m365_action_review_required", "m365_context_changed",
            "m365_action_changed", "m365_workflow_changed",
        }
    )
    summary = deepcopy(action.get('summary')) if isinstance(action.get('summary'), dict) else {}
    allowed_summary = {
        'subject', 'to_recipients', 'cc_recipients', 'bcc_recipient_count',
        'start_datetime', 'end_datetime', 'timezone', 'location', 'attendee_recipients',
        'teams_meeting_requested',
    }
    if can_manage:
        allowed_summary.update({'bcc_recipients', 'body_preview', 'content_type'})
    else:
        allowed_summary = {'subject', 'start_datetime', 'end_datetime', 'timezone', 'teams_meeting_requested'}
    summary = {key: value for key, value in summary.items() if key in allowed_summary}
    body = summary.get("body_preview", "")
    full_review_required = (
        can_manage and isinstance(body, str)
        and len(body) > MSGRAPH_PENDING_PREVIEW_CHARACTERS and not include_full_review
    )
    if full_review_required:
        summary["body_preview"] = body[:MSGRAPH_PENDING_PREVIEW_CHARACTERS]
        summary["body_preview_truncated"] = True
        summary["body_length"] = len(body)
    if not include_preview:
        summary.pop("body_preview", None)
        summary.pop("bcc_recipients", None)
    error_code = action.get("error_code") or ""
    if error_code in M365_AUTH_INTERACTION_CODES:
        safe_error = "Reconnect Microsoft 365, then return to this card and choose Send again."
    elif error_code in {"delivery_outcome_unknown", "timeout", "transport_error", "incomplete_response"}:
        safe_error = "The delivery outcome needs review in Microsoft 365 before another action is sent."
    elif needs_recreation:
        safe_error = "The saved action needs renewed review. Cancel it and prepare a new action."
    else:
        safe_error = "This action could not be completed. Review its current status." if action.get("error") else ""

    return {
        'id': action.get('id'),
        'type': MSGRAPH_PENDING_ACTION_TYPE,
        'operation': action.get('operation'),
        'graph_resource_type': graph_resource_type,
        'status': status,
        'action_mode': action_mode,
        'subject': summary.get('subject') or '',
        'summary': summary,
        'version': action.get('_etag') or action.get('version') or '',
        'viewer_is_owner': can_manage,
        'request_id': action.get('request_id') or '',
        'conversation_id': action.get('conversation_id') or '',
        'workflow_id': action.get('workflow_id') or '',
        'run_id': action.get('run_id') or '',
        'message_id': (action.get('graph_message_id') or '') if can_manage else '',
        'event_id': (action.get('graph_event_id') or '') if can_manage else '',
        'web_link': (action.get('web_link') or '') if can_manage else '',
        'created_at': action.get('created_at') or '',
        'updated_at': action.get('updated_at') or '',
        'auto_send_at_utc': due_at,
        'completed_at': action.get('completed_at') or '',
        'cancelled_at': action.get('cancelled_at') or '',
        'failed_at': action.get('failed_at') or '',
        'delay_seconds': action.get('delay_seconds'),
        'error': safe_error,
        'error_code': error_code,
        'auth_required': can_manage and error_code in M365_AUTH_INTERACTION_CODES,
        'scopes': (action.get('auth_scopes') or []) if can_manage else [],
        'sources': ['email' if graph_resource_type == 'mail' else 'calendar'],
        'delivery_note': action.get('delivery_note') or '',
        'requires_review': needs_recreation or status == 'review_required',
        'requires_recreation': needs_recreation,
        'review_details_required': full_review_required and include_preview,
        'review_message': (
            'This older action needs a new review. Cancel it and ask the agent to prepare it again.'
            if needs_recreation else ''
        ),
        'can_approve': can_manage and bound and not needs_recreation and not terminal and not full_review_required and action_mode == MSGRAPH_PENDING_ACTION_MANUAL,
        'can_cancel': can_manage and not terminal,
        'can_send_now': can_manage and bound and not needs_recreation and not terminal and not full_review_required,
        'will_auto_send': bound and status == 'scheduled' and action_mode == MSGRAPH_PENDING_ACTION_DELAYED and bool(due_at),
    }


def create_msgraph_pending_action(
    user_id,
    *,
    operation,
    graph_resource_type,
    action_mode,
    status=None,
    graph_message_id='',
    graph_event_id='',
    graph_draft_version='',
    graph_payload=None,
    summary=None,
    conversation_id='',
    workflow_id='',
    run_id='',
    auto_send_at_utc='',
    delay_seconds=None,
    graph_endpoint=MSGRAPH_DEFAULT_ENDPOINT,
    web_link='',
    m365_action_id='',
):
    """Create a pending Microsoft Graph action record."""
    if operation not in {MSGRAPH_PENDING_OPERATION_SEND_MAIL, MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE}:
        raise M365PolicyError("unsupported_operation", "This action does not support confirmation cards.")
    if action_mode not in {MSGRAPH_PENDING_ACTION_MANUAL, MSGRAPH_PENDING_ACTION_DELAYED}:
        raise M365PolicyError("invalid_parameters", "Select a supported confirmation mode.")
    expected_resource = MSGRAPH_PENDING_RESOURCE_MAIL if operation == MSGRAPH_PENDING_OPERATION_SEND_MAIL else MSGRAPH_PENDING_RESOURCE_CALENDAR
    if graph_resource_type != expected_resource:
        raise M365PolicyError("invalid_parameters", "The pending action resource does not match its operation.")
    if status not in (None, "", MSGRAPH_PENDING_STATUS_PENDING, MSGRAPH_PENDING_STATUS_SCHEDULED):
        raise M365PolicyError("invalid_parameters", "A new action must wait for review or its scheduled delivery.")
    delivery = capture_workflow_delivery(user_id, m365_action_id, workflow_id, run_id)
    if not isinstance(graph_payload, dict) or not graph_payload:
        raise M365PolicyError("invalid_parameters", "The complete outgoing content is required for review.")
    if graph_resource_type == MSGRAPH_PENDING_RESOURCE_MAIL:
        message = graph_payload.get("message")
        if not isinstance(message, dict) or not message or not graph_message_id or not graph_draft_version:
            raise M365PolicyError("m365_action_review_required", "A saved, versioned Outlook draft is required for review.")
        summary = build_mail_pending_action_summary(message)
    else:
        summary = build_calendar_pending_action_summary(graph_payload)
    due = _coerce_datetime(auto_send_at_utc)
    if action_mode == MSGRAPH_PENDING_ACTION_DELAYED and (
        due is None or due.tzinfo is None
        or type(delay_seconds) is not int or not 0 <= delay_seconds <= MSGRAPH_PENDING_TIMER_MAX_SECONDS
    ):
        raise M365PolicyError("invalid_parameters", "A bounded delivery delay and UTC due time are required.")
    expected_status = (
        MSGRAPH_PENDING_STATUS_SCHEDULED if action_mode == MSGRAPH_PENDING_ACTION_DELAYED
        else MSGRAPH_PENDING_STATUS_PENDING
    )
    if status and status != expected_status:
        raise M365PolicyError("invalid_parameters", "The pending action status does not match its delivery mode.")
    created_at = _utc_now_iso()
    normalized_status = _normalize_text(status) or (
        MSGRAPH_PENDING_STATUS_SCHEDULED
        if action_mode == MSGRAPH_PENDING_ACTION_DELAYED
        else MSGRAPH_PENDING_STATUS_PENDING
    )
    action_record = {
        'id': str(uuid.uuid4()),
        'user_id': _normalize_text(user_id),
        'type': MSGRAPH_PENDING_ACTION_TYPE,
        'operation': _normalize_text(operation),
        'graph_resource_type': _normalize_text(graph_resource_type),
        'status': normalized_status,
        'action_mode': _normalize_text(action_mode),
        'graph_message_id': _normalize_text(graph_message_id),
        'graph_event_id': _normalize_text(graph_event_id),
        'graph_payload': deepcopy(graph_payload) if isinstance(graph_payload, dict) else {},
        'graph_draft_version': _normalize_text(graph_draft_version),
        'summary': deepcopy(summary) if isinstance(summary, dict) else {},
        'conversation_id': _normalize_text(conversation_id),
        'workflow_id': _normalize_text(workflow_id),
        'run_id': _normalize_text(run_id),
        'auto_send_at_utc': _normalize_text(auto_send_at_utc),
        'delay_seconds': delay_seconds,
        'graph_endpoint': _normalize_text(graph_endpoint) or MSGRAPH_DEFAULT_ENDPOINT,
        'web_link': _normalize_text(web_link),
        'created_at': created_at,
        'updated_at': created_at,
    }
    snapshot = delivery["context"]
    if snapshot.get("conversation_id") != action_record["conversation_id"]:
        raise M365PolicyError("m365_delivery_context_invalid", "The pending action has a different conversation.")
    action_record['m365_execution'] = delivery
    action_record['request_id'] = snapshot.get("request_id") or ""
    action_record['m365_notification_pending'] = action_mode == MSGRAPH_PENDING_ACTION_MANUAL
    if graph_resource_type == MSGRAPH_PENDING_RESOURCE_MAIL and action_record['graph_payload']:
        action_record['delivery_note'] = (
            "Send uses the content reviewed here. The Outlook draft is retained so external edits are not overwritten."
        )
    action_record["material_fingerprint"] = pending_delivery_fingerprint(action_record)
    if not has_verified_delivery_binding(action_record):
        raise M365PolicyError("m365_delivery_context_invalid", "The outgoing action needs its authorized operation binding.")
    saved = cosmos_msgraph_pending_actions_container.create_item(body=action_record)
    record_pending_action_reference(saved, log_event=log_event)
    saved = notify_m365_pending_delivery(saved)
    return _strip_cosmos_metadata(saved)


def get_msgraph_pending_action(user_id, action_id):
    """Fetch one pending Microsoft Graph action owned by the user."""
    normalized_user_id = _normalize_text(user_id)
    normalized_action_id = _normalize_text(action_id)
    if not normalized_user_id or not normalized_action_id:
        return None

    try:
        item = cosmos_msgraph_pending_actions_container.read_item(
            item=normalized_action_id,
            partition_key=normalized_user_id,
        )
        return _strip_cosmos_metadata(item)
    except exceptions.CosmosResourceNotFoundError:
        return None


def _pending_query(user_id, *, conversation_id='', workflow_id='', run_id='', request_id='', active_only=False, owner_only=True):
    if not isinstance(user_id, str) or not user_id:
        raise M365PolicyError("invalid_parameters", "A signed-in action owner is required.")
    clauses = ["c.type = @type"]
    parameters = [{"name": "@type", "value": MSGRAPH_PENDING_ACTION_TYPE}]
    for field, value in (
        ("user_id", user_id), ("conversation_id", conversation_id),
        ("workflow_id", workflow_id), ("run_id", run_id), ("request_id", request_id),
    ):
        if field == "user_id" and not owner_only:
            continue
        if not value:
            continue
        if not isinstance(value, str) or len(value) > 256:
            raise M365PolicyError("invalid_parameters", "The pending-action filter is invalid.")
        clauses.append(f"c.{field} = @{field}")
        parameters.append({"name": f"@{field}", "value": value})
    if active_only:
        clauses.append("c.status IN ('pending', 'scheduled', 'sending', 'review_required', 'recovery_required')")
    return " AND ".join(clauses), parameters


def list_msgraph_pending_actions(user_id, conversation_id='', workflow_id='', run_id='', limit=100):
    """Return a bounded recent owner list; a storage failure is never an empty inbox."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise M365PolicyError("invalid_parameters", "Choose an action page size from 1 to 100.")
    where, parameters = _pending_query(
        user_id, conversation_id=conversation_id, workflow_id=workflow_id, run_id=run_id,
    )
    parameters.append({"name": "@limit", "value": limit})
    items = cosmos_msgraph_pending_actions_container.query_items(
        query=f"SELECT TOP @limit * FROM c WHERE {where} ORDER BY c.created_at DESC",
        parameters=parameters, partition_key=user_id,
    )
    return [_strip_cosmos_metadata(item) for item in items]


def _cursor_scope(user_id, filters):
    return material_fingerprint({"user_id": user_id, **filters})


def get_pending_action_page(
    user_id, *, conversation_id='', workflow_id='', run_id='', active_only=False,
    continuation_token='', limit=50,
):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise M365PolicyError("invalid_parameters", "Choose an action page size from 1 to 100.")
    if conversation_id:
        conversation_id = authorize_pending_action_conversation(user_id, conversation_id)
    filters = {
        "conversation_id": conversation_id, "workflow_id": workflow_id,
        "run_id": run_id, "active_only": active_only,
    }
    cursor = None
    if continuation_token:
        try:
            if not isinstance(continuation_token, str) or len(continuation_token) > 16384:
                raise ValueError("Invalid cursor size")
            envelope = json.loads(base64.urlsafe_b64decode(continuation_token.encode("ascii")))
            if not isinstance(envelope, dict) or envelope.get("scope") != _cursor_scope(user_id, filters) or not isinstance(envelope.get("cursor"), str):
                raise ValueError("Different cursor scope")
            cursor = envelope["cursor"]
        except (ValueError, UnicodeError, TypeError) as error:
            raise M365PolicyError("invalid_parameters", "This action page cursor is invalid for the current request.") from error
    owner_only = not bool(conversation_id)
    where, parameters = _pending_query(user_id, **filters, owner_only=owner_only)
    query_scope = {"partition_key": user_id} if owner_only else {"enable_cross_partition_query": True}
    # Python Cosmos continuations support cross-partition streaming, not sorted aggregates.
    order = " ORDER BY c.created_at DESC" if owner_only else ""
    items = cosmos_msgraph_pending_actions_container.query_items(
        query=f"SELECT * FROM c WHERE {where}{order}",
        parameters=parameters, max_item_count=limit, **query_scope,
    )
    pages = items.by_page(continuation_token=cursor)
    rows = list(next(pages, []))
    cards = []
    for action in rows:
        if authorize_pending_action_view(action, user_id):
            cards.append(sanitize_msgraph_pending_action_for_client(action, viewer_user_id=user_id))
    next_cursor = pages.continuation_token
    continuation = (
        base64.urlsafe_b64encode(json.dumps({
            "scope": _cursor_scope(user_id, filters), "cursor": next_cursor,
        }).encode("utf-8")).decode("ascii")
        if next_cursor else None
    )
    return {"success": True, "pending_actions": cards, "continuation_token": continuation}


def get_chat_pending_action_cards(
    viewer_user_id, conversation_id, *, request_id=None, action_ids=None, include_full_review=False,
):
    """Project current records only after proving access to this exact conversation."""
    canonical_id = authorize_pending_action_conversation(viewer_user_id, conversation_id)
    if action_ids is not None and (
        not isinstance(action_ids, (list, tuple))
        or len(action_ids) > 100
        or any(not isinstance(value, str) or not 1 <= len(value) <= 256 for value in action_ids)
    ):
        raise M365PolicyError("invalid_parameters", "The pending action references are invalid.")
    if action_ids == [] or action_ids == ():
        return []
    clauses = ["c.type = @type", "c.conversation_id = @conversation_id"]
    parameters = [
        {"name": "@type", "value": MSGRAPH_PENDING_ACTION_TYPE},
        {"name": "@conversation_id", "value": canonical_id},
    ]
    if request_id:
        if not isinstance(request_id, str) or len(request_id) > 256:
            raise M365PolicyError("invalid_parameters", "The pending action request is invalid.")
        clauses.append("c.request_id = @request_id")
        parameters.append({"name": "@request_id", "value": request_id})
    if action_ids:
        clauses.append("ARRAY_CONTAINS(@action_ids, c.id)")
        parameters.append({"name": "@action_ids", "value": list(dict.fromkeys(action_ids))})
    items = cosmos_msgraph_pending_actions_container.query_items(
        query=f"SELECT TOP 100 * FROM c WHERE {' AND '.join(clauses)} ORDER BY c.created_at DESC",
        parameters=parameters, enable_cross_partition_query=True,
    )
    return [
        sanitize_msgraph_pending_action_for_client(
            action, viewer_user_id=viewer_user_id, include_full_review=include_full_review,
        )
        for action in items if authorize_pending_action_view(action, viewer_user_id)
    ]


def hydrate_m365_pending_action_cards(messages, viewer_user_id, conversation_id):
    """Resolve message references with current viewer access, never saved controls."""
    projected = []
    for message in messages:
        item = dict(message)
        item.pop("m365_pending_actions", None)
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            metadata = dict(metadata)
            metadata.pop("m365_pending_actions", None)
            item["metadata"] = metadata
            action_ids = metadata.get("m365_pending_action_ids")
            if isinstance(action_ids, list) and action_ids:
                cards = {}
                for offset in range(0, len(action_ids), 100):
                    resolved = get_chat_pending_action_cards(
                        viewer_user_id, conversation_id,
                        request_id=metadata.get("m365_request_id") or None,
                        action_ids=action_ids[offset:offset + 100],
                    )
                    cards.update((card["id"], card) for card in resolved)
                metadata["m365_pending_action_ids"] = list(cards)
                item["m365_pending_actions"] = list(cards.values())
        projected.append(item)
    return projected


def _commit_msgraph_pending_action_with_token(user_id, action_id, token):
    def subject_token(scopes, context):
        if context.data_user_id != user_id:
            raise M365PolicyError("m365_principal_mismatch", "The scheduled delivery has a different data owner.")
        return {"access_token": token}
    return dispatch_m365_pending_delivery(
        user_id, action_id, automatic=True, token_provider=subject_token,
    )


def approve_msgraph_pending_action(user_id, action_id, *, expected_version=None):
    """Send only the reviewed, owner-bound record through the claimed dispatcher."""
    return dispatch_m365_pending_delivery(user_id, action_id, expected_version=expected_version)


def cancel_msgraph_pending_action(user_id, action_id, *, expected_version=None):
    """Stop delivery locally; mailbox authentication cannot prevent cancellation."""
    action, error = dispatch_m365_pending_delivery(
        user_id, action_id, cancel=True, expected_version=expected_version,
    )
    if action and action.get("status") == MSGRAPH_PENDING_STATUS_CANCELLED:
        _cancel_scheduled_timer(action_id)
    return action, error


def _cancel_scheduled_timer(action_id):
    normalized_action_id = _normalize_text(action_id)
    if not normalized_action_id:
        return
    with _scheduled_timer_lock:
        timer = _scheduled_timers.pop(normalized_action_id, None)
    if timer:
        timer.cancel()


def schedule_msgraph_pending_action_auto_commit(action, token):
    """Schedule an in-process auto-commit for a delayed pending action."""
    action = action if isinstance(action, dict) else {}
    if (action.get('m365_execution') or {}).get('kind') == 'workflow':
        return True
    action_id = _normalize_text(action.get('id'))
    user_id = _normalize_text(action.get('user_id'))
    auto_send_at = _coerce_datetime(action.get('auto_send_at_utc'))
    if not action_id or not user_id or not token or not auto_send_at:
        return False

    delay_seconds = max(0, (auto_send_at - _utc_now()).total_seconds())
    if delay_seconds > MSGRAPH_PENDING_TIMER_MAX_SECONDS:
        return False

    def commit_pending_action():
        try:
            committed_action, error = _commit_msgraph_pending_action_with_token(user_id, action_id, token)
            if error:
                log_event(
                    '[MS_GRAPH_PENDING_ACTIONS] Delayed action auto-send failed.',
                    extra={
                        'user_id': user_id,
                        'action_id': action_id,
                        'error': error.get('error'),
                        'message': error.get('message'),
                    },
                    level=logging.ERROR,
                )
            elif committed_action:
                log_event(
                    '[MS_GRAPH_PENDING_ACTIONS] Delayed action auto-send completed.',
                    extra={'user_id': user_id, 'action_id': action_id},
                )
        finally:
            with _scheduled_timer_lock:
                _scheduled_timers.pop(action_id, None)

    _cancel_scheduled_timer(action_id)
    timer = threading.Timer(delay_seconds, commit_pending_action)
    timer.daemon = True
    with _scheduled_timer_lock:
        _scheduled_timers[action_id] = timer
    timer.start()
    debug_print(f'[MS_GRAPH_PENDING_ACTIONS] Scheduled delayed action {action_id} in {delay_seconds:.1f}s')
    return True


def build_pending_action_response(action, *, viewer_user_id=None, include_full_review=False):
    """Build a standard API response wrapper for a pending action."""
    return {
        'success': True,
        'pending_action': sanitize_msgraph_pending_action_for_client(
            action, viewer_user_id=viewer_user_id, include_full_review=include_full_review,
        ),
    }