# functions_workflow_plan_replay.py
"""Plan replay: a personal workflow task that repeats one approved chat-orchestration plan.

The creator approved a plan in chat. The server freezes that plan (normalized, SHA-256 hashed)
onto a workflow task and replays it as the creator, in the workflow's own conversation. The
model never adds, removes or rewrites a step during a replay; model steps still run with their
frozen instructions.

Every run re-authorizes the creator: the settings, the frozen hash, the replay allowlist, each
step's capability against the current admin list, and every source the plan reads. Background
runs carry no roles, so a step that needs a signed-in session is refused when the plan is frozen
and again before step 1 of every run. A plan therefore behaves the same whether it was started by
hand or by the schedule.
"""

import hashlib
import json
from copy import deepcopy

from functions_orchestration_registry import (
    DEPENDENCY_PLAN_CONTRACT_VERSION,
    VISUAL_IMAGE_PROPOSAL,
    WORKFLOW_PLAN_REPLAY_SETTING,
    approval_floor_capability_ids,
    external_effect_capability_ids,
    get_capability,
    resolve_available_capabilities,
)
from functions_orchestration_schema import plan_document_ids
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_definitions import WorkflowPublicValidationError


PLAN_REPLAY_TASK_TYPE = 'plan_replay'
PLAN_REPLAY_TASK_VERSION = 1
PLAN_REPLAY_ALLOWLIST_VERSION = 'plan-replay-allowlist-v1'
PLAN_REPLAY_RESULT_CONTRACT = 'plan-replay-result-v1'
PLAN_REPLAY_TIME_HANDLING = 'frozen_with_run_time_line'
PLAN_REPLAY_MAX_STEPS = 8
PLAN_REPLAY_TASK_NAME = 'Repeat saved plan'

# Deny by default. Each entry says why repeating it as the creator, without a signed-in session,
# reads nothing the creator could not read and writes nothing outside the workflow's conversation.
REPLAYABLE_CAPABILITIES = {
    'document_search': 'Searches documents the creator can still open; access is re-checked before every run.',
    'document_analyze': 'Analyzes documents the creator can still open, with the frozen instructions.',
    'document_compare': 'Compares documents the creator can still open, with the frozen instructions.',
    'document_merge': 'Merges documents the creator can still open into a file kept with the run.',
    'tabular_inspect': 'Reads the shape of tabular files the creator can still open; it finishes in the step.',
    'compose': 'Writes the answer from earlier step results with the frozen instructions.',
    'generate_image': 'Creates a new image from the frozen prompt; reference images are refused.',
}

# A step that needs the caller's signed-in roles. A repeated run has none.
ROLE_REQUIRED_CAPABILITIES = frozenset({'web_search'})
# Steps that finish asynchronously, after the plan stops waiting. Refused in this slice.
WAIT_CAPABILITIES = frozenset({'tabular_analyze', 'render_file'})
# Phase 6c in-plan wait kind. Mirrors SAVED_WORKFLOW_RUN_WAIT_KIND in
# functions_orchestration_workflow_run_wait.py, which is not on this base yet.
SAVED_WORKFLOW_RUN_WAIT_KIND = 'saved_workflow_run'
REFUSED_WAIT_KINDS = frozenset({
    'native_tabular_compute', 'orchestration_output', 'orchestration_result',
    SAVED_WORKFLOW_RUN_WAIT_KIND,
})
WORKFLOW_CAPABILITIES = frozenset({
    'workflow_propose', 'workflow_run', 'workflow_results', 'workflow_handoff',
})

REFUSAL_MESSAGES = {
    'replay_disabled': 'Repeating chat plans is turned off. Ask an admin to turn it on, then run the workflow again.',
    'orchestration_disabled': 'Chat orchestration is turned off, so this saved plan can\'t run.',
    'personal_workflows_disabled': 'Personal workflows are turned off, so this saved plan can\'t run.',
    'group_not_supported': 'Only personal workflows can repeat a chat plan.',
    'creator_mismatch': 'This saved plan can only run as the person who created it.',
    'plan_hash_mismatch': 'This saved plan changed after it was approved. Create it again from chat.',
    'allowlist_version_unsupported': 'This saved plan was made with rules this version doesn\'t support. Create it again from chat.',
    'capability_not_replayable': 'A step in this plan can\'t be repeated by a saved workflow.',
    'capability_unavailable': 'A step in this plan is turned off or no longer available.',
    'role_required': 'A step in this plan needs your signed-in session, which a repeated run doesn\'t have.',
    'elicitation_not_replayable': 'This plan asked you a question before it ran. Repeated runs can\'t stop to ask.',
    'source_unavailable': 'A document, group or public workspace this plan reads is no longer available to you.',
    'source_run_not_eligible': 'Only a completed plan that you approved can be saved as a workflow.',
    'shared_conversation_not_allowed': 'Plans from shared conversations can\'t be saved as a workflow.',
    'conversation_context_not_replayable': 'This plan relies on earlier messages in the chat, so it can\'t be repeated on its own.',
    'replay_wait_unsupported': 'A step in this plan waits for a file or result to finish, which a repeated run can\'t do yet.',
    'replay_budget_exceeded': 'The repeated plan took longer than its time limit and was stopped.',
    'replay_execution_failed': 'The repeated plan could not finish. Open the run for details.',
    'plan_replay_read_only': 'A saved plan can\'t be edited. Create it again from chat.',
    'workflow_replay_managed': 'This workflow repeats a saved chat plan; only its name, schedule and alerts can change.',
    'model_unavailable': 'The model this plan used is no longer available. Create it again from chat.',
}


class PlanReplayRefused(WorkflowInputError):
    """Raised at run time. ``public_message`` is fixed text, never model output."""

    def __init__(self, code, message=None, *, step_id=None, refusals=None):
        text = message or REFUSAL_MESSAGES.get(code) or REFUSAL_MESSAGES['replay_execution_failed']
        super().__init__(text)
        self.code = code
        self.public_message = text
        self.step_id = step_id
        self.refusals = list(refusals or [])


class PlanReplaySaveError(WorkflowPublicValidationError):
    """Raised when a replay workflow is created or saved. Routes return ``{error, code}``."""

    def __init__(self, code, message=None, *, refusals=None):
        text = message or REFUSAL_MESSAGES.get(code) or REFUSAL_MESSAGES['source_run_not_eligible']
        super().__init__(text)
        self.code = code
        self.public_message = text
        self.refusals = list(refusals or [])


def capability_label(capability_id):
    """The registry's label; never the model-written step title."""
    capability = get_capability(capability_id) if isinstance(capability_id, str) else None
    return (capability or {}).get('label') or 'Unknown step'


def _declared_wait_kinds(value, found=None):
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('wait_kind', 'kind') and isinstance(item, str) and item in REFUSED_WAIT_KINDS:
                found.add(item)
            _declared_wait_kinds(item, found)
    elif isinstance(value, list):
        for item in value:
            _declared_wait_kinds(item, found)
    return found


def _refusal(code, number, step, message):
    return {
        'code': code, 'step_number': number,
        'step_id': str(step.get('step_id') or '') if isinstance(step, dict) else '',
        'capability_id': str(step.get('capability_id') or '') if isinstance(step, dict) else '',
        'message': message,
    }


def classify_plan_steps(plan):
    """Return every refusal for ``plan``; an empty list means every enabled step may replay.

    One function serves the freeze and the run-time preflight, so both apply the same rules.
    """
    plan = plan if isinstance(plan, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    refusals = []
    enabled = [step for step in steps if isinstance(step, dict) and step.get('enabled', True)]
    if not enabled:
        refusals.append(_refusal('capability_unavailable', 0, {}, 'This plan has no steps to repeat.'))
    if len(enabled) > PLAN_REPLAY_MAX_STEPS:
        refusals.append(_refusal(
            'replay_budget_exceeded', 0, {},
            f'A saved plan can repeat at most {PLAN_REPLAY_MAX_STEPS} steps.',
        ))
    blocked = set(WORKFLOW_CAPABILITIES) | set(approval_floor_capability_ids()) | set(external_effect_capability_ids())
    for number, step in enumerate(enabled, start=1):
        capability_id = step.get('capability_id')
        label = capability_label(capability_id)
        prefix = f'Step {number} ({label})'
        arguments = step.get('arguments') if isinstance(step.get('arguments'), dict) else {}
        if _declared_wait_kinds(step):
            refusals.append(_refusal(
                'replay_wait_unsupported', number, step,
                f'{prefix} waits for work to finish after the plan stops, which a repeated run can\'t do yet.',
            ))
        elif capability_id in WAIT_CAPABILITIES:
            refusals.append(_refusal(
                'replay_wait_unsupported', number, step,
                f'{prefix} finishes after the plan stops waiting, which a repeated run can\'t do yet.',
            ))
        elif capability_id in ROLE_REQUIRED_CAPABILITIES:
            refusals.append(_refusal(
                'role_required', number, step,
                f'{prefix} needs your signed-in session, which a repeated run doesn\'t have.',
            ))
        elif capability_id in blocked or capability_id not in REPLAYABLE_CAPABILITIES:
            refusals.append(_refusal(
                'capability_not_replayable', number, step,
                f'{prefix} can\'t be repeated by a saved workflow.',
            ))
        elif capability_id == 'generate_image' and (
            arguments.get('reference_document_ids') or arguments.get('reference_message_ids')
        ):
            refusals.append(_refusal(
                'capability_not_replayable', number, step,
                f'{prefix} edits a reference image. Repeated runs only create new images from a prompt.',
            ))
        elif capability_id == 'compose' and VISUAL_IMAGE_PROPOSAL in (arguments.get('visuals') or []):
            refusals.append(_refusal(
                'capability_not_replayable', number, step,
                f'{prefix} offers an image for you to accept, which a repeated run can\'t do.',
            ))
    if plan.get('deliverables'):
        refusals.append(_refusal(
            'replay_wait_unsupported', 0, {},
            f'This plan creates a file ({capability_label("render_file")}), which a repeated run can\'t do yet.',
        ))
    return refusals


_FROZEN_SEED_FIELDS = (
    'model_deployment', 'model_id', 'model_endpoint_id', 'model_provider', 'reasoning_effort',
    'doc_scope', 'document_ids', 'tags', 'document_filter_mode', 'active_group_ids',
    'active_public_workspace_ids',
)
_REPLAY_DOC_SCOPES = ('all', 'personal', 'group', 'public')


def build_frozen_seeds(seeds):
    """Keep only the request choices a replay may reuse; everything else is dropped."""
    seeds = seeds if isinstance(seeds, dict) else {}
    frozen = {}
    for field in _FROZEN_SEED_FIELDS:
        value = seeds.get(field)
        if value in (None, '', [], {}):
            continue
        frozen[field] = deepcopy(value)
    scope = frozen.get('doc_scope') or 'all'
    if scope not in _REPLAY_DOC_SCOPES:
        raise PlanReplaySaveError('conversation_context_not_replayable')
    for field in ('document_ids', 'tags', 'active_group_ids', 'active_public_workspace_ids'):
        if field in frozen and (
            not isinstance(frozen[field], list) or any(not isinstance(item, str) for item in frozen[field])
        ):
            raise PlanReplaySaveError('source_run_not_eligible')
    return frozen


_CONTRACT_PLAN_KEYS = (
    'plan_id', 'planner_contract_version', 'intent', 'assumptions', 'steps', 'inputs', 'outputs',
    'final_response', 'deliverables', 'model_routing',
)  # The plan-revision fields minus run identity, approval, status and edit/validation state.
_CONTRACT_STEP_KEYS = (
    'step_id', 'capability_id', 'title', 'rationale', 'arguments', 'depends_on', 'inputs', 'outputs',
    'optional', 'enabled', 'estimated_cost', 'role', 'model_task', 'model_binding', 'delivers',
)


def normalize_plan_contract(plan):
    """The executable plan without runtime state. What is stored is what is hashed and run."""
    plan = plan if isinstance(plan, dict) else {}
    contract = {key: deepcopy(plan[key]) for key in _CONTRACT_PLAN_KEYS if key in plan}
    contract['steps'] = [
        {key: deepcopy(step[key]) for key in _CONTRACT_STEP_KEYS if key in step}
        for step in plan.get('steps') or [] if isinstance(step, dict)
    ]
    return contract


def plan_replay_sha256(request, frozen_plan, frozen_seeds):
    payload = {
        'task_version': PLAN_REPLAY_TASK_VERSION, 'allowlist_version': PLAN_REPLAY_ALLOWLIST_VERSION,
        'request': request, 'plan': frozen_plan, 'seeds': frozen_seeds,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _refuse(code, refusals=None):
    first = (refusals or [{}])[0]
    raise PlanReplayRefused(
        code, first.get('message') or None, step_id=first.get('step_id') or None, refusals=refusals,
    )


def authorize_plan_replay_settings(settings):
    settings = settings if isinstance(settings, dict) else {}
    if settings.get(WORKFLOW_PLAN_REPLAY_SETTING) is not True:
        _refuse('replay_disabled')
    if settings.get('enable_chat_orchestration') is not True:
        _refuse('orchestration_disabled')
    if settings.get('allow_user_workflows') is not True:
        _refuse('personal_workflows_disabled')


def authorize_plan_replay_run(workflow, task, settings):
    """Re-authorize the creator before step 1 of every run, or raise ``PlanReplayRefused``."""
    authorize_plan_replay_settings(settings)
    workflow = workflow if isinstance(workflow, dict) else {}
    if workflow.get('group_id') or str(workflow.get('scope') or 'personal').lower() == 'group':
        _refuse('group_not_supported')
    replay = (task or {}).get('plan_replay') if isinstance(task, dict) else None
    if (task or {}).get('type') != PLAN_REPLAY_TASK_TYPE or not isinstance(replay, dict):
        _refuse('plan_hash_mismatch')
    user_id = str(workflow.get('user_id') or '')
    provenance = replay.get('provenance') if isinstance(replay.get('provenance'), dict) else {}
    approval = replay.get('approval') if isinstance(replay.get('approval'), dict) else {}
    if not user_id or any(
        str(value or '') != user_id
        for value in (workflow.get('created_by') or user_id, provenance.get('created_by'), approval.get('approved_by'))
    ):
        _refuse('creator_mismatch')
    if replay.get('version') != PLAN_REPLAY_TASK_VERSION or replay.get('allowlist_version') != PLAN_REPLAY_ALLOWLIST_VERSION:
        _refuse('allowlist_version_unsupported')
    frozen_plan = replay.get('frozen_plan')
    frozen_seeds = replay.get('frozen_seeds') if isinstance(replay.get('frozen_seeds'), dict) else {}
    digest = plan_replay_sha256(replay.get('request'), frozen_plan, frozen_seeds)
    if digest != replay.get('plan_sha256') or digest != approval.get('plan_sha256'):
        _refuse('plan_hash_mismatch')
    if normalize_plan_contract(frozen_plan) != frozen_plan:
        _refuse('plan_hash_mismatch')
    refusals = classify_plan_steps(frozen_plan)
    if refusals:
        _refuse(refusals[0]['code'], refusals)
    authorize_replay_capabilities(user_id, frozen_plan, settings)
    authorize_replay_sources(user_id, frozen_plan, frozen_seeds, settings)
    return {'user_id': user_id, 'plan_sha256': digest, 'frozen_plan': frozen_plan, 'frozen_seeds': frozen_seeds}


def authorize_replay_capabilities(user_id, frozen_plan, settings):
    """Every enabled step must still be on and allowed by the admin list, with no roles.

    Runtime service bindings are left to the harness, which checks them again before step 1.
    """
    enabled = [step for step in frozen_plan.get('steps') or [] if step.get('enabled', True)]
    required = {step.get('capability_id') for step in enabled}
    reasons = {}
    available = resolve_available_capabilities(
        settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        request_context={
            'user_id': user_id, 'user_roles': [], 'user_enable_agents': False,
            'message_urls': [], 'allowed_user_urls': [],
        },
        candidate_ids=required, unavailable=reasons,
        contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION, include_runtime_bindings=False,
    )
    available_ids = {item['id'] for item in available}
    for number, step in enumerate(enabled, start=1):
        capability_id = step.get('capability_id')
        if capability_id in available_ids:
            continue
        prefix = f'Step {number} ({capability_label(capability_id)})'
        if reasons.get(capability_id) == 'caller_access_required':
            refusal = _refusal('role_required', number, step,
                               f'{prefix} needs your signed-in session, which a repeated run doesn\'t have.')
        else:
            refusal = _refusal('capability_unavailable', number, step, f'{prefix} is turned off or no longer available.')
        _refuse(refusal['code'], [refusal])


def authorize_replay_sources(user_id, frozen_plan, frozen_seeds, settings):
    """Re-check every document, group and public workspace the plan reads, as the creator."""
    group_ids = list(frozen_seeds.get('active_group_ids') or [])
    workspace_ids = list(frozen_seeds.get('active_public_workspace_ids') or [])
    if group_ids:
        if settings.get('enable_group_workspaces') is False:
            _refuse('source_unavailable')
        from functions_group import (
            check_group_status_allows_operation, find_group_by_id, get_user_role_in_group,
        )

        for group_id in group_ids:
            group = find_group_by_id(group_id)
            if not group or get_user_role_in_group(group, user_id) is None:
                _refuse('source_unavailable')
            allowed, _reason = check_group_status_allows_operation(group, 'chat')
            if not allowed:
                _refuse('source_unavailable')
    if workspace_ids:
        if settings.get('enable_public_workspaces') is not True:
            _refuse('source_unavailable')
        from functions_public_workspaces import (
            check_public_workspace_status_allows_operation, find_public_workspace_by_id,
        )

        for workspace_id in workspace_ids:
            workspace = find_public_workspace_by_id(workspace_id)
            if not workspace:
                _refuse('source_unavailable')
            allowed, _reason = check_public_workspace_status_allows_operation(workspace, 'chat')
            if not allowed:
                _refuse('source_unavailable')
    document_ids = list(dict.fromkeys([
        *(frozen_seeds.get('document_ids') or []), *plan_document_ids(frozen_plan),
    ]))
    if not document_ids:
        return
    from functions_mixed_source_orchestration import resolve_authorized_source_manifest

    try:
        manifest = resolve_authorized_source_manifest(
            document_ids, user_id, conversation_id=None,
            doc_scope=frozen_seeds.get('doc_scope') or 'all',
            active_group_ids=group_ids or None, active_public_workspace_ids=workspace_ids or None,
        )
    except (ValueError, LookupError, PermissionError):
        _refuse('source_unavailable')
    authorized = {
        entry.get('document_id') for entry in manifest
        if isinstance(entry, dict) and entry.get('authorization_status') == 'authorized'
    }
    if set(document_ids) - authorized:
        _refuse('source_unavailable')
