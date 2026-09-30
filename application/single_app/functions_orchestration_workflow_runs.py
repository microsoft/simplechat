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
* runs the step: it starts the workflow through the durable workflow queue, once per plan, and
  links to the run. It never waits for the run or reads its results. A small retained ``run``
  result holds the workflow's name and whether it started; the workflow and run ids ride on the
  step record as a server-only sidecar that the run link reads;
* rebuilds that sidecar when a completed step was recovered or reused without it.

The run is started with a request id derived from the plan's first attempt and the step, so the
run id is deterministic: a retry of the plan, a second tab or a crash between starting the run and
saving the step finds the run instead of starting another. The only write is the queue's.

Logs carry codes and counts only, never workflow names or handles.
"""

import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_appinsights import log_event
from functions_m365_workflow_binding import M365_ACTIVE_STATES
from functions_mixed_source_orchestration import MixedSourceCancellationError
from functions_orchestration_registry import (
    CAPABILITY_WORKFLOW_RUN,
    ROLE_GATHER,
    WORKFLOW_HANDLE_PATTERN,
    WORKFLOW_RUNS_MAX_PER_PLAN,
)
from functions_orchestration_result_contracts import Completeness, Coverage, ResultContractError
from functions_orchestration_result_runtime import raise_source_service_failure, require_result_service
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_orchestration_schema import (
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    WORKFLOW_RUN_INVALID_CODE,
    PlanValidationError,
    build_failure,
    build_step_result,
    failure_from_exception,
)
from functions_orchestration_workflow_context import (
    NAME_MAX_LENGTH,
    WORKFLOW_REASON_CONTEXT_UNAVAILABLE,
    WORKFLOW_REASON_ROLE_REQUIRED,
    WORKFLOW_REASON_SHARED_CONVERSATION,
    WORKFLOW_RUNS_REASON_DISABLED,
    clean_catalog_text,
    refresh_workflow_planning_privacy,
    workflow_run_gate,
    workflow_run_ready,
    workflow_run_settings_gate,
)


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

WORKFLOW_RUN_VERSION = 1
WORKFLOW_RUN_CHECK = 'workflow_run_start'
# The trigger a run started from chat records, which run history and alerts show as its trigger.
WORKFLOW_RUN_TRIGGER_SOURCE = 'chat_orchestration'
# Namespace for a run step's request id: one per first attempt and step, so every retry of a plan
# finds the run its first attempt started.
WORKFLOW_RUN_REQUEST_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'urn:simplechat:orchestration-workflow-runs')

# How a workflow_run step ended. The first three mean a run exists and the step links to it.
WORKFLOW_RUN_STATUS_QUEUED = 'queued'
WORKFLOW_RUN_STATUS_RUNNING = 'running'
WORKFLOW_RUN_STATUS_ALREADY_STARTED = 'already_started'
WORKFLOW_RUN_STATUS_UNAVAILABLE = 'unavailable'
WORKFLOW_RUN_STARTED_STATUSES = frozenset({
    WORKFLOW_RUN_STATUS_QUEUED, WORKFLOW_RUN_STATUS_RUNNING, WORKFLOW_RUN_STATUS_ALREADY_STARTED,
})
WORKFLOW_RUN_STATUSES = WORKFLOW_RUN_STARTED_STATUSES | {WORKFLOW_RUN_STATUS_UNAVAILABLE}

# Why a step that ran did not start its workflow. The step still completes, so the rest of the
# plan runs and the answer says why.
REASON_WORKFLOW_UNAVAILABLE = 'workflow_unavailable'
REASON_WAITING_FOR_MICROSOFT_365 = 'workflow_waiting_for_microsoft_365'
REASON_ALREADY_RUNNING = 'workflow_already_running'
REASON_DEFINITION_CHANGED = 'workflow_definition_changed'
REASON_RUN_TOMBSTONED = 'workflow_run_tombstoned'
REASON_ACCESS_LOST = 'workflow_access_lost'
REASON_NOT_STARTED = 'workflow_run_not_started'

# Application-owned text for each reason. It never repeats a handle, a name or an error.
WORKFLOW_RUN_REASON_TEXT = {
    WORKFLOW_RUNS_REASON_DISABLED: 'Starting saved workflows from chat is turned off for this deployment.',
    WORKFLOW_REASON_ROLE_REQUIRED: 'Your account does not have access to personal workflows.',
    WORKFLOW_REASON_SHARED_CONVERSATION: (
        'Saved workflows can be started only from your own conversations, not from shared ones.'
    ),
    WORKFLOW_REASON_CONTEXT_UNAVAILABLE: (
        'Your saved workflows could not be checked for this request. Ask again in a new message.'
    ),
    REASON_WORKFLOW_UNAVAILABLE: (
        "The workflow can't be started from chat. It may have been deleted, or it can't run as saved. "
        'Open it in Workflows to check it.'
    ),
    RULE_NOT_DURABLE: WORKFLOW_RUN_SKIP_REASONS[RULE_NOT_DURABLE],
    REASON_WAITING_FOR_MICROSOFT_365: (
        'The workflow is waiting for a Microsoft 365 approval or sign-in. Finish that in Workflows, '
        'then run it again.'
    ),
    REASON_ALREADY_RUNNING: (
        'The workflow is already running. You can follow that run in Workflows and start the workflow '
        'again once it finishes.'
    ),
    REASON_DEFINITION_CHANGED: (
        'The workflow changed while it was being started. Ask again in a new message to start its '
        'current version.'
    ),
    REASON_RUN_TOMBSTONED: "The workflow couldn't be started. Ask again in a new message.",
    REASON_ACCESS_LOST: 'You no longer have access to start this workflow.',
    REASON_NOT_STARTED: "The workflow couldn't be started. Open it in Workflows to run it.",
}
# The workflow runtime's conflict codes. Any other code, including one added later, reads as
# not started; the runtime's code and message are never shown.
_CONFLICT_REASONS = {
    'workflow_already_running': REASON_ALREADY_RUNNING,
    'workflow_definition_changed': REASON_DEFINITION_CHANGED,
    'workflow_deleting': REASON_WORKFLOW_UNAVAILABLE,
    'workflow_deleted': REASON_WORKFLOW_UNAVAILABLE,
    'tombstoned': REASON_RUN_TOMBSTONED,
}
# Step failures of the workflow_run step. Each leaves the step retryable: a retry uses the same
# request id, so it links a run this plan already started instead of starting another.
FAILURE_RUNTIME_UNAVAILABLE = 'workflow_runtime_unavailable'
FAILURE_SESSION_REQUIRED = 'external_session_required'
_STEP_SUMMARIES = {
    WORKFLOW_RUN_STATUS_QUEUED: 'Started the saved workflow.',
    WORKFLOW_RUN_STATUS_RUNNING: 'Started the saved workflow.',
    WORKFLOW_RUN_STATUS_ALREADY_STARTED: 'Linked the run this plan already started for the saved workflow.',
    WORKFLOW_RUN_STATUS_UNAVAILABLE: 'The saved workflow was not started.',
}
_DEFAULT_WORKFLOW_NAME = 'Workflow'

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
# Request ids, run ids and links
# ---------------------------------------------------------------------------

def workflow_run_request_id(attempt_root_run_id, step_id):
    """The request id a plan's workflow_run step starts its run with.

    It is derived from the plan's first attempt, not the current one, so every retry of the plan
    queues the same request and the workflow runtime gives it the same run id. A new plan, even for
    the same message, has a new first attempt and so starts a new run.
    """
    if not isinstance(attempt_root_run_id, str) or not attempt_root_run_id:
        raise ValueError('A workflow run request needs the plan attempt it belongs to.')
    if not isinstance(step_id, str) or not step_id:
        raise ValueError('A workflow run request needs its step.')
    return str(uuid.uuid5(WORKFLOW_RUN_REQUEST_NAMESPACE, f'{attempt_root_run_id}:{step_id}'))


def _workflow_run_id(user_id, workflow_id, request_id):
    # Imported here: the workflow runtime loads only when a plan starts a workflow, and importing
    # it with the orchestration modules would close an import cycle through the plugin loader.
    from functions_workflow_runtime import workflow_run_id_for_request

    return workflow_run_id_for_request({'id': workflow_id, 'user_id': user_id}, request_id)


def started_workflow_run_id(user_id, workflow_id, *, attempt_root_run_id, step_id):
    """The id of the run a plan's workflow_run step starts for ``workflow_id``. Raises ValueError.

    The same formula the step starts its run with, so a caller holding a stored run id can confirm
    it is the one this plan and step started.
    """
    return _workflow_run_id(user_id, workflow_id, workflow_run_request_id(attempt_root_run_id, step_id))


def _workflow_id(workflow_planning, handle):
    """The saved workflow id the request offered for ``handle``, or None."""
    if workflow_run_catalog_entry(workflow_planning, handle) is None:
        return None
    return workflow_planning['handles']['workflows'][handle]['id']


def _attempt_root(context):
    root = getattr(context, 'attempt_root_run_id', None)
    return root if isinstance(root, str) and root else context.run_id


def workflow_run_link(workflow_planning, handle, *, user_id, attempt_root_run_id, step_id):
    """``{'workflow_id', 'run_id'}`` for the run a workflow_run step starts, or None. Never raises.

    The ids are computed, not read, so a step recovered or reused without its sidecar, or one that
    failed after its run started, still links to that run.
    """
    try:
        workflow_id = _workflow_id(workflow_planning, handle)
        if workflow_id is None or not isinstance(user_id, str) or not user_id:
            return None
        request_id = workflow_run_request_id(attempt_root_run_id, step_id)
        return {'workflow_id': workflow_id, 'run_id': _workflow_run_id(user_id, workflow_id, request_id)}
    except Exception as exc:
        _log('A workflow run link could not be computed.', logging.WARNING, error_type=type(exc).__name__)
        return None


# ---------------------------------------------------------------------------
# Storage reads and the queue (one point read each; tests replace these)
# ---------------------------------------------------------------------------

class _WorkflowRunStepFailure(Exception):
    """A condition that fails the step with an application-owned failure code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _point_read(container, item, partition_key):
    try:
        return container.read_item(item=item, partition_key=partition_key)
    except CosmosResourceNotFoundError:
        return None
    except AzureError as exc:
        # Unavailable storage is not a missing workflow: the step fails and can be retried.
        raise _WorkflowRunStepFailure(FAILURE_RUNTIME_UNAVAILABLE) from exc


def _read_conversation(conversation_id):
    from config import cosmos_conversations_container

    return _point_read(cosmos_conversations_container, conversation_id, conversation_id)


def _read_workflow(user_id, workflow_id):
    from config import cosmos_personal_workflows_container

    return _point_read(cosmos_personal_workflows_container, workflow_id, user_id)


def _read_workflow_run(user_id, run_id):
    from config import cosmos_personal_workflow_runs_container

    return _point_read(cosmos_personal_workflow_runs_container, run_id, user_id)


def _queue_workflow_run(workflow, **options):
    # Imported here for the same reason as _workflow_run_id.
    from functions_workflow_runtime import queue_durable_workflow_run

    return queue_durable_workflow_run(workflow, **options)


def _runtime_terminal_states():
    from functions_workflow_runtime import RUNTIME_TERMINAL_STATES

    return RUNTIME_TERMINAL_STATES


def _runtime_errors():
    from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict

    return RuntimeUnavailable, WorkflowRuntimeConflict


# ---------------------------------------------------------------------------
# The workflow_run step
# ---------------------------------------------------------------------------

def _display_name(workflow, entry):
    for value in (
        workflow.get('name') if isinstance(workflow, dict) else None,
        entry.get('name') if isinstance(entry, dict) else None,
    ):
        text = clean_catalog_text(value, NAME_MAX_LENGTH)
        if text:
            return text
    return _DEFAULT_WORKFLOW_NAME


def _outcome(status, *, name, workflow_id=None, run_id=None, reason=None, queued=False):
    return {
        'status': status, 'reason': reason, 'name': name,
        'workflow_id': workflow_id,
        'run_id': run_id if status in WORKFLOW_RUN_STARTED_STATUSES else None,
        'queued': queued,
    }


def _started_status(run):
    state = str((run or {}).get('status') or '').strip().lower() if isinstance(run, dict) else ''
    if state in _runtime_terminal_states():
        return WORKFLOW_RUN_STATUS_ALREADY_STARTED
    if state == WORKFLOW_RUN_STATUS_RUNNING:
        return WORKFLOW_RUN_STATUS_RUNNING
    return WORKFLOW_RUN_STATUS_QUEUED


def _start(step, context, *, settings, user_id, recheck, requested_at):
    """Start or link the step's workflow run. Returns an outcome; raises only to fail the step.

    Linking a run this plan already started needs only the deployment's settings, the private
    conversation and the workflow; starting one also needs a signed-in session, the user's
    workflow role, durable execution and no Microsoft 365 wait.
    """
    step_id = step['step_id']
    handle = (step.get('arguments') or {}).get('workflow')
    entry = workflow_run_catalog_entry(getattr(context, 'workflow_planning', None), handle)
    name = _display_name(None, entry)

    def unavailable(reason, workflow_id=None):
        return _outcome(WORKFLOW_RUN_STATUS_UNAVAILABLE, name=name, workflow_id=workflow_id, reason=reason)

    reason = workflow_run_settings_gate(settings)
    if reason:
        return unavailable(reason)
    conversation = _read_conversation(context.conversation_id)
    if (
        not isinstance(conversation, dict) or conversation.get('user_id') != user_id
        or conversation.get('orchestration_deleted')
    ):
        return unavailable(WORKFLOW_REASON_CONTEXT_UNAVAILABLE)
    planning = refresh_workflow_planning_privacy(getattr(context, 'workflow_planning', None), conversation, user_id)
    if not isinstance(planning, dict):
        return unavailable(WORKFLOW_REASON_CONTEXT_UNAVAILABLE)
    if planning.get('conversation_private') is not True:
        return unavailable(WORKFLOW_REASON_SHARED_CONVERSATION)
    workflow_id = _workflow_id(planning, handle) if workflow_run_ready(planning) else None
    if workflow_id is None:
        return unavailable(WORKFLOW_REASON_CONTEXT_UNAVAILABLE)
    workflow = _read_workflow(user_id, workflow_id)
    if (
        not isinstance(workflow, dict) or workflow.get('id') != workflow_id
        or workflow.get('user_id') != user_id or workflow.get('deleting')
    ):
        return unavailable(REASON_WORKFLOW_UNAVAILABLE)
    name = _display_name(workflow, entry)

    # The run id is computed before anything else is checked: a run this plan already started is
    # linked, even when a later run of the workflow is active or the workflow changed since.
    request_id = workflow_run_request_id(_attempt_root(context), step_id)
    run_id = _workflow_run_id(user_id, workflow_id, request_id)
    existing = _read_workflow_run(user_id, run_id)
    if existing is not None:
        if existing.get('workflow_id') != workflow_id or existing.get('user_id') != user_id:
            return unavailable(REASON_WORKFLOW_UNAVAILABLE, workflow_id)
        if (
            str(existing.get('status') or '').strip().lower() in _runtime_terminal_states()
            or workflow.get('active_run_id') == run_id
        ):
            return _outcome(
                WORKFLOW_RUN_STATUS_ALREADY_STARTED, name=name, workflow_id=workflow_id, run_id=run_id,
            )
        # A run record the workflow does not hold: queueing the same request finishes starting it.

    if getattr(context, 'signed_in_session', False) is not True:
        raise _WorkflowRunStepFailure(FAILURE_SESSION_REQUIRED)
    reason = workflow_run_gate(settings, getattr(context, 'user_roles', None))
    if reason:
        return unavailable(reason, workflow_id)
    if workflow.get('durable_execution') is not True:
        return unavailable(RULE_NOT_DURABLE, workflow_id)
    if workflow.get('status') in M365_ACTIVE_STATES:
        return unavailable(REASON_WAITING_FOR_MICROSOFT_365, workflow_id)

    recheck()
    runtime_unavailable, runtime_conflict = _runtime_errors()
    try:
        queued = _queue_workflow_run(
            {'id': workflow_id, 'user_id': user_id},
            actor_user_id=user_id,
            trigger_source=WORKFLOW_RUN_TRIGGER_SOURCE,
            request_id=request_id,
            chat_invocation={
                'version': WORKFLOW_RUN_VERSION,
                'source': WORKFLOW_RUN_TRIGGER_SOURCE,
                'conversation_id': context.conversation_id,
                'user_message_id': getattr(context, 'user_message_id', None),
                'orchestration_run_id': context.run_id,
                'attempt_root_run_id': _attempt_root(context),
                'step_id': step_id,
                'requested_by': user_id,
                'requested_at': requested_at,
            },
        )
    except runtime_conflict as exc:
        code = getattr(exc, 'code', None)
        return unavailable(_CONFLICT_REASONS.get(code if isinstance(code, str) else None, REASON_NOT_STARTED), workflow_id)
    except runtime_unavailable as exc:
        raise _WorkflowRunStepFailure(FAILURE_RUNTIME_UNAVAILABLE) from exc
    except PermissionError:
        return unavailable(REASON_ACCESS_LOST, workflow_id)
    except (ValueError, LookupError):
        return unavailable(REASON_WORKFLOW_UNAVAILABLE, workflow_id)
    except AzureError as exc:
        raise _WorkflowRunStepFailure(FAILURE_RUNTIME_UNAVAILABLE) from exc
    run = queued.get('run') if isinstance(queued, dict) else None
    return _outcome(_started_status(run), name=name, workflow_id=workflow_id, run_id=run_id, queued=True)


def _sidecar(step, context, *, user_id, producer_run_id, outcome):
    return {
        'version': WORKFLOW_RUN_VERSION,
        'step_id': step['step_id'],
        'orchestration_run_id': producer_run_id,
        'attempt_root_run_id': _attempt_root(context),
        'conversation_id': context.conversation_id,
        'requested_by': user_id,
        'handle': (step.get('arguments') or {}).get('workflow'),
        'workflow_id': outcome.get('workflow_id'),
        'run_id': outcome.get('run_id') if outcome.get('status') in WORKFLOW_RUN_STARTED_STATUSES else None,
        'name': outcome.get('name') or _DEFAULT_WORKFLOW_NAME,
        'status': outcome.get('status'),
        'reason': outcome.get('reason'),
    }


def _failure(exc):
    if isinstance(exc, ResultUnavailableError):
        return build_failure('result_unavailable')
    if isinstance(exc, ResultContractError):
        return build_failure('result_invalid')
    return failure_from_exception(exc)


def _failed(failure):
    return build_step_result(
        status=STEP_STATUS_FAILED, failure=failure, summary=failure['message'], error=failure['message'],
    )


def adapter_workflow_run(step, context, *, settings, user_id, emit=None, cancel_requested=None):
    """Start the saved workflow a workflow_run step names, or link the run this plan already started.

    The step completes when it started or linked the run, and also when the workflow could not be
    started for a reason the user can act on: its retained ``run`` result then says why, and the
    rest of the plan runs. It fails, retryably, only when storage or the user's signed-in session
    was unavailable; a retry uses the same request id, so it never starts a second run.
    """
    service = require_result_service(context)
    producer = context.result_producer(step)
    if user_id != producer.user_id or context.plan_contract_version != 2:
        raise ResultUnavailableError('result_owner_mismatch')
    step_id = step['step_id']
    guard_token = context.result_guard_token_for_step(step_id)
    input_fingerprint = context.result_input_fingerprint_for_step(step_id)

    def recheck():
        if callable(cancel_requested) and cancel_requested():
            raise MixedSourceCancellationError('orchestration_workflow_run')
        service.access.authorize_producer(producer, for_write=True)
        if context.result_guard_token_for_step(step_id) != guard_token:
            raise ResultUnavailableError('result_attempt_stopped')

    try:
        recheck()
        outcome = _start(
            step, context, settings=settings, user_id=user_id, recheck=recheck,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        if not outcome['queued']:
            # Nothing was started here, so a stop still ends the step before it records anything.
            recheck()
        task = service.persist_task_result(
            producer=producer, role=ROLE_GATHER, status='complete',
            outputs=[NamedOutput(
                WORKFLOW_RUN_OUTPUT, WORKFLOW_RUN_OUTPUT_KIND,
                {
                    'version': WORKFLOW_RUN_VERSION, 'name': outcome['name'],
                    'status': outcome['status'], 'reason': outcome['reason'],
                },
                Completeness('complete', 1, 1, Coverage(1, 1, 'items'), 'valid', (WORKFLOW_RUN_CHECK,), ()),
            )],
            sources=[], origin='generated', guard_token=guard_token, upstream=(),
            input_fingerprint=input_fingerprint,
        )
        _log(
            'A workflow run step finished.',
            run_id=context.run_id, step_id=step_id,
            workflow_run_status=outcome['status'], reason_code=outcome['reason'],
        )
        result = build_step_result(
            status=STEP_STATUS_COMPLETED, summary=_STEP_SUMMARIES[outcome['status']], task_result=task,
        )
        # build_step_result keeps only its own fields, so the sidecar is added afterwards.
        result['workflow_run'] = _sidecar(
            step, context, user_id=user_id, producer_run_id=producer.run_id, outcome=outcome,
        )
        return result
    except MixedSourceCancellationError:
        raise
    except _WorkflowRunStepFailure as exc:
        failure = build_failure(exc.code)
        _log(
            'A workflow run step failed.', logging.WARNING,
            run_id=context.run_id, step_id=step_id, reason_code=failure['code'],
        )
        return _failed(failure)
    except Exception as exc:
        raise_source_service_failure(exc)
        failure = _failure(exc)
        _log(
            'A workflow run step failed.', logging.WARNING,
            run_id=context.run_id, step_id=step_id, error_type=type(exc).__name__, reason_code=failure['code'],
        )
        return _failed(failure)


def rebuild_workflow_run(step, context, *, user_id, task):
    """Describe again the run of a completed step recovered or reused without its sidecar. Never raises.

    The name and start status come from the retained result, the ids are computed again from the
    turn's planning context, the plan's first attempt and the step, and the producing run comes
    from the result's producer. Returns None when the retained result cannot be read, so the step
    is then treated as one whose run may have started.
    """
    try:
        service = require_result_service(context)
        value = service.open_result(task.output(WORKFLOW_RUN_OUTPUT), allow_partial=False).read_value()
        status = value.get('status') if isinstance(value, dict) else None
        if status not in WORKFLOW_RUN_STATUSES:
            return None
        reason = value.get('reason') if value.get('reason') in WORKFLOW_RUN_REASON_TEXT else None
        link = workflow_run_link(
            getattr(context, 'workflow_planning', None), (step.get('arguments') or {}).get('workflow'),
            user_id=user_id, attempt_root_run_id=_attempt_root(context), step_id=step['step_id'],
        ) or {}
        outcome = _outcome(
            status, name=clean_catalog_text(value.get('name'), NAME_MAX_LENGTH) or _DEFAULT_WORKFLOW_NAME,
            workflow_id=link.get('workflow_id'), run_id=link.get('run_id'), reason=reason,
        )
        return _sidecar(step, context, user_id=user_id, producer_run_id=task.producer.run_id, outcome=outcome)
    except Exception as exc:
        _log(
            'A recovered workflow run could not be described.', logging.WARNING,
            step_id=step.get('step_id') if isinstance(step, dict) else None, error_type=type(exc).__name__,
        )
        return None


def workflow_run_reason_text(reason):
    """The application-owned sentence for a closed reason, or the generic not-started one."""
    return WORKFLOW_RUN_REASON_TEXT.get(reason) or WORKFLOW_RUN_REASON_TEXT[REASON_NOT_STARTED]


__all__ = [
    'FAILURE_RUNTIME_UNAVAILABLE',
    'NO_WORKFLOW_STARTED',
    'REASON_INVALID',
    'WORKFLOW_RUN_OUTPUT',
    'WORKFLOW_RUN_OUTPUT_KIND',
    'WORKFLOW_RUN_REASON_TEXT',
    'WORKFLOW_RUN_REQUEST_NAMESPACE',
    'WORKFLOW_RUN_SKIP_REASONS',
    'WORKFLOW_RUN_STARTED_STATUSES',
    'WORKFLOW_RUN_STATUSES',
    'WORKFLOW_RUN_STATUS_ALREADY_STARTED',
    'WORKFLOW_RUN_STATUS_QUEUED',
    'WORKFLOW_RUN_STATUS_RUNNING',
    'WORKFLOW_RUN_STATUS_UNAVAILABLE',
    'WORKFLOW_RUN_TRIGGER_SOURCE',
    'WORKFLOW_RUN_VERSION',
    'adapter_workflow_run',
    'drop_workflow_runs',
    'prepare_workflow_run_arguments',
    'rebuild_workflow_run',
    'started_workflow_run_id',
    'workflow_run_catalog_entry',
    'workflow_run_failure_message',
    'workflow_run_link',
    'workflow_run_reason_text',
    'workflow_run_repair_text',
    'workflow_run_request_id',
]
