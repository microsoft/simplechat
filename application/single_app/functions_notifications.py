# functions_notifications.py

"""
Notifications Management

This module handles all operations related to notifications stored in the
notifications container. Supports personal, group, and public workspace scoped
notifications with per-user read/dismiss tracking.

Version: 0.234.032
Implemented in: 0.234.032
"""

# Imports (grouped after docstring)
import copy
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from azure.core import MatchConditions
from azure.cosmos import exceptions
from flask import current_app
import logging
from config import cosmos_notifications_container
from functions_appinsights import log_event
from functions_group import assert_group_role, get_user_groups
from functions_group_workflow_policy import GROUP_WORKFLOW_MEMBER_ROLES
from functions_debug import debug_print
from functions_public_workspaces import find_public_workspace_by_id, get_user_public_workspaces
from functions_workflow_alert_safety import sanitize_workflow_alert_record
from functions_workflow_alerts import (
    WORKFLOW_ALERT_SIZE_ORDER,
    WORKFLOW_ALERT_SOUND_ORDER,
    normalize_alert_flag,
    resolve_alert_option,
)

# Constants
TTL_60_DAYS = 60 * 24 * 60 * 60  # 60 days in seconds (5184000)
ASSIGNMENT_NOTIFICATIONS_PARTITION_KEY = 'assignment-notifications'
WORKFLOW_ALERT_NOTIFICATION_TYPE = 'workflow_priority_alert'
KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE = 'key_vault_secret_expiring'
M365_APPROVAL_PENDING_NOTIFICATION_TYPE = 'm365_approval_pending'
M365_APPROVAL_UPDATED_NOTIFICATION_TYPE = 'm365_approval_updated'
# Pinned by a parity test to functions_workflow_chat_delivery.NOTIFICATION_TYPE, which this module
# does not import so its import graph stays unchanged.
WORKFLOW_CHAT_DELIVERY_NOTIFICATION_TYPE = 'workflow_chat_delivery'
MAX_NOTIFICATION_IDEMPOTENCY_KEY_LENGTH = 512
WORKFLOW_ALERT_PRIORITY_CONFIG = {
    'info': {
        'icon': 'bi-info-circle',
        'color': 'info',
    },
    'low': {
        'icon': 'bi-bell',
        'color': 'info',
    },
    'medium': {
        'icon': 'bi-exclamation-circle',
        'color': 'warning',
    },
    'high': {
        'icon': 'bi-exclamation-triangle',
        'color': 'danger',
    },
    'critical': {
        'icon': 'bi-exclamation-octagon',
        'color': 'danger',
    },
}
# A run that errored is presented differently from a run that found something,
# independently of how loud the owner made the severity.
WORKFLOW_ALERT_FAILURE_CATEGORY = 'failure'
WORKFLOW_ALERT_FAILURE_ICON = 'bi-x-octagon'
WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY = 'notify_only'
# Shared notifications are written by many readers, so read, dismiss and acknowledgment writes
# are conditional on the stored version and retried this many times on a conflict.
NOTIFICATION_WRITE_ATTEMPTS = 3
WORKFLOW_ALERT_ACKNOWLEDGER_NAME_MAX_LENGTH = 200
# What a group member other than the workflow's owner may read from a team alert. The rest of an
# alert describes the owner's side of the run: its summary and detail can quote conversations and
# actions in the owner's own space, and its links include the owner's workflow conversation and
# private conversations. Members get the alert's facts and links to what the run created in the
# group; the run's output stays in the group's workflow run history.
WORKFLOW_ALERT_MEMBER_METADATA_KEYS = (
    'workflow_id',
    'workflow_name',
    'workflow_scope',
    'workflow_group_id',
    'priority',
    'category',
    'delivery',
    'require_acknowledgment',
    'sound',
    'size',
    'audience',
    'alert_mode',
    'trigger_reason',
    'trigger_source',
    'run_id',
    'runner_type',
    'status',
)
WORKFLOW_ALERT_MEMBER_RULE_KEYS = ('rule_id', 'rule_name', 'severity', 'condition_type')

# Notification type registry for extensibility
NOTIFICATION_TYPES = {
    M365_APPROVAL_PENDING_NOTIFICATION_TYPE: {
        'icon': 'bi-person-lock',
        'color': 'warning'
    },
    M365_APPROVAL_UPDATED_NOTIFICATION_TYPE: {
        'icon': 'bi-check2-square',
        'color': 'info'
    },
    'document_processing_complete': {
        'icon': 'bi-file-earmark-check',
        'color': 'success'
    },
    'group_created': {
        'icon': 'bi-people-fill',
        'color': 'success'
    },
    'group_member_added': {
        'icon': 'bi-person-plus',
        'color': 'info'
    },
    'conversation_created': {
        'icon': 'bi-chat-square-text',
        'color': 'info'
    },
    'collaboration_message_received': {
        'icon': 'bi-people-fill',
        'color': 'info'
    },
    'chat_response_complete': {
        'icon': 'bi-chat-dots',
        'color': 'success'
    },
    'document_processing_failed': {
        'icon': 'bi-file-earmark-x',
        'color': 'danger'
    },
    'ownership_transfer_request': {
        'icon': 'bi-arrow-left-right',
        'color': 'warning'
    },
    'group_deletion_request': {
        'icon': 'bi-trash',
        'color': 'danger'
    },
    'document_deletion_request': {
        'icon': 'bi-trash',
        'color': 'warning'
    },
    'personal_document_share_pending': {
        'icon': 'bi-file-earmark-plus',
        'color': 'warning'
    },
    'personal_document_share_approved': {
        'icon': 'bi-file-earmark-check',
        'color': 'success'
    },
    'personal_document_share_denied': {
        'icon': 'bi-file-earmark-x',
        'color': 'danger'
    },
    'group_document_share_pending': {
        'icon': 'bi-folder-plus',
        'color': 'warning'
    },
    'group_document_share_approved': {
        'icon': 'bi-folder-check',
        'color': 'success'
    },
    'group_document_share_denied': {
        'icon': 'bi-folder-x',
        'color': 'danger'
    },
    'group_document_share_removed': {
        'icon': 'bi-folder-minus',
        'color': 'info'
    },
    'system_announcement': {
        'icon': 'bi-megaphone',
        'color': 'info'
    },
    'approval_request_pending': {
        'icon': 'bi-hourglass-split',
        'color': 'warning'
    },
    'approval_request_pending_submitter': {
        'icon': 'bi-hourglass',
        'color': 'info'
    },
    'approval_request_approved': {
        'icon': 'bi-check-circle',
        'color': 'success'
    },
    'approval_request_denied': {
        'icon': 'bi-x-circle',
        'color': 'danger'
    },
    'safety_violation_warning': {
        'icon': 'bi-shield-exclamation',
        'color': 'warning'
    },
    'safety_violation_suspension': {
        'icon': 'bi-slash-circle',
        'color': 'warning'
    },
    'safety_violation_block': {
        'icon': 'bi-shield-lock',
        'color': 'danger'
    },
    'agent_template_pending_admin': {
        'icon': 'bi-layers',
        'color': 'warning'
    },
    'agent_template_pending_submitter': {
        'icon': 'bi-layers-half',
        'color': 'info'
    },
    'agent_template_approved': {
        'icon': 'bi-check2-square',
        'color': 'success'
    },
    'agent_template_rejected': {
        'icon': 'bi-x-octagon',
        'color': 'danger'
    },
    'agent_template_deleted': {
        'icon': 'bi-trash',
        'color': 'secondary'
    },
    'mcp_tool_drift_detected': {
        'icon': 'bi-shield-exclamation',
        'color': 'warning'
    },
    'generated_file_approval_pending': {
        'icon': 'bi-file-earmark-lock',
        'color': 'warning'
    },
    'generated_file_approval_approved': {
        'icon': 'bi-file-earmark-check',
        'color': 'success'
    },
    'generated_file_approval_denied': {
        'icon': 'bi-file-earmark-x',
        'color': 'danger'
    },
    WORKFLOW_ALERT_NOTIFICATION_TYPE: {
        'icon': 'bi-bell',
        'color': 'secondary'
    },
    WORKFLOW_CHAT_DELIVERY_NOTIFICATION_TYPE: {
        'icon': 'bi-activity',
        'color': 'info'
    },
    KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE: {
        'icon': 'bi-safe',
        'color': 'warning'
    },
    'file_sync_run_failed': {
        'icon': 'bi-cloud-slash',
        'color': 'danger'
    },
    'azure_files_search_access_unverified': {
        'icon': 'bi-shield-exclamation',
        'color': 'warning'
    }
}


def _get_notification_partition_key(notification):
    """Resolve the Cosmos partition key for a notification document."""
    if notification.get('scope') == 'assignment':
        return ASSIGNMENT_NOTIFICATIONS_PARTITION_KEY

    return (
        notification.get('user_id')
        or notification.get('group_id')
        or notification.get('public_workspace_id')
    )


def _notification_retry_id(idempotency_key, notification):
    """Bind an opaque retry key to its scope, audience and notification type."""
    if (
        not isinstance(idempotency_key, str) or not idempotency_key.strip()
        or len(idempotency_key) > MAX_NOTIFICATION_IDEMPOTENCY_KEY_LENGTH
    ):
        raise ValueError("The notification retry key is invalid.")
    identity = {
        "version": 1,
        "key": idempotency_key,
        **{field: notification.get(field) for field in (
            "scope", "user_id", "group_id", "public_workspace_id", "notification_type", "assignment",
        )},
    }
    encoded = json.dumps(
        identity, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return f"notification-{hashlib.sha256(encoded).hexdigest()}"


def _log_notification_failure(code, error):
    """Optional delivery and telemetry failures must never change content state."""
    try:
        log_event(
            f"[CONTENT_SCREENING] {code}",
            extra={"error_type": type(error).__name__},
            level=logging.WARNING,
        )
    except Exception:
        return


def _read_existing_notification(notification):
    # config.py partitions this container on /user_id, including null for scope notices.
    existing = cosmos_notifications_container.read_item(
        item=notification["id"], partition_key=notification.get("user_id"),
    )
    if not isinstance(existing, dict) or any(
        existing.get(field) != notification.get(field) for field in (
            "id", "scope", "user_id", "group_id", "public_workspace_id", "notification_type", "assignment",
        )
    ):
        raise ValueError("The stored notification does not match the retry identity.")
    return existing


def _get_notification_display_message(notification):
    """Normalize display text and backfill reviewer reasons from metadata when needed."""
    message = str(notification.get('message') or '').strip()
    metadata = notification.get('metadata') or {}
    notification_type = notification.get('notification_type')

    reason = None
    if notification_type == 'approval_request_denied':
        reason = str(metadata.get('comment') or '').strip()
    elif notification_type == 'agent_template_rejected':
        reason = str(metadata.get('rejection_reason') or '').strip()

    if reason and reason not in message:
        if message:
            return f"{message} Reason provided: {reason}"
        return f"Reason provided: {reason}"

    return message


def _get_workflow_alert_priority(notification):
    metadata = notification.get('metadata') or {}
    priority = str(metadata.get('priority') or 'medium').strip().lower()
    if priority not in WORKFLOW_ALERT_PRIORITY_CONFIG:
        return 'medium'
    return priority


def _get_workflow_alert_category(notification):
    metadata = notification.get('metadata') or {}
    category = str(metadata.get('category') or 'alert').strip().lower()
    return category if category in {'alert', WORKFLOW_ALERT_FAILURE_CATEGORY} else 'alert'


def _get_workflow_alert_delivery(notification):
    """Return the delivery style, defaulting to popup so legacy alerts still interrupt."""
    metadata = notification.get('metadata') or {}
    delivery = str(metadata.get('delivery') or '').strip().lower()
    return delivery if delivery in {'notify_only', 'popup'} else 'popup'


def _get_workflow_alert_metadata(notification):
    metadata = notification.get('metadata')
    return metadata if isinstance(metadata, dict) else {}


def _workflow_alert_requires_acknowledgment(notification):
    return normalize_alert_flag(_get_workflow_alert_metadata(notification).get('require_acknowledgment', False))


def _is_workflow_alert_acknowledged(notification):
    return bool(str(notification.get('acknowledged_at') or '').strip())


def _is_team_workflow_alert(notification):
    return notification.get('scope') == 'group' and bool(str(notification.get('group_id') or '').strip())


def _reads_team_workflow_alert_as_member(notification, reader_user_id):
    """Return True when a team alert must be reduced for this reader.

    Only the workflow's owner reads a team alert in full. A team alert without a recorded owner
    is reduced for everyone, so a damaged record can't widen what members see.
    """
    if not _is_team_workflow_alert(notification):
        return False
    owner_user_id = str(_get_workflow_alert_metadata(notification).get('owner_user_id') or '').strip()
    return not owner_user_id or owner_user_id != reader_user_id


def _join_rule_names(names):
    if len(names) <= 1:
        return ''.join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _member_workflow_alert_links(notification, metadata):
    """Keep only links a member can follow: group conversations the run created in this group.

    The workflow's own conversation belongs to its owner, and a personal conversation the agent
    created is private, so neither is offered to the rest of the group.
    """
    group_id = str(notification.get('group_id') or '').strip()
    workflow_conversation_id = str(metadata.get('conversation_id') or '').strip()
    links = []
    for target in metadata.get('link_targets') or []:
        if not isinstance(target, dict):
            continue
        link_context = target.get('link_context') if isinstance(target.get('link_context'), dict) else {}
        chat_type = str(link_context.get('chat_type') or '').strip().lower()
        conversation_id = str(target.get('conversation_id') or link_context.get('conversation_id') or '').strip()
        if (
            chat_type.startswith('group')
            and str(link_context.get('group_id') or '').strip() == group_id
            and conversation_id
            and conversation_id != workflow_conversation_id
        ):
            links.append(copy.deepcopy(target))
    return links


def _project_workflow_alert_for_member(notification):
    """Return the reduced team alert a group member other than the owner reads."""
    metadata = _get_workflow_alert_metadata(notification)
    member_metadata = {
        key: copy.deepcopy(metadata[key])
        for key in WORKFLOW_ALERT_MEMBER_METADATA_KEYS
        if key in metadata
    }
    member_metadata['matched_rules'] = [
        {key: match[key] for key in WORKFLOW_ALERT_MEMBER_RULE_KEYS if key in match}
        for match in metadata.get('matched_rules') or []
        if isinstance(match, dict)
    ]
    links = _member_workflow_alert_links(notification, metadata)
    member_metadata['link_targets'] = links

    priority = _get_workflow_alert_priority(notification)
    workflow_name = str(metadata.get('workflow_name') or '').strip() or 'Workflow'
    rule_names = [
        str(match.get('rule_name') or '').strip()
        for match in member_metadata['matched_rules']
    ]
    rule_names = [name for name in rule_names if name]

    projected = dict(notification)
    projected['title'] = f'{priority.capitalize()} priority workflow alert: {workflow_name}'
    projected['message'] = (
        f'Matched {_join_rule_names(rule_names)}. Open it for details.'
        if rule_names
        else 'Open the workflow run for details.'
    )
    projected['metadata'] = member_metadata
    first_link = links[0] if links else {}
    projected['link_url'] = first_link.get('link_url') or ''
    projected['link_context'] = copy.deepcopy(first_link.get('link_context') or {})
    return projected


def _decorate_workflow_alert(notification, reader_user_id):
    """Return a workflow alert as this reader may see it, with its display fields added.

    A team alert is reduced for group members other than the workflow's owner, and every shared
    alert reports only the reader's own read and dismissed state, never other members' ids.
    """
    if _reads_team_workflow_alert_as_member(notification, reader_user_id):
        notification = _project_workflow_alert_for_member(notification)
        content_scope = 'member'
    else:
        notification = dict(notification)
        content_scope = 'full'

    metadata = _get_workflow_alert_metadata(notification)
    acknowledged_by = notification.get('acknowledged_by') if isinstance(notification.get('acknowledged_by'), dict) else {}
    acknowledged = _is_workflow_alert_acknowledged(notification)

    notification['priority'] = _get_workflow_alert_priority(notification)
    notification['category'] = _get_workflow_alert_category(notification)
    notification['delivery'] = _get_workflow_alert_delivery(notification)
    notification['require_acknowledgment'] = normalize_alert_flag(metadata.get('require_acknowledgment', False))
    notification['sound'] = resolve_alert_option(metadata.get('sound'), WORKFLOW_ALERT_SOUND_ORDER)
    notification['size'] = resolve_alert_option(metadata.get('size'), WORKFLOW_ALERT_SIZE_ORDER)
    notification['audience'] = 'group' if _is_team_workflow_alert(notification) else 'owner'
    notification['acknowledged'] = acknowledged
    notification['acknowledged_at'] = str(notification.get('acknowledged_at') or '').strip() or None
    notification['acknowledged_by_name'] = (
        str(acknowledged_by.get('display_name') or '').strip() or None
    ) if acknowledged else None
    notification.pop('acknowledged_by', None)
    notification['content_scope'] = content_scope
    if notification.get('scope') == 'group':
        notification['read_by'] = [reader_user_id] if reader_user_id in (notification.get('read_by') or []) else []
        notification['dismissed_by'] = (
            [reader_user_id] if reader_user_id in (notification.get('dismissed_by') or []) else []
        )
    return notification


def _get_notification_type_config(notification):
    notification_type = notification.get('notification_type')
    if notification_type == WORKFLOW_ALERT_NOTIFICATION_TYPE:
        priority_config = WORKFLOW_ALERT_PRIORITY_CONFIG.get(
            _get_workflow_alert_priority(notification),
            NOTIFICATION_TYPES[WORKFLOW_ALERT_NOTIFICATION_TYPE],
        )
        if _get_workflow_alert_category(notification) == WORKFLOW_ALERT_FAILURE_CATEGORY:
            return {
                'icon': WORKFLOW_ALERT_FAILURE_ICON,
                'color': priority_config.get('color', 'danger'),
            }
        return priority_config

    return NOTIFICATION_TYPES.get(
        notification_type,
        NOTIFICATION_TYPES['system_announcement'],
    )


def get_notifications_by_metadata(
    metadata_filters=None, notification_types=None, *, safe_errors=False, strict=False, missing_metadata_fields=(),
):
    """Fetch notifications matching metadata values and optional types."""
    try:
        query_parts = ["SELECT * FROM c WHERE 1=1"]
        parameters = []

        if notification_types:
            type_clauses = []
            for index, notification_type in enumerate(notification_types):
                parameter_name = f"@notification_type_{index}"
                type_clauses.append(f"c.notification_type = {parameter_name}")
                parameters.append({"name": parameter_name, "value": notification_type})
            query_parts.append(f"AND ({' OR '.join(type_clauses)})")

        for key, value in (metadata_filters or {}).items():
            if value is None:
                continue
            parameter_name = f"@metadata_{key}"
            query_parts.append(f"AND c.metadata.{key} = {parameter_name}")
            parameters.append({"name": parameter_name, "value": value})
        for key in missing_metadata_fields:
            if key not in {"request_id", "document_version"}:
                raise ValueError("Unsupported notification absence filter.")
            query_parts.append(f"AND NOT IS_DEFINED(c.metadata.{key})")

        return list(cosmos_notifications_container.query_items(
            query=" ".join(query_parts),
            parameters=parameters or None,
            enable_cross_partition_query=True
        ))
    except Exception as e:
        if strict:
            _log_notification_failure("notification_lookup_failed", e)
            raise
        if safe_errors:
            _log_notification_failure("notification_lookup_failed", e)
            return []
        debug_print(f"Error fetching notifications by metadata: {e}")
        return []


def delete_notifications_by_metadata(
    metadata_filters=None, notification_types=None, *, safe_errors=False, strict=False, missing_metadata_fields=(),
    operation_guard=None,
):
    """Delete notifications matching metadata values and optional types."""
    deleted_count = 0
    if operation_guard is not None:
        operation_guard()
    notifications = get_notifications_by_metadata(
        metadata_filters=metadata_filters,
        notification_types=notification_types,
        **({"safe_errors": True} if safe_errors else {}),
        **({"strict": True} if strict else {}),
        **({"missing_metadata_fields": missing_metadata_fields} if missing_metadata_fields else {}),
    )

    for notification in notifications:
        partition_key = notification.get("user_id") if strict else _get_notification_partition_key(notification)
        if strict and (not notification.get("id") or "user_id" not in notification):
            raise ValueError("Notification identity could not be confirmed.")
        if not strict and not partition_key:
            continue

        if operation_guard is not None:
            operation_guard()
        try:
            cosmos_notifications_container.delete_item(
                item=notification['id'],
                partition_key=partition_key
            )
            deleted_count += 1
        except Exception as e:
            if strict:
                if getattr(e, "status_code", None) == 404:
                    continue
                _log_notification_failure("notification_cleanup_failed", e)
                raise
            if safe_errors:
                _log_notification_failure("notification_cleanup_failed", e)
                continue
            debug_print(
                f"Error deleting notification {notification.get('id')} by metadata: {e}"
            )

    return deleted_count


def create_notification(
    user_id=None,
    group_id=None,
    public_workspace_id=None,
    notification_type='system_announcement',
    title='',
    message='',
    link_url='',
    link_context=None,
    metadata=None,
    assignment=None,
    notification_id=None,
    idempotency_key=None,
    strict=False,
):
    """
    Create a notification for personal, group, or public workspace scope.
    
    Args:
        user_id (str, optional): User ID for personal notifications (deprecated if using assignment)
        group_id (str, optional): Group ID for group-scoped notifications
        public_workspace_id (str, optional): Public workspace ID for workspace notifications
        notification_type (str): Type of notification (must be in NOTIFICATION_TYPES)
        title (str): Notification title
        message (str): Notification message
        link_url (str): URL to navigate to when clicked
        link_context (dict, optional): Additional context for navigation
        metadata (dict, optional): Flexible metadata for type-specific data
        assignment (dict, optional): Role and ownership-based assignment:
            {
                'roles': ['Admin', 'ControlCenterAdmin'],  # Users with these roles see notification
                'personal_workspace_owner_id': 'user123',   # Personal workspace owner
                'group_owner_id': 'user456',                # Group owner
                'public_workspace_owner_id': 'user789'      # Public workspace owner
            }
            If any role matches or any owner ID matches user's ID, notification is visible.
        notification_id (str, optional): Server-generated idempotency ID for durable workflows.
        idempotency_key (str, optional): Nonempty opaque server retry key, at most 512
            characters. Produces a deterministic ID bound to scope, audience and type.
            A duplicate create point-reads and returns the existing notification,
            preserving its original content, timestamp, read and dismissal state.
            The key itself is never stored or logged. Do not combine with notification_id.
        strict (bool, optional): Propagate delivery and readback failures to callers
            that must distinguish uncertain transport outcomes from known refusals.
        
    Returns:
        dict: Created notification, existing notification for a repeated retry key,
            or None on error. Omitting retry options preserves random-ID behavior.
    """
    use_retry_key = idempotency_key is not None
    notification_doc = None
    try:
        if use_retry_key and notification_id is not None:
            raise ValueError("Choose one notification retry identifier.")
        # Determine scope and partition key
        scope = 'personal'
        partition_key = user_id
        
        # If assignment is provided, always use assignment partition for role-based notifications
        if assignment:
            # Assignment-based notifications always use the special assignment partition
            # This allows role-based filtering across all users
            scope = 'assignment'
            partition_key = ASSIGNMENT_NOTIFICATIONS_PARTITION_KEY
        else:
            # Legacy behavior - partition by specific workspace
            if group_id:
                scope = 'group'
                partition_key = group_id
            elif public_workspace_id:
                scope = 'public_workspace'
                partition_key = public_workspace_id
        
        if not partition_key:
            debug_print("create_notification: No partition key provided")
            return None
        
        # Validate notification type
        if notification_type not in NOTIFICATION_TYPES:
            if use_retry_key:
                _log_notification_failure("notification_type_unrecognized", ValueError())
            else:
                debug_print(f"Unknown notification type: {notification_type}")
        
        notification_doc = {
            'id': notification_id or (None if use_retry_key else str(uuid.uuid4())),
            'user_id': user_id,
            'group_id': group_id,
            'public_workspace_id': public_workspace_id,
            'scope': scope,
            'notification_type': notification_type,
            'title': title,
            'message': message,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'ttl': TTL_60_DAYS,
            'read_by': [],
            'dismissed_by': [],
            'link_url': link_url or '',
            'link_context': link_context or {},
            'metadata': metadata or {},
            'assignment': assignment or None
        }
        if use_retry_key:
            notification_doc['id'] = _notification_retry_id(idempotency_key, notification_doc)
        
        # Create in Cosmos with partition key based on scope
        cosmos_notifications_container.create_item(notification_doc)
        
        if not use_retry_key:
            debug_print(
                f"Notification created: {notification_doc['id']} "
                f"[{scope}] [{notification_type}] for partition: {partition_key}"
            )
        
        return notification_doc
        
    except Exception as e:
        if use_retry_key:
            if notification_doc and notification_doc.get('id') and getattr(e, 'status_code', None) == 409:
                try:
                    return _read_existing_notification(notification_doc)
                except Exception as read_error:
                    _log_notification_failure("notification_retry_lookup_failed", read_error)
                    if strict:
                        raise
                    return None
            _log_notification_failure("notification_delivery_failed", e)
            if strict:
                raise
            return None
        if notification_id:
            if getattr(e, 'status_code', None) == 409:
                return {'id': notification_id}
            _log_notification_failure("notification_delivery_failed", e)
            if strict:
                raise
            return None
        debug_print(f"Error creating notification: {e}")
        if strict:
            raise
        return None


def broadcast_system_notification(title, message, metadata=None):
    """Create a system announcement visible to all users regardless of role."""
    return create_notification(
        notification_type='system_announcement',
        title=title,
        message=message,
        metadata=metadata or {},
        assignment={'all_users': True}
    )


def create_m365_approval_notification(approval):
    """Deliver a deterministic, subject-only notification without source content."""
    subject_user_id = approval.get('subject_user_id')
    if (
        not subject_user_id or approval.get('approval_scope') != 'user'
        or approval.get('group_id') != subject_user_id
        or approval.get('request_type') not in {
            'm365_source_sharing', 'm365_extended_analysis', 'm365_workflow_run_as'
        }
    ):
        raise ValueError("A subject-owned Microsoft 365 approval is required.")
    status = approval.get('status')
    if status not in {'pending', 'approved', 'denied', 'expired', 'invalidated', 'revoked', 'cancelled'}:
        raise ValueError("Invalid Microsoft 365 approval status.")
    approval_id = approval['id']
    pending = status == 'pending'
    notification_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"m365-approval:{approval_id}:{status}"))
    notification = {
        'id': notification_id,
        'user_id': subject_user_id,
        'group_id': None,
        'public_workspace_id': None,
        'scope': 'personal',
        'assignment': None,
        'notification_type': M365_APPROVAL_PENDING_NOTIFICATION_TYPE if pending else M365_APPROVAL_UPDATED_NOTIFICATION_TYPE,
        'title': 'Microsoft 365 approval required' if pending else 'Microsoft 365 approval updated',
        'message': (
            'Review the Microsoft 365 request for your data. Only you can decide.'
            if pending else 'Your Microsoft 365 request changed. Open Approvals to see the decision and continuation state.'
        ),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'ttl': TTL_60_DAYS,
        'read_by': [],
        'dismissed_by': [],
        'link_url': f"/approvals?{urlencode({'m365_approval': approval_id})}",
        'link_context': {'approval_id': approval_id, 'group_id': subject_user_id},
        'metadata': {
            'approval_id': approval_id,
            'request_type': approval['request_type'],
            'status': status,
        },
    }
    try:
        try:
            cosmos_notifications_container.create_item(body=notification)
        except exceptions.CosmosResourceExistsError:
            # Deterministic IDs make repeated notification delivery idempotent.
            pass
        if not pending:
            pending_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"m365-approval:{approval_id}:pending"))
            try:
                cosmos_notifications_container.delete_item(item=pending_id, partition_key=subject_user_id)
            except exceptions.CosmosResourceNotFoundError:
                # Another worker may already have removed the pending notification.
                pass
        return notification
    except exceptions.CosmosHttpResponseError as exc:
        log_event(
            "[APPROVALS] Microsoft 365 notification delivery is pending",
            extra={'approval_id': approval_id, 'exception_type': type(exc).__name__},
            level=logging.WARNING,
        )
        return None


def create_group_notification(group_id, notification_type, title, message, link_url='', link_context=None, metadata=None):
    """
    Create a notification for all members of a group.
    
    Args:
        group_id (str): Group ID
        notification_type (str): Type of notification
        title (str): Notification title
        message (str): Notification message
        link_url (str): URL to navigate to when clicked
        link_context (dict, optional): Additional context for navigation
        metadata (dict, optional): Additional metadata
        
    Returns:
        dict: Created notification or None on error
    """
    return create_notification(
        group_id=group_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link_url=link_url,
        link_context=link_context or {'workspace_type': 'group', 'group_id': group_id},
        metadata=metadata
    )


def create_public_workspace_notification(
    public_workspace_id,
    notification_type,
    title,
    message,
    link_url='',
    link_context=None,
    metadata=None
):
    """
    Create a notification for all members of a public workspace.
    
    Args:
        public_workspace_id (str): Public workspace ID
        notification_type (str): Type of notification
        title (str): Notification title
        message (str): Notification message
        link_url (str): URL to navigate to when clicked
        link_context (dict, optional): Additional context for navigation
        metadata (dict, optional): Additional metadata
        
    Returns:
        dict: Created notification or None on error
    """
    return create_notification(
        public_workspace_id=public_workspace_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link_url=link_url,
        link_context=link_context or {
            'workspace_type': 'public',
            'public_workspace_id': public_workspace_id
        },
        metadata=metadata
    )


def create_chat_response_notification(
    user_id,
    conversation_id,
    message_id,
    conversation_title='',
    response_preview='',
    *,
    idempotency_key=None,
    strict=False,
):
    """Create a personal notification when a chat response completes.

    ``idempotency_key`` and ``strict`` pass through to ``create_notification``, so a server
    retry with the same key returns the existing notice rather than creating a second one.
    """
    normalized_title = str(conversation_title or '').strip() or 'Conversation'
    normalized_preview = str(response_preview or '').strip()
    if len(normalized_preview) > 160:
        normalized_preview = f"{normalized_preview[:157]}..."

    notification_message = (
        normalized_preview
        or f'The AI model responded in {normalized_title}.'
    )

    return create_notification(
        user_id=user_id,
        notification_type='chat_response_complete',
        title=f'AI responded in {normalized_title}',
        message=notification_message,
        link_url=f'/chats?conversationId={conversation_id}',
        link_context={
            'workspace_type': 'personal',
            'conversation_id': conversation_id,
        },
        metadata={
            'conversation_id': conversation_id,
            'message_id': message_id,
        },
        idempotency_key=idempotency_key,
        strict=strict,
    )


def create_collaboration_message_notification(
    user_id,
    conversation_id,
    message_id,
    conversation_title='',
    sender_display_name='',
    message_preview='',
    chat_type='',
    group_id=None,
    mentioned_user=False,
):
    """Create a personal notification when another participant posts in a shared conversation."""
    normalized_title = str(conversation_title or '').strip() or 'Shared Conversation'
    normalized_sender = str(sender_display_name or '').strip() or 'A participant'
    normalized_preview = str(message_preview or '').strip()
    if len(normalized_preview) > 160:
        normalized_preview = f"{normalized_preview[:157]}..."

    notification_title = f"New shared message in {normalized_title}"
    if mentioned_user:
        notification_title = f"{normalized_sender} tagged you in {normalized_title}"

    notification_message = normalized_preview or f"{normalized_sender} posted in {normalized_title}."

    return create_notification(
        user_id=user_id,
        notification_type='collaboration_message_received',
        title=notification_title,
        message=notification_message,
        link_url=f'/chats?conversationId={conversation_id}',
        link_context={
            'workspace_type': 'group' if str(chat_type or '').strip().lower().startswith('group') else 'personal',
            'conversation_id': conversation_id,
            'group_id': group_id,
            'conversation_kind': 'collaborative',
        },
        metadata={
            'conversation_id': conversation_id,
            'message_id': message_id,
            'sender_display_name': normalized_sender,
            'mentioned_user': bool(mentioned_user),
            'conversation_kind': 'collaborative',
            'chat_type': chat_type,
            'group_id': group_id,
        }
    )


def create_workflow_priority_notification(
    user_id,
    workflow_id,
    workflow_name,
    priority,
    title,
    message,
    link_url='',
    link_context=None,
    metadata=None,
    group_id=None,
):
    """Create a workflow alert notification with a priority-aware display.

    The alert is personal to ``user_id`` unless ``group_id`` is given, in which case one shared
    group-scoped alert reaches every member of that group. ``metadata['owner_user_id']`` then
    names the workflow's owner, the only member who reads the alert in full.
    """
    normalized_priority = str(priority or 'medium').strip().lower()
    if normalized_priority not in WORKFLOW_ALERT_PRIORITY_CONFIG:
        normalized_priority = 'medium'

    alert_metadata = dict(metadata or {})
    alert_metadata.setdefault('priority', normalized_priority)
    alert_metadata.setdefault('workflow_id', workflow_id)
    alert_metadata.setdefault('workflow_name', workflow_name)

    normalized_group_id = str(group_id or '').strip()
    if normalized_group_id:
        alert_metadata['audience'] = 'group'
        alert_metadata.setdefault('owner_user_id', user_id)
        return create_notification(
            group_id=normalized_group_id,
            notification_type=WORKFLOW_ALERT_NOTIFICATION_TYPE,
            title=title,
            message=message,
            link_url=link_url,
            link_context=link_context or {},
            metadata=alert_metadata,
        )

    return create_notification(
        user_id=user_id,
        notification_type=WORKFLOW_ALERT_NOTIFICATION_TYPE,
        title=title,
        message=message,
        link_url=link_url,
        link_context=link_context or {},
        metadata=alert_metadata,
    )


def get_user_notifications(user_id, page=1, per_page=20, include_read=True, include_dismissed=False, user_roles=None):
    """
    Fetch notifications visible to a user from personal, group, and public workspace scopes.
    Supports assignment-based notifications that target users by roles and/or ownership.
    
    Args:
        user_id (str): User's unique identifier
        page (int): Page number (1-indexed)
        per_page (int): Items per page
        include_read (bool): Include notifications already read by user
        include_dismissed (bool): Include notifications dismissed by user
        user_roles (list, optional): User's roles for assignment-based notifications
        
    Returns:
        dict: {
            'notifications': [...],
            'total': int,
            'page': int,
            'per_page': int,
            'has_more': bool
        }
    """
    try:
        all_notifications = []
        
        # 1. Fetch personal notifications
        personal_query = "SELECT * FROM c WHERE c.user_id = @user_id"
        personal_params = [{"name": "@user_id", "value": user_id}]
        
        personal_notifications = list(cosmos_notifications_container.query_items(
            query=personal_query,
            parameters=personal_params,
            partition_key=user_id
        ))
        all_notifications.extend(personal_notifications)
        
        # 2. Fetch group notifications for user's groups
        from functions_group import get_user_groups
        user_groups = get_user_groups(user_id)
        
        for group in user_groups:
            group_id = group['id']
            group_query = "SELECT * FROM c WHERE c.group_id = @group_id"
            group_params = [{"name": "@group_id", "value": group_id}]
            
            group_notifications = list(cosmos_notifications_container.query_items(
                query=group_query,
                parameters=group_params,
                enable_cross_partition_query=True
            ))
            all_notifications.extend(group_notifications)
        
        # 3. Fetch public workspace notifications
        from functions_public_workspaces import get_user_public_workspaces
        user_workspaces = get_user_public_workspaces(user_id)
        
        for workspace in user_workspaces:
            workspace_id = workspace['id']
            workspace_query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id"
            workspace_params = [{"name": "@workspace_id", "value": workspace_id}]
            
            workspace_notifications = list(cosmos_notifications_container.query_items(
                query=workspace_query,
                parameters=workspace_params,
                enable_cross_partition_query=True
            ))
            all_notifications.extend(workspace_notifications)
        
        # 4. Fetch assignment-based notifications
        assignment_query = "SELECT * FROM c WHERE c.scope = 'assignment'"
        assignment_notifications = list(cosmos_notifications_container.query_items(
            query=assignment_query,
            enable_cross_partition_query=True
        ))
        
        # Filter assignment notifications based on user's roles and ownership
        for notif in assignment_notifications:
            assignment = notif.get('assignment')
            if not assignment:
                continue
            
            # Check if user matches assignment criteria
            user_matches = False

            # Broadcast to all users regardless of role/ownership
            if assignment.get('all_users'):
                user_matches = True
            
            # Check roles
            if not user_matches and user_roles and assignment.get('roles'):
                for role in assignment.get('roles', []):
                    if role in user_roles:
                        user_matches = True
                        break
            
            # Check ownership IDs
            if not user_matches:
                if assignment.get('personal_workspace_owner_id') == user_id:
                    user_matches = True
                elif assignment.get('group_owner_id') == user_id:
                    user_matches = True
                elif assignment.get('public_workspace_owner_id') == user_id:
                    user_matches = True
            
            if user_matches:
                all_notifications.append(notif)
        
        # Filter based on read/dismissed status
        filtered_notifications = []
        for notif in all_notifications:
            notif = sanitize_workflow_alert_record(notif)
            notif_id = notif.get('id', 'unknown')
            read_by = notif.get('read_by', [])
            dismissed_by = notif.get('dismissed_by', [])
            
            if not include_dismissed and user_id in dismissed_by:
                continue
            if not include_read and user_id in read_by:
                continue

            if notif.get('notification_type') == WORKFLOW_ALERT_NOTIFICATION_TYPE:
                notif = _decorate_workflow_alert(notif, user_id)

            # Add UI metadata
            notif['message'] = _get_notification_display_message(notif)
            notif['is_read'] = user_id in read_by
            notif['is_dismissed'] = user_id in dismissed_by
            notif['type_config'] = _get_notification_type_config(notif)
            
            filtered_notifications.append(notif)
        
        # Sort by created_at descending (newest first)
        filtered_notifications.sort(
            key=lambda x: x.get('created_at', ''),
            reverse=True
        )
        
        # Pagination
        total = len(filtered_notifications)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated = filtered_notifications[start_idx:end_idx]
        
        return {
            'notifications': paginated,
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': end_idx < total
        }
        
    except Exception as e:
        debug_print(f"Error fetching notifications for user {user_id}: {e}")
        return {
            'notifications': [],
            'total': 0,
            'page': page,
            'per_page': per_page,
            'has_more': False
        }


def get_unread_notification_count(user_id):
    """
    Get count of unread notifications for a user across all scopes.
    
    Args:
        user_id (str): User's unique identifier
        
    Returns:
        int: Count of unread notifications (capped at 10 for efficiency)
    """
    try:
        # Get notifications without pagination
        result = get_user_notifications(
            user_id=user_id,
            page=1,
            per_page=10,  # Only need first 10 for badge display
            include_read=False,
            include_dismissed=False
        )
        
        return min(result['total'], 10)  # Cap at 10 for display purposes
        
    except Exception as e:
        debug_print(f"Error counting unread notifications for {user_id}: {e}")
        return 0


def get_recent_chat_response_notifications(user_id, limit=50):
    """Return recent personal chat completion event identities for one user."""
    try:
        normalized_limit = max(1, min(int(limit or 50), 100))
    except (TypeError, ValueError):
        normalized_limit = 50

    try:
        notifications = list(cosmos_notifications_container.query_items(
            query=(
                f"SELECT TOP {normalized_limit} "
                "c.id, c.created_at, c.link_context, c.metadata "
                "FROM c WHERE c.user_id = @user_id "
                "AND c.notification_type = @notification_type "
                "ORDER BY c.created_at DESC"
            ),
            parameters=[
                {"name": "@user_id", "value": user_id},
                {"name": "@notification_type", "value": "chat_response_complete"},
            ],
            partition_key=user_id,
        ))
        return notifications
    except Exception as e:
        log_event(
            "[NOTIFICATIONS] Failed to load recent chat completion events.",
            extra={
                "user_id": user_id,
                "error": str(e),
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise


# Notifications expire after 60 days, so a longer recency window could never match more.
WORKFLOW_ALERT_SINCE_HOURS_MAX = TTL_60_DAYS // 3600


def parse_workflow_alert_since_hours(value):
    """Return a validated pop-up recency window in hours, or None when none was asked for.

    Accepts a whole number of hours from 1 to WORKFLOW_ALERT_SINCE_HOURS_MAX, as an int or as
    a plain string of ASCII digits. Anything else raises ValueError, so a caller can reject
    the request rather than silently widen or narrow the window.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('since_hours must be a whole number of hours.')
    if isinstance(value, int):
        hours = value
    elif isinstance(value, str) and 0 < len(value) <= 4 and value.isascii() and value.isdigit():
        hours = int(value)
    else:
        raise ValueError('since_hours must be a whole number of hours.')
    if hours < 1 or hours > WORKFLOW_ALERT_SINCE_HOURS_MAX:
        raise ValueError(f'since_hours must be between 1 and {WORKFLOW_ALERT_SINCE_HOURS_MAX}.')
    return hours


def get_unread_workflow_priority_notifications(user_id, limit=5, since_hours=None, raise_on_error=False):
    """Return the most recent unread pop-up workflow alerts for a user.

    The unread, not-dismissed and not-notify-only filters run in Cosmos, so the read is
    bounded by ``limit`` instead of scanning every alert still inside the 60-day TTL.
    ``since_hours`` optionally keeps only alerts created within that many hours; None leaves
    the window open, which is what the classic interface asks for.

    A failed read returns an empty list, as the classic interface has always had it. With
    ``raise_on_error`` the failure is raised instead, for a caller that must not mistake it
    for "nothing unread": the V2 interface treats a short list as every unread pop-up alert
    there is, and would retire the ones it is showing.
    """
    try:
        normalized_limit = max(1, min(int(limit or 5), 10))
    except (TypeError, ValueError):
        normalized_limit = 5
    normalized_since_hours = parse_workflow_alert_since_hours(since_hours)

    # These filters must stay equivalent to the Python re-check below, or TOP could starve it.
    query_parts = [
        'SELECT TOP @limit * FROM c',
        'WHERE c.user_id = @user_id',
        'AND c.notification_type = @notification_type',
        'AND (NOT IS_ARRAY(c.read_by) OR NOT ARRAY_CONTAINS(c.read_by, @user_id))',
        'AND (NOT IS_ARRAY(c.dismissed_by) OR NOT ARRAY_CONTAINS(c.dismissed_by, @user_id))',
        'AND (NOT IS_STRING(c.metadata.delivery) OR LOWER(TRIM(c.metadata.delivery)) != @notify_only)',
    ]
    parameters = [
        {'name': '@limit', 'value': normalized_limit},
        {'name': '@user_id', 'value': user_id},
        {'name': '@notification_type', 'value': WORKFLOW_ALERT_NOTIFICATION_TYPE},
        {'name': '@notify_only', 'value': WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY},
    ]
    if normalized_since_hours is not None:
        # Stamped the way create_notification stamps created_at, so the strings compare in order.
        created_after = (datetime.now(timezone.utc) - timedelta(hours=normalized_since_hours)).isoformat()
        query_parts.append('AND c.created_at >= @created_after')
        parameters.append({'name': '@created_after', 'value': created_after})
    query_parts.append('ORDER BY c.created_at DESC')

    try:
        notifications = list(cosmos_notifications_container.query_items(
            query=' '.join(query_parts),
            parameters=parameters,
            partition_key=user_id,
        ))

        unread_notifications = []
        for notification in notifications:
            notification = sanitize_workflow_alert_record(notification)
            if user_id in notification.get('dismissed_by', []):
                continue
            if user_id in notification.get('read_by', []):
                continue
            # Quiet severities stay in the notification bell instead of interrupting.
            if _get_workflow_alert_delivery(notification) == WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY:
                continue

            unread_notifications.append(_present_workflow_alert_popup(notification, user_id))

            if len(unread_notifications) >= normalized_limit:
                break

        return unread_notifications
    except Exception as e:
        debug_print(f"Error fetching unread workflow alerts for {user_id}: {e}")
        if raise_on_error:
            raise
        return []


def _normalize_workflow_alert_limit(limit):
    try:
        return max(1, min(int(limit or 5), 10))
    except (TypeError, ValueError):
        return 5


def _present_workflow_alert_popup(notification, user_id):
    """Decorate one workflow alert for a pop-up reader, reporting only that reader's state."""
    read_by = notification.get('read_by') or []
    dismissed_by = notification.get('dismissed_by') or []
    is_read = user_id in read_by
    is_dismissed = user_id in dismissed_by
    notification = _decorate_workflow_alert(notification, user_id)
    notification['message'] = _get_notification_display_message(notification)
    notification['is_read'] = is_read
    notification['is_dismissed'] = is_dismissed
    notification['type_config'] = _get_notification_type_config(notification)
    return notification


def _get_user_group_ids(user_id):
    """Return the ids of the groups the user belongs to now, read from the groups store."""
    return sorted({
        str(group.get('id') or '').strip()
        for group in get_user_groups(user_id) or []
        if isinstance(group, dict) and str(group.get('id') or '').strip()
    })


def _read_workflow_alert_page(query_parts, parameters, partition_key=None):
    query = ' '.join(query_parts)
    if partition_key is not None:
        return list(cosmos_notifications_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=partition_key,
        ))
    return list(cosmos_notifications_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    ))


# Must-acknowledge alerts keep popping up until acknowledged, whatever their age or the reader's
# read state, so they are read separately and can't be crowded out of TOP by newer alerts.
_WORKFLOW_ALERT_UNACKNOWLEDGED_FILTERS = [
    'AND c.notification_type = @notification_type',
    'AND c.metadata.require_acknowledgment = true',
    "AND (NOT IS_DEFINED(c.acknowledged_at) OR IS_NULL(c.acknowledged_at) OR c.acknowledged_at = '')",
    'AND (NOT IS_STRING(c.metadata.delivery) OR LOWER(TRIM(c.metadata.delivery)) != @notify_only)',
]


def _is_pending_acknowledgment_popup(notification):
    return (
        _workflow_alert_requires_acknowledgment(notification)
        and not _is_workflow_alert_acknowledged(notification)
        and _get_workflow_alert_delivery(notification) != WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY
    )


def get_workflow_alert_popups(user_id, limit=5, since_hours=None, raise_on_error=False):
    """Return every workflow alert that should pop up for a user, and whether that list is whole.

    Four bounded reads, each capped at ``limit``:

    - the user's unread pop-up alerts (``get_unread_workflow_priority_notifications``);
    - the user's must-acknowledge alerts nobody has acknowledged, whatever their age or read state;
    - unread pop-up team alerts from the groups the user belongs to now;
    - unacknowledged must-acknowledge team alerts from those groups.

    ``since_hours`` narrows only the unread reads. ``complete`` is False when any read came back
    full, so a client can't take a capped answer for every alert there is. Team alerts are reduced
    for members other than the workflow's owner (``_decorate_workflow_alert``).

    Returns ``{'notifications': [...], 'complete': bool}``, newest first.
    """
    normalized_limit = _normalize_workflow_alert_limit(limit)
    normalized_since_hours = parse_workflow_alert_since_hours(since_hours)
    popups = {}
    complete = True

    def keep(notifications):
        for notification in notifications:
            popups.setdefault(notification.get('id'), notification)

    unread = get_unread_workflow_priority_notifications(
        user_id,
        limit=normalized_limit,
        since_hours=normalized_since_hours,
        raise_on_error=raise_on_error,
    )
    complete = len(unread) < normalized_limit
    keep(unread)

    base_parameters = [
        {'name': '@limit', 'value': normalized_limit},
        {'name': '@user_id', 'value': user_id},
        {'name': '@notification_type', 'value': WORKFLOW_ALERT_NOTIFICATION_TYPE},
        {'name': '@notify_only', 'value': WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY},
    ]
    try:
        pending = _read_workflow_alert_page(
            ['SELECT TOP @limit * FROM c', 'WHERE c.user_id = @user_id', *_WORKFLOW_ALERT_UNACKNOWLEDGED_FILTERS,
             'ORDER BY c.created_at DESC'],
            base_parameters,
            partition_key=user_id,
        )
        complete = complete and len(pending) < normalized_limit
        keep(
            _present_workflow_alert_popup(notification, user_id)
            for notification in (sanitize_workflow_alert_record(item) for item in pending)
            if notification.get('user_id') == user_id and _is_pending_acknowledgment_popup(notification)
        )

        group_ids = _get_user_group_ids(user_id)
        if group_ids:
            team_parameters = [*base_parameters, {'name': '@group_ids', 'value': group_ids}]
            team_unread_parts = [
                'SELECT TOP @limit * FROM c',
                'WHERE ARRAY_CONTAINS(@group_ids, c.group_id)',
                "AND c.scope = 'group'",
                'AND c.notification_type = @notification_type',
                'AND (NOT IS_ARRAY(c.read_by) OR NOT ARRAY_CONTAINS(c.read_by, @user_id))',
                'AND (NOT IS_ARRAY(c.dismissed_by) OR NOT ARRAY_CONTAINS(c.dismissed_by, @user_id))',
                'AND (NOT IS_STRING(c.metadata.delivery) OR LOWER(TRIM(c.metadata.delivery)) != @notify_only)',
                'AND (NOT IS_DEFINED(c.metadata.require_acknowledgment) OR c.metadata.require_acknowledgment != true)',
            ]
            team_unread_parameters = list(team_parameters)
            if normalized_since_hours is not None:
                created_after = (datetime.now(timezone.utc) - timedelta(hours=normalized_since_hours)).isoformat()
                team_unread_parts.append('AND c.created_at >= @created_after')
                team_unread_parameters.append({'name': '@created_after', 'value': created_after})
            team_unread_parts.append('ORDER BY c.created_at DESC')

            team_unread = _read_workflow_alert_page(team_unread_parts, team_unread_parameters)
            complete = complete and len(team_unread) < normalized_limit
            keep(
                _present_workflow_alert_popup(notification, user_id)
                for notification in (sanitize_workflow_alert_record(item) for item in team_unread)
                if _is_team_workflow_alert(notification)
                and notification.get('group_id') in group_ids
                and user_id not in (notification.get('read_by') or [])
                and user_id not in (notification.get('dismissed_by') or [])
                and _get_workflow_alert_delivery(notification) != WORKFLOW_ALERT_DELIVERY_NOTIFY_ONLY
                and not _workflow_alert_requires_acknowledgment(notification)
            )

            team_pending = _read_workflow_alert_page(
                ['SELECT TOP @limit * FROM c', 'WHERE ARRAY_CONTAINS(@group_ids, c.group_id)', "AND c.scope = 'group'",
                 *_WORKFLOW_ALERT_UNACKNOWLEDGED_FILTERS, 'ORDER BY c.created_at DESC'],
                [parameter for parameter in team_parameters if parameter['name'] != '@user_id'],
            )
            complete = complete and len(team_pending) < normalized_limit
            keep(
                _present_workflow_alert_popup(notification, user_id)
                for notification in (sanitize_workflow_alert_record(item) for item in team_pending)
                if _is_team_workflow_alert(notification)
                and notification.get('group_id') in group_ids
                and _is_pending_acknowledgment_popup(notification)
            )
    except Exception as e:
        log_event(
            '[NOTIFICATIONS] Workflow alert pop-up read failed.',
            extra={'user_id': user_id, 'error_type': type(e).__name__},
            level=logging.WARNING,
        )
        if raise_on_error:
            raise
        complete = False

    ordered = sorted(popups.values(), key=lambda item: str(item.get('created_at') or ''), reverse=True)
    return {'notifications': ordered, 'complete': complete}


def _read_notification_by_id(notification_id):
    """Find a notification by id across every scope's partition."""
    notifications = list(cosmos_notifications_container.query_items(
        query='SELECT * FROM c WHERE c.id = @notification_id',
        parameters=[{'name': '@notification_id', 'value': notification_id}],
        enable_cross_partition_query=True,
    ))
    return notifications[0] if notifications else None


def _write_notification_change(notification_id, change):
    """Apply ``change`` to a stored notification, writing only if nobody changed it meanwhile.

    ``change(notification)`` edits the document in place and returns True when it changed
    anything. Group and workspace notifications are shared by many readers, so writing a stale
    copy unconditionally could drop another reader's read or dismissal, or undo a workflow
    alert's acknowledgment. The write is conditional on the stored ETag and retried on a conflict.

    Returns the stored notification, or None when it doesn't exist or has no partition key.
    """
    for _attempt in range(NOTIFICATION_WRITE_ATTEMPTS):
        notification = _read_notification_by_id(notification_id)
        if not notification or not _get_notification_partition_key(notification):
            return None
        if not change(notification):
            return notification
        etag = notification.get('_etag')
        if not etag:
            return cosmos_notifications_container.upsert_item(notification)
        try:
            return cosmos_notifications_container.replace_item(
                item=notification['id'],
                body=notification,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise exceptions.CosmosAccessConditionFailedError(status_code=412, message='Notification changed.')


def _can_receive_workflow_alert(notification, user_id):
    """Return True when this user is one of the alert's recipients right now.

    A personal alert belongs to its owner. A team alert belongs to the current members of its
    group, re-checked against the groups store rather than taken from the request.
    """
    if not user_id:
        return False
    if _is_team_workflow_alert(notification):
        try:
            assert_group_role(
                user_id,
                str(notification.get('group_id') or '').strip(),
                allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES,
            )
        except (LookupError, PermissionError):
            return False
        return True
    return notification.get('scope') in (None, 'personal') and notification.get('user_id') == user_id


def acknowledge_workflow_alert(notification_id, user_id, display_name=''):
    """Acknowledge a must-acknowledge workflow alert for everyone who receives it.

    The caller must be a recipient: the owner of a personal alert, or a current member of a team
    alert's group. Anything else is answered as ``not_found``, so the response never confirms an
    alert the caller can't see. The first acknowledgment wins: the write is conditional on the
    stored ETag, and an alert someone already acknowledged keeps that acknowledgment. The
    caller's own read state is set either way.

    Returns ``(status, notification)``. ``status`` is ``acknowledged``, ``already_acknowledged``,
    ``not_found`` or ``not_required``; ``notification`` is the alert decorated for the caller,
    or None.
    """
    normalized_id = str(notification_id or '').strip()
    if not normalized_id or not user_id:
        return 'not_found', None

    outcome = {'status': 'not_found'}
    acknowledger_name = ' '.join(str(display_name or '').split())[:WORKFLOW_ALERT_ACKNOWLEDGER_NAME_MAX_LENGTH]

    def acknowledge(notification):
        if (
            notification.get('notification_type') != WORKFLOW_ALERT_NOTIFICATION_TYPE
            or not _can_receive_workflow_alert(notification, user_id)
        ):
            outcome['status'] = 'not_found'
            return False
        if not _workflow_alert_requires_acknowledgment(notification):
            outcome['status'] = 'not_required'
            return False

        changed = False
        if _is_workflow_alert_acknowledged(notification):
            outcome['status'] = 'already_acknowledged'
        else:
            outcome['status'] = 'acknowledged'
            notification['acknowledged_at'] = datetime.now(timezone.utc).isoformat()
            notification['acknowledged_by'] = {'user_id': user_id, 'display_name': acknowledger_name}
            changed = True
        read_by = list(notification.get('read_by') or [])
        if user_id not in read_by:
            read_by.append(user_id)
            notification['read_by'] = read_by
            changed = True
        return changed

    stored = _write_notification_change(normalized_id, acknowledge)
    if stored is None or outcome['status'] in ('not_found', 'not_required'):
        return outcome['status'], None

    if outcome['status'] == 'acknowledged':
        log_event(
            '[NOTIFICATIONS] Workflow alert acknowledged.',
            extra={
                'notification_id': normalized_id,
                'user_id': user_id,
                'scope': stored.get('scope'),
                'group_id': stored.get('group_id'),
                'workflow_id': _get_workflow_alert_metadata(stored).get('workflow_id'),
                'run_id': _get_workflow_alert_metadata(stored).get('run_id'),
            },
        )
    return outcome['status'], _present_workflow_alert_popup(sanitize_workflow_alert_record(stored), user_id)


def mark_notification_read(notification_id, user_id):
    """
    Mark a notification as read by a specific user.

    Reading never acknowledges a workflow alert that must be acknowledged.
    
    Args:
        notification_id (str): Notification ID
        user_id (str): User ID marking as read
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        def mark_read(notification):
            read_by = list(notification.get('read_by') or [])
            if user_id in read_by:
                return False
            read_by.append(user_id)
            notification['read_by'] = read_by
            return True

        stored = _write_notification_change(notification_id, mark_read)
        if stored is None:
            debug_print(f"Notification {notification_id} not found")
            return False

        debug_print(f"Notification {notification_id} marked read by {user_id}")
        return True
        
    except Exception as e:
        debug_print(f"Error marking notification {notification_id} as read: {e}")
        return False


def mark_chat_response_notifications_read_for_conversation(user_id, conversation_id):
    """Mark personal chat-completion notifications read for a conversation."""
    try:
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.notification_type = @notification_type
            AND c.metadata.conversation_id = @conversation_id
        """
        params = [
            {'name': '@user_id', 'value': user_id},
            {'name': '@notification_type', 'value': 'chat_response_complete'},
            {'name': '@conversation_id', 'value': conversation_id},
        ]

        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))

        marked_count = 0
        for notification in notifications:
            read_by = notification.get('read_by', [])
            if user_id in read_by:
                continue

            read_by.append(user_id)
            notification['read_by'] = read_by
            cosmos_notifications_container.upsert_item(notification)
            marked_count += 1

        return marked_count
    except Exception as e:
        debug_print(
            f"Error marking chat response notifications as read for conversation {conversation_id}: {e}"
        )
        return 0


def mark_collaboration_message_notifications_read_for_conversation(user_id, conversation_id):
    """Mark personal collaboration-message notifications read for a conversation."""
    try:
        query = """
            SELECT * FROM c
            WHERE c.user_id = @user_id
            AND c.notification_type = @notification_type
            AND c.metadata.conversation_id = @conversation_id
        """
        params = [
            {'name': '@user_id', 'value': user_id},
            {'name': '@notification_type', 'value': 'collaboration_message_received'},
            {'name': '@conversation_id', 'value': conversation_id},
        ]

        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            partition_key=user_id
        ))

        marked_count = 0
        for notification in notifications:
            read_by = notification.get('read_by', [])
            if user_id in read_by:
                continue

            read_by.append(user_id)
            notification['read_by'] = read_by
            cosmos_notifications_container.upsert_item(notification)
            marked_count += 1

        return marked_count
    except Exception as e:
        debug_print(
            f"Error marking collaboration notifications as read for conversation {conversation_id}: {e}"
        )
        return 0


def dismiss_notification(notification_id, user_id):
    """
    Dismiss a notification for a specific user (adds to dismissed_by).

    Dismissing never acknowledges a workflow alert that must be acknowledged.
    
    Args:
        notification_id (str): Notification ID
        user_id (str): User ID dismissing the notification
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        def dismiss(notification):
            dismissed_by = list(notification.get('dismissed_by') or [])
            if user_id in dismissed_by:
                return False
            dismissed_by.append(user_id)
            notification['dismissed_by'] = dismissed_by
            return True

        stored = _write_notification_change(notification_id, dismiss)
        if stored is None:
            debug_print(f"Notification {notification_id} not found")
            return False

        debug_print(f"Notification {notification_id} dismissed by {user_id}")
        return True
        
    except Exception as e:
        debug_print(f"Error dismissing notification {notification_id}: {e}")
        return False


def mark_all_read(user_id):
    """
    Mark all unread notifications as read for a user.
    
    Args:
        user_id (str): User's unique identifier
        
    Returns:
        int: Number of notifications marked as read
    """
    try:
        # Get all unread notifications
        result = get_user_notifications(
            user_id=user_id,
            page=1,
            per_page=1000,  # Get all unread
            include_read=False,
            include_dismissed=True
        )
        
        count = 0
        for notification in result['notifications']:
            if mark_notification_read(notification['id'], user_id):
                count += 1
        
        debug_print(f"Marked {count} notifications as read for user {user_id}")
        return count
        
    except Exception as e:
        debug_print(f"Error marking all notifications as read for {user_id}: {e}")
        return 0


def delete_notification(notification_id):
    """
    Permanently delete a notification (admin only).
    
    Args:
        notification_id (str): Notification ID to delete
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Find notification to get partition key
        query = "SELECT * FROM c WHERE c.id = @notification_id"
        params = [{"name": "@notification_id", "value": notification_id}]
        
        notifications = list(cosmos_notifications_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        if not notifications:
            return False
        
        notification = notifications[0]
        partition_key = _get_notification_partition_key(notification)
        
        if not partition_key:
            return False
        
        cosmos_notifications_container.delete_item(
            item=notification_id,
            partition_key=partition_key
        )
        
        debug_print(f"Notification {notification_id} permanently deleted")
        return True
        
    except Exception as e:
        debug_print(f"Error deleting notification {notification_id}: {e}")
        return False
