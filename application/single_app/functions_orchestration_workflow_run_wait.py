# functions_orchestration_workflow_run_wait.py
"""Waiting inside a chat plan for a quick saved workflow run.

With Wait For Quick Workflows In Chat on, a plan that starts one of the user's saved workflows
with ``workflow_run`` may wait for that run to finish and hand its result to a later ``compose``
step. Only a *quick* workflow qualifies. Whether a workflow is quick is decided here, on the
server, from the saved workflow definition and the deployment's settings, never from anything a
model wrote.

``SAVED_WORKFLOW_RUN_WAIT_KIND`` is the plan step wait kind for such a wait. Other features, such
as plan replay, import it to refuse a step that waits on a saved workflow run.
"""

import logging

from functions_m365_workflow_binding import M365_ACTIVE_STATES


SAVED_WORKFLOW_RUN_WAIT_KIND = 'saved_workflow_run'
WORKFLOW_RUN_WAIT_SETTING = 'enable_chat_orchestration_workflow_run_wait'

# A plan holds a chat turn's continuation open while it waits, so only a short, single-pass
# workflow is worth waiting for. Five tasks covers the "gather, analyze, summarize" digests users
# start from chat while keeping a run's expected length inside the wait cap.
QUICK_RUN_MAX_TASKS = 5
# How deep the loop check walks a workflow's flow before refusing it as too deep to verify.
QUICK_RUN_FLOW_MAX_DEPTH = 32
QUICK_RUN_LOOP_KINDS = frozenset({'for_each', 'repeat_until'})
# Publication policies that finish a task only after a person approves it or indexing completes.
QUICK_RUN_REVIEW_POLICIES = frozenset({'approved', 'indexed_ready'})
# A waiting plan resumes in the background without the user's sign-in, so a plan that also uses
# any of these, which need the signed-in session or evaluate the caller's roles when they run,
# never waits.
SESSION_NEEDING_CAPABILITIES = frozenset({
    'web_search', 'url_fetch', 'deep_research', 'agent_invoke', 'action_invoke',
    'workflow_handoff', 'workflow_propose',
})
WAIT_MARKER_VERSION = 1

QUICK_RUN_REASON_WAIT_DISABLED = 'wait_disabled'
QUICK_RUN_REASON_INVALID = 'invalid_workflow'
QUICK_RUN_REASON_NOT_PERSONAL = 'not_personal'
QUICK_RUN_REASON_NOT_DURABLE = 'not_durable'
QUICK_RUN_REASON_DELETING = 'deleting'
QUICK_RUN_REASON_M365_ACTIVE = 'm365_active'
QUICK_RUN_REASON_ONE_TIME = 'one_time'
QUICK_RUN_REASON_LOOP = 'loop'
QUICK_RUN_REASON_STRUCTURED = 'structured_workflow'
QUICK_RUN_REASON_APPROVAL = 'approval_required'
QUICK_RUN_REASON_RUN_AS = 'm365_run_as'
QUICK_RUN_REASON_REVIEW = 'publication_review'
QUICK_RUN_REASON_FILE_SYNC = 'file_sync'
QUICK_RUN_REASON_NO_TASKS = 'no_tasks'
QUICK_RUN_REASON_TOO_MANY_TASKS = 'too_many_tasks'

# App-owned text for each reason. None of it names a workflow, so it is safe in any answer.
QUICK_RUN_REASON_TEXT = {
    QUICK_RUN_REASON_WAIT_DISABLED: 'Waiting for a workflow in chat is turned off.',
    QUICK_RUN_REASON_INVALID: "The workflow couldn't be checked, so the plan won't wait for it.",
    QUICK_RUN_REASON_NOT_PERSONAL: 'Only your own personal workflows can be waited for in chat.',
    QUICK_RUN_REASON_NOT_DURABLE: 'Only a workflow with durable execution on can be waited for in chat.',
    QUICK_RUN_REASON_DELETING: 'The workflow is being deleted.',
    QUICK_RUN_REASON_M365_ACTIVE: 'The workflow is waiting on Microsoft 365, so the plan won\'t wait for it.',
    QUICK_RUN_REASON_ONE_TIME: "A one-time hand-off workflow can't be waited for in chat.",
    QUICK_RUN_REASON_LOOP: "A workflow with For each or Repeat until steps can't be waited for in chat.",
    QUICK_RUN_REASON_STRUCTURED: "A structured workflow can't be waited for in chat.",
    QUICK_RUN_REASON_APPROVAL: "A workflow with a task that needs approval can't be waited for in chat.",
    QUICK_RUN_REASON_RUN_AS: "A workflow that runs as a Microsoft 365 user can't be waited for in chat.",
    QUICK_RUN_REASON_REVIEW: "A workflow that waits for a review or for indexing can't be waited for in chat.",
    QUICK_RUN_REASON_FILE_SYNC: "A workflow that uses File Sync can't be waited for in chat.",
    QUICK_RUN_REASON_NO_TASKS: "A workflow with no tasks can't be waited for in chat.",
    QUICK_RUN_REASON_TOO_MANY_TASKS: (
        f'Only a workflow with at most {QUICK_RUN_MAX_TASKS} tasks can be waited for in chat.'
    ),
}


def wait_configured(settings):
    """Whether an administrator turned on waiting for quick workflows, with everything it needs.

    The wait starts a saved workflow, reads its result and, when the wait runs out, relies on the
    run's result being posted back to the chat. So Run Workflows From Chat and Use Workflow Results
    In Chat must be on too. Only a real boolean ``True`` turns the wait on.
    """
    settings = settings if isinstance(settings, dict) else {}
    if settings.get(WORKFLOW_RUN_WAIT_SETTING) is not True or not settings.get('allow_user_workflows'):
        return False
    # Imported here: the workflow planning context imports the registry, which is not needed to
    # read a definition.
    from functions_orchestration_workflow_context import workflow_results_configured, workflow_runs_configured
    return workflow_runs_configured(settings) and workflow_results_configured(settings)


def quick_run_reason_text(reason):
    """The app-owned explanation for a quick-run refusal code."""
    return QUICK_RUN_REASON_TEXT.get(reason, QUICK_RUN_REASON_TEXT[QUICK_RUN_REASON_INVALID])


def _flow_has_loop(node, depth=0):
    """Whether a flow holds a For each or Repeat until node, or nests too deep to tell."""
    if depth > QUICK_RUN_FLOW_MAX_DEPTH:
        return True
    if isinstance(node, dict):
        kind = node.get('kind')
        if isinstance(kind, str) and kind in QUICK_RUN_LOOP_KINDS:
            return True
        return any(_flow_has_loop(value, depth + 1) for value in node.values())
    if isinstance(node, (list, tuple)):
        return any(_flow_has_loop(value, depth + 1) for value in node)
    return False


def _run_as_set(value):
    if value is None:
        return False
    return not isinstance(value, str) or bool(value.strip())


def _waits_for_review(task):
    publication = task.get('publication')
    if publication is None:
        return False
    if not isinstance(publication, dict):
        return True
    policy = publication.get('completion_policy')
    if policy is None:
        return False
    return not isinstance(policy, str) or policy.strip().lower() in QUICK_RUN_REVIEW_POLICIES


def _uses_file_sync(workflow):
    if str(workflow.get('trigger_type') or '').strip().lower() == 'file_sync':
        return True
    config = workflow.get('file_sync')
    if config is None:
        return False
    return not isinstance(config, dict) or bool(config.get('enabled'))


def quick_run_eligibility(workflow, settings):
    """Return ``(True, None)`` when a plan may wait for a run of ``workflow``, else ``(False, reason)``.

    ``workflow`` is the stored workflow document; ``settings`` the deployment's settings. Pure and
    deterministic: it reads nothing and changes nothing. Every rule must hold, and anything this
    cannot read refuses:

    1. The wait is configured, and the workflow is the user's own personal workflow (no group),
       with durable execution on, not being deleted and not paused on Microsoft 365. Only a
       durable run records its progress where a later continuation can read it; a group workflow
       is not the user's alone to wait for.
    2. It is not a one-time hand-off workflow. A hand-off is large work handed out of the chat on
       purpose, and its result is always posted back.
    3. Its flow has no For each or Repeat until node, whose length depends on the data.
    4. It is not a structured workflow. Its result can't be read back into a chat answer.
    5. No task needs approval, which waits for a person.
    6. It does not run as a Microsoft 365 user, which can pause for that user's sign-in.
    7. No task finishes only after a review or indexing completes.
    8. It neither starts on File Sync nor runs a File Sync first, which waits for files to sync.
    9. It has between one and ``QUICK_RUN_MAX_TASKS`` tasks.
    """
    if not wait_configured(settings):
        return False, QUICK_RUN_REASON_WAIT_DISABLED
    if not isinstance(workflow, dict):
        return False, QUICK_RUN_REASON_INVALID
    if workflow.get('group_id'):
        return False, QUICK_RUN_REASON_NOT_PERSONAL
    if workflow.get('durable_execution') is not True:
        return False, QUICK_RUN_REASON_NOT_DURABLE
    if workflow.get('deleting'):
        return False, QUICK_RUN_REASON_DELETING
    status = workflow.get('status')
    if isinstance(status, str) and status in M365_ACTIVE_STATES:
        return False, QUICK_RUN_REASON_M365_ACTIVE
    origin = workflow.get('origin')
    if workflow.get('one_time') is True or (isinstance(origin, dict) and origin.get('one_time') is True):
        return False, QUICK_RUN_REASON_ONE_TIME
    flow = workflow.get('flow')
    if _flow_has_loop(flow):
        return False, QUICK_RUN_REASON_LOOP
    if workflow.get('definition_version') == 3 or flow not in (None, {}, []):
        return False, QUICK_RUN_REASON_STRUCTURED
    tasks = workflow.get('tasks')
    if not isinstance(tasks, list) or not all(isinstance(task, dict) for task in tasks):
        return False, QUICK_RUN_REASON_INVALID
    if any(isinstance(task.get('approval'), dict) and task['approval'].get('required') for task in tasks):
        return False, QUICK_RUN_REASON_APPROVAL
    if _run_as_set(workflow.get('m365_run_as_user_id')):
        return False, QUICK_RUN_REASON_RUN_AS
    if any(_waits_for_review(task) for task in tasks):
        return False, QUICK_RUN_REASON_REVIEW
    if _uses_file_sync(workflow):
        return False, QUICK_RUN_REASON_FILE_SYNC
    if not tasks:
        return False, QUICK_RUN_REASON_NO_TASKS
    if len(tasks) > QUICK_RUN_MAX_TASKS:
        return False, QUICK_RUN_REASON_TOO_MANY_TASKS
    return True, None


def headless_request_context(request_context):
    """The caller's own request context as a resumed continuation sees it.

    A waiting plan resumes in the background, without the user's sign-in: no roles, no email and
    no native bridge. Everything else is the caller's own context, unchanged.
    """
    context = dict(request_context) if isinstance(request_context, dict) else {}
    context.update({'user_roles': [], 'user_email': None, 'native_bridge_for_step': None})
    return context


def headless_capability_ids(settings, request_context, candidate_ids, *, export_catalog=None):
    """The candidate capabilities a resumed continuation can still use. Any failure returns none."""
    settings = settings if isinstance(settings, dict) else {}
    candidates = {value for value in candidate_ids or () if isinstance(value, str)}
    if not candidates:
        return frozenset()
    try:
        from functions_orchestration_registry import resolve_available_capability_ids

        available = resolve_available_capability_ids(
            settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
            request_context=headless_request_context(request_context), candidate_ids=candidates,
            export_catalog=export_catalog,
        )
    except Exception as exc:  # noqa: BLE001 - a plan that can't be checked simply doesn't wait
        from functions_appinsights import log_event

        log_event(
            '[ChatOrchestrationWorkflowRunWait] Headless capability check failed; the plan will not wait.',
            extra={'error_type': type(exc).__name__}, level=logging.WARNING,
        )
        return frozenset()
    return frozenset(value for value in available if value in candidates)


def with_headless_capability_ids(workflow_planning, settings, request_context, available_ids, *,
                                 export_catalog=None):
    """Add what a resumed continuation can still use to a planning context with the wait marker.

    The planner and the plan editor call this with the caller's own request context and the
    capabilities this request offers. A context without the marker comes back unchanged, so with
    waiting off nothing is computed. A plan revision reuses the turn's stored context, so the
    marker is dropped when waiting is no longer configured.
    """
    marker = workflow_planning.get('workflow_run_wait') if isinstance(workflow_planning, dict) else None
    if not isinstance(marker, dict) or marker.get('ready') is not True:
        return workflow_planning
    if not wait_configured(settings) or (isinstance(settings, dict) and settings.get('require_member_of_workflow_user')):
        return {key: value for key, value in workflow_planning.items() if key != 'workflow_run_wait'}
    available = [value for value in available_ids or () if isinstance(value, str)]
    ids = headless_capability_ids(settings, request_context, available, export_catalog=export_catalog)
    return {**workflow_planning, 'workflow_run_wait': {**marker, 'headless_capability_ids': sorted(ids)}}


def workflow_run_wait_ready(workflow_planning):
    """Whether this planning context carries the server's wait marker.

    The marker is added only when an administrator configured the wait and the conversation and
    user allow it, so without it a plan is checked exactly as it was before waits existed.
    """
    marker = workflow_planning.get('workflow_run_wait') if isinstance(workflow_planning, dict) else None
    return isinstance(marker, dict) and marker.get('ready') is True


def workflow_run_wait_possible(workflow_planning):
    """Whether any plan made with this planning context could wait for a workflow run."""
    marker = workflow_planning.get('workflow_run_wait') if isinstance(workflow_planning, dict) else None
    headless = marker.get('headless_capability_ids') if isinstance(marker, dict) else None
    return (
        workflow_run_wait_ready(workflow_planning)
        and isinstance(headless, (list, tuple)) and {'workflow_run', 'compose'} <= set(headless)
    )


def waitable_projection(projection, workflow_planning):
    """The planner's projection, with every ``waitable`` flag removed when no plan could wait.

    The flags are what the planner's wait instructions key on, so the instructions appear only
    when the server would accept a wait. A projection without flags comes back unchanged.
    """
    catalog = projection.get('catalog') if isinstance(projection, dict) else None
    entries = catalog.get('workflows') if isinstance(catalog, dict) else None
    if not isinstance(entries, list) or not any(
        isinstance(entry, dict) and 'waitable' in entry for entry in entries
    ):
        return projection
    if workflow_run_wait_possible(workflow_planning):
        return projection
    stripped = [
        {key: value for key, value in entry.items() if key != 'waitable'} if isinstance(entry, dict) else entry
        for entry in entries
    ]
    return {**projection, 'catalog': {**catalog, 'workflows': stripped}}


def projection_offers_wait(projection):
    """Whether the planner's projection marks any workflow as one a plan may wait for."""
    catalog = projection.get('catalog') if isinstance(projection, dict) else None
    entries = catalog.get('workflows') if isinstance(catalog, dict) else None
    return isinstance(entries, list) and any(
        isinstance(entry, dict) and entry.get('waitable') is True for entry in entries
    )


def _enabled(step):
    return step.get('enabled', True) is not False


def _named_and_bound(step):
    """The step ids a step names, and ``(step_id, output_name, optional)`` for each input binding."""
    names, bindings = set(), []
    depends_on = step.get('depends_on')
    for value in depends_on if isinstance(depends_on, list) else ():
        if isinstance(value, str):
            names.add(value)
    inputs = step.get('inputs')
    for value in inputs.values() if isinstance(inputs, dict) else ():
        binding = value.get('binding') if isinstance(value, dict) else None
        if isinstance(binding, dict) and isinstance(binding.get('step_id'), str):
            names.add(binding['step_id'])
            bindings.append((binding['step_id'], binding.get('output_name'), value.get('optional') is True))
    return names, bindings


def waited_run_consumers_valid(steps, final_response, run_step_id):
    """Whether a waited run's result reaches only the answer, and the answer really needs it.

    The same masking rule as ``workflow_results``: a step that names the run step, or names a step
    that does, is tainted, and only ``compose`` may name a tainted step, so no export, analysis,
    agent or action can copy the run's result out of the answer. At least one enabled ``compose``
    must bind the run's ``run`` output through a required input, which keeps the run step required
    work, and the final response must not select the run step itself.
    """
    steps = [step for step in steps or () if isinstance(step, dict)]
    if not isinstance(run_step_id, str) or not run_step_id:
        return False
    if isinstance(final_response, dict) and final_response.get('step_id') == run_step_id:
        return False
    named = {}
    required_reader = False
    for step in steps:
        names, bindings = _named_and_bound(step)
        named[id(step)] = names
        if step.get('capability_id') == 'compose' and _enabled(step) and any(
            producer == run_step_id and output == 'run' and not optional
            for producer, output, optional in bindings
        ):
            required_reader = True
    tainted = {run_step_id}
    changed = True
    while changed:
        changed = False
        for step in steps:
            step_id = step.get('step_id')
            if step_id not in tainted and named[id(step)] & tainted:
                if step.get('capability_id') != 'compose' or not isinstance(step_id, str):
                    return False
                tainted.add(step_id)
                changed = True
    return required_reader


def _single_run_step(steps):
    """The plan's one enabled workflow_run step and its enabled capabilities, or None.

    A plan waits only when nothing in it needs the user's session, which is checked before
    anything else so the signed-in user's catalogs can't change the outcome, and only when it
    starts exactly one workflow.
    """
    enabled = [step for step in steps if _enabled(step)]
    capability_ids = {step.get('capability_id') for step in enabled}
    if capability_ids & SESSION_NEEDING_CAPABILITIES:
        return None
    runs = [step for step in enabled if step.get('capability_id') == 'workflow_run']
    if len(runs) != 1:
        return None
    run = runs[0]
    arguments = run.get('arguments') if isinstance(run.get('arguments'), dict) else {}
    handle = arguments.get('workflow')
    if not isinstance(run.get('step_id'), str) or run.get('optional') is True or not isinstance(handle, str):
        return None
    return run, handle, capability_ids


def compute_workflow_run_waits(steps, final_response, workflow_planning):
    """Decide, on the server, which workflow_run step of a plan waits for its run.

    Returns ``{step_id: {'version': 1, 'workflow': handle}}`` for the one step that waits, or
    ``{}``. ``workflow_planning`` is the request's server-only planning context: the wait marker
    is present only when an administrator configured the wait, its catalog entries carry
    ``waitable`` only for workflows ``quick_run_eligibility`` accepted, and
    ``headless_capability_ids`` lists what a resumed continuation can still use. Nothing a model
    wrote is read: a step waits only when every rule holds, and anything unreadable refuses.
    """
    wait = workflow_planning.get('workflow_run_wait') if isinstance(workflow_planning, dict) else None
    if not isinstance(wait, dict) or wait.get('ready') is not True:
        return {}
    headless = wait.get('headless_capability_ids')
    if not isinstance(headless, (list, tuple, set, frozenset)):
        return {}
    steps = [step for step in steps or () if isinstance(step, dict)]
    found = _single_run_step(steps)
    if found is None:
        return {}
    run, handle, capability_ids = found
    if not capability_ids <= {value for value in headless if isinstance(value, str)}:
        return {}
    from functions_orchestration_schema import workflow_run_catalog_entry

    entry = workflow_run_catalog_entry(workflow_planning, handle)
    if not isinstance(entry, dict) or entry.get('waitable') is not True:
        return {}
    if not waited_run_consumers_valid(steps, final_response, run['step_id']):
        return {}
    return {run['step_id']: {'version': WAIT_MARKER_VERSION, 'workflow': handle}}


def stored_workflow_run_waits(marker, steps, final_response):
    """Keep a stored plan's wait marker only where it still fits the plan exactly.

    Used when a saved plan is validated again without a planning context, for example before it
    runs. The marker was computed by the server when the plan was made, and the run step checks
    the workflow and the settings again when it starts.
    """
    if not isinstance(marker, dict) or len(marker) != 1:
        return {}
    steps = [step for step in steps or () if isinstance(step, dict)]
    found = _single_run_step(steps)
    if found is None:
        return {}
    run, handle, _capability_ids = found
    entry = marker.get(run['step_id'])
    if (
        not isinstance(entry, dict) or set(entry) != {'version', 'workflow'}
        or entry.get('version') != WAIT_MARKER_VERSION or entry.get('workflow') != handle
    ):
        return {}
    if not waited_run_consumers_valid(steps, final_response, run['step_id']):
        return {}
    return {run['step_id']: {'version': WAIT_MARKER_VERSION, 'workflow': handle}}


__all__ = [
    'QUICK_RUN_FLOW_MAX_DEPTH',
    'QUICK_RUN_LOOP_KINDS',
    'QUICK_RUN_MAX_TASKS',
    'QUICK_RUN_REASON_APPROVAL',
    'QUICK_RUN_REASON_DELETING',
    'QUICK_RUN_REASON_FILE_SYNC',
    'QUICK_RUN_REASON_INVALID',
    'QUICK_RUN_REASON_LOOP',
    'QUICK_RUN_REASON_M365_ACTIVE',
    'QUICK_RUN_REASON_NOT_DURABLE',
    'QUICK_RUN_REASON_NOT_PERSONAL',
    'QUICK_RUN_REASON_NO_TASKS',
    'QUICK_RUN_REASON_ONE_TIME',
    'QUICK_RUN_REASON_REVIEW',
    'QUICK_RUN_REASON_RUN_AS',
    'QUICK_RUN_REASON_STRUCTURED',
    'QUICK_RUN_REASON_TEXT',
    'QUICK_RUN_REASON_TOO_MANY_TASKS',
    'QUICK_RUN_REASON_WAIT_DISABLED',
    'QUICK_RUN_REVIEW_POLICIES',
    'SAVED_WORKFLOW_RUN_WAIT_KIND',
    'SESSION_NEEDING_CAPABILITIES',
    'WAIT_MARKER_VERSION',
    'WORKFLOW_RUN_WAIT_SETTING',
    'compute_workflow_run_waits',
    'headless_capability_ids',
    'headless_request_context',
    'projection_offers_wait',
    'quick_run_eligibility',
    'quick_run_reason_text',
    'stored_workflow_run_waits',
    'wait_configured',
    'waitable_projection',
    'waited_run_consumers_valid',
    'with_headless_capability_ids',
    'workflow_run_wait_possible',
    'workflow_run_wait_ready',
]
