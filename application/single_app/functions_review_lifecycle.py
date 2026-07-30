# functions_review_lifecycle.py

from datetime import datetime, timezone

from functions_activity_logging import log_general_admin_action


ARCHIVE_STATE_ACTIVE = 'active'
ARCHIVE_STATE_ARCHIVED = 'archived'
ALLOWED_ARCHIVE_STATES = {
    ARCHIVE_STATE_ACTIVE,
    ARCHIVE_STATE_ARCHIVED,
}


def normalize_archive_state(value):
    """Normalize an archive-state query value, defaulting to active records."""
    normalized_value = str(value or ARCHIVE_STATE_ACTIVE).strip().lower()
    if normalized_value not in ALLOWED_ARCHIVE_STATES:
        raise ValueError("Archive state must be 'active' or 'archived'.")
    return normalized_value


def append_archive_query_filter(where_clauses, archive_state):
    """Add a backward-compatible archive predicate to a Cosmos SQL query."""
    normalized_state = normalize_archive_state(archive_state)
    if normalized_state == ARCHIVE_STATE_ARCHIVED:
        where_clauses.append("IS_DEFINED(c.is_archived) AND c.is_archived = true")
    else:
        where_clauses.append("(NOT IS_DEFINED(c.is_archived) OR c.is_archived = false)")


def apply_archive_state(item, archived, actor_id):
    """Apply archive or unarchive metadata to a review record."""
    changed_at = datetime.now(timezone.utc).isoformat()
    item['is_archived'] = archived
    if archived:
        item['archived_at'] = changed_at
        item['archived_by'] = actor_id
    else:
        item['unarchived_at'] = changed_at
        item['unarchived_by'] = actor_id
    return changed_at


def serialize_archive_metadata(item):
    """Return browser-safe lifecycle metadata for a review record."""
    return {
        'isArchived': bool(item.get('is_archived')),
        'archivedAt': item.get('archived_at'),
        'archivedBy': item.get('archived_by'),
        'unarchivedAt': item.get('unarchived_at'),
        'unarchivedBy': item.get('unarchived_by'),
    }


def log_review_lifecycle_action(
    record_type,
    lifecycle_action,
    item,
    actor,
    was_archived=None,
):
    """Write a non-sensitive admin activity event for a review record mutation."""
    action_names = {
        'archive': f'{record_type}_archived',
        'unarchive': f'{record_type}_unarchived',
        'delete': f'{record_type}_deleted',
    }
    descriptions = {
        'archive': f"Archived {record_type.replace('_', ' ')} record.",
        'unarchive': f"Unarchived {record_type.replace('_', ' ')} record.",
        'delete': f"Deleted {record_type.replace('_', ' ')} record.",
    }
    additional_context = {
        'record_type': record_type,
        'record_id': item.get('id'),
        'target_user_id': item.get('userId') or item.get('user_id'),
        'lifecycle_action': lifecycle_action,
        'was_archived': (
            bool(item.get('is_archived'))
            if was_archived is None
            else bool(was_archived)
        ),
    }

    if record_type == 'feedback':
        additional_context.update({
            'conversation_id': item.get('conversationId'),
            'message_id': item.get('messageId'),
        })
    elif record_type == 'safety_violation':
        additional_context.update({
            'action': item.get('action'),
            'action_request_id': item.get('action_request_id'),
            'action_request_status': item.get('action_request_status'),
        })

    return log_general_admin_action(
        admin_user_id=actor.get('id'),
        admin_email=actor.get('email') or '',
        action=action_names[lifecycle_action],
        description=descriptions[lifecycle_action],
        additional_context=additional_context,
    )
