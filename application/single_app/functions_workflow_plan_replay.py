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
import logging
import re
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial

from azure.cosmos import exceptions
from functions_appinsights import log_event
from functions_orchestration_context import ConversationContextError
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
PLAN_REPLAY_DEFAULT_ALERT_RULE_NAME = 'Run failed'
# The run inspector's copy of the final answer matches the task preview's cap; the full answer
# stays in the workflow conversation and in the task's stored json result.
PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT = 4000

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
# Phase 6c stores which workflow_run step waits as plan['workflow_run_waits'] =
# {step_id: {'version': 1, 'workflow': handle}}. Contract normalization drops the key, so it is
# read from the source run before the plan is frozen.
WORKFLOW_RUN_WAITS_PLAN_KEY = 'workflow_run_waits'
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
    'workflow_replay_run_managed': 'This plan runs as part of a saved workflow. Open the workflow to run or cancel it.',
    'model_unavailable': 'The model this plan used is no longer available. Create it again from chat.',
    'quota_exceeded': 'You already have the most saved chat-plan workflows allowed. Delete one before adding another.',
    'workflow_conflict': 'This workflow is being changed or deleted. Reload and try again.',
    'workflow_unavailable': 'This workflow was deleted or is being deleted, so the saved plan didn\'t run.',
    'run_not_found': 'That plan could not be found.',
    'invalid_request': 'The request was not valid. Reload the plan and try again.',
    'service_unavailable': 'The plan could not be saved as a workflow right now. Try again.',
}

# HTTP status for each code when a request to preview or save a replay is refused.
PLAN_REPLAY_ERROR_STATUS = {
    'replay_disabled': 403,
    'orchestration_disabled': 403,
    'personal_workflows_disabled': 403,
    'creator_mismatch': 403,
    'shared_conversation_not_allowed': 403,
    'run_not_found': 404,
    'source_run_not_eligible': 409,
    'plan_hash_mismatch': 409,
    'workflow_conflict': 409,
    'quota_exceeded': 429,
    'service_unavailable': 503,
}

PLAN_REPLAY_MAX_SECONDS = 900
PLAN_REPLAY_POLL_SECONDS = 5
PLAN_REPLAY_STOP_GRACE_SECONDS = 30


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


def plan_replay_error_response(code, message=None, refusals=None):
    """Return ``(payload, status)`` for a refused preview or save. Every text is fixed server text."""
    payload = {'error': message or REFUSAL_MESSAGES.get(code) or REFUSAL_MESSAGES['service_unavailable'], 'code': code}
    if refusals:
        payload['refusals'] = [dict(item) for item in refusals if isinstance(item, dict)]
    return payload, PLAN_REPLAY_ERROR_STATUS.get(code, 422)


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


def classify_plan_steps(plan, workflow_run_waits=None):
    """Return every refusal for ``plan``; an empty list means every enabled step may replay.

    One function serves the freeze and the run-time preflight, so both apply the same rules.
    ``workflow_run_waits`` is the source run's Phase 6c wait marker, read before normalization.
    """
    plan = plan if isinstance(plan, dict) else {}
    steps = plan.get('steps') if isinstance(plan.get('steps'), list) else []
    refusals = []
    enabled = [step for step in steps if isinstance(step, dict) and step.get('enabled', True)]
    # Any marker that is present fails closed: an unreadable one refuses the whole plan below.
    waited_step_ids = set(workflow_run_waits) if isinstance(workflow_run_waits, dict) else set()
    waited_matched = False
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
        if isinstance(step.get('step_id'), str) and step['step_id'] in waited_step_ids:
            waited_matched = True
            refusals.append(_refusal(
                'replay_wait_unsupported', number, step,
                f'{prefix} waits for a saved workflow run to finish, which a repeated run can\'t do yet.',
            ))
        elif _declared_wait_kinds(step):
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
    if workflow_run_waits not in (None, {}) and not waited_matched:
        refusals.append(_refusal(
            'replay_wait_unsupported', 0, {},
            'This plan waits for a saved workflow run to finish, which a repeated run can\'t do yet.',
        ))
    # Every compiled plan declares at least the implicit answer. Only a file waits on render_file;
    # any other kind outside the answer, image and visuals is refused too.
    deliverables = plan.get('deliverables') if isinstance(plan.get('deliverables'), list) else []
    kinds = {deliverable.get('kind') if isinstance(deliverable, dict) else None for deliverable in deliverables}
    if 'file' in kinds:
        refusals.append(_refusal(
            'replay_wait_unsupported', 0, {},
            f'This plan creates a file ({capability_label("render_file")}), which a repeated run can\'t do yet.',
        ))
    if kinds - {'file', 'answer', 'image', 'chart', 'diagram'}:
        refusals.append(_refusal(
            'capability_not_replayable', 0, {},
            'This plan delivers something a saved workflow can\'t create.',
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
    if _contains_elicitation_marker(frozen_plan) or _contains_elicitation_marker(frozen_seeds):
        # Freezing refuses a plan that asked a question; a stored one is refused again before step 1.
        _refuse('elicitation_not_replayable')
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
        if settings.get('enable_group_workspaces') is not True:
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


def _utc_now():
    return datetime.now(timezone.utc)


def _iso(value):
    source = value or _utc_now()
    if isinstance(source, str):
        return source
    if source.tzinfo is None:
        source = source.replace(tzinfo=timezone.utc)
    return source.isoformat()


def _enabled_plan_steps(plan):
    return [
        step for step in (plan or {}).get('steps') or []
        if isinstance(step, dict) and step.get('enabled', True)
    ]


def _contains_key(value, names):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in names:
                return True
            if _contains_key(item, names):
                return True
    elif isinstance(value, list):
        return any(_contains_key(item, names) for item in value)
    return False


def _contains_elicitation_marker(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).startswith('elicitation'):
                return True
            if _contains_elicitation_marker(item):
                return True
    elif isinstance(value, list):
        return any(_contains_elicitation_marker(item) for item in value)
    return False


def _strip_run_time_line(message, fallback=''):
    text = str(message or '').strip()
    if not text:
        return str(fallback or '').strip()
    lines = text.splitlines()
    while lines and re.fullmatch(r'Current date and time: .+ \([^)]+\)', lines[-1].strip()):
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return '\n'.join(lines).strip() or str(fallback or '').strip()


def freeze_source_run(record, conversation, user_id, settings):
    """Return the frozen replay payload and any per-step refusal details."""
    record = record if isinstance(record, dict) else {}
    conversation = conversation if isinstance(conversation, dict) else {}
    if record.get('user_id') != user_id:
        raise PlanReplaySaveError('creator_mismatch')
    # Imported here to keep storage-free save preflight importable without memory bootstrap.
    from functions_orchestration_memory import conversation_is_private

    if conversation.get('user_id') != user_id or not conversation_is_private(conversation, user_id):
        raise PlanReplaySaveError('shared_conversation_not_allowed')
    approval = record.get('approval') if isinstance(record.get('approval'), dict) else {}
    failures = record.get('failures')
    if (
        record.get('status') != 'completed'
        or record.get('outcome') not in (None, 'completed')
        or approval.get('state') != 'approved'
        or record.get('failure')
        or (isinstance(failures, list) and failures)
        or record.get('workflow_replay')
        or not isinstance(record.get('plan'), dict)
    ):
        raise PlanReplaySaveError('source_run_not_eligible')
    seeds = record.get('seeds') if isinstance(record.get('seeds'), dict) else {}
    if (
        record.get('answered_questions')
        or seeds.get('elicitation_references')
        or _contains_elicitation_marker(record.get('plan'))
    ):
        raise PlanReplaySaveError('elicitation_not_replayable')
    context = record.get('conversation_context') if isinstance(record.get('conversation_context'), dict) else {}
    if record.get('result_aliases') or record.get('plan', {}).get('result_aliases') or _contains_key(
        context, {'analysis_result_contexts'},
    ):
        raise PlanReplaySaveError('conversation_context_not_replayable')
    request = _strip_run_time_line(record.get('resolved_message'), record.get('user_message'))
    if not request:
        raise PlanReplaySaveError('source_run_not_eligible')
    frozen_seeds = build_frozen_seeds(seeds)
    # Read Phase 6c's wait marker before normalization drops it from the frozen plan.
    workflow_run_waits = record['plan'].get(WORKFLOW_RUN_WAITS_PLAN_KEY)
    frozen_plan = normalize_plan_contract(record['plan'])
    refusals = classify_plan_steps(frozen_plan, workflow_run_waits)
    if not refusals:
        try:
            authorize_replay_capabilities(user_id, frozen_plan, settings)
        except PlanReplayRefused as exc:
            refusals.extend(exc.refusals or [{
                'code': exc.code, 'step_number': 0, 'step_id': exc.step_id or '',
                'capability_id': '', 'message': exc.public_message,
            }])
    return {
        'request': request,
        'frozen_plan': frozen_plan,
        'frozen_seeds': frozen_seeds,
        'plan_sha256': plan_replay_sha256(request, frozen_plan, frozen_seeds),
        'refusals': refusals,
        'source_run_id': record['id'],
        'source_conversation_id': record['conversation_id'],
        'time_zone': record.get('time_zone') or '',
    }


def build_plan_replay_preview(freeze, settings):
    freeze = freeze if isinstance(freeze, dict) else {}
    steps = []
    for number, step in enumerate(_enabled_plan_steps(freeze.get('frozen_plan')), start=1):
        capability_id = step.get('capability_id') or ''
        steps.append({
            'number': number,
            'step_id': str(step.get('step_id') or ''),
            'title': str(step.get('title') or '').strip(),
            'capability_id': capability_id,
            'capability_label': capability_label(capability_id),
            'enabled': True,
        })
    from functions_workflow_limits import get_orchestration_workflow_min_interval_seconds

    return {
        'eligible': not bool(freeze.get('refusals')),
        'request': freeze.get('request') or '',
        'steps': steps,
        'refusals': list(freeze.get('refusals') or []),
        'plan_sha256': freeze.get('plan_sha256') or '',
        'time_handling': PLAN_REPLAY_TIME_HANDLING,
        'time_zone': freeze.get('time_zone') or '',
        'min_interval_seconds': get_orchestration_workflow_min_interval_seconds(settings),
        'allowlist_version': PLAN_REPLAY_ALLOWLIST_VERSION,
        'max_steps': PLAN_REPLAY_MAX_STEPS,
    }


def attach_plan_replay(task, plan_replay):
    return {
        **(task if isinstance(task, dict) else {}),
        'type': PLAN_REPLAY_TASK_TYPE,
        'name': PLAN_REPLAY_TASK_NAME,
        'plan_replay': deepcopy(plan_replay),
    }


def stored_plan_replay_task(workflow):
    for task in (workflow or {}).get('tasks') or []:
        if isinstance(task, dict) and task.get('type') == PLAN_REPLAY_TASK_TYPE and isinstance(task.get('plan_replay'), dict):
            return task
    return None


def build_plan_replay_payload(freeze, user_id, now):
    freeze = freeze if isinstance(freeze, dict) else {}
    timestamp = _iso(now)
    return {
        'version': PLAN_REPLAY_TASK_VERSION,
        'allowlist_version': PLAN_REPLAY_ALLOWLIST_VERSION,
        'request': freeze.get('request') or '',
        'frozen_plan': deepcopy(freeze.get('frozen_plan')),
        'frozen_seeds': deepcopy(freeze.get('frozen_seeds') or {}),
        'plan_sha256': freeze.get('plan_sha256') or '',
        'approval': {'approved_by': user_id, 'approved_at': timestamp, 'plan_sha256': freeze.get('plan_sha256') or ''},
        'provenance': {
            'source_run_id': freeze.get('source_run_id') or '',
            'source_conversation_id': freeze.get('source_conversation_id') or '',
            'created_by': user_id,
            'frozen_at': timestamp,
            'time_handling': PLAN_REPLAY_TIME_HANDLING,
            'time_zone': freeze.get('time_zone') or '',
        },
    }


def _read_source_run(run_id, user_id, conversation_id):
    from functions_orchestration_plan_revisions import read_revision_run

    return read_revision_run(run_id, user_id, conversation_id)


def _read_conversation(conversation_id):
    from config import cosmos_conversations_container

    return cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)


def _workflow_name_from_request(request):
    text = re.sub(r'\s+', ' ', str(request or '')).strip()
    return f'Repeat: {text[:80]}' if text else 'Repeat saved plan'


def _default_alert_fields(workflow_id):
    # A scheduled replay can be refused or fail with nobody watching, so every created replay
    # workflow starts with one editable rule that puts failed runs in the creator's bell.
    return {
        'alert_mode': 'rules',
        'alert_priority': 'none',
        'alert_evaluation': {'on_error': 'skip'},
        'alert_rules': [{
            'id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'workflow-replay:alert:{workflow_id}:run-failed')),
            'name': PLAN_REPLAY_DEFAULT_ALERT_RULE_NAME,
            'enabled': True,
            'severity': 'high',
            'delivery': 'notify_only',
            'scope': {'type': 'final', 'task_id': ''},
            'condition': {'type': 'run_status', 'statuses': ['failed', 'completed_with_task_errors']},
        }],
    }


def _workflow_payload_from_body(body, request, workflow_id):
    body = body if isinstance(body, dict) else {}
    trigger = body.get('trigger') if isinstance(body.get('trigger'), dict) else {}
    schedule = body.get('schedule') if isinstance(body.get('schedule'), dict) else trigger.get('schedule')
    trigger_type = str(body.get('trigger_type') or trigger.get('type') or ('interval' if schedule else 'manual')).strip().lower()
    if trigger_type == 'scheduled':
        trigger_type = 'interval'
    name = str(body.get('name') or '').strip() or _workflow_name_from_request(request)
    return {
        'name': name[:120],
        'description': str(body.get('description') or '').strip(),
        'task_prompt': request,
        'definition_version': 2,
        'runner_type': 'model',
        # Every run holds the workflow's durable lease, so the scheduler and a worker restart
        # resume the same run instead of starting a second replay.
        'durable_execution': True,
        'trigger_type': trigger_type,
        'is_enabled': body.get('enabled') is True or body.get('is_enabled') is True,
        'schedule': schedule or {},
        'tasks': [{
            'type': 'instructions',
            'name': PLAN_REPLAY_TASK_NAME,
            'instructions': request,
            'runner': {'type': 'inherit'},
        }],
        **_default_alert_fields(workflow_id),
    }


def create_plan_replay_workflow(user_id, run_id, body, settings, *, read_run=None, read_conversation=None, now=None):
    body = body if isinstance(body, dict) else {}
    authorize_plan_replay_settings(settings)
    conversation_id = str(body.get('conversation_id') or '').strip()
    if not conversation_id:
        raise PlanReplaySaveError('source_run_not_eligible')
    run_reader = read_run or _read_source_run
    conversation_reader = read_conversation or _read_conversation
    try:
        record = run_reader(run_id, user_id, conversation_id)
        conversation = conversation_reader(conversation_id)
    except exceptions.CosmosResourceNotFoundError as exc:
        raise PlanReplaySaveError('source_run_not_eligible') from exc
    freeze = freeze_source_run(record, conversation, user_id, settings)
    if freeze.get('refusals'):
        first = freeze['refusals'][0]
        raise PlanReplaySaveError(first['code'], first.get('message') or None, refusals=freeze['refusals'])
    if str(body.get('plan_sha256') or '').strip() != freeze['plan_sha256']:
        raise PlanReplaySaveError('plan_hash_mismatch')
    try:
        # The creator must still reach every source today, or the first run would only fail later.
        authorize_replay_sources(user_id, freeze['frozen_plan'], freeze['frozen_seeds'], settings)
    except PlanReplayRefused as exc:
        raise PlanReplaySaveError(exc.code) from None
    from functions_settings import read_user_settings_snapshot
    from functions_workflow_drafts import (
        check_orchestration_workflow_quota, orchestration_workflow_id, read_only_document_resolver,
    )
    from functions_workflow_definitions import WorkflowDefinitionConflict, normalize_workflow_origin, workflow_definition_for_editor
    from functions_personal_workflows import create_personal_workflow_if_absent

    quota_error = check_orchestration_workflow_quota(user_id, settings)
    if quota_error:
        raise PlanReplaySaveError('quota_exceeded')
    timestamp = _iso(now)
    proposal_id = f"replay-{run_id}-{freeze['plan_sha256'][:12]}"
    workflow_id = orchestration_workflow_id(user_id, proposal_id)
    origin = normalize_workflow_origin({
        'source': 'orchestration',
        'conversation_id': freeze['source_conversation_id'],
        'orchestration_run_id': run_id,
        'proposal_id': proposal_id,
        'created_at': timestamp,
        'edited': False,
    })
    try:
        workflow, created = create_personal_workflow_if_absent(
            user_id,
            _workflow_payload_from_body(body, freeze['request'], workflow_id),
            workflow_id=workflow_id,
            origin=origin,
            actor_user_id=user_id,
            settings=settings,
            # Read-only seams, as the chat proposal create uses: saving never repairs user settings.
            user_settings_reader=read_user_settings_snapshot,
            resolve_document=read_only_document_resolver(user_settings_reader=read_user_settings_snapshot),
            plan_replay_task=build_plan_replay_payload(freeze, user_id, timestamp),
        )
    except WorkflowDefinitionConflict as exc:
        raise PlanReplaySaveError('workflow_conflict') from exc
    return {'ok': True, 'workflow': workflow_definition_for_editor(workflow), 'created': bool(created)}


_PLAN_REPLAY_EDITABLE_KEYS = frozenset({
    'id', 'definition_revision', 'name', 'description', 'trigger_type', 'schedule', 'is_enabled',
    'alert_priority', 'alert_mode', 'alert_rules', 'alert_evaluation',
})


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, default=str)


def _browser_json(value):
    # A browser reads 1.0 as 1, so a whole float and its integer are the same saved value.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _browser_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_browser_json(item) for item in value]
    return value


def _same_json(left, right):
    return _canonical(_browser_json(left)) == _canonical(_browser_json(right))


def normalize_plan_replay_update(existing_workflow, payload):
    """Keep only editable replay-workflow fields and preserve the frozen plan."""
    existing = existing_workflow if isinstance(existing_workflow, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    stored = stored_plan_replay_task(existing)
    if not stored:
        return payload
    if 'plan_replay' in payload and not _same_json(payload.get('plan_replay'), stored.get('plan_replay')):
        raise PlanReplaySaveError('plan_replay_read_only')
    incoming_tasks = payload.get('tasks')
    if incoming_tasks is not None:
        if not isinstance(incoming_tasks, list) or len(incoming_tasks) != 1:
            raise PlanReplaySaveError('plan_replay_read_only')
        incoming = incoming_tasks[0] if isinstance(incoming_tasks[0], dict) else {}
        incoming_replay = incoming.get('plan_replay', stored.get('plan_replay'))
        if (
            incoming.get('type', PLAN_REPLAY_TASK_TYPE) != PLAN_REPLAY_TASK_TYPE
            or not _same_json(incoming_replay, stored.get('plan_replay'))
        ):
            raise PlanReplaySaveError('plan_replay_read_only')
    sanitized = {key: deepcopy(existing.get(key)) for key in (
        'task_prompt', 'runner_type', 'definition_version', 'durable_execution',
        'document_action', 'analyze', 'file_sync', 'chat_capabilities_enabled',
        'url_access_enabled', 'model_endpoint_id', 'model_id', 'model_provider',
        'reference_inputs', 'error_handling',
    ) if key in existing}
    for key in _PLAN_REPLAY_EDITABLE_KEYS:
        if key in payload:
            sanitized[key] = deepcopy(payload[key])
        elif key in existing:
            sanitized[key] = deepcopy(existing[key])
    sanitized['tasks'] = [{
        'id': stored.get('id'),
        'type': 'instructions',
        'name': stored.get('name') or PLAN_REPLAY_TASK_NAME,
        'instructions': stored.get('instructions') or (stored.get('plan_replay') or {}).get('request') or '',
        'runner': deepcopy(stored.get('runner') or {'type': 'inherit'}),
    }]
    return sanitized


def build_executable_replay_plan(frozen_plan, *, run_id, plan_id, turn_id, conversation_id, user_id, approved_at):
    plan = deepcopy(frozen_plan if isinstance(frozen_plan, dict) else {})
    plan.update({
        'run_id': run_id,
        'plan_id': plan_id,
        'turn_id': turn_id,
        'conversation_id': conversation_id,
        'user_id': user_id,
        'status': 'approved',
        'approval': {
            'mode': 'manual', 'state': 'approved', 'approved_at': approved_at,
            'approved_by': user_id, 'edited': False,
        },
    })
    for step in plan.get('steps') or []:
        if isinstance(step, dict):
            step['status'] = 'pending'
    return plan


def _deterministic_id(prefix, workflow_run_id, task_id, attempt, kind):
    return f'{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-replay:{kind}:{workflow_run_id}:{task_id}:{attempt}").hex}'


def _authorize_private_conversation(conversation_id, user_id, *, read_conversation=None):
    reader = read_conversation or _read_conversation
    try:
        conversation = reader(conversation_id)
    except exceptions.CosmosResourceNotFoundError:
        raise ConversationContextError('That conversation could not be opened.') from None
    # Imported at the authorization boundary to avoid importing memory services during module import.
    from functions_orchestration_memory import conversation_is_private

    if (
        conversation.get('user_id') != user_id
        or conversation.get('orchestration_deleted')
        or not conversation_is_private(conversation, user_id)
    ):
        raise ConversationContextError('That conversation could not be opened.')
    return conversation


def _verify_workflow_conversation(workflow, conversation_id, user_id, source_conversation_id, *, read_conversation=None):
    if conversation_id == source_conversation_id:
        raise PlanReplayRefused('conversation_context_not_replayable')
    conversation = _authorize_private_conversation(conversation_id, user_id, read_conversation=read_conversation)
    if (
        str(conversation.get('chat_type') or '').strip().lower() != 'workflow'
        or str(conversation.get('workflow_id') or '').strip() != str(workflow.get('id') or '').strip()
        or str(conversation.get('group_id') or '').strip()
    ):
        raise ConversationContextError('That conversation could not be opened.')
    return conversation


def _read_message(message_id, conversation_id):
    from config import cosmos_messages_container

    return cosmos_messages_container.read_item(item=message_id, partition_key=conversation_id)


def _message_container():
    from config import cosmos_messages_container

    return cosmos_messages_container


def _default_workflow_run(user_id, run_id):
    from functions_personal_workflows import get_personal_workflow_run

    return get_personal_workflow_run(user_id, run_id)


def _load_current_workflow(user_id, workflow_id):
    from functions_personal_workflows import get_personal_workflow

    return get_personal_workflow(user_id, workflow_id)


def _authorize_current_workflow(workflow, actor_user_id, plan_sha256, settings, *, load_workflow=None):
    """Re-read the stored workflow so a delete or a changed plan stops the run before step 1."""
    current = (load_workflow or _load_current_workflow)(workflow.get('user_id'), workflow.get('id'))
    if not isinstance(current, dict) or current.get('deleting'):
        raise PlanReplayRefused('workflow_unavailable')
    # Imported at run admission; the runtime module imports the runner lazily, never this module.
    from functions_workflow_runtime import _authorize_execution
    from functions_workflow_runtime_store import WorkflowRuntimeConflict

    try:
        _authorize_execution(current, actor_user_id, settings)
    except WorkflowRuntimeConflict:
        raise PlanReplayRefused('workflow_unavailable') from None
    except PermissionError:
        raise PlanReplayRefused('creator_mismatch') from None
    stored = stored_plan_replay_task(current)
    if not stored or (stored.get('plan_replay') or {}).get('plan_sha256') != plan_sha256:
        raise PlanReplayRefused('plan_hash_mismatch')
    return current


def _safe_error_code(error):
    code = getattr(error, 'code', '') or ''
    if code == 'model_routing_changed':
        return 'model_unavailable'
    if code in {'context_unavailable', 'analysis_result_unavailable', 'result_unavailable', 'workflow_result_changed'}:
        return 'source_unavailable'
    return 'replay_execution_failed'


def _completed_replay_result(orch_run_id, final_record, conversation_id, read_message):
    from functions_orchestration_checkpoints import orchestration_answer_message_id

    answer_message = None
    try:
        answer_message = (read_message or _read_message)(orchestration_answer_message_id(orch_run_id), conversation_id)
    except exceptions.CosmosResourceNotFoundError:
        answer_message = None
    value = build_plan_replay_result(final_record, answer_message)
    return {
        'reply': value['final_response']['text'],
        'authoritative_result': {'kind': 'json', 'value': value},
        'plan_replay': plan_replay_run_item_projection(value),
    }


def _read_raw_run(run_id, user_id, conversation_id):
    """Read an owned orchestration run with its ETag for a conditional write, or None if absent."""
    from functions_orchestration_plan_revisions import PlanRevisionError, read_revision_run

    try:
        return read_revision_run(run_id, user_id, conversation_id)
    except PlanRevisionError as exc:
        if getattr(exc, 'code', '') == 'not_found':
            return None
        raise


def _read_prior_attempt(read_run, prior_id, prior, *, user_id, conversation_id, run_id, task_id, required=True):
    record = read_run(prior_id, user_id, conversation_id)
    if not record:
        if required:
            raise PlanReplayRefused('replay_execution_failed')
        return None
    marker = record.get('workflow_replay') if isinstance(record.get('workflow_replay'), dict) else {}
    if (
        str(record.get('user_id') or '') != str(user_id)
        or record.get('conversation_id') != conversation_id
        or marker.get('workflow_run_id') != run_id
        or marker.get('task_id') != task_id
        or marker.get('attempt') != prior
    ):
        raise PlanReplayRefused('replay_execution_failed')
    return record


def _settle_open_run(read, replace, failure_code, *, own_token=None):
    """Mark an orchestration run that no worker drives any more as failed, by CAS.

    A run whose lease is still live is returned untouched unless the lease is ``own_token``,
    the stopped worker's own: a live lease is never taken over. Returns the latest record.
    """
    from functions_orchestration_recovery import _TERMINAL, _live, _replace
    from functions_orchestration_schema import build_failure

    failure = build_failure(failure_code)
    for _ in range(8):
        record = read()
        if not record or record.get('status') in _TERMINAL:
            return record
        if _live(record) and (own_token is None or (record.get('execution_lease') or {}).get('token') != own_token):
            return record
        try:
            settled = (replace or _replace)(record, {
                'status': 'failed', 'outcome': 'failed', 'failure': failure, 'error': failure['message'],
                'execution_lease': None, 'completed_at': _iso(_utc_now()), 'recovery_version': uuid.uuid4().hex,
            })
        except exceptions.CosmosAccessConditionFailedError:
            continue
        log_event(
            '[WORKFLOW_PLAN_REPLAY] Settled a replay orchestration run no worker is driving.',
            extra={'orchestration_run_id': record.get('id'), 'failure_code': failure['code']},
            level=logging.WARNING,
        )
        return settled
    raise PlanReplayRefused('replay_execution_failed')


def _settle_stopped_attempt(
    orch_run_id, worker, failure_code, *, user_id, conversation_id, read_run, replace_record, fence,
    msg_container,
):
    """Once this attempt's worker has stopped, nothing else will finish its orchestration run.

    The orchestration scheduler leaves replay runs to the workflow, so a failed attempt settles
    its own run rather than leave it open. A worker that is still alive was asked to stop and is
    fenced; it finalizes its own run. Errors are logged so the original refusal still surfaces.
    """
    thread = worker.get('thread')
    if thread is not None and thread.is_alive():
        return
    lease = worker.get('lease')
    try:
        if lease is not None:
            lease.close()
        settled = _settle_open_run(
            partial(read_run, orch_run_id, user_id, conversation_id), replace_record, failure_code,
            own_token=getattr(lease, 'token', None),
        )
        if settled and settled.get('status') != 'completed' and not worker.get('fenced'):
            fence(settled, msg_container)
    except Exception as exc:
        log_event(
            '[WORKFLOW_PLAN_REPLAY] A stopped replay attempt could not be settled.',
            extra={'orchestration_run_id': orch_run_id, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )


def _reconcile_prior_attempts(
    *, run_id, task_id, attempt, user_id, conversation_id, plan_sha256, read_run, authorize,
    request_cancel, fence, replace_record, msg_container, check_cancelled, time_source, poll_seconds,
    reconcile_seconds,
):
    """Settle every earlier attempt of this task before the next one starts.

    A durable restart re-enters the task with the next attempt number. An earlier attempt's
    orchestration run may have completed, failed, or been left running by a worker that died.
    A completed run of the same frozen plan is adopted, not repeated. Anything still open is
    settled and fenced, so a task never has two live orchestration runs or a stale running one.
    A run whose lease is still live is asked to stop but never taken over: if it does not stop
    within one lease period, this attempt fails cleanly. Returns ``(run_id, record)`` to adopt.
    """
    from functions_orchestration_checkpoints import CheckpointError
    from functions_orchestration_plan_revisions import PlanRevisionError
    from functions_orchestration_recovery import HEARTBEAT_SECONDS, LEASE_SECONDS, RecoveryError, _TERMINAL, _live
    from functions_workflow_execution import assert_workflow_execution_owned

    bound = LEASE_SECONDS + HEARTBEAT_SECONDS if reconcile_seconds is None else reconcile_seconds
    scope = {'user_id': user_id, 'conversation_id': conversation_id, 'run_id': run_id, 'task_id': task_id}
    adopted = None
    for prior in range(max(0, int(attempt or 0))):
        prior_id = _deterministic_id('run', run_id, task_id, prior, 'run')
        try:
            record = _read_prior_attempt(read_run, prior_id, prior, required=False, **scope)
            if record is None:
                continue
            deadline = time_source() + bound
            while record.get('status') not in _TERMINAL:
                if not _live(record):
                    record = _settle_open_run(
                        partial(_read_prior_attempt, read_run, prior_id, prior, **scope),
                        replace_record, 'ownership_lost',
                    )
                    continue
                if not record.get('cancellation_requested_at'):
                    record = request_cancel(prior_id, user_id, conversation_id, authorize) or record
                    fence(record, msg_container)
                (check_cancelled or assert_workflow_execution_owned)()
                if time_source() >= deadline:
                    log_event(
                        '[WORKFLOW_PLAN_REPLAY] An earlier replay attempt still holds a live lease.',
                        extra={'workflow_run_id': run_id, 'orchestration_run_id': prior_id},
                        level=logging.WARNING,
                    )
                    raise PlanReplayRefused('replay_execution_failed')
                time.sleep(max(0.01, float(poll_seconds)))
                record = _read_prior_attempt(read_run, prior_id, prior, **scope)
            if record.get('status') == 'completed':
                if (record.get('workflow_replay') or {}).get('plan_sha256') != plan_sha256:
                    raise PlanReplayRefused('replay_execution_failed')
                adopted = (prior_id, record)
            else:
                fence(record, msg_container)
        except (CheckpointError, PlanRevisionError, RecoveryError) as exc:
            log_event(
                '[WORKFLOW_PLAN_REPLAY] An earlier replay attempt could not be settled.',
                extra={
                    'workflow_run_id': run_id, 'orchestration_run_id': prior_id,
                    'error_code': getattr(exc, 'code', ''), 'error_type': type(exc).__name__,
                },
                level=logging.WARNING,
            )
            raise PlanReplayRefused('replay_execution_failed') from exc
    return adopted


def execute_plan_replay_task(
    workflow, task, settings, *, conversation_id, run_id, actor_user_id, attempt=0,
    user_message_id=None, now=None, clock=None, max_seconds=PLAN_REPLAY_MAX_SECONDS,
    poll_seconds=PLAN_REPLAY_POLL_SECONDS, read_conversation=None, read_message=None,
    read_workflow_run=None, create_run=None, claim_run=None, prepare_execution=None,
    get_run=None, request_cancel=None, fence=None, message_container=None, load_workflow=None,
    check_cancelled=None, replace_record=None, reconcile_seconds=None, read_run=None,
):
    workflow = workflow if isinstance(workflow, dict) else {}
    task = task if isinstance(task, dict) else {}
    ctx = authorize_plan_replay_run(workflow, task, settings)
    if str(actor_user_id or '') != str(workflow.get('user_id') or ''):
        raise PlanReplayRefused('creator_mismatch')
    user_id = ctx['user_id']
    _authorize_current_workflow(workflow, actor_user_id, ctx['plan_sha256'], settings, load_workflow=load_workflow)
    replay = task['plan_replay']
    provenance = replay.get('provenance') if isinstance(replay.get('provenance'), dict) else {}
    _verify_workflow_conversation(
        workflow, conversation_id, user_id, provenance.get('source_conversation_id') or '',
        read_conversation=read_conversation,
    )
    if not user_message_id:
        workflow_run = (read_workflow_run or _default_workflow_run)(user_id, run_id) or {}
        user_message_id = workflow_run.get('user_message_id')
    if not user_message_id:
        raise PlanReplayRefused('replay_execution_failed')
    user_message = (read_message or _read_message)(user_message_id, conversation_id)
    if user_message.get('conversation_id') != conversation_id or user_message.get('role') != 'user':
        raise PlanReplayRefused('replay_execution_failed')
    from functions_orchestration_context import build_conversation_snapshot, normalize_history_message
    from functions_orchestration_workflow_context import request_local_time_line

    normalized_message = normalize_history_message(user_message)
    if not normalized_message or not normalized_message.get('fingerprint'):
        raise PlanReplayRefused('replay_execution_failed')
    schedule = workflow.get('schedule') if isinstance(workflow.get('schedule'), dict) else {}
    tz = schedule.get('timezone') or provenance.get('time_zone') or 'UTC'
    started_at = now or _utc_now()
    time_line = request_local_time_line(tz, started_at)
    request = replay['request']
    resolved_message = f'{request}\n\n{time_line}' if time_line else request
    task_id = task.get('id') or PLAN_REPLAY_TASK_NAME
    orch_run_id = _deterministic_id('run', run_id, task_id, attempt, 'run')
    plan_id = _deterministic_id('plan', run_id, task_id, attempt, 'plan')
    turn_id = _deterministic_id('turn', run_id, task_id, attempt, 'turn')
    approved_at = (replay.get('approval') or {}).get('approved_at') or _iso(started_at)
    executable_plan = build_executable_replay_plan(
        ctx['frozen_plan'], run_id=orch_run_id, plan_id=plan_id, turn_id=turn_id,
        conversation_id=conversation_id, user_id=user_id, approved_at=approved_at,
    )
    snapshot = build_conversation_snapshot([], None, turn_id=turn_id)
    from functions_orchestration_runs import create_orchestration_run, get_orchestration_run
    from functions_orchestration_plan_revisions import PlanRevisionError, claim_plan_run
    from functions_orchestration_recovery import ExecutionLease, fence_publication, request_cancellation
    from functions_orchestration_services import composition_profiles

    creator = create_run or create_orchestration_run
    claimer = claim_run or claim_plan_run
    get_record = get_run or get_orchestration_run
    read_raw = read_run or _read_raw_run
    fence_run = fence or fence_publication
    msg_container = message_container or _message_container()
    time_source = clock or time.monotonic

    def authorize():
        _verify_workflow_conversation(
            workflow, conversation_id, user_id, provenance.get('source_conversation_id') or '',
            read_conversation=read_conversation,
        )

    adopted = _reconcile_prior_attempts(
        run_id=run_id, task_id=task_id, attempt=attempt, user_id=user_id, conversation_id=conversation_id,
        plan_sha256=ctx['plan_sha256'], read_run=read_raw, authorize=authorize,
        request_cancel=request_cancel or request_cancellation, fence=fence_run,
        replace_record=replace_record, msg_container=msg_container, check_cancelled=check_cancelled,
        time_source=time_source, poll_seconds=poll_seconds, reconcile_seconds=reconcile_seconds,
    )
    if adopted is not None:
        log_event(
            '[WORKFLOW_PLAN_REPLAY] Adopted a completed earlier attempt instead of replaying again.',
            extra={'workflow_id': workflow.get('id'), 'workflow_run_id': run_id, 'orchestration_run_id': adopted[0]},
        )
        return _completed_replay_result(adopted[0], adopted[1], conversation_id, read_message)
    record = creator(
        executable_plan,
        user_id,
        conversation_id,
        idempotent=True,
        turn_context={
            'user_message': request,
            'user_message_id': user_message_id,
            'user_message_fingerprint': normalized_message['fingerprint'],
            'turn_id': turn_id,
            'seeds': ctx['frozen_seeds'],
            'resolved_message': resolved_message,
            'conversation_context': snapshot,
            'time_zone': tz,
        },
        initial_updates={'workflow_replay': {
            'workflow_id': workflow.get('id'),
            'workflow_run_id': run_id,
            'task_id': task_id,
            'plan_sha256': ctx['plan_sha256'],
            'attempt': attempt,
        }},
    )

    stopped = {}

    def settle(failure_code):
        _settle_stopped_attempt(
            orch_run_id, stopped, failure_code, user_id=user_id, conversation_id=conversation_id,
            read_run=read_raw, replace_record=replace_record, fence=fence_run, msg_container=msg_container,
        )

    try:
        claimed = claimer(
            orch_run_id, user_id, conversation_id, plan_id=plan_id, conversation_context=snapshot,
            composition_profiles=composition_profiles(), settings=settings,
        )
    except PlanRevisionError as exc:
        log_event(
            '[WORKFLOW_PLAN_REPLAY] Replay run could not be claimed.',
            extra={
                'workflow_id': workflow.get('id'), 'workflow_run_id': run_id,
                'orchestration_run_id': orch_run_id, 'error_code': getattr(exc, 'code', ''),
            },
            level=logging.WARNING,
        )
        settle('execution_interrupted')
        raise PlanReplayRefused('replay_execution_failed') from exc
    lease = ExecutionLease(claimed, authorize, message_container=msg_container)
    from functions_orchestration_execution import HarnessExecutionError, prepare_harness_execution
    from functions_workflow_execution import assert_workflow_execution_owned

    execution_error = {}

    def worker():
        try:
            execution = (prepare_execution or prepare_harness_execution)(
                claimed,
                settings=settings,
                identity_context={'user_roles': [], 'user_enable_agents': False},
                execution_identity=None,
                lease=lease,
            )
            execution.execute(emit=None)
        except BaseException as exc:
            execution_error['error'] = exc

    thread = threading.Thread(target=worker, name=f'plan-replay-{orch_run_id}', daemon=True)
    stopped.update({'thread': thread, 'lease': lease})
    thread.start()
    deadline = time_source() + max_seconds

    def cancel_and_fence():
        latest = None
        try:
            latest = (request_cancel or request_cancellation)(
                orch_run_id, user_id, conversation_id, authorize,
            )
        finally:
            try:
                fence_run(latest or record, msg_container)
                stopped['fenced'] = True
            except Exception as exc:
                log_event(
                    '[WORKFLOW_PLAN_REPLAY] Publication fence failed during cancellation.',
                    extra={'run_id': orch_run_id, 'error_type': type(exc).__name__},
                    level=logging.ERROR,
                )

    while thread.is_alive():
        thread.join(timeout=max(0.1, float(poll_seconds)))
        if not thread.is_alive():
            break
        try:
            # The runner passes its cancel check, which also asserts a durable run's lease.
            (check_cancelled or assert_workflow_execution_owned)()
        except BaseException:
            try:
                cancel_and_fence()
            finally:
                thread.join(timeout=PLAN_REPLAY_STOP_GRACE_SECONDS)
                settle('execution_interrupted')
            raise
        if time_source() >= deadline:
            try:
                cancel_and_fence()
            finally:
                thread.join(timeout=PLAN_REPLAY_STOP_GRACE_SECONDS)
                settle('run_timeout')
            raise PlanReplayRefused('replay_budget_exceeded')
    if execution_error:
        error = execution_error['error']
        code = _safe_error_code(error) if isinstance(error, HarnessExecutionError) else 'replay_execution_failed'
        log_event(
            '[WORKFLOW_PLAN_REPLAY] Replay execution failed.',
            extra={
                'workflow_id': workflow.get('id'), 'workflow_run_id': run_id,
                'orchestration_run_id': orch_run_id, 'error_code': getattr(error, 'code', ''),
                'error_type': type(error).__name__,
            },
            level=logging.ERROR,
        )
        settle('execution_interrupted')
        raise PlanReplayRefused(code) from error
    final_record = get_record(orch_run_id, user_id, conversation_id, strict=True)
    if not final_record or final_record.get('status') != 'completed':
        log_event(
            '[WORKFLOW_PLAN_REPLAY] Replay finished without completed status.',
            extra={
                'workflow_id': workflow.get('id'), 'workflow_run_id': run_id,
                'orchestration_run_id': orch_run_id,
                'status': (final_record or {}).get('status'),
                'outcome': (final_record or {}).get('outcome'),
            },
            level=logging.ERROR,
        )
        settle('execution_interrupted')
        raise PlanReplayRefused('replay_execution_failed')
    return _completed_replay_result(orch_run_id, final_record, conversation_id, read_message)


def plan_replay_run_item_projection(value):
    """The typed result the run inspector reads from the task's run item, with the answer capped."""
    projection = deepcopy(value if isinstance(value, dict) else {})
    final_response = projection.get('final_response') if isinstance(projection.get('final_response'), dict) else {}
    text = str(final_response.get('text') or '')
    projection['final_response'] = {
        'message_id': str(final_response.get('message_id') or ''),
        'text': text[:PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT],
        'truncated': len(text) > PLAN_REPLAY_RUN_ITEM_TEXT_LIMIT,
    }
    return projection


def build_plan_replay_result(record, answer_message=None):
    record = record if isinstance(record, dict) else {}
    plan = record.get('plan') if isinstance(record.get('plan'), dict) else {}
    replay = record.get('workflow_replay') if isinstance(record.get('workflow_replay'), dict) else {}
    execution_steps = {
        item.get('step_id'): item.get('status')
        for item in record.get('execution_steps') or []
        if isinstance(item, dict) and item.get('step_id')
    }
    task_step_status = {}
    task_results = record.get('task_results')
    for result in (task_results.values() if isinstance(task_results, dict) else task_results or []):
        if not isinstance(result, dict):
            continue
        producer = result.get('producer') if isinstance(result.get('producer'), dict) else {}
        step_id = result.get('step_id') or producer.get('step_id')
        if step_id and step_id not in task_step_status:
            task_step_status[step_id] = result.get('status') or 'completed'
    steps = []
    for step in _enabled_plan_steps(plan):
        step_id = step.get('step_id') or ''
        capability_id = step.get('capability_id') or ''
        steps.append({
            'step_id': step_id,
            'capability_id': capability_id,
            'label': capability_label(capability_id),
            'status': execution_steps.get(step_id) or task_step_status.get(step_id) or 'not_run',
        })
    artifacts = []
    metadata = answer_message.get('metadata') if isinstance(answer_message, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    orchestration = metadata.get('orchestration') if isinstance(metadata.get('orchestration'), dict) else {}
    for image in orchestration.get('generated_images') or []:
        if isinstance(image, dict) and image.get('visual_id'):
            artifacts.append({
                'id': str(image.get('visual_id')),
                'kind': 'image',
                'message_id': str(image.get('message_id') or ''),
            })
    for artifact in record.get('artifacts') or []:
        if not isinstance(artifact, dict):
            continue
        artifact_id = (
            artifact.get('id') or artifact.get('artifact_id') or artifact.get('result_id')
            or artifact.get('file_id') or artifact.get('blob_name')
        )
        if artifact_id:
            kind = 'image' if (artifact.get('kind') or artifact.get('type')) == 'image' else 'file'
            artifacts.append({'id': str(artifact_id), 'kind': kind})
    message_id = (answer_message or {}).get('id') if isinstance(answer_message, dict) else ''
    return {
        'contract': PLAN_REPLAY_RESULT_CONTRACT,
        'orchestration_run_id': str(record.get('id') or ''),
        'conversation_id': str(record.get('conversation_id') or ''),
        'plan_sha256': str(replay.get('plan_sha256') or ''),
        'status': str(record.get('status') or ''),
        'outcome': str(record.get('outcome') or ''),
        'steps': steps,
        'final_response': {'message_id': str(message_id or ''), 'text': str(record.get('message') or '')},
        'artifacts': artifacts,
    }
