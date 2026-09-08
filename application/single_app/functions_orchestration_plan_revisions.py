# functions_orchestration_plan_revisions.py
"""
Conditional pre-execution editing and execution claims for orchestration plans.

Revision publication uses a transactional batch in the conversation partition. Neither
an editor lease nor a browser approval may bypass the run's ETag boundary.

Version: 0.261.104
"""

import hashlib
import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions

import functions_orchestration_runs as run_store
from functions_appinsights import log_event
from functions_orchestration_events import merge_reasoning_adjustments
from functions_orchestration_registry import required_capability_ids
from functions_orchestration_schema import apply_plan_edits, summarize_plan


EDIT_CLAIM_SECONDS = 900
EDIT_RETAINED_SUBMISSIONS = 12
EDIT_CHAT_LIMIT = 20
EDIT_CHAT_CONTENT_LIMIT = 4000
EDIT_HISTORY_PAGE_SIZE = 20
EDIT_REQUEST_MAX_BYTES = 131072
EDIT_INSTRUCTION_LIMIT = 2000
EDIT_NOTE_LIMIT = 600

_EDITABLE_STATUSES = {'draft', 'awaiting_approval'}
_RUNNABLE_STATUSES = _EDITABLE_STATUSES | {'approved'}
_CONTEXT_FIELDS = (
    'seeds', 'answered_questions', 'request_resolution', 'resolved_message',
    'planning_token_usage', 'prompt_selection', 'edit_user_urls',
    'reasoning_adjustments', 'memory_audience', 'memory_scope',
)
_IMMUTABLE_FIELDS = (
    'user_message', 'user_message_id', 'user_message_fingerprint', 'turn_id',
    'original_seeds', 'conversation_context', 'snapshot', 'request_fingerprint',
)
_PLAN_FIELDS = (
    'plan_id', 'run_id', 'turn_id', 'revision', 'conversation_id', 'user_id',
    'planner_contract_version', 'intent', 'assumptions', 'approval', 'status',
    'steps', 'inputs', 'outputs', 'validation', 'edit_version',
)
_STEP_FIELDS = (
    'step_id', 'capability_id', 'title', 'rationale', 'arguments', 'depends_on',
    'optional', 'enabled', 'estimated_cost', 'phase', 'status',
)
_QUESTION_FIELDS = (
    'elicitation_id', 'contract_version', 'run_id', 'revision', 'message',
    'requested_schema', 'ui_hints', 'conversation_id', 'turn_id',
)
_REQUEST_FIELDS = {
    'conversation_id', 'expected_version', 'submission_id', 'action', 'edits',
}
_ACTION_FIELDS = {
    'ask': {'instruction'},
    'restore': {'source_run_id'},
    'answer': {
        'elicitation_id', 'elicitation_revision', 'elicitation_response',
        'elicitation_context',
    },
    'discard': {'elicitation_id', 'elicitation_revision'},
}


class PlanRevisionError(ValueError):
    """An actionable error whose message is safe to return to an API client."""

    def __init__(self, message, code='plan_changed', status_code=409, current_run_id=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.current_run_id = current_run_id


def _now():
    return datetime.now(timezone.utc)


def _valid_id(value):
    return (
        isinstance(value, str) and 0 < len(value) <= 200 and value == value.strip()
        and not any(
            ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF
            or character in '/\\?#' for character in value
        )
    )


def _invalid(message='Invalid plan edit request.'):
    return PlanRevisionError(message, code='invalid_request', status_code=400)


def _not_found():
    return PlanRevisionError('The plan could not be found.', code='not_found', status_code=404)


def _turn_id(record):
    return record.get('turn_id') or (record.get('plan') or {}).get('turn_id')


def _root_id(record):
    return record.get('revision_root_run_id') or record['id']


def _revision(record):
    value = record.get('revision', 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _owned_run(record, run_id, user_id, conversation_id):
    if (
        not all(_valid_id(value) for value in (run_id, user_id, conversation_id))
        or not run_store._is_run_record(record)
        or record.get('id') != run_id
        or record.get('user_id') != user_id
        or record.get('conversation_id') != conversation_id
        or not isinstance(record.get('plan'), dict)
    ):
        return False
    plan = record['plan']
    return (
        _valid_id(plan.get('plan_id')) and record.get('run_id', run_id) == run_id
        and plan.get('run_id') == run_id
        and plan.get('user_id', user_id) == user_id
        and plan.get('conversation_id', conversation_id) == conversation_id
        and (
            not record.get('turn_id') or not plan.get('turn_id')
            or record['turn_id'] == plan['turn_id']
        )
    )


def _same_lineage(left, right):
    return (
        left['user_id'] == right.get('user_id')
        and left['conversation_id'] == right.get('conversation_id')
        and _turn_id(left) == _turn_id(right)
        and _root_id(left) == _root_id(right)
    )


def read_revision_run(run_id, user_id, conversation_id, *, follow_current=False):
    """Read an owned raw run, optionally following only its own revision chain."""
    if not all(_valid_id(value) for value in (run_id, user_id, conversation_id)):
        raise _not_found()
    original = None
    previous = None
    visited = set()
    while True:
        if run_id in visited:
            raise _not_found()
        visited.add(run_id)
        try:
            record = run_store.cosmos_orchestration_runs_container.read_item(
                item=run_id, partition_key=conversation_id,
            )
        except exceptions.CosmosResourceNotFoundError as exc:
            raise _not_found() from exc
        if not _owned_run(record, run_id, user_id, conversation_id):
            raise _not_found()
        if original is not None and (
            not _same_lineage(original, record)
            or _revision(record) <= _revision(previous)
            or record.get('parent_run_id', previous['id']) != previous['id']
        ):
            raise _not_found()
        if not follow_current or 'superseded_by_run_id' not in record:
            return record
        target = record['superseded_by_run_id']
        if not _valid_id(target):
            raise _not_found()
        original = original or record
        previous = record
        run_id = target


def _changed(record):
    current_run_id = None
    if 'superseded_by_run_id' in record:
        current = read_revision_run(
            record['id'], record['user_id'], record['conversation_id'], follow_current=True,
        )
        current_run_id = current['id']
    return PlanRevisionError(
        'This plan changed. Reload the latest plan before continuing.',
        current_run_id=current_run_id,
    )


def _busy():
    return PlanRevisionError(
        'A plan edit or planner question is in progress. Finish it before continuing.',
        code='edit_in_progress',
    )


def _assert_editable(record):
    if (
        record.get('status') not in _EDITABLE_STATUSES or record.get('started_at')
        or 'superseded_by_run_id' in record
    ):
        raise _changed(record)


def _version(record):
    return record.get('edit_version') or record['plan'].get('edit_version') or ''


def _check_version(record, expected_version, *, required=False):
    current = _version(record)
    if (
        (required and not current)
        or (current and record.get('edit_version') != record['plan'].get('edit_version'))
        or (required and expected_version != current)
        or (expected_version is not None and expected_version != current)
    ):
        raise _changed(record)


def _check_plan_id(record, plan_id, *, required=False):
    if (required or plan_id is not None) and (
        not _valid_id(plan_id) or plan_id != record['plan'].get('plan_id')
    ):
        raise _changed(record)


def _json_text(value):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        size = len(text.encode('utf-8'))
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise _invalid() from exc
    if size > EDIT_REQUEST_MAX_BYTES:
        raise PlanRevisionError(
            'The plan edit request is too large.', code='request_too_large', status_code=413,
        )
    return text


def _normalize_edits(plan, edits):
    if edits is None:
        return {'disabled_step_ids': [], 'removed_document_ids': {}}
    _json_text(edits)
    if not isinstance(edits, dict) or set(edits) - {'disabled_step_ids', 'removed_document_ids'}:
        raise _invalid('Only step disabling and document removal are allowed.')
    steps = {step['step_id']: step for step in plan.get('steps') or []}
    disabled = edits.get('disabled_step_ids', [])
    removed = edits.get('removed_document_ids', {})
    if not isinstance(disabled, list) or not isinstance(removed, dict):
        raise _invalid('Invalid step or document removals.')
    if any(not _valid_id(step_id) or step_id not in steps for step_id in disabled):
        raise _invalid('Choose steps from the current plan.')
    if any(steps[step_id].get('capability_id') == 'respond' for step_id in disabled):
        raise _invalid('The final answering step cannot be disabled.')
    clean_removed = {}
    for step_id, document_ids in removed.items():
        if (
            not _valid_id(step_id) or step_id not in steps
            or not isinstance(document_ids, list)
        ):
            raise _invalid('Choose documents from the current plan.')
        arguments = steps[step_id].get('arguments') or {}
        available = {
            document_id for field in ('document_ids', 'right_document_ids')
            for document_id in arguments.get(field) or []
        }
        if any(not _valid_id(document_id) or document_id not in available for document_id in document_ids):
            raise _invalid('Choose documents from the current plan.')
        if document_ids:
            clean_removed[step_id] = list(dict.fromkeys(document_ids))
    return {
        'disabled_step_ids': list(dict.fromkeys(disabled)),
        'removed_document_ids': clean_removed,
    }


def _bounded_chat(chat):
    if not isinstance(chat, list):
        return []
    return [
        {
            'role': entry['role'],
            'content': entry['content'][:EDIT_CHAT_CONTENT_LIMIT],
            'timestamp': entry['timestamp'][:64] if isinstance(entry.get('timestamp'), str) else _now().isoformat(),
        }
        for entry in chat
        if isinstance(entry, dict) and entry.get('role') in ('user', 'assistant')
        and isinstance(entry.get('content'), str)
    ][-EDIT_CHAT_LIMIT:]


def _manual_plan(plan, version):
    result = deepcopy(plan)
    result.update(status='awaiting_approval', edit_version=version)
    result['approval'] = {
        **(result.get('approval') or {}), 'mode': 'manual', 'state': 'pending',
        'approved_at': None, 'approved_by': None,
    }
    return result


def _replace(record, updates):
    if not record.get('_etag'):
        raise _changed(record)
    replacement = deepcopy(run_store._strip_cosmos_metadata(record))
    replacement.update(deepcopy(updates))
    replacement['updated_at'] = _now().isoformat()
    try:
        result = run_store.cosmos_orchestration_runs_container.replace_item(
            item=record['id'], body=replacement, etag=record['_etag'],
            match_condition=MatchConditions.IfNotModified,
        )
    except exceptions.CosmosHttpResponseError as exc:
        if exc.status_code in (404, 409, 412):
            latest = read_revision_run(record['id'], record['user_id'], record['conversation_id'])
            raise _changed(latest) from exc
        raise
    if isinstance(result, dict) and result.get('_etag'):
        return result
    return read_revision_run(record['id'], record['user_id'], record['conversation_id'])


def begin_plan_edit(
    run_id, user_id, conversation_id, *, plan_id, edits=None, expected_version=None,
):
    """Establish a manual hold without changing the original executable steps."""
    record = read_revision_run(run_id, user_id, conversation_id)
    _assert_editable(record)
    _check_plan_id(record, plan_id, required=True)
    _check_version(record, expected_version)
    if _version(record):
        return record
    overlay = _normalize_edits(record['plan'], edits)
    version = str(uuid.uuid4())
    plan = _manual_plan(record['plan'], version)
    return _replace(record, {
        'plan': plan, 'approval': deepcopy(plan['approval']), 'status': 'awaiting_approval',
        'plan_summary': summarize_plan(plan), 'edit_version': version,
        'revision_root_run_id': _root_id(record), 'edit_narrowing': overlay,
        'edit_chat': _bounded_chat(record.get('edit_chat')),
        'edit_pending': None, 'edit_claim': None, 'edit_submissions': [], 'edit_attempts': [],
        'revision_origin': record.get('revision_origin') or 'original',
        'revision_note': record.get('revision_note') or 'Original plan.',
    })


def _claim_is_active(claim):
    if not isinstance(claim, dict) or not claim:
        return False
    try:
        started = datetime.fromisoformat(claim['started_at'])
        deadline = started + timedelta(seconds=EDIT_CLAIM_SECONDS)
        if claim.get('expires_at'):
            deadline = min(deadline, datetime.fromisoformat(claim['expires_at']))
        return _now() < deadline
    except (KeyError, TypeError, ValueError, OverflowError):
        return True


def _public_plan(plan, *, seeds=None, reasoning_adjustments=None):
    result = {key: deepcopy(plan[key]) for key in _PLAN_FIELDS if key in plan}
    result['steps'] = [
        {key: deepcopy(step[key]) for key in _STEP_FIELDS if key in step}
        for step in plan.get('steps') or []
    ]
    result['reasoning_adjustments'] = merge_reasoning_adjustments(
        plan.get('reasoning_adjustments'), reasoning_adjustments,
    )
    if not isinstance(result.get('inputs'), dict):
        result['inputs'] = {}
    if isinstance(seeds, dict):
        result['inputs']['required_capabilities'] = required_capability_ids(seeds)
    else:
        result['inputs'].setdefault('required_capabilities', [])
    return result


def plan_editor_state(record, user_id, *, before_revision=None):
    """Project only the canonical plan and bounded, owned editor conversation/history."""
    if not isinstance(record, dict) or not _owned_run(
        record, record.get('id'), user_id, record.get('conversation_id'),
    ):
        raise _not_found()
    if before_revision is not None and (
        not isinstance(before_revision, int) or isinstance(before_revision, bool)
        or before_revision < 0
    ):
        raise _invalid('Invalid history cursor.')
    parameters = [
        {'name': '@conversation_id', 'value': record['conversation_id']},
        {'name': '@user_id', 'value': user_id},
        {'name': '@turn_id', 'value': _turn_id(record)},
        {'name': '@revision_root_run_id', 'value': _root_id(record)},
    ]
    cursor_filter = ''
    if before_revision is not None:
        parameters.append({'name': '@before_revision', 'value': before_revision})
        cursor_filter = 'AND c.revision < @before_revision '
    rows = run_store.cosmos_orchestration_runs_container.query_items(
        query=(
            f'SELECT TOP {EDIT_HISTORY_PAGE_SIZE + 1} * FROM c '
            'WHERE c.conversation_id = @conversation_id AND c.user_id = @user_id '
            'AND (c.turn_id = @turn_id OR (NOT IS_DEFINED(c.turn_id) AND c.plan.turn_id = @turn_id)) '
            'AND (NOT IS_DEFINED(c.record_type) OR c.record_type = "run" OR c.record_type = "orchestration_run") '
            'AND (c.revision_root_run_id = @revision_root_run_id OR c.id = @revision_root_run_id) '
            f'{cursor_filter}ORDER BY c.revision DESC'
        ),
        parameters=parameters, partition_key=record['conversation_id'],
    )
    history_records = [
        row for row in rows
        if _owned_run(row, row.get('id'), user_id, record['conversation_id'])
        and _same_lineage(record, row)
        and (before_revision is None or _revision(row) < before_revision)
    ]
    history_records.sort(key=_revision, reverse=True)
    page = history_records[:EDIT_HISTORY_PAGE_SIZE]
    history = [
        {
            'run_id': row['id'], 'plan_id': row['plan'].get('plan_id'),
            'revision': _revision(row),
            'created_at': row['created_at'][:64] if isinstance(row.get('created_at'), str) else None,
            'origin': (
                row['revision_origin'] if row.get('revision_origin') in ('ai', 'restore')
                else 'original' if row['id'] == _root_id(row) else 'ai'
            ),
            'note': row['revision_note'][:EDIT_NOTE_LIMIT] if isinstance(row.get('revision_note'), str) else '',
        }
        for row in page
    ]
    pending = (record.get('edit_pending') or {}).get('elicitation')
    return {
        'plan': _public_plan(
            record['plan'], seeds=record.get('seeds'),
            reasoning_adjustments=record.get('reasoning_adjustments'),
        ),
        'version': _version(record),
        'edits': deepcopy(record.get('edit_narrowing') or _normalize_edits(record['plan'], None)),
        'chat': _bounded_chat(record.get('edit_chat')),
        'history': history,
        'next_before_revision': _revision(page[-1]) if len(history_records) > len(page) else None,
        'pending': {
            key: deepcopy(pending[key]) for key in _QUESTION_FIELDS if key in pending
        } if isinstance(pending, dict) else None,
        'busy': _claim_is_active(record.get('edit_claim')),
    }


def _normalize_request(data, conversation_id):
    _json_text(data)
    if not isinstance(data, dict):
        raise _invalid()
    action = data.get('action')
    if not isinstance(action, str) or action not in _ACTION_FIELDS:
        raise _invalid('Choose a supported plan edit action.')
    if set(data) - (_REQUEST_FIELDS | _ACTION_FIELDS[action]):
        raise _invalid('Invalid plan edit request fields.')
    if data.get('conversation_id') != conversation_id:
        raise _not_found()
    if not _valid_id(data.get('submission_id')):
        raise _invalid('A submission ID is required.')
    version = data.get('expected_version')
    if not isinstance(version, str) or len(version) > 200:
        raise PlanRevisionError('Reload the plan before editing it.')
    result = deepcopy(data)
    if action == 'ask':
        instruction = data.get('instruction')
        if (
            not isinstance(instruction, str) or not instruction.strip()
            or len(instruction) > EDIT_INSTRUCTION_LIMIT
        ):
            raise _invalid('Enter a plan change of at most 2,000 characters.')
        result['instruction'] = instruction.strip()
    if action == 'restore' and not _valid_id(data.get('source_run_id')):
        raise _invalid('Choose a saved version to restore.')
    if action == 'answer' or any(
        key in data for key in ('elicitation_id', 'elicitation_revision')
    ):
        revision = data.get('elicitation_revision')
        if (
            not _valid_id(data.get('elicitation_id')) or not isinstance(revision, int)
            or isinstance(revision, bool) or revision < 0
        ):
            raise _invalid('Use the current planner question.')
    if action == 'answer':
        response = data.get('elicitation_response')
        context = data.get('elicitation_context')
        if (
            not isinstance(response, dict) or set(response) - {'action', 'content'}
            or response.get('action') not in ('accept', 'decline', 'cancel')
            or ('content' in response and not isinstance(response['content'], dict))
            or (context is not None and not isinstance(context, dict))
        ):
            raise _invalid('Invalid planner question response.')
    return result


def _submission_receipt(record, request, fingerprint):
    for entry in [
        *(record.get('edit_submissions') or []), *(record.get('edit_attempts') or []),
        record.get('edit_claim') or {},
    ]:
        if entry.get('submission_id') != request['submission_id']:
            continue
        if entry.get('fingerprint') != fingerprint:
            raise PlanRevisionError(
                'That submission ID was already used for a different edit.',
                code='submission_conflict',
            )
        if entry.get('result_run_id'):
            result = read_revision_run(
                entry['result_run_id'], record['user_id'], record['conversation_id'],
            )
            if not _same_lineage(record, result):
                raise _not_found()
            return {
                'record': record, 'request': request, 'claim_id': None,
                'replayed': True, 'outcome_run_id': result['id'],
            }
    return None


def claim_plan_revision(run_id, user_id, conversation_id, data):
    """Claim one bounded edit lease, or replay an already committed identical request."""
    record = read_revision_run(run_id, user_id, conversation_id)
    request = _normalize_request(data, conversation_id)
    fingerprint = hashlib.sha256(_json_text(request).encode('utf-8')).hexdigest()
    replay = _submission_receipt(record, request, fingerprint)
    if replay:
        return replay
    _assert_editable(record)
    _check_version(record, request['expected_version'], required=True)
    active_claim = record.get('edit_claim') or {}
    discarding = request['action'] == 'discard'
    if _claim_is_active(active_claim) and (
        not discarding or active_claim.get('submission_id') == request['submission_id']
    ):
        raise _busy()
    pending = record.get('edit_pending')
    if request['action'] in ('ask', 'restore') and pending:
        raise _busy()
    if request['action'] in ('answer', 'discard'):
        question = (pending or {}).get('elicitation')
        # A discard can revoke an abandoned worker even before it produces a question.
        if not isinstance(question, dict) and not (discarding and active_claim):
            raise _changed(record)
        if request['action'] == 'answer' or 'elicitation_id' in request:
            if (
                not isinstance(question, dict)
                or request['elicitation_id'] != question.get('elicitation_id')
                or request['elicitation_revision'] != question.get('revision')
            ):
                raise _changed(record)
    if request['action'] == 'restore':
        source = read_revision_run(request['source_run_id'], user_id, conversation_id)
        if not _same_lineage(record, source) or source.get('started_at'):
            raise _not_found()
    overlay = _normalize_edits(
        record['plan'], request.get('edits') if request.get('edits') is not None
        else record.get('edit_narrowing'),
    )
    request['edits'] = overlay
    now = _now()
    lease = {
        'claim_id': str(uuid.uuid4()), 'submission_id': request['submission_id'],
        'fingerprint': fingerprint, 'started_at': now.isoformat(),
        'expires_at': (now + timedelta(seconds=EDIT_CLAIM_SECONDS)).isoformat(),
    }
    attempts = [
        item for item in record.get('edit_attempts') or []
        if item.get('submission_id') != request['submission_id']
    ]
    attempts.append({'submission_id': request['submission_id'], 'fingerprint': fingerprint})
    try:
        held = _replace(record, {
            'edit_claim': lease, 'edit_narrowing': overlay,
            'edit_attempts': attempts[-EDIT_RETAINED_SUBMISSIONS:],
        })
    except PlanRevisionError:
        latest = read_revision_run(run_id, user_id, conversation_id)
        replay = _submission_receipt(latest, request, fingerprint)
        if replay:
            return replay
        if _claim_is_active(latest.get('edit_claim')):
            raise _busy()
        raise
    return {'record': held, 'request': request, 'claim_id': lease['claim_id'], 'replayed': False}


def _claimed_record(claim):
    if not isinstance(claim, dict) or claim.get('replayed') or not claim.get('claim_id'):
        raise PlanRevisionError('This edit is no longer active. Reload the plan.')
    original = claim['record']
    record = read_revision_run(original['id'], original['user_id'], original['conversation_id'])
    saved = record.get('edit_claim') or {}
    if (
        saved.get('claim_id') != claim['claim_id']
        or saved.get('submission_id') != claim['request']['submission_id']
        or saved.get('fingerprint') != (original.get('edit_claim') or {}).get('fingerprint')
        or record.get('_etag') != original.get('_etag')
        or _version(record) != _version(original)
        or not _claim_is_active(saved)
    ):
        raise _changed(record)
    _assert_editable(record)
    return record


def _completion_updates(record, result_run_id, kind):
    lease = record['edit_claim']
    receipt = {
        'submission_id': lease['submission_id'], 'fingerprint': lease['fingerprint'],
        'result_run_id': result_run_id, 'kind': kind, 'completed_at': _now().isoformat(),
    }
    receipts = [
        item for item in record.get('edit_submissions') or []
        if item.get('submission_id') != lease['submission_id']
    ]
    return {
        'edit_claim': None,
        'edit_submissions': (receipts + [receipt])[-EDIT_RETAINED_SUBMISSIONS:],
        'edit_attempts': [
            item for item in record.get('edit_attempts') or []
            if item.get('submission_id') != lease['submission_id']
        ][-EDIT_RETAINED_SUBMISSIONS:],
    }


def _new_revision(record, document, turn_context, chat, instruction, origin):
    if not isinstance(document, dict) or not isinstance(document.get('steps'), list):
        raise _invalid('A validated plan is required.')
    if origin not in ('ai', 'restore'):
        raise _invalid('Invalid revision origin.')
    identity = json.dumps([
        record['conversation_id'], record['user_id'], record['id'],
        record['edit_claim']['submission_id'],
    ], separators=(',', ':'))
    run_id = f'run_{uuid.uuid5(uuid.NAMESPACE_URL, identity + ":run").hex}'
    plan_id = f'plan_{uuid.uuid5(uuid.NAMESPACE_URL, identity + ":plan").hex}'
    version = str(uuid.uuid4())
    plan = _manual_plan(_public_plan(document), version)
    plan.update({
        'plan_id': plan_id, 'run_id': run_id, 'revision': _revision(record) + 1,
        'turn_id': _turn_id(record), 'conversation_id': record['conversation_id'],
        'user_id': record['user_id'],
    })
    for step in plan['steps']:
        step['status'] = 'pending'
    summary = summarize_plan(plan)
    now = _now().isoformat()
    result = {
        'id': run_id, 'run_id': run_id, 'record_type': run_store.RUN_RECORD_TYPE,
        'conversation_id': record['conversation_id'], 'user_id': record['user_id'],
        'turn_index': record.get('turn_index', 0), 'plan': plan, 'plan_summary': summary,
        'revision': plan['revision'], 'status': 'awaiting_approval',
        'created_at': now, 'updated_at': now, 'started_at': None, 'completed_at': None,
        'error': None, 'approval': deepcopy(plan['approval']),
        'capabilities_used': list(summary['capabilities_used']),
        'documents_touched': [], 'artifacts': [], 'token_usage': {},
        'unresolved': [], 'answered_questions': [],
        'edit_version': version, 'edit_narrowing': _normalize_edits(plan, None),
        'edit_chat': _bounded_chat(chat), 'edit_pending': None, 'edit_claim': None,
        'edit_submissions': [], 'edit_attempts': [],
        'revision_root_run_id': _root_id(record), 'parent_run_id': record['id'],
        'revision_origin': origin,
        'revision_note': instruction[:EDIT_NOTE_LIMIT] if isinstance(instruction, str) else '',
    }
    for key in (*_IMMUTABLE_FIELDS, *_CONTEXT_FIELDS):
        if key in record:
            result[key] = deepcopy(record[key])
    result['turn_id'] = _turn_id(record)
    for key in _CONTEXT_FIELDS:
        if isinstance(turn_context, dict) and key in turn_context:
            result[key] = deepcopy(turn_context[key])
    return result


def complete_plan_revision(
    claim, *, kind, document=None, turn_context=None, chat=None, instruction='',
    origin='ai', pending=None,
):
    """Commit a new plan and its supersession together, or save a same-plan outcome."""
    record = _claimed_record(claim)
    desired_chat = record.get('edit_chat') if chat is None else chat
    if kind == 'plan':
        result = _new_revision(record, document, turn_context, desired_chat, instruction, origin)
        predecessor = deepcopy(run_store._strip_cosmos_metadata(record))
        predecessor.update(_completion_updates(record, result['id'], kind))
        predecessor.update({
            'status': 'superseded', 'superseded_by_run_id': result['id'],
            'superseded_at': _now().isoformat(), 'updated_at': _now().isoformat(),
            'edit_pending': None,
        })
        # The SDK's per-operation option is if_match_etag, not replace_item's etag.
        operations = [
            ('replace', (record['id'], predecessor), {'if_match_etag': record['_etag']}),
            ('create', (result,)),
        ]
        try:
            responses = run_store.cosmos_orchestration_runs_container.execute_item_batch(
                batch_operations=operations, partition_key=record['conversation_id'],
            )
        except (exceptions.CosmosBatchOperationError, exceptions.CosmosHttpResponseError) as exc:
            if exc.status_code in (404, 409, 412):
                latest = read_revision_run(record['id'], record['user_id'], record['conversation_id'])
                raise _changed(latest) from exc
            raise
        claim['completed'] = True
        saved = responses[1].get('resourceBody') if responses and len(responses) > 1 else None
        if isinstance(saved, dict) and saved.get('_etag'):
            return saved
        return read_revision_run(result['id'], result['user_id'], result['conversation_id'])
    if kind not in ('elicitation', 'message', 'discard'):
        raise _invalid('Invalid plan edit outcome.')
    if kind == 'elicitation' and (
        not isinstance(pending, dict) or not isinstance(pending.get('elicitation'), dict)
    ):
        raise _invalid('A saved planner question is required.')
    version = str(uuid.uuid4())
    plan = _manual_plan(record['plan'], version)
    updates = {
        **_completion_updates(record, record['id'], kind),
        'plan': plan, 'approval': deepcopy(plan['approval']), 'status': 'awaiting_approval',
        'edit_version': version, 'edit_chat': _bounded_chat(desired_chat),
        'edit_pending': deepcopy(pending) if kind == 'elicitation' else None,
    }
    if isinstance(turn_context, dict) and 'planning_token_usage' in turn_context:
        updates['planning_token_usage'] = deepcopy(turn_context['planning_token_usage'])
    if isinstance(turn_context, dict) and 'reasoning_adjustments' in turn_context:
        updates['reasoning_adjustments'] = merge_reasoning_adjustments(
            record.get('reasoning_adjustments'), turn_context['reasoning_adjustments'],
        )
    result = _replace(record, updates)
    claim['completed'] = True
    return result


def release_plan_revision(claim):
    """Best-effort cleanup of our own still-live lease, never another worker's outcome."""
    if not claim or claim.get('replayed') or claim.get('completed'):
        return
    try:
        record = _claimed_record(claim)
        _replace(record, {'edit_claim': None})
    except PlanRevisionError:
        log_event(
            '[ORCHESTRATION_RUNS] Kept a newer or completed plan edit during lease cleanup.',
            level=logging.INFO, debug_only=True,
        )
    except AzureError as exc:
        log_event(
            '[ORCHESTRATION_RUNS] Plan edit lease cleanup could not be saved.',
            extra={'exception_type': type(exc).__name__}, level=logging.ERROR,
        )


def claim_plan_run(
    run_id, user_id, conversation_id, *, plan_id=None, expected_version=None,
    edits=None, conversation_context=None,
):
    """Atomically turn a current pre-execution plan into the one executable run."""
    record = read_revision_run(run_id, user_id, conversation_id)
    if record.get('started_at') or record.get('status') in ('running', 'completed'):
        raise PlanRevisionError('This plan has already started.', code='already_run')
    if record.get('status') not in _RUNNABLE_STATUSES or 'superseded_by_run_id' in record:
        raise _changed(record)
    _check_plan_id(record, plan_id)
    _check_version(record, expected_version, required=bool(_version(record)))
    if _claim_is_active(record.get('edit_claim')) or record.get('edit_pending'):
        raise _busy()
    overlay = _normalize_edits(
        record['plan'], edits if edits is not None else record.get('edit_narrowing'),
    )
    plan = apply_plan_edits(deepcopy(record['plan']), overlay)
    now = _now().isoformat()
    plan['status'] = 'running'
    plan['approval'] = {
        **(plan.get('approval') or {}), 'state': 'approved',
        'approved_at': now, 'approved_by': user_id,
    }
    summary = summarize_plan(plan)
    updates = {
        'plan': plan, 'plan_summary': summary, 'approval': deepcopy(plan['approval']),
        'status': 'running', 'started_at': now, 'edit_claim': None,
        'capabilities_used': list(summary['capabilities_used']),
    }
    if conversation_context is not None:
        if not isinstance(conversation_context, dict):
            raise _invalid('Invalid conversation context.')
        updates['conversation_context'] = deepcopy(conversation_context)
    return _replace(record, updates)
