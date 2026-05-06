# functions_safety_remediation.py

"""Helpers for safety violation remediation actions and notifications."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from config import cosmos_safety_container
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_notifications import create_notification
from functions_settings import get_user_settings, update_user_settings


SAFETY_REMEDIATION_WARNING = 'WarnUser'
SAFETY_REMEDIATION_SUSPEND = 'SuspendUser'
SAFETY_REMEDIATION_BLOCK = 'BlockUser'


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
        '[SafetyRemediation] Executed safety remediation action',
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
        f"[SafetyRemediation] Executed {action} for {target_user_id} on safety log {safety_log.get('id')}"
    )

    return {
        'success': True,
        'message': result_message,
        'notification_id': notification.get('id'),
        'target_user': target_user,
    }
