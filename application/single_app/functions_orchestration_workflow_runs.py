# functions_orchestration_workflow_runs.py
"""Starting saved workflows from chat orchestration: plan checks, the run step and degrading.

Version: 0.261.211
Implemented in: 0.261.211

A plan starts one of the requester's saved personal workflows with one ``workflow_run`` step per
workflow. The step's only argument, ``workflow``, is a request-local handle from the turn's
workflow planning context (``functions_orchestration_workflow_context``). The step takes no
dependencies and no inputs, so no step result, and so no email, document or web content, can
choose which workflow runs. This module

* checks a run step while a plan is validated: the handle is written in the step's own
  arguments, names a workflow with durable execution that the request offered, and each workflow
  is started once, at most ``WORKFLOW_RUNS_MAX_PER_PLAN`` per plan;
* drops the run steps that still break those rules after the planner's correction round, so the
  rest of the plan runs and the reply says why each workflow was not started;
* runs the step.

Logs carry codes and counts only, never workflow names or handles.
"""

import logging
import re
from copy import deepcopy

from functions_appinsights import log_event
from functions_orchestration_registry import (
    CAPABILITY_WORKFLOW_RUN,
    WORKFLOW_HANDLE_PATTERN,
    WORKFLOW_RUNS_MAX_PER_PLAN,
)
from functions_orchestration_schema import (
    STEP_STATUS_FAILED,
    WORKFLOW_RUN_INVALID_CODE,
    PlanValidationError,
    build_failure,
    build_step_result,
)
from functions_orchestration_workflow_context import workflow_run_ready


WORKFLOW_RUN_OUTPUT = 'run'
WORKFLOW_RUN_OUTPUT_KIND = 'structured-v1'

# Plan-check rules. Each is also the reason a dropped step is reported with, except the static
# input and consumed rules, which both report the plan as invalid.
RULE_STATIC_INPUT = 'workflow_run_static_input'
RULE_UNKNOWN = 'workflow_run_unknown'
RULE_NOT_DURABLE = 'workflow_not_durable'
RULE_DUPLICATE = 'workflow_run_duplicate'
RULE_LIMIT = 'workflow_run_limit'
RULE_CONSUMED = 'workflow_run_consumed'
RULE_CONTEXT_UNAVAILABLE = 'workflow_context_unavailable'

REASON_INVALID = 'workflow_run_invalid'

# Why a workflow the plan named was not started. Application-owned text only: it reaches the plan
# card, the planner's failure message and the reply, so it never repeats a handle or a name.
WORKFLOW_RUN_SKIP_REASONS = {
    RULE_UNKNOWN: (
        "A workflow the plan named isn't one of your saved workflows that chat can start. Start it "
        'from Workflows, or name it exactly as it is saved.'
    ),
    RULE_NOT_DURABLE: (
        'Only workflows with durable execution turned on can be started from chat. Open the workflow '
        'in Workflows and select Run, or turn on durable execution.'
    ),
    RULE_LIMIT: (
        f'One plan can start at most {WORKFLOW_RUNS_MAX_PER_PLAN} workflows. Ask for the rest in a '
        'new message.'
    ),
    RULE_DUPLICATE: 'A plan starts each workflow once.',
    REASON_INVALID: (
        "A workflow step was planned in a way SimpleChat can't run, so it was left out. Ask again, "
        'naming the workflow to start.'
    ),
    RULE_CONTEXT_UNAVAILABLE: 'Your saved workflows could not be checked for this request. Try again later.',
}
_REASON_FOR_RULE = {
    RULE_UNKNOWN: RULE_UNKNOWN,
    RULE_NOT_DURABLE: RULE_NOT_DURABLE,
    RULE_DUPLICATE: RULE_DUPLICATE,
    RULE_LIMIT: RULE_LIMIT,
    RULE_CONTEXT_UNAVAILABLE: RULE_CONTEXT_UNAVAILABLE,
}
NO_WORKFLOW_STARTED = 'No workflow was started.'

_HANDLE = re.compile(WORKFLOW_HANDLE_PATTERN)
_LOG_PREFIX = '[ORCHESTRATION_WORKFLOW_RUNS]'


def _log(message, level=logging.INFO, **fields):
    # Codes and counts only: never workflow names, handles or catalog text.
    log_event(f'{_LOG_PREFIX} {message}', extra={'stage': 'workflow_run', **fields}, level=level)


# ---------------------------------------------------------------------------
# Plan checks
# ---------------------------------------------------------------------------

def _invalid(rule, message):
    return PlanValidationError(message, code=WORKFLOW_RUN_INVALID_CODE, rule=rule)


def workflow_run_catalog_entry(workflow_planning, handle):
    """The catalog entry the request offered for ``handle``, or None. Never raises.

    The handle must be in both the planner-facing catalog and the server-side handle map, with a
    record id, so a handle the planner invented, or one whose record is missing, is never used.
    """
    if not isinstance(workflow_planning, dict) or not isinstance(handle, str):
        return None
    handles = workflow_planning.get('handles')
    handles = handles.get('workflows') if isinstance(handles, dict) else None
    record = handles.get(handle) if isinstance(handles, dict) else None
    if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not record['id'].strip():
        return None
    catalog = workflow_planning.get('catalog')
    entries = catalog.get('workflows') if isinstance(catalog, dict) else None
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, dict) and entry.get('handle') == handle:
            return entry
    return None


def prepare_workflow_run_arguments(raw, arguments, *, workflow_planning=None, seen=None):
    """Check one workflow_run step while a plan is validated; return its arguments.

    ``raw`` is the planner's step and ``arguments`` its arguments. The workflow is named only by the
    handle in the step's own arguments: the step takes no ``depends_on`` and no ``inputs``, so no
    result of another step can choose which workflow runs.

    ``seen`` collects the handles that earlier run steps of the same plan start, so each workflow
    is started once and a plan starts at most ``WORKFLOW_RUNS_MAX_PER_PLAN``.

    Without ``workflow_planning`` (a stored plan revalidated for execution), only those checks
    apply; the step resolves and checks its workflow again when it runs. With it (a new plan or a
    plan revision), the handle must name a workflow the request offered, with durable execution
    turned on.

    Raises ``PlanValidationError`` with code ``workflow_run_invalid``. Its rule is
    ``workflow_context_unavailable`` when the check itself could not run, which no repair can fix.
    The message never repeats a handle or a name.
    """
    raw = raw if isinstance(raw, dict) else {}
    if raw.get('depends_on') or raw.get('inputs'):
        raise _invalid(
            RULE_STATIC_INPUT,
            'A workflow_run step names its workflow in its own arguments: remove its depends_on and its inputs.',
        )
    handle = arguments.get('workflow') if isinstance(arguments, dict) else None
    if (
        not isinstance(arguments, dict) or set(arguments) != {'workflow'}
        or not isinstance(handle, str) or not _HANDLE.fullmatch(handle)
    ):
        raise _invalid(
            RULE_STATIC_INPUT,
            'A workflow_run step takes exactly one argument, "workflow", set to a handle from '
            'workflow_planning.catalog.workflows. It cannot be bound to another step\'s output.',
        )
    seen = seen if isinstance(seen, set) else set()
    if handle in seen:
        raise _invalid(
            RULE_DUPLICATE, 'A plan starts each workflow once: remove the second workflow_run step for it.',
        )
    if workflow_planning is not None:
        if not workflow_run_ready(workflow_planning):
            raise _invalid(RULE_CONTEXT_UNAVAILABLE, 'The saved workflows could not be checked for this request.')
        entry = workflow_run_catalog_entry(workflow_planning, handle)
        if entry is None:
            raise _invalid(
                RULE_UNKNOWN,
                'A workflow_run step names a workflow that is not in workflow_planning.catalog.workflows. '
                'Use a handle from that catalog, or plan no step for it and say in the answer that the '
                'workflow was not found.',
            )
        if entry.get('durable') is not True:
            raise _invalid(
                RULE_NOT_DURABLE,
                'A workflow_run step names a workflow whose "durable" is false; it cannot be started from '
                'chat. Plan no step for it, and say in the answer that the user can open it in Workflows '
                'and select Run, or turn on durable execution.',
            )
    if len(seen) >= WORKFLOW_RUNS_MAX_PER_PLAN:
        raise _invalid(
            RULE_LIMIT, f'A plan starts at most {WORKFLOW_RUNS_MAX_PER_PLAN} workflows: remove the extra workflow_run steps.',
        )
    seen.add(handle)
    return arguments


# ---------------------------------------------------------------------------
# Degrading a plan
# ---------------------------------------------------------------------------

def _named(value, step_ids):
    return isinstance(value, str) and value in step_ids


def _bound_to(value, step_ids):
    binding = value.get('binding') if isinstance(value, dict) else None
    return isinstance(binding, dict) and _named(binding.get('step_id'), step_ids)


def _consumed_step_ids(steps, final_response, run_ids):
    """The run steps another step or the final response names."""
    consumed = set()
    for step in steps:
        if not isinstance(step, dict) or _named(step.get('step_id'), run_ids):
            continue
        depends_on = step.get('depends_on')
        for value in depends_on if isinstance(depends_on, list) else ():
            if _named(value, run_ids):
                consumed.add(value)
        inputs = step.get('inputs')
        for value in inputs.values() if isinstance(inputs, dict) else ():
            if _bound_to(value, run_ids):
                consumed.add(value['binding']['step_id'])
    if isinstance(final_response, dict) and _named(final_response.get('step_id'), run_ids):
        consumed.add(final_response['step_id'])
    return consumed


def drop_workflow_runs(plan, *, workflow_planning=None, drop_all=False):
    """Return a copy of a raw plan without the workflow_run steps that cannot run, and why.

    Used when a run step could not be repaired (each run step is checked again on its own, in plan
    order, and only the failing ones are dropped), or could not be checked at all (``drop_all``).
    A run step that another step or the final response reads is dropped as invalid. Every
    dependency, input binding and final response naming a dropped step is removed, so nothing can
    read it. When no single step fails its check, every run step is dropped, so a plan can always
    be planned without them.

    Returns ``(plan, notes, remaining)``: ``notes`` lists ``{'reason', 'name'}`` once for each
    distinct reason and workflow, where ``name`` is the saved name when the request offered the
    workflow, else None; ``remaining`` counts the run steps kept.
    """
    plan = deepcopy(plan) if isinstance(plan, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    run_steps = [
        step for step in steps if isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_RUN
    ]
    run_ids = {step.get('step_id') for step in run_steps if isinstance(step.get('step_id'), str)}
    consumed = _consumed_step_ids(steps, plan.get('final_response'), run_ids)
    seen = set()
    dropped = []
    for step in run_steps:
        if drop_all:
            reason = RULE_CONTEXT_UNAVAILABLE
        elif _named(step.get('step_id'), consumed):
            reason = REASON_INVALID
        else:
            try:
                prepare_workflow_run_arguments(
                    step, step.get('arguments'), workflow_planning=workflow_planning, seen=seen,
                )
                continue
            except PlanValidationError as exc:
                reason = _REASON_FOR_RULE.get(exc.rule, REASON_INVALID)
        dropped.append((step, reason))
    if not dropped:
        dropped = [(step, REASON_INVALID) for step in run_steps]

    notes = []
    for step, reason in dropped:
        arguments = step.get('arguments') if isinstance(step.get('arguments'), dict) else {}
        entry = workflow_run_catalog_entry(workflow_planning, arguments.get('workflow'))
        name = entry.get('name') if isinstance(entry, dict) and isinstance(entry.get('name'), str) else None
        note = {'reason': reason, 'name': name or None}
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
    final = plan.get('final_response')
    if isinstance(final, dict) and _named(final.get('step_id'), dropped_ids):
        plan.pop('final_response')
    return plan, notes, len(run_steps) - len(dropped_steps)


def workflow_run_repair_text(note):
    """The plan card line for one dropped run step. Names are shown as plain text there."""
    note = note if isinstance(note, dict) else {}
    text = WORKFLOW_RUN_SKIP_REASONS.get(note.get('reason')) or WORKFLOW_RUN_SKIP_REASONS[REASON_INVALID]
    name = note.get('name')
    return f'"{name}" will not be started. {text}' if isinstance(name, str) and name else text


def workflow_run_failure_message(notes):
    """The planner's failure message when a plan could not be made without its run steps.

    It holds application-owned text only, never a workflow name, because it may be shown as
    Markdown.
    """
    texts = []
    for note in notes or ():
        text = WORKFLOW_RUN_SKIP_REASONS.get(note.get('reason')) if isinstance(note, dict) else None
        if text and text not in texts:
            texts.append(text)
    return ' '.join([NO_WORKFLOW_STARTED, *texts])


# ---------------------------------------------------------------------------
# The workflow_run step
# ---------------------------------------------------------------------------

def adapter_workflow_run(step, context, *, settings, user_id, emit=None, cancel_requested=None):
    """Start the saved workflow a workflow_run step names. Fails closed, starting nothing.

    Starting a run needs the approval floor and the run-start path, which are not part of this
    build, so the step reports a failure and has no side effects.
    """
    failure = build_failure('step_failed')
    _log(
        'A workflow run step was not started.', logging.WARNING,
        run_id=getattr(context, 'run_id', None), reason_code=failure['code'],
    )
    return build_step_result(
        status=STEP_STATUS_FAILED, failure=failure, summary=failure['message'], error=failure['message'],
    )


__all__ = [
    'NO_WORKFLOW_STARTED',
    'REASON_INVALID',
    'WORKFLOW_RUN_OUTPUT',
    'WORKFLOW_RUN_OUTPUT_KIND',
    'WORKFLOW_RUN_SKIP_REASONS',
    'adapter_workflow_run',
    'drop_workflow_runs',
    'prepare_workflow_run_arguments',
    'workflow_run_catalog_entry',
    'workflow_run_failure_message',
    'workflow_run_repair_text',
]
