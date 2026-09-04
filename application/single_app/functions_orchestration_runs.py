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

Version: 0.261.085
"""

import logging
from datetime import datetime, timezone

from azure.cosmos import exceptions

from config import (
    cosmos_orchestration_run_steps_container,
    cosmos_orchestration_runs_container,
)
from functions_appinsights import log_event
from functions_orchestration_schema import (
    PLAN_STATUS_DRAFT,
    new_run_id,
    new_step_id,
    summarize_plan,
)

_LOG_PREFIX = '[ORCHESTRATION_RUNS]'


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


# --------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------

def create_orchestration_run(
    plan,
    user_id,
    conversation_id=None,
    turn_index=None,
    request_fingerprint=None,
):
    """Persist a new run record for a validated plan.

    The run's ``id`` is the plan's ``run_id`` so the two never drift, and ``turn_index`` is
    resolved from the conversation when the caller does not supply one -- the ordering that
    the ledger and the map view rely on has to be assigned somewhere, and assigning it at
    creation keeps it monotonic without the route having to track a counter.
    """
    plan = plan if isinstance(plan, dict) else {}
    conversation_id = conversation_id or plan.get('conversation_id')
    if not conversation_id:
        raise ValueError('conversation_id is required to create an orchestration run')
    if not user_id:
        raise ValueError('user_id is required to create an orchestration run')

    run_id = plan.get('run_id') or new_run_id()
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

    try:
        cosmos_orchestration_runs_container.upsert_item(body=record)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Failed to create run {run_id}: {exc}',
            extra={'conversation_id': conversation_id, 'user_id': user_id, 'run_id': run_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise

    return _strip_cosmos_metadata(record)


def get_orchestration_run(run_id, user_id, conversation_id=None):
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
        return None

    if not item:
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


def update_orchestration_run(run_id, user_id, updates, conversation_id=None):
    """Apply a partial update to an owned run and persist it.

    Reads through :func:`get_orchestration_run` first so the ownership check is never
    bypassed by an update path, and refuses to rewrite the identity/partition fields, since
    changing ``conversation_id`` or ``user_id`` on an existing item would move it or reassign
    it rather than update it.
    """
    existing = get_orchestration_run(run_id, user_id, conversation_id=conversation_id)
    if not existing:
        return None

    updates = updates if isinstance(updates, dict) else {}
    protected = {'id', 'run_id', 'conversation_id', 'user_id', 'created_at'}
    for key, value in updates.items():
        if key in protected:
            continue
        existing[key] = value

    # If the plan document itself was replaced (a re-plan), keep the denormalised summary and
    # capability list in step with it rather than letting the ledger read a stale summary.
    if isinstance(updates.get('plan'), dict):
        summary = summarize_plan(updates['plan'])
        existing['plan_summary'] = summary
        existing['capabilities_used'] = list((summary or {}).get('capabilities_used') or [])

    existing['updated_at'] = _utc_now_iso()

    try:
        result = cosmos_orchestration_runs_container.upsert_item(body=existing)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Failed to update run {run_id}: {exc}',
            extra={'user_id': user_id, 'run_id': run_id},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise

    return _strip_cosmos_metadata(result)


def list_conversation_runs(conversation_id, user_id, limit=10):
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
            query='SELECT * FROM c WHERE c.user_id = @user_id ORDER BY c.turn_index DESC',
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
        return []

    trimmed = items[:limit]
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
            query='SELECT VALUE MAX(c.turn_index) FROM c WHERE c.user_id = @user_id',
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


def list_run_steps(run_id, user_id=None, conversation_id=None):
    """Steps of a run in execution order.

    Steps carry only ``run_id``, so ownership can only be proven through the parent run. When
    a ``user_id`` is supplied the run is checked first and an unowned run yields no steps;
    the executor, which already holds the run it is writing, may omit it.
    """
    if not run_id:
        return []

    if user_id is not None and not get_orchestration_run(
        run_id, user_id, conversation_id=conversation_id
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
        return []

    return [_strip_cosmos_metadata(item) for item in items]
