# functions_orchestration_workflow_runs.py
"""Starting saved workflows from chat orchestration: plan checks, the run step and degrading.

Version: 0.261.212
Implemented in: 0.261.212

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
  links to the run. A small retained ``run`` result holds the workflow's name and whether it
  started; the workflow and run ids ride on the step record as a server-only sidecar that the run
  link reads. When an administrator allows waiting for quick workflows, a step the server marked
  while it checked the plan holds the run's chat post-back and waits, within a bound, for the run
  (``resume_workflow_run_wait``): the plan then takes the result instead of the post-back, or,
  when the bound passes, lets the post-back post it. Its content is only ever read through the
  workflow results reader;
* rebuilds that sidecar when a completed step was recovered or reused without it;
* writes the reply's note, after the prepared answer, on which workflows the plan started, which
  it did not start and why, and where each run's results appear.

The run is started with a request id derived from the plan's first attempt and the step, so the
run id is deterministic: a retry of the plan, a second tab or a crash between starting the run and
saving the step finds the run instead of starting another. The only writes are the queue's and,
for a waiting step, compare-and-set writes to the run's chat post-back record.

Logs carry hashed run and step ids and application codes, never workflow names or handles.
"""

import logging
import math
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_appinsights import log_event, workflow_log_context
from functions_m365_workflow_binding import M365_ACTIVE_STATES
from functions_mixed_source_orchestration import MixedSourceCancellationError
from functions_orchestration_registry import (
    CAPABILITY_WORKFLOW_RUN,
    ROLE_GATHER,
    WORKFLOW_HANDLE_PATTERN,
    WORKFLOW_RUNS_MAX_PER_PLAN,
)
from functions_orchestration_result_contracts import (
    Completeness,
    Coverage,
    ResultContractError,
    TaskResult,
)
from functions_orchestration_result_runtime import (
    raise_source_service_failure,
    require_result_service,
    validate_task_outputs,
)
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_orchestration_schema import (
    STEP_STATUS_CANCELLED,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    STEP_STATUS_WAITING,
    WORKFLOW_RUN_INVALID_CODE,
    PlanValidationError,
    build_failure,
    build_step_result,
    failure_from_exception,
    workflow_run_catalog_entry,
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
    workflow_results_gate,
)
from functions_orchestration_workflow_run_wait import (
    SAVED_WORKFLOW_RUN_WAIT_KIND,
    compute_workflow_run_waits,
    quick_run_eligibility,
    wait_configured,
    waited_run_dependents,
    workflow_run_hold_until,
    workflow_run_wait_deadline,
    workflow_run_wait_ready,
)
from functions_workflow_chat_delivery import (
    CHAT_DELIVERY_KEY,
    FAILED_RUN_STATES,
    PLAN_WAIT_CONSUMED,
    PLAN_WAIT_ENDED,
    PLAN_WAIT_HELD,
    PLAN_WAIT_POSTED,
    PLAN_WAIT_RELEASED,
    RESULT_RUN_STATES,
    RUNTIME_TERMINAL_STATES,
    WORKFLOW_RUN_DELIVERY_FOLLOW_UP,
    WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY,
    apply_plan_wait_consume,
    apply_plan_wait_hold,
    apply_plan_wait_release,
    build_chat_delivery_seed,
    chat_delivery_applies,
    control_summary,
    normalize_model_selection,
    normalize_requester_roles,
    parse_delivery_timestamp,
    signal_workflow_chat_delivery,
)


WORKFLOW_RUN_OUTPUT = 'run'
WORKFLOW_RUN_OUTPUT_KIND = 'structured-v1'

# Plan-check rules. Each is also the reason a dropped step is reported with, except the static
# input rule, which reports the plan as invalid, as the schema's workflow_run_consumed rule does.
RULE_STATIC_INPUT = 'workflow_run_static_input'
RULE_UNKNOWN = 'workflow_run_unknown'
RULE_NOT_DURABLE = 'workflow_not_durable'
RULE_DUPLICATE = 'workflow_run_duplicate'
RULE_LIMIT = 'workflow_run_limit'
RULE_CONTEXT_UNAVAILABLE = 'workflow_context_unavailable'

REASON_INVALID = 'workflow_run_invalid'
# A plan read a run's result, and the server would not let this plan wait for that run.
REASON_NOT_WAITABLE = 'workflow_run_not_waitable'

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
    REASON_NOT_WAITABLE: (
        "A plan can use a workflow's results only when the workflow is a quick run and the rest of "
        'the plan can continue without you, so it was left out. Ask to start it in a new message.'
    ),
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
REASON_ONE_TIME = 'workflow_one_time'

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
    REASON_ONE_TIME: 'It was created for a single run. Open it in Workflows to run it again.',
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
# How many times a waiting plan's write to its run's delivery record reads the run again after
# another writer, such as the chat post-back worker, changed it first.
_DELIVERY_WRITE_RETRIES = 5
_STEP_SUMMARIES = {
    WORKFLOW_RUN_STATUS_QUEUED: 'Started the saved workflow.',
    WORKFLOW_RUN_STATUS_RUNNING: 'Started the saved workflow.',
    WORKFLOW_RUN_STATUS_ALREADY_STARTED: 'Linked the run this plan already started for the saved workflow.',
    WORKFLOW_RUN_STATUS_UNAVAILABLE: 'The saved workflow was not started.',
}
_DEFAULT_WORKFLOW_NAME = 'Workflow'

# The reply's note about the saved workflows a plan started. It says where a run's results appear.
# It promises them in the chat only when every run it started recorded a chat delivery, because only
# then does the server post each run's result back into this conversation when the run finishes.
WORKFLOW_RUN_NOTE_HEADING = 'Saved workflows:'
WORKFLOW_RUN_FOLLOW_UP = (
    "Follow the run's progress and results in the workflow's run history in Workflows. Results also "
    'appear wherever the workflow already sends them, such as its conversation or alerts.'
)
WORKFLOW_RUN_FOLLOW_UP_MANY = (
    "Follow each run's progress and results in that workflow's run history in Workflows. Results also "
    'appear wherever each workflow already sends them, such as its conversation or alerts.'
)
WORKFLOW_RUN_STOPPED = (
    "Stopping this plan doesn't stop a workflow it already started. Cancel the run in Workflows if "
    'you need to.'
)
_UNNAMED_WORKFLOW_NOTE = 'A workflow you asked for'

_HANDLE = re.compile(WORKFLOW_HANDLE_PATTERN)
_LOG_PREFIX = '[ORCHESTRATION_WORKFLOW_RUNS]'


def _log(message, level=logging.INFO, *, run_id=None, step_id=None, **fields):
    # Hashed ids and application codes, under keys the log allowlist keeps: never workflow names,
    # handles or catalog text.
    log_event(
        f'{_LOG_PREFIX} {message}',
        extra={'stage': 'workflow_run', **workflow_log_context(run_id=run_id, step_id=step_id), **fields},
        level=level,
    )


# ---------------------------------------------------------------------------
# Plan checks
# ---------------------------------------------------------------------------

def _invalid(rule, message):
    return PlanValidationError(message, code=WORKFLOW_RUN_INVALID_CODE, rule=rule)


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
    A run step that another step or the final response reads is dropped as invalid, unless the
    request's planning context lets the plan wait for that run (see
    ``functions_orchestration_workflow_run_wait``): then a step the server would wait for is kept,
    and any other one is dropped as not waitable. Every
    dependency, input binding and final response naming a dropped step is removed, so nothing can
    read it. When no single step fails its check, every run step the plan does not wait for is
    dropped, so a plan can always be planned without them.

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
    wait_ready = workflow_run_wait_ready(workflow_planning)
    waits = (
        compute_workflow_run_waits(steps, plan.get('final_response'), workflow_planning)
        if wait_ready and consumed and not drop_all else {}
    )
    seen = set()
    dropped = []
    for step in run_steps:
        if drop_all:
            reason = RULE_CONTEXT_UNAVAILABLE
        elif _named(step.get('step_id'), consumed) and not wait_ready:
            reason = REASON_INVALID
        elif _named(step.get('step_id'), consumed) and step.get('step_id') not in waits:
            reason = REASON_NOT_WAITABLE
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
        # A step the plan waits for passed every check a single run step can fail, so it stays.
        dropped = [(step, REASON_INVALID) for step in run_steps if step.get('step_id') not in waits]

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
# A waited run's chat post-back
# ---------------------------------------------------------------------------

def _runs_container():
    from config import cosmos_personal_workflow_runs_container

    return cosmos_personal_workflow_runs_container


def _status_code(exc):
    code = getattr(exc, 'status_code', None)
    return code if type(code) is int else None


def _runtime_store(user_id, workflow_id, run_id):
    from functions_workflow_runtime_store import workflow_runtime_store

    return workflow_runtime_store({'id': workflow_id, 'user_id': user_id}, run_id)


def read_run_control_summary(user_id, workflow_id, run_id):
    """The run's runtime control, summarized as the post-back reads it, or None when it can't be read now.

    A personal store's identity is the workflow ID and owner only, so the control of a run whose
    workflow was deleted still reads, as tombstoned, and a control that was never written reads as
    missing.
    """
    unavailable, conflict = _runtime_errors()
    try:
        control = _runtime_store(user_id, workflow_id, run_id).read(allow_deleted=True)
    except conflict as exc:
        return control_summary(None) if getattr(exc, 'code', None) == 'not_found' else None
    except unavailable:
        return None
    except Exception as exc:
        _log('A waited workflow run could not be read.', logging.WARNING, error_type=type(exc).__name__)
        return None
    return control_summary(control)


def _write_plan_wait(user_id, run_id, apply, *, orchestration_run_id, step_id, signal=False):
    """Decide with ``apply(record)`` and write the result with the run document's ETag.

    ``apply`` returns ``(updated, decision)``. It runs again on a fresh read whenever another writer,
    such as the post-back worker claiming the run, changed the run first, so every decision is made
    on the record its write replaces. Returns the decision, or None when the run can't be read or
    written right now.
    """
    try:
        container = _runs_container()
    except Exception as exc:
        _log(
            'Workflow runs are unavailable.', logging.WARNING,
            error_type=type(exc).__name__, run_id=orchestration_run_id, step_id=step_id,
        )
        return None
    for _attempt in range(_DELIVERY_WRITE_RETRIES + 1):
        try:
            run = container.read_item(item=run_id, partition_key=user_id)
        except Exception as exc:
            if _status_code(exc) == 404:
                return PLAN_WAIT_ENDED
            _log(
                'A waited workflow run could not be read.', logging.WARNING,
                error_type=type(exc).__name__, run_id=orchestration_run_id, step_id=step_id,
            )
            return None
        if not isinstance(run, dict) or run.get('user_id') != user_id or run.get('id') != run_id:
            return PLAN_WAIT_ENDED
        updated, decision = apply(run.get(CHAT_DELIVERY_KEY))
        if updated is None:
            return decision
        try:
            container.replace_item(
                item=run_id, body={**run, CHAT_DELIVERY_KEY: updated}, etag=run.get('_etag'),
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            code = _status_code(exc)
            if code == 412:
                continue
            if code == 404:
                return PLAN_WAIT_ENDED
            _log(
                'A waited workflow run could not be updated.', logging.WARNING,
                error_type=type(exc).__name__, run_id=orchestration_run_id, step_id=step_id,
            )
            return None
        if signal:
            signal_workflow_chat_delivery(user_id, run_id)
        return decision
    _log(
        'A waited workflow run kept changing; the plan will try again.', logging.WARNING,
        run_id=orchestration_run_id, step_id=step_id,
    )
    return None


def hold_chat_delivery(user_id, run_id, *, orchestration_run_id, step_id, until, now=None):
    """Hold the run's chat post-back for the plan step that waits on it, until ``until`` at the latest.

    Returns ``held``, or the post-back's own outcome when it already owns the run's result
    (``posted``, or ``ended`` when it can't post), or None when storage couldn't be reached.
    """
    return _write_plan_wait(
        user_id, run_id,
        lambda record: apply_plan_wait_hold(
            record, orchestration_run_id=orchestration_run_id, step_id=step_id, until=until, now=now,
        ),
        orchestration_run_id=orchestration_run_id, step_id=step_id,
    )


def consume_chat_delivery(user_id, run_id, summary, *, orchestration_run_id, step_id, now=None):
    """Mark the run's result as used in this plan's answer, so it's never posted to the chat as well.

    Returns ``consumed`` when the plan may use the result, ``held`` while the run hasn't finished,
    the post-back's ``posted`` or ``ended`` when it owns the result instead, or None when storage
    couldn't be reached.
    """
    return _write_plan_wait(
        user_id, run_id,
        lambda record: apply_plan_wait_consume(
            record, summary, orchestration_run_id=orchestration_run_id, step_id=step_id, now=now,
        ),
        orchestration_run_id=orchestration_run_id, step_id=step_id,
    )


def release_chat_delivery(user_id, run_id, *, orchestration_run_id, step_id, now=None):
    """Stop holding the run's chat post-back, so the result is posted to the chat when the run finishes.

    Returns ``released``, ``consumed`` when this step already used the result, the post-back's
    ``posted`` or ``ended``, or None when storage couldn't be reached; the hold then lapses on its own.
    """
    return _write_plan_wait(
        user_id, run_id,
        lambda record: apply_plan_wait_release(
            record, orchestration_run_id=orchestration_run_id, step_id=step_id, now=now,
        ),
        orchestration_run_id=orchestration_run_id, step_id=step_id, signal=True,
    )


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


def chat_delivery_seed_for(settings, *, user_roles, time_zone, model_selection, run_id=None):
    """Return the record that has a started run's result posted back to its chat, or None.

    Shared by a plan's ``workflow_run`` step and a hand-off's accept, so both record delivery the
    same way. ``model_selection`` is the normalized turn selection captured on the server. The
    cheap settings check comes first, so a deployment with Use Workflow Results In Chat off never
    reaches the role-aware gate. A failure here only means the run is not delivered: it never
    fails the start.
    """
    if not isinstance(settings, dict) or not settings.get('enable_chat_workflow_results'):
        return None
    try:
        # Settings initialize application storage, so they are imported only once a gate is reached.
        from functions_settings import is_chat_workflow_results_enabled_for_user

        if not is_chat_workflow_results_enabled_for_user(settings, user_roles=user_roles):
            return None
        return build_chat_delivery_seed(
            time_zone=time_zone,
            model_selection=model_selection,
            requester_roles=normalize_requester_roles(user_roles),
        )
    except Exception as exc:
        _log(
            'Chat delivery was not recorded for a started workflow run.', logging.WARNING,
            run_id=run_id, error_type=type(exc).__name__,
        )
        return None


def _chat_delivery_seed(settings, context, planning):
    """Return the record that has the run's result posted back to this chat, or None.

    The cheap settings check comes first, so a deployment with Use Workflow Results In Chat off
    never reaches the role-aware gate. A failure here only means the run is not delivered: it
    never fails the start.
    """
    if not isinstance(settings, dict) or not settings.get('enable_chat_workflow_results'):
        return None
    try:
        user_roles = getattr(context, 'user_roles', None)
        time_zone = getattr(context, 'time_zone', None)
        if not time_zone and isinstance(planning, dict):
            time_zone = planning.get('time_zone')
        model_selection = normalize_model_selection(
            getattr(context, 'seeds', None), getattr(context, 'active_group_ids', None),
        )
    except Exception as exc:
        _log(
            'Chat delivery was not recorded for a started workflow run.', logging.WARNING,
            run_id=getattr(context, 'run_id', None), error_type=type(exc).__name__,
        )
        return None
    return chat_delivery_seed_for(
        settings, user_roles=user_roles, time_zone=time_zone, model_selection=model_selection,
        run_id=getattr(context, 'run_id', None),
    )


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
    # A hand-off's workflow is made for its one run; the user can still run it again from Workflows.
    origin = workflow.get('origin')
    if isinstance(origin, dict) and origin.get('one_time') is True:
        return unavailable(REASON_ONE_TIME, workflow_id)
    if workflow.get('status') in M365_ACTIVE_STATES:
        return unavailable(REASON_WAITING_FOR_MICROSOFT_365, workflow_id)
    chat_delivery = _chat_delivery_seed(settings, context, planning)

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
            **({'chat_delivery': chat_delivery} if chat_delivery is not None else {}),
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
    outcome = _outcome(_started_status(run), name=name, workflow_id=workflow_id, run_id=run_id, queued=True)
    # Only a run this call started, carrying this chat's delivery record, is posted back here.
    if (
        chat_delivery is not None
        and outcome['status'] in (WORKFLOW_RUN_STATUS_QUEUED, WORKFLOW_RUN_STATUS_RUNNING)
        and chat_delivery_applies(run, context.conversation_id)
    ):
        outcome['chat_delivery'] = True
    # Read by the adapter only, to decide whether a step this plan waits on may wait; never persisted.
    outcome['_workflow'] = workflow
    return outcome


def _sidecar(step, context, *, user_id, producer_run_id, outcome):
    sidecar = {
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
    # Set only by a start that recorded this chat's delivery, never for a linked or rebuilt run.
    if outcome.get('chat_delivery') is True:
        sidecar['chat_delivery'] = True
    if isinstance(outcome.get('wait'), dict):
        sidecar['wait'] = deepcopy(outcome['wait'])
    return sidecar


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


# ---------------------------------------------------------------------------
# Waiting for a quick run
# ---------------------------------------------------------------------------

# How a run step that the server let wait ended. Recorded in the step's retained ``run`` result
# and its sidecar, so the reply's note, the plan card and the steps that use the result agree.
WAIT_OUTCOME_CONSUMED = 'consumed'
WAIT_OUTCOME_TIMEOUT = 'timeout'
WAIT_OUTCOME_POSTED = 'posted'
WAIT_OUTCOME_ENDED = 'ended'
WAIT_OUTCOMES = frozenset({WAIT_OUTCOME_CONSUMED, WAIT_OUTCOME_TIMEOUT, WAIT_OUTCOME_POSTED, WAIT_OUTCOME_ENDED})
_WAIT_KEYS = frozenset({'kind', 'run_id', 'workflow_id', 'wait_deadline'})
_CANCELLED_RUN_STATES = frozenset({'cancelled', 'skipped'})
# Application-owned step summaries. The waiting one adds the saved name as plain text.
_WAIT_SUMMARIES = {
    WAIT_OUTCOME_CONSUMED: 'The saved workflow finished; its result is ready for this plan.',
    WAIT_OUTCOME_TIMEOUT: 'Still running. Its result will be posted to this chat when it finishes.',
    WAIT_OUTCOME_POSTED: 'The saved workflow finished; its result is posted to this chat separately.',
    WAIT_OUTCOME_ENDED: 'The plan stopped waiting for the saved workflow. Its result will be posted to this chat.',
}
_WAIT_SUMMARIES_UNPOSTED = {
    WAIT_OUTCOME_TIMEOUT: 'Still running. Open its run in Workflows to see the result when it finishes.',
    WAIT_OUTCOME_ENDED: 'The plan stopped waiting for the saved workflow. Open its run in Workflows to see the result.',
}


def _wait_record(outcome, *, run_id, run_status=None, run=None, pointer=None, partial=False, truncated=False,
                 posts_to_chat=False):
    """The ``wait`` a waited or waitable run step completes with. Ids and timestamps only, never content."""
    run = run if isinstance(run, dict) else {}

    def moment(value):
        parsed = parse_delivery_timestamp(value)
        return parsed.isoformat() if parsed is not None else None

    return {
        'outcome': outcome,
        'run_id': run_id,
        'run_status': run_status if isinstance(run_status, str) and run_status else None,
        'started_at': moment(run.get('started_at')),
        'completed_at': moment(run.get('completed_at')),
        'result_pointer': deepcopy(pointer) if outcome == WAIT_OUTCOME_CONSUMED and isinstance(pointer, dict) else None,
        'partial': partial is True,
        'truncated': truncated is True,
        'posts_to_chat': posts_to_chat is True,
    }


def _wait_summary(wait):
    outcome = wait.get('outcome') if isinstance(wait, dict) else None
    if outcome not in WAIT_OUTCOMES:
        return _STEP_SUMMARIES[WORKFLOW_RUN_STATUS_QUEUED]
    if outcome in _WAIT_SUMMARIES_UNPOSTED and wait.get('posts_to_chat') is not True:
        return _WAIT_SUMMARIES_UNPOSTED[outcome]
    return _WAIT_SUMMARIES[outcome]


def workflow_run_wait_text(wait):
    """Application-owned text on how a waited run's wait ended, for the step and the steps that use it."""
    return _wait_summary(wait)


def _waiting_summary(name, deadline, now):
    """The plan card's line while the step waits. Plain text: the card shows it as text, never markup."""
    text = clean_catalog_text(name, NAME_MAX_LENGTH).strip()
    label = f'"{text}"' if text else 'the saved workflow'
    minutes = max(1, math.ceil(max(0.0, (deadline - now).total_seconds()) / 60))
    return f'Waiting for {label} to finish (up to {minutes} min).'


def _wait_deadline(context, settings, step_id, now):
    # Imported here: limits and timing read settings only, and neither is needed to plan a run.
    from functions_orchestration_timing import positive_setting_int
    from functions_workflow_limits import get_chat_orchestration_workflow_run_wait_max_seconds

    return workflow_run_wait_deadline(
        now=now, execution_deadline_at=getattr(context, 'execution_deadline_at', None),
        cap_seconds=get_chat_orchestration_workflow_run_wait_max_seconds(settings),
        step_timeout_seconds=positive_setting_int(settings, 'chat_orchestration_step_timeout_seconds', 120),
        dependents=waited_run_dependents(getattr(context, 'plan_steps', None) or [], step_id),
    )


def _release_quietly(user_id, run_id, *, orchestration_run_id, step_id):
    """Hand the run's post back to the post-back worker; None when storage couldn't be reached. Never raises."""
    try:
        return release_chat_delivery(user_id, run_id, orchestration_run_id=orchestration_run_id, step_id=step_id)
    except Exception as exc:
        _log(
            'A waited workflow run could not be released; its hold lapses on its own.', logging.WARNING,
            run_id=orchestration_run_id, step_id=step_id, error_type=type(exc).__name__,
        )
        return None


def _begin_wait(step, context, *, settings, user_id, producer, workflow, outcome, cancel_requested):
    """Hold the run's chat post-back and return the waiting step result, or None when the step can't wait.

    Only a run this call started for this chat's post-back, of a workflow that is a quick run now,
    in a plan whose other steps can all run without the user, waits. When the step can't wait,
    ``outcome`` gets the ``wait`` it completes with instead: the run's result then reaches the
    chat through the post-back, and the steps that use it are told so.
    """
    step_id = step['step_id']
    now = datetime.now(timezone.utc)
    deadline = None
    if (
        not (callable(cancel_requested) and cancel_requested())
        and getattr(context, 'durable_checkpoints', False) is True
        and getattr(context, 'workflow_run_headless', False) is True
        and wait_configured(settings)
        and not workflow_results_gate(settings, getattr(context, 'user_roles', None))
        and isinstance(workflow, dict) and quick_run_eligibility(workflow, settings)[0]
        and outcome.get('chat_delivery') is True
        and outcome['status'] in (WORKFLOW_RUN_STATUS_QUEUED, WORKFLOW_RUN_STATUS_RUNNING)
        and isinstance(outcome.get('run_id'), str) and isinstance(outcome.get('workflow_id'), str)
    ):
        deadline = _wait_deadline(context, settings, step_id, now)
    decision = None
    if deadline is not None:
        decision = hold_chat_delivery(
            user_id, outcome['run_id'], orchestration_run_id=producer.run_id, step_id=step_id,
            until=workflow_run_hold_until(deadline),
        )
    if decision == PLAN_WAIT_HELD:
        wait = {
            'kind': SAVED_WORKFLOW_RUN_WAIT_KIND, 'run_id': outcome['run_id'],
            'workflow_id': outcome['workflow_id'], 'wait_deadline': deadline.isoformat(),
        }
        outcome['wait'] = {'kind': SAVED_WORKFLOW_RUN_WAIT_KIND, 'wait_deadline': wait['wait_deadline']}
        _log('A workflow run step is waiting for its run.', run_id=context.run_id, step_id=step_id)
        result = build_step_result(
            status=STEP_STATUS_WAITING, summary=_waiting_summary(outcome['name'], deadline, now),
            task_result=TaskResult(producer, ROLE_GATHER, 'pending', ()), wait=wait,
        )
        result['workflow_run'] = _sidecar(
            step, context, user_id=user_id, producer_run_id=producer.run_id, outcome=outcome,
        )
        return result
    if decision == PLAN_WAIT_POSTED:
        kind, posts = WAIT_OUTCOME_POSTED, True
    elif decision in (PLAN_WAIT_ENDED, PLAN_WAIT_CONSUMED):
        kind, posts = WAIT_OUTCOME_ENDED, False
    else:
        # The run is still running and was never waited for; only its own post-back, if any, reports it.
        kind, posts = WAIT_OUTCOME_TIMEOUT, outcome.get('chat_delivery') is True
    outcome['wait'] = _wait_record(kind, run_id=outcome.get('run_id'), run_status=outcome['status'], posts_to_chat=posts)
    return None


def _reauthorize_wait(step, context, *, settings, user_id, wait):
    """Check again that this plan may still wait for its run: ``(workflow, None)`` or ``(None, reason)``.

    The same checks as starting the run, without the signed-in session a continuation doesn't
    have, plus the wait's own: the conversation is still the user's and private, the wait and
    workflow results are still on for the user, and the workflow is still the user's own quick
    run. Raises ``_WorkflowRunStepFailure`` only when storage can't be read now.
    """
    roles = getattr(context, 'user_roles', None)
    if workflow_run_settings_gate(settings) or not wait_configured(settings):
        return None, 'wait_disabled'
    if workflow_run_gate(settings, roles) or workflow_results_gate(settings, roles):
        return None, 'access_lost'
    conversation = _read_conversation(context.conversation_id)
    if (
        not isinstance(conversation, dict) or conversation.get('user_id') != user_id
        or conversation.get('orchestration_deleted')
    ):
        return None, 'conversation_unavailable'
    planning = refresh_workflow_planning_privacy(getattr(context, 'workflow_planning', None), conversation, user_id)
    if not isinstance(planning, dict) or planning.get('conversation_private') is not True:
        return None, 'conversation_shared'
    handle = (step.get('arguments') or {}).get('workflow')
    if not workflow_run_ready(planning) or _workflow_id(planning, handle) != wait['workflow_id']:
        return None, 'workflow_unavailable'
    workflow = _read_workflow(user_id, wait['workflow_id'])
    if (
        not isinstance(workflow, dict) or workflow.get('id') != wait['workflow_id']
        or workflow.get('user_id') != user_id or workflow.get('deleting') or workflow.get('group_id')
    ):
        return None, 'workflow_unavailable'
    if not quick_run_eligibility(workflow, settings)[0]:
        return None, 'workflow_not_quick'
    return workflow, None


def _observe_wait(step, context, *, settings, user_id, wait, name, orchestration_run_id):
    """Decide once what a waiting step's run means for the plan now.

    Returns ``(verdict, fields)``. The verdict is a wait outcome, ``failed`` (with ``code``) when the
    plan used a run that failed or was cancelled, or ``pending`` when the run hasn't finished or
    can't be read now. The chat post-back's record decides every outcome that delivers the result,
    so the plan uses a result only when the post-back never will.
    """
    step_id = step['step_id']
    workflow_id, run_id = wait['workflow_id'], wait['run_id']
    ids = {'orchestration_run_id': orchestration_run_id, 'step_id': step_id}
    try:
        workflow, reason = _reauthorize_wait(step, context, settings=settings, user_id=user_id, wait=wait)
        if workflow is None:
            _log('A waiting workflow run step stopped waiting.', run_id=context.run_id, step_id=step_id, reason=reason)
            _release_quietly(user_id, run_id, **ids)
            # The post-back applies its own rules to a chat or workflow that changed, so the plan promises nothing.
            return WAIT_OUTCOME_ENDED, {'posts_to_chat': False}
        summary = read_run_control_summary(user_id, workflow_id, run_id)
        if not isinstance(summary, dict) or summary.get('exists') is not True:
            return 'pending', {}
        state = summary.get('state')
        if summary.get('deleted'):
            _release_quietly(user_id, run_id, **ids)
            return WAIT_OUTCOME_ENDED, {'posts_to_chat': False, 'run_status': state}
        if state in RESULT_RUN_STATES:
            run = _read_workflow_run(user_id, run_id)
            if not isinstance(run, dict) or run.get('user_id') != user_id or run.get('workflow_id') != workflow_id:
                return 'pending', {'run_status': state}
            # Imported here: the results module imports this one.
            from functions_orchestration_workflow_results import (
                WORKFLOW_RESULTS_OUTCOME_IN_PROGRESS,
                WORKFLOW_RESULTS_OUTCOME_READ,
                WORKFLOW_RESULTS_OUTCOME_STATUS_ONLY,
                _reader_outcome,
            )

            closed = _reader_outcome(user_id, workflow_id, run, name=name, newer_in_progress=False)
            kind = closed.get('outcome') if isinstance(closed, dict) else None
            fields = {'run_status': state, 'run': run}
            if kind in (WORKFLOW_RESULTS_OUTCOME_STATUS_ONLY, WORKFLOW_RESULTS_OUTCOME_IN_PROGRESS):
                return 'pending', fields
            if kind != WORKFLOW_RESULTS_OUTCOME_READ or not isinstance(closed.get('context'), dict):
                # A finished run whose result a plan can't read: the post-back posts it instead.
                decision = _release_quietly(user_id, run_id, **ids)
                if decision in (PLAN_WAIT_POSTED, PLAN_WAIT_RELEASED, None):
                    return WAIT_OUTCOME_POSTED, {**fields, 'posts_to_chat': True}
                return WAIT_OUTCOME_ENDED, {**fields, 'posts_to_chat': False}
            decision = consume_chat_delivery(user_id, run_id, summary, **ids)
            if decision == PLAN_WAIT_CONSUMED:
                return WAIT_OUTCOME_CONSUMED, {
                    **fields, 'pointer': closed['context'],
                    'partial': closed.get('partial') is True, 'truncated': closed.get('truncated') is True,
                }
            if decision == PLAN_WAIT_POSTED:
                return WAIT_OUTCOME_POSTED, {**fields, 'posts_to_chat': True}
            if decision == PLAN_WAIT_ENDED:
                return WAIT_OUTCOME_ENDED, {**fields, 'posts_to_chat': False}
            return 'pending', fields
        if state in FAILED_RUN_STATES or state in _CANCELLED_RUN_STATES:
            run = _read_workflow_run(user_id, run_id)
            fields = {'run_status': state, 'run': run}
            decision = consume_chat_delivery(user_id, run_id, summary, **ids)
            if decision == PLAN_WAIT_CONSUMED:
                code = 'workflow_run_cancelled' if state in _CANCELLED_RUN_STATES else 'workflow_run_failed'
                return 'failed', {**fields, 'code': code}
            if decision == PLAN_WAIT_POSTED:
                return WAIT_OUTCOME_POSTED, {**fields, 'posts_to_chat': True}
            if decision == PLAN_WAIT_ENDED:
                return WAIT_OUTCOME_ENDED, {**fields, 'posts_to_chat': False}
            return 'pending', fields
        return 'pending', {'run_status': state}
    except _WorkflowRunStepFailure:
        return 'pending', {}
    except Exception as exc:
        _log(
            'A waited workflow run could not be checked; the plan will check again.', logging.WARNING,
            run_id=context.run_id, step_id=step_id, error_type=type(exc).__name__,
        )
        return 'pending', {}


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
        workflow = outcome.pop('_workflow', None)
        if not outcome['queued']:
            # Nothing was started here, so a stop still ends the step before it records anything.
            recheck()
        elif step_id in (getattr(context, 'workflow_run_waits', None) or ()):
            # Only a step the server marked when it checked the plan may wait; the model never decides it.
            waiting = _begin_wait(
                step, context, settings=settings, user_id=user_id, producer=producer, workflow=workflow,
                outcome=outcome, cancel_requested=cancel_requested,
            )
            if waiting is not None:
                return waiting
        value = {
            'version': WORKFLOW_RUN_VERSION, 'name': outcome['name'],
            'status': outcome['status'], 'reason': outcome['reason'],
        }
        if isinstance(outcome.get('wait'), dict):
            value['wait'] = deepcopy(outcome['wait'])
        task = service.persist_task_result(
            producer=producer, role=ROLE_GATHER, status='complete',
            outputs=[NamedOutput(
                WORKFLOW_RUN_OUTPUT, WORKFLOW_RUN_OUTPUT_KIND, value,
                Completeness('complete', 1, 1, Coverage(1, 1, 'items'), 'valid', (WORKFLOW_RUN_CHECK,), ()),
            )],
            sources=[], origin='generated', guard_token=guard_token, upstream=(),
            input_fingerprint=input_fingerprint,
        )
        _log(
            'A workflow run step finished.',
            run_id=context.run_id, step_id=step_id, status=outcome['status'], reason=outcome['reason'],
        )
        summary = (
            _wait_summary(outcome['wait']) if isinstance(outcome.get('wait'), dict)
            else _STEP_SUMMARIES[outcome['status']]
        )
        result = build_step_result(status=STEP_STATUS_COMPLETED, summary=summary, task_result=task)
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
            run_id=context.run_id, step_id=step_id, failure_code=failure['code'],
        )
        return _failed(failure)
    except Exception as exc:
        raise_source_service_failure(exc)
        failure = _failure(exc)
        _log(
            'A workflow run step failed.', logging.WARNING,
            run_id=context.run_id, step_id=step_id, error_type=type(exc).__name__, failure_code=failure['code'],
        )
        return _failed(failure)


def _complete_wait(step, context, *, service, producer, user_id, start, wait, guard_token, input_fingerprint):
    """Retain a waited run step's ``run`` result, with how its wait ended, and complete the step."""
    service.access.authorize_producer(producer, for_write=True)
    if context.result_guard_token_for_step(step['step_id']) != guard_token:
        raise ResultUnavailableError('result_attempt_stopped')
    task = service.persist_task_result(
        producer=producer, role=ROLE_GATHER, status='complete',
        outputs=[NamedOutput(
            WORKFLOW_RUN_OUTPUT, WORKFLOW_RUN_OUTPUT_KIND,
            {
                'version': WORKFLOW_RUN_VERSION, 'name': start['name'], 'status': start['status'],
                'reason': start['reason'], 'wait': deepcopy(wait),
            },
            Completeness('complete', 1, 1, Coverage(1, 1, 'items'), 'valid', (WORKFLOW_RUN_CHECK,), ()),
        )],
        sources=[], origin='generated', guard_token=guard_token, upstream=(),
        input_fingerprint=input_fingerprint,
    )
    _log(
        'A waiting workflow run step finished.',
        run_id=context.run_id, step_id=step['step_id'], reason=wait['outcome'],
    )
    result = build_step_result(status=STEP_STATUS_COMPLETED, summary=_wait_summary(wait), task_result=task)
    result['workflow_run'] = _sidecar(
        step, context, user_id=user_id, producer_run_id=producer.run_id,
        outcome={**start, 'chat_delivery': True, 'wait': wait},
    )
    return result


def _stopped_wait(step, context, *, user_id, producer, start, wait):
    """The cancelled result of a waiting step the user stopped. The run goes on, and its post-back with it."""
    decision = _release_quietly(
        user_id, wait['run_id'], orchestration_run_id=producer.run_id, step_id=step['step_id'],
    )
    record = (
        _wait_record(WAIT_OUTCOME_POSTED, run_id=wait['run_id'], posts_to_chat=True)
        if decision == PLAN_WAIT_POSTED else
        _wait_record(
            WAIT_OUTCOME_ENDED, run_id=wait['run_id'],
            posts_to_chat=decision not in (PLAN_WAIT_ENDED, PLAN_WAIT_CONSUMED),
        )
    )
    result = build_step_result(status=STEP_STATUS_CANCELLED, failure=build_failure('user_cancelled'))
    result['workflow_run'] = _sidecar(
        step, context, user_id=user_id, producer_run_id=producer.run_id,
        outcome={**start, 'chat_delivery': True, 'wait': record},
    )
    return result


def resume_workflow_run_wait(step, context, *, settings, user_id, input_fingerprint, cancel_requested=None,
                             saved_result=None):
    """Check once, from a continuation, on a workflow_run step waiting for the run it started.

    The step completes when the run finished and this plan took its result from the chat
    post-back, when the post-back already has it, when the wait can no longer go on, and when the
    wait's bound passed: the post-back then posts the result when the run finishes. A run that
    failed or was cancelled fails the step, and the plan's dependency rules decide the rest.
    Otherwise the step keeps waiting. Every check authorizes the wait again, as the start did, and
    the result's content is never read here: later steps read it through the workflow results
    reader, which authorizes every read.
    """
    # Imported here: checkpoints import the executor, which imports this module.
    from functions_orchestration_checkpoints import step_input_fingerprint

    step_id = step.get('step_id') if isinstance(step, dict) else None
    pending = getattr(context, 'pending_results', None)
    wait = pending.get(step_id) if isinstance(pending, dict) and isinstance(step_id, str) else None
    if (
        context.plan_contract_version != 2 or user_id != context.user_id
        or step.get('capability_id') != CAPABILITY_WORKFLOW_RUN or step.get('role') != ROLE_GATHER
        or step.get('enabled') is not True
        or type(wait) is not dict or set(wait) != _WAIT_KEYS
        or any(type(wait[key]) is not str or not wait[key] for key in _WAIT_KEYS)
        or wait['kind'] != SAVED_WORKFLOW_RUN_WAIT_KIND
    ):
        raise ResultContractError('result_wait_invalid')
    if input_fingerprint != step_input_fingerprint(step, context, None, settings=settings):
        raise ResultContractError('result_input_changed')
    deadline = parse_delivery_timestamp(wait['wait_deadline'])
    if (
        deadline is None or type(saved_result) is not dict
        or saved_result.get('status') != STEP_STATUS_WAITING or saved_result.get('wait') != wait
        or wait['run_id'] != _workflow_run_id(
            user_id, wait['workflow_id'], workflow_run_request_id(_attempt_root(context), step_id),
        )
    ):
        raise ResultContractError('result_wait_invalid')
    service = require_result_service(context)
    producer = context.result_producer(step)
    if producer.user_id != user_id:
        raise ResultUnavailableError('result_owner_mismatch')
    task = context.task_results.get(step_id)
    validate_task_outputs(step, context, task)
    if task.status != 'pending' or task.outputs:
        raise ResultContractError('result_wait_invalid')
    guard_token = context.result_guard_token_for_step(step_id)
    saved = saved_result.get('workflow_run') if isinstance(saved_result.get('workflow_run'), dict) else {}
    start_status = saved.get('status')
    start = {
        'name': clean_catalog_text(saved.get('name'), NAME_MAX_LENGTH) or _DEFAULT_WORKFLOW_NAME,
        'status': start_status if start_status in (WORKFLOW_RUN_STATUS_QUEUED, WORKFLOW_RUN_STATUS_RUNNING)
        else WORKFLOW_RUN_STATUS_QUEUED,
        'reason': None, 'workflow_id': wait['workflow_id'], 'run_id': wait['run_id'],
    }
    try:
        if callable(cancel_requested) and cancel_requested():
            return _stopped_wait(step, context, user_id=user_id, producer=producer, start=start, wait=wait)
        verdict, fields = _observe_wait(
            step, context, settings=settings, user_id=user_id, wait=wait, name=start['name'],
            orchestration_run_id=producer.run_id,
        )
        if verdict == 'pending' and datetime.now(timezone.utc) >= deadline:
            decision = _release_quietly(user_id, wait['run_id'], orchestration_run_id=producer.run_id, step_id=step_id)
            if decision == PLAN_WAIT_CONSUMED:
                # Taken by an earlier check that stopped before it was recorded: its result stays in Workflows.
                verdict, fields = WAIT_OUTCOME_ENDED, {**fields, 'posts_to_chat': False}
            else:
                # The run hasn't finished, so the post-back posts its result when it does.
                verdict, fields = WAIT_OUTCOME_TIMEOUT, {**fields, 'posts_to_chat': decision != PLAN_WAIT_ENDED}
        if verdict == 'failed':
            failure = build_failure(fields['code'])
            _log(
                'A waited workflow run did not finish successfully.', logging.WARNING,
                run_id=context.run_id, step_id=step_id, failure_code=failure['code'],
            )
            result = _failed(failure)
            result['workflow_run'] = _sidecar(
                step, context, user_id=user_id, producer_run_id=producer.run_id,
                outcome={
                    **start, 'chat_delivery': True,
                    'wait': _wait_record(
                        WAIT_OUTCOME_CONSUMED, run_id=wait['run_id'], run_status=fields.get('run_status'),
                        run=fields.get('run'),
                    ),
                },
            )
            return result
        if verdict in WAIT_OUTCOMES:
            record = _wait_record(
                verdict, run_id=wait['run_id'], run_status=fields.get('run_status'), run=fields.get('run'),
                pointer=fields.get('pointer'), partial=fields.get('partial'), truncated=fields.get('truncated'),
                posts_to_chat=fields.get('posts_to_chat'),
            )
            return _complete_wait(
                step, context, service=service, producer=producer, user_id=user_id, start=start, wait=record,
                guard_token=guard_token, input_fingerprint=input_fingerprint,
            )
        result = build_step_result(
            status=STEP_STATUS_WAITING,
            summary=_waiting_summary(start['name'], deadline, datetime.now(timezone.utc)),
            task_result=task, wait=deepcopy(wait),
        )
        result['workflow_run'] = _sidecar(
            step, context, user_id=user_id, producer_run_id=producer.run_id,
            outcome={
                **start, 'chat_delivery': True,
                'wait': {'kind': SAVED_WORKFLOW_RUN_WAIT_KIND, 'wait_deadline': wait['wait_deadline']},
            },
        )
        return result
    except MixedSourceCancellationError:
        return _stopped_wait(step, context, user_id=user_id, producer=producer, start=start, wait=wait)
    except _WorkflowRunStepFailure as exc:
        failure = build_failure(exc.code)
        _log(
            'A waiting workflow run step failed.', logging.WARNING,
            run_id=context.run_id, step_id=step_id, failure_code=failure['code'],
        )
        return _failed(failure)
    except Exception as exc:
        raise_source_service_failure(exc)
        failure = _failure(exc)
        _log(
            'A waiting workflow run step failed.', logging.WARNING,
            run_id=context.run_id, step_id=step_id, error_type=type(exc).__name__, failure_code=failure['code'],
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
        # A step that waited for its run keeps how the wait ended, so the reply's note stays true.
        if isinstance(value.get('wait'), dict) and value['wait'].get('outcome') in WAIT_OUTCOMES:
            outcome['wait'] = deepcopy(value['wait'])
        return _sidecar(step, context, user_id=user_id, producer_run_id=task.producer.run_id, outcome=outcome)
    except Exception as exc:
        _log(
            'A recovered workflow run could not be described.', logging.WARNING,
            run_id=getattr(context, 'run_id', None),
            step_id=step.get('step_id') if isinstance(step, dict) else None, error_type=type(exc).__name__,
        )
        return None


def workflow_run_reason_text(reason):
    """The application-owned sentence for a closed reason, or the generic not-started one."""
    reason = reason if isinstance(reason, str) else None
    return WORKFLOW_RUN_REASON_TEXT.get(reason) or WORKFLOW_RUN_REASON_TEXT[REASON_NOT_STARTED]


# ---------------------------------------------------------------------------
# The reply
# ---------------------------------------------------------------------------

def _quoted_name(value):
    """A saved name as inline code that cannot format the reply, or None when nothing is left of it."""
    text = clean_catalog_text(value, NAME_MAX_LENGTH)
    if not text.replace('`', '').strip():
        return None
    return '`' + text.replace('`', "'") + '`'


def _step_line(sidecar):
    name = _quoted_name(sidecar.get('name')) or f'`{_DEFAULT_WORKFLOW_NAME}`'
    status = sidecar['status']
    if status == WORKFLOW_RUN_STATUS_ALREADY_STARTED:
        return f'- {name} was already started for this request, so it was not started again.'
    if status in WORKFLOW_RUN_STARTED_STATUSES:
        return f'- Started {name}.'
    return f"- {name} was not started. {workflow_run_reason_text(sidecar.get('reason'))}"


def _left_out_line(note):
    reason = note.get('reason') if isinstance(note.get('reason'), str) else None
    text = WORKFLOW_RUN_SKIP_REASONS.get(reason) or WORKFLOW_RUN_SKIP_REASONS[REASON_INVALID]
    name = _quoted_name(note.get('name'))
    return f'- {name or _UNNAMED_WORKFLOW_NOTE} was not started. {text}'


def _wait_line(sidecar, *, composed):
    """A waited run step's line, with how many runs it counts as started and as posted back later."""
    name = _quoted_name(sidecar.get('name')) or f'`{_DEFAULT_WORKFLOW_NAME}`'
    wait = sidecar['wait']
    outcome = wait.get('outcome')
    posts = 1 if wait.get('posts_to_chat') is True else 0
    if outcome == WAIT_OUTCOME_CONSUMED:
        if wait.get('run_status') in _CANCELLED_RUN_STATES:
            return f'- {name} was cancelled before it finished, so it has no results to use.', 0, 0
        if wait.get('run_status') in FAILED_RUN_STATES:
            return f"- {name} failed, so its results couldn't be used. Its run in Workflows says why.", 0, 0
        if composed:
            return f'- Ran {name}. Its results were used in this answer.', 0, 0
        return f"- Ran {name}. This answer couldn't use its results; they're in its run in Workflows.", 0, 0
    if outcome == WAIT_OUTCOME_POSTED:
        return f'- Ran {name}. Its results are posted to this chat separately.', 0, 0
    if outcome == WAIT_OUTCOME_TIMEOUT:
        return f'- Started {name}. It was still running when this answer was written.', 1, posts
    if outcome == WAIT_OUTCOME_ENDED:
        return f'- Started {name}. The plan stopped waiting for it.', 1, posts
    # Still waiting when the reply was written: its hold lapses and the post-back posts the result.
    return _step_line(sidecar), 1, 1 if sidecar.get('chat_delivery') is True else 0


def workflow_run_note(plan, execution_steps, *, stopped=False, composed=False):
    """What the reply says about the saved workflows a plan started, or ''. Never raises.

    Application-owned text: each completed workflow_run step the plan enables gets a line, in plan
    order, saying it started, was already started for this request or was not started and why.
    The run steps the planner left out follow, from the plan's ``workflow_run_notes``. A step that
    failed or never ran is left to the failure explanation. When a run started, the note says
    where to follow it, and ``stopped`` adds that stopping the plan does not stop the run. Saved
    names are inline code, so a name cannot add links, formatting or lines, and no id or handle
    is shown. A step the server let wait for its run says how the wait ended instead, including
    when it failed or was stopped; ``composed`` says the answer was written from the plan's steps.
    """
    plan = plan if isinstance(plan, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    records = {
        record['step_id']: record for record in (execution_steps if isinstance(execution_steps, list) else ())
        if isinstance(record, dict) and isinstance(record.get('step_id'), str)
    }
    lines, started, delivered = [], 0, 0
    for step in steps:
        if not isinstance(step, dict) or step.get('capability_id') != CAPABILITY_WORKFLOW_RUN:
            continue
        if not step.get('enabled', True):
            continue
        record = records.get(step.get('step_id')) if isinstance(step.get('step_id'), str) else None
        if not isinstance(record, dict) or record.get('capability_id') != CAPABILITY_WORKFLOW_RUN:
            continue
        sidecar = record.get('workflow_run')
        waited = isinstance(sidecar, dict) and isinstance(sidecar.get('wait'), dict)
        if record.get('status') != STEP_STATUS_COMPLETED and not (
            waited and record.get('status') in (STEP_STATUS_WAITING, STEP_STATUS_FAILED, STEP_STATUS_CANCELLED)
        ):
            continue
        if not isinstance(sidecar, dict) or sidecar.get('status') not in WORKFLOW_RUN_STATUSES:
            continue
        if waited:
            line, run_started, run_delivered = _wait_line(sidecar, composed=composed)
            started += run_started
            delivered += run_delivered
            lines.append(line)
            continue
        if sidecar['status'] in WORKFLOW_RUN_STARTED_STATUSES:
            started += 1
            if sidecar.get('chat_delivery') is True:
                delivered += 1
        lines.append(_step_line(sidecar))
    notes = plan.get('workflow_run_notes') if isinstance(plan.get('workflow_run_notes'), list) else []
    for note in notes:
        # A duplicate step names a workflow the plan starts once anyway, so it is not news.
        if not isinstance(note, dict) or note.get('reason') == RULE_DUPLICATE:
            continue
        line = _left_out_line(note)
        if line not in lines:
            lines.append(line)
    if not lines:
        return ''
    parts = ['\n'.join([WORKFLOW_RUN_NOTE_HEADING, *lines])]
    if started:
        # The chat promises the result only when every run started here will be posted back to it.
        if delivered == started:
            parts.append(WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY if started > 1 else WORKFLOW_RUN_DELIVERY_FOLLOW_UP)
        else:
            parts.append(WORKFLOW_RUN_FOLLOW_UP_MANY if started > 1 else WORKFLOW_RUN_FOLLOW_UP)
        if stopped:
            parts.append(WORKFLOW_RUN_STOPPED)
    return '\n\n'.join(parts)


__all__ = [
    'FAILURE_RUNTIME_UNAVAILABLE',
    'NO_WORKFLOW_STARTED',
    'REASON_INVALID',
    'WAIT_OUTCOMES',
    'WAIT_OUTCOME_CONSUMED',
    'WAIT_OUTCOME_ENDED',
    'WAIT_OUTCOME_POSTED',
    'WAIT_OUTCOME_TIMEOUT',
    'WORKFLOW_RUN_DELIVERY_FOLLOW_UP',
    'WORKFLOW_RUN_DELIVERY_FOLLOW_UP_MANY',
    'WORKFLOW_RUN_FOLLOW_UP',
    'WORKFLOW_RUN_FOLLOW_UP_MANY',
    'WORKFLOW_RUN_NOTE_HEADING',
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
    'WORKFLOW_RUN_STOPPED',
    'WORKFLOW_RUN_TRIGGER_SOURCE',
    'WORKFLOW_RUN_VERSION',
    'adapter_workflow_run',
    'chat_delivery_seed_for',
    'consume_chat_delivery',
    'drop_workflow_runs',
    'hold_chat_delivery',
    'prepare_workflow_run_arguments',
    'read_run_control_summary',
    'rebuild_workflow_run',
    'release_chat_delivery',
    'resume_workflow_run_wait',
    'started_workflow_run_id',
    'workflow_run_failure_message',
    'workflow_run_link',
    'workflow_run_note',
    'workflow_run_reason_text',
    'workflow_run_repair_text',
    'workflow_run_request_id',
    'workflow_run_wait_text',
]
