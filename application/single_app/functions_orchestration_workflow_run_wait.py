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
    'WORKFLOW_RUN_WAIT_SETTING',
    'quick_run_eligibility',
    'quick_run_reason_text',
    'wait_configured',
]
