# functions_orchestration_runs.py

"""
Cosmos persistence for orchestration runs and their steps.

A run is one turn's plan and everything that happened when it executed. The two containers
are split the way the reads are: a run is read by its conversation (the ledger and the map
view both walk a conversation's runs in order), so runs are partitioned by
``/conversation_id``; a step is only ever read as part of its run, so steps are partitioned
by ``/run_id``. Point-reading a run therefore needs its conversation, and the helpers here
accept it wherever the caller has it and fall back to a cross-partition lookup by id when it
does not.

**Ownership is enforced on every read, not assumed.** These records name documents a user
was allowed to see at plan time and can carry an answer synthesised from them, so handing
one user another user's run would leak both. Cosmos partitioning alone does not prevent that
-- a guessed ``run_id`` with the wrong ``conversation_id`` would still resolve through the
cross-partition path -- so every read compares ``user_id`` and returns nothing on a mismatch
rather than trusting the key.

Shaped and styled after ``functions_personal_workflows.py`` so the run/step CRUD reads the
same as the workflow-run CRUD it sits beside.

Version: 0.261.104
"""

import hashlib
import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.cosmos import exceptions

from config import (
    cosmos_orchestration_run_steps_container,
    cosmos_orchestration_runs_container,
)
from functions_appinsights import log_event
from functions_orchestration_context import ConversationContextError, LEDGER_MAX_ANSWERED_QUESTIONS
from functions_orchestration_schema import (
    PLAN_STATUS_DRAFT,
    new_run_id,
    new_step_id,
    summarize_plan,
    safe_failure,
)

_LOG_PREFIX = '[ORCHESTRATION_RUNS]'
RUN_RECORD_TYPE = 'run'
PENDING_ELICITATION_RECORD_TYPE = 'pending_elicitation'
ELICITATION_CLAIM_SECONDS = 900
ELICITATION_RETAINED_SUBMISSIONS = 12
PENDING_TURN_PREFIX = 'oturn_'
PENDING_TURN_MAX_BYTES = 65536
RUN_RECORD_FILTER = (
    '(NOT IS_DEFINED(c.record_type) OR c.record_type = "run" '
    'OR c.record_type = "orchestration_run") '
    'AND NOT IS_DEFINED(c.superseded_by_run_id) '
    'AND (NOT IS_DEFINED(c.status) OR c.status != "superseded")'
)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _strip_cosmos_metadata(document):
    if not isinstance(document, dict):
        return {}
    return {key: value for key, value in document.items() if not str(key).startswith('_')}


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_run_record(document):
    return isinstance(document, dict) and document.get('record_type') in (
        None, RUN_RECORD_TYPE, 'orchestration_run',
    )


def _is_current_run_record(document):
    return (
        _is_run_record(document) and 'superseded_by_run_id' not in document
        and document.get('status') != 'superseded'
    )


def _pending_turn_id(conversation_id, user_id, turn_id):
    if not conversation_id or not user_id or not turn_id:
        raise ValueError('Conversation, user, and turn IDs are required.')
    identity = json.dumps([conversation_id, user_id, turn_id], separators=(',', ':'))
    return f'{PENDING_TURN_PREFIX}{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}'


def get_pending_turn_context(conversation_id, user_id, turn_id):
    """Read private clarification state without making it an executable or displayed run."""
    pending = get_pending_elicitation(user_id, conversation_id, turn_id)
    if pending:
        if pending.get('status') == 'completed':
            return None
        context = pending['turn_context']
        return {
            **pending,
            'revision': pending['question']['revision'],
            'user_message': context['user_message'],
            'conversation_context': context.get('conversation_context'),
            'answered_questions': context.get('answered_questions') or [],
            'elicitation': pending['question'],
            'planning_token_usage': context.get('planning_token_usage') or {},
        }
    item_id = _pending_turn_id(conversation_id, user_id, turn_id)
    try:
        item = cosmos_orchestration_runs_container.read_item(
            item=item_id, partition_key=conversation_id
        )
    except exceptions.CosmosResourceNotFoundError:
        return None
    if (
        item.get('record_type') != 'pending_turn'
        or item.get('user_id') != user_id
        or item.get('conversation_id') != conversation_id
        or item.get('turn_id') != turn_id
    ):
        raise ConversationContextError('The pending clarification could not be opened.')
    return item


def save_pending_turn_context(
    conversation_id, user_id, turn_id, *, user_message, snapshot,
    answered_questions, elicitation, planning_token_usage, expected_pending=None,
):
    existing = get_pending_turn_context(conversation_id, user_id, turn_id)
    if (
        (existing is None) != (expected_pending is None)
        or (
            existing is not None
            and (
                existing['id'] != expected_pending.get('id')
                or existing['_etag'] != expected_pending.get('_etag')
            )
        )
    ):
        raise ConversationContextError('The clarification changed while planning. Please retry.')
    if existing and existing.get('record_type') != 'pending_turn':
        raise ConversationContextError('Submit the answer through the authoritative question state.')
    revision = _coerce_int(elicitation.get('revision'), 0)
    if existing and revision < _coerce_int(existing.get('revision'), 0):
        raise ConversationContextError('A newer clarification is already available.')
    now = _utc_now_iso()
    record = {
        'id': _pending_turn_id(conversation_id, user_id, turn_id),
        'record_type': 'pending_turn',
        'conversation_id': conversation_id,
        'user_id': user_id,
        'turn_id': turn_id,
        'revision': revision,
        'user_message': user_message,
        'conversation_context': snapshot,
        'answered_questions': answered_questions,
        'elicitation': elicitation,
        'planning_token_usage': planning_token_usage,
        'created_at': existing['created_at'] if existing else now,
        'updated_at': now,
    }
    if (
        len(answered_questions) > LEDGER_MAX_ANSWERED_QUESTIONS
        or len(json.dumps(record, ensure_ascii=False).encode('utf-8')) > PENDING_TURN_MAX_BYTES
    ):
        raise ConversationContextError('The clarified request is too large. Start a new request.')
    try:
        if existing:
            cosmos_orchestration_runs_container.replace_item(
                item=existing['id'], body=record, etag=existing['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
        else:
            cosmos_orchestration_runs_container.create_item(body=record)
    except (exceptions.CosmosResourceExistsError, exceptions.CosmosAccessConditionFailedError) as exc:
        raise ConversationContextError('The clarification changed. Please retry.') from exc


def clear_pending_turn_context(record, user_id):
    if not record or record.get('record_type') != 'pending_turn' or record.get('user_id') != user_id:
        raise ConversationContextError('The pending clarification could not be cleared.')
    try:
        cosmos_orchestration_runs_container.delete_item(
            item=record['id'], partition_key=record['conversation_id'],
            etag=record['_etag'], match_condition=MatchConditions.IfNotModified,
        )
    except exceptions.CosmosResourceNotFoundError:
        return
    except exceptions.CosmosAccessConditionFailedError:
        log_event(
            f'{_LOG_PREFIX} Kept a newer pending clarification after a plan was saved.',
            level=logging.INFO,
        )


# --------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------

def create_orchestration_run(
    plan,
    user_id,
    conversation_id=None,
    turn_index=None,
    request_fingerprint=None,
    initial_updates=None,
    idempotent=False,
    turn_context=None,
    expected_previous_run=None,
):
    """Persist a new run record for a validated plan.

    The run's ``id`` is the plan's ``run_id`` so the two never drift, and ``turn_index`` is
    resolved from the conversation when the caller does not supply one -- the ordering that
    the ledger and the map view rely on has to be assigned somewhere, and assigning it at
    creation keeps it monotonic without the route having to track a counter.

    ``expected_previous_run`` is the owned raw record observed before ordinary replanning.
    It makes publication conditional on that unstarted plan remaining unchanged.
    """
    plan = plan if isinstance(plan, dict) else {}
    conversation_id = conversation_id or plan.get('conversation_id')
    if not conversation_id:
        raise ValueError('conversation_id is required to create an orchestration run')
    if not user_id:
        raise ValueError('user_id is required to create an orchestration run')

    run_id = plan.get('run_id') or new_run_id()
    if str(run_id).startswith((PENDING_TURN_PREFIX, 'elicitation_')):
        raise ValueError('The plan uses a reserved run ID.')
    if expected_previous_run is not None:
        if (
            not _is_run_record(expected_previous_run)
            or expected_previous_run.get('user_id') != user_id
            or expected_previous_run.get('conversation_id') != conversation_id
            or not expected_previous_run.get('_etag')
            or not expected_previous_run.get('id')
        ):
            raise ConversationContextError('The previous plan could not be matched to this turn.')
        if turn_index is None:
            turn_index = expected_previous_run.get('turn_index', 0)
    if turn_index is None:
        turn_index = next_turn_index(conversation_id, user_id)

    now = _utc_now_iso()
    summary = summarize_plan(plan)
    approval_source = plan.get('approval') if isinstance(plan.get('approval'), dict) else {}
    approval = {
        'mode': approval_source.get('mode'),
        'state': approval_source.get('state'),
        'approved_at': approval_source.get('approved_at'),
        'approved_by': approval_source.get('approved_by'),
        'edited': bool(approval_source.get('edited', False)),
    }

    record = {
        'id': run_id,
        'record_type': RUN_RECORD_TYPE,
        'run_id': run_id,
        'conversation_id': conversation_id,
        'user_id': user_id,
        'turn_index': _coerce_int(turn_index, 0),
        'plan': plan,
        'plan_summary': summary,
        'status': plan.get('status') or PLAN_STATUS_DRAFT,
        'created_at': now,
        'started_at': None,
        'completed_at': None,
        'error': None,
        'approval': approval,
        'request_fingerprint': request_fingerprint or plan.get('request_fingerprint'),
        'revision': _coerce_int(plan.get('revision'), 0),
        'capabilities_used': list((summary or {}).get('capabilities_used') or []),
        'documents_touched': [],
        'artifacts': [],
        'token_usage': {},
        # Read back into the planner's ledger; present from creation so a run that is read
        # before it finishes does not look malformed to the ledger builder.
        'unresolved': [],
        'answered_questions': [],
    }
    for key in (
        'user_message', 'user_message_id', 'user_message_fingerprint', 'turn_id', 'seeds',
        'answered_questions', 'conversation_context', 'request_resolution',
        'resolved_message', 'planning_token_usage', 'original_seeds', 'prompt_selection',
        'memory_audience', 'memory_scope',
    ):
        if isinstance(turn_context, dict) and key in turn_context:
            record[key] = turn_context[key]
    protected = {'id', 'record_type', 'run_id', 'conversation_id', 'user_id', 'created_at'}
    record.update({
        key: value for key, value in (initial_updates or {}).items()
        if key not in protected
    })

    try:
        if expected_previous_run is not None:
            record = _publish_replanned_run(
                record, expected_previous_run, idempotent=idempotent,
            )
        elif idempotent:
            try:
                cosmos_orchestration_runs_container.create_item(body=record)
            except exceptions.CosmosResourceExistsError:
                existing = get_orchestration_run(run_id, user_id, conversation_id)
                if not existing or existing.get('turn_id') != record.get('turn_id'):
                    raise ValueError('The saved plan could not be matched to this turn.')
                return existing
        else:
            cosmos_orchestration_runs_container.upsert_item(body=record)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Failed to create run.',
            extra={
                'conversation_id': conversation_id, 'user_id': user_id, 'run_id': run_id,
                'exception_type': type(exc).__name__,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise

    return _strip_cosmos_metadata(record)


def _replanned_outcome(record, previous):
    """Replay only a matching owned run, never a guessed or unrelated result ID."""
    if (
        not _is_run_record(previous)
        or previous.get('user_id') != record['user_id']
        or previous.get('conversation_id') != record['conversation_id']
        or previous.get('turn_id') != record.get('turn_id')
    ):
        raise ConversationContextError('The saved plan could not be matched to this turn.')
    if previous['id'] == record['id']:
        existing = previous
    elif previous.get('superseded_by_run_id') == record['id']:
        existing = cosmos_orchestration_runs_container.read_item(
            item=record['id'], partition_key=record['conversation_id'],
        )
        if (
            existing.get('parent_run_id') != previous['id']
            or existing.get('revision_root_run_id')
            != (previous.get('revision_root_run_id') or previous['id'])
        ):
            raise ConversationContextError('The saved plan could not be matched to this turn.')
    else:
        return None
    if (
        not _is_run_record(existing)
        or existing.get('id') != record['id']
        or existing.get('user_id') != record['user_id']
        or existing.get('conversation_id') != record['conversation_id']
        or existing.get('turn_id') != record.get('turn_id')
        or (existing.get('plan') or {}).get('plan_id') != record['plan'].get('plan_id')
        or existing.get('revision') != record.get('revision')
    ):
        raise ConversationContextError('The saved plan could not be matched to this turn.')
    return existing


def _publish_replanned_run(record, expected_previous_run, *, idempotent=False):
    """An ordinary replan must also lose to an editor hold or execution claim."""
    previous = cosmos_orchestration_runs_container.read_item(
        item=expected_previous_run['id'], partition_key=record['conversation_id'],
    )
    if idempotent:
        replay = _replanned_outcome(record, previous)
        if replay is not None:
            return replay
    if (
        not _is_current_run_record(previous)
        or previous.get('user_id') != record['user_id']
        or previous.get('conversation_id') != record['conversation_id']
        or previous.get('turn_id') != record.get('turn_id')
        or previous.get('_etag') != expected_previous_run['_etag']
        or previous.get('status') not in ('draft', 'awaiting_approval', 'approved')
        or previous.get('started_at') or previous.get('edit_version')
        or (previous.get('plan') or {}).get('edit_version')
        or previous['id'] == record['id']
        or _coerce_int(record.get('revision')) <= _coerce_int(previous.get('revision'))
    ):
        raise ConversationContextError('The plan changed while planning. Reload the latest plan.')
    for key in (
        'user_message', 'user_message_id', 'user_message_fingerprint', 'turn_id',
        'original_seeds', 'conversation_context', 'snapshot', 'request_fingerprint',
    ):
        if key in previous:
            record[key] = deepcopy(previous[key])
    record['turn_index'] = previous.get('turn_index', 0)
    record['revision_root_run_id'] = previous.get('revision_root_run_id') or previous['id']
    record['parent_run_id'] = previous['id']
    record['revision_origin'] = 'ai'
    record['revision_note'] = 'Plan regenerated.'
    predecessor = deepcopy(_strip_cosmos_metadata(previous))
    predecessor.update({
        'status': 'superseded', 'superseded_by_run_id': record['id'],
        'revision_root_run_id': record['revision_root_run_id'],
        'superseded_at': _utc_now_iso(), 'updated_at': _utc_now_iso(),
    })
    try:
        cosmos_orchestration_runs_container.execute_item_batch(
            batch_operations=[
                ('replace', (previous['id'], predecessor), {'if_match_etag': previous['_etag']}),
                ('create', (record,)),
            ],
            partition_key=record['conversation_id'],
        )
    except (exceptions.CosmosBatchOperationError, exceptions.CosmosHttpResponseError) as exc:
        if exc.status_code in (404, 409, 412):
            if idempotent:
                latest = cosmos_orchestration_runs_container.read_item(
                    item=previous['id'], partition_key=record['conversation_id'],
                )
                replay = _replanned_outcome(record, latest)
                if replay is not None:
                    return replay
            raise ConversationContextError(
                'The plan changed while planning. Reload the latest plan.'
            ) from exc
        raise
    return record


def get_orchestration_run(run_id, user_id, conversation_id=None, *, strict=False):
    """Fetch one run, returning ``None`` unless it exists and belongs to ``user_id``.

    A ``conversation_id`` turns this into a point read; without one it is a cross-partition
    query by id, which the caller pays for only when it has genuinely lost the conversation.
    Either way the ownership check is the same, because the cross-partition path is exactly
    where a wrong owner could otherwise slip through.
    """
    if not run_id or not user_id:
        return None

    try:
        if conversation_id:
            item = cosmos_orchestration_runs_container.read_item(
                item=run_id,
                partition_key=conversation_id,
            )
        else:
            results = list(cosmos_orchestration_runs_container.query_items(
                query='SELECT * FROM c WHERE c.id = @run_id',
                parameters=[{'name': '@run_id', 'value': run_id}],
                enable_cross_partition_query=True,
            ))
            item = results[0] if results else None
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Error fetching run {run_id}: {exc}',
            extra={'user_id': user_id, 'run_id': run_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        if strict:
            raise
        return None

    if not _is_run_record(item):
        return None

    if str(item.get('user_id')) != str(user_id):
        # Not an error the caller can act on, but worth a trail: an id resolved to a run the
        # requester does not own.
        log_event(
            f'{_LOG_PREFIX} Ownership mismatch reading run {run_id}; refusing.',
            extra={'user_id': user_id, 'run_id': run_id},
            level=logging.WARNING,
        )
        return None

    return _strip_cosmos_metadata(item)


def get_latest_turn_run(conversation_id, user_id, turn_id):
    """Find an owned turn's last plan without conflating a read failure with a new turn."""
    if not conversation_id or not user_id or not turn_id:
        raise ValueError('Conversation, user, and turn IDs are required.')
    rows = list(cosmos_orchestration_runs_container.query_items(
        query=(
            'SELECT TOP 1 * FROM c WHERE c.conversation_id = @conversation_id '
            f'AND c.user_id = @user_id AND c.turn_id = @turn_id AND {RUN_RECORD_FILTER} '
            'ORDER BY c.created_at DESC'
        ),
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
            {'name': '@user_id', 'value': user_id},
            {'name': '@turn_id', 'value': turn_id},
        ],
        partition_key=conversation_id,
    ))
    current = [
        row for row in rows if _is_current_run_record(row)
        and row.get('conversation_id') == conversation_id
        and row.get('user_id') == user_id and row.get('turn_id') == turn_id
    ]
    return _strip_cosmos_metadata(current[0]) if current else None


def update_orchestration_run(run_id, user_id, updates, conversation_id=None):
    """Apply a partial update to an owned run and persist it.

    Reads through :func:`get_orchestration_run` first so the ownership check is never
    bypassed by an update path, and refuses to rewrite the identity/partition fields, since
    changing ``conversation_id`` or ``user_id`` on an existing item would move it or reassign
    it rather than update it.
    """
    if not conversation_id:
        found = get_orchestration_run(run_id, user_id)
        if not found:
            return None
        conversation_id = found['conversation_id']
    protected = {'id', 'record_type', 'run_id', 'conversation_id', 'user_id', 'created_at'}
    for _ in range(8):
        try:
            current = cosmos_orchestration_runs_container.read_item(item=run_id, partition_key=conversation_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        if not _is_run_record(current) or current.get('user_id') != user_id or current.get('checkpoints_deleted'):
            return None
        existing = _strip_cosmos_metadata(deepcopy(current))
        existing.update({key: value for key, value in (updates or {}).items() if key not in protected})
        if isinstance((updates or {}).get('plan'), dict):
            summary = summarize_plan(updates['plan'])
            existing.update({'plan_summary': summary, 'capabilities_used': list(summary.get('capabilities_used') or [])})
        existing['updated_at'] = _utc_now_iso()
        try:
            result = cosmos_orchestration_runs_container.replace_item(
                item=run_id, body=existing, etag=current['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
            return _strip_cosmos_metadata(result)
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise exceptions.CosmosAccessConditionFailedError(status_code=412, message='Run changed.')


def list_conversation_runs(conversation_id, user_id, limit=10, *, strict=False):
    """A conversation's runs for this user, oldest first.

    Ordered so the ledger builder can read it as "newest last": the query pulls the most
    recent ``limit`` runs (newest first, so the cap keeps the recent ones), then reverses,
    because trimming an oldest-first list would have thrown away the very runs a follow-up
    question is usually about.
    """
    if not conversation_id or not user_id:
        return []

    limit = _coerce_int(limit, 10)
    limit = max(1, min(limit, 200))

    try:
        items = list(cosmos_orchestration_runs_container.query_items(
            query=(
                f'SELECT TOP {limit} * FROM c WHERE c.user_id = @user_id AND {RUN_RECORD_FILTER} '
                'ORDER BY c.turn_index DESC'
            ),
            parameters=[{'name': '@user_id', 'value': user_id}],
            partition_key=conversation_id,
        ))
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Error listing runs for conversation {conversation_id}: {exc}',
            extra={'conversation_id': conversation_id, 'user_id': user_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        if strict:
            raise
        return []

    trimmed = [
        item for item in items if _is_current_run_record(item)
        and item.get('user_id') == user_id and item.get('conversation_id') == conversation_id
    ][:limit]
    trimmed.reverse()
    return [_strip_cosmos_metadata(item) for item in trimmed]


def next_turn_index(conversation_id, user_id):
    """The next ordering index for a new run in this conversation.

    Derived from the stored maximum rather than a count, so a deleted or superseded run in
    the middle of a conversation does not cause a new run to collide with an existing index.
    """
    if not conversation_id or not user_id:
        return 0

    try:
        rows = list(cosmos_orchestration_runs_container.query_items(
            query=f'SELECT VALUE MAX(c.turn_index) FROM c WHERE c.user_id = @user_id AND {RUN_RECORD_FILTER}',
            parameters=[{'name': '@user_id', 'value': user_id}],
            partition_key=conversation_id,
        ))
    except exceptions.CosmosResourceNotFoundError:
        return 0
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Error resolving next turn index for {conversation_id}: {exc}',
            extra={'conversation_id': conversation_id, 'user_id': user_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return 0

    highest = rows[0] if rows else None
    if highest is None:
        return 0
    return _coerce_int(highest, -1) + 1


# --------------------------------------------------------------------------------------
# Pending questions (not runnable plans)
# --------------------------------------------------------------------------------------

class ElicitationStateError(ValueError):
    """A recoverable, user-safe error at the authoritative question boundary."""

    def __init__(self, message, code='elicitation_expired', status_code=409):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _pending_id(user_id, turn_id):
    identity = f'{user_id}\0{turn_id}'.encode('utf-8')
    return f'elicitation_{hashlib.sha256(identity).hexdigest()}'


def get_pending_elicitation(user_id, conversation_id, turn_id):
    """Point-read one owner's turn. Keep the ETag private for conditional transitions."""
    if not user_id or not conversation_id or not turn_id:
        return None
    try:
        record = cosmos_orchestration_runs_container.read_item(
            item=_pending_id(user_id, turn_id),
            partition_key=conversation_id,
        )
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Pending question could not be read.',
            extra={'exception_type': type(exc).__name__},
            level=logging.ERROR,
        )
        raise ElicitationStateError(
            'The question could not be loaded. Please retry.',
            code='elicitation_unavailable', status_code=503,
        ) from exc
    if (
        record.get('record_type') != PENDING_ELICITATION_RECORD_TYPE
        or record.get('user_id') != user_id
        or record.get('conversation_id') != conversation_id
        or record.get('turn_id') != turn_id
    ):
        return None
    return record


def create_pending_elicitation(
    question, turn_context, user_id, conversation_id, turn_id, *, expected_pending=None,
):
    """Persist an initial question exactly once; concurrent planning cannot replace it."""
    record = {
        'id': _pending_id(user_id, turn_id),
        'record_type': PENDING_ELICITATION_RECORD_TYPE,
        'user_id': user_id,
        'conversation_id': conversation_id,
        'turn_id': turn_id,
        'question': deepcopy(question),
        'turn_context': deepcopy(turn_context),
        'status': 'pending',
        'created_at': _utc_now_iso(),
        'submissions': [],
        'claim': None,
        'prepared': None,
    }
    try:
        return cosmos_orchestration_runs_container.create_item(body=record)
    except exceptions.CosmosResourceExistsError:
        existing = get_pending_elicitation(user_id, conversation_id, turn_id)
        if existing:
            if expected_pending and expected_pending.get('status') == 'completed':
                if existing.get('_etag') != expected_pending.get('_etag'):
                    raise ElicitationStateError('This turn changed while planning. Please retry.')
                return _replace_pending(existing, {
                    'question': deepcopy(question),
                    'turn_context': deepcopy(turn_context),
                    'status': 'pending',
                    'claim': None,
                    'prepared': None,
                })
            if existing['turn_context']['user_message'] != turn_context['user_message']:
                raise ElicitationStateError('This turn changed. Please submit a new request.')
            return existing
        raise ElicitationStateError('This question has expired. Please send the request again.')


def _replace_pending(record, updates):
    if not record.get('_etag'):
        raise ElicitationStateError(
            'The question could not be safely updated. Please retry.',
            code='elicitation_unavailable', status_code=503,
        )
    replacement = deepcopy(_strip_cosmos_metadata(record))
    replacement.update(updates)
    replacement['updated_at'] = _utc_now_iso()
    try:
        return cosmos_orchestration_runs_container.replace_item(
            item=record['id'],
            body=replacement,
            etag=record['_etag'],
            match_condition=MatchConditions.IfNotModified,
        )
    except exceptions.CosmosHttpResponseError as exc:
        if getattr(exc, 'status_code', None) in (404, 409, 412):
            raise ElicitationStateError(
                'This question changed while you were answering. Please retry or use the latest question.',
                code='elicitation_stale',
            ) from exc
        raise


def claim_elicitation_submission(
    user_id, conversation_id, turn_id, fingerprint, *,
    elicitation_id=None, revision=None, submission_id=None,
):
    """Claim a reply with CAS, or return the retained result of an identical retry."""
    record = get_pending_elicitation(user_id, conversation_id, turn_id)
    if not record:
        raise ElicitationStateError('This question has expired. Please send the request again.')

    identity_supplied = any(value is not None for value in (elicitation_id, revision, submission_id))
    if identity_supplied and (
        not isinstance(elicitation_id, str) or not elicitation_id or len(elicitation_id) > 200
        or not isinstance(revision, int) or isinstance(revision, bool) or revision < 0
        or not isinstance(submission_id, str) or not submission_id or len(submission_id) > 200
    ):
        raise ElicitationStateError(
            'The question identity is incomplete. Please use the latest question.',
            code='elicitation_identity_invalid', status_code=400,
        )

    question = record['question']
    if not identity_supplied:
        # Legacy clients can answer this one owner's pending turn, but never supply a
        # schema. A repeated legacy payload can also retrieve its last successful result.
        for completed in reversed(record.get('submissions') or []):
            if (
                completed.get('legacy') and completed.get('fingerprint') == fingerprint
                and completed.get('elicitation_id') == question['elicitation_id']
                and completed.get('revision') == question['revision']
            ):
                return {'record': record, 'outcome': completed['outcome'], 'replayed': True}
        elicitation_id = question['elicitation_id']
        revision = question['revision']
        submission_id = 'legacy_' + hashlib.sha256(
            f'{elicitation_id}:{revision}:{fingerprint}'.encode('utf-8')
        ).hexdigest()

    for completed in record.get('submissions') or []:
        if completed.get('submission_id') != submission_id:
            continue
        if (
            completed.get('fingerprint') != fingerprint
            or completed.get('elicitation_id') != elicitation_id
            or completed.get('revision') != revision
        ):
            raise ElicitationStateError(
                'That submission was already used for another answer.',
                code='elicitation_submission_conflict',
            )
        return {'record': record, 'outcome': completed['outcome'], 'replayed': True}

    if (
        record.get('status') == 'completed'
        or question.get('elicitation_id') != elicitation_id
        or question.get('revision') != revision
    ):
        raise ElicitationStateError(
            'This answer is for an older question. Please use the latest question.',
            code='elicitation_stale',
        )

    prepared = record.get('prepared')
    if prepared and (
        prepared['submission']['submission_id'] != submission_id
        or prepared['submission']['fingerprint'] != fingerprint
    ):
        raise ElicitationStateError(
            'An answer is already being saved. Retry the previous submission.',
            code='elicitation_submission_conflict',
        )

    previous_claim = record.get('claim') or {}
    if previous_claim:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(previous_claim['started_at'])).total_seconds()
        except (KeyError, TypeError, ValueError):
            elapsed = 0
        if elapsed < ELICITATION_CLAIM_SECONDS:
            raise ElicitationStateError(
                'This answer is still being processed. Please retry shortly.',
                code='elicitation_in_progress',
            )

    claim = {
        'token': uuid.uuid4().hex,
        'submission_id': submission_id,
        'elicitation_id': elicitation_id,
        'revision': revision,
        'fingerprint': fingerprint,
        'legacy': not identity_supplied,
        'started_at': _utc_now_iso(),
    }
    updated = _replace_pending(record, {'claim': claim, 'status': 'processing'})
    return {'record': updated, 'claim': claim, 'outcome': (prepared or {}).get('outcome'), 'replayed': False}


def _read_claimed_record(submission):
    record = submission['record']
    current = get_pending_elicitation(record['user_id'], record['conversation_id'], record['turn_id'])
    if not current or (current.get('claim') or {}).get('token') != submission['claim']['token']:
        raise ElicitationStateError(
            'This answer was superseded. Please retry the latest submission.',
            code='elicitation_stale',
        )
    return current


def prepare_elicitation_outcome(submission, kind, document, turn_context):
    """Durably choose IDs and output before any idempotent run/message writes."""
    current = _read_claimed_record(submission)
    outcome = {'kind': kind, 'document': deepcopy(document)}
    for key in ('memory_audience', 'memory_scope'):
        if key in turn_context:
            outcome[key] = deepcopy(turn_context[key])
    updated = _replace_pending(current, {
        'prepared': {
            'submission': deepcopy(submission['claim']),
            'outcome': outcome,
            'turn_context': deepcopy(turn_context),
        },
    })
    submission['record'] = updated
    submission['outcome'] = outcome
    return outcome


def complete_elicitation_submission(submission):
    current = _read_claimed_record(submission)
    prepared = current.get('prepared')
    if not prepared:
        raise ElicitationStateError('The answer has not finished saving. Please retry.')
    outcome = prepared['outcome']
    completed = {**prepared['submission'], 'outcome': outcome}
    updates = {
        'submissions': ((current.get('submissions') or []) + [completed])[-ELICITATION_RETAINED_SUBMISSIONS:],
        'turn_context': prepared['turn_context'],
        'status': 'pending' if outcome['kind'] == 'elicitation' else 'completed',
        'claim': None,
        'prepared': None,
    }
    if outcome['kind'] == 'elicitation':
        updates['question'] = outcome['document']
    _replace_pending(current, updates)
    return outcome


def release_elicitation_submission(submission):
    """Release only our own claim; a prepared outcome survives materialization failures."""
    if not submission or submission.get('replayed'):
        return
    try:
        current = _read_claimed_record(submission)
        _replace_pending(current, {'claim': None, 'status': 'pending'})
    except ElicitationStateError:
        return
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Pending submission could not be released.',
            extra={'exception_type': type(exc).__name__},
            level=logging.ERROR,
        )


# --------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------

def save_orchestration_step(run_id, step_record):
    """Create or update one step record for a run.

    The document id is derived as ``run_id:step_id`` so that re-emitting a step as it moves
    from running to completed upserts the same row instead of appending a second one -- the
    executor writes a step at least twice, and the map view must see one row per step, not a
    history of its states.
    """
    if not run_id:
        raise ValueError('run_id is required to save an orchestration step')

    step_record = dict(step_record) if isinstance(step_record, dict) else {}
    step_index = _coerce_int(step_record.get('step_index'), 0)
    step_id = step_record.get('step_id') or step_record.get('id') or new_step_id(step_index)

    step_record['run_id'] = run_id
    step_record['step_id'] = step_id
    step_record['step_index'] = step_index
    step_record.setdefault('id', f'{run_id}:{step_id}')
    step_record.setdefault('created_at', _utc_now_iso())
    step_record['updated_at'] = _utc_now_iso()

    try:
        result = cosmos_orchestration_run_steps_container.upsert_item(body=step_record)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Failed to save step {step_id} for run {run_id}: {exc}',
            extra={'run_id': run_id, 'step_id': step_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise

    return _strip_cosmos_metadata(result)


def list_run_steps(run_id, user_id=None, conversation_id=None, *, strict=False):
    """Steps of a run in execution order.

    Steps carry only ``run_id``, so ownership can only be proven through the parent run. When
    a ``user_id`` is supplied the run is checked first and an unowned run yields no steps;
    the executor, which already holds the run it is writing, may omit it.
    """
    if not run_id:
        return []

    if user_id is not None and not get_orchestration_run(
        run_id, user_id, conversation_id=conversation_id, strict=strict,
    ):
        return []

    try:
        items = list(cosmos_orchestration_run_steps_container.query_items(
            query='SELECT * FROM c WHERE c.run_id = @run_id ORDER BY c.step_index ASC',
            parameters=[{'name': '@run_id', 'value': run_id}],
            partition_key=run_id,
        ))
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Error listing steps for run {run_id}: {exc}',
            extra={'run_id': run_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        if strict:
            raise
        return []

    return [public_step_record(item) for item in items if item.get('record_type') in (None, 'step')]


def public_step_record(item):
    """Checkpoint chunks/manifests and future private fields never cross this boundary."""
    fields = (
        'run_id', 'step_id', 'step_index', 'capability_id', 'title', 'status',
        'started_at', 'completed_at', 'duration_ms', 'reused', 'reused_from_run_id',
        'checkpoint_available',
    )
    row = {key: deepcopy(item[key]) for key in fields if key in item}
    row['failure'] = safe_failure(item['failure']) if item.get('failure') else None
    failed = item.get('status') in ('failed', 'cancelled')
    row['summary'] = (
        (row['failure'] or {}).get('message') or 'This step did not complete.'
    ) if failed else item.get('summary') or ''
    row['error'] = row['failure']['message'] if row['failure'] else None
    return row
