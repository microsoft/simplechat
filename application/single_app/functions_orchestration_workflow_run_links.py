# functions_orchestration_workflow_run_links.py
"""The run links under an answer whose plan started saved workflows, for the requester only.

Version: 0.261.212
Implemented in: 0.261.212

A plan's ``workflow_run`` step starts one of the requester's saved personal workflows and keeps
the workflow and run ids in a server-only sidecar on its step record
(``functions_orchestration_workflow_runs``). ``workflow_run_links`` lists, for the person who asked,
each run the plan started: the workflow's name, the run's status when read, and the ids the link
opens in Workflows. The route authorizes the run and its conversation first; nothing here reads
Flask state, and nothing is written.

* Only runs that started are listed. A step that did not start its workflow is explained by the
  answer itself.
* A requester who lost access to starting workflows from chat, a conversation that is no longer
  private and a response removed by content review each make every link unavailable, with no name
  and no ids, and no workflow or run is read.
* The workflow and its run are point-read for the current name and status. A deleted workflow or
  a run no longer in its history makes the link unavailable.
* A sidecar that does not belong to the plan, step and requester it claims, or whose run id is not
  the one the plan's first attempt and the step derive, is left out.

A retry that reused the step shows the run of the attempt that started it, the same run, because
the run id comes from the plan's first attempt.

Logs carry codes and counts only, never names or ids.
"""

import logging

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_appinsights import log_event
from functions_orchestration_registry import CAPABILITY_WORKFLOW_RUN
from functions_orchestration_runs import get_orchestration_run, get_orchestration_step_record
from functions_orchestration_workflow_context import (
    NAME_MAX_LENGTH,
    WORKFLOW_REASON_SHARED_CONVERSATION,
    clean_catalog_text,
    conversation_is_private,
    workflow_run_gate,
)
from functions_orchestration_workflow_runs import (
    WORKFLOW_RUN_STARTED_STATUSES,
    WORKFLOW_RUN_VERSION,
    started_workflow_run_id,
)


LINK_STATE_QUEUED = 'queued'
LINK_STATE_RUNNING = 'running'
LINK_STATE_WAITING = 'waiting'
LINK_STATE_UNAVAILABLE = 'unavailable'
WORKFLOW_RUN_LINK_STATES = (
    LINK_STATE_QUEUED, LINK_STATE_RUNNING, LINK_STATE_WAITING, 'completed', 'completed_partial', 'failed',
    'cancelled', 'skipped', LINK_STATE_UNAVAILABLE,
)
# The link state for each durable run state. Waiting states come from the runtime itself, and a
# state this version does not know reads as running: the run page shows the run's own state.
_LINK_STATE_FOR_RUN_STATUS = {
    'queued': LINK_STATE_QUEUED,
    'running': LINK_STATE_RUNNING,
    'cancelling': LINK_STATE_RUNNING,
    'completed': 'completed',
    'completed_partial': 'completed_partial',
    'failed': 'failed',
    'invalid': 'failed',
    'incomplete': 'failed',
    'cancelled': 'cancelled',
    'skipped': 'skipped',
}

# Why a link cannot be opened, besides the access reasons the workflow gate returns.
REASON_WORKFLOW_DELETED = 'workflow_deleted'
REASON_RUN_MISSING = 'workflow_run_missing'
REASON_CONTENT_REVIEW = 'content_review'

SERVICE_UNAVAILABLE_CODE = 'service_unavailable'
ERROR_MESSAGES = {
    'invalid_request': 'This request is not valid.',
    'run_not_found': 'Run not found.',
    SERVICE_UNAVAILABLE_CODE: 'Workflow run links are unavailable right now. Try again later.',
}

_LOG_PREFIX = '[ORCHESTRATION_WORKFLOW_RUN_LINKS]'


def _log(message, level=logging.INFO, **fields):
    # Codes and counts only: never workflow names, handles or ids.
    log_event(f'{_LOG_PREFIX} {message}', extra={'stage': 'workflow_run_links', **fields}, level=level)


def error_payload(code):
    """The body the link route returns for one of this module's fixed refusals."""
    code = code if code in ERROR_MESSAGES else 'invalid_request'
    return {'error': ERROR_MESSAGES[code], 'code': code}


# ---------------------------------------------------------------------------
# The sidecars a run's plan left
# ---------------------------------------------------------------------------

def _plan_step_ids(run):
    plan = run.get('plan') if isinstance(run.get('plan'), dict) else {}
    return [
        step['step_id'] for step in plan.get('steps') or ()
        if isinstance(step, dict) and step.get('capability_id') == CAPABILITY_WORKFLOW_RUN
        and step.get('enabled', True) is not False and isinstance(step.get('step_id'), str) and step['step_id']
    ]


def _entry(run, step_id):
    return next(
        (
            entry for entry in run.get('execution_steps') or ()
            if isinstance(entry, dict) and entry.get('step_id') == step_id
        ),
        None,
    )


def _sidecar(record):
    value = record.get('workflow_run') if isinstance(record, dict) else None
    return value if isinstance(value, dict) else None


def _attempt_root(run):
    root = run.get('attempt_root_run_id')
    return root if isinstance(root, str) and root else run.get('id')


def _producer_run_id(run, step_id, entry):
    """The earlier attempt a retry reused this step from, or None."""
    value = (entry or {}).get('reused_from_run_id')
    if isinstance(value, str) and value:
        return value
    inherited = run.get('inherited_checkpoints') if isinstance(run.get('inherited_checkpoints'), dict) else {}
    reference = inherited.get(step_id) if isinstance(inherited.get(step_id), dict) else {}
    provenance = reference.get('provenance') if isinstance(reference.get('provenance'), dict) else {}
    value = provenance.get('run_id')
    return value if isinstance(value, str) and value else None


def _same_plan(producer, run):
    return (
        isinstance(producer, dict) and producer.get('conversation_id') == run.get('conversation_id')
        and producer.get('turn_id') == run.get('turn_id') and _attempt_root(producer) == _attempt_root(run)
    )


def _find_sidecar(run, step_id, user_id):
    """The step's sidecar: on the run, on its step record, or on the attempt a retry reused it from."""
    run_id, conversation_id = run.get('id'), run.get('conversation_id')
    entry = _entry(run, step_id)
    sidecar = _sidecar(entry)
    if sidecar is None:
        record = get_orchestration_step_record(run_id, step_id, user_id, conversation_id)
        sidecar = _sidecar(record)
        entry = entry or record
    if sidecar is None:
        producer_id = _producer_run_id(run, step_id, entry)
        if producer_id and producer_id != run_id:
            producer = get_orchestration_run(producer_id, user_id, conversation_id=conversation_id, strict=True)
            if _same_plan(producer, run):
                sidecar = _sidecar(_entry(producer, step_id)) or _sidecar(
                    get_orchestration_step_record(producer_id, step_id, user_id, conversation_id),
                )
    return sidecar


def _matches(sidecar, *, run, step_id, user_id):
    """Whether a started run's sidecar belongs to this plan, step and requester, run id included."""
    root = _attempt_root(run)
    workflow_id, run_id = sidecar.get('workflow_id'), sidecar.get('run_id')
    if not (
        sidecar.get('version') == WORKFLOW_RUN_VERSION and sidecar.get('step_id') == step_id
        and sidecar.get('conversation_id') == run.get('conversation_id') and sidecar.get('requested_by') == user_id
        and sidecar.get('attempt_root_run_id') == root
        and isinstance(workflow_id, str) and workflow_id and isinstance(run_id, str) and run_id
    ):
        return False
    try:
        return started_workflow_run_id(user_id, workflow_id, attempt_root_run_id=root, step_id=step_id) == run_id
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# The workflow and its run (one point read each; tests replace the containers)
# ---------------------------------------------------------------------------

def _point_read(container, item, partition_key):
    try:
        return container.read_item(item=item, partition_key=partition_key)
    except CosmosResourceNotFoundError:
        return None


def _read_workflow(user_id, workflow_id):
    # Imported here, as the run step imports them: the containers need initialized storage.
    from config import cosmos_personal_workflows_container

    return _point_read(cosmos_personal_workflows_container, workflow_id, user_id)


def _read_workflow_run(user_id, run_id):
    from config import cosmos_personal_workflow_runs_container

    return _point_read(cosmos_personal_workflow_runs_container, run_id, user_id)


def _link_state(run):
    from functions_workflow_runtime_store import WAITING_STATES

    status = str(run.get('status') or '').strip().lower()
    if status in _LINK_STATE_FOR_RUN_STATUS:
        return _LINK_STATE_FOR_RUN_STATUS[status]
    if status in WAITING_STATES:
        return LINK_STATE_WAITING
    return LINK_STATE_RUNNING


def _name(*values):
    for value in values:
        text = clean_catalog_text(value, NAME_MAX_LENGTH)
        if text:
            return text
    return ''


def _link(step_id, *, state, name='', reason=None, workflow_id=None, run_id=None):
    return {
        'step_id': step_id, 'name': name, 'state': state, 'reason': reason,
        'workflow_id': workflow_id, 'workflow_run_id': run_id,
    }


def _unavailable(step_id, reason, *, name=''):
    return _link(step_id, state=LINK_STATE_UNAVAILABLE, name=name, reason=reason)


def _describe(step_id, sidecar, user_id):
    workflow_id, run_id = sidecar['workflow_id'], sidecar['run_id']
    name = _name(sidecar.get('name'))
    workflow = _read_workflow(user_id, workflow_id)
    if (
        not isinstance(workflow, dict) or workflow.get('id') != workflow_id or workflow.get('user_id') != user_id
        or workflow.get('deleting') or workflow.get('status') == 'deleting'
    ):
        return _unavailable(step_id, REASON_WORKFLOW_DELETED, name=name)
    name = _name(workflow.get('name'), name)
    run = _read_workflow_run(user_id, run_id)
    if (
        not isinstance(run, dict) or run.get('id') != run_id or run.get('workflow_id') != workflow_id
        or run.get('user_id') != user_id
    ):
        return _unavailable(step_id, REASON_RUN_MISSING, name=name)
    return _link(step_id, state=_link_state(run), name=name, workflow_id=workflow_id, run_id=run_id)


def workflow_run_links(run, conversation, *, identity, settings, response_removed):
    """Every saved workflow run ``run``'s plan started, for its requester's run links, in plan order.

    ``response_removed`` is called at most once, and only when the requester may open the links
    here, to learn whether content review removed the run's response. Storage failures raise.
    """
    user_id = identity.get('user_id')
    started = []
    for step_id in _plan_step_ids(run):
        sidecar = _find_sidecar(run, step_id, user_id)
        if sidecar is None or sidecar.get('status') not in WORKFLOW_RUN_STARTED_STATUSES:
            continue
        if not _matches(sidecar, run=run, step_id=step_id, user_id=user_id):
            _log(
                'A workflow run link did not match the plan that started it.', logging.WARNING,
                code='workflow_run_link_mismatch',
            )
            continue
        started.append((step_id, sidecar))
    blocked = workflow_run_gate(settings, identity.get('roles'))
    if not blocked and not conversation_is_private(conversation, user_id):
        blocked = WORKFLOW_REASON_SHARED_CONVERSATION
    if not blocked and started and response_removed():
        blocked = REASON_CONTENT_REVIEW
    return {
        'run_id': run.get('id'),
        'workflow_runs': [
            _unavailable(step_id, blocked) if blocked else _describe(step_id, sidecar, user_id)
            for step_id, sidecar in started
        ],
    }


__all__ = [
    'ERROR_MESSAGES',
    'LINK_STATE_UNAVAILABLE',
    'REASON_CONTENT_REVIEW',
    'REASON_RUN_MISSING',
    'REASON_WORKFLOW_DELETED',
    'SERVICE_UNAVAILABLE_CODE',
    'WORKFLOW_RUN_LINK_STATES',
    'error_payload',
    'workflow_run_links',
]
