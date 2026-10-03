# functions_orchestration_workflow_proposals.py
"""Decisions on workflow proposals from chat orchestration: status, accept, deny and draft.

Version: 0.261.207
Implemented in: 0.261.207

A plan's ``workflow_propose`` step describes a personal workflow and creates nothing
(``functions_orchestration_workflows``). The server-only sidecar on its step record is what the
proposal card shows and what this module decides on:

* ``proposal_status`` lists the proposals a run shows, each with its state and the actions the
  card may offer. The requester also gets the full description: every task's title and complete
  instructions, similar workflows they already have and the Microsoft 365 access it needs;
* ``accept_proposal`` creates the workflow once, paused or enabled, through the workflow draft
  service, from the proposal's blueprint or from the requester's edited editor draft;
* ``deny_proposal`` records that the requester declined the proposal;
* ``proposal_draft`` returns the proposal as a workflow editor draft and writes nothing.

A run that reuses a proposal from an earlier attempt (a retry) shows the proposal of the run that
produced it, and every decision is stored on that producing run, in its
``workflow_proposal_decisions`` map, through the same compare-and-swap loop as other run
updates. The workflow itself, point-read by the id derived from the proposal, is the authority on
whether a proposal was accepted, so a lost decision write never hides a workflow or creates a
second one.

Callers authorize the run and its conversation first; nothing here reads Flask state. Logs carry
ids and codes only: never names, instructions or catalog text.
"""

import logging
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from azure.cosmos import exceptions

import functions_personal_workflows
from functions_appinsights import log_event, workflow_log_context
from functions_m365_workflow_binding import M365_WAITING_STATES
from functions_orchestration_registry import CAPABILITY_WORKFLOW_PROPOSE
from functions_orchestration_result_contracts import canonical_digest
from functions_orchestration_runs import (
    WORKFLOW_PROPOSAL_DECISIONS_FIELD,
    ProposalDecisionBusy,
    get_orchestration_run,
    get_orchestration_step_record,
    update_workflow_proposal_decision,
)
from functions_orchestration_schema import is_legacy_plan
from functions_orchestration_workflow_context import (
    WORKFLOW_REASON_DISABLED,
    WORKFLOW_REASON_ROLE_REQUIRED,
    WORKFLOW_REASON_SHARED_CONVERSATION,
    conversation_is_private,
    workflow_planning_gate,
)
from functions_orchestration_workflows import (
    WORKFLOW_PROPOSAL_STATUS_READY,
    WORKFLOW_PROPOSAL_VERSION,
    workflow_proposal_id,
)
from functions_workflow_definitions import workflow_origin_material_change
from functions_workflow_drafts import (
    DRAFT_MAX_ERRORS,
    DRAFT_MESSAGE_MAX_LENGTH,
    URL_ACCESS_AUTHORIZATION_FIELDS,
    WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
    create_personal_workflow_from_blueprint,
    create_personal_workflow_from_payload,
    dry_run_personal_workflow,
    dry_run_workflow_blueprint,
    orchestration_workflow_id,
)


_LOG_PREFIX = '[ORCHESTRATION_WORKFLOW_PROPOSALS]'

# A claim older than this no longer blocks another accept: its request stopped before finishing.
PROPOSAL_CLAIM_SECONDS = 120

DECISION_CREATING = 'creating'
DECISION_CREATED = 'created'
DECISION_DENIED = 'denied'

MODE_PAUSED = 'paused'
MODE_ENABLED = 'enabled'
ACCEPT_MODES = (MODE_PAUSED, MODE_ENABLED)

STATE_PENDING = 'pending'
STATE_CREATING = 'creating'
STATE_CREATED_ENABLED = 'created_enabled'
STATE_CREATED_PAUSED = 'created_paused'
STATE_DENIED = 'denied'
STATE_DELETED = 'deleted'
STATE_EXPIRED = 'expired'
STATE_UNAVAILABLE = 'unavailable'
PROPOSAL_STATES = (
    STATE_PENDING, STATE_CREATING, STATE_CREATED_ENABLED, STATE_CREATED_PAUSED, STATE_DENIED,
    STATE_DELETED, STATE_EXPIRED, STATE_UNAVAILABLE,
)

REASON_CONTENT_REVIEW = 'content_review'
REASON_PROPOSAL_UNAVAILABLE = 'proposal_unavailable'
# Reasons the requester cannot act on proposals here at all: nothing is shown and nothing is allowed.
ACCESS_REASONS = (WORKFLOW_REASON_DISABLED, WORKFLOW_REASON_ROLE_REQUIRED, WORKFLOW_REASON_SHARED_CONVERSATION)

URL_ACCESS_NOTE = 'Create the workflow first, then turn on URL Access in the workflow editor.'

ACCEPT_FIELDS = frozenset({'conversation_id', 'mode', 'create_again', 'workflow'})
DENY_FIELDS = frozenset({'conversation_id'})

# What a built workflow carries that the server owns; an editor draft never includes it.
DRAFT_SERVER_FIELDS = frozenset({
    'id', 'user_id', 'origin', 'definition_revision', 'created_at', 'modified_at', 'updated_at',
    'created_by', 'modified_by', 'status', 'last_run_at', 'last_run_error', 'last_run_response_preview',
    'last_run_started_at', 'last_run_status', 'last_run_trigger_source', 'run_count', 'active_run_id',
    'cancellation_requested_at', 'cancellation_requested_by', 'url_access_authorized',
    'url_access_authorized_at', 'url_access_authorized_by', 'conversation_id', 'next_run_at',
    'm365_binding_approval_id', 'm365_revision',
})

SERVICE_UNAVAILABLE_CODE = 'service_unavailable'
ERROR_MESSAGES = {
    'invalid_request': 'This request is not valid.',
    'proposal_not_found': 'This workflow proposal could not be found.',
    'run_not_found': 'Run not found.',
    WORKFLOW_REASON_DISABLED: 'Workflow proposals are turned off.',
    WORKFLOW_REASON_ROLE_REQUIRED: 'You do not have access to create workflows.',
    WORKFLOW_REASON_SHARED_CONVERSATION: 'Workflows can be proposed only in a private conversation.',
    'proposal_unavailable': 'This workflow proposal is no longer available.',
    'proposal_expired': 'This workflow proposal has expired. Ask again for a new one.',
    'proposal_denied': 'This workflow proposal was denied.',
    'proposal_accepted': 'This workflow proposal was already accepted.',
    'proposal_busy': 'This workflow proposal is being updated. Try again in a moment.',
    'workflow_deleted': 'The workflow from this proposal was deleted. Choose Create again to create it again.',
    SERVICE_UNAVAILABLE_CODE: 'Workflow proposals are unavailable right now. Try again later.',
}
_ERROR_STATUS = {
    'invalid_request': 400,
    'proposal_not_found': 404,
    'run_not_found': 404,
    WORKFLOW_REASON_DISABLED: 403,
    WORKFLOW_REASON_ROLE_REQUIRED: 403,
    WORKFLOW_REASON_SHARED_CONVERSATION: 403,
    'proposal_unavailable': 409,
    'proposal_expired': 409,
    'proposal_denied': 409,
    'proposal_accepted': 409,
    'proposal_busy': 409,
    'workflow_deleted': 409,
    SERVICE_UNAVAILABLE_CODE: 503,
}

# Workflow draft service error codes, by the HTTP status an accept or draft returns for them.
_FORBIDDEN_DRAFT_CODES = frozenset({'workflows_unavailable', 'not_allowed'})
_CONFLICT_DRAFT_CODES = frozenset({
    'quota_exceeded', 'workflow_conflict', 'agent_unavailable', 'reference_unknown', 'reference_unauthorized',
    'file_sync_source_unavailable', 'workflow_unavailable', 'workflow_definition_conflict', 'workflow_deleted',
    'merge_unavailable',
})
_INVALID_DRAFT_CODES = frozenset({
    'blueprint_invalid', 'unsupported_field', 'too_many_tasks', 'trigger_invalid', 'cadence_below_minimum',
    'invalid_workflow', 'invalid_workflow_definition', 'invalid_workflow_settings', 'invalid_workflow_alerts',
    'merge_inputs_required', 'merge_trigger_required', 'merge_options_invalid', 'merge_runner_invalid',
})
_INVALID_WORKFLOW_MESSAGE = 'Invalid workflow settings. Review the task, runner, trigger, and document inputs.'
_SAFE_POINTER = re.compile(r'^(/[A-Za-z0-9_-]{1,64}){0,8}$')
_RUN_AS_VALUES = ('self', 'none')


class ProposalError(Exception):
    """A refusal a proposal route returns as written: an HTTP status, a stable code and fixed text."""

    def __init__(self, code, *, status=None, message=None, errors=()):
        super().__init__(code)
        self.code = code
        self.status = status or _ERROR_STATUS.get(code, 400)
        self.message = message or ERROR_MESSAGES.get(code, ERROR_MESSAGES['invalid_request'])
        self.errors = [dict(error) for error in errors]

    def payload(self):
        return {'error': self.message, 'code': self.code, 'errors': deepcopy(self.errors)}


def error_payload(code):
    """The body a proposal route returns for one of this module's fixed refusals."""
    return ProposalError(code).payload()


class _AlreadyCreated(Exception):
    """A claim found the proposal already accepted, and the caller did not ask to create it again."""


@dataclass
class _Proposal:
    proposal_id: str
    step_id: str
    producer: dict
    sidecar: dict
    blueprint: dict
    blueprint_ok: bool
    decision: dict


@dataclass
class _Assessment:
    state: str
    reason: str
    workflow: dict
    decision: dict
    expired: bool
    blocked: bool


def _log(message, level=logging.INFO, *, run_id=None, conversation_id=None, **fields):
    log_event(
        f'{_LOG_PREFIX} {message}',
        extra={
            'stage': 'workflow_proposal_decision',
            **workflow_log_context(run_id=run_id, conversation_id=conversation_id),
            **fields,
        },
        level=level,
    )


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
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Workflow draft service errors
# ---------------------------------------------------------------------------

def _public_errors(errors):
    """Bounded draft errors with known codes and safe pointers; any other code reads as invalid."""
    public = []
    for error in errors or ():
        if not isinstance(error, dict):
            continue
        code = _text(error.get('code'))
        message = ' '.join(str(error.get('message') or '').split())[:DRAFT_MESSAGE_MAX_LENGTH]
        if code not in _FORBIDDEN_DRAFT_CODES | _CONFLICT_DRAFT_CODES | _INVALID_DRAFT_CODES or not message:
            code, message = 'invalid_workflow', _INVALID_WORKFLOW_MESSAGE
        path = error.get('path')
        public.append({
            'code': code, 'message': message,
            'path': path if isinstance(path, str) and _SAFE_POINTER.match(path) else '',
        })
        if len(public) >= DRAFT_MAX_ERRORS:
            break
    return public


def _draft_failure(errors):
    """One refusal for the draft service's errors, with the status of the most severe of them."""
    public = _public_errors(errors) or [
        {'code': 'invalid_workflow', 'message': _INVALID_WORKFLOW_MESSAGE, 'path': ''},
    ]
    for status, codes in ((403, _FORBIDDEN_DRAFT_CODES), (409, _CONFLICT_DRAFT_CODES)):
        chosen = next((error for error in public if error['code'] in codes), None)
        if chosen is not None:
            return ProposalError(chosen['code'], status=status, message=chosen['message'], errors=public)
    return ProposalError(public[0]['code'], status=400, message=public[0]['message'], errors=public)


# ---------------------------------------------------------------------------
# Finding a run's proposals
# ---------------------------------------------------------------------------

def _proposal_plan_steps(run):
    plan = run.get('plan') if isinstance(run.get('plan'), dict) else {}
    return [
        step for step in plan.get('steps') or ()
        if isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_PROPOSE
        and step.get('enabled', True) is not False and isinstance(step.get('step_id'), str) and step['step_id']
    ]


def _plan_step(run, step_id):
    return next((step for step in _proposal_plan_steps(run) if step['step_id'] == step_id), None)


def _execution_entry(run, step_id):
    return next(
        (
            entry for entry in run.get('execution_steps') or ()
            if isinstance(entry, dict) and entry.get('step_id') == step_id
        ),
        None,
    )


def _sidecar(record):
    value = record.get('workflow_proposal') if isinstance(record, dict) else None
    return value if isinstance(value, dict) else None


def _producer_run_id(run, step_id, sidecar, entry):
    """The run that produced a step's proposal: this run, or the earlier attempt it reused."""
    for value in ((sidecar or {}).get('origin_run_id'), (entry or {}).get('reused_from_run_id')):
        if isinstance(value, str) and value:
            return value
    inherited = run.get('inherited_checkpoints') if isinstance(run.get('inherited_checkpoints'), dict) else {}
    reference = inherited.get(step_id) if isinstance(inherited.get(step_id), dict) else {}
    provenance = reference.get('provenance') if isinstance(reference.get('provenance'), dict) else {}
    value = provenance.get('run_id')
    return value if isinstance(value, str) and value else None


def _same_turn(producer, run):
    return (
        isinstance(producer, dict) and producer.get('conversation_id') == run.get('conversation_id')
        and producer.get('turn_id') == run.get('turn_id') and not is_legacy_plan(producer.get('plan'))
    )


def _sidecar_matches(sidecar, *, proposal_id, producer_id, step_id, conversation_id, user_id):
    return (
        sidecar.get('version') == WORKFLOW_PROPOSAL_VERSION and sidecar.get('proposal_id') == proposal_id
        and sidecar.get('origin_run_id') == producer_id and sidecar.get('step_id') == step_id
        and sidecar.get('conversation_id') == conversation_id and sidecar.get('requester_user_id') == user_id
    )


def _blueprint_matches(blueprint, sidecar):
    if not isinstance(blueprint, dict) or not isinstance(sidecar.get('blueprint_digest'), str):
        return False
    try:
        return canonical_digest(blueprint) == sidecar['blueprint_digest']
    except Exception:
        return False


def _resolve_proposals(run, user_id):
    """Every proposal ``run`` shows, verified against the run that produced it."""
    run_id = run.get('id')
    conversation_id = run.get('conversation_id')
    proposals = []
    for step in _proposal_plan_steps(run):
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
        producer_step = _plan_step(producer, step_id)
        if sidecar is None or producer_step is None or producer.get('checkpoints_deleted'):
            continue
        proposal_id = workflow_proposal_id(producer_id, step_id)
        if not _sidecar_matches(
            sidecar, proposal_id=proposal_id, producer_id=producer_id, step_id=step_id,
            conversation_id=conversation_id, user_id=user_id,
        ):
            _log(
                'A workflow proposal did not match the run that produced it.', logging.WARNING,
                run_id=run_id, conversation_id=conversation_id, step_id=step_id,
                code='proposal_integrity_mismatch',
            )
            continue
        arguments = producer_step.get('arguments') if isinstance(producer_step.get('arguments'), dict) else {}
        blueprint = arguments.get('blueprint') if isinstance(arguments.get('blueprint'), dict) else None
        decisions = producer.get(WORKFLOW_PROPOSAL_DECISIONS_FIELD)
        decision = decisions.get(proposal_id) if isinstance(decisions, dict) else None
        proposals.append(_Proposal(
            proposal_id=proposal_id, step_id=step_id, producer=producer, sidecar=sidecar,
            blueprint=blueprint, blueprint_ok=_blueprint_matches(blueprint, sidecar),
            decision=decision if isinstance(decision, dict) else None,
        ))
    return proposals


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _read_workflow(user_id, proposal_id):
    """The workflow this proposal created, if it still exists; a storage failure raises."""
    workflow_id = orchestration_workflow_id(user_id, proposal_id)
    try:
        record = functions_personal_workflows.cosmos_personal_workflows_container.read_item(
            item=workflow_id, partition_key=user_id,
        )
    except exceptions.CosmosResourceNotFoundError:
        return None
    origin = record.get('origin') if isinstance(record, dict) and isinstance(record.get('origin'), dict) else {}
    if (
        not isinstance(record, dict) or record.get('id') != workflow_id or record.get('user_id') != user_id
        or origin.get('proposal_id') != proposal_id or record.get('deleting') or record.get('status') == 'deleting'
    ):
        return None
    return record


def _effective_decision(decision, now):
    """The decision that holds now: a claim that went stale gives way to the one it replaced."""
    if not isinstance(decision, dict):
        return None
    state = decision.get('state')
    if state == DECISION_CREATING:
        claimed_at = _parse_time(decision.get('claimed_at'))
        if claimed_at is not None and abs((now - claimed_at).total_seconds()) < PROPOSAL_CLAIM_SECONDS:
            return decision
        previous = decision.get('previous')
        return previous if isinstance(previous, dict) and previous.get('state') == DECISION_CREATED else None
    return decision if state in (DECISION_CREATED, DECISION_DENIED) else None


def _expired(sidecar, now):
    expires_at = _parse_time(sidecar.get('expires_at'))
    return expires_at is None or now >= expires_at


def _ready(proposal):
    return (
        proposal.sidecar.get('status') == WORKFLOW_PROPOSAL_STATUS_READY and proposal.blueprint_ok
        and bool(_text(proposal.sidecar.get('created_at')))
    )


def _gate(settings, identity, conversation):
    """The closed reason this requester cannot act on proposals here, or None."""
    reason = workflow_planning_gate(settings, identity.get('roles'))
    if reason:
        return reason
    if not conversation_is_private(conversation, identity.get('user_id')):
        return WORKFLOW_REASON_SHARED_CONVERSATION
    return None


def _assess(proposal, *, blocked_reason, removed, user_id, now):
    expired = _expired(proposal.sidecar, now)
    if blocked_reason:
        return _Assessment(STATE_UNAVAILABLE, blocked_reason, None, None, expired, True)
    workflow = _read_workflow(user_id, proposal.proposal_id)
    decision = _effective_decision(proposal.decision, now)
    if removed:
        return _Assessment(STATE_UNAVAILABLE, REASON_CONTENT_REVIEW, workflow, decision, expired, True)
    if workflow is not None:
        state = STATE_CREATED_ENABLED if workflow.get('is_enabled') is True else STATE_CREATED_PAUSED
        return _Assessment(state, None, workflow, decision, expired, False)
    decided = (decision or {}).get('state')
    if decided == DECISION_DENIED:
        return _Assessment(STATE_DENIED, None, None, decision, expired, False)
    if decided == DECISION_CREATING:
        return _Assessment(STATE_CREATING, None, None, decision, expired, False)
    if decided == DECISION_CREATED:
        return _Assessment(STATE_DELETED, None, None, decision, expired, False)
    if not _ready(proposal):
        reason = _text(proposal.sidecar.get('reason')) or REASON_PROPOSAL_UNAVAILABLE
        return _Assessment(STATE_UNAVAILABLE, reason, None, None, expired, False)
    if expired:
        return _Assessment(STATE_EXPIRED, None, None, None, expired, False)
    return _Assessment(STATE_PENDING, None, None, None, expired, False)


def _actions(assessment, proposal):
    state = assessment.state
    return {
        'accept': state == STATE_PENDING,
        'edit': state == STATE_PENDING,
        # A proposal can be declined until it is decided or expires, even one that cannot be created.
        'deny': (
            assessment.reason not in ACCESS_REASONS
            and assessment.workflow is None and assessment.decision is None and not assessment.expired
        ),
        'create_again': state == STATE_DELETED and not assessment.expired and _ready(proposal),
        'open_workflow': state in (STATE_CREATED_ENABLED, STATE_CREATED_PAUSED),
    }


def _m365_connected(user_id, tenant_id):
    """Whether the requester's stored Microsoft 365 connection is connected; None when unknown.

    Reads the stored connection record only: no token refresh and no Microsoft Graph call.
    """
    try:
        from functions_m365_connections import get_m365_connection_service

        connection = get_m365_connection_service().current_connection(user_id, tenant_id)
    except Exception as exc:
        _log(
            'The Microsoft 365 connection could not be read for a workflow proposal.', logging.WARNING,
            error_type=type(exc).__name__,
        )
        return None
    return isinstance(connection, dict) and connection.get('status') == 'connected'


def _m365(proposal, workflow, identity):
    summary = proposal.sidecar.get('summary') if isinstance(proposal.sidecar.get('summary'), dict) else {}
    source = summary.get('m365') if isinstance(summary.get('m365'), dict) else {}
    required = source.get('required') is True
    approval_state = None
    if isinstance(workflow, dict):
        if workflow.get('m365_binding_approval_id'):
            approval_state = 'approved'
        elif workflow.get('last_run_status') in M365_WAITING_STATES:
            approval_state = 'waiting'
    return {
        'required': required,
        'can_send': source.get('can_send') is True,
        'run_as': source.get('run_as') if source.get('run_as') in _RUN_AS_VALUES else 'none',
        'sources': [value for value in source.get('sources') or () if isinstance(value, str)],
        'connected': _m365_connected(identity.get('user_id'), identity.get('tenant_id')) if required else None,
        'approval_state': approval_state,
    }


def _summary(proposal):
    """The card's description, with every task's full instructions from the verified blueprint."""
    summary = deepcopy(proposal.sidecar.get('summary')) if isinstance(proposal.sidecar.get('summary'), dict) else {}
    blueprint_tasks = proposal.blueprint.get('tasks') if isinstance(proposal.blueprint.get('tasks'), list) else []
    tasks = [task for task in summary.get('tasks') or () if isinstance(task, dict)]
    for index, task in enumerate(tasks):
        source = blueprint_tasks[index] if index < len(blueprint_tasks) and isinstance(blueprint_tasks[index], dict) else {}
        instructions = source.get('instructions')
        task['instructions'] = instructions if isinstance(instructions, str) else ''
    summary['tasks'] = tasks
    return summary


def _workflow_projection(workflow):
    return {
        'id': workflow.get('id'),
        'name': workflow.get('name') if isinstance(workflow.get('name'), str) else '',
        'is_enabled': workflow.get('is_enabled') is True,
    }


def _describe(proposal, assessment, identity):
    disclosed = not assessment.blocked and proposal.blueprint_ok
    created = assessment.state in (STATE_CREATED_ENABLED, STATE_CREATED_PAUSED)
    similar = proposal.sidecar.get('similar_workflows')
    return {
        'proposal_id': proposal.proposal_id,
        'step_id': proposal.step_id,
        'state': assessment.state,
        'reason': assessment.reason,
        'created_at': proposal.sidecar.get('created_at'),
        'expires_at': proposal.sidecar.get('expires_at'),
        'actions': _actions(assessment, proposal),
        'summary': _summary(proposal) if disclosed else None,
        'similar_workflows': deepcopy(similar) if disclosed and isinstance(similar, list) else [],
        'm365': _m365(proposal, assessment.workflow if created else None, identity) if disclosed else None,
        'workflow': _workflow_projection(assessment.workflow) if created else None,
    }


def proposal_status(run, conversation, *, identity, settings, response_removed):
    """Every workflow proposal ``run`` shows, for its requester's proposal card.

    ``response_removed`` is called at most once, and only when the requester may act on
    proposals here, to learn whether content review removed the run's response.
    """
    user_id = identity.get('user_id')
    now = _now()
    blocked_reason = _gate(settings, identity, conversation)
    proposals = _resolve_proposals(run, user_id)
    removed = bool(proposals) and not blocked_reason and bool(response_removed())
    return {
        'run_id': run.get('id'),
        'proposals': [
            _describe(proposal, _assess(
                proposal, blocked_reason=blocked_reason, removed=removed, user_id=user_id, now=now,
            ), identity)
            for proposal in proposals
        ],
    }


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def _open_proposal(run, conversation, proposal_id, *, identity, settings, response_removed=None):
    """The proposal a decision names, after every access check a decision needs."""
    if not _canonical_uuid(proposal_id):
        raise ProposalError('proposal_not_found')
    reason = _gate(settings, identity, conversation)
    if reason:
        raise ProposalError(reason)
    proposal = next(
        (item for item in _resolve_proposals(run, identity.get('user_id')) if item.proposal_id == proposal_id),
        None,
    )
    if proposal is None:
        raise ProposalError('proposal_not_found')
    if response_removed is not None and response_removed():
        raise ProposalError('proposal_unavailable')
    return proposal


def _refuse_decided(decision, *, create_again=False):
    state = (decision or {}).get('state')
    if state == DECISION_DENIED:
        raise ProposalError('proposal_denied')
    if state == DECISION_CREATING:
        raise ProposalError('proposal_busy')
    if state == DECISION_CREATED and not create_again:
        raise ProposalError('workflow_deleted')


def _origin(proposal, *, edited):
    return {
        'source': WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
        'conversation_id': proposal.sidecar['conversation_id'],
        'orchestration_run_id': proposal.sidecar['origin_run_id'],
        'proposal_id': proposal.proposal_id,
        'created_at': proposal.sidecar['created_at'],
        'edited': bool(edited),
    }


def _user_info(identity):
    return {
        'userId': identity.get('user_id'),
        'email': identity.get('email'),
        'roles': list(identity.get('roles') or []),
    }


def _handles(proposal):
    handles = proposal.sidecar.get('handles')
    return deepcopy(handles) if isinstance(handles, dict) else {}


def _decide(proposal, user_id, mutate):
    return update_workflow_proposal_decision(
        proposal.producer['id'], user_id, proposal.producer['conversation_id'], proposal.proposal_id, mutate,
    )


def _log_context(proposal):
    return {'run_id': proposal.producer.get('id'), 'conversation_id': proposal.producer.get('conversation_id')}


def _confirm_created(proposal, user_id, workflow, *, claim_id, now):
    """Record that the proposal's workflow exists. A failure is logged: the workflow is the authority."""
    decision = {
        'state': DECISION_CREATED,
        'accepted_at': _iso(now),
        'mode': MODE_ENABLED if workflow.get('is_enabled') is True else MODE_PAUSED,
        'edited': ((workflow.get('origin') or {}).get('edited') is True),
        'workflow_id': workflow.get('id'),
        'claim_id': claim_id,
    }

    def confirm(previous):
        if (
            isinstance(previous, dict) and previous.get('state') == DECISION_CREATED
            and previous.get('workflow_id') == decision['workflow_id']
        ):
            return previous
        return decision

    try:
        _decide(proposal, user_id, confirm)
        return True
    except Exception as exc:
        _log(
            'A workflow proposal decision could not be confirmed.', logging.WARNING, **_log_context(proposal),
            proposal_id=proposal.proposal_id, workflow_id=workflow.get('id'), error_type=type(exc).__name__,
        )
        return False


def _release_claim(proposal, user_id, claim_id):
    """Undo this request's claim, restoring the decision it replaced. A failure is logged only."""
    def release(previous):
        if (
            isinstance(previous, dict) and previous.get('state') == DECISION_CREATING
            and previous.get('claim_id') == claim_id
        ):
            restored = previous.get('previous')
            return deepcopy(restored) if isinstance(restored, dict) else None
        return previous

    try:
        _decide(proposal, user_id, release)
    except Exception as exc:
        _log(
            'A workflow proposal claim could not be released.', logging.WARNING, **_log_context(proposal),
            proposal_id=proposal.proposal_id, error_type=type(exc).__name__,
        )


def _accept_request(body):
    if not isinstance(body, dict) or set(body) - ACCEPT_FIELDS:
        raise ProposalError('invalid_request')
    mode = body.get('mode')
    create_again = body.get('create_again', False)
    payload = body.get('workflow')
    if type(create_again) is not bool or (payload is not None and not isinstance(payload, dict)):
        raise ProposalError('invalid_request')
    if (mode is None and payload is None) or (mode is not None and mode not in ACCEPT_MODES):
        raise ProposalError('invalid_request')
    return mode, create_again, payload


def _edited(proposal, payload, *, user_id, settings, user_info):
    """Whether an editor draft changes what the proposal would have created. Unknown reads as edited."""
    try:
        proposed = dry_run_workflow_blueprint(
            user_id, proposal.blueprint, _handles(proposal), origin=_origin(proposal, edited=False),
            settings=settings, user_info=user_info, enabled=False, check_quota=False,
        )
        if not proposed.get('ok'):
            return True
        draft = {
            key: deepcopy(value) for key, value in payload.items()
            if key != 'id' and key not in URL_ACCESS_AUTHORIZATION_FIELDS
        }
        candidate = dry_run_personal_workflow(user_id, draft, actor_user_id=user_id, settings=settings)
        if not candidate.get('ok'):
            return True
        return workflow_origin_material_change(proposed['workflow'], candidate['workflow'])
    except Exception as exc:
        _log(
            'An edited workflow proposal could not be compared.', logging.WARNING, **_log_context(proposal),
            proposal_id=proposal.proposal_id, error_type=type(exc).__name__,
        )
        return True


def _created_response(proposal, workflow, *, created):
    return {
        'proposal_id': proposal.proposal_id,
        'created': bool(created),
        'workflow': _workflow_projection(workflow),
        'state': STATE_CREATED_ENABLED if workflow.get('is_enabled') is True else STATE_CREATED_PAUSED,
    }


def _existing_accept(proposal, user_id, workflow, now):
    """Answer an accept for a proposal whose workflow exists, recording the decision if it was lost."""
    decision = proposal.decision if isinstance(proposal.decision, dict) else {}
    if not (decision.get('state') == DECISION_CREATED and decision.get('workflow_id') == workflow.get('id')):
        _confirm_created(
            proposal, user_id, workflow, claim_id=decision.get('claim_id'), now=now,
        )
    return 200, _created_response(proposal, workflow, created=False), None


def accept_proposal(run, conversation, proposal_id, body, *, identity, settings, response_removed):
    """Create the proposal's workflow, once. Returns ``(HTTP status, body, created workflow or None)``.

    ``body`` is the request: ``mode`` (``paused`` or ``enabled``), and for a proposal the
    requester changed in the workflow editor, ``workflow``, the editor's draft. ``create_again``
    creates the workflow again after the requester deleted the one this proposal created.
    Accepting an accepted proposal returns its workflow with status 200. Run as is never approved
    here: a Microsoft 365 workflow still asks for approval before it first runs as the user. The
    caller records the workflow creation activity when a workflow is returned as created.
    """
    user_id = identity.get('user_id')
    mode, create_again, payload = _accept_request(body)
    proposal = _open_proposal(
        run, conversation, proposal_id, identity=identity, settings=settings, response_removed=response_removed,
    )
    if not _ready(proposal):
        raise ProposalError('proposal_unavailable')
    now = _now()
    workflow = _read_workflow(user_id, proposal.proposal_id)
    if workflow is not None:
        return _existing_accept(proposal, user_id, workflow, now)
    decision = _effective_decision(proposal.decision, now)
    _refuse_decided(decision, create_again=create_again)
    if _expired(proposal.sidecar, now):
        raise ProposalError('proposal_expired')

    user_info = _user_info(identity)
    if payload is not None:
        payload = deepcopy(payload)
        if mode is not None:
            payload['is_enabled'] = mode == MODE_ENABLED
        requested_mode = MODE_ENABLED if payload.get('is_enabled') is True else MODE_PAUSED
        edited = _edited(proposal, payload, user_id=user_id, settings=settings, user_info=user_info)
    else:
        requested_mode = mode
        edited = False
    claim_id = uuid.uuid4().hex

    def claim(previous):
        current = _effective_decision(previous, now)
        state = (current or {}).get('state')
        if state == DECISION_CREATED and not create_again:
            raise _AlreadyCreated()
        if state in (DECISION_DENIED, DECISION_CREATING):
            _refuse_decided(current)
        return {
            'state': DECISION_CREATING,
            'claim_id': claim_id,
            'claimed_at': _iso(now),
            'mode': requested_mode,
            'edited': edited,
            'previous': deepcopy(current) if state == DECISION_CREATED else None,
        }

    try:
        _decide(proposal, user_id, claim)
    except _AlreadyCreated:
        workflow = _read_workflow(user_id, proposal.proposal_id)
        if workflow is None:
            raise ProposalError('workflow_deleted') from None
        return _existing_accept(proposal, user_id, workflow, now)
    except ProposalDecisionBusy:
        raise ProposalError('proposal_busy') from None
    except LookupError:
        raise ProposalError('proposal_unavailable') from None

    origin = _origin(proposal, edited=edited)
    try:
        if payload is None:
            outcome = create_personal_workflow_from_blueprint(
                user_id, proposal.blueprint, _handles(proposal), origin=origin, settings=settings,
                user_info=user_info, enabled=mode == MODE_ENABLED,
            )
        else:
            outcome = create_personal_workflow_from_payload(
                user_id, payload, origin=origin, settings=settings, user_info=user_info,
            )
    except Exception:
        _release_claim(proposal, user_id, claim_id)
        raise
    if not outcome.get('ok') or not isinstance(outcome.get('workflow'), dict):
        _release_claim(proposal, user_id, claim_id)
        failure = _draft_failure(outcome.get('errors'))
        _log(
            'A workflow proposal was not accepted.', **_log_context(proposal), proposal_id=proposal.proposal_id,
            code=failure.code, error_codes=[error['code'] for error in failure.errors],
        )
        raise failure

    workflow = outcome['workflow']
    created = outcome.get('created') is True
    _confirm_created(proposal, user_id, workflow, claim_id=claim_id, now=now)
    _log(
        'A workflow proposal was accepted.', **_log_context(proposal), proposal_id=proposal.proposal_id,
        workflow_id=workflow.get('id'), created=created, edited=edited,
        mode=MODE_ENABLED if workflow.get('is_enabled') is True else MODE_PAUSED,
    )
    return (201 if created else 200), _created_response(proposal, workflow, created=created), (
        workflow if created else None
    )


def deny_proposal(run, conversation, proposal_id, body, *, identity, settings):
    """Record that the requester declined a proposal. Denying it again changes nothing.

    A proposal that cannot be created, or whose response is in content review, can still be
    denied; an accepted one cannot.
    """
    if not isinstance(body, dict) or set(body) - DENY_FIELDS:
        raise ProposalError('invalid_request')
    user_id = identity.get('user_id')
    proposal = _open_proposal(run, conversation, proposal_id, identity=identity, settings=settings)
    now = _now()
    if _read_workflow(user_id, proposal.proposal_id) is not None:
        raise ProposalError('proposal_accepted')
    decision = _effective_decision(proposal.decision, now)
    state = (decision or {}).get('state')
    if state == DECISION_DENIED:
        return 200, {'proposal_id': proposal.proposal_id, 'state': STATE_DENIED}
    if state == DECISION_CREATED:
        raise ProposalError('proposal_accepted')
    if state == DECISION_CREATING:
        raise ProposalError('proposal_busy')
    if _expired(proposal.sidecar, now):
        raise ProposalError('proposal_expired')

    def deny(previous):
        current = _effective_decision(previous, now)
        current_state = (current or {}).get('state')
        if current_state == DECISION_DENIED:
            return previous
        if current_state == DECISION_CREATED:
            raise ProposalError('proposal_accepted')
        if current_state == DECISION_CREATING:
            raise ProposalError('proposal_busy')
        return {'state': DECISION_DENIED, 'denied_at': _iso(now)}

    try:
        _decide(proposal, user_id, deny)
    except ProposalDecisionBusy:
        raise ProposalError('proposal_busy') from None
    except LookupError:
        raise ProposalError('proposal_unavailable') from None
    _log('A workflow proposal was denied.', **_log_context(proposal), proposal_id=proposal.proposal_id)
    return 200, {'proposal_id': proposal.proposal_id, 'state': STATE_DENIED}


def proposal_draft(run, conversation, proposal_id, *, identity, settings, response_removed):
    """The proposal as a workflow editor draft, while it is still pending. Writes nothing.

    The draft has no id and no server fields; accepting it with ``workflow`` creates the same
    workflow id this proposal always maps to.
    """
    user_id = identity.get('user_id')
    proposal = _open_proposal(
        run, conversation, proposal_id, identity=identity, settings=settings, response_removed=response_removed,
    )
    if not _ready(proposal):
        raise ProposalError('proposal_unavailable')
    now = _now()
    if _read_workflow(user_id, proposal.proposal_id) is not None:
        raise ProposalError('proposal_accepted')
    _refuse_decided(_effective_decision(proposal.decision, now))
    if _expired(proposal.sidecar, now):
        raise ProposalError('proposal_expired')
    outcome = dry_run_workflow_blueprint(
        user_id, proposal.blueprint, _handles(proposal), origin=_origin(proposal, edited=False),
        settings=settings, user_info=_user_info(identity), enabled=False, check_quota=False,
    )
    if not outcome.get('ok') or not isinstance(outcome.get('workflow'), dict):
        raise _draft_failure(outcome.get('errors'))
    workflow = {key: value for key, value in outcome['workflow'].items() if key not in DRAFT_SERVER_FIELDS}
    return 200, {'proposal_id': proposal.proposal_id, 'workflow': workflow, 'url_access_note': URL_ACCESS_NOTE}


__all__ = [
    'ACCEPT_MODES',
    'PROPOSAL_CLAIM_SECONDS',
    'PROPOSAL_STATES',
    'ProposalError',
    'SERVICE_UNAVAILABLE_CODE',
    'URL_ACCESS_NOTE',
    'accept_proposal',
    'deny_proposal',
    'error_payload',
    'proposal_draft',
    'proposal_status',
]
