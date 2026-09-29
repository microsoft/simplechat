# functions_orchestration_workflows.py
"""Workflow proposals from chat orchestration: plan checks, the proposal step and degrading.

Version: 0.261.204
Implemented in: 0.261.204

A plan proposes a personal workflow with one ``workflow_propose`` step. Its ``blueprint``
argument is the closed workflow blueprint from ``functions_workflow_drafts``, naming agents,
documents and File Sync sources by the request-local handles of the turn's workflow planning
context (``functions_orchestration_workflow_context``). This module

* checks a proposal while a plan is validated: the step takes no dependencies or inputs, the
  blueprint passes every draft rule that reads nothing and names only offered handles, each
  task that needs actions runs on an agent that has them, and Microsoft 365 agents run as the
  user;
* runs the step: a write-free dry run of the blueprint through the workflow draft service, a
  small retained ``proposal`` result for the run, and a server-only sidecar on the step record
  that the proposal card and the accept route read. Nothing is created until the user approves
  the card;
* rebuilds that sidecar when a completed step was recovered without it;
* drops the proposal from a plan whose blueprint could not be repaired, so the rest of the plan
  still runs and the workflow is reported as not delivered.

Nothing here writes a workflow. Logs carry ids and codes only, never names, instructions or
catalog text.
"""

import difflib
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from functions_appinsights import log_event
from functions_mixed_source_orchestration import MixedSourceCancellationError
from functions_orchestration_registry import CAPABILITY_WORKFLOW_PROPOSE
from functions_orchestration_result_contracts import (
    Completeness,
    Coverage,
    ResultContractError,
    canonical_digest,
)
from functions_orchestration_result_runtime import raise_source_service_failure, require_result_service
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_orchestration_schema import (
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    WORKFLOW_BLUEPRINT_INVALID_CODE,
    PlanValidationError,
    build_failure,
    build_step_result,
    failure_from_exception,
)
from functions_orchestration_workflow_context import (
    NAME_MAX_LENGTH,
    WORKFLOW_DEFAULT_TIME_ZONE,
    clean_catalog_text,
    workflow_draft_handles,
    workflow_planning_ready,
)
from functions_workflow_drafts import (
    BLUEPRINT_TASK_TITLE_MAX_LENGTH,
    WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
    check_workflow_blueprint,
    dry_run_workflow_blueprint,
    validate_workflow_blueprint,
)
from functions_workflow_schedules import (
    WorkflowPublicValidationError,
    normalize_workflow_schedule,
    workflow_schedule_label,
)


WORKFLOW_PROPOSAL_VERSION = 1
# Namespace for proposal ids: one proposal per producing run and step, stable across recovery.
WORKFLOW_PROPOSAL_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'urn:simplechat:workflow-proposals')
WORKFLOW_PROPOSAL_TTL = timedelta(days=14)
WORKFLOW_PROPOSAL_OUTPUT = 'proposal'
WORKFLOW_PROPOSAL_OUTPUT_KIND = 'structured-v1'
WORKFLOW_PROPOSAL_CHECK = 'workflow_proposal_dry_run'

WORKFLOW_PROPOSAL_STATUS_READY = 'ready'
WORKFLOW_PROPOSAL_STATUS_UNAVAILABLE = 'unavailable'

# Why a proposal cannot be created as planned, most useful first. The card maps each to fixed text.
WORKFLOW_PROPOSAL_REASONS = (
    'workflows_unavailable',
    'quota_reached',
    'model_unavailable',
    'no_suitable_agent',
    'agent_unavailable',
    'file_sync_source_unavailable',
    'reference_unavailable',
    'cadence_below_minimum',
    'proposal_unavailable',
)
_REASON_FOR_CODE = {
    'workflows_unavailable': 'workflows_unavailable',
    'quota_exceeded': 'quota_reached',
    'agent_unavailable': 'agent_unavailable',
    'file_sync_source_unavailable': 'file_sync_source_unavailable',
    'reference_unknown': 'reference_unavailable',
    'reference_unauthorized': 'reference_unavailable',
    'cadence_below_minimum': 'cadence_below_minimum',
}

# Plan-check rules this module adds to the draft service's own error codes.
RULE_STATIC_INPUT = 'workflow_static_input'
RULE_CONTEXT_UNAVAILABLE = 'workflow_context_unavailable'
RULE_TASK_ACTIONS = 'task_actions_invalid'
RULE_CAPABILITY_MISMATCH = 'agent_capability_mismatch'
RULE_RUN_AS_REQUIRED = 'run_as_required'

MAX_SIMILAR_WORKFLOWS = 3
SIMILAR_NAME_RATIO = 0.85
SECONDS_PER_MONTH = 30 * 24 * 60 * 60
DAYS_PER_MONTH = 30
WEEKDAYS_PER_MONTH = 22
MAX_COVERING_AGENTS_NAMED = 3

_DRAFT_HANDLE_KINDS = ('agents', 'documents', 'sources')
_M365_SOURCE_ORDER = ('email', 'calendar', 'onedrive', 'sharepoint', 'directory')
_LOG_PREFIX = '[ORCHESTRATION_WORKFLOWS]'


def _log(message, level=logging.INFO, **fields):
    # Ids, codes and counts only: never blueprint text, names or catalog entries.
    log_event(f'{_LOG_PREFIX} {message}', extra={'stage': 'workflow_proposal', **fields}, level=level)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Plan checks
# ---------------------------------------------------------------------------

def _blueprint_error(errors, rule=None):
    """One planner-facing validation error from draft errors, built from fixed text only."""
    details = '; '.join(
        f"[{error['code']}] {error['path'] or '/'}: {error['message']}" for error in errors
    )
    return PlanValidationError(
        f'The workflow_propose blueprint breaks these rules: {details}',
        code=WORKFLOW_BLUEPRINT_INVALID_CODE, rule=rule or errors[0]['code'],
    )


def _context_unavailable(message='Workflow details are unavailable for this request.'):
    return PlanValidationError(message, code=WORKFLOW_BLUEPRINT_INVALID_CODE, rule=RULE_CONTEXT_UNAVAILABLE)


def _plan_error(code, path, message):
    return {'code': code, 'path': path, 'message': message}


def _task_actions(arguments, task_count):
    """The per-task action kinds, or raise when they do not line up with the tasks."""
    task_actions = arguments.get('task_actions')
    if task_actions is None:
        return [[] for _index in range(task_count)]
    if len(task_actions) != task_count:
        raise _blueprint_error([_plan_error(
            RULE_TASK_ACTIONS, '/task_actions',
            'List one array of action kinds per task, in task order; use [] for a task that needs none.',
        )])
    return [list(kinds) for kinds in task_actions]


def _fill_time_zone(blueprint, time_zone):
    """Give a calendar schedule without a zone the request's zone; an explicit zone is kept."""
    trigger = blueprint.get('trigger') if isinstance(blueprint, dict) else None
    if not isinstance(trigger, dict):
        return
    if trigger.get('type') == 'calendar' and not trigger.get('timezone'):
        trigger['timezone'] = time_zone
    schedule = trigger.get('schedule')
    if (
        trigger.get('type') == 'file_sync' and isinstance(schedule, dict)
        and schedule.get('kind') == 'calendar' and not schedule.get('timezone')
    ):
        schedule['timezone'] = time_zone


def _runner_agent(task):
    runner = task.get('runner') if isinstance(task.get('runner'), dict) else {}
    agent_ref = runner.get('agent_ref')
    return agent_ref if runner.get('type') == 'agent' and isinstance(agent_ref, str) else None


def _agent_kinds(capabilities, agent_ref):
    entry = capabilities.get(agent_ref) if agent_ref else None
    return set((entry or {}).get('action_kinds') or ()) if isinstance(entry, dict) else set()


def _catalog_handles(planning, kind):
    catalog = planning.get('catalog') if isinstance(planning.get('catalog'), dict) else {}
    return [
        entry.get('handle') for entry in catalog.get(kind) or ()
        if isinstance(entry, dict) and isinstance(entry.get('handle'), str)
    ]


def _capability_errors(blueprint, task_actions, planning):
    """Tasks whose actions another offered agent has, and Microsoft 365 agents not run as the user."""
    capabilities = planning.get('agent_capabilities')
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    agents = _catalog_handles(planning, 'agents')
    errors = []
    used_agents = []
    for index, task in enumerate(blueprint['tasks']):
        agent_ref = _runner_agent(task)
        if agent_ref and agent_ref not in used_agents:
            used_agents.append(agent_ref)
        needed = set(task_actions[index])
        if not needed or needed <= _agent_kinds(capabilities, agent_ref):
            continue
        covering = [handle for handle in agents if needed <= _agent_kinds(capabilities, handle)]
        if covering:
            # No offered agent has these actions otherwise: the card reports that instead.
            named = ', '.join(covering[:MAX_COVERING_AGENTS_NAMED])
            errors.append(_plan_error(
                RULE_CAPABILITY_MISMATCH, f'/tasks/{index}/runner',
                f'This task needs actions its runner does not have. Run it on an agent whose '
                f'action_kinds include every kind task_actions lists for it, such as {named}.',
            ))
    needs_run_as = any(
        isinstance(capabilities.get(agent_ref), dict) and capabilities[agent_ref].get('needs_run_as') is True
        for agent_ref in used_agents
    )
    if needs_run_as and blueprint.get('run_as') != 'self':
        errors.append(_plan_error(
            RULE_RUN_AS_REQUIRED, '/run_as',
            'An agent in this workflow uses Microsoft 365 actions, which run with the user\'s access. '
            'Set run_as to "self".',
        ))
    return errors


def prepare_workflow_proposal_arguments(raw, arguments, *, settings, workflow_planning=None):
    """Check one workflow_propose step while a plan is validated; return its arguments.

    ``raw`` is the planner's step and ``arguments`` its schema-checked copy. A proposal takes no
    ``depends_on`` and no ``inputs``, because it is written from the request alone.

    Without ``workflow_planning`` (a stored plan revalidated for execution), only the closed
    blueprint schema and the task action list are checked, and the arguments come back
    unchanged. With it (a new plan or a plan revision), a calendar schedule without a time zone
    takes the request's zone, the blueprint must pass every draft rule that reads nothing and name
    only the handles offered with the request, a task that needs actions must run on an agent
    that has them when an offered agent does, and a Microsoft 365 agent must run as the user.

    Raises ``PlanValidationError`` with code ``workflow_blueprint_invalid``. Its rule is
    ``workflow_context_unavailable`` when the check itself could not run, which no repair can fix.
    """
    if raw.get('depends_on') or raw.get('inputs'):
        raise PlanValidationError(
            'A workflow_propose step is written from the request alone: remove its depends_on and '
            'its inputs.', code=WORKFLOW_BLUEPRINT_INVALID_CODE, rule=RULE_STATIC_INPUT,
        )
    blueprint = arguments.get('blueprint')
    if workflow_planning is None:
        errors = validate_workflow_blueprint(blueprint)
        if errors:
            raise _blueprint_error(errors)
        _task_actions(arguments, len(blueprint['tasks']))
        return arguments

    if not workflow_planning_ready(workflow_planning) or not isinstance(settings, dict) or not settings:
        raise _context_unavailable()
    candidate = deepcopy(blueprint)
    _fill_time_zone(candidate, workflow_planning.get('time_zone') or WORKFLOW_DEFAULT_TIME_ZONE)
    handles = workflow_draft_handles(workflow_planning)
    try:
        prepared, errors = check_workflow_blueprint(
            candidate, settings=settings,
            handle_names={kind: sorted(handles.get(kind) or {}) for kind in _DRAFT_HANDLE_KINDS},
        )
    except Exception as exc:
        _log(
            'A workflow proposal could not be checked.', logging.WARNING,
            reason=RULE_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        raise _context_unavailable('The workflow proposal could not be checked for this request.') from exc
    if errors:
        raise _blueprint_error(errors)
    task_actions = _task_actions(arguments, len(prepared['tasks']))
    errors = _capability_errors(prepared, task_actions, workflow_planning)
    if errors:
        raise _blueprint_error(errors)
    return {**arguments, 'blueprint': prepared}


# ---------------------------------------------------------------------------
# Proposal summary
# ---------------------------------------------------------------------------

def workflow_proposal_id(run_id, step_id):
    """The id of the proposal a run's workflow_propose step made; the accepted workflow derives from it."""
    return str(uuid.uuid5(WORKFLOW_PROPOSAL_NAMESPACE, f'{run_id}:{step_id}'))


def _schedule_payload(fields, kind):
    if not isinstance(fields, dict):
        return None
    if kind == 'calendar':
        payload = {
            'kind': 'calendar', 'frequency': fields.get('frequency'),
            'time_of_day': fields.get('time_of_day'), 'timezone': fields.get('timezone'),
        }
        if 'days_of_week' in fields:
            payload['days_of_week'] = fields.get('days_of_week')
        if 'day_of_month' in fields:
            payload['day_of_month'] = fields.get('day_of_month')
        return payload
    if kind == 'interval':
        return {'unit': fields.get('unit'), 'value': fields.get('value')}
    return None


def stored_workflow_trigger(trigger):
    """Return ``(stored trigger type, schedule payload)`` for a blueprint trigger.

    A calendar schedule is stored under the interval trigger, beside interval schedules, and a
    File Sync trigger keeps the schedule that checks for changes. A manual trigger has none.
    """
    trigger = trigger if isinstance(trigger, dict) else {}
    kind = trigger.get('type')
    if kind in ('calendar', 'interval'):
        return 'interval', _schedule_payload(trigger, kind)
    if kind == 'file_sync':
        schedule = trigger.get('schedule') if isinstance(trigger.get('schedule'), dict) else {}
        return 'file_sync', _schedule_payload(schedule, schedule.get('kind'))
    return 'manual', None


def _normalized_schedule(schedule):
    if schedule is None:
        return None
    try:
        return normalize_workflow_schedule(schedule)
    except WorkflowPublicValidationError:
        return None


def _checks_per_month(normalized):
    if not isinstance(normalized, dict):
        return None
    if normalized.get('kind') == 'calendar':
        frequency = normalized.get('frequency')
        if frequency == 'daily':
            return DAYS_PER_MONTH
        if frequency == 'weekdays':
            return WEEKDAYS_PER_MONTH
        if frequency == 'weekly':
            return round(len(normalized.get('days_of_week') or ()) * DAYS_PER_MONTH / 7)
        return 1
    seconds = normalized.get('value', 0) * (60 if normalized.get('unit') == 'minutes' else 3600)
    return SECONDS_PER_MONTH // seconds if seconds > 0 else None


def workflow_proposal_runs_per_month(trigger_type, normalized_schedule):
    """About how often a proposed workflow runs in a 30-day month, for the card.

    A File Sync workflow runs when a check finds changes, so it reports how often it checks.
    """
    if trigger_type == 'manual':
        return {'kind': 'manual', 'value': None}
    count = _checks_per_month(normalized_schedule)
    if trigger_type == 'file_sync':
        return {'kind': 'on_change', 'value': None, 'checks_per_month': count}
    return {'kind': 'count', 'value': count}


def _catalog_names(planning, kind):
    catalog = planning.get('catalog') if isinstance(planning.get('catalog'), dict) else {}
    return {
        entry['handle']: entry.get('name') or ''
        for entry in catalog.get(kind) or ()
        if isinstance(entry, dict) and isinstance(entry.get('handle'), str)
    }


def used_workflow_handles(blueprint, handles):
    """The handle map entries a blueprint actually names, in the draft service's shape."""
    handles = handles if isinstance(handles, dict) else {}
    used = {kind: {} for kind in _DRAFT_HANDLE_KINDS}

    def take(kind, handle):
        entries = handles.get(kind) if isinstance(handles.get(kind), dict) else {}
        if isinstance(handle, str) and handle in entries and handle not in used[kind]:
            used[kind][handle] = deepcopy(entries[handle])

    blueprint = blueprint if isinstance(blueprint, dict) else {}
    for task in blueprint.get('tasks') or ():
        if not isinstance(task, dict):
            continue
        take('agents', _runner_agent(task))
        for handle in task.get('inputs') or ():
            take('documents', handle)
    trigger = blueprint.get('trigger') if isinstance(blueprint.get('trigger'), dict) else {}
    if trigger.get('type') == 'file_sync':
        for handle in trigger.get('source_ids') or ():
            take('sources', handle)
    return used


def _ordered(values, order):
    present = set(values)
    return [value for value in order if value in present]


def _similar_workflows(planning, *, name, trigger_type, schedule, source_keys):
    """At most three of the user's workflows that look like this proposal, and why."""
    snapshots = planning.get('workflow_snapshots') if isinstance(planning.get('workflow_snapshots'), dict) else {}
    records = (planning.get('handles') or {}).get('workflows') if isinstance(planning.get('handles'), dict) else {}
    records = records if isinstance(records, dict) else {}
    proposed_name = clean_catalog_text(name, NAME_MAX_LENGTH).casefold()
    proposed_sources = set(source_keys)
    matches = []
    for position, handle in enumerate(_catalog_handles(planning, 'workflows')):
        snapshot, record = snapshots.get(handle), records.get(handle)
        if not isinstance(snapshot, dict) or not isinstance(record, dict) or not record.get('id'):
            continue
        why = []
        if proposed_sources and proposed_sources & set(snapshot.get('source_keys') or ()):
            why.append('same_sources')
        if (
            trigger_type != 'manual' and schedule and snapshot.get('trigger_type') == trigger_type
            and snapshot.get('schedule') == schedule
        ):
            why.append('same_schedule')
        existing_name = str(snapshot.get('name') or '').casefold()
        if proposed_name and existing_name and (
            proposed_name == existing_name
            or difflib.SequenceMatcher(None, proposed_name, existing_name).ratio() >= SIMILAR_NAME_RATIO
        ):
            why.append('similar_name')
        if why:
            matches.append((len(why), position, {
                'workflow_id': record['id'],
                'name': str(snapshot.get('name') or ''),
                'schedule_label': str(snapshot.get('schedule_label') or ''),
                'why': why,
            }))
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _count, _position, entry in matches[:MAX_SIMILAR_WORKFLOWS]]


def _proposal_summary(blueprint, task_actions, planning, used, request_time_zone):
    capabilities = planning.get('agent_capabilities') if isinstance(planning.get('agent_capabilities'), dict) else {}
    agent_names = _catalog_names(planning, 'agents')
    document_names = _catalog_names(planning, 'documents')
    source_names = _catalog_names(planning, 'sources')
    trigger = blueprint.get('trigger') if isinstance(blueprint.get('trigger'), dict) else {}
    stored_type, schedule = stored_workflow_trigger(trigger)
    normalized = _normalized_schedule(schedule)
    zone = (normalized or {}).get('timezone') if (normalized or {}).get('kind') == 'calendar' else None

    tasks = []
    for index, task in enumerate(blueprint.get('tasks') or ()):
        task = task if isinstance(task, dict) else {}
        agent_ref = _runner_agent(task)
        entry = capabilities.get(agent_ref) if agent_ref else None
        tasks.append({
            'title': clean_catalog_text(task.get('title'), BLUEPRINT_TASK_TITLE_MAX_LENGTH),
            'runner': 'agent' if agent_ref else 'model',
            'agent_name': agent_names.get(agent_ref, '') if agent_ref else '',
            'action_kinds': list((entry or {}).get('action_kinds') or []) if isinstance(entry, dict) else [],
            'requested_actions': list(task_actions[index]) if index < len(task_actions) else [],
            'inputs': [
                document_names.get(handle) or 'Document'
                for handle in task.get('inputs') or () if isinstance(handle, str)
            ],
        })

    m365_sources, can_send, required = set(), False, False
    for agent_ref in used['agents']:
        entry = capabilities.get(agent_ref)
        if not isinstance(entry, dict):
            continue
        m365_sources.update(entry.get('m365_sources') or ())
        can_send = can_send or entry.get('can_send') is True
        required = required or entry.get('needs_run_as') is True
    alerts = blueprint.get('alerts') if isinstance(blueprint.get('alerts'), dict) else {}
    return {
        'name': clean_catalog_text(blueprint.get('name'), NAME_MAX_LENGTH * 2),
        'description': clean_catalog_text(blueprint.get('description'), 1000),
        'trigger_type': trigger.get('type') or 'manual',
        'schedule_label': workflow_schedule_label(stored_type, schedule) if schedule else '',
        'time_zone': zone or request_time_zone,
        'runs_per_month': workflow_proposal_runs_per_month(stored_type, normalized),
        'tasks': tasks,
        'file_sync_sources': [source_names.get(handle) or 'File Sync source' for handle in used['sources']],
        'm365': {
            'sources': _ordered(m365_sources, _M365_SOURCE_ORDER),
            'can_send': can_send,
            'run_as': blueprint.get('run_as') or 'none',
            'required': required,
        },
        'alerts': {'mode': alerts.get('mode') or 'every_run', 'severity': alerts.get('severity') or 'info'},
        'durable': True,
    }, stored_type, normalized


def _uncovered_task(blueprint, task_actions, planning):
    capabilities = planning.get('agent_capabilities') if isinstance(planning.get('agent_capabilities'), dict) else {}
    for index, task in enumerate(blueprint.get('tasks') or ()):
        needed = set(task_actions[index]) if index < len(task_actions) else set()
        if needed and not needed <= _agent_kinds(capabilities, _runner_agent(task if isinstance(task, dict) else {})):
            return True
    return False


def _uses_default_model(blueprint):
    return any(
        isinstance(task, dict) and _runner_agent(task) is None for task in blueprint.get('tasks') or ()
    )


def workflow_proposal_reason(codes, *, blueprint, task_actions, planning):
    """The first reason a proposal cannot be created as planned, or None when it can."""
    codes = set(codes)
    candidates = {_REASON_FOR_CODE[code] for code in codes if code in _REASON_FOR_CODE}
    if _uses_default_model(blueprint) and planning.get('default_model_valid') is False:
        candidates.add('model_unavailable')
    if _uncovered_task(blueprint, task_actions, planning):
        candidates.add('no_suitable_agent')
    if codes and not candidates:
        candidates.add('proposal_unavailable')
    for reason in WORKFLOW_PROPOSAL_REASONS:
        if reason in candidates:
            return reason
    return None


def _proposal_task_actions(arguments, blueprint):
    task_actions = arguments.get('task_actions') if isinstance(arguments.get('task_actions'), list) else []
    count = len(blueprint.get('tasks') or ())
    return [
        list(task_actions[index]) if index < len(task_actions) and isinstance(task_actions[index], list) else []
        for index in range(count)
    ]


def build_workflow_proposal(step, context, *, settings, user_id, producer, created_at):
    """Dry-run a step's blueprint and describe the proposal. Returns ``(sidecar, card value)``.

    The sidecar is server-only and never contains task instructions, which stay in the step's
    arguments. A proposal that cannot be created as planned is still described, with the reason.
    """
    arguments = step.get('arguments') if isinstance(step.get('arguments'), dict) else {}
    blueprint = arguments.get('blueprint') if isinstance(arguments.get('blueprint'), dict) else {}
    task_actions = _proposal_task_actions(arguments, blueprint)
    planning = getattr(context, 'workflow_planning', None)
    ready = workflow_planning_ready(planning)
    planning = planning if ready else {}
    request_time_zone = (
        getattr(context, 'time_zone', None) or planning.get('time_zone') or WORKFLOW_DEFAULT_TIME_ZONE
    )
    proposal_id = workflow_proposal_id(producer.run_id, producer.step_id)
    used = used_workflow_handles(blueprint, workflow_draft_handles(planning))
    summary, stored_type, normalized = _proposal_summary(blueprint, task_actions, planning, used, request_time_zone)

    codes = []
    reason = None
    if not ready:
        reason = 'proposal_unavailable'
    else:
        try:
            outcome = dry_run_workflow_blueprint(
                user_id, blueprint, used,
                origin={
                    'source': WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
                    'conversation_id': producer.conversation_id,
                    'orchestration_run_id': producer.run_id,
                    'proposal_id': proposal_id,
                    'created_at': _iso(created_at),
                    'edited': False,
                },
                settings=settings,
                user_info={
                    'userId': user_id, 'email': getattr(context, 'user_email', None),
                    'roles': list(getattr(context, 'user_roles', None) or []),
                },
                enabled=False, check_quota=True,
            )
            codes = sorted({error['code'] for error in outcome.get('errors') or ()})
            if not outcome.get('ok') and not codes:
                codes = ['blueprint_invalid']
            reason = workflow_proposal_reason(codes, blueprint=blueprint, task_actions=task_actions, planning=planning)
        except Exception as exc:
            _log(
                'A workflow proposal could not be dry-run.', logging.WARNING,
                run_id=producer.run_id, step_id=producer.step_id, error_type=type(exc).__name__,
            )
            reason = 'proposal_unavailable'

    status = WORKFLOW_PROPOSAL_STATUS_READY if reason is None else WORKFLOW_PROPOSAL_STATUS_UNAVAILABLE
    source_keys = planning.get('source_keys') if isinstance(planning.get('source_keys'), dict) else {}
    sidecar = {
        'version': WORKFLOW_PROPOSAL_VERSION,
        'proposal_id': proposal_id,
        'origin_run_id': producer.run_id,
        'step_id': producer.step_id,
        'conversation_id': producer.conversation_id,
        'requester_user_id': user_id,
        'created_at': _iso(created_at),
        'expires_at': _iso(created_at + WORKFLOW_PROPOSAL_TTL) if isinstance(created_at, datetime) else None,
        'status': status,
        'reason': reason,
        'error_codes': codes,
        'blueprint_digest': canonical_digest(blueprint),
        'handles': used,
        'time_zone': request_time_zone,
        'summary': summary,
        'similar_workflows': _similar_workflows(
            planning, name=blueprint.get('name'), trigger_type=stored_type, schedule=normalized,
            source_keys=[source_keys[handle] for handle in used['sources'] if handle in source_keys],
        ) if ready else [],
    }
    card = {
        'version': WORKFLOW_PROPOSAL_VERSION,
        'name': summary['name'],
        'status': status,
        'reason': reason,
        'schedule_label': summary['schedule_label'],
        'created_at': _iso(created_at),
    }
    return sidecar, card


# ---------------------------------------------------------------------------
# The workflow_propose step
# ---------------------------------------------------------------------------

def _failure(exc):
    if isinstance(exc, ResultUnavailableError):
        return build_failure('result_unavailable')
    if isinstance(exc, ResultContractError):
        return build_failure('result_invalid')
    return failure_from_exception(exc)


def adapter_workflow_propose(step, context, *, settings, user_id, emit=None, cancel_requested=None):
    """Prepare one workflow proposal for the user's approval. Creates nothing.

    The step always completes when the proposal was described, even when it cannot be created as
    planned: the card then says why. Its retained ``proposal`` result holds only the name, status
    and schedule; the full description rides on the step record as a server-only sidecar.
    """
    service = require_result_service(context)
    producer = context.result_producer(step)
    if user_id != producer.user_id or context.plan_contract_version != 2:
        raise ResultUnavailableError('result_owner_mismatch')
    guard_token = context.result_guard_token_for_step(step['step_id'])
    input_fingerprint = context.result_input_fingerprint_for_step(step['step_id'])

    def recheck():
        if callable(cancel_requested) and cancel_requested():
            raise MixedSourceCancellationError('orchestration_workflow_propose')
        service.access.authorize_producer(producer, for_write=True)
        if context.result_guard_token_for_step(step['step_id']) != guard_token:
            raise ResultUnavailableError('result_attempt_stopped')

    try:
        recheck()
        sidecar, card = build_workflow_proposal(
            step, context, settings=settings, user_id=user_id, producer=producer, created_at=_now(),
        )
        recheck()
        task = service.persist_task_result(
            producer=producer, role='reason', status='complete',
            outputs=[NamedOutput(
                WORKFLOW_PROPOSAL_OUTPUT, WORKFLOW_PROPOSAL_OUTPUT_KIND, card,
                Completeness('complete', 1, 1, Coverage(1, 1, 'items'), 'valid', (WORKFLOW_PROPOSAL_CHECK,), ()),
            )],
            sources=[], origin='generated', guard_token=guard_token, upstream=(),
            input_fingerprint=input_fingerprint,
        )
        _log(
            'Prepared a workflow proposal.',
            run_id=context.run_id, conversation_id=context.conversation_id, step_id=step['step_id'],
            proposal_id=sidecar['proposal_id'], proposal_status=sidecar['status'],
            reason_code=sidecar['reason'], error_codes=sidecar['error_codes'],
        )
        result = build_step_result(
            status=STEP_STATUS_COMPLETED,
            summary=(
                'Prepared a workflow proposal for your approval.'
                if sidecar['status'] == WORKFLOW_PROPOSAL_STATUS_READY
                else 'Prepared a workflow proposal that cannot be created as planned.'
            ),
            task_result=task,
        )
        # build_step_result keeps only its own fields, so the sidecar is added afterwards.
        result['workflow_proposal'] = sidecar
        return result
    except MixedSourceCancellationError:
        raise
    except Exception as exc:
        raise_source_service_failure(exc)
        failure = _failure(exc)
        _log(
            'A workflow proposal could not be prepared.', logging.WARNING,
            run_id=context.run_id, conversation_id=context.conversation_id, step_id=step['step_id'],
            error_type=type(exc).__name__, reason_code=failure['code'],
        )
        return build_step_result(
            status=STEP_STATUS_FAILED, failure=failure, summary=failure['message'], error=failure['message'],
        )


def rebuild_workflow_proposal(step, context, *, settings, user_id, task):
    """Describe again the proposal of a completed step recovered without its sidecar. Never raises.

    The ids come from the retained result's producer and the creation time from its value, so the
    proposal keeps its id and expiry. Returns None when even that cannot be read.
    """
    try:
        producer = task.producer
        created_at = None
        try:
            service = require_result_service(context)
            value = service.open_result(task.output(WORKFLOW_PROPOSAL_OUTPUT), allow_partial=False).read_value()
            created_at = _parse_time(value.get('created_at')) if isinstance(value, dict) else None
        except Exception as exc:
            _log(
                'A recovered workflow proposal could not be read.', logging.WARNING,
                run_id=producer.run_id, step_id=producer.step_id, error_type=type(exc).__name__,
            )
        sidecar, _card = build_workflow_proposal(
            step, context, settings=settings, user_id=user_id, producer=producer,
            created_at=created_at or _now(),
        )
        if created_at is None:
            sidecar.update({
                'status': WORKFLOW_PROPOSAL_STATUS_UNAVAILABLE, 'reason': 'proposal_unavailable',
                'created_at': None, 'expires_at': None,
            })
        return sidecar
    except Exception as exc:
        _log(
            'A recovered workflow proposal could not be described.', logging.WARNING,
            step_id=step.get('step_id') if isinstance(step, dict) else None, error_type=type(exc).__name__,
        )
        return None


# ---------------------------------------------------------------------------
# Degrading a plan
# ---------------------------------------------------------------------------

def _bound_to(value, step_ids):
    binding = value.get('binding') if isinstance(value, dict) else None
    return isinstance(binding, dict) and binding.get('step_id') in step_ids


def drop_workflow_proposals(plan, deliverable_availability, *, reason='workflow_draft_invalid'):
    """Return copies of a raw plan and its deliverable availability without the workflow proposal.

    Used when a proposal could not be repaired, or could not be checked at all: the rest of the
    plan still runs, and each explicit workflow deliverable is reported as not delivered with
    ``reason`` (``workflow_draft_invalid`` or ``workflow_context_unavailable``). Every dependency,
    input binding, delivers entry and final response naming the proposal is removed, so nothing
    can read the dropped step.
    """
    plan = deepcopy(plan) if isinstance(plan, dict) else {}
    availability = deepcopy(deliverable_availability) if isinstance(deliverable_availability, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    dropped = {
        step.get('step_id') for step in steps
        if isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_PROPOSE
    }
    deliverables = plan.get('deliverables') if isinstance(plan.get('deliverables'), list) else None
    workflow_ids = {
        entry.get('id') for entry in deliverables or ()
        if isinstance(entry, dict) and entry.get('kind') == 'workflow'
    }
    kept = []
    for step in steps:
        if isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_PROPOSE:
            continue
        if isinstance(step, dict):
            if isinstance(step.get('depends_on'), list):
                step['depends_on'] = [value for value in step['depends_on'] if value not in dropped]
            if isinstance(step.get('inputs'), dict):
                step['inputs'] = {
                    name: value for name, value in step['inputs'].items() if not _bound_to(value, dropped)
                }
            if isinstance(step.get('delivers'), list):
                step['delivers'] = [value for value in step['delivers'] if value not in workflow_ids]
        kept.append(step)
    plan['steps'] = kept
    final = plan.get('final_response')
    if isinstance(final, dict) and final.get('step_id') in dropped:
        plan.pop('final_response')
    if deliverables is not None:
        remaining = []
        for entry in deliverables:
            if isinstance(entry, dict) and entry.get('kind') == 'workflow':
                if entry.get('requested') != 'explicit':
                    # Only an explicit ask is reported as not delivered.
                    continue
                entry['status'] = 'unavailable'
                entry['unavailable_reason'] = reason
                entry.pop('unavailable_message', None)
            remaining.append(entry)
        plan['deliverables'] = remaining
    if 'workflow' in availability:
        availability['workflow'] = {'status': 'unavailable', 'reason': reason}
    return plan, availability


__all__ = [
    'WORKFLOW_PROPOSAL_OUTPUT',
    'WORKFLOW_PROPOSAL_REASONS',
    'WORKFLOW_PROPOSAL_STATUS_READY',
    'WORKFLOW_PROPOSAL_STATUS_UNAVAILABLE',
    'WORKFLOW_PROPOSAL_TTL',
    'WORKFLOW_PROPOSAL_VERSION',
    'adapter_workflow_propose',
    'build_workflow_proposal',
    'drop_workflow_proposals',
    'prepare_workflow_proposal_arguments',
    'rebuild_workflow_proposal',
    'stored_workflow_trigger',
    'used_workflow_handles',
    'workflow_proposal_id',
    'workflow_proposal_reason',
    'workflow_proposal_runs_per_month',
]
