# functions_workflow_chat_delivery_status.py
"""Owner-only status rows for the workflow runs a user's chats started.

Version: 0.261.218
Implemented in: 0.261.218

Backs ``GET /api/v2/orchestration/workflow-runs/status``, the batched route the V2 run card polls.
Every read is a single-partition query in the signed-in user's own partition that projects only
the fields a row needs. In-flight rows get a bounded number of live runtime reads; finished rows
use the runtime projection stored on the run. Nothing is written, and nothing in a row comes from
a run's output, its error text, or an exception.
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from functions_m365_workflow_binding import M365_WAITING_STATES
from functions_workflow_alert_safety import sanitize_workflow_alert_record
from functions_workflow_chat_delivery import (
    CHAT_TRIGGER_SOURCE,
    DELIVERY_MESSAGE_ID_PREFIX,
    FAILED_RUN_STATES,
    FAILURE_REASON_CODES,
    NAME_MAX_LENGTH,
    OPEN_STATUSES,
    REASON_ACCESS_LOST,
    REASON_CHAT_UNAVAILABLE,
    REASON_CONTENT_BLOCKED,
    REASON_DEADLINE_EXCEEDED,
    REASON_DELIVERY_FAILED,
    REASON_EXPIRED_BEFORE_DELIVERY,
    REASON_RESULT_UNAVAILABLE,
    REASON_RESULTS_OFF,
    REASON_RUNTIME_MISSING,
    REASON_WORKFLOW_DELETED,
    RESULT_RUN_STATES,
    RUN_DOCUMENT_TERMINAL_STATUSES,
    RUNTIME_ACTIVE_STATES,
    RUNTIME_RESUMABLE_STATES,
    RUNTIME_TERMINAL_STATES,
    RUNTIME_WAITING_STATES,
    STATUS_DELIVERED,
    STATUS_EXPIRED,
    STATUS_READY,
    STATUSES,
    WORKFLOW_SCOPE,
    clean_catalog_text,
    delivery_log,
    failure_reason_text,
    parse_delivery_timestamp,
    utc_now,
)
from functions_workflow_definitions import workflow_definition_for_editor, workflow_definition_revision


CONVERSATION_LIMIT = 20
GLOBAL_LIMIT = 50
LIVE_READ_LIMIT = 10
WORKFLOW_READ_LIMIT = 20
RECENT_DELIVERY_SECONDS = 600

INVALID_CONVERSATION_CODE = 'invalid_conversation_id'
STATUS_UNAVAILABLE_CODE = 'workflow_run_status_unavailable'
_ERRORS = {
    INVALID_CONVERSATION_CODE: ('The conversation ID is not valid.', 400),
    STATUS_UNAVAILABLE_CODE: ("Workflow run status isn't available right now. Try again later.", 503),
}

ROW_STATUSES = ('queued', 'running', 'waiting', 'completed', 'completed_partial', 'failed', 'cancelled', 'expired')
ROW_PHASES = ('running', 'needs_you', 'finished', 'failed', 'cancelled')
DELIVERY_NOT_APPLICABLE = 'not_applicable'
DELIVERY_ROW_STATUSES = ('pending', 'delivering', 'delivered', 'undeliverable', 'expired', DELIVERY_NOT_APPLICABLE)
DELIVERY_REASONS = frozenset({
    REASON_CHAT_UNAVAILABLE,
    REASON_ACCESS_LOST,
    REASON_WORKFLOW_DELETED,
    REASON_RUNTIME_MISSING,
    REASON_DELIVERY_FAILED,
    REASON_EXPIRED_BEFORE_DELIVERY,
    REASON_CONTENT_BLOCKED,
    REASON_RESULTS_OFF,
    REASON_RESULT_UNAVAILABLE,
    REASON_DEADLINE_EXCEEDED,
})

RETRY_BLOCKED_WORKFLOW_DELETED = 'workflow_deleted'
RETRY_BLOCKED_ALREADY_RUNNING = 'workflow_already_running'
RETRY_BLOCKED_DEFINITION_CHANGED = 'workflow_definition_changed'
RETRY_BLOCKED_NOT_RESUMABLE = 'not_resumable'
RETRY_BLOCKED_DEADLINE_EXCEEDED = 'deadline_exceeded'
RETRY_BLOCKED_UNAVAILABLE = 'retry_unavailable'
RETRY_BLOCKED_CODES = frozenset({
    RETRY_BLOCKED_WORKFLOW_DELETED,
    RETRY_BLOCKED_ALREADY_RUNNING,
    RETRY_BLOCKED_DEFINITION_CHANGED,
    RETRY_BLOCKED_NOT_RESUMABLE,
    RETRY_BLOCKED_DEADLINE_EXCEEDED,
    RETRY_BLOCKED_UNAVAILABLE,
})

WAITING_ACTION_APPROVE = 'approve'
WAITING_ACTION_RECONNECT = 'reconnect'
WAITING_ACTION_OPEN_RUN = 'open_run'

_KNOWN_STATES = RUNTIME_ACTIVE_STATES | RUNTIME_WAITING_STATES | RUNTIME_TERMINAL_STATES | frozenset({'canceled'})
_CANCELLED_STATES = frozenset({'cancelled', 'canceled'})
_DEFAULT_WORKFLOW_NAME = 'Workflow'
_CONVERSATION_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
_CODE_MAX_LENGTH = 64
_ID_MAX_LENGTH = 256
_SECONDS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

_READ_OK = 'ok'
_READ_GONE = 'gone'
_READ_DELETING = 'deleting'
_READ_ERROR = 'error'
_READ_OVER_CAP = 'over_cap'

_PROJECTION = ', '.join((
    'c.id AS run_id',
    'c.workflow_id AS workflow_id',
    'c.workflow_name AS workflow_name',
    'c.status AS status',
    'c.started_at AS started_at',
    'c.completed_at AS completed_at',
    'c.progress AS progress',
    'c.runtime_version AS runtime_version',
    'c.definition_revision AS definition_revision',
    'c.chat_invocation.conversation_id AS conversation_id',
    'c.chat_invocation.orchestration_run_id AS orchestration_run_id',
    'c.chat_invocation.step_id AS step_id',
    'c.chat_invocation.requested_at AS requested_at',
    'c.runtime.version AS projection_version',
    'c.runtime.state AS projection_state',
    'c.runtime.phase AS projection_phase',
    'c.runtime.progress AS projection_progress',
    'c.runtime.can_resume AS projection_can_resume',
    'c.runtime.deleted AS projection_deleted',
    'c.runtime.limits.deadline_at AS projection_deadline_at',
    'c.runtime.gate.id AS projection_gate_id',
    'c.runtime.gate.reason_code AS projection_gate_reason_code',
    'c.chat_delivery.status AS delivery_status',
    'c.chat_delivery.generation AS delivery_generation',
    'c.chat_delivery.message_id AS delivery_message_id',
    'c.chat_delivery.delivered_at AS delivery_delivered_at',
    'c.chat_delivery.outcome_reason AS delivery_outcome_reason',
))
_OWNER_FILTER = 'c.user_id = @user_id AND c.trigger_source = @source AND IS_DEFINED(c.chat_invocation)'
_NEWEST_FIRST = 'ORDER BY c.chat_invocation.requested_at DESC'
CONVERSATION_QUERY = (
    f'SELECT TOP {CONVERSATION_LIMIT + 1} {_PROJECTION} FROM c '
    f'WHERE {_OWNER_FILTER} AND c.chat_invocation.conversation_id = @conversation_id '
    f'{_NEWEST_FIRST}'
)
GLOBAL_QUERY = (
    f'SELECT TOP {GLOBAL_LIMIT + 1} {_PROJECTION} FROM c '
    f'WHERE {_OWNER_FILTER} '
    'AND (NOT ARRAY_CONTAINS(@terminal, c.status) '
    'OR ARRAY_CONTAINS(@open, c.chat_delivery.status) '
    'OR (IS_STRING(c.chat_delivery.delivered_at) AND c.chat_delivery.delivered_at >= @recent)) '
    f'{_NEWEST_FIRST}'
)


class WorkflowRunStatusError(Exception):
    """A closed status-route failure: a code, its HTTP status and a fixed sentence."""

    def __init__(self, code):
        if code not in _ERRORS:
            code = STATUS_UNAVAILABLE_CODE
        super().__init__(code)
        self.code = code
        self.status = _ERRORS[code][1]

    def payload(self):
        return {'error': _ERRORS[self.code][0], 'code': self.code}, self.status


@dataclass(frozen=True)
class WorkflowRunStatusServices:
    """The reads one status request needs. Tests bind fakes; the route binds the real ones."""

    runs: Any
    workflows: Any
    get_settings: Callable[[], Any]
    settings_gate: Callable[[Any], Any]
    live_status: Callable[..., Any]
    clock: Callable[[], datetime] = utc_now


def default_workflow_run_status_services():
    """Bind the personal workflow containers and runtime reader on first use.

    Imported here so importing this module never loads config or the runtime.
    """
    import config
    from functions_orchestration_workflow_context import workflow_run_settings_gate
    from functions_settings import get_settings
    from functions_workflow_runtime import workflow_runtime_status

    return WorkflowRunStatusServices(
        runs=config.cosmos_personal_workflow_runs_container,
        workflows=config.cosmos_personal_workflows_container,
        get_settings=get_settings,
        settings_gate=workflow_run_settings_gate,
        live_status=workflow_runtime_status,
        clock=utc_now,
    )


def _identifier(value, max_length=_ID_MAX_LENGTH):
    """A stored id as it is, or None: the same shape the runtime store accepts for its ids."""
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= max_length
        or value != value.strip()
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        return None
    return value


def _code(value):
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text or len(text) > _CODE_MAX_LENGTH:
        return None
    return text


def _known_state(value):
    state = _code(value)
    return state if state in _KNOWN_STATES else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _seconds(value):
    moment = parse_delivery_timestamp(value)
    return moment.strftime(_SECONDS_FORMAT) if moment is not None else None


def parse_status_conversation_id(values):
    """The one optional ``conversation_id`` query value, trimmed; a repeated or malformed one is refused."""
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    values = list(values)
    if not values:
        return None
    if len(values) > 1:
        raise WorkflowRunStatusError(INVALID_CONVERSATION_CODE)
    text = values[0].strip() if isinstance(values[0], str) else ''
    if not _CONVERSATION_ID.fullmatch(text):
        raise WorkflowRunStatusError(INVALID_CONVERSATION_CODE)
    return text


def status_query(user_id, conversation_id, now):
    """The query text, its parameters and the row limit. One partition, newest request first."""
    parameters = [
        {'name': '@user_id', 'value': user_id},
        {'name': '@source', 'value': CHAT_TRIGGER_SOURCE},
    ]
    if conversation_id is not None:
        parameters.append({'name': '@conversation_id', 'value': conversation_id})
        return CONVERSATION_QUERY, parameters, CONVERSATION_LIMIT
    recent = (now - timedelta(seconds=RECENT_DELIVERY_SECONDS)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    parameters.extend((
        {'name': '@terminal', 'value': sorted(RUN_DOCUMENT_TERMINAL_STATUSES)},
        {'name': '@open', 'value': sorted(OPEN_STATUSES)},
        {'name': '@recent', 'value': recent},
    ))
    return GLOBAL_QUERY, parameters, GLOBAL_LIMIT


class _WorkflowRead:
    __slots__ = ('kind', 'workflow')

    def __init__(self, kind, workflow=None):
        self.kind = kind
        self.workflow = workflow


class _RequestReads:
    """One request's read budget.

    One workflow read per distinct workflow (at most ``WORKFLOW_READ_LIMIT``), counted apart from
    the live runtime reads (at most ``LIVE_READ_LIMIT``).
    """

    def __init__(self, services, user_id):
        self.services = services
        self.user_id = user_id
        self.workflows = {}
        self.live_reads = 0

    def workflow(self, workflow_id):
        if workflow_id in self.workflows:
            return self.workflows[workflow_id]
        if len(self.workflows) >= WORKFLOW_READ_LIMIT:
            return _WorkflowRead(_READ_OVER_CAP)
        read = self._read_workflow(workflow_id)
        self.workflows[workflow_id] = read
        return read

    def _read_workflow(self, workflow_id):
        """The workflow in the form the runtime compares revisions on, or why it can't be used."""
        try:
            raw = self.services.workflows.read_item(item=workflow_id, partition_key=self.user_id)
        except Exception as exc:
            if getattr(exc, 'status_code', None) == 404:
                return _WorkflowRead(_READ_GONE)
            delivery_log(
                'Workflow read failed.', level=logging.WARNING, status_route=True,
                error_type=type(exc).__name__,
            )
            return _WorkflowRead(_READ_ERROR)
        if not isinstance(raw, Mapping) or raw.get('user_id') != self.user_id or raw.get('group_id'):
            return _WorkflowRead(_READ_GONE)
        if raw.get('deleting') or raw.get('status') == 'deleting':
            return _WorkflowRead(_READ_DELETING)
        try:
            # The same editor form get_personal_workflow returns, which decide_workflow_runtime compares.
            cleaned = {key: value for key, value in raw.items() if not str(key).startswith('_')}
            workflow = workflow_definition_for_editor(sanitize_workflow_alert_record(cleaned))
        except Exception as exc:
            delivery_log(
                'Workflow read failed.', level=logging.WARNING, status_route=True,
                error_type=type(exc).__name__,
            )
            return _WorkflowRead(_READ_ERROR)
        return _WorkflowRead(_READ_OK, workflow)

    def live(self, workflow, run_id):
        if self.live_reads >= LIVE_READ_LIMIT:
            return None
        self.live_reads += 1
        try:
            projection = self.services.live_status(workflow, run_id, reader_user_id=self.user_id)
        except Exception as exc:
            delivery_log(
                'Live run status read failed; using the stored status.', level=logging.WARNING,
                status_route=True, run_id=run_id, error_type=type(exc).__name__,
            )
            return None
        return projection if isinstance(projection, Mapping) else None


def _view(*, version, state, phase, progress, can_resume, deleted, deadline_at, gate_id, gate_reason_code):
    return {
        'version': _count(version),
        'state': _known_state(state),
        'phase': _code(phase),
        'progress': progress if isinstance(progress, Mapping) else None,
        'can_resume': can_resume if type(can_resume) is bool else None,
        'deleted': deleted is True,
        'deadline_at': deadline_at,
        'gate_id': _identifier(gate_id),
        'gate_reason_code': _code(gate_reason_code),
    }


def _stored_view(item):
    return _view(
        version=item.get('projection_version'),
        state=item.get('projection_state'),
        phase=item.get('projection_phase'),
        progress=item.get('projection_progress'),
        can_resume=item.get('projection_can_resume'),
        deleted=item.get('projection_deleted'),
        deadline_at=item.get('projection_deadline_at'),
        gate_id=item.get('projection_gate_id'),
        gate_reason_code=item.get('projection_gate_reason_code'),
    )


def _live_view(projection):
    limits = projection.get('limits') if isinstance(projection.get('limits'), Mapping) else {}
    gate = projection.get('gate') if isinstance(projection.get('gate'), Mapping) else {}
    return _view(
        version=projection.get('version'),
        state=projection.get('state'),
        phase=projection.get('phase'),
        progress=projection.get('progress'),
        can_resume=projection.get('can_resume'),
        deleted=projection.get('deleted'),
        deadline_at=limits.get('deadline_at'),
        gate_id=gate.get('id'),
        gate_reason_code=gate.get('reason_code'),
    )


def _deadline_paused(state, view):
    return state == 'paused' and REASON_DEADLINE_EXCEEDED in (view['gate_reason_code'], view['phase'])


def _status_and_phase(state, *, expired):
    if expired:
        return 'expired', 'failed'
    if state in ('queued', 'running'):
        return state, 'running'
    if state in RESULT_RUN_STATES:
        return state, 'finished'
    if state in FAILED_RUN_STATES or state == 'skipped':
        return 'failed', 'failed'
    if state in _CANCELLED_STATES:
        return 'cancelled', 'cancelled'
    if state in RUNTIME_WAITING_STATES and state != 'waiting_recovery':
        return 'waiting', 'needs_you'
    # cancelling, waiting_recovery, and any state this module doesn't know yet.
    return 'running', 'running'


def _waiting(state, view):
    if state == 'waiting_approval':
        reason, action = 'approval', WAITING_ACTION_APPROVE
    elif state == 'awaiting_sign_in':
        reason, action = 'microsoft_365_reconnect', WAITING_ACTION_RECONNECT
    elif state in M365_WAITING_STATES:
        reason, action = 'microsoft_365_approval', WAITING_ACTION_OPEN_RUN
    elif state == 'waiting_output':
        reason, action = 'output_review', WAITING_ACTION_OPEN_RUN
    elif state == 'waiting_recovery':
        reason, action = 'recovery', WAITING_ACTION_OPEN_RUN
    elif state == 'paused':
        reason = REASON_DEADLINE_EXCEEDED if _deadline_paused(state, view) else 'paused'
        action = WAITING_ACTION_OPEN_RUN
    else:
        return None
    return {'reason': reason, 'action': action, 'gate_id': view['gate_id']}


def _steps(*candidates):
    """Steps finished and steps in all, from the first ``{completed, total}`` progress that has both."""
    for progress in candidates:
        if not isinstance(progress, Mapping):
            continue
        completed = _count(progress.get('completed'))
        total = _count(progress.get('total'))
        if completed is not None and total is not None:
            return min(completed, total), total
    return None, None


def _elapsed_seconds(started_at, end):
    started = parse_delivery_timestamp(started_at)
    if started is None or end is None:
        return None
    return max(0, int((end - started).total_seconds()))


def _delivery(item):
    status = item.get('delivery_status')
    if status not in STATUSES:
        return {
            'status': DELIVERY_NOT_APPLICABLE,
            'generation': None,
            'message_id': None,
            'delivered_at': None,
            'reason': None,
        }
    delivered = status == STATUS_DELIVERED
    message_id = _identifier(item.get('delivery_message_id'))
    reason = item.get('delivery_outcome_reason')
    return {
        'status': 'pending' if status == STATUS_READY else status,
        'generation': _count(item.get('delivery_generation')),
        'message_id': message_id if delivered and message_id and message_id.startswith(DELIVERY_MESSAGE_ID_PREFIX) else None,
        'delivered_at': _seconds(item.get('delivery_delivered_at')) if delivered else None,
        'reason': reason if reason in DELIVERY_REASONS else None,
    }


def _failure(status, state, view):
    """The closed failure code and its fixed sentence; never the run's own error text."""
    if status == 'expired':
        code = REASON_DEADLINE_EXCEEDED
    elif status == 'failed':
        candidate = view['gate_reason_code'] or state
        code = candidate if candidate in FAILURE_REASON_CODES else 'failed'
    else:
        return None, None
    text = failure_reason_text(code)
    return text[:1].upper() + text[1:] + '.', code


def _retry_blocked(view, runtime_version, item, workflow_read, run_id, delivery_status, now):
    """Why the durable resume route would refuse this run now, or None when it should accept it.

    The checks mirror ``decide_workflow_runtime`` and ``journal_request('resume')`` on the stored
    projection, so the answer is a snapshot: the resume route can still refuse.
    """
    if view['can_resume'] is None or runtime_version is None:
        return RETRY_BLOCKED_UNAVAILABLE
    if view['deleted']:
        return RETRY_BLOCKED_WORKFLOW_DELETED
    if not view['can_resume']:
        return RETRY_BLOCKED_NOT_RESUMABLE
    deadline = parse_delivery_timestamp(view['deadline_at'])
    if (deadline is not None and deadline <= now) or delivery_status == STATUS_EXPIRED:
        return RETRY_BLOCKED_DEADLINE_EXCEEDED
    if workflow_read is None or workflow_read.kind in (_READ_ERROR, _READ_OVER_CAP):
        return RETRY_BLOCKED_UNAVAILABLE
    if workflow_read.kind in (_READ_GONE, _READ_DELETING):
        return RETRY_BLOCKED_WORKFLOW_DELETED
    revision = item.get('definition_revision')
    if not isinstance(revision, str) or not revision:
        return RETRY_BLOCKED_UNAVAILABLE
    try:
        current = workflow_definition_revision(workflow_read.workflow)
    except Exception:
        return RETRY_BLOCKED_UNAVAILABLE
    if current != revision:
        return RETRY_BLOCKED_DEFINITION_CHANGED
    if workflow_read.workflow.get('active_run_id') not in (None, '', run_id):
        return RETRY_BLOCKED_ALREADY_RUNNING
    return None


def _status_row(item, reads, now):
    if not isinstance(item, Mapping):
        return None
    run_id = _identifier(item.get('run_id'))
    workflow_id = _identifier(item.get('workflow_id'))
    conversation_id = _identifier(item.get('conversation_id'))
    if not run_id or not workflow_id or not conversation_id:
        return None

    stored = _stored_view(item)
    stored_state = stored['state'] or _known_state(item.get('status'))
    in_flight = stored_state not in RUN_DOCUMENT_TERMINAL_STATUSES
    workflow_read = None
    if in_flight or stored_state in RUNTIME_RESUMABLE_STATES:
        workflow_read = reads.workflow(workflow_id)

    view = stored
    live = False
    if in_flight and workflow_read.kind == _READ_OK:
        projection = reads.live(workflow_read.workflow, run_id)
        if projection is not None:
            view = _live_view(projection)
            live = True
    state = view['state'] or stored_state
    terminal = state in RUN_DOCUMENT_TERMINAL_STATUSES

    if live and view['version'] is not None:
        runtime_version = view['version']
    elif _count(item.get('runtime_version')) is not None:
        runtime_version = item['runtime_version']
    else:
        runtime_version = stored['version']

    delivery = _delivery(item)
    raw_delivery_status = item.get('delivery_status')
    expired = not terminal and (raw_delivery_status == STATUS_EXPIRED or _deadline_paused(state, view))
    status, phase = _status_and_phase(state, expired=expired)
    waiting = _waiting(state, view)
    error, error_code = _failure(status, state, view)

    retry_blocked = None
    if state in RUNTIME_RESUMABLE_STATES:
        retry_blocked = _retry_blocked(view, runtime_version, item, workflow_read, run_id, raw_delivery_status, now)
    step_index, step_count = _steps(view['progress'], stored['progress'], item.get('progress'))
    completed_at = _seconds(item.get('completed_at')) if terminal else None

    return {
        'workflow_id': workflow_id,
        'workflow_scope': WORKFLOW_SCOPE,
        'run_id': run_id,
        'workflow_name': clean_catalog_text(item.get('workflow_name'), NAME_MAX_LENGTH) or _DEFAULT_WORKFLOW_NAME,
        'conversation_id': conversation_id,
        'orchestration_run_id': _identifier(item.get('orchestration_run_id')),
        'step_id': _identifier(item.get('step_id')),
        'requested_at': _seconds(item.get('requested_at')),
        'status': status,
        'phase': phase,
        'runtime_version': runtime_version,
        'step_index': step_index,
        'step_count': step_count,
        'step_label': None,
        'started_at': _seconds(item.get('started_at')),
        'completed_at': completed_at,
        'elapsed_seconds': _elapsed_seconds(
            item.get('started_at'),
            parse_delivery_timestamp(completed_at) if terminal else now,
        ),
        'waiting': waiting,
        'delivery': delivery,
        'error': error,
        'error_code': error_code,
        'retry_blocked': retry_blocked,
        'actions': {
            'cancel': not terminal and not expired and state != 'cancelling',
            'retry': state in RUNTIME_RESUMABLE_STATES and retry_blocked is None,
            'approve': bool(
                waiting and waiting['action'] == WAITING_ACTION_APPROVE and waiting['gate_id'] and not expired
            ),
            'open_run': True,
        },
        'live': live,
    }


def _request_now(services):
    try:
        moment = parse_delivery_timestamp(services.clock())
    except Exception:
        moment = None
    return moment or utc_now()


def workflow_run_status_payload(user_id, conversation_id_values=None, *, services=None):
    """The status route's 200 body for ``user_id``, or a ``WorkflowRunStatusError``.

    ``conversation_id_values`` is every ``conversation_id`` the request sent. With one, the rows
    are that chat's runs; with none, they are the user's runs still in flight, still waiting to be
    delivered, or delivered in the last ten minutes. Rows come back even when chats can no longer
    start workflows, so an in-flight card doesn't vanish when an admin changes the setting.
    """
    conversation_id = parse_status_conversation_id(conversation_id_values)
    if _identifier(user_id) is None:
        raise WorkflowRunStatusError(STATUS_UNAVAILABLE_CODE)
    services = services or default_workflow_run_status_services()
    now = _request_now(services)
    try:
        available = services.settings_gate(services.get_settings()) is None
    except Exception as exc:
        delivery_log(
            'Workflow run status settings read failed.', level=logging.WARNING, status_route=True,
            error_type=type(exc).__name__,
        )
        raise WorkflowRunStatusError(STATUS_UNAVAILABLE_CODE) from None

    query, parameters, limit = status_query(user_id, conversation_id, now)
    try:
        items = list(services.runs.query_items(query=query, parameters=parameters, partition_key=user_id))
    except Exception as exc:
        delivery_log(
            'Workflow run status query failed.', level=logging.WARNING, status_route=True,
            conversation_id=conversation_id, error_type=type(exc).__name__,
        )
        raise WorkflowRunStatusError(STATUS_UNAVAILABLE_CODE) from None

    reads = _RequestReads(services, user_id)
    rows = []
    for item in items[:limit]:
        row = _status_row(item, reads, now)
        if row is not None:
            rows.append(row)
    return {
        'available': available,
        'runs': rows,
        'checked_at': now.strftime(_SECONDS_FORMAT),
        'truncated': len(items) > limit,
    }


__all__ = (
    'CONVERSATION_LIMIT',
    'GLOBAL_LIMIT',
    'LIVE_READ_LIMIT',
    'WORKFLOW_READ_LIMIT',
    'RECENT_DELIVERY_SECONDS',
    'INVALID_CONVERSATION_CODE',
    'STATUS_UNAVAILABLE_CODE',
    'ROW_STATUSES',
    'ROW_PHASES',
    'DELIVERY_NOT_APPLICABLE',
    'DELIVERY_ROW_STATUSES',
    'DELIVERY_REASONS',
    'RETRY_BLOCKED_WORKFLOW_DELETED',
    'RETRY_BLOCKED_ALREADY_RUNNING',
    'RETRY_BLOCKED_DEFINITION_CHANGED',
    'RETRY_BLOCKED_NOT_RESUMABLE',
    'RETRY_BLOCKED_DEADLINE_EXCEEDED',
    'RETRY_BLOCKED_UNAVAILABLE',
    'RETRY_BLOCKED_CODES',
    'WAITING_ACTION_APPROVE',
    'WAITING_ACTION_RECONNECT',
    'WAITING_ACTION_OPEN_RUN',
    'CONVERSATION_QUERY',
    'GLOBAL_QUERY',
    'WorkflowRunStatusError',
    'WorkflowRunStatusServices',
    'default_workflow_run_status_services',
    'parse_status_conversation_id',
    'status_query',
    'workflow_run_status_payload',
)
