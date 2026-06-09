# functions_msgraph_pending_actions.py

"""User-owned pending Microsoft Graph action helpers."""

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from azure.cosmos import exceptions

from config import cosmos_msgraph_pending_actions_container
from functions_appinsights import log_event
from functions_authentication import get_valid_access_token_for_plugins
from functions_debug import debug_print
from functions_msgraph_operations import MSGRAPH_DEFAULT_ENDPOINT


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
}

MSGRAPH_PENDING_OPERATION_SEND_MAIL = 'send_mail'
MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE = 'create_calendar_invite'

MSGRAPH_PENDING_ACTION_MANUAL = 'manual'
MSGRAPH_PENDING_ACTION_DELAYED = 'delayed'

MSGRAPH_PENDING_RESOURCE_MAIL = 'mail'
MSGRAPH_PENDING_RESOURCE_CALENDAR = 'calendar'

MSGRAPH_PENDING_TIMER_MAX_SECONDS = 600
MSGRAPH_PENDING_REQUEST_TIMEOUT_SECONDS = 30

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
    return {key: value for key, value in document.items() if not str(key).startswith('_')}


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
    }


def sanitize_msgraph_pending_action_for_client(action):
    """Return a browser-safe pending action payload without stored Graph request bodies."""
    action = action if isinstance(action, dict) else {}
    status = _normalize_text(action.get('status')) or MSGRAPH_PENDING_STATUS_PENDING
    action_mode = _normalize_text(action.get('action_mode')) or MSGRAPH_PENDING_ACTION_MANUAL
    graph_resource_type = _normalize_text(action.get('graph_resource_type'))
    terminal = status in MSGRAPH_PENDING_TERMINAL_STATUSES
    due_at = _normalize_text(action.get('auto_send_at_utc'))

    return {
        'id': action.get('id'),
        'type': MSGRAPH_PENDING_ACTION_TYPE,
        'operation': action.get('operation'),
        'graph_resource_type': graph_resource_type,
        'status': status,
        'action_mode': action_mode,
        'subject': (action.get('summary') or {}).get('subject') or '',
        'summary': action.get('summary') if isinstance(action.get('summary'), dict) else {},
        'conversation_id': action.get('conversation_id') or '',
        'workflow_id': action.get('workflow_id') or '',
        'run_id': action.get('run_id') or '',
        'message_id': action.get('graph_message_id') or '',
        'event_id': action.get('graph_event_id') or '',
        'web_link': action.get('web_link') or '',
        'created_at': action.get('created_at') or '',
        'updated_at': action.get('updated_at') or '',
        'auto_send_at_utc': due_at,
        'completed_at': action.get('completed_at') or '',
        'cancelled_at': action.get('cancelled_at') or '',
        'failed_at': action.get('failed_at') or '',
        'delay_seconds': action.get('delay_seconds'),
        'error': action.get('error') or '',
        'can_approve': not terminal and action_mode == MSGRAPH_PENDING_ACTION_MANUAL,
        'can_cancel': not terminal,
        'can_send_now': not terminal,
        'will_auto_send': not terminal and action_mode == MSGRAPH_PENDING_ACTION_DELAYED and bool(due_at),
    }


def save_msgraph_pending_action(user_id, action):
    """Create or update a pending Microsoft Graph action for a user."""
    normalized_user_id = _normalize_text(user_id)
    if not normalized_user_id:
        raise ValueError('user_id is required to save a pending Microsoft Graph action.')

    action_record = action if isinstance(action, dict) else {}
    action_record['user_id'] = normalized_user_id
    action_record['type'] = MSGRAPH_PENDING_ACTION_TYPE
    action_record.setdefault('id', str(uuid.uuid4()))
    action_record['updated_at'] = _utc_now_iso()
    result = cosmos_msgraph_pending_actions_container.upsert_item(body=action_record)
    return _strip_cosmos_metadata(result)


def create_msgraph_pending_action(
    user_id,
    *,
    operation,
    graph_resource_type,
    action_mode,
    status=None,
    graph_message_id='',
    graph_event_id='',
    graph_payload=None,
    summary=None,
    conversation_id='',
    workflow_id='',
    run_id='',
    auto_send_at_utc='',
    delay_seconds=None,
    graph_endpoint=MSGRAPH_DEFAULT_ENDPOINT,
    web_link='',
):
    """Create a pending Microsoft Graph action record."""
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
        'graph_payload': graph_payload if isinstance(graph_payload, dict) else {},
        'summary': summary if isinstance(summary, dict) else {},
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
    return save_msgraph_pending_action(user_id, action_record)


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
    except Exception as exc:
        log_event(
            f'[MSGraphPendingActions] Error fetching action {normalized_action_id}: {exc}',
            extra={'user_id': normalized_user_id, 'action_id': normalized_action_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return None


def list_msgraph_pending_actions(user_id, conversation_id='', workflow_id='', run_id='', limit=100):
    """List pending Microsoft Graph actions for a user and optional activity context."""
    normalized_user_id = _normalize_text(user_id)
    if not normalized_user_id:
        return []

    query = 'SELECT * FROM c WHERE c.user_id = @user_id AND c.type = @type'
    parameters = [
        {'name': '@user_id', 'value': normalized_user_id},
        {'name': '@type', 'value': MSGRAPH_PENDING_ACTION_TYPE},
    ]

    normalized_conversation_id = _normalize_text(conversation_id)
    normalized_workflow_id = _normalize_text(workflow_id)
    normalized_run_id = _normalize_text(run_id)
    if normalized_conversation_id:
        query += ' AND c.conversation_id = @conversation_id'
        parameters.append({'name': '@conversation_id', 'value': normalized_conversation_id})
    if normalized_workflow_id:
        query += ' AND c.workflow_id = @workflow_id'
        parameters.append({'name': '@workflow_id', 'value': normalized_workflow_id})
    if normalized_run_id:
        query += ' AND c.run_id = @run_id'
        parameters.append({'name': '@run_id', 'value': normalized_run_id})

    query += ' ORDER BY c.created_at ASC'

    try:
        items = list(cosmos_msgraph_pending_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=normalized_user_id,
        ))
        return [_strip_cosmos_metadata(item) for item in items[:limit]]
    except Exception as exc:
        log_event(
            f'[MSGraphPendingActions] Error listing pending actions: {exc}',
            extra={
                'user_id': normalized_user_id,
                'conversation_id': normalized_conversation_id,
                'workflow_id': normalized_workflow_id,
                'run_id': normalized_run_id,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return []


def _build_graph_url(action, path):
    endpoint = _normalize_text((action or {}).get('graph_endpoint')) or MSGRAPH_DEFAULT_ENDPOINT
    endpoint = endpoint.rstrip('/')
    if endpoint.endswith('/v1.0'):
        endpoint = endpoint[:-5]
    return f'{endpoint}{path}'


def _perform_graph_request_with_token(action, token, method, path, json_body=None, expect_json_response=False):
    url = _build_graph_url(action, path)
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
    }
    try:
        response = requests.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            timeout=MSGRAPH_PENDING_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return {
            'success': False,
            'error': 'graph_request_failed',
            'message': 'Microsoft Graph request could not be completed.',
            'details': str(exc),
        }

    if response.status_code >= 400:
        message = response.text.strip() or 'Microsoft Graph request failed.'
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            graph_error = payload.get('error') if isinstance(payload.get('error'), dict) else {}
            message = graph_error.get('message') or message
        return {
            'success': False,
            'error': 'graph_request_failed',
            'message': message,
            'status_code': response.status_code,
        }

    result = {
        'success': True,
        'status_code': response.status_code,
    }
    if expect_json_response:
        try:
            result['value'] = response.json()
        except ValueError:
            result['value'] = None
    return result


def _get_graph_token(scopes):
    token_result = get_valid_access_token_for_plugins(scopes=scopes)
    if isinstance(token_result, dict) and token_result.get('access_token'):
        return token_result.get('access_token'), None
    return None, token_result if isinstance(token_result, dict) else {
        'error': 'token_acquisition_failed',
        'message': 'Failed to acquire Microsoft Graph access token.',
    }


def _mark_action_failed(user_id, action, message, error='graph_request_failed'):
    updated_action = dict(action or {})
    updated_action.update({
        'status': MSGRAPH_PENDING_STATUS_FAILED,
        'error': _normalize_text(message) or 'Microsoft Graph action failed.',
        'error_code': _normalize_text(error),
        'failed_at': _utc_now_iso(),
    })
    return save_msgraph_pending_action(user_id, updated_action)


def _commit_msgraph_pending_action_with_token(user_id, action_id, token):
    action = get_msgraph_pending_action(user_id, action_id)
    if not action:
        return None, {'error': 'not_found', 'message': 'Pending Microsoft Graph action was not found.'}

    status = _normalize_text(action.get('status'))
    if status in MSGRAPH_PENDING_TERMINAL_STATUSES:
        return action, None

    operation = _normalize_text(action.get('operation'))
    if operation == MSGRAPH_PENDING_OPERATION_SEND_MAIL:
        message_id = _normalize_text(action.get('graph_message_id'))
        if not message_id:
            updated_action = _mark_action_failed(user_id, action, 'Pending mail action is missing its draft message id.', error='missing_message_id')
            return updated_action, {'error': 'missing_message_id', 'message': updated_action.get('error')}
        graph_result = _perform_graph_request_with_token(
            action,
            token,
            'POST',
            f'/v1.0/me/messages/{quote(message_id, safe="")}/send',
            expect_json_response=False,
        )
        if not graph_result.get('success'):
            updated_action = _mark_action_failed(user_id, action, graph_result.get('message'), error=graph_result.get('error'))
            return updated_action, graph_result

        updated_action = dict(action)
        updated_action.update({
            'status': MSGRAPH_PENDING_STATUS_SENT,
            'completed_at': _utc_now_iso(),
            'send_status_code': graph_result.get('status_code'),
            'error': '',
        })
        return save_msgraph_pending_action(user_id, updated_action), None

    if operation == MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE:
        graph_payload = action.get('graph_payload') if isinstance(action.get('graph_payload'), dict) else {}
        if not graph_payload:
            updated_action = _mark_action_failed(user_id, action, 'Pending calendar invite is missing its event payload.', error='missing_event_payload')
            return updated_action, {'error': 'missing_event_payload', 'message': updated_action.get('error')}
        graph_result = _perform_graph_request_with_token(
            action,
            token,
            'POST',
            '/v1.0/me/events',
            json_body=graph_payload,
            expect_json_response=True,
        )
        if not graph_result.get('success'):
            updated_action = _mark_action_failed(user_id, action, graph_result.get('message'), error=graph_result.get('error'))
            return updated_action, graph_result

        event_result = graph_result.get('value') if isinstance(graph_result.get('value'), dict) else {}
        updated_action = dict(action)
        updated_action.update({
            'status': MSGRAPH_PENDING_STATUS_SENT,
            'completed_at': _utc_now_iso(),
            'graph_event_id': event_result.get('id') or '',
            'web_link': event_result.get('webLink') or updated_action.get('web_link') or '',
            'send_status_code': graph_result.get('status_code'),
            'error': '',
        })
        return save_msgraph_pending_action(user_id, updated_action), None

    updated_action = _mark_action_failed(user_id, action, f'Unsupported pending action operation: {operation}', error='unsupported_operation')
    return updated_action, {'error': 'unsupported_operation', 'message': updated_action.get('error')}


def approve_msgraph_pending_action(user_id, action_id):
    """Approve or send a pending Microsoft Graph action using the signed-in user token."""
    action = get_msgraph_pending_action(user_id, action_id)
    if not action:
        return None, {'error': 'not_found', 'message': 'Pending Microsoft Graph action was not found.'}

    operation = _normalize_text(action.get('operation'))
    scopes = ['Mail.Send'] if operation == MSGRAPH_PENDING_OPERATION_SEND_MAIL else ['Calendars.ReadWrite']
    token, token_error = _get_graph_token(scopes)
    if token_error:
        return action, token_error

    return _commit_msgraph_pending_action_with_token(user_id, action_id, token)


def cancel_msgraph_pending_action(user_id, action_id):
    """Cancel a pending Microsoft Graph action owned by the signed-in user."""
    action = get_msgraph_pending_action(user_id, action_id)
    if not action:
        return None, {'error': 'not_found', 'message': 'Pending Microsoft Graph action was not found.'}

    status = _normalize_text(action.get('status'))
    if status in MSGRAPH_PENDING_TERMINAL_STATUSES:
        return action, None

    operation = _normalize_text(action.get('operation'))
    if operation == MSGRAPH_PENDING_OPERATION_SEND_MAIL and _normalize_text(action.get('graph_message_id')):
        token, token_error = _get_graph_token(['Mail.ReadWrite'])
        if token_error:
            return action, token_error

        graph_result = _perform_graph_request_with_token(
            action,
            token,
            'DELETE',
            f'/v1.0/me/messages/{quote(_normalize_text(action.get("graph_message_id")), safe="")}',
            expect_json_response=False,
        )
        if not graph_result.get('success'):
            return action, graph_result

    updated_action = dict(action)
    updated_action.update({
        'status': MSGRAPH_PENDING_STATUS_CANCELLED,
        'cancelled_at': _utc_now_iso(),
        'error': '',
    })
    _cancel_scheduled_timer(action_id)
    return save_msgraph_pending_action(user_id, updated_action), None


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
                    '[MSGraphPendingActions] Delayed action auto-send failed.',
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
                    '[MSGraphPendingActions] Delayed action auto-send completed.',
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
    debug_print(f'[MSGraphPendingActions] Scheduled delayed action {action_id} in {delay_seconds:.1f}s')
    return True


def build_pending_action_response(action):
    """Build a standard API response wrapper for a pending action."""
    return {
        'success': True,
        'pending_action': sanitize_msgraph_pending_action_for_client(action),
    }