# functions_orchestration_m365.py
"""Microsoft 365 for orchestration action steps.

Each action step runs in its own request context, the execution identity's bridge. Classic
chat and workflows install a Microsoft 365 execution context on their own request, so a
bridge never had one: every Microsoft 365 function refused the call with
``m365_context_required`` before reaching Microsoft Graph, and the step still reported
completed. ``action_step_scope`` installs a context for one approved action step. The
helpers here turn Microsoft 365 sign-in, approval and policy refusals into
application-owned step failures, instead of findings the model reports as data.

Agent steps need no scope: a plan runs only Foundry agents, whose tools run in Foundry,
and refuses local agents, the only agents that load Microsoft 365 actions.

Version: 0.261.236
Implemented in: 0.261.236
"""

import hashlib
import json
import logging
import uuid
from contextlib import contextmanager

from functions_appinsights import log_event
from functions_m365_approvals import M365ApprovalRequired, M365PolicyError
from functions_m365_operations import M365_PLUGIN_TYPES, M365_SOURCES
from functions_msgraph_operations import MSGRAPH_PLUGIN_TYPE
from m365_interaction import M365_AUTH_INTERACTION_CODES


M365_STEP_ACTION_TYPES = frozenset({*M365_PLUGIN_TYPES, MSGRAPH_PLUGIN_TYPE})
_APPROVAL_CODES = frozenset({'m365_approval_required', 'm365_approval_pending'})
# Function-result codes that stop a step: no later call can succeed until the user acts.
_RESULT_STOP_CODES = frozenset({'execution_context_required', 'source_not_authorized', 'token_acquisition_failed'})


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
        or code.startswith('m365_')
    )


def result_refusal(value):
    """The step stop for a Microsoft 365 function result that refused its call, or None.

    Ordinary Microsoft Graph outcomes, such as nothing found or throttling, stay data that
    the model reports. Sign-in, approval and authorization refusals stop the step.
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


def action_step_scope(action_ref, *, user_id, conversation_id, request_key, user_groups=None, origin=None):
    """Authorize one approved Microsoft 365 action step, selecting only that action."""
    selection = {
        'kind': 'action', 'action_ref': action_ref,
        'user_groups': [group for group in user_groups or () if isinstance(group, str)],
    }
    return _step_scope(
        user_id=user_id, conversation_id=conversation_id, request_key=request_key,
        selection=selection, origin={**(origin or {}), 'capability_id': 'action_invoke'},
    )
