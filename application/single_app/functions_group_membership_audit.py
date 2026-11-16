# functions_group_membership_audit.py
"""The audit trail of a group role change, shared by the classic and native routes.

A role change writes one activity record (``group_member_role_changed``) and tells
the member in a notification. Both used to be written inline by the classic
``update_member_role`` route. They live here so the native role route produces
exactly the same record and notification. Each helper swallows its own failure, as
the route did, so a failed audit write never fails a role change that has already
committed.
"""

import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from config import cosmos_activity_logs_container
from functions_debug import debug_print
from functions_notifications import create_notification


def log_group_member_role_change(
    *,
    group_id,
    group_doc,
    changed_by_user_id,
    changed_by_email,
    changed_by_role,
    member_id,
    member_email,
    member_name,
    old_role,
    new_role,
):
    """Write the ``group_member_role_changed`` activity record."""
    try:
        activity_record = {
            'id': str(uuid.uuid4()),
            'type': 'group_member_role_changed',
            'activity_type': 'update_member_role',
            'timestamp': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            'changed_by_user_id': changed_by_user_id,
            'changed_by_email': changed_by_email,
            'changed_by_role': changed_by_role,
            'group_id': group_id,
            'group_name': group_doc.get('name', 'Unknown'),
            'member_user_id': member_id,
            'member_email': member_email,
            'member_name': member_name,
            'old_role': old_role,
            'new_role': new_role,
            'description': (
                f"{changed_by_role} {changed_by_email} changed {member_name} ({member_email}) "
                f"role from {old_role} to {new_role} in group {group_doc.get('name', group_id)}"
            ),
        }
        cosmos_activity_logs_container.create_item(body=activity_record)
    except Exception as log_error:
        debug_print(f"Failed to log role change activity: {log_error}")


def notify_group_member_role_change(*, group_id, group_doc, member_id, changed_by_email, old_role, new_role):
    """Tell the member whose role changed."""
    try:
        create_notification(
            user_id=member_id,
            notification_type='system_announcement',
            title='Role Changed',
            message=(
                f"Your role in group '{group_doc.get('name', 'Unknown')}' has been changed "
                f"from {old_role} to {new_role} by {changed_by_email}."
            ),
            link_url=f"/groups/{quote(group_id, safe='')}",
            metadata={
                'group_id': group_id,
                'group_name': group_doc.get('name', 'Unknown'),
                'changed_by': changed_by_email,
                'old_role': old_role,
                'new_role': new_role,
            },
        )
    except Exception as notif_error:
        debug_print(f"Failed to create role change notification: {notif_error}")
