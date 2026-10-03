# functions_orchestration_workflow_handoffs.py
"""Workflow hand-offs from chat orchestration: plan checks, the hand-off step, degrading and the reply note.

Version: 0.261.232
Implemented in: 0.261.232

A request too large for one chat plan is handed to a one-time durable workflow with one
``workflow_handoff`` step. Its ``blueprint`` argument is the closed hand-off blueprint from
``functions_workflow_drafts``: a loop over the documents the user named or over a bounded
workspace query, then one task for each document and one report task. It names documents,
workspaces and agents by the request-local handles of the turn's workflow planning context
(``functions_orchestration_workflow_context``). This module

* checks a hand-off while a plan is validated: the step takes no dependencies or inputs, the
  blueprint passes every hand-off rule that reads nothing, names only offered handles, and runs
  its tasks only on the default model or on local agents;
* runs the step: a write-free dry run of the blueprint through the workflow draft service, a
  small retained ``handoff`` result for the run, and a server-only sidecar on the step record
  that the hand-off card and the accept route read. Nothing is created or started until the
  user approves the card;
* rebuilds that sidecar when a completed step was recovered without it;
* drops the hand-off from a plan whose blueprint could not be repaired, so the rest of the plan
  still runs and the reply says no workflow was handed off;
* writes the reply's note about the hand-off a plan prepared.

Nothing here writes or queues a workflow; the accept route in
``functions_orchestration_workflow_handoff_decisions`` does, once. Logs carry hashed ids and
application codes only, never names, instructions, handles or catalog text.
"""

import logging
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from functions_appinsights import log_event, workflow_log_context
from functions_mixed_source_orchestration import MixedSourceCancellationError
from functions_orchestration_registry import CAPABILITY_WORKFLOW_HANDOFF
from functions_orchestration_result_contracts import Completeness, Coverage, ResultContractError, canonical_digest
from functions_orchestration_result_runtime import raise_source_service_failure, require_result_service
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_orchestration_schema import (
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    WORKFLOW_HANDOFF_INVALID_CODE,
    PlanValidationError,
    build_failure,
    build_step_result,
    failure_from_exception,
)
from functions_orchestration_workflow_context import (
    NAME_MAX_LENGTH,
    WORKFLOW_DEFAULT_TIME_ZONE,
    clean_catalog_text,
    workflow_handoff_ready,
)
from functions_workflow_chat_delivery import normalize_model_selection


WORKFLOW_HANDOFF_VERSION = 1
# Namespace for hand-off ids: one hand-off per producing run and step, stable across recovery.
WORKFLOW_HANDOFF_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'urn:simplechat:workflow-handoffs')
WORKFLOW_HANDOFF_TTL = timedelta(days=14)
WORKFLOW_HANDOFF_OUTPUT = 'handoff'
WORKFLOW_HANDOFF_OUTPUT_KIND = 'structured-v1'
WORKFLOW_HANDOFF_CHECK = 'workflow_handoff_dry_run'

WORKFLOW_HANDOFF_STATUS_READY = 'ready'
WORKFLOW_HANDOFF_STATUS_INVALID = 'invalid'
WORKFLOW_HANDOFF_STATUS_UNAVAILABLE = 'unavailable'
WORKFLOW_HANDOFF_STATUSES = (
    WORKFLOW_HANDOFF_STATUS_READY, WORKFLOW_HANDOFF_STATUS_INVALID, WORKFLOW_HANDOFF_STATUS_UNAVAILABLE,
)

# Plan-check rules this module adds to the draft service's own error codes.
RULE_STATIC_INPUT = 'workflow_handoff_static_input'
RULE_CONTEXT_UNAVAILABLE = 'workflow_context_unavailable'
RULE_AGENT_UNSUPPORTED = 'handoff_agent_unsupported'

# Why a hand-off was left out of a plan or cannot be accepted as prepared. Each has fixed text.
REASON_INVALID = 'workflow_handoff_invalid'
REASON_LOOP_LIMIT = 'handoff_loop_limit'
REASON_AGENT_UNSUPPORTED = RULE_AGENT_UNSUPPORTED
REASON_NOT_AVAILABLE = 'handoff_unavailable'
REASON_SOURCES_UNAVAILABLE = 'handoff_sources_unavailable'
REASON_PREPARE_FAILED = 'handoff_prepare_failed'
_REASON_FOR_CODE = {
    RULE_CONTEXT_UNAVAILABLE: RULE_CONTEXT_UNAVAILABLE,
    'handoff_loop_limit': REASON_LOOP_LIMIT,
    'handoff_limit_changed': REASON_LOOP_LIMIT,
    'handoff_agent_unsupported': REASON_AGENT_UNSUPPORTED,
    'handoff_unavailable': REASON_NOT_AVAILABLE,
    'handoff_analyze_unavailable': REASON_NOT_AVAILABLE,
    'workflows_unavailable': REASON_NOT_AVAILABLE,
    'reference_unknown': REASON_SOURCES_UNAVAILABLE,
    'reference_unauthorized': REASON_SOURCES_UNAVAILABLE,
    'scope_unavailable': REASON_SOURCES_UNAVAILABLE,
    'agent_unavailable': REASON_SOURCES_UNAVAILABLE,
}

NO_WORKFLOW_HANDED_OFF = 'No workflow was handed off.'
# Application-owned text for each reason. It reaches the plan card, the planner's failure message
# and the reply, so it never repeats a handle, a name or an error.
WORKFLOW_HANDOFF_REASON_TEXT = {
    REASON_INVALID: (
        "The hand-off was planned in a way SimpleChat can't run. Ask again, naming the documents or "
        'the workspace to review.'
    ),
    RULE_CONTEXT_UNAVAILABLE: (
        'Your documents and workspaces could not be checked for this request. Ask again in a new message.'
    ),
    REASON_LOOP_LIMIT: (
        'The request covers more documents than one hand-off can review. Ask again with a narrower request.'
    ),
    REASON_AGENT_UNSUPPORTED: (
        'A hand-off runs its tasks on the default model or on a local agent. Ask again without naming '
        'that agent.'
    ),
    REASON_NOT_AVAILABLE: "Handing work off to a workflow isn't available with this deployment's workflow settings.",
    REASON_SOURCES_UNAVAILABLE: (
        'A document, workspace or agent the hand-off named is no longer available to you. Ask again in '
        'a new message.'
    ),
    REASON_PREPARE_FAILED: "The hand-off couldn't be prepared. Ask again in a new message.",
}
# The reply's note for a hand-off card the plan prepared. Nothing runs until the user approves it.
WORKFLOW_HANDOFF_NOTE = (
    'Prepared a one-time workflow for this request. Nothing runs until you approve it on the hand-off card.'
)

_LOG_PREFIX = '[ORCHESTRATION_WORKFLOW_HANDOFFS]'


def _log(message, level=logging.INFO, *, run_id=None, step_id=None, **fields):
    # Hashed ids and application codes, under keys the log allowlist keeps: never blueprint text,
    # names, handles or catalog entries.
    log_event(
        f'{_LOG_PREFIX} {message}',
        extra={'stage': 'workflow_handoff', **workflow_log_context(run_id=run_id, step_id=step_id), **fields},
        level=level,
    )


def workflow_handoff_id(run_id, step_id):
    """The id of the hand-off a run's workflow_handoff step made; its one-time workflow derives from it."""
    return str(uuid.uuid5(WORKFLOW_HANDOFF_NAMESPACE, f'{run_id}:{step_id}'))


def workflow_handoff_reason(code):
    """The closed reason a draft error code or plan rule reports a hand-off with."""
    return _REASON_FOR_CODE.get(code, REASON_INVALID)


def workflow_handoff_reason_text(reason):
    """Application-owned text for a closed hand-off reason. An unknown reason reads as invalid."""
    return WORKFLOW_HANDOFF_REASON_TEXT.get(reason, WORKFLOW_HANDOFF_REASON_TEXT[REASON_INVALID])


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
    details = '; '.join(f"[{error['code']}] {error['path'] or '/'}: {error['message']}" for error in errors)
    return PlanValidationError(
        'The workflow_handoff blueprint breaks these rules: ' + details,
        code=WORKFLOW_HANDOFF_INVALID_CODE, rule=rule or errors[0]['code'],
    )


def _context_unavailable(message=None):
    return PlanValidationError(
        message or (
            'Handing work off to a workflow is unavailable for this request. Remove the workflow_handoff '
            'step and answer what you can within the plan limits.'
        ),
        code=WORKFLOW_HANDOFF_INVALID_CODE, rule=RULE_CONTEXT_UNAVAILABLE,
    )


def _agent_errors(blueprint, marker):
    """Draft errors for each task that names an agent the request did not offer as local."""
    from functions_workflow_drafts import draft_error

    local = marker.get('agent_local') if isinstance(marker.get('agent_local'), dict) else {}
    errors = []
    for index, task in enumerate(blueprint.get('tasks') or ()):
        runner = task.get('runner') if isinstance(task, dict) else None
        if isinstance(runner, dict) and runner.get('type') == 'agent' and local.get(runner.get('agent_ref')) is not True:
            errors.append(draft_error(RULE_AGENT_UNSUPPORTED, ('tasks', index, 'runner', 'agent_ref')))
    return errors


def prepare_workflow_handoff_arguments(raw, arguments, *, settings=None, workflow_planning=None):
    """Check a workflow_handoff step's static blueprint and return its normalized arguments.

    A hand-off is reviewed on its own card and runs later, so it consumes nothing: a step with
    ``depends_on`` or ``inputs`` is refused. Without a planning context only the rules that read
    nothing apply. With one, the blueprint must also pass the administrator's limits, name only
    the handles offered with the request, and name only local agents. Raises
    ``PlanValidationError`` with the repairable ``workflow_handoff_invalid`` code.
    """
    raw = raw if isinstance(raw, dict) else {}
    if raw.get('depends_on') or raw.get('inputs'):
        raise PlanValidationError(
            'A workflow_handoff step takes only its static blueprint argument. Remove its depends_on '
            'and inputs; the handed-off workflow finds its own documents.',
            code=WORKFLOW_HANDOFF_INVALID_CODE, rule=RULE_STATIC_INPUT,
        )
    if not isinstance(arguments, dict) or set(arguments) != {'blueprint'}:
        raise PlanValidationError(
            'A workflow_handoff step takes exactly one argument, blueprint.',
            code=WORKFLOW_HANDOFF_INVALID_CODE, rule=REASON_INVALID,
        )
    # The draft service loads workflow storage helpers, so it is imported only for a hand-off.
    from functions_workflow_drafts import check_handoff_blueprint, validate_handoff_blueprint

    if workflow_planning is None:
        errors = validate_handoff_blueprint(arguments['blueprint'])
        if errors:
            raise _blueprint_error(errors)
        return arguments
    if not workflow_handoff_ready(workflow_planning) or not settings:
        raise _context_unavailable()
    marker = workflow_planning['workflow_handoff']
    try:
        prepared, errors = check_handoff_blueprint(
            arguments['blueprint'], settings=settings, handle_names=marker['handles'],
        )
    except Exception as exc:
        _log(
            'Hand-off blueprint could not be checked; handing work off is unavailable for this plan.',
            logging.WARNING, reason=RULE_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        raise _context_unavailable(
            'The workflow_handoff blueprint could not be checked for this request. Remove the '
            'workflow_handoff step.',
        ) from exc
    if errors:
        raise _blueprint_error(errors)
    errors = _agent_errors(prepared, marker)
    if errors:
        raise _blueprint_error(errors)
    return {**arguments, 'blueprint': prepared}


# ---------------------------------------------------------------------------
# Degrading a plan whose hand-off could not be repaired
# ---------------------------------------------------------------------------

def _named(value, step_ids):
    return isinstance(value, str) and value in step_ids


def _bound_to(value, step_ids):
    binding = value.get('binding') if isinstance(value, dict) else None
    return isinstance(binding, dict) and _named(binding.get('step_id'), step_ids)


def _consumed_step_ids(steps, final_response, ids):
    """The ids in ``ids`` another step depends on or binds an input to, or the answer selects."""
    consumed = set()
    for step in steps:
        if not isinstance(step, dict) or step.get('step_id') in ids:
            continue
        depends_on = step.get('depends_on') if isinstance(step.get('depends_on'), list) else []
        consumed.update(value for value in depends_on if _named(value, ids))
        inputs = step.get('inputs') if isinstance(step.get('inputs'), dict) else {}
        for value in inputs.values():
            if _bound_to(value, ids):
                consumed.add(value['binding']['step_id'])
    if isinstance(final_response, dict) and _named(final_response.get('step_id'), ids):
        consumed.add(final_response['step_id'])
    return consumed


def drop_workflow_handoffs(plan, *, workflow_planning=None, settings=None, drop_all=False):
    """Remove the hand-off steps the planner could not repair. Returns ``(plan, notes, remaining)``.

    Mirrors ``drop_workflow_runs``. Each hand-off step that still fails its checks is dropped;
    when every one passes, the failure came from how the plan used them, so all are dropped.
    ``drop_all`` drops every one, for a planning context that could not be read. References to a
    dropped step are removed, an answer that selects one is cleared, and each drop gets a note
    ``{'reason'}`` with a closed reason. ``remaining`` counts the hand-off steps left.
    """
    plan = deepcopy(plan) if isinstance(plan, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    handoff_steps = [
        step for step in steps
        if isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_HANDOFF
    ]
    handoff_ids = {step.get('step_id') for step in handoff_steps if isinstance(step.get('step_id'), str)}
    consumed = _consumed_step_ids(steps, plan.get('final_response'), handoff_ids)
    dropped = []
    for step in handoff_steps:
        if drop_all:
            reason = RULE_CONTEXT_UNAVAILABLE
        elif step.get('step_id') in consumed:
            reason = REASON_INVALID
        else:
            try:
                prepare_workflow_handoff_arguments(
                    step, step.get('arguments'), settings=settings, workflow_planning=workflow_planning,
                )
                continue
            except PlanValidationError as exc:
                reason = workflow_handoff_reason(exc.rule)
        dropped.append((step, reason))
    if not dropped:
        dropped = [(step, REASON_INVALID) for step in handoff_steps]
    notes = []
    for _step, reason in dropped:
        note = {'reason': reason}
        if note not in notes:
            notes.append(note)
    dropped_steps = [step for step, _reason in dropped]
    dropped_ids = {step.get('step_id') for step in dropped_steps if isinstance(step.get('step_id'), str)}
    kept = []
    for step in steps:
        if any(step is candidate for candidate in dropped_steps):
            continue
        if isinstance(step, dict):
            if isinstance(step.get('depends_on'), list):
                step['depends_on'] = [value for value in step['depends_on'] if not _named(value, dropped_ids)]
            if isinstance(step.get('inputs'), dict):
                step['inputs'] = {
                    name: value for name, value in step['inputs'].items() if not _bound_to(value, dropped_ids)
                }
        kept.append(step)
    plan['steps'] = kept
    if isinstance(plan.get('final_response'), dict) and _named(plan['final_response'].get('step_id'), dropped_ids):
        plan.pop('final_response', None)
    return plan, notes, len(handoff_steps) - len(dropped_steps)


def workflow_handoff_repair_text(note):
    """The plan card's repair line for a hand-off the planner left out."""
    reason = note.get('reason') if isinstance(note, dict) else None
    return f'{NO_WORKFLOW_HANDED_OFF} {workflow_handoff_reason_text(reason)}'


def workflow_handoff_failure_message(notes):
    """The planner's failure message when a plan held nothing but hand-offs it could not repair."""
    texts = []
    for note in notes if isinstance(notes, list) else ():
        text = workflow_handoff_reason_text(note.get('reason') if isinstance(note, dict) else None)
        if text not in texts:
            texts.append(text)
    return ' '.join([NO_WORKFLOW_HANDED_OFF, *texts])


# ---------------------------------------------------------------------------
# The reply's note
# ---------------------------------------------------------------------------

def _note_lines(plan, execution_steps):
    plan = plan if isinstance(plan, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    records = {
        record['step_id']: record for record in (execution_steps if isinstance(execution_steps, list) else ())
        if isinstance(record, dict) and isinstance(record.get('step_id'), str)
    }
    lines = []
    for step in steps:
        if not isinstance(step, dict) or step.get('capability_id') != CAPABILITY_WORKFLOW_HANDOFF:
            continue
        if not step.get('enabled', True):
            continue
        record = records.get(step.get('step_id')) if isinstance(step.get('step_id'), str) else None
        if (
            not isinstance(record, dict) or record.get('capability_id') != CAPABILITY_WORKFLOW_HANDOFF
            or record.get('status') != STEP_STATUS_COMPLETED
        ):
            continue
        sidecar = record.get('workflow_handoff')
        if not isinstance(sidecar, dict) or sidecar.get('status') not in WORKFLOW_HANDOFF_STATUSES:
            continue
        if sidecar['status'] == WORKFLOW_HANDOFF_STATUS_READY:
            line = WORKFLOW_HANDOFF_NOTE
        else:
            line = f'{NO_WORKFLOW_HANDED_OFF} {workflow_handoff_reason_text(sidecar.get("reason"))}'
        if line not in lines:
            lines.append(line)
    notes = plan.get('workflow_handoff_notes') if isinstance(plan.get('workflow_handoff_notes'), list) else []
    for note in notes:
        if not isinstance(note, dict):
            continue
        line = workflow_handoff_repair_text(note)
        if line not in lines:
            lines.append(line)
    return lines


def workflow_handoff_note(plan, execution_steps):
    """What the reply says about the hand-off a plan prepared or left out, or ''. Never raises.

    Application-owned text only: a completed hand-off step whose card is ready says nothing runs
    until the user approves the card, whatever the plan's own outcome, as the card does; one
    whose card could not be prepared, and each hand-off the planner left out, says no workflow
    was handed off and why. A step that failed or never ran is left to the failure explanation.
    """
    try:
        return '\n\n'.join(_note_lines(plan, execution_steps))
    except Exception as exc:
        _log('Hand-off note could not be written.', logging.WARNING, error_type=type(exc).__name__)
        return ''


def plan_has_workflow_handoff(plan):
    """Whether a plan has an enabled workflow_handoff step. Never raises."""
    steps = plan.get('steps') if isinstance(plan, dict) and isinstance(plan.get('steps'), list) else []
    return any(
        isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_HANDOFF
        and step.get('enabled', True) is not False
        for step in steps
    )


# ---------------------------------------------------------------------------
# The hand-off card and its server-only sidecar
# ---------------------------------------------------------------------------

# The first of these a hand-off's error codes map to is the reason its card reports.
_REASON_PRIORITY = (
    RULE_CONTEXT_UNAVAILABLE,
    REASON_NOT_AVAILABLE,
    REASON_SOURCES_UNAVAILABLE,
    REASON_AGENT_UNSUPPORTED,
    REASON_LOOP_LIMIT,
    REASON_INVALID,
)
# Reasons the user cannot fix by asking differently; the rest describe the request itself.
_UNAVAILABLE_REASONS = frozenset({
    RULE_CONTEXT_UNAVAILABLE, REASON_NOT_AVAILABLE, REASON_SOURCES_UNAVAILABLE, REASON_PREPARE_FAILED,
})


def _catalog_names(marker, kind):
    catalog = marker.get('catalog') if isinstance(marker.get('catalog'), dict) else {}
    return {
        entry['handle']: entry.get('name') or ''
        for entry in catalog.get(kind) or ()
        if isinstance(entry, dict) and isinstance(entry.get('handle'), str)
    }


def _runner_agent(task):
    runner = task.get('runner') if isinstance(task.get('runner'), dict) else {}
    agent_ref = runner.get('agent_ref')
    return agent_ref if runner.get('type') == 'agent' and isinstance(agent_ref, str) else None


def _used_handles(blueprint, offered):
    """The offered handle map entries a checked blueprint names, in the draft service's shape."""
    from functions_workflow_handoff_builder import HANDOFF_HANDLE_KINDS, handoff_handle_uses

    offered = offered if isinstance(offered, dict) else {}
    uses = handoff_handle_uses(blueprint)
    used = {}
    for kind in HANDOFF_HANDLE_KINDS:
        entries = offered.get(kind) if isinstance(offered.get(kind), dict) else {}
        used[kind] = {handle: deepcopy(entries[handle]) for handle in uses[kind] if handle in entries}
    return used


def _empty_handles():
    from functions_workflow_handoff_builder import HANDOFF_HANDLE_KINDS

    return {kind: {} for kind in HANDOFF_HANDLE_KINDS}


def _codes(errors):
    return sorted({
        error['code'] for error in errors or ()
        if isinstance(error, dict) and isinstance(error.get('code'), str)
    })


def _reason_for_codes(codes):
    """The reason a hand-off with these draft error codes reports, or None when there are none."""
    reasons = {workflow_handoff_reason(code) for code in codes}
    for reason in _REASON_PRIORITY:
        if reason in reasons:
            return reason
    return None


def _status_for(reason):
    if reason is None:
        return WORKFLOW_HANDOFF_STATUS_READY
    if reason in _UNAVAILABLE_REASONS:
        return WORKFLOW_HANDOFF_STATUS_UNAVAILABLE
    return WORKFLOW_HANDOFF_STATUS_INVALID


def _handoff_summary(blueprint, marker):
    """What the card shows about a hand-off: names, titles and runners. Never instructions or ids."""
    from functions_workflow_drafts import BLUEPRINT_TASK_TITLE_MAX_LENGTH
    from functions_workflow_handoff_builder import HANDOFF_ALERTS

    blueprint = blueprint if isinstance(blueprint, dict) else {}
    agent_names = _catalog_names(marker, 'agents')
    tasks = []
    for task in blueprint.get('tasks') or ():
        task = task if isinstance(task, dict) else {}
        agent_ref = _runner_agent(task)
        tasks.append({
            'title': clean_catalog_text(task.get('title'), BLUEPRINT_TASK_TITLE_MAX_LENGTH),
            'runner': 'agent' if agent_ref else 'model',
            'agent_name': agent_names.get(agent_ref, '') if agent_ref else '',
        })
    return {
        'name': clean_catalog_text(blueprint.get('name'), NAME_MAX_LENGTH * 2),
        'description': clean_catalog_text(blueprint.get('description'), 1000),
        'tasks': tasks,
        'alerts': dict(HANDOFF_ALERTS),
        'durable': True,
        'one_time': True,
    }


def _model_selection(context):
    """The chat's model choice, captured on the server when the step runs, for the delivery seed."""
    try:
        return normalize_model_selection(
            getattr(context, 'seeds', None), getattr(context, 'active_group_ids', None),
        )
    except Exception as exc:
        _log(
            'Hand-off model selection could not be captured; delivery uses the default model.',
            logging.WARNING, error_type=type(exc).__name__,
        )
        return None


def build_workflow_handoff(step, context, *, settings, user_id, producer, created_at):
    """Dry-run a step's hand-off blueprint and describe it. Returns ``(sidecar, card value)``.

    The sidecar is server-only: it holds the checked blueprint, the handle map entries it names,
    the dry-run outcome, the disclosure, and the model selection and time zone captured here for
    the accept route. The card value holds the name, summary, disclosure and status. A hand-off
    that cannot be accepted as planned is still described, with the reason. Writes nothing.
    """
    from functions_workflow_drafts import (
        WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
        WorkflowLoopLimitError,
        check_handoff_blueprint,
        dry_run_handoff_workflow,
    )

    arguments = step.get('arguments') if isinstance(step.get('arguments'), dict) else {}
    blueprint = arguments.get('blueprint') if isinstance(arguments.get('blueprint'), dict) else {}
    planning = getattr(context, 'workflow_planning', None)
    ready = workflow_handoff_ready(planning)
    marker = planning['workflow_handoff'] if ready else {}
    planning = planning if ready else {}
    time_zone = (
        getattr(context, 'time_zone', None) or marker.get('time_zone') or planning.get('time_zone')
        or WORKFLOW_DEFAULT_TIME_ZONE
    )
    handoff_id = workflow_handoff_id(producer.run_id, producer.step_id)

    prepared = None
    used = _empty_handles()
    codes = []
    dry_run_codes = []
    outcome = {}
    if not ready:
        reason = RULE_CONTEXT_UNAVAILABLE
    else:
        try:
            prepared, errors = check_handoff_blueprint(blueprint, settings=settings, handle_names=marker['handles'])
            if not errors:
                errors = _agent_errors(prepared, marker)
            if errors:
                codes = _codes(errors)
            else:
                used = _used_handles(prepared, marker['handles'])
                outcome = dry_run_handoff_workflow(
                    user_id, prepared, used,
                    origin={
                        'source': WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION,
                        'conversation_id': producer.conversation_id,
                        'orchestration_run_id': producer.run_id,
                        'proposal_id': handoff_id,
                        'created_at': _iso(created_at),
                        'edited': False,
                    },
                    settings=settings,
                    user_info={
                        'userId': user_id, 'email': getattr(context, 'user_email', None),
                        'roles': list(getattr(context, 'user_roles', None) or []),
                    },
                )
                dry_run_codes = _codes(outcome.get('errors'))
                if not outcome.get('ok') and not dry_run_codes:
                    dry_run_codes = ['blueprint_invalid']
                codes = list(dry_run_codes)
            reason = _reason_for_codes(codes)
        except WorkflowLoopLimitError:
            _log(
                'Hand-off loop limit is misconfigured; handing work off is unavailable.', logging.WARNING,
                run_id=producer.run_id, step_id=producer.step_id, reason=REASON_NOT_AVAILABLE,
            )
            reason = REASON_NOT_AVAILABLE
            outcome = {}
        except Exception as exc:
            _log(
                'A workflow hand-off could not be dry-run.', logging.WARNING,
                run_id=producer.run_id, step_id=producer.step_id, error_type=type(exc).__name__,
            )
            reason = REASON_PREPARE_FAILED
            outcome = {}

    status = _status_for(reason)
    dry_run_ok = bool(outcome.get('ok')) and reason is None
    stored_blueprint = deepcopy(prepared) if isinstance(prepared, dict) else deepcopy(blueprint)
    summary = _handoff_summary(stored_blueprint, marker)
    disclosure = deepcopy(outcome.get('disclosure')) if dry_run_ok else None
    sidecar = {
        'version': WORKFLOW_HANDOFF_VERSION,
        'handoff_id': handoff_id,
        'origin_run_id': producer.run_id,
        'step_id': producer.step_id,
        'conversation_id': producer.conversation_id,
        'requester_user_id': user_id,
        'created_at': _iso(created_at),
        'expires_at': _iso(created_at + WORKFLOW_HANDOFF_TTL) if isinstance(created_at, datetime) else None,
        'status': status,
        'reason': reason,
        'error_codes': codes,
        'blueprint': stored_blueprint,
        'blueprint_digest': canonical_digest(stored_blueprint),
        'handles': used,
        'dry_run': {'ok': dry_run_ok, 'error_codes': dry_run_codes},
        'disclosure': disclosure,
        'loop_limit': outcome.get('loop_limit') if dry_run_ok else None,
        'model_selection': _model_selection(context),
        'time_zone': time_zone,
        'summary': summary,
    }
    card = {
        'version': WORKFLOW_HANDOFF_VERSION,
        'handoff_id': handoff_id,
        'name': summary['name'],
        'summary': deepcopy(summary),
        'disclosure': deepcopy(disclosure),
        'status': status,
        'reason': reason,
        'created_at': _iso(created_at),
    }
    return sidecar, card


# ---------------------------------------------------------------------------
# The workflow_handoff step
# ---------------------------------------------------------------------------

def _failure(exc):
    if isinstance(exc, ResultUnavailableError):
        return build_failure('result_unavailable')
    if isinstance(exc, ResultContractError):
        return build_failure('result_invalid')
    return failure_from_exception(exc)


def adapter_workflow_handoff(step, context, *, settings, user_id, emit=None, cancel_requested=None):
    """Prepare one workflow hand-off for the user's approval. Creates and queues nothing.

    The step always completes when the hand-off was described, even when it cannot be handed
    off as planned: the card then says why. Its retained ``handoff`` result holds the name,
    summary, disclosure and status; the blueprint, handles and captured selections ride on the
    step record as a server-only sidecar for the accept route.
    """
    service = require_result_service(context)
    producer = context.result_producer(step)
    if user_id != producer.user_id or context.plan_contract_version != 2:
        raise ResultUnavailableError('result_owner_mismatch')
    guard_token = context.result_guard_token_for_step(step['step_id'])
    input_fingerprint = context.result_input_fingerprint_for_step(step['step_id'])

    def recheck():
        if callable(cancel_requested) and cancel_requested():
            raise MixedSourceCancellationError('orchestration_workflow_handoff')
        service.access.authorize_producer(producer, for_write=True)
        if context.result_guard_token_for_step(step['step_id']) != guard_token:
            raise ResultUnavailableError('result_attempt_stopped')

    try:
        recheck()
        sidecar, card = build_workflow_handoff(
            step, context, settings=settings, user_id=user_id, producer=producer, created_at=_now(),
        )
        recheck()
        task = service.persist_task_result(
            producer=producer, role='reason', status='complete',
            outputs=[NamedOutput(
                WORKFLOW_HANDOFF_OUTPUT, WORKFLOW_HANDOFF_OUTPUT_KIND, card,
                Completeness('complete', 1, 1, Coverage(1, 1, 'items'), 'valid', (WORKFLOW_HANDOFF_CHECK,), ()),
            )],
            sources=[], origin='generated', guard_token=guard_token, upstream=(),
            input_fingerprint=input_fingerprint,
        )
        _log(
            'Prepared a workflow hand-off.',
            run_id=context.run_id, step_id=step['step_id'],
            status=sidecar['status'], reason=sidecar['reason'], error_codes=sidecar['error_codes'],
        )
        result = build_step_result(
            status=STEP_STATUS_COMPLETED,
            summary=(
                'Prepared a one-time workflow hand-off for your approval.'
                if sidecar['status'] == WORKFLOW_HANDOFF_STATUS_READY
                else 'Prepared a one-time workflow hand-off that cannot be handed off as planned.'
            ),
            task_result=task,
        )
        # build_step_result keeps only its own fields, so the sidecar is added afterwards.
        result['workflow_handoff'] = sidecar
        return result
    except MixedSourceCancellationError:
        raise
    except Exception as exc:
        raise_source_service_failure(exc)
        failure = _failure(exc)
        _log(
            'A workflow hand-off could not be prepared.', logging.WARNING,
            run_id=context.run_id, step_id=step['step_id'],
            error_type=type(exc).__name__, failure_code=failure['code'],
        )
        return build_step_result(
            status=STEP_STATUS_FAILED, failure=failure, summary=failure['message'], error=failure['message'],
        )


def rebuild_workflow_handoff(step, context, *, settings, user_id, task):
    """Describe again the hand-off of a completed step recovered without its sidecar. Never raises.

    The ids come from the retained result's producer and the creation time from its value, so the
    hand-off keeps its id and expiry. A creation time that cannot be read leaves the hand-off
    unavailable. Returns None when even that cannot be described.
    """
    try:
        producer = task.producer
        created_at = None
        try:
            service = require_result_service(context)
            value = service.open_result(task.output(WORKFLOW_HANDOFF_OUTPUT), allow_partial=False).read_value()
            created_at = _parse_time(value.get('created_at')) if isinstance(value, dict) else None
        except Exception as exc:
            _log(
                'A recovered workflow hand-off could not be read.', logging.WARNING,
                run_id=producer.run_id, step_id=producer.step_id, error_type=type(exc).__name__,
            )
        sidecar, _card = build_workflow_handoff(
            step, context, settings=settings, user_id=user_id, producer=producer,
            created_at=created_at or _now(),
        )
        if created_at is None:
            sidecar.update({
                'status': WORKFLOW_HANDOFF_STATUS_UNAVAILABLE, 'reason': REASON_PREPARE_FAILED,
                'created_at': None, 'expires_at': None,
            })
        return sidecar
    except Exception as exc:
        _log(
            'A recovered workflow hand-off could not be described.', logging.WARNING,
            step_id=step.get('step_id') if isinstance(step, dict) else None, error_type=type(exc).__name__,
        )
        return None


__all__ = [
    'NO_WORKFLOW_HANDED_OFF',
    'REASON_AGENT_UNSUPPORTED',
    'REASON_INVALID',
    'REASON_LOOP_LIMIT',
    'REASON_NOT_AVAILABLE',
    'REASON_PREPARE_FAILED',
    'REASON_SOURCES_UNAVAILABLE',
    'RULE_AGENT_UNSUPPORTED',
    'RULE_CONTEXT_UNAVAILABLE',
    'RULE_STATIC_INPUT',
    'WORKFLOW_HANDOFF_CHECK',
    'WORKFLOW_HANDOFF_NAMESPACE',
    'WORKFLOW_HANDOFF_NOTE',
    'WORKFLOW_HANDOFF_OUTPUT',
    'WORKFLOW_HANDOFF_OUTPUT_KIND',
    'WORKFLOW_HANDOFF_REASON_TEXT',
    'WORKFLOW_HANDOFF_STATUSES',
    'WORKFLOW_HANDOFF_STATUS_INVALID',
    'WORKFLOW_HANDOFF_STATUS_READY',
    'WORKFLOW_HANDOFF_STATUS_UNAVAILABLE',
    'WORKFLOW_HANDOFF_TTL',
    'WORKFLOW_HANDOFF_VERSION',
    'adapter_workflow_handoff',
    'build_workflow_handoff',
    'drop_workflow_handoffs',
    'plan_has_workflow_handoff',
    'prepare_workflow_handoff_arguments',
    'rebuild_workflow_handoff',
    'workflow_handoff_failure_message',
    'workflow_handoff_id',
    'workflow_handoff_note',
    'workflow_handoff_reason',
    'workflow_handoff_reason_text',
    'workflow_handoff_repair_text',
]
