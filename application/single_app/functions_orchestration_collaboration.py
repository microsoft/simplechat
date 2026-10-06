# functions_orchestration_collaboration.py
"""Orchestrate in a shared conversation.

Version: 0.261.269
Implemented in: 0.261.269

A shared conversation's plans run in a hidden backing conversation that reuses the shared
conversation's id and belongs to the person who started it, so every plan, run, result and
answer keeps the id the browser already holds. That person's question and each run's final
answer are mirrored into the shared thread and announced to every participant, and an answer
the run republishes later updates its shared copy. Messages that only address people never
reach a plan: the composer posts them to the thread instead.

Only the person who started a shared conversation can orchestrate in it, the same person who
owns its classic assistant's hidden source conversation, and only while they still take part
in it. Other participants ask the assistant the classic way. Lookups elsewhere treat the
backing as part of the shared conversation (``collaboration_models.is_shared_conversation_backing``),
and deleting the shared conversation deletes its backing. Collaboration storage is imported on
first use rather than with this module, so importing it never initializes Cosmos clients.
"""

import logging

from collaboration_models import COLLABORATION_SOURCE_KIND, is_shared_conversation_backing
from functions_appinsights import log_event


SHARED_ORCHESTRATION_OWNER_ONLY = (
    'Only the person who started this shared conversation can use Orchestrate here. '
    'Turn off Orchestrate to ask the assistant.'
)
SHARED_ORCHESTRATION_STALE_COPY = (
    "Orchestrate can't be used in this shared conversation because an earlier version kept "
    'another participant\'s private copy of it. Turn off Orchestrate to ask the assistant.'
)
# Fields a mirrored answer takes from the run's own message; refreshed when the run republishes.
_MIRRORED_ANSWER_FIELDS = (
    'content', 'role', 'model_deployment_name', 'augmented', 'hybrid_citations',
    'web_search_citations', 'citation_tracking_version', 'cited_hybrid_citations',
    'cited_web_search_citations', 'agent_citations', 'agent_display_name', 'agent_name',
)
# Metadata the shared copy keeps from when it was first mirrored.
_MIRROR_METADATA_KEPT = ('source_conversation_id', 'source_thought_user_id')


class SharedOrchestrationError(PermissionError):
    """Orchestrate is not available to this participant of a shared conversation."""

    def __init__(self, message=SHARED_ORCHESTRATION_OWNER_ONLY):
        super().__init__(message)
        self.message = message


def is_orchestration_backing(conversation):
    """Whether a personal conversation record is a shared conversation's orchestration backing."""
    return is_shared_conversation_backing(conversation)


def shared_conversation(conversation_id):
    """The shared conversation with this id, or None when it is not one."""
    # Collaboration storage initializes Cosmos clients; it is imported on first use.
    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    from functions_collaboration import get_collaboration_conversation

    if not isinstance(conversation_id, str) or not conversation_id.strip():
        return None
    try:
        return get_collaboration_conversation(conversation_id)
    except CosmosResourceNotFoundError:
        return None


def authorize_shared_orchestration(collaboration, user_id):
    """Require a current participant who started the conversation; return the backing fields."""
    from functions_collaboration import (
        assert_user_can_participate_in_collaboration_conversation,
        is_group_collaboration_conversation,
    )

    assert_user_can_participate_in_collaboration_conversation(user_id, collaboration)
    if str(collaboration.get('created_by_user_id') or '').strip() != str(user_id or '').strip():
        raise SharedOrchestrationError()
    return {
        'conversation_kind': COLLABORATION_SOURCE_KIND,
        'collaboration_conversation_id': collaboration['id'],
        'is_hidden': True,
        'chat_type': 'group' if is_group_collaboration_conversation(collaboration) else 'personal_single_user',
        # The shared conversation's workspace lock applies to its plans, as it does to the
        # classic assistant's hidden source conversation.
        'context': list(collaboration.get('context') or []),
        'scope_locked': bool(collaboration.get('scope_locked', False)),
        'locked_contexts': list(collaboration.get('locked_contexts') or []),
    }


def _publish_message(collaboration, message_doc, viewer_user_id):
    from functions_collaboration import (
        create_collaboration_message_notifications,
        get_collaboration_user_state_or_none,
        publish_collaboration_event,
        serialize_collaboration_conversation,
        serialize_collaboration_message,
    )
    from collaboration_models import utc_now_iso

    create_collaboration_message_notifications(collaboration, message_doc)
    message = serialize_collaboration_message(message_doc)
    message.pop('m365_pending_actions', None)
    if isinstance(message.get('metadata'), dict):
        message['metadata'] = {
            key: value for key, value in message['metadata'].items() if key != 'm365_pending_actions'
        }
    publish_collaboration_event(collaboration['id'], {
        'conversation_id': collaboration['id'],
        'event_type': 'collaboration.message.created',
        'occurred_at': utc_now_iso(),
        'payload': {
            'conversation': serialize_collaboration_conversation(
                collaboration, current_user_id=viewer_user_id,
                user_state=get_collaboration_user_state_or_none(viewer_user_id, collaboration['id']),
            ),
            'message': message,
        },
    })


def _authorized_collaboration(conversation):
    """The backing's shared conversation, while its owner may still orchestrate there.

    Rechecked on every post: someone removed from a shared conversation, or whose group no
    longer allows chat, keeps their plans' answers to themselves.
    """
    from functions_collaboration import get_collaboration_conversation

    collaboration = get_collaboration_conversation(conversation['collaboration_conversation_id'])
    authorize_shared_orchestration(collaboration, conversation.get('user_id'))
    return collaboration


def mirror_orchestration_turn(conversation, user_message, sender_user, *, details=None):
    """Post the owner's orchestrated question to the shared thread once, and announce it."""
    from functions_collaboration import (
        get_collaboration_message_by_source_message,
        persist_collaboration_message,
        resolve_collaboration_mentions,
    )
    from collaboration_models import MESSAGE_KIND_AI_REQUEST

    if not is_orchestration_backing(conversation) or not isinstance(user_message, dict):
        return None
    if str((sender_user or {}).get('user_id') or '') != str(conversation.get('user_id') or ''):
        raise SharedOrchestrationError()
    collaboration = _authorized_collaboration(conversation)
    existing = get_collaboration_message_by_source_message(collaboration['id'], user_message.get('id'))
    if existing:
        return existing
    details = details if isinstance(details, dict) else {}
    metadata = user_message.get('metadata') if isinstance(user_message.get('metadata'), dict) else {}
    extra = {
        'source_message_id': user_message['id'],
        'source_conversation_id': conversation['id'],
        'source_role': 'user',
        'orchestration_turn_id': metadata.get('orchestration_turn_id'),
        'orchestration': {'turn_id': metadata.get('orchestration_turn_id')},
    }
    if isinstance(details.get('invocation_target'), dict):
        extra['ai_invocation_target'] = details['invocation_target']
    if isinstance(metadata.get('prompt_selection'), dict):
        extra['prompt_selection'] = metadata['prompt_selection']
    message_doc, updated = persist_collaboration_message(
        collaboration, sender_user, user_message.get('content') or '',
        reply_to_message_id=details.get('reply_to_message_id') or None,
        mentioned_participants=resolve_collaboration_mentions(
            collaboration, details.get('mentioned_participants'),
        ),
        message_kind=MESSAGE_KIND_AI_REQUEST,
        extra_metadata=extra,
    )
    _publish_message(updated, message_doc, sender_user.get('user_id'))
    return message_doc


def mirror_orchestration_answer(conversation, answer, *, user_message_id=None, owner_user_id=None):
    """Post a run's final answer to the shared thread, replying to its question.

    A run republishes its answer under the same id when it finishes later, for example after a
    step that was waiting completes or the run times out. The shared copy is then updated in
    place and announced, so participants never keep the earlier text.
    """
    from functions_collaboration import (
        get_collaboration_message_by_source_message,
        mirror_source_message_to_collaboration,
    )

    if not is_orchestration_backing(conversation) or not isinstance(answer, dict):
        return None
    owner = conversation.get('user_id')
    if owner_user_id is not None and owner_user_id != owner:
        raise SharedOrchestrationError()
    collaboration = _authorized_collaboration(conversation)
    existing = get_collaboration_message_by_source_message(collaboration['id'], answer.get('id'))
    if existing:
        return _refresh_mirrored_answer(collaboration, existing, answer, owner)
    question = get_collaboration_message_by_source_message(collaboration['id'], user_message_id)
    message_doc, updated, created = mirror_source_message_to_collaboration(
        collaboration, answer, {'user_id': owner},
        reply_to_message_id=(question or {}).get('id'),
        extra_metadata={'source_conversation_id': conversation['id']},
    )
    if message_doc is None:
        return None
    if created:
        _publish_message(updated, message_doc, owner)
    return message_doc


def _refresh_mirrored_answer(collaboration, existing, answer, owner):
    """Bring an existing shared copy up to date with a republished answer, and announce it."""
    from azure.core import MatchConditions
    import functions_collaboration as collaboration_store
    from collaboration_models import build_collaboration_message_doc_from_legacy, utc_now_iso
    from functions_workflow_result_masking import (
        message_uses_workflow_result,
        withhold_workflow_result_message,
    )

    source = withhold_workflow_result_message(answer) if message_uses_workflow_result(answer) else answer
    fresh = build_collaboration_message_doc_from_legacy(collaboration['id'], source, {'user_id': owner})
    if not fresh:
        return existing
    refreshed = dict(existing)
    for field in _MIRRORED_ANSWER_FIELDS:
        if field in fresh:
            refreshed[field] = fresh[field]
        else:
            refreshed.pop(field, None)
    existing_metadata = existing.get('metadata') if isinstance(existing.get('metadata'), dict) else {}
    refreshed['metadata'] = {
        **(fresh.get('metadata') or {}),
        **{key: existing_metadata[key] for key in _MIRROR_METADATA_KEPT if key in existing_metadata},
    }

    def visible(message):
        return {
            key: value for key, value in message.items()
            if not key.startswith('_') and key in (*_MIRRORED_ANSWER_FIELDS, 'metadata')
        }

    if visible(refreshed) == visible(existing):
        return existing
    saved = collaboration_store.cosmos_collaboration_messages_container.replace_item(
        item=existing['id'], body=refreshed, etag=existing.get('_etag'),
        match_condition=MatchConditions.IfNotModified,
    )
    collaboration_store.publish_collaboration_event(collaboration['id'], {
        'conversation_id': collaboration['id'],
        'event_type': 'collaboration.message.updated',
        'occurred_at': utc_now_iso(),
        'payload': {'message': collaboration_store.serialize_collaboration_message(saved)},
    })
    return saved


def delete_orchestration_backing(
    collaboration, *, archiving_enabled, expected_user_id=None,
    conversation_container, message_container,
    archived_conversation_container=None, archived_message_container=None,
    not_found_error=None,
):
    """Delete a shared conversation's Orchestrate backing together with the shared conversation.

    Follows deleting a personal conversation: runs are fenced and their retained files enrolled
    for output cleanup, then messages, thoughts and the record are archived or deleted. A
    co-owner who didn't start the conversation removes it without deleting its creator's plans,
    as with the classic assistant's source conversation. The caller's containers, and the
    exception its container raises for a missing item, are used, and the deletion services load
    only once a backing is found. Returns the backing that was deleted, or None when there is none.
    """
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    not_found_error = not_found_error or CosmosResourceNotFoundError
    conversation_id = str((collaboration or {}).get('id') or '').strip()
    if not conversation_id:
        return None

    def read_backing():
        try:
            return conversation_container.read_item(item=conversation_id, partition_key=conversation_id)
        except not_found_error:
            return None

    backing = read_backing()
    if not is_orchestration_backing(backing):
        return None
    owner = str(backing.get('user_id') or '').strip()
    if not owner or (expected_user_id and owner != str(expected_user_id).strip()):
        return None

    # Deletion services reach application storage; they load only for a backing to delete.
    from functools import partial
    from datetime import datetime, timezone

    from azure.core import MatchConditions
    from functions_conversation_cache import invalidate_conversation_cache_for_item
    from functions_orchestration_artifacts import is_retained_orchestration_file
    from functions_orchestration_recovery import cleanup_conversation_checkpoints
    from functions_saved_analysis import cleanup_chat_analysis_conversation
    from functions_simplechat_operations import delete_blob_backed_chat_message_files
    from functions_thoughts import archive_thoughts_for_conversation, delete_thoughts_for_conversation

    if archiving_enabled and (archived_conversation_container is None or archived_message_container is None):
        raise ValueError('Archiving a shared conversation backing needs its archive containers.')

    def authorize():
        current = read_backing()
        return is_orchestration_backing(current) and current.get('user_id') == owner

    cleanup_conversation_checkpoints(
        conversation_id, owner, authorize,
        message_container=message_container,
        conversation_container=conversation_container,
        output_cleanup=partial(_enroll_backing_outputs, owner, conversation_id),
        retain_committed=archiving_enabled,
    )
    messages = list(message_container.query_items(
        query='SELECT * FROM c WHERE c.conversation_id = @conversation_id',
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        partition_key=conversation_id,
    ))
    cleanup_chat_analysis_conversation(conversation_id, owner, messages)
    direct_messages = [message for message in messages if not is_retained_orchestration_file(message)]
    if not archiving_enabled:
        delete_blob_backed_chat_message_files(direct_messages, conversation=backing)
    archived_at = datetime.now(timezone.utc).isoformat()
    direct_message_ids = {message['id'] for message in direct_messages}
    for message in messages:
        if archiving_enabled:
            archived_message_container.upsert_item({**message, 'archived_at': archived_at})
        if message['id'] not in direct_message_ids:
            continue
        try:
            message_container.delete_item(message['id'], partition_key=conversation_id)
        except not_found_error:
            pass
    if archiving_enabled:
        archive_thoughts_for_conversation(conversation_id, owner)
        archived_conversation_container.upsert_item({**backing, 'archived_at': archived_at})
    else:
        delete_thoughts_for_conversation(conversation_id, owner)
    current = read_backing()
    if current is not None:
        # Conditional, so a backing that changed after cleanup is left for a retry.
        conversation_container.delete_item(
            item=conversation_id, partition_key=conversation_id,
            etag=current.get('_etag'), match_condition=MatchConditions.IfNotModified,
        )
    invalidate_conversation_cache_for_item(backing, reason='orchestration_backing_deleted')
    return backing


def _enroll_backing_outputs(user_id, conversation_id, run_id):
    """Initialize deletion-only output cleanup for one of the backing's runs."""
    from functions_orchestration_bootstrap import build_orchestration_cleanup_service

    return build_orchestration_cleanup_service(user_id, conversation_id).enroll_run_cleanup(run_id)


def log_mirror_failure(stage, error):
    """A mirror failure leaves the run's own record intact; log it without content."""
    log_event(
        '[ORCHESTRATION_COLLABORATION] A shared conversation message was not mirrored.',
        level=logging.WARNING, extra={'stage': stage, 'error_type': type(error).__name__},
    )
