# functions_orchestration_m365.py
"""Microsoft 365 for orchestration action and agent steps.

Each action or agent step runs in its own request context, the execution identity's
bridge. Classic chat and workflows install a Microsoft 365 execution context on their own
request, so a bridge never had one: every Microsoft 365 function refused the call with
``m365_context_required`` before reaching Microsoft Graph, and the step still reported
completed. ``action_step_scope`` installs a context for one approved action step, and
``agent_step_scope`` one for an approved agent step whose agent loads Microsoft 365
actions. The helpers here turn Microsoft 365 sign-in, approval and policy refusals into
application-owned step failures, instead of findings the model reports as data.

SharePoint and OneDrive file functions also need the model's token budget, and deeper file
analysis needs a model. Chat supplies both through the selected agent. An action step has no
agent, so ``file_step_filter`` binds the step's own model around each of its function calls.

Version: 0.261.321
Implemented in: 0.261.238
Agent steps get their own Microsoft 365 scope in: 0.261.270
File action steps get their model's token budget and analysis model in: 0.261.300
Explicit operation intent preserves configured write policies in: 0.261.321
"""

import hashlib
import json
import logging
import uuid
from contextlib import contextmanager

from functions_appinsights import log_event
from functions_m365_approvals import M365ApprovalRequired, M365PolicyError
from functions_m365_operations import M365_ACTION_DEFINITIONS, M365_FILE_SOURCES, M365_PLUGIN_TYPES, M365_SOURCES
from functions_msgraph_operations import MSGRAPH_PLUGIN_TYPE
from m365_interaction import M365_AUTH_INTERACTION_CODES


M365_STEP_ACTION_TYPES = frozenset({*M365_PLUGIN_TYPES, MSGRAPH_PLUGIN_TYPE})
_FILE_ACTION_SOURCES = {
    action_type: definition['source'] for action_type, definition in M365_ACTION_DEFINITIONS.items()
    if definition['source'] in M365_FILE_SOURCES
}
_APPROVAL_CODES = frozenset({'m365_approval_required', 'm365_approval_pending'})
# Function-result codes that stop a step: no later call can succeed until the user acts.
_RESULT_STOP_CODES = frozenset({'execution_context_required', 'source_not_authorized', 'token_acquisition_failed'})
# The step's model can't bound file content: its token limits are missing or unusable.
_MODEL_LIMIT_CODES = frozenset({
    'model_context_unavailable', 'model_generation_unbounded', 'model_input_estimate_unavailable',
    'model_context_invalid', 'model_tool_configuration_invalid',
})
# Retained file evidence couldn't be stored or read safely for this conversation and request.
_EVIDENCE_CODES = frozenset({
    'memory_unavailable', 'memory_access_denied', 'memory_context_mismatch', 'memory_busy',
    'memory_recovery_required', 'request_memory_binding_required', 'request_memory_mismatch',
    'request_memory_busy', 'invalid_request_memory', 'invalid_model_budget',
    'm365_continuation_unavailable',
})


class OrchestrationM365Error(RuntimeError):
    """Stops a step with an application-owned Microsoft 365 failure.

    ``failure_from_exception`` reads ``orchestration_failure_code`` and ``m365_sources``.
    ``m365_code`` is the stable Microsoft 365 reason, logged for diagnostics only.
    """

    def __init__(self, failure_code, *, m365_code=None, sources=(), approval_id=None):
        super().__init__('A Microsoft 365 step could not continue.')
        self.orchestration_failure_code = failure_code
        self.m365_code = m365_code if isinstance(m365_code, str) else None
        self.m365_sources = tuple(sorted({source for source in sources or () if source in M365_SOURCES}))
        self.approval_id = approval_id if isinstance(approval_id, str) and approval_id else None


def failure_code(m365_code):
    """The orchestration failure for a stable Microsoft 365 refusal code."""
    if m365_code == 'm365_session_required':
        return 'external_session_required'
    if m365_code == 'm365_shared_conversation_unsupported':
        return 'm365_shared_conversation'
    if m365_code == 'm365_read_only_step':
        return 'm365_read_only'
    if m365_code in M365_AUTH_INTERACTION_CODES:
        return 'm365_sign_in_required'
    if m365_code in _APPROVAL_CODES:
        return 'm365_approval_required'
    if m365_code in _MODEL_LIMIT_CODES:
        return 'm365_model_limits_required'
    if m365_code in _EVIDENCE_CODES:
        return 'm365_evidence_unavailable'
    return 'm365_unavailable'


def step_error(error, *, sources=()):
    """The step stop for a Microsoft 365 policy, sign-in or approval refusal."""
    if isinstance(error, OrchestrationM365Error):
        return error
    code = getattr(error, 'code', None)
    code = code if isinstance(code, str) else None
    payload = getattr(error, 'payload', None)
    payload = payload if isinstance(payload, dict) else {}
    reported = payload.get('sources')
    sources = [*sources, *(reported if isinstance(reported, list) else []), payload.get('source')]
    if isinstance(error, M365ApprovalRequired):
        return OrchestrationM365Error(
            'm365_approval_required', m365_code=code, sources=sources, approval_id=error.approval_id,
        )
    return OrchestrationM365Error(failure_code(code), m365_code=code, sources=sources)


def _stops_step(code):
    return (
        code in M365_AUTH_INTERACTION_CODES or code in _APPROVAL_CODES or code in _RESULT_STOP_CODES
        or code in _MODEL_LIMIT_CODES or code in _EVIDENCE_CODES
        or code.startswith('m365_')
    )


def result_refusal(value):
    """The step stop for a Microsoft 365 function result that refused its call, or None.

    Ordinary Microsoft Graph outcomes, such as nothing found or throttling, stay data that
    the model reports, as do bounded-coverage limits. Sign-in, approval and authorization
    refusals stop the step, and so do model-budget and conversation-evidence failures: they
    describe the application, not the user's data.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    error = value.get('error')
    code = error.get('code') if isinstance(error, dict) else error
    if not isinstance(code, str) or not _stops_step(code):
        return None
    reported = value.get('sources')
    sources = [*(reported if isinstance(reported, list) else []), value.get('source')]
    return OrchestrationM365Error(failure_code(code), m365_code=code, sources=sources)


def is_m365_action_manifest(manifest):
    return isinstance(manifest, dict) and manifest.get('type') in M365_STEP_ACTION_TYPES


def m365_file_source(manifest):
    """The file source, ``onedrive`` or ``spo``, of a Microsoft 365 file action, or None."""
    return _FILE_ACTION_SOURCES.get(manifest.get('type')) if isinstance(manifest, dict) else None


@contextmanager
def file_step_model_limits(source):
    """Stop a file step whose model's token limits can't bound file content.

    The stop keeps the model-budget code for diagnostics and names the step's file source.
    The step's Microsoft 365 scope logs it as it leaves.
    """
    from functions_model_capabilities import ModelTokenBudgetError

    try:
        yield
    except ModelTokenBudgetError as error:
        raise OrchestrationM365Error(
            failure_code(error.code), m365_code=error.code, sources=(source,),
        ) from error


def file_step_filter(context, *, service, model_token_budget, tool_schemas, source):
    """The auto function-invocation filter one SharePoint or OneDrive action step needs.

    File functions bound the content they return by the model's token budget, and deeper
    file analysis needs a model. Chat supplies both through the selected agent. An action
    step has none, so before 0.261.300 every file read was refused with
    ``model_context_unavailable`` and the step still completed. The step's own model must
    have verified token limits: without them the step stops here, before its model or
    Microsoft Graph is called.
    """
    # Continuation loads Semantic Kernel and conversation memory; only a file step needs it.
    from functions_m365_agent_continuation import m365_step_model_binder
    from functions_model_capabilities import ModelTokenBudget, ModelTokenBudgetError

    with file_step_model_limits(source):
        if not isinstance(model_token_budget, ModelTokenBudget):
            raise ModelTokenBudgetError('model_context_unavailable', "The step's model has no token budget.")
        model_token_budget.remaining_input(0)
    try:
        binder = m365_step_model_binder(
            context, service=service, model_token_budget=model_token_budget, tool_schemas=tool_schemas,
        )
    except M365PolicyError as error:
        raise step_error(error, sources=(source,)) from error

    async def bind_step_model(invocation, next):
        history = getattr(invocation, 'chat_history', None)
        with binder(history.messages if history is not None else ()):
            await next(invocation)

    return bind_step_model


def step_request_id(request_key):
    """A stable request id for one plan step, shared by its retries, so an approval carries over."""
    if not isinstance(request_key, str) or not request_key:
        return f'orch-{uuid.uuid4().hex}'
    digest = hashlib.sha256(f'orchestration-m365-step\x00{request_key}'.encode('utf-8')).hexdigest()
    return f'orch-{digest[:48]}'


def _log_stop(error, capability_id):
    log_event(
        '[ORCHESTRATION_M365] A Microsoft 365 step stopped.',
        level=logging.WARNING,
        extra={
            'failure_code': error.orchestration_failure_code,
            'authority_reason': error.m365_code,
            'capability_id': capability_id,
            'source_count': len(error.m365_sources),
        },
    )


@contextmanager
def _step_scope(*, user_id, conversation_id, request_key, selection, origin):
    # The runtime owns Cosmos, the tenant and conversation access, so it loads only for a
    # Microsoft 365 step.
    from functions_m365_runtime import step_m365_context

    try:
        with step_m365_context(
            user_id=user_id, conversation_id=conversation_id,
            request_id=step_request_id(request_key), selection=selection, origin=origin,
        ) as context:
            yield context
    except OrchestrationM365Error as error:
        _log_stop(error, origin.get('capability_id'))
        raise
    except M365PolicyError as error:
        stop = step_error(error)
        _log_stop(stop, origin.get('capability_id'))
        raise stop from error


def action_step_scope(
    action_ref, *, user_id, conversation_id, request_key, user_groups=None, origin=None,
    execution_intent='gather',
):
    """Authorize one approved Microsoft 365 action step, selecting only that action."""
    selection = {
        'kind': 'action', 'action_ref': action_ref,
        'user_groups': [group for group in user_groups or () if isinstance(group, str)],
        'execution_intent': execution_intent,
    }
    return _step_scope(
        user_id=user_id, conversation_id=conversation_id, request_key=request_key,
        selection=selection, origin={**(origin or {}), 'capability_id': 'action_invoke'},
    )


def agent_loads_actions(agent):
    """Whether an agent step could need a Microsoft 365 scope: only an agent that loads actions."""
    actions = agent.get('actions_to_load') if isinstance(agent, dict) else None
    return isinstance(actions, list) and any(isinstance(action, str) and action for action in actions)


def agent_step_scope(agent, *, user_id, conversation_id, request_key, origin=None, execution_intent='gather'):
    """Authorize one approved agent step's Microsoft 365 actions, selecting only that agent's.

    The agent's actions and their overrides resolve from current storage as a chat-selected
    agent's do. An agent that loads no Microsoft 365 action gets no context.
    """
    selection = {
        'kind': 'agent',
        'execution_intent': execution_intent,
        'agent': {
            key: agent.get(key) for key in ('id', 'name', 'is_global', 'is_group', 'group_id')
            if isinstance(agent, dict) and key in agent
        },
    }
    return _step_scope(
        user_id=user_id, conversation_id=conversation_id, request_key=request_key,
        selection=selection, origin={**(origin or {}), 'capability_id': 'agent_invoke'},
    )
