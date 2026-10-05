# functions_orchestration_workflow_handoff_decisions.py
"""Accept, deny and read the workflow hand-offs a chat orchestration run offers.

Version: 0.261.238
Implemented in: 0.261.238

A ``workflow_handoff`` step only dry-runs a one-time workflow and keeps what it checked in a
server-side sidecar on its step record. The requester's accept is the second gate. It
re-authorizes the request, rebuilds the workflow from that sidecar with fresh authorization,
creates it disabled under an id derived from the hand-off, and queues exactly one durable run whose
result is posted back to the chat. Every write is idempotent: an accept retried after the
workflow was created, but before its run was queued, finds the workflow and queues the same run.

The module does not use Flask. The route passes the run, the conversation, the request body and
the caller's identity, and turns a ``HandoffError`` into a JSON response. Responses carry closed
codes and fixed text, never exception text, handles, the model selection or the blueprint.
"""

import hashlib
import logging
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from azure.core.exceptions import AzureError
from azure.cosmos import exceptions

import functions_personal_workflows
from functions_appinsights import log_event, workflow_log_context
from functions_orchestration_registry import CAPABILITY_WORKFLOW_HANDOFF, CAPABILITY_WORKFLOW_PROPOSE
from functions_orchestration_result_contracts import canonical_digest
from functions_orchestration_runs import (
    WORKFLOW_HANDOFF_DECISIONS_FIELD,
    ProposalDecisionBusy,
    get_orchestration_run,
    get_orchestration_step_record,
    update_workflow_handoff_decision,
)
from functions_orchestration_schema import is_legacy_plan
from functions_orchestration_workflow_context import (
    WORKFLOW_REASON_SHARED_CONVERSATION,
    conversation_is_private,
    workflow_handoff_gate,
)
from functions_orchestration_workflow_handoffs import (
    WORKFLOW_HANDOFF_REASON_TEXT,
    WORKFLOW_HANDOFF_STATUS_READY,
    WORKFLOW_HANDOFF_STATUS_UNAVAILABLE,
    WORKFLOW_HANDOFF_VERSION,
    workflow_handoff_id,
)
from functions_orchestration_workflow_proposals import DRAFT_SERVER_FIELDS, REASON_CONTENT_REVIEW, URL_ACCESS_NOTE
from functions_orchestration_workflow_runs import (
    REASON_NOT_STARTED,
    WORKFLOW_RUN_TRIGGER_SOURCE,
    WORKFLOW_RUN_VERSION,
    _CONFLICT_REASONS,
    chat_delivery_seed_for,
)
from functions_orchestration_workflows import workflow_proposal_id
from functions_workflow_chat_delivery import chat_delivery_applies
from functions_workflow_definitions import workflow_origin_material_change
from functions_workflow_drafts import (
    DRAFT_MAX_ERRORS,
    DRAFT_MESSAGE_MAX_LENGTH,
    HANDOFF_SERVER_FIELDS,
    URL_ACCESS_AUTHORIZATION_FIELDS,
    WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
    create_personal_handoff_workflow,
    create_personal_handoff_workflow_from_payload,
    dry_run_handoff_workflow,
    dry_run_personal_workflow,
    is_handoff_workflow,
    orchestration_workflow_id,
)
from functions_workflow_limits import WorkflowLoopLimitError, get_chat_orchestration_max_workflow_handoffs_per_day


_LOG_PREFIX = '[ORCHESTRATION_WORKFLOW_HANDOFF_DECISIONS]'
_LOG_STAGE = 'workflow_handoff_decision'
_SIDECAR_KEY = 'workflow_handoff'
_PROPOSAL_SIDECAR_KEY = 'workflow_proposal'

# A claim older than this no longer blocks another accept: its request stopped before finishing.
HANDOFF_CLAIM_SECONDS = 120
# The rolling window the per-user hand-off limit counts over.
HANDOFF_DAILY_WINDOW = timedelta(hours=24)

# The run's request id comes from the user and the hand-off, so every retry queues the same run.
WORKFLOW_HANDOFF_REQUEST_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'urn:simplechat:workflow-handoff-runs')

DECISION_CREATING = 'creating'
DECISION_CREATED = 'created'
DECISION_QUEUED = 'queued'
DECISION_DENIED = 'denied'

MODE_AS_PROPOSED = 'as_proposed'
MODE_EDITED = 'edited'
ACCEPT_MODES = (MODE_AS_PROPOSED, MODE_EDITED)
ACCEPT_FIELDS = frozenset({'conversation_id', 'mode', 'workflow'})
DENY_FIELDS = frozenset({'conversation_id'})

STATE_PENDING = 'pending'
STATE_CREATING = 'creating'
STATE_CREATED = 'created'
STATE_QUEUED = 'queued'
STATE_DENIED = 'denied'
STATE_EXPIRED = 'expired'
STATE_UNAVAILABLE = 'unavailable'
STATE_INVALID = 'invalid'

ACTION_ACCEPT = 'accept'
ACTION_EDIT = 'edit'
ACTION_DENY = 'deny'

SERVICE_UNAVAILABLE_CODE = 'service_unavailable'

ERROR_MESSAGES = {
    'invalid_request': 'The request is not valid.',
    'handoff_edit_invalid': 'The edited workflow is not valid. Review the task, runner and document inputs.',
    'workflow_handoff_disabled': 'Workflow hand-off is not available here.',
    'workflow_role_required': 'You need the workflow role to hand work off to a workflow.',
    'workflow_shared_conversation': 'Workflow hand-off is available only in your own private chats.',
    'handoff_results_off': 'Workflow hand-off needs workflow results in chat, which is turned off.',
    'handoff_access_lost': 'You no longer have access to a document, workspace or agent this workflow uses.',
    'run_not_found': 'Run not found.',
    'handoff_not_found': 'Workflow hand-off not found.',
    'handoff_unavailable': 'This workflow hand-off is no longer available.',
    'handoff_expired': 'This workflow hand-off expired. Ask again to get a new one.',
    'handoff_denied': 'This workflow hand-off was declined.',
    'handoff_accepted': 'This workflow hand-off was already accepted.',
    'handoff_busy': 'This workflow hand-off is being accepted. Try again in a moment.',
    'handoff_kind_mismatch': 'This is not a workflow hand-off.',
    'handoff_run_conflict': 'The workflow was created, but its run could not be started.',
    'workflow_deleted': 'The workflow this hand-off created was deleted.',
    'handoff_limit_changed': 'The document limit changed since this hand-off was prepared. Ask again to get a new one.',
    'handoff_invalid': 'This workflow hand-off is not valid. Ask again to get a new one.',
    'handoff_agent_unsupported': 'A hand-off workflow can use only your own agents.',
    'handoff_daily_limit': 'You reached the daily limit for workflow hand-offs. Try again later.',
    'handoff_queue_failed': 'The workflow was created, but its run could not be queued. Try again.',
    'service_unavailable': 'The service is temporarily unavailable. Try again.',
}

_ERROR_STATUS = {
    'invalid_request': 400,
    'handoff_edit_invalid': 400,
    'workflow_handoff_disabled': 403,
    'workflow_role_required': 403,
    'workflow_shared_conversation': 403,
    'handoff_results_off': 403,
    'handoff_access_lost': 403,
    'run_not_found': 404,
    'handoff_not_found': 404,
    'handoff_unavailable': 409,
    'handoff_expired': 409,
    'handoff_denied': 409,
    'handoff_accepted': 409,
    'handoff_busy': 409,
    'handoff_kind_mismatch': 409,
    'handoff_run_conflict': 409,
    'workflow_deleted': 409,
    'handoff_limit_changed': 409,
    'handoff_invalid': 422,
    'handoff_agent_unsupported': 422,
    'handoff_daily_limit': 429,
    'handoff_queue_failed': 503,
    'service_unavailable': 503,
}

# The closed codes a gate reason becomes.
_GATE_ERRORS = {
    'workflow_handoff_disabled': 'workflow_handoff_disabled',
    'workflow_results_disabled': 'handoff_results_off',
    'workflow_role_required': 'workflow_role_required',
    WORKFLOW_REASON_SHARED_CONVERSATION: 'workflow_shared_conversation',
}

# Draft-service codes a response may name; anything else is reported as an invalid workflow.
_FORBIDDEN_DRAFT_CODES = frozenset({'workflows_unavailable', 'not_allowed'})
_ACCESS_LOST_DRAFT_CODES = frozenset({
    'scope_unavailable', 'reference_unauthorized', 'reference_unknown', 'agent_unavailable',
})
_SAME_DRAFT_CODES = ('handoff_limit_changed', 'handoff_kind_mismatch', 'handoff_agent_unsupported')
_CONFLICT_DRAFT_CODES = frozenset({
    'quota_exceeded', 'workflow_conflict', 'file_sync_source_unavailable', 'workflow_unavailable',
    'workflow_definition_conflict', 'workflow_deleted',
})
_INVALID_DRAFT_CODES = frozenset({
    'blueprint_invalid', 'unsupported_field', 'too_many_tasks', 'trigger_invalid', 'cadence_below_minimum',
    'invalid_workflow', 'invalid_workflow_definition', 'invalid_workflow_settings', 'invalid_workflow_alerts',
    'handoff_edit_invalid', 'handoff_loop_limit',
})
_KNOWN_DRAFT_CODES = (
    _FORBIDDEN_DRAFT_CODES | _ACCESS_LOST_DRAFT_CODES | frozenset(_SAME_DRAFT_CODES)
    | _CONFLICT_DRAFT_CODES | _INVALID_DRAFT_CODES
)
_INVALID_WORKFLOW_MESSAGE = 'Invalid workflow settings. Review the task, runner, trigger, and document inputs.'
_SAFE_POINTER = re.compile(r'^(/[A-Za-z0-9_-]{1,64}){0,8}$')
# A message that looks like it carries an identifier is replaced with fixed text.
_ID_LIKE = re.compile(r'[0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{12}')


class HandoffError(Exception):
    """A refused hand-off request: a closed code, its HTTP status and fixed text."""

    def __init__(self, code, *, status=None, errors=(), state=None, reason=None):
        code = code if code in ERROR_MESSAGES else 'invalid_request'
        super().__init__(code)
        self.code = code
        self.status = status or _ERROR_STATUS.get(code, 400)
        self.message = ERROR_MESSAGES[code]
        self.errors = [dict(error) for error in errors or () if isinstance(error, dict)]
        self.state = state
        self.reason = reason

    def payload(self):
        body = {'error': self.message, 'code': self.code, 'errors': deepcopy(self.errors)}
        if self.state:
            body['state'] = self.state
        if self.reason:
            body['reason'] = self.reason
        return body


def error_payload(code, **options):
    """Return ``(body, status)`` for a closed hand-off error code."""
    error = HandoffError(code, **options)
    return error.payload(), error.status


class _AlreadyCreated(Exception):
    """The claim found the hand-off already created: the accept continues with that workflow."""

    def __init__(self, decision=None):
        super().__init__('already_created')
        self.decision = deepcopy(decision) if isinstance(decision, dict) else None


@dataclass
class _Handoff:
    handoff_id: str
    step_id: str
    producer: dict
    sidecar: dict
    blueprint_ok: bool
    decision: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(value):
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode('utf-8', errors='replace')).hexdigest()


def _log(message, level=logging.INFO, *, run_id=None, conversation_id=None, step_id=None, handoff_id=None,
         workflow_id=None, **fields):
    extra = {
        'stage': _LOG_STAGE,
        **workflow_log_context(run_id=run_id, conversation_id=conversation_id, step_id=step_id),
    }
    for name, value in (('handoff_id', handoff_id), ('workflow_id', workflow_id)):
        digest = _hash(value)
        if digest:
            extra[f'{name}_hash'] = digest
    extra.update({key: value for key, value in fields.items() if value is not None})
    log_event(f'{_LOG_PREFIX} {message}', extra=extra, level=level)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value):
    return value.isoformat()


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def workflow_handoff_request_id(user_id, handoff_id):
    """The run request id an accepted hand-off queues under: the same for every retry."""
    if not isinstance(user_id, str) or not user_id or not isinstance(handoff_id, str) or not handoff_id:
        raise ValueError('A hand-off run request needs a user id and a hand-off id.')
    return str(uuid.uuid5(WORKFLOW_HANDOFF_REQUEST_NAMESPACE, f'{user_id}:{handoff_id}'))


def _public_errors(errors):
    public = []
    for error in errors or ():
        if not isinstance(error, dict):
            continue
        code = _text(error.get('code'))
        message = ' '.join(_text(error.get('message')).split())[:DRAFT_MESSAGE_MAX_LENGTH]
        if code not in _KNOWN_DRAFT_CODES:
            code, message = 'invalid_workflow', _INVALID_WORKFLOW_MESSAGE
        elif not message or _ID_LIKE.search(message):
            message = _INVALID_WORKFLOW_MESSAGE
        path = _text(error.get('path'))
        public.append({'code': code, 'message': message, 'path': path if _SAFE_POINTER.match(path) else ''})
        if len(public) >= DRAFT_MAX_ERRORS:
            break
    return public


def _draft_failure(errors, *, edited):
    """The closed hand-off error for a refused dry run or create."""
    public = _public_errors(errors) or [
        {'code': 'invalid_workflow', 'message': _INVALID_WORKFLOW_MESSAGE, 'path': ''},
    ]
    codes = [error['code'] for error in public]
    if any(code in _FORBIDDEN_DRAFT_CODES for code in codes):
        return HandoffError('workflow_handoff_disabled', errors=public)
    if any(code in _ACCESS_LOST_DRAFT_CODES for code in codes):
        return HandoffError('handoff_access_lost', errors=public)
    for code in _SAME_DRAFT_CODES:
        if code in codes:
            return HandoffError(code, errors=public)
    if any(code in _CONFLICT_DRAFT_CODES for code in codes):
        return HandoffError('handoff_unavailable', errors=public)
    return HandoffError('handoff_edit_invalid' if edited else 'handoff_invalid', errors=public)


# ---------------------------------------------------------------------------
# Resolution: the hand-offs a run shows, verified against the run that produced each
# ---------------------------------------------------------------------------

def _plan_steps(run, capability_id):
    plan = run.get('plan') if isinstance(run.get('plan'), dict) else {}
    return [
        step for step in plan.get('steps') or ()
        if isinstance(step, dict) and step.get('capability_id') == capability_id
        and step.get('enabled', True) is not False and isinstance(step.get('step_id'), str) and step['step_id']
    ]


def _plan_step(run, step_id):
    return next(
        (step for step in _plan_steps(run, CAPABILITY_WORKFLOW_HANDOFF) if step['step_id'] == step_id), None,
    )


def _execution_entry(run, step_id):
    return next(
        (
            entry for entry in run.get('execution_steps') or ()
            if isinstance(entry, dict) and entry.get('step_id') == step_id
        ),
        None,
    )


def _sidecar(record, key=_SIDECAR_KEY):
    value = record.get(key) if isinstance(record, dict) else None
    return value if isinstance(value, dict) else None


def _inherited_run_id(run, step_id):
    inherited = run.get('inherited_checkpoints') if isinstance(run.get('inherited_checkpoints'), dict) else {}
    reference = inherited.get(step_id) if isinstance(inherited.get(step_id), dict) else {}
    provenance = reference.get('provenance') if isinstance(reference.get('provenance'), dict) else {}
    value = provenance.get('run_id')
    return value if isinstance(value, str) and value else None


def _producer_run_id(run, step_id, sidecar, entry):
    """The run that produced a step's hand-off: this run, or the earlier attempt it reused."""
    for value in ((sidecar or {}).get('origin_run_id'), (entry or {}).get('reused_from_run_id')):
        if isinstance(value, str) and value:
            return value
    return _inherited_run_id(run, step_id)


def _same_turn(producer, run):
    return (
        isinstance(producer, dict) and producer.get('conversation_id') == run.get('conversation_id')
        and producer.get('turn_id') == run.get('turn_id') and not is_legacy_plan(producer.get('plan'))
    )


def _sidecar_matches(sidecar, *, handoff_id, producer_id, step_id, conversation_id, user_id):
    return (
        sidecar.get('version') == WORKFLOW_HANDOFF_VERSION and sidecar.get('handoff_id') == handoff_id
        and sidecar.get('origin_run_id') == producer_id and sidecar.get('step_id') == step_id
        and sidecar.get('conversation_id') == conversation_id and sidecar.get('requester_user_id') == user_id
    )


def _blueprint_matches(sidecar):
    blueprint = sidecar.get('blueprint')
    if not isinstance(blueprint, dict) or not isinstance(sidecar.get('blueprint_digest'), str):
        return False
    try:
        return canonical_digest(blueprint) == sidecar['blueprint_digest']
    except Exception:
        return False


def _resolve_handoffs(run, user_id):
    """Every hand-off ``run`` shows, verified against the run that produced it."""
    run_id = run.get('id')
    conversation_id = run.get('conversation_id')
    handoffs = []
    for step in _plan_steps(run, CAPABILITY_WORKFLOW_HANDOFF):
        step_id = step['step_id']
        entry = _execution_entry(run, step_id)
        sidecar = _sidecar(entry)
        if sidecar is None:
            record = get_orchestration_step_record(run_id, step_id, user_id, conversation_id)
            sidecar = _sidecar(record)
            entry = entry or record
        producer_id = _producer_run_id(run, step_id, sidecar, entry)
        if not producer_id:
            continue
        producer = run
        if producer_id != run_id:
            producer = get_orchestration_run(producer_id, user_id, conversation_id=conversation_id, strict=True)
            if not _same_turn(producer, run):
                continue
            if sidecar is None:
                sidecar = _sidecar(_execution_entry(producer, step_id)) or _sidecar(
                    get_orchestration_step_record(producer_id, step_id, user_id, conversation_id),
                )
        if sidecar is None or _plan_step(producer, step_id) is None or producer.get('checkpoints_deleted'):
            continue
        handoff_id = workflow_handoff_id(producer_id, step_id)
        if not _sidecar_matches(
            sidecar, handoff_id=handoff_id, producer_id=producer_id, step_id=step_id,
            conversation_id=conversation_id, user_id=user_id,
        ):
            _log(
                'A workflow hand-off did not match the run that produced it.', logging.WARNING,
                run_id=run_id, conversation_id=conversation_id, step_id=step_id, code='handoff_integrity_mismatch',
            )
            continue
        decisions = producer.get(WORKFLOW_HANDOFF_DECISIONS_FIELD)
        decision = decisions.get(handoff_id) if isinstance(decisions, dict) else None
        handoffs.append(_Handoff(
            handoff_id=handoff_id, step_id=step_id, producer=producer, sidecar=sidecar,
            blueprint_ok=_blueprint_matches(sidecar), decision=decision if isinstance(decision, dict) else None,
        ))
    return handoffs


def _is_proposal_id(run, value):
    """Whether ``value`` names a workflow proposal in ``run``: a Phase 4 card, not a hand-off."""
    for step in _plan_steps(run, CAPABILITY_WORKFLOW_PROPOSE):
        step_id = step['step_id']
        entry = _execution_entry(run, step_id) or {}
        candidates = (
            run.get('id'), (_sidecar(entry, _PROPOSAL_SIDECAR_KEY) or {}).get('origin_run_id'),
            entry.get('reused_from_run_id'), _inherited_run_id(run, step_id),
        )
        for producer_id in candidates:
            if isinstance(producer_id, str) and producer_id and workflow_proposal_id(producer_id, step_id) == value:
                return True
    return False


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _read_workflow(user_id, handoff_id):
    """The workflow this hand-off created, if it still exists; a storage failure raises."""
    workflow_id = orchestration_workflow_id(user_id, handoff_id)
    try:
        record = functions_personal_workflows.cosmos_personal_workflows_container.read_item(
            item=workflow_id, partition_key=user_id,
        )
    except exceptions.CosmosResourceNotFoundError:
        return None
    if not isinstance(record, dict) or record.get('id') != workflow_id or record.get('user_id') != user_id:
        return None
    origin = record.get('origin') if isinstance(record.get('origin'), dict) else {}
    if origin.get('proposal_id') != handoff_id or record.get('deleting') or record.get('status') == 'deleting':
        return None
    if not is_handoff_workflow(record, user_id):
        raise HandoffError('handoff_kind_mismatch')
    return record


def _effective_decision(decision, now):
    """The decision that holds now: a claim that went stale gives way to the one it replaced."""
    if not isinstance(decision, dict):
        return None
    state = decision.get('state')
    if state == DECISION_CREATING:
        claimed_at = _parse_time(decision.get('claimed_at'))
        if claimed_at is not None and abs((now - claimed_at).total_seconds()) < HANDOFF_CLAIM_SECONDS:
            return decision
        previous = decision.get('previous')
        return (
            previous if isinstance(previous, dict) and previous.get('state') in (DECISION_CREATED, DECISION_QUEUED)
            else None
        )
    return decision if state in (DECISION_CREATED, DECISION_QUEUED, DECISION_DENIED) else None


def _expired(sidecar, now):
    expires_at = _parse_time(sidecar.get('expires_at'))
    return expires_at is None or now >= expires_at


def _ready(handoff):
    sidecar = handoff.sidecar
    loop_limit = sidecar.get('loop_limit')
    return (
        sidecar.get('status') == WORKFLOW_HANDOFF_STATUS_READY and handoff.blueprint_ok
        and bool(_text(sidecar.get('created_at'))) and type(loop_limit) is int and loop_limit >= 1
        and isinstance(sidecar.get('handles'), dict)
    )


def _sidecar_reason(handoff):
    reason = handoff.sidecar.get('reason')
    return reason if isinstance(reason, str) and reason in WORKFLOW_HANDOFF_REASON_TEXT else None


def _not_ready(handoff):
    if handoff.sidecar.get('status') == WORKFLOW_HANDOFF_STATUS_UNAVAILABLE:
        return HandoffError('handoff_unavailable', state=STATE_UNAVAILABLE, reason=_sidecar_reason(handoff))
    return HandoffError('handoff_invalid', state=STATE_INVALID, reason=_sidecar_reason(handoff))


def _gate(settings, identity, conversation):
    """The closed reason this requester cannot act on hand-offs here, or None."""
    reason = workflow_handoff_gate(settings, identity.get('roles'))
    if reason:
        return reason
    if not conversation_is_private(conversation, identity.get('user_id')):
        return WORKFLOW_REASON_SHARED_CONVERSATION
    return None


def _open_handoff(run, conversation, handoff_id, *, identity, settings, response_removed=None):
    """The hand-off a decision names, after every access check a decision needs."""
    if not _canonical_uuid(handoff_id):
        raise HandoffError('handoff_not_found')
    user_id = identity.get('user_id')
    if not isinstance(user_id, str) or not user_id or run.get('user_id') != user_id:
        # Only the requester acts on a hand-off; anyone else learns nothing about it.
        raise HandoffError('handoff_not_found')
    reason = _gate(settings, identity, conversation)
    if reason:
        raise HandoffError(_GATE_ERRORS.get(reason, 'workflow_handoff_disabled'))
    handoff = next((item for item in _resolve_handoffs(run, user_id) if item.handoff_id == handoff_id), None)
    if handoff is None:
        if _is_proposal_id(run, handoff_id):
            raise HandoffError('handoff_kind_mismatch')
        raise HandoffError('handoff_not_found')
    if response_removed is not None and response_removed():
        raise HandoffError('handoff_unavailable', state=STATE_UNAVAILABLE)
    return handoff


def _origin(handoff, *, edited):
    return {
        'source': WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
        'conversation_id': handoff.sidecar['conversation_id'],
        'orchestration_run_id': handoff.sidecar['origin_run_id'],
        'proposal_id': handoff.handoff_id,
        'created_at': handoff.sidecar['created_at'],
        'edited': bool(edited),
    }


def _user_info(identity):
    return {
        'userId': identity.get('user_id'),
        'email': identity.get('email'),
        'roles': list(identity.get('roles') or []),
    }


def _handles(handoff):
    handles = handoff.sidecar.get('handles')
    return deepcopy(handles) if isinstance(handles, dict) else {}


def _decide(handoff, user_id, mutate):
    return update_workflow_handoff_decision(
        handoff.producer['id'], user_id, handoff.producer['conversation_id'], handoff.handoff_id, mutate,
    )


def _log_context(handoff):
    return {
        'run_id': handoff.producer.get('id'), 'conversation_id': handoff.producer.get('conversation_id'),
        'step_id': handoff.step_id, 'handoff_id': handoff.handoff_id,
    }


# ---------------------------------------------------------------------------
# The durable runtime (imported when used; tests replace these)
# ---------------------------------------------------------------------------

def _workflow_run_id(user_id, workflow_id, request_id):
    from functions_workflow_runtime import workflow_run_id_for_request

    return workflow_run_id_for_request({'id': workflow_id, 'user_id': user_id}, request_id)


def _read_workflow_run(user_id, run_id):
    from config import cosmos_personal_workflow_runs_container

    try:
        return cosmos_personal_workflow_runs_container.read_item(item=run_id, partition_key=user_id)
    except exceptions.CosmosResourceNotFoundError:
        return None


def _queue_workflow_run(workflow, **options):
    from functions_workflow_runtime import queue_durable_workflow_run

    return queue_durable_workflow_run(workflow, **options)


def _runtime_terminal_states():
    from functions_workflow_runtime import RUNTIME_TERMINAL_STATES

    return RUNTIME_TERMINAL_STATES


def _runtime_errors():
    from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict

    return RuntimeUnavailable, WorkflowRuntimeConflict


def _count_recent_handoffs(user_id, since):
    return functions_personal_workflows.count_personal_handoff_workflows_since(user_id, since)


# ---------------------------------------------------------------------------
# Writes: the claim, its release, the created and queued records, and the run
# ---------------------------------------------------------------------------

def _claim(handoff, user_id, *, claim_id, mode, edited):
    """Claim the hand-off for this accept, or raise why it cannot be claimed."""

    def mutate(current):
        effective = _effective_decision(current, _now())
        state = (effective or {}).get('state')
        if state in (DECISION_CREATED, DECISION_QUEUED):
            raise _AlreadyCreated(effective)
        if state == DECISION_DENIED:
            raise HandoffError('handoff_denied', state=STATE_DENIED)
        if state == DECISION_CREATING:
            raise HandoffError('handoff_busy', state=STATE_CREATING)
        return {
            'state': DECISION_CREATING, 'claim_id': claim_id, 'claimed_at': _iso(_now()),
            'mode': mode, 'edited': bool(edited), 'previous': deepcopy(effective),
        }

    try:
        _decide(handoff, user_id, mutate)
    except ProposalDecisionBusy as exc:
        raise HandoffError('handoff_busy', state=STATE_CREATING) from exc
    except LookupError as exc:
        raise HandoffError('handoff_unavailable', state=STATE_UNAVAILABLE) from exc


def _release_claim(handoff, user_id, claim_id):
    """Give back a claim whose create failed, so the requester can accept again."""

    def mutate(current):
        if isinstance(current, dict) and current.get('state') == DECISION_CREATING and current.get('claim_id') == claim_id:
            previous = current.get('previous')
            return deepcopy(previous) if isinstance(previous, dict) else None
        return current

    try:
        _decide(handoff, user_id, mutate)
    except Exception as exc:
        _log(
            'A workflow hand-off claim was not released.', logging.WARNING,
            error_type=type(exc).__name__, **_log_context(handoff),
        )


def _record(handoff, user_id, decision, *, keep):
    """Write ``decision`` unless the stored one already says the same; never fails the accept."""

    def mutate(current):
        if isinstance(current, dict) and keep(current):
            return current
        return deepcopy(decision)

    try:
        _decide(handoff, user_id, mutate)
        return True
    except Exception as exc:
        _log(
            'A workflow hand-off decision was not recorded.', logging.WARNING,
            error_type=type(exc).__name__, decision_state=decision.get('state'), **_log_context(handoff),
        )
        return False


def _confirm_created(handoff, user_id, workflow_id):
    return _record(
        handoff, user_id, {'state': DECISION_CREATED, 'workflow_id': workflow_id, 'created_at': _iso(_now())},
        keep=lambda current: (
            current.get('state') in (DECISION_CREATED, DECISION_QUEUED) and current.get('workflow_id') == workflow_id
        ),
    )


def _record_queued(handoff, user_id, workflow_id, started):
    return _record(
        handoff, user_id,
        {
            'state': DECISION_QUEUED, 'workflow_id': workflow_id, 'run_id': started['run_id'],
            'chat_delivery': bool(started['chat_delivery']), 'queued_at': _iso(_now()),
        },
        keep=lambda current: (
            current.get('state') == DECISION_QUEUED and current.get('workflow_id') == workflow_id
            and current.get('run_id') == started['run_id']
        ),
    )


def _run_status(run):
    status = str((run or {}).get('status') or '').strip().lower() if isinstance(run, dict) else ''
    return status or STATE_QUEUED


def _queue(handoff, workflow, *, identity, settings):
    """Queue the hand-off's one durable run, or find the run an earlier accept queued."""
    user_id = identity['user_id']
    workflow_id = workflow['id']
    conversation_id = handoff.sidecar['conversation_id']
    request_id = workflow_handoff_request_id(user_id, handoff.handoff_id)
    runtime_unavailable, runtime_conflict = _runtime_errors()
    try:
        run_id = _workflow_run_id(user_id, workflow_id, request_id)
        existing = _read_workflow_run(user_id, run_id)
    except (AzureError, runtime_unavailable) as exc:
        raise HandoffError('handoff_queue_failed', state=STATE_CREATED) from exc
    if existing is not None:
        if existing.get('workflow_id') != workflow_id or existing.get('user_id') != user_id:
            raise HandoffError('handoff_unavailable', state=STATE_CREATED)
        if (
            str(existing.get('status') or '').strip().lower() in _runtime_terminal_states()
            or workflow.get('active_run_id') == run_id
        ):
            return {
                'run_id': run_id, 'status': _run_status(existing), 'queued': False,
                'chat_delivery': bool(chat_delivery_applies(existing, conversation_id)),
            }
        # A run record the workflow does not hold: queueing the same request finishes starting it.
    if workflow.get('durable_execution') is not True:
        raise HandoffError('handoff_unavailable', state=STATE_CREATED)
    sidecar = handoff.sidecar
    chat_delivery = chat_delivery_seed_for(
        settings, user_roles=identity.get('roles'), time_zone=sidecar.get('time_zone'),
        model_selection=deepcopy(sidecar.get('model_selection')), run_id=handoff.producer.get('id'),
    )
    producer = handoff.producer
    try:
        queued = _queue_workflow_run(
            {'id': workflow_id, 'user_id': user_id},
            actor_user_id=user_id,
            trigger_source=WORKFLOW_RUN_TRIGGER_SOURCE,
            request_id=request_id,
            chat_invocation={
                'version': WORKFLOW_RUN_VERSION,
                'source': WORKFLOW_RUN_TRIGGER_SOURCE,
                'conversation_id': conversation_id,
                'user_message_id': producer.get('user_message_id'),
                'orchestration_run_id': producer['id'],
                'attempt_root_run_id': producer.get('attempt_root_run_id') or producer['id'],
                'step_id': handoff.step_id,
                'requested_by': user_id,
                'requested_at': _iso(_now()),
                'handoff_id': handoff.handoff_id,
            },
            **({'chat_delivery': chat_delivery} if chat_delivery is not None else {}),
        )
    except runtime_conflict as exc:
        code = getattr(exc, 'code', None)
        raise HandoffError(
            'handoff_run_conflict', state=STATE_CREATED,
            reason=_CONFLICT_REASONS.get(code if isinstance(code, str) else None, REASON_NOT_STARTED),
        ) from exc
    except runtime_unavailable as exc:
        raise HandoffError('handoff_queue_failed', state=STATE_CREATED) from exc
    except PermissionError as exc:
        raise HandoffError('handoff_access_lost', state=STATE_CREATED) from exc
    except (ValueError, LookupError) as exc:
        raise HandoffError('handoff_unavailable', state=STATE_CREATED) from exc
    except AzureError as exc:
        raise HandoffError('handoff_queue_failed', state=STATE_CREATED) from exc
    run = queued.get('run') if isinstance(queued, dict) else None
    status = _run_status(run)
    return {
        'run_id': run_id, 'status': status, 'queued': True,
        # Only a run this accept started, carrying this chat's delivery record, is posted back here.
        'chat_delivery': bool(
            chat_delivery is not None and status in ('queued', 'running')
            and chat_delivery_applies(run, conversation_id)
        ),
    }


def _workflow_projection(workflow):
    return {
        'id': workflow.get('id'),
        'name': workflow.get('name') if isinstance(workflow.get('name'), str) else '',
        'is_enabled': workflow.get('is_enabled') is True,
    }


def _accepted_body(handoff, workflow, started, *, created):
    return {
        'handoff_id': handoff.handoff_id,
        'state': STATE_QUEUED,
        'created': bool(created),
        'workflow': _workflow_projection(workflow),
        'run': {'id': started['run_id'], 'status': started['status']},
        'chat_delivery': bool(started['chat_delivery']),
    }


def _start_existing(handoff, workflow, decision, *, identity, settings):
    """Finish an accept whose workflow exists: report its run, or queue the one it is missing."""
    user_id = identity['user_id']
    if (decision or {}).get('state') == DECISION_QUEUED and decision.get('workflow_id') == workflow.get('id'):
        run_id = decision.get('run_id')
        if isinstance(run_id, str) and run_id:
            try:
                run = _read_workflow_run(user_id, run_id)
            except Exception as exc:
                _log(
                    'A hand-off run could not be read.', logging.WARNING,
                    error_type=type(exc).__name__, **_log_context(handoff),
                )
                run = None
            started = {
                'run_id': run_id, 'status': _run_status(run) if run is not None else STATE_QUEUED,
                'chat_delivery': decision.get('chat_delivery') is True,
            }
            return 200, _accepted_body(handoff, workflow, started, created=False), None
    started = _queue(handoff, workflow, identity=identity, settings=settings)
    _record_queued(handoff, user_id, workflow['id'], started)
    _log(
        'A workflow hand-off run was queued for an existing workflow.',
        queued=started['queued'], chat_delivery=started['chat_delivery'], **_log_context(handoff),
    )
    return 200, _accepted_body(handoff, workflow, started, created=False), None


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def _accept_request(body, run):
    if not isinstance(body, dict) or set(body) - ACCEPT_FIELDS:
        raise HandoffError('invalid_request')
    conversation_id = body.get('conversation_id')
    if conversation_id is not None and conversation_id != run.get('conversation_id'):
        raise HandoffError('invalid_request')
    mode = body.get('mode')
    if mode not in ACCEPT_MODES:
        raise HandoffError('invalid_request')
    workflow = body.get('workflow')
    if mode == MODE_EDITED:
        if not isinstance(workflow, dict) or not workflow:
            raise HandoffError('invalid_request')
        return {'mode': mode, 'workflow': deepcopy(workflow)}
    if workflow is not None:
        raise HandoffError('invalid_request')
    return {'mode': mode, 'workflow': None}


def _dry_run(handoff, identity, settings):
    """The hand-off's workflow rebuilt as proposed, with fresh authorization."""
    try:
        outcome = dry_run_handoff_workflow(
            identity['user_id'], deepcopy(handoff.sidecar['blueprint']), _handles(handoff),
            origin=_origin(handoff, edited=False), settings=settings, user_info=_user_info(identity),
            loop_limit=handoff.sidecar['loop_limit'],
        )
    except WorkflowLoopLimitError as exc:
        raise HandoffError('handoff_limit_changed') from exc
    if not isinstance(outcome, dict) or not outcome.get('ok'):
        raise _draft_failure((outcome or {}).get('errors') if isinstance(outcome, dict) else None, edited=False)
    return outcome


def _edited(handoff, workflow_data, *, identity, settings):
    """Whether the user's edit changes what the hand-off would create. Unsure means edited."""
    user_id = identity['user_id']
    try:
        proposed = dry_run_handoff_workflow(
            user_id, deepcopy(handoff.sidecar['blueprint']), _handles(handoff),
            origin=_origin(handoff, edited=False), settings=settings, user_info=_user_info(identity),
            loop_limit=handoff.sidecar['loop_limit'],
        )
        if not isinstance(proposed, dict) or not proposed.get('ok'):
            return True
        excluded = {'id', *URL_ACCESS_AUTHORIZATION_FIELDS, *HANDOFF_SERVER_FIELDS}
        draft = {key: deepcopy(value) for key, value in workflow_data.items() if key not in excluded}
        draft['is_enabled'] = False
        candidate = dry_run_personal_workflow(user_id, draft, actor_user_id=user_id, settings=settings)
        if not isinstance(candidate, dict) or not candidate.get('ok'):
            return True
        return bool(workflow_origin_material_change(proposed['workflow'], candidate['workflow']))
    except Exception as exc:
        _log(
            'A workflow hand-off edit could not be compared.', logging.WARNING,
            error_type=type(exc).__name__, **_log_context(handoff),
        )
        return True


def _check_daily_limit(user_id, settings, now):
    limit = get_chat_orchestration_max_workflow_handoffs_per_day(settings)
    try:
        count = _count_recent_handoffs(user_id, _iso(now - HANDOFF_DAILY_WINDOW))
    except Exception as exc:
        _log('The workflow hand-off daily count could not be read.', logging.WARNING, error_type=type(exc).__name__)
        raise HandoffError('service_unavailable') from exc
    if count >= limit:
        raise HandoffError('handoff_daily_limit')


def _create(handoff, request, *, identity, settings, edited):
    user_id = identity['user_id']
    options = {
        'origin': _origin(handoff, edited=edited), 'settings': settings, 'user_info': _user_info(identity),
        'loop_limit': handoff.sidecar['loop_limit'],
    }
    if request['mode'] == MODE_EDITED:
        return create_personal_handoff_workflow_from_payload(user_id, deepcopy(request['workflow']), **options)
    return create_personal_handoff_workflow(
        user_id, deepcopy(handoff.sidecar['blueprint']), _handles(handoff), **options,
    )


def accept_handoff(run, conversation, handoff_id, body, *, identity, settings, response_removed):
    """Create the hand-off's one-time workflow disabled and queue its one durable run.

    Returns ``(status, body, created_workflow)``: 201 when this call created the workflow, 200
    when it already existed, and ``created_workflow`` only when it was created. A run that could
    not be queued after this call created the workflow returns the closed error's status and body
    with that workflow, so its creation is still recorded; a retry queues the same run. Raises
    ``HandoffError`` with a closed code; any other exception is a storage failure.
    """
    request = _accept_request(body, run)
    handoff = _open_handoff(
        run, conversation, handoff_id, identity=identity, settings=settings, response_removed=response_removed,
    )
    user_id = identity['user_id']
    now = _now()
    decision = _effective_decision(handoff.decision, now)
    workflow = _read_workflow(user_id, handoff.handoff_id)
    if workflow is not None:
        return _start_existing(handoff, workflow, decision, identity=identity, settings=settings)
    state = (decision or {}).get('state')
    if state in (DECISION_CREATED, DECISION_QUEUED):
        raise HandoffError('workflow_deleted', state=state)
    if state == DECISION_DENIED:
        raise HandoffError('handoff_denied', state=STATE_DENIED)
    if state == DECISION_CREATING:
        raise HandoffError('handoff_busy', state=STATE_CREATING)
    if _expired(handoff.sidecar, now):
        raise HandoffError('handoff_expired', state=STATE_EXPIRED)
    if not _ready(handoff):
        raise _not_ready(handoff)
    edited = request['mode'] == MODE_EDITED and _edited(
        handoff, request['workflow'], identity=identity, settings=settings,
    )
    _check_daily_limit(user_id, settings, now)

    claim_id = uuid.uuid4().hex
    try:
        _claim(handoff, user_id, claim_id=claim_id, mode=request['mode'], edited=edited)
    except _AlreadyCreated as already:
        workflow = _read_workflow(user_id, handoff.handoff_id)
        if workflow is None:
            raise HandoffError('workflow_deleted', state=STATE_CREATED)
        return _start_existing(handoff, workflow, already.decision, identity=identity, settings=settings)
    try:
        outcome = _create(handoff, request, identity=identity, settings=settings, edited=edited)
    except WorkflowLoopLimitError as exc:
        _release_claim(handoff, user_id, claim_id)
        raise HandoffError('handoff_limit_changed') from exc
    except Exception:
        _release_claim(handoff, user_id, claim_id)
        raise
    if not isinstance(outcome, dict) or not outcome.get('ok') or not isinstance(outcome.get('workflow'), dict):
        _release_claim(handoff, user_id, claim_id)
        raise _draft_failure(
            outcome.get('errors') if isinstance(outcome, dict) else None, edited=request['mode'] == MODE_EDITED,
        )
    created_workflow = outcome['workflow']
    created = outcome.get('created') is True
    workflow_id = orchestration_workflow_id(user_id, handoff.handoff_id)
    _confirm_created(handoff, user_id, workflow_id)
    _log(
        'A workflow hand-off created its workflow.', created=created, mode=request['mode'], edited=bool(edited),
        workflow_id=workflow_id, **_log_context(handoff),
    )
    started_workflow = {**created_workflow, 'id': workflow_id}
    try:
        started = _queue(handoff, started_workflow, identity=identity, settings=settings)
    except Exception as exc:
        # The workflow exists, so the caller still records its creation; a retry queues the same run.
        error = exc if isinstance(exc, HandoffError) else HandoffError('handoff_queue_failed', state=STATE_CREATED)
        _log(
            'A workflow hand-off run was not queued.', logging.WARNING, code=error.code,
            error_type=type(exc).__name__, workflow_id=workflow_id, **_log_context(handoff),
        )
        return error.status, error.payload(), (created_workflow if created else None)
    _record_queued(handoff, user_id, workflow_id, started)
    _log(
        'A workflow hand-off run was queued.', queued=started['queued'], chat_delivery=started['chat_delivery'],
        workflow_id=workflow_id, **_log_context(handoff),
    )
    body = _accepted_body(handoff, started_workflow, started, created=created)
    return (201 if created else 200), body, (created_workflow if created else None)


def deny_handoff(run, conversation, handoff_id, body, *, identity, settings):
    """Decline a hand-off. Declining again is a no-op; an accepted hand-off cannot be declined."""
    if not isinstance(body, dict) or set(body) - DENY_FIELDS:
        raise HandoffError('invalid_request')
    conversation_id = body.get('conversation_id')
    if conversation_id is not None and conversation_id != run.get('conversation_id'):
        raise HandoffError('invalid_request')
    handoff = _open_handoff(run, conversation, handoff_id, identity=identity, settings=settings)
    user_id = identity['user_id']
    if _read_workflow(user_id, handoff.handoff_id) is not None:
        raise HandoffError('handoff_accepted', state=STATE_CREATED)
    now = _now()
    decision = _effective_decision(handoff.decision, now)
    state = (decision or {}).get('state')
    if state == DECISION_DENIED:
        return 200, {'handoff_id': handoff.handoff_id, 'state': STATE_DENIED}
    if state in (DECISION_CREATED, DECISION_QUEUED):
        raise HandoffError('handoff_accepted', state=state)
    if state == DECISION_CREATING:
        # An accept in progress may still release its claim, so this is busy rather than accepted.
        raise HandoffError('handoff_busy', state=STATE_CREATING)
    if _expired(handoff.sidecar, now):
        raise HandoffError('handoff_expired', state=STATE_EXPIRED)

    def mutate(current):
        effective = _effective_decision(current, _now())
        current_state = (effective or {}).get('state')
        if current_state == DECISION_DENIED:
            return current
        if current_state in (DECISION_CREATED, DECISION_QUEUED):
            raise HandoffError('handoff_accepted', state=current_state)
        if current_state == DECISION_CREATING:
            raise HandoffError('handoff_busy', state=STATE_CREATING)
        return {'state': DECISION_DENIED, 'denied_at': _iso(_now())}

    try:
        _decide(handoff, user_id, mutate)
    except ProposalDecisionBusy as exc:
        raise HandoffError('handoff_busy', state=STATE_CREATING) from exc
    except LookupError as exc:
        raise HandoffError('handoff_unavailable', state=STATE_UNAVAILABLE) from exc
    _log('A workflow hand-off was declined.', **_log_context(handoff))
    return 200, {'handoff_id': handoff.handoff_id, 'state': STATE_DENIED}


# ---------------------------------------------------------------------------
# Reads: the card's status and the editor's draft
# ---------------------------------------------------------------------------

def _status_workflow(handoff, user_id):
    """The hand-off's workflow for its card: None when it does not exist, False when it could not be read."""
    try:
        return _read_workflow(user_id, handoff.handoff_id)
    except Exception as exc:
        _log(
            'A hand-off workflow could not be read.', logging.WARNING,
            error_type=type(exc).__name__, **_log_context(handoff),
        )
        return False


def _assess(handoff, *, blocked_reason, removed, workflow, now):
    """``(state, reason)`` for a hand-off's card.

    Like the proposal card, a closed gate discloses nothing, not even a decision, and neither
    does a run whose response content review removed. Once the workflow exists it is the
    authority: if the queued decision was never recorded the hand-off shows ``created``, which an
    accept finishes without a second run.
    """
    if blocked_reason:
        return STATE_UNAVAILABLE, blocked_reason
    if removed:
        return STATE_UNAVAILABLE, REASON_CONTENT_REVIEW
    decision = _effective_decision(handoff.decision, now)
    state = (decision or {}).get('state')
    if isinstance(workflow, dict):
        if state == DECISION_QUEUED and decision.get('workflow_id') == workflow.get('id'):
            return STATE_QUEUED, None
        return STATE_CREATED, None
    if state in (DECISION_QUEUED, DECISION_CREATED, DECISION_CREATING, DECISION_DENIED):
        return state, None
    if not _ready(handoff):
        error = _not_ready(handoff)
        return error.state, error.reason
    if _expired(handoff.sidecar, now):
        return STATE_EXPIRED, None
    return STATE_PENDING, None


def _actions(handoff, state, now):
    if state == STATE_PENDING:
        return [ACTION_ACCEPT, ACTION_EDIT, ACTION_DENY]
    if state == STATE_CREATED:
        return [ACTION_ACCEPT]
    # Like a proposal, a hand-off can be declined until it is decided or expires, even one that
    # cannot be accepted.
    if (
        state in (STATE_UNAVAILABLE, STATE_INVALID) and _effective_decision(handoff.decision, now) is None
        and not _expired(handoff.sidecar, now)
    ):
        return [ACTION_DENY]
    return []


def _describe(handoff, *, state, reason, actions, disclosed, workflow, user_id):
    summary = handoff.sidecar.get('summary')
    disclosure = handoff.sidecar.get('disclosure')
    item = {
        'handoff_id': handoff.handoff_id,
        'step_id': handoff.step_id,
        'state': state,
        'reason': reason,
        'created_at': handoff.sidecar.get('created_at'),
        'expires_at': handoff.sidecar.get('expires_at'),
        'actions': actions,
        'summary': deepcopy(summary) if disclosed and isinstance(summary, dict) else None,
        'disclosure': deepcopy(disclosure) if disclosed and isinstance(disclosure, dict) else None,
    }
    decision = handoff.decision if isinstance(handoff.decision, dict) else {}
    if state in (STATE_CREATED, STATE_QUEUED):
        if workflow is None:
            item['reason'] = 'workflow_deleted'
            item['actions'] = []
        elif isinstance(workflow, dict):
            item['workflow'] = _workflow_projection(workflow)
    run_id = decision.get('run_id') if state == STATE_QUEUED else None
    if isinstance(run_id, str) and run_id:
        run = {'id': run_id}
        try:
            record = _read_workflow_run(user_id, run_id)
        except Exception as exc:
            _log(
                'A hand-off run could not be read.', logging.WARNING,
                error_type=type(exc).__name__, **_log_context(handoff),
            )
            record = None
        if isinstance(record, dict):
            run['status'] = _run_status(record)
        item['run'] = run
        item['chat_delivery'] = decision.get('chat_delivery') is True
    return item


def handoff_status(run, conversation, *, identity, settings, response_removed):
    """Every workflow hand-off ``run`` shows, for its requester's hand-off card.

    ``response_removed`` is called at most once, and only when the requester may act on
    hand-offs here, to learn whether content review removed the run's response.
    """
    user_id = identity.get('user_id')
    if not isinstance(user_id, str) or not user_id or run.get('user_id') != user_id:
        raise HandoffError('run_not_found')
    now = _now()
    blocked_reason = _gate(settings, identity, conversation)
    handoffs = _resolve_handoffs(run, user_id)
    removed = bool(handoffs) and not blocked_reason and bool(response_removed())
    items = []
    for handoff in handoffs:
        # A closed gate or a removed response discloses nothing, so the workflow is not read.
        workflow = None if blocked_reason or removed else _status_workflow(handoff, user_id)
        state, reason = _assess(
            handoff, blocked_reason=blocked_reason, removed=removed, workflow=workflow, now=now,
        )
        items.append(_describe(
            handoff, state=state, reason=reason, workflow=workflow, user_id=user_id,
            # A closed gate refuses every decision, so it offers none.
            actions=[] if blocked_reason else _actions(handoff, state, now),
            disclosed=not blocked_reason and not removed and handoff.blueprint_ok,
        ))
    return {'run_id': run.get('id'), 'handoffs': items}


def handoff_draft(run, conversation, handoff_id, *, identity, settings, response_removed):
    """The hand-off's workflow as the editor shows it, for an edit before accepting."""
    handoff = _open_handoff(
        run, conversation, handoff_id, identity=identity, settings=settings, response_removed=response_removed,
    )
    user_id = identity['user_id']
    if _read_workflow(user_id, handoff.handoff_id) is not None:
        raise HandoffError('handoff_accepted', state=STATE_CREATED)
    now = _now()
    decision = _effective_decision(handoff.decision, now)
    state = (decision or {}).get('state')
    if state in (DECISION_CREATED, DECISION_QUEUED):
        raise HandoffError('workflow_deleted', state=state)
    if state == DECISION_DENIED:
        raise HandoffError('handoff_denied', state=STATE_DENIED)
    if state == DECISION_CREATING:
        raise HandoffError('handoff_busy', state=STATE_CREATING)
    if _expired(handoff.sidecar, now):
        raise HandoffError('handoff_expired', state=STATE_EXPIRED)
    if not _ready(handoff):
        raise _not_ready(handoff)
    outcome = _dry_run(handoff, identity, settings)
    built = outcome['workflow']
    excluded = {*DRAFT_SERVER_FIELDS, *HANDOFF_SERVER_FIELDS}
    workflow = {key: deepcopy(value) for key, value in built.items() if key not in excluded}
    return {
        'handoff_id': handoff.handoff_id,
        'workflow': workflow,
        'url_access_note': URL_ACCESS_NOTE,
    }


__all__ = [
    'ACCEPT_FIELDS',
    'ACCEPT_MODES',
    'DECISION_CREATED',
    'DECISION_CREATING',
    'DECISION_DENIED',
    'DECISION_QUEUED',
    'DENY_FIELDS',
    'ERROR_MESSAGES',
    'HANDOFF_CLAIM_SECONDS',
    'HANDOFF_DAILY_WINDOW',
    'HandoffError',
    'MODE_AS_PROPOSED',
    'MODE_EDITED',
    'SERVICE_UNAVAILABLE_CODE',
    'WORKFLOW_HANDOFF_REQUEST_NAMESPACE',
    'accept_handoff',
    'deny_handoff',
    'error_payload',
    'handoff_draft',
    'handoff_status',
    'workflow_handoff_request_id',
]