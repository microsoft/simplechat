# functions_conversation_unread.py

"""Helpers for conversation unread assistant-response state."""

from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.cosmos import exceptions


# Closed outcomes of mark_conversation_unread_guarded.
UNREAD_MARKED = 'marked'
UNREAD_ALREADY_MARKED = 'already_marked'
UNREAD_READ_SINCE = 'read_since'
UNREAD_NOT_FOUND = 'not_found'
UNREAD_UNAVAILABLE = 'unavailable'
UNREAD_CONFLICT = 'conflict'


def normalize_conversation_unread_state(conversation_item):
    """Ensure unread assistant-response fields always exist on a conversation."""
    if not isinstance(conversation_item, dict):
        return conversation_item

    conversation_item['has_unread_assistant_response'] = bool(
        conversation_item.get('has_unread_assistant_response', False)
    )
    conversation_item['last_unread_assistant_message_id'] = conversation_item.get(
        'last_unread_assistant_message_id'
    )
    conversation_item['last_unread_assistant_at'] = conversation_item.get(
        'last_unread_assistant_at'
    )
    return conversation_item


def mark_conversation_unread(
    conversation_item,
    assistant_message_id,
    unread_timestamp=None,
):
    """Mark a conversation as having an unread assistant response."""
    normalized_item = normalize_conversation_unread_state(conversation_item)
    normalized_item['has_unread_assistant_response'] = True
    normalized_item['last_unread_assistant_message_id'] = assistant_message_id
    normalized_item['last_unread_assistant_at'] = unread_timestamp or datetime.utcnow().isoformat()
    return normalized_item


def clear_conversation_unread(conversation_item):
    """Clear unread assistant-response state from a conversation."""
    normalized_item = normalize_conversation_unread_state(conversation_item)
    normalized_item['has_unread_assistant_response'] = False
    normalized_item['last_unread_assistant_message_id'] = None
    normalized_item['last_unread_assistant_at'] = None
    return normalized_item


def _parse_utc_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reached(value, threshold):
    """Whether timestamp ``value`` is at or after ``threshold``; False when either is unreadable."""
    parsed_value = _parse_utc_timestamp(value)
    parsed_threshold = _parse_utc_timestamp(threshold)
    return parsed_value is not None and parsed_threshold is not None and parsed_value >= parsed_threshold


def _conversation_unavailable(conversation_item, user_id, require_private):
    if not isinstance(conversation_item, dict) or conversation_item.get('user_id') != user_id:
        return True
    if conversation_item.get('orchestration_deleted') or conversation_item.get('deleted'):
        return True
    if not require_private:
        return False
    # Imported here so the plain unread helpers above keep their light import graph.
    from functions_orchestration_memory import conversation_is_private

    return not conversation_is_private(conversation_item, user_id)


def mark_conversation_unread_guarded(
    container,
    conversation_id,
    user_id,
    message_id,
    planned_at,
    *,
    require_private=True,
    skip_if_read_since=None,
    max_retries=5,
):
    """Mark one assistant message unread on a conversation, under an ETag guard.

    Every attempt rereads the conversation and rechecks that it exists, belongs to ``user_id``,
    isn't being deleted and, by default, is still private, so a concurrent delete or share wins
    over the mark. ``last_updated`` is raised to at least ``planned_at`` so the conversation sorts
    with its newest message.

    ``skip_if_read_since`` is the planned time of an earlier attempt. Marking a chat read keeps its
    ``last_updated``, so a conversation that already reached that time was either marked and then
    read, or moved on without the mark; either way it is left alone.

    Returns ``(outcome, conversation)``. The outcome is one of the ``UNREAD_*`` constants and the
    conversation is the stored item when one was read. The caller invalidates any conversation
    cache after ``UNREAD_MARKED``. Storage errors other than a missing item or an ETag conflict
    propagate.
    """
    # An empty user id must never match a conversation that has no owner, so every id is required.
    required = (conversation_id, user_id, message_id, planned_at)
    if not all(isinstance(value, str) and value for value in required):
        raise ValueError('An unread mark needs a conversation id, a user id, a message id and a planned time.')
    attempts = max(1, int(max_retries) + 1)
    conversation_item = None
    for _attempt in range(attempts):
        try:
            conversation_item = container.read_item(item=conversation_id, partition_key=conversation_id)
        except exceptions.CosmosResourceNotFoundError:
            return UNREAD_NOT_FOUND, None
        if _conversation_unavailable(conversation_item, user_id, require_private):
            return UNREAD_UNAVAILABLE, conversation_item
        if conversation_item.get('last_unread_assistant_message_id') == message_id:
            return UNREAD_ALREADY_MARKED, conversation_item
        if skip_if_read_since is not None and _reached(conversation_item.get('last_updated'), skip_if_read_since):
            return UNREAD_READ_SINCE, conversation_item

        candidate = dict(conversation_item)
        if not _reached(candidate.get('last_updated'), planned_at):
            candidate['last_updated'] = planned_at
        candidate = mark_conversation_unread(candidate, message_id, planned_at)
        try:
            stored = container.replace_item(
                item=conversation_id,
                body=candidate,
                etag=conversation_item.get('_etag'),
                match_condition=MatchConditions.IfNotModified,
            )
        except exceptions.CosmosResourceNotFoundError:
            return UNREAD_NOT_FOUND, None
        except exceptions.CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
            continue
        return UNREAD_MARKED, stored if isinstance(stored, dict) else candidate
    return UNREAD_CONFLICT, conversation_item
