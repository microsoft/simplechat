# functions_public_membership_audit.py
"""The audit trail of a public workspace membership change.

One activity record is written for each add, role change and member removal,
mirroring the group's ``add_member_directly``, ``update_member_role`` and
``group_member_deleted`` records with public-workspace fields. Approve, reject and
transfer write no activity record, exactly as the group writes none (a recorded
follow-up). Each helper swallows its own failure, so a failed audit write never fails
a membership change that has already committed, and logs the failure with the action
only -- never the member's details. No notification is sent from here: the two
membership-change notifications the classic routes send stay in
``functions_public_membership`` and no new one is added (decision from M10A §5).
"""

import logging
import uuid
from datetime import datetime, timezone

from config import cosmos_activity_logs_container
from functions_appinsights import log_event


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _workspace_name(workspace_doc, workspace_id):
    name = workspace_doc.get("name") if isinstance(workspace_doc, dict) else None
    return name or workspace_id


def _record_failed(action):
    log_event(
        "[WORKSPACE_ROUTE] Public membership audit record could not be written.",
        extra={"action": action},
        level=logging.WARNING,
    )


def log_public_member_added(
    *,
    workspace_id,
    workspace_doc,
    added_by_user_id,
    added_by_email,
    added_by_role,
    member_id,
    member_name,
    member_email,
    member_role,
):
    """Write the ``public_add_member_directly`` activity record."""
    name = _workspace_name(workspace_doc, workspace_id)
    try:
        cosmos_activity_logs_container.create_item(body={
            "id": str(uuid.uuid4()),
            "activity_type": "public_add_member_directly",
            "timestamp": _now(),
            "added_by_user_id": added_by_user_id,
            "added_by_email": added_by_email,
            "added_by_role": added_by_role,
            "public_workspace_id": workspace_id,
            "public_workspace_name": name,
            "member_user_id": member_id,
            "member_email": member_email,
            "member_name": member_name,
            "member_role": member_role,
            "description": (
                f"{added_by_role} {added_by_email} added member {member_name} "
                f"({member_email}) to public workspace {name} as {member_role}"
            ),
        })
    except Exception:  # noqa: BLE001 - a failed audit write must not fail a committed change
        _record_failed("add_member")


def log_public_member_role_change(
    *,
    workspace_id,
    workspace_doc,
    changed_by_user_id,
    changed_by_email,
    changed_by_role,
    member_id,
    member_name,
    member_email,
    old_role,
    new_role,
):
    """Write the ``public_update_member_role`` activity record."""
    name = _workspace_name(workspace_doc, workspace_id)
    try:
        cosmos_activity_logs_container.create_item(body={
            "id": str(uuid.uuid4()),
            "type": "public_workspace_member_role_changed",
            "activity_type": "public_update_member_role",
            "timestamp": _now(),
            "changed_by_user_id": changed_by_user_id,
            "changed_by_email": changed_by_email,
            "changed_by_role": changed_by_role,
            "public_workspace_id": workspace_id,
            "public_workspace_name": name,
            "member_user_id": member_id,
            "member_email": member_email,
            "member_name": member_name,
            "old_role": old_role,
            "new_role": new_role,
            "description": (
                f"{changed_by_role} {changed_by_email} changed {member_name} "
                f"({member_email}) role from {old_role} to {new_role} in public workspace {name}"
            ),
        })
    except Exception:  # noqa: BLE001 - a failed audit write must not fail a committed change
        _record_failed("change_role")


def log_public_member_removed(
    *,
    workspace_id,
    workspace_doc,
    removed_by_user_id,
    removed_by_email,
    removed_by_role,
    member_id,
    member_name,
    member_email,
):
    """Write the ``public_member_removed`` activity record. There is no "leave"."""
    name = _workspace_name(workspace_doc, workspace_id)
    try:
        cosmos_activity_logs_container.create_item(body={
            "id": str(uuid.uuid4()),
            "user_id": removed_by_user_id,
            "activity_type": "public_member_removed",
            "timestamp": _now(),
            "removed_by": {
                "user_id": removed_by_user_id,
                "email": removed_by_email,
                "role": removed_by_role,
            },
            "removed_member": {
                "user_id": member_id,
                "email": member_email,
                "name": member_name,
            },
            "public_workspace": {
                "public_workspace_id": workspace_id,
                "public_workspace_name": name,
            },
            "description": (
                f"{removed_by_role} {removed_by_email} removed member {member_name} "
                f"({member_email}) from public workspace {name}"
            ),
        })
    except Exception:  # noqa: BLE001 - a failed audit write must not fail a committed change
        _record_failed("remove_member")


__all__ = [
    "log_public_member_added",
    "log_public_member_role_change",
    "log_public_member_removed",
]
