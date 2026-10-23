# functions_conversation_handoff_runtime.py
"""Bind handoff storage and policy only after web/scheduler bootstrap completes."""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging

from functions_conversation_handoffs import (
    ConversationHandoffError, ConversationHandoffService, ConversationHandoffStore,
    digest, held_destination,
)
from functions_conversation_references import normalize_conversation_references


def _validate_approval(job):
    # The orchestration owner verifies persisted approved scope, not caller assertions.
    from functions_orchestration_conversation_capabilities import validate_conversation_send_approval

    return validate_conversation_send_approval(
        job['user_id'], job['source_conversation_id'], job['destination_conversation_id'],
        job['instruction'], job['conversation_references'], job['approval'],
    )


def _mark_unread(job):
    # Storage/settings must already have been initialized by the owning process.
    from config import cosmos_conversations_container
    from functions_conversation_unread import mark_conversation_unread_guarded
    from functions_conversation_cache import bump_conversation_cache_version

    timestamp = datetime.fromtimestamp(job['updated_at'], timezone.utc).isoformat()
    outcome, _ = mark_conversation_unread_guarded(
        cosmos_conversations_container, job['destination_conversation_id'], job['user_id'],
        job['destination_message_id'], timestamp,
    )
    if outcome not in ('marked', 'already_marked', 'read_since'):
        raise ConversationHandoffError('destination_unavailable', 'The destination is no longer available.')
    bump_conversation_cache_version(job['user_id'], reason='conversation_handoff')


def get_handoff_service():
    # Deferred by design: config initializes Cosmos; reference runtime binds screening.
    from config import cosmos_conversation_handoffs_container
    from functions_conversation_reference_runtime import authorize_private_conversation, resolve_conversation_references
    from functions_conversation_handoff_generation import generate_handoff_turn, resolve_handoff_destination

    return ConversationHandoffService(
        ConversationHandoffStore(cosmos_conversation_handoffs_container),
        authorize=authorize_private_conversation, normalize_references=normalize_conversation_references,
        resolve_references=resolve_conversation_references, resolve_destination=resolve_handoff_destination,
        generate=generate_handoff_turn, validate_approval=_validate_approval, mark_unread=_mark_unread,
    )


def enqueue_conversation_handoff(user_id, source_conversation_id, destination_conversation_id, instruction,
                                 *, references=None, request_id=None, approval=None, origin=None,
                                 destination_config_revision=None):
    return get_handoff_service().enqueue(
        user_id, source_conversation_id, destination_conversation_id, instruction,
        references=references, request_id=request_id, approval=approval, origin=origin,
        destination_config_revision=destination_config_revision,
    )


def acquire_destination(user_id, conversation_id, owner_id, *, kind='chat'):
    return get_handoff_service().store.acquire(user_id, conversation_id, owner_id, kind=kind)


def release_destination(lease):
    lease.close()


def heartbeat_destination(lease):
    lease.store.heartbeat(lease)


@contextmanager
def destination_execution(user_id, conversation_id, owner_id, *, kind='orchestration'):
    with held_destination(get_handoff_service().store, user_id, conversation_id, owner_id, kind=kind) as lease:
        yield lease


def dispatch_conversation_handoffs_once(limit=8):
    service = get_handoff_service()
    rows = service.store.container.query_items(
        query='SELECT TOP @limit c.destination_conversation_id FROM c WHERE c.kind = @kind AND ARRAY_LENGTH(c.queue) > 0',
        parameters=[{'name': '@limit', 'value': max(1, min(int(limit), 32))}, {'name': '@kind', 'value': 'admission'}],
        enable_cross_partition_query=True,
    )
    outcomes = []
    for row in rows:
        try:
            outcomes.append(service.dispatch(row['destination_conversation_id']))
        except Exception as error:
            # Avoid importing the logging/bootstrap owner until runtime execution.
            from functions_appinsights import log_event

            log_event('[CONVERSATION_HANDOFF] Dispatch could not complete.', level=logging.ERROR,
                      extra={'error_type': type(error).__name__})
    return outcomes
