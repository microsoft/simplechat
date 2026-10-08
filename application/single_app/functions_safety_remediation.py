# functions_safety_remediation.py

"""Helpers for safety violation remediation actions and notifications."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from config import cosmos_safety_container
from functions_access_restriction import (
    ACCESS_RESTRICTION_KIND_BLOCKED,
    ACCESS_RESTRICTION_KIND_SUSPENDED,
    ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
    build_access_restriction_notice,
)
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_notifications import create_notification, mark_notification_read
from functions_settings import get_user_settings, update_user_settings


SAFETY_REMEDIATION_WARNING = 'WarnUser'
SAFETY_REMEDIATION_SUSPEND = 'SuspendUser'
SAFETY_REMEDIATION_BLOCK = 'BlockUser'

# Warnings the signed-in user still has to acknowledge, read at most this many at a time.
SAFETY_WARNING_PENDING_LIMIT = 20
SAFETY_WARNING_WRITE_ATTEMPTS = 3
SAFETY_WARNING_FALLBACK_MESSAGE = (
    'An administrator reviewed content you submitted and sent you this warning. '
    'Please review the acceptable use requirements before continuing.'
)

WARNING_ACKNOWLEDGMENT_PENDING = 'pending'
WARNING_ACKNOWLEDGMENT_ACKNOWLEDGED = 'acknowledged'
WARNING_ACKNOWLEDGMENT_NOT_TRACKED = 'not_tracked'


def get_safety_log_item(log_id: str) -> Dict[str, Any]:
    """Return a safety log item by its document id."""
    return cosmos_safety_container.read_item(item=log_id, partition_key=log_id)


def update_safety_log_action_state(log_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Persist remediation state changes onto a safety log item."""
    item = get_safety_log_item(log_id)
    item.update(updates or {})
    item['last_updated'] = datetime.utcnow().isoformat()
    cosmos_safety_container.upsert_item(item)
    return item


def resolve_safety_target_user(user_id: str) -> Dict[str, str]:
    """Resolve target user display information from the server-side user settings store."""
    user_doc = get_user_settings(user_id, allow_cross_user=True) or {}
    email = str(user_doc.get('email') or '').strip()
    display_name = str(user_doc.get('display_name') or '').strip()

    return {
        'user_id': user_id,
        'email': email,
        'display_name': display_name or email or user_id,
    }


def _format_triggered_categories_for_notification(safety_log: Dict[str, Any]) -> str:
    categories = safety_log.get('triggered_categories') or []
    formatted_categories = []
    for category in categories:
        category_name = str(category.get('category') or '').strip()
        severity = category.get('severity')
        if category_name and severity is not None:
            formatted_categories.append(f"{category_name}(s={severity})")
        elif category_name:
            formatted_categories.append(category_name)

    return ', '.join(formatted_categories)


def _default_notification_title(action: str) -> str:
    if action == SAFETY_REMEDIATION_WARNING:
        return 'Safety Violation Warning'
    if action == SAFETY_REMEDIATION_SUSPEND:
        return 'Account Suspension Notice'
    if action == SAFETY_REMEDIATION_BLOCK:
        return 'Account Access Blocked'
    return 'Safety Violation Notice'


def _default_notification_message(
    action: str,
    safety_log: Dict[str, Any],
    datetime_to_allow: Optional[str],
) -> str:
    details = [
        'A safety review has been completed for recent activity in your workspace.',
        f"Violation ID: {safety_log.get('id') or 'Unknown'}",
    ]

    categories = _format_triggered_categories_for_notification(safety_log)
    if categories:
        details.append(f"Triggered categories: {categories}")

    if action == SAFETY_REMEDIATION_WARNING:
        details.append('Action taken: Warning issued. Please review our acceptable use requirements before continuing.')
    elif action == SAFETY_REMEDIATION_SUSPEND:
        details.append('Action taken: Your access has been temporarily suspended pending the date below.')
        if datetime_to_allow:
            details.append(f"Access restores automatically after: {datetime_to_allow}")
    elif action == SAFETY_REMEDIATION_BLOCK:
        details.append('Action taken: Your access has been blocked with no automatic restore date.')

    admin_notes = str(safety_log.get('notes') or '').strip()
    if admin_notes:
        details.append(f"Admin notes: {admin_notes}")

    return '\n'.join(details)


def execute_safety_violation_action(
    action: str,
    safety_log: Dict[str, Any],
    notification_title: str,
    notification_message: str,
    datetime_to_allow: Optional[str],
    actor: Dict[str, str],
) -> Dict[str, Any]:
    """Execute a warning or access restriction for a safety violation."""
    if safety_log.get("content_origin", "user") != "user":
        raise ValueError("AI-generated findings cannot be used to warn or restrict a user.")
    target_user_id = str(safety_log.get('user_id') or '').strip()
    if not target_user_id:
        raise ValueError('Safety violation is missing a target user id')

    target_user = resolve_safety_target_user(target_user_id)
    normalized_title = str(notification_title or '').strip() or _default_notification_title(action)
    normalized_message = str(notification_message or '').strip() or _default_notification_message(
        action,
        safety_log,
        datetime_to_allow,
    )

    if action == SAFETY_REMEDIATION_SUSPEND:
        if not datetime_to_allow:
            raise ValueError('Suspend user actions require a restore date and time')

        access_updated = update_user_settings(
            target_user_id,
            {
                'access': {
                    'status': 'deny',
                    'datetime_to_allow': datetime_to_allow,
                    # What the user was told, so the Access restricted screen can show it.
                    'notice': build_access_restriction_notice(
                        ACCESS_RESTRICTION_KIND_SUSPENDED,
                        normalized_title,
                        normalized_message,
                        until=datetime_to_allow,
                        reference_id=safety_log.get('id'),
                        source=ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
                    ),
                }
            },
            allow_cross_user=True,
        )
        if not access_updated:
            raise RuntimeError('Failed to apply the temporary access restriction')
        notification_type = 'safety_violation_suspension'
        result_message = f"User access suspended until {datetime_to_allow}."
    elif action == SAFETY_REMEDIATION_BLOCK:
        access_updated = update_user_settings(
            target_user_id,
            {
                'access': {
                    'status': 'deny',
                    'datetime_to_allow': None,
                    'notice': build_access_restriction_notice(
                        ACCESS_RESTRICTION_KIND_BLOCKED,
                        normalized_title,
                        normalized_message,
                        reference_id=safety_log.get('id'),
                        source=ACCESS_RESTRICTION_SOURCE_SAFETY_VIOLATION,
                    ),
                }
            },
            allow_cross_user=True,
        )
        if not access_updated:
            raise RuntimeError('Failed to apply the permanent access block')
        notification_type = 'safety_violation_block'
        result_message = 'User access blocked indefinitely.'
    elif action == SAFETY_REMEDIATION_WARNING:
        notification_type = 'safety_violation_warning'
        result_message = 'Warning notification sent to the user.'
    else:
        raise ValueError(f'Unsupported safety remediation action: {action}')

    notification = create_notification(
        user_id=target_user_id,
        notification_type=notification_type,
        title=normalized_title,
        message=normalized_message,
        link_url='/profile?tab=violations',
        link_context={
            'tab': 'violations',
            'violation_id': safety_log.get('id'),
        },
        metadata={
            'safety_log_id': safety_log.get('id'),
            'violation_action': action,
            'target_user_id': target_user_id,
            'actor_id': actor.get('id'),
            'actor_email': actor.get('email'),
            'datetime_to_allow': datetime_to_allow,
        },
    )

    if notification is None:
        raise RuntimeError('Failed to create the user notification')

    log_event(
        '[SAFETY_REMEDIATION] Executed safety remediation action',
        {
            'safety_log_id': safety_log.get('id'),
            'violation_action': action,
            'target_user_id': target_user_id,
            'target_user_email': target_user.get('email'),
            'datetime_to_allow': datetime_to_allow,
            'actor_id': actor.get('id'),
            'actor_email': actor.get('email'),
        },
    )
    debug_print(
        f"[SAFETY_REMEDIATION] Executed {action} for {target_user_id} on safety log {safety_log.get('id')}"
    )

    return {
        'success': True,
        'message': result_message,
        'notification_id': notification.get('id'),
        'notification_title': normalized_title,
        'notification_message': normalized_message,
        'target_user': target_user,
    }


def build_safety_action_execution_updates(
    action: str,
    execution_result: Dict[str, Any],
    executed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the safety log fields that record an executed remediation action.

    An executed warning is also marked as needing the user's acknowledgment, with the title
    and message the user was sent, so it can be shown to them until they acknowledge it.
    Warnings executed before this was recorded carry none of these fields and are never
    shown again.
    """
    executed_at = executed_at or datetime.now(timezone.utc).isoformat()
    updates = {
        'action_request_status': 'executed',
        'action_executed_at': executed_at,
        'action_execution_error': None,
    }
    if action == SAFETY_REMEDIATION_WARNING:
        result = execution_result or {}
        updates.update({
            'warning_requires_acknowledgment': True,
            'warning_notification_id': result.get('notification_id'),
            'warning_title': result.get('notification_title'),
            'warning_message': result.get('notification_message'),
            'warning_issued_at': executed_at,
            'warning_acknowledged_at': None,
        })
    return updates


def serialize_safety_warning_state(log_item: Dict[str, Any]) -> Dict[str, Any]:
    """Return a record's warning acknowledgment state for reviewers and the warned user.

    ``warning_acknowledgment_status`` is None unless the record holds an executed warning;
    then it is ``pending``, ``acknowledged`` or ``not_tracked`` for a warning sent before
    acknowledgment was recorded.
    """
    executed_warning = (
        log_item.get('action') == SAFETY_REMEDIATION_WARNING
        and str(log_item.get('action_request_status') or '').strip().lower() == 'executed'
    )
    requires_acknowledgment = log_item.get('warning_requires_acknowledgment') is True
    status = None
    if executed_warning:
        if not requires_acknowledgment:
            status = WARNING_ACKNOWLEDGMENT_NOT_TRACKED
        elif log_item.get('warning_acknowledged_at'):
            status = WARNING_ACKNOWLEDGMENT_ACKNOWLEDGED
        else:
            status = WARNING_ACKNOWLEDGMENT_PENDING
    return {
        'warning_requires_acknowledgment': requires_acknowledgment,
        'warning_issued_at': log_item.get('warning_issued_at'),
        'warning_acknowledged_at': log_item.get('warning_acknowledged_at'),
        'warning_acknowledgment_status': status,
    }


def _user_safe_categories(log_item: Dict[str, Any]) -> List[Dict[str, Any]]:
    categories = []
    for entry in log_item.get('triggered_categories') or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get('category') or '').strip()
        if not name:
            continue
        severity = entry.get('severity')
        if isinstance(severity, bool) or not isinstance(severity, (int, float)):
            severity = None
        categories.append({'category': name, 'severity': severity})
    return categories


def serialize_safety_warning_for_user(log_item: Dict[str, Any]) -> Dict[str, Any]:
    """Return only what the warned user may see of a warning: what they were sent, and when."""
    return {
        'id': log_item.get('id'),
        'violation_id': log_item.get('id'),
        'title': str(log_item.get('warning_title') or '').strip()
        or _default_notification_title(SAFETY_REMEDIATION_WARNING),
        'message': str(log_item.get('warning_message') or '').strip() or SAFETY_WARNING_FALLBACK_MESSAGE,
        'issued_at': log_item.get('warning_issued_at') or log_item.get('action_executed_at'),
        'acknowledged_at': log_item.get('warning_acknowledged_at'),
        'triggered_categories': _user_safe_categories(log_item),
    }


def _is_acknowledgeable_warning(log_item: Dict[str, Any], user_id: str) -> bool:
    """True for the caller's own executed warning that asks for acknowledgment."""
    return (
        bool(user_id)
        and log_item.get('user_id') == user_id
        and log_item.get('content_origin', 'user') == 'user'
        and log_item.get('action') == SAFETY_REMEDIATION_WARNING
        and str(log_item.get('action_request_status') or '').strip().lower() == 'executed'
        and log_item.get('warning_requires_acknowledgment') is True
    )


_PENDING_WARNING_CONDITIONS = (
    "c.user_id = @user_id "
    "AND c.action = @action "
    "AND c.action_request_status = 'executed' "
    "AND c.warning_requires_acknowledgment = true "
    "AND (NOT IS_DEFINED(c.warning_acknowledged_at) OR IS_NULL(c.warning_acknowledged_at)) "
    "AND (NOT IS_DEFINED(c.content_origin) OR c.content_origin = 'user')"
)


def _pending_warning_parameters(user_id: str) -> List[Dict[str, Any]]:
    return [
        {'name': '@user_id', 'value': user_id},
        {'name': '@action', 'value': SAFETY_REMEDIATION_WARNING},
    ]


def count_pending_safety_warnings(user_id: str) -> int:
    """Return how many warnings the user still has to acknowledge.

    V2 bootstrap carries this so the interface only asks for the warnings themselves when
    there are some, rather than on every page load.
    """
    if not user_id:
        return 0
    values = cosmos_safety_container.query_items(
        query=f"SELECT VALUE COUNT(1) FROM c WHERE {_PENDING_WARNING_CONDITIONS}",
        parameters=_pending_warning_parameters(user_id),
        enable_cross_partition_query=True,
    )
    return sum(int(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool))


def list_pending_safety_warnings(user_id: str) -> List[Dict[str, Any]]:
    """Return the caller's warnings that still need acknowledgment, oldest first."""
    if not user_id:
        return []
    query = (
        "SELECT c.id, c.user_id, c.content_origin, c.action, c.action_request_status, "
        "c.action_executed_at, c.warning_requires_acknowledgment, c.warning_acknowledged_at, "
        "c.warning_title, c.warning_message, c.warning_issued_at, c.triggered_categories "
        f"FROM c WHERE {_PENDING_WARNING_CONDITIONS}"
    )
    items = list(cosmos_safety_container.query_items(
        query=query,
        parameters=_pending_warning_parameters(user_id),
        enable_cross_partition_query=True,
    ))
    pending = [
        item for item in items
        if _is_acknowledgeable_warning(item, user_id) and not item.get('warning_acknowledged_at')
    ]
    pending.sort(key=lambda item: str(item.get('warning_issued_at') or item.get('action_executed_at') or ''))
    return [serialize_safety_warning_for_user(item) for item in pending[:SAFETY_WARNING_PENDING_LIMIT]]


def _mark_warning_notification_read(log_item: Dict[str, Any], user_id: str) -> None:
    """Mark the bell notification that delivered the warning as read for its recipient."""
    notification_id = str(log_item.get('warning_notification_id') or '').strip()
    if not notification_id:
        return
    if not mark_notification_read(notification_id, user_id):
        log_event(
            '[SAFETY_WARNINGS] The warning notification could not be marked read.',
            extra={'safety_log_id': log_item.get('id'), 'user_id': user_id},
            level=logging.WARNING,
        )


def acknowledge_safety_warning(log_id: str, user_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Record that the signed-in user acknowledged their own warning.

    Returns ``(status, warning)``. ``status`` is ``acknowledged``, ``already_acknowledged``
    or ``not_found``. A record that doesn't exist, belongs to someone else, or isn't a
    warning that asks for acknowledgment is ``not_found``, so the answer never confirms
    another user's record. The write is conditional on the stored ETag and retried, so a
    reviewer saving the record at the same moment is never overwritten.
    """
    normalized_id = str(log_id or '').strip()
    if not normalized_id or not user_id:
        return 'not_found', None

    for _attempt in range(SAFETY_WARNING_WRITE_ATTEMPTS):
        try:
            item = cosmos_safety_container.read_item(item=normalized_id, partition_key=normalized_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return 'not_found', None
        if not _is_acknowledgeable_warning(item, user_id):
            return 'not_found', None
        if item.get('warning_acknowledged_at'):
            _mark_warning_notification_read(item, user_id)
            return 'already_acknowledged', serialize_safety_warning_for_user(item)

        item['warning_acknowledged_at'] = datetime.now(timezone.utc).isoformat()
        etag = item.get('_etag')
        try:
            if etag:
                stored = cosmos_safety_container.replace_item(
                    item=normalized_id,
                    body=item,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            else:
                stored = cosmos_safety_container.upsert_item(item)
        except cosmos_exceptions.CosmosAccessConditionFailedError:
            continue

        stored = stored if isinstance(stored, dict) else item
        _mark_warning_notification_read(stored, user_id)
        log_event(
            '[SAFETY_WARNINGS] Safety warning acknowledged by its recipient.',
            extra={
                'safety_log_id': normalized_id,
                'user_id': user_id,
                'warning_issued_at': stored.get('warning_issued_at'),
            },
        )
        return 'acknowledged', serialize_safety_warning_for_user(stored)

    raise cosmos_exceptions.CosmosAccessConditionFailedError(
        status_code=412,
        message='The safety warning changed while it was being acknowledged.',
    )
