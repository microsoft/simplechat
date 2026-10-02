# functions_workflow_chat_delivery.py
"""Pure chat delivery contract for chat-started workflow runs.

Version: 0.261.226
Implemented in: 0.261.226

This module owns the pure contract for posting a chat-started workflow run's result back into the
chat. It performs no storage, model calls, or result-text reads. Inline copies of ``_fingerprint``,
``clean_catalog_text``, ``quoted_workflow_name``, state sets, and model identity fields are pinned
by parity tests because importing their sources would create import cycles or pull azure.cosmos or
config into this module.
"""

import hashlib
import json
import logging
import re
import threading
import uuid
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from functions_appinsights import log_event, workflow_log_context
from functions_m365_workflow_binding import M365_WAITING_STATES


CHAT_DELIVERY_VERSION = 1
CHAT_DELIVERY_KEY = 'chat_delivery'
DELIVERY_METADATA_KEY = 'workflow_delivery'
DELIVERY_MESSAGE_ID_PREFIX = 'assistant_workflow_delivery_'
NOTIFICATION_TYPE = 'workflow_chat_delivery'
WORKFLOW_SCOPE = 'personal'
CHAT_TRIGGER_SOURCE = 'chat_orchestration'
LOG_PREFIX = '[WORKFLOW_CHAT_DELIVERY]'
STATUS_LOG_PREFIX = '[WORKFLOW_CHAT_DELIVERY_STATUS]'

STATUS_PENDING = 'pending'
STATUS_READY = 'ready'
STATUS_DELIVERING = 'delivering'
STATUS_DELIVERED = 'delivered'
STATUS_UNDELIVERABLE = 'undeliverable'
STATUS_EXPIRED = 'expired'
STATUSES = frozenset({
    STATUS_PENDING,
    STATUS_READY,
    STATUS_DELIVERING,
    STATUS_DELIVERED,
    STATUS_UNDELIVERABLE,
    STATUS_EXPIRED,
})
OPEN_STATUSES = frozenset({STATUS_PENDING, STATUS_READY, STATUS_DELIVERING})
FINAL_STATUSES = frozenset({STATUS_DELIVERED, STATUS_UNDELIVERABLE, STATUS_EXPIRED})
REOPENABLE_STATUSES = frozenset({STATUS_DELIVERED, STATUS_UNDELIVERABLE})

KIND_RESULT = 'result'
KIND_FAILED = 'failed'
KIND_CANCELLED = 'cancelled'
KIND_STATUS = 'status'
KIND_CONTENT_BLOCKED = 'content_blocked'
KIND_ANALYSIS = 'analysis'
KIND_EXPIRED = 'expired'
KIND_SKIPPED = 'skipped'
RESULT_CONTEXT_KINDS = frozenset({KIND_RESULT, KIND_ANALYSIS})

PHASE_CLAIMED = 'claimed'
PHASE_PUBLISHING = 'publishing'
PHASE_UNREAD_MARKED = 'unread_marked'
PHASE_MESSAGE_CREATED = 'message_created'
PHASE_NOTIFIED = 'notified'
PHASES = (PHASE_CLAIMED, PHASE_PUBLISHING, PHASE_UNREAD_MARKED, PHASE_MESSAGE_CREATED, PHASE_NOTIFIED)

NOTICE_CHAT_RESPONSE = 'chat_response'
NOTICE_UNDELIVERABLE = 'undeliverable'
NOTICE_EXPIRED = 'expired'
NOTICE_NONE = 'none'
NOTICE_KINDS = frozenset({NOTICE_CHAT_RESPONSE, NOTICE_UNDELIVERABLE, NOTICE_EXPIRED, NOTICE_NONE})

REASON_CHAT_UNAVAILABLE = 'chat_unavailable'
REASON_ACCESS_LOST = 'access_lost'
REASON_WORKFLOW_DELETED = 'workflow_deleted'
REASON_RUNTIME_MISSING = 'runtime_missing'
REASON_DELIVERY_FAILED = 'delivery_failed'
REASON_EXPIRED_BEFORE_DELIVERY = 'expired_before_delivery'
REASON_CONTENT_BLOCKED = 'content_blocked'
REASON_RESULTS_OFF = 'results_off'
REASON_RESULT_UNAVAILABLE = 'result_unavailable'
REASON_DEADLINE_EXCEEDED = 'deadline_exceeded'
SILENT_REASONS = frozenset({REASON_WORKFLOW_DELETED, REASON_RUNTIME_MISSING})

RUNTIME_TERMINAL_STATES = frozenset({
    'completed',
    'completed_partial',
    'failed',
    'invalid',
    'incomplete',
    'cancelled',
    'skipped',
})
RESULT_RUN_STATES = frozenset({'completed', 'completed_partial'})
FAILED_RUN_STATES = frozenset({'failed', 'invalid', 'incomplete'})
RUNTIME_RESUMABLE_STATES = frozenset({'failed', 'invalid', 'incomplete'})
RUNTIME_WAITING_STATES = frozenset({'waiting_approval', 'waiting_output', 'waiting_recovery', 'paused'}) | M365_WAITING_STATES
RUNTIME_ACTIVE_STATES = frozenset({'queued', 'running', 'cancelling'})
RUN_DOCUMENT_TERMINAL_STATUSES = RUNTIME_TERMINAL_STATES | frozenset({'canceled'})

KIND_BY_TERMINAL_STATE = {
    'completed': KIND_RESULT,
    'completed_partial': KIND_RESULT,
    'failed': KIND_FAILED,
    'invalid': KIND_FAILED,
    'incomplete': KIND_FAILED,
    'cancelled': KIND_CANCELLED,
    'skipped': KIND_SKIPPED,
}
MODEL_IDENTITY_FIELDS = ('model_deployment', 'model_id', 'model_endpoint_id', 'model_provider')

DELIVERY_GRACE_SECONDS = 86400
DEFAULT_DEADLINE_SECONDS = 86400
MAX_DEADLINE_SECONDS = 86400
LEASE_SECONDS = 300
SWEEP_INTERVAL_SECONDS = 30
SWEEP_LOCK_NAME = 'workflow_chat_delivery_sweep'
SWEEP_LOCK_SECONDS = 120
SWEEP_TOP = 25
SWEEP_MAX_RUNS = 8
SWEEP_MAX_SECONDS = 90
SWEEP_TS_GRACE_SECONDS = 120
BACKOFF_SECONDS = (30, 60, 120, 240, 480, 900, 900, 900)
MAX_ATTEMPTS = 8
DEFER_RETRY_SECONDS = 30
DEFER_MAX_SECONDS = 900
STREAM_META_FRESH_SECONDS = 90
RECENT_USER_MESSAGE_SECONDS = 600

HINT_QUEUE_MAX = 256
HISTORY_MAX = 5
MAX_ROLES = 20
MAX_ROLE_LENGTH = 64
MAX_GROUPS = 10
MAX_GROUP_ID_LENGTH = 64
MAX_MODEL_FIELD_LENGTH = 200
MAX_REASONING_EFFORT_LENGTH = 32
NAME_MAX_LENGTH = 80

COMPOSE_TEMPERATURE = 0.3
COMPOSE_MAX_TOKENS = 1500
REPLY_MAX_CHARS = 12000
TRIMMED_FALLBACK_CHARS = 2000
EXCERPT_BUDGET_BYTES = 48 * 1024
TRIMMED_FALLBACK_INTRO = "I couldn't summarize the result, so here's the start of it:"
FALLBACK_QUESTION = 'Summarize what this workflow run produced.'
WORKFLOW_RUN_DELIVERY_FOLLOW_UP = (
    "I'll post the results here when the run finishes. You can also follow it in the workflow's "
    "run history in Workflows."
)
WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY = (
    "I'll post each run's results here when it finishes. You can also follow them in each "
    "workflow's run history in Workflows."
)
UNDELIVERABLE_NOTICE_MESSAGE = "The chat that started this run can't show it anymore. Open the run in Workflows to see the details."
EXPIRED_NOTICE_MESSAGE = "The run didn't finish in time to post to the chat. Open it in Workflows to see where it stands."
DELIVERY_RETRY_UNSUPPORTED = 'workflow_delivery_retry_unsupported'
DELIVERY_EDIT_UNSUPPORTED = 'workflow_delivery_edit_unsupported'
_DELIVERY_REFUSALS = {
    DELIVERY_RETRY_UNSUPPORTED: (
        "A workflow run posted this message, so it can't be retried here. "
        "To run the workflow again, open the run in Workflows."
    ),
    DELIVERY_EDIT_UNSUPPORTED: "A workflow run posted this message, so it can't be edited. Ask a new question instead.",
}
_DEFAULT_WORKFLOW_NAME = 'Workflow'
_TEXT_NOISE = re.compile('[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]')
_TIME_ZONE_RE = re.compile(r'[A-Za-z0-9_+\-/]{1,64}')

_HINT_LOCK = threading.Lock()
_HINT_EVENT = threading.Event()
_HINT_QUEUE = deque()
_HINT_KEYS = set()


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    ).hexdigest()


def clean_catalog_text(value, limit):
    """Return user-authored text as one bounded, printable line, or '' for anything else."""
    if not isinstance(value, str):
        return ''
    text = ' '.join(_TEXT_NOISE.sub(' ', value).split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '\u2026'


def quoted_workflow_name(value):
    """A saved name as inline code that cannot format the reply, or None when nothing is left of it."""
    text = clean_catalog_text(value, NAME_MAX_LENGTH)
    if not text.replace('`', '').strip():
        return None
    return '`' + text.replace('`', "'") + '`'


def display_workflow_name(value):
    return quoted_workflow_name(value) or f'`{_DEFAULT_WORKFLOW_NAME}`'


def utc_now():
    return datetime.now(timezone.utc)


def format_delivery_timestamp(dt):
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def parse_delivery_timestamp(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or len(text) > 64:
            return None
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def workflow_delivery_message_id(run_id, conversation_id, generation):
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('run_id is required')
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ValueError('conversation_id is required')
    if type(generation) is not int or generation < 0:
        raise ValueError('generation must be a non-negative integer')
    return DELIVERY_MESSAGE_ID_PREFIX + _fingerprint([run_id, conversation_id, generation])[:40]


def delivery_thread_id(message_id):
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError('message_id is required')
    return str(uuid.uuid5(uuid.NAMESPACE_URL, message_id))


def is_workflow_delivery_message(message):
    if not isinstance(message, Mapping):
        return False
    message_id = message.get('id')
    if isinstance(message_id, str) and message_id.startswith(DELIVERY_MESSAGE_ID_PREFIX):
        return True
    metadata = message.get('metadata')
    return isinstance(metadata, Mapping) and isinstance(metadata.get(DELIVERY_METADATA_KEY), Mapping)


def workflow_delivery_refusal_payload(code):
    """Return the fixed 400 body for Retry or Edit on a message a workflow run posted."""
    if code not in _DELIVERY_REFUSALS:
        code = DELIVERY_RETRY_UNSUPPORTED
    return {'error': _DELIVERY_REFUSALS[code], 'code': code}, 400


def normalize_requester_roles(roles):
    if not isinstance(roles, (list, tuple)):
        return []
    normalized = []
    seen = set()
    for role in roles:
        if not isinstance(role, str) or not role.strip() or len(role) > MAX_ROLE_LENGTH or role in seen:
            continue
        normalized.append(role)
        seen.add(role)
        if len(normalized) >= MAX_ROLES:
            break
    return normalized


def normalize_model_selection(seeds, active_group_ids=None):
    if not isinstance(seeds, Mapping):
        seeds = {}
    model = {}
    raw_model = seeds.get('model')
    if isinstance(raw_model, Mapping):
        invalid = False
        for field in MODEL_IDENTITY_FIELDS:
            value = raw_model.get(field)
            if value is None or value == '':
                continue
            if not isinstance(value, str):
                invalid = True
                break
            text = value.strip()
            if not text or len(text) > MAX_MODEL_FIELD_LENGTH:
                invalid = True
                break
            model[field] = text
        if invalid:
            model = {}
    reasoning_effort = seeds.get('reasoning_effort')
    if isinstance(reasoning_effort, str):
        reasoning_effort = reasoning_effort.strip()
        if len(reasoning_effort) > MAX_REASONING_EFFORT_LENGTH:
            reasoning_effort = ''
    else:
        reasoning_effort = ''
    groups_source = seeds.get('active_group_ids')
    if not isinstance(groups_source, (list, tuple)) or not groups_source:
        groups_source = active_group_ids
    active_groups = []
    seen_groups = set()
    if isinstance(groups_source, (list, tuple)):
        for group_id in groups_source:
            if not isinstance(group_id, str):
                continue
            text = group_id.strip()
            if not text or len(text) > MAX_GROUP_ID_LENGTH or text in seen_groups:
                continue
            active_groups.append(text)
            seen_groups.add(text)
            if len(active_groups) >= MAX_GROUPS:
                break
    return {'model': model, 'reasoning_effort': reasoning_effort, 'active_group_ids': active_groups}


def normalize_time_zone(value):
    if isinstance(value, str) and _TIME_ZONE_RE.fullmatch(value):
        return value
    return 'UTC'


def build_chat_delivery_seed(*, time_zone, model_selection, requester_roles, now=None):
    created_at = format_delivery_timestamp(now if isinstance(now, datetime) else utc_now())
    return {
        'version': CHAT_DELIVERY_VERSION,
        'status': STATUS_PENDING,
        'generation': None,
        'expires_at': None,
        'time_zone': normalize_time_zone(time_zone),
        'model_selection': normalize_model_selection(model_selection),
        'requester_roles': normalize_requester_roles(requester_roles),
        'lease_id': None,
        'lease_expires_at': None,
        'attempts': 0,
        'next_attempt_at': None,
        'first_deferred_at': None,
        'phase': None,
        'message_id': None,
        'planned_at': None,
        'kind': None,
        'notice_kind': None,
        'outcome_reason': None,
        'run_status': None,
        'delivered_at': None,
        'created_at': created_at,
        'updated_at': created_at,
        'history': [],
    }


def _lower_text(value):
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text or None


def control_summary(control):
    if not isinstance(control, Mapping):
        return {
            'exists': False,
            'deleted': False,
            'version': None,
            'state': None,
            'phase': None,
            'gate_reason_code': None,
            'deadline_at': None,
            'deadline_seconds': None,
            'schema_version': None,
        }
    limits = control.get('limits') if isinstance(control.get('limits'), Mapping) else {}
    gate = control.get('gate') if isinstance(control.get('gate'), Mapping) else {}
    version = control.get('version')
    schema_version = control.get('schema_version')
    return {
        'exists': True,
        'deleted': bool(control.get('deleted')),
        'version': version if type(version) is int else None,
        'state': _lower_text(control.get('state') if control.get('state') is not None else control.get('control_state')),
        'phase': _lower_text(control.get('phase')),
        'gate_reason_code': _lower_text(gate.get('reason_code')),
        'deadline_at': control.get('deadline_at') if control.get('deadline_at') is not None else limits.get('deadline_at'),
        'deadline_seconds': control.get('deadline_seconds') if control.get('deadline_seconds') is not None else limits.get('deadline_seconds'),
        'schema_version': schema_version if type(schema_version) is int else None,
    }


def compute_expires_at(*, deadline_at=None, deadline_seconds=None, base=None):
    parsed_deadline = parse_delivery_timestamp(deadline_at)
    if parsed_deadline:
        return format_delivery_timestamp(parsed_deadline + timedelta(seconds=DELIVERY_GRACE_SECONDS))
    parsed_base = parse_delivery_timestamp(base) or utc_now()
    seconds = DEFAULT_DEADLINE_SECONDS
    if type(deadline_seconds) is int and deadline_seconds > 0:
        seconds = min(deadline_seconds, MAX_DEADLINE_SECONDS)
    return format_delivery_timestamp(parsed_base + timedelta(seconds=seconds + DELIVERY_GRACE_SECONDS))


def finalize_chat_delivery_seed(seed, control):
    if not isinstance(seed, Mapping):
        return None
    record = deepcopy(dict(seed))
    summary = control_summary(control)
    record['expires_at'] = compute_expires_at(
        deadline_at=summary.get('deadline_at'),
        deadline_seconds=summary.get('deadline_seconds'),
        base=record.get('created_at'),
    )
    return record


def chat_delivery_applies(run, conversation_id):
    if not isinstance(run, Mapping) or not isinstance(conversation_id, str) or not conversation_id:
        return False
    delivery = run.get(CHAT_DELIVERY_KEY)
    invocation = run.get('chat_invocation')
    return (
        isinstance(delivery, Mapping)
        and type(delivery.get('version')) is int
        and delivery.get('version') == CHAT_DELIVERY_VERSION
        and isinstance(invocation, Mapping)
        and invocation.get('conversation_id') == conversation_id
    )


def needs_guarded_run_save(run):
    if not isinstance(run, Mapping):
        return False
    return CHAT_DELIVERY_KEY in run or (run.get('trigger_source') == CHAT_TRIGGER_SOURCE and 'chat_invocation' not in run)


def merge_stored_run_fields(incoming, stored):
    incoming = incoming if isinstance(incoming, Mapping) else {}
    stored = stored if isinstance(stored, Mapping) else {}
    cosmos_keys = {'_rid', '_self', '_etag', '_attachments', '_ts'}
    merged = {key: deepcopy(value) for key, value in incoming.items() if key not in cosmos_keys}
    if CHAT_DELIVERY_KEY in stored:
        merged[CHAT_DELIVERY_KEY] = deepcopy(stored.get(CHAT_DELIVERY_KEY))
    else:
        merged.pop(CHAT_DELIVERY_KEY, None)
    if 'chat_invocation' not in merged and 'chat_invocation' in stored:
        merged['chat_invocation'] = deepcopy(stored.get('chat_invocation'))
    stored_status = _lower_text(stored.get('status'))
    has_cancel_request = bool(stored.get('cancellation_requested_at')) or stored_status in {'cancelling', 'cancelled', 'canceled'}
    if has_cancel_request:
        for field in ('cancellation_requested_at', 'cancellation_requested_by'):
            if stored.get(field):
                merged[field] = deepcopy(stored.get(field))
        incoming_status = _lower_text(merged.get('status'))
        if stored_status in {'cancelled', 'canceled'}:
            merged['status'] = 'cancelled'
        elif incoming_status not in {'cancelled', 'canceled'}:
            merged['status'] = 'cancelling'
    return merged


def _mark_closed(record, reason, timestamp):
    updated = deepcopy(dict(record))
    updated.update({
        'status': STATUS_UNDELIVERABLE,
        'outcome_reason': reason,
        'notice_kind': NOTICE_NONE,
        'lease_id': None,
        'lease_expires_at': None,
        'next_attempt_at': None,
        'updated_at': timestamp,
    })
    return updated


def _mark_delivered_without_notice(record, timestamp):
    updated = deepcopy(dict(record))
    updated.update({
        'status': STATUS_DELIVERED,
        'notice_kind': NOTICE_NONE,
        'delivered_at': updated.get('delivered_at') or timestamp,
        'lease_id': None,
        'lease_expires_at': None,
        'next_attempt_at': None,
        'updated_at': timestamp,
    })
    return updated


def _close_for_runtime(record, reason, timestamp):
    # A message that already exists stays delivered; only an unposted generation closes.
    if phase_at_least(record.get('phase'), PHASE_MESSAGE_CREATED):
        return _mark_delivered_without_notice(record, timestamp)
    return _mark_closed(record, reason, timestamp)


def _abandon_generation(current, candidate):
    """Reset the per-generation fields when a ready generation is replaced before it finished."""
    updated = deepcopy(candidate)
    if phase_at_least(current.get('phase'), PHASE_MESSAGE_CREATED):
        history = list(current.get('history') if isinstance(current.get('history'), list) else [])
        entry = _history_entry(current)
        entry.update({'status': STATUS_DELIVERED, 'notice_kind': NOTICE_NONE})
        history.append(entry)
        updated['history'] = history[-HISTORY_MAX:]
    updated.update({
        'phase': None,
        'planned_at': None,
        'message_id': None,
        'attempts': 0,
        'outcome_reason': None,
        'notice_kind': None,
        'delivered_at': None,
        'next_attempt_at': None,
        'first_deferred_at': None,
        'lease_id': None,
        'lease_expires_at': None,
    })
    return updated


def _generation_from_summary(summary):
    version = summary.get('version') if isinstance(summary, Mapping) else None
    if type(version) is int and version >= 0:
        return version
    return 0


def _ready_fields(summary, kind):
    state = summary.get('state') if isinstance(summary, Mapping) else None
    return {
        'status': STATUS_READY,
        'generation': _generation_from_summary(summary),
        'kind': kind,
        'run_status': state,
    }


def _history_entry(record):
    return {
        'generation': record.get('generation'),
        'status': record.get('status'),
        'kind': record.get('kind'),
        'outcome_reason': record.get('outcome_reason'),
        'message_id': record.get('message_id'),
        'delivered_at': record.get('delivered_at'),
        'notice_kind': record.get('notice_kind'),
    }


def _changed_record(original, candidate):
    original_without_updated = {key: value for key, value in original.items() if key != 'updated_at'}
    candidate_without_updated = {key: value for key, value in candidate.items() if key != 'updated_at'}
    return original_without_updated != candidate_without_updated


def reconcile_chat_delivery(record, summary, now=None):
    timestamp_dt = now if isinstance(now, datetime) else utc_now()
    timestamp = format_delivery_timestamp(timestamp_dt)
    if not isinstance(record, Mapping):
        return deepcopy(record), False, False
    current = deepcopy(dict(record))
    if current.get('version') != CHAT_DELIVERY_VERSION or current.get('status') not in STATUSES:
        return current, False, False
    status = current.get('status')
    if status in {STATUS_DELIVERING, STATUS_EXPIRED}:
        return current, False, False
    if not isinstance(summary, Mapping) or not summary.get('exists'):
        if status in {STATUS_PENDING, STATUS_READY}:
            updated = _close_for_runtime(current, REASON_RUNTIME_MISSING, timestamp)
            return updated, True, False
        return current, False, False
    if summary.get('deleted'):
        if status in {STATUS_PENDING, STATUS_READY}:
            updated = _close_for_runtime(current, REASON_WORKFLOW_DELETED, timestamp)
            return updated, True, False
        return current, False, False
    reopened = False
    if status in REOPENABLE_STATUSES and type(current.get('generation')) is int:
        version = summary.get('version')
        if type(version) is int and version > current.get('generation'):
            history = list(current.get('history') if isinstance(current.get('history'), list) else [])
            history.append(_history_entry(current))
            current.update({
                'status': STATUS_PENDING,
                'generation': None,
                'kind': None,
                'notice_kind': None,
                'outcome_reason': None,
                'run_status': None,
                'delivered_at': None,
                'message_id': None,
                'planned_at': None,
                'phase': None,
                'lease_id': None,
                'lease_expires_at': None,
                'next_attempt_at': None,
                'first_deferred_at': None,
                'attempts': 0,
                'expires_at': compute_expires_at(
                    deadline_at=summary.get('deadline_at'),
                    deadline_seconds=summary.get('deadline_seconds'),
                    base=timestamp_dt,
                ),
                'history': history[-HISTORY_MAX:],
            })
            status = STATUS_PENDING
            reopened = True
    if status in {STATUS_PENDING, STATUS_READY}:
        state = summary.get('state')
        candidate = deepcopy(current)
        expires_at = parse_delivery_timestamp(candidate.get('expires_at'))
        if state in RUNTIME_TERMINAL_STATES:
            candidate.update(_ready_fields(summary, KIND_BY_TERMINAL_STATE[state]))
        elif (
            state == 'paused'
            and REASON_DEADLINE_EXCEEDED in {summary.get('gate_reason_code'), summary.get('phase')}
        ) or (state not in RUNTIME_TERMINAL_STATES and expires_at and timestamp_dt > expires_at):
            candidate.update(_ready_fields(summary, KIND_EXPIRED))
        elif status == STATUS_READY:
            candidate.update({'status': STATUS_PENDING, 'generation': None, 'kind': None, 'run_status': None})
        if status == STATUS_READY and candidate.get('generation') != current.get('generation'):
            # The run moved on (resumed, or resumed and finished again) before this generation was posted.
            candidate = _abandon_generation(current, candidate)
        if candidate.get('status') == STATUS_READY and (
            status == STATUS_PENDING or candidate.get('generation') != current.get('generation')
        ):
            # A record that just became deliverable is due now, not after a wait scheduled while it was pending.
            candidate.update({'next_attempt_at': None, 'first_deferred_at': None})
        if reopened or _changed_record(current, candidate):
            candidate['updated_at'] = timestamp
            return candidate, True, candidate.get('status') == STATUS_READY
        return current, False, current.get('status') == STATUS_READY
    return current, False, False


def phase_at_least(phase, wanted):
    if phase not in PHASES or wanted not in PHASES:
        return False
    return PHASES.index(phase) >= PHASES.index(wanted)


def delivery_label(workflow_name, asked_when):
    label = f'Results from {display_workflow_name(workflow_name)}'
    if isinstance(asked_when, str) and asked_when:
        return f'{label} · you asked on {asked_when}'
    return label


def assemble_delivery_content(label, body, disclosure=''):
    parts = []
    if isinstance(label, str) and label:
        parts.append(label)
    body_text = body.strip() if isinstance(body, str) else ''
    if body_text:
        parts.append(body_text)
    if isinstance(disclosure, str) and disclosure:
        parts.append(disclosure)
    return '\n\n'.join(parts)


_FAILURE_REASONS = {
    'failed': 'the run stopped before it finished',
    'invalid': "the workflow couldn't run as defined",
    'incomplete': "some of its steps didn't finish",
    'skipped': 'no new or changed files were detected',
    REASON_DEADLINE_EXCEEDED: 'it reached its time limit',
    'execution_budget_exceeded': 'it reached its execution limit',
    'repeat_iteration_limit': 'it reached its repeat limit',
    'm365_authorization': 'Microsoft 365 access needs to be reconnected',
    'authorization': 'your workflow access must be restored',
}
FAILURE_REASON_CODES = frozenset(_FAILURE_REASONS)


def failure_reason_text(code):
    return _FAILURE_REASONS.get(code, _FAILURE_REASONS['failed'])


def delivery_note_text(kind, workflow_name, *, reason_code=None):
    name = display_workflow_name(workflow_name)
    if kind == KIND_FAILED:
        return f'{name} failed: {failure_reason_text(reason_code)}.'
    if kind == KIND_CANCELLED:
        return f'{name} was cancelled.'
    if kind == KIND_STATUS:
        return f'{name} finished. Open the run to see its results.'
    if kind == KIND_CONTENT_BLOCKED:
        return f"{name} finished, but its results can't be shown here. Open the run to see them."
    if kind == KIND_ANALYSIS:
        return f'{name} finished with a saved analysis. Ask a follow-up question about it here.'
    if kind == KIND_SKIPPED:
        return f"{name} didn't run: no new or changed files were detected."
    raise ValueError('unsupported delivery note kind')


def notice_workflow_name(name):
    text = clean_catalog_text(name, NAME_MAX_LENGTH).replace('"', "'")
    if not text:
        return 'your workflow'
    return f'"{text}"'


def _sentence_start(text):
    if text.startswith('your workflow'):
        return 'Your workflow' + text[len('your workflow'):]
    return text


def notice_title(kind, workflow_name):
    q = notice_workflow_name(workflow_name)
    if kind in {KIND_RESULT, KIND_ANALYSIS, KIND_STATUS, KIND_CONTENT_BLOCKED}:
        return _sentence_start(f'Results from {q} are ready')
    if kind == KIND_FAILED:
        return _sentence_start(f"{q} didn't finish")
    if kind == KIND_CANCELLED:
        return _sentence_start(f'{q} was cancelled')
    if kind == KIND_SKIPPED:
        return _sentence_start(f"{q} didn't run")
    if kind == KIND_EXPIRED:
        return _sentence_start(f"{q} didn't finish in time to post to chat")
    raise ValueError('unsupported notice kind')


def delivered_notice_preview(workflow_name):
    return _sentence_start(f'Results from {notice_workflow_name(workflow_name)} are in your chat')


def delivery_notification_key(run_id, generation):
    return f'workflow-chat-delivery:{run_id}:{generation}'


def undeliverable_notification_key(run_id, generation):
    return f'workflow-chat-delivery-notice:{run_id}:{generation}'


def expired_notification_key(run_id):
    return f'workflow-chat-delivery-notice:{run_id}:expired'


def token_usage_idempotency_key(message_id, attempt):
    return f'workflow_result_delivery:{message_id}:{attempt}'


def workflow_run_notice_link(workflow_id, run_id):
    return '/workflow-activity?' + urlencode({'workflowId': workflow_id, 'runId': run_id, 'scope': WORKFLOW_SCOPE})


def notice_metadata(workflow_id, run_id, delivery_status):
    return {'workflow_id': workflow_id, 'run_id': run_id, 'workflow_scope': WORKFLOW_SCOPE, 'delivery_status': delivery_status}


def build_delivery_metadata(*, kind, workflow_id, run_id, generation, run_status, orchestration_run_id, step_id, requested_at):
    return {
        'version': CHAT_DELIVERY_VERSION,
        'kind': kind,
        'workflow_id': workflow_id,
        'workflow_scope': WORKFLOW_SCOPE,
        'run_id': run_id,
        'generation': generation,
        'run_status': run_status,
        'orchestration_run_id': orchestration_run_id,
        'step_id': step_id,
        'requested_at': requested_at,
    }


def next_backoff_seconds(attempts):
    if type(attempts) is not int:
        return BACKOFF_SECONDS[0]
    index = min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1
    return BACKOFF_SECONDS[index]


def signal_workflow_chat_delivery(user_id, run_id):
    try:
        if not isinstance(user_id, str) or not user_id.strip() or not isinstance(run_id, str) or not run_id.strip():
            return False
        key = (user_id, run_id)
        with _HINT_LOCK:
            if key in _HINT_KEYS:
                _HINT_EVENT.set()
                return True
            if len(_HINT_QUEUE) >= HINT_QUEUE_MAX:
                return False
            _HINT_QUEUE.append(key)
            _HINT_KEYS.add(key)
            _HINT_EVENT.set()
            return True
    except Exception:
        return False


def drain_workflow_chat_delivery_hints(limit=None):
    with _HINT_LOCK:
        if type(limit) is not int or limit < 0:
            limit = len(_HINT_QUEUE)
        drained = []
        while _HINT_QUEUE and len(drained) < limit:
            key = _HINT_QUEUE.popleft()
            _HINT_KEYS.discard(key)
            drained.append(key)
        if not _HINT_QUEUE:
            _HINT_EVENT.clear()
        return drained


def wait_for_workflow_chat_delivery_hint(timeout):
    return _HINT_EVENT.wait(timeout)


def clear_workflow_chat_delivery_hints():
    with _HINT_LOCK:
        _HINT_QUEUE.clear()
        _HINT_KEYS.clear()
        _HINT_EVENT.clear()


def delivery_log(message, *, level=logging.INFO, status_route=False, run_id=None, conversation_id=None, **fields):
    try:
        prefix = STATUS_LOG_PREFIX if status_route else LOG_PREFIX
        stage = 'workflow_chat_delivery_status' if status_route else 'workflow_chat_delivery'
        extra = {'stage': stage, **workflow_log_context(conversation_id=conversation_id, run_id=run_id)}
        extra.update({key: value for key, value in fields.items() if value is not None})
        log_event(f'{prefix} {message}', extra=extra, level=level)
    except Exception:
        return


__all__ = (
    'CHAT_DELIVERY_VERSION',
    'CHAT_DELIVERY_KEY',
    'DELIVERY_METADATA_KEY',
    'DELIVERY_MESSAGE_ID_PREFIX',
    'NOTIFICATION_TYPE',
    'WORKFLOW_SCOPE',
    'CHAT_TRIGGER_SOURCE',
    'LOG_PREFIX',
    'STATUS_LOG_PREFIX',
    'STATUS_PENDING',
    'STATUS_READY',
    'STATUS_DELIVERING',
    'STATUS_DELIVERED',
    'STATUS_UNDELIVERABLE',
    'STATUS_EXPIRED',
    'STATUSES',
    'OPEN_STATUSES',
    'FINAL_STATUSES',
    'REOPENABLE_STATUSES',
    'KIND_RESULT',
    'KIND_FAILED',
    'KIND_CANCELLED',
    'KIND_STATUS',
    'KIND_CONTENT_BLOCKED',
    'KIND_ANALYSIS',
    'KIND_EXPIRED',
    'KIND_SKIPPED',
    'RESULT_CONTEXT_KINDS',
    'PHASE_CLAIMED',
    'PHASE_PUBLISHING',
    'PHASE_UNREAD_MARKED',
    'PHASE_MESSAGE_CREATED',
    'PHASE_NOTIFIED',
    'PHASES',
    'NOTICE_CHAT_RESPONSE',
    'NOTICE_UNDELIVERABLE',
    'NOTICE_EXPIRED',
    'NOTICE_NONE',
    'NOTICE_KINDS',
    'REASON_CHAT_UNAVAILABLE',
    'REASON_ACCESS_LOST',
    'REASON_WORKFLOW_DELETED',
    'REASON_RUNTIME_MISSING',
    'REASON_DELIVERY_FAILED',
    'REASON_EXPIRED_BEFORE_DELIVERY',
    'REASON_CONTENT_BLOCKED',
    'REASON_RESULTS_OFF',
    'REASON_RESULT_UNAVAILABLE',
    'REASON_DEADLINE_EXCEEDED',
    'SILENT_REASONS',
    'RUNTIME_TERMINAL_STATES',
    'RESULT_RUN_STATES',
    'FAILED_RUN_STATES',
    'RUNTIME_RESUMABLE_STATES',
    'RUNTIME_WAITING_STATES',
    'RUNTIME_ACTIVE_STATES',
    'RUN_DOCUMENT_TERMINAL_STATUSES',
    'KIND_BY_TERMINAL_STATE',
    'MODEL_IDENTITY_FIELDS',
    'DELIVERY_GRACE_SECONDS',
    'DEFAULT_DEADLINE_SECONDS',
    'MAX_DEADLINE_SECONDS',
    'LEASE_SECONDS',
    'SWEEP_INTERVAL_SECONDS',
    'SWEEP_LOCK_NAME',
    'SWEEP_LOCK_SECONDS',
    'SWEEP_TOP',
    'SWEEP_MAX_RUNS',
    'SWEEP_MAX_SECONDS',
    'SWEEP_TS_GRACE_SECONDS',
    'BACKOFF_SECONDS',
    'MAX_ATTEMPTS',
    'DEFER_RETRY_SECONDS',
    'DEFER_MAX_SECONDS',
    'STREAM_META_FRESH_SECONDS',
    'RECENT_USER_MESSAGE_SECONDS',
    'HINT_QUEUE_MAX',
    'HISTORY_MAX',
    'MAX_ROLES',
    'MAX_ROLE_LENGTH',
    'MAX_GROUPS',
    'MAX_GROUP_ID_LENGTH',
    'MAX_MODEL_FIELD_LENGTH',
    'MAX_REASONING_EFFORT_LENGTH',
    'NAME_MAX_LENGTH',
    'COMPOSE_TEMPERATURE',
    'COMPOSE_MAX_TOKENS',
    'REPLY_MAX_CHARS',
    'TRIMMED_FALLBACK_CHARS',
    'EXCERPT_BUDGET_BYTES',
    'TRIMMED_FALLBACK_INTRO',
    'FALLBACK_QUESTION',
    'WORKFLOW_RUN_DELIVERY_FOLLOW_UP',
    'WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY',
    'UNDELIVERABLE_NOTICE_MESSAGE',
    'EXPIRED_NOTICE_MESSAGE',
    'DELIVERY_RETRY_UNSUPPORTED',
    'DELIVERY_EDIT_UNSUPPORTED',
    'clean_catalog_text',
    'quoted_workflow_name',
    'display_workflow_name',
    'utc_now',
    'format_delivery_timestamp',
    'parse_delivery_timestamp',
    'workflow_delivery_message_id',
    'delivery_thread_id',
    'is_workflow_delivery_message',
    'workflow_delivery_refusal_payload',
    'normalize_requester_roles',
    'normalize_model_selection',
    'normalize_time_zone',
    'build_chat_delivery_seed',
    'control_summary',
    'compute_expires_at',
    'finalize_chat_delivery_seed',
    'chat_delivery_applies',
    'needs_guarded_run_save',
    'merge_stored_run_fields',
    'reconcile_chat_delivery',
    'phase_at_least',
    'delivery_label',
    'assemble_delivery_content',
    'delivery_note_text',
    'FAILURE_REASON_CODES',
    'failure_reason_text',
    'notice_workflow_name',
    'notice_title',
    'delivered_notice_preview',
    'delivery_notification_key',
    'undeliverable_notification_key',
    'expired_notification_key',
    'token_usage_idempotency_key',
    'workflow_run_notice_link',
    'notice_metadata',
    'build_delivery_metadata',
    'next_backoff_seconds',
    'signal_workflow_chat_delivery',
    'drain_workflow_chat_delivery_hints',
    'wait_for_workflow_chat_delivery_hint',
    'clear_workflow_chat_delivery_hints',
    'delivery_log',
)
