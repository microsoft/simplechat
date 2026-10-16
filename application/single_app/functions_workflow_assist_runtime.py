# functions_workflow_assist_runtime.py
"""
The AI workflow assistant's services: the Azure-backed side of ``functions_workflow_assist``.

Version: 0.261.208
Implemented in: 0.261.208

``build_workflow_assist_services`` wires the core to:

* the stored workflow, read the way the editor loads it
* Track A2's `#` reference authorizer (``resolve_scope_references``)
* the editor options (``get_workflow_editor_options``)
* bounded document excerpts, read through ``load_workflow_reference``, which re-authorizes the document
* Phase 2's dry run (``dry_run_personal_workflow``)
* the advisory Microsoft 365 checks, which read stored records only
* the model: the draft-instructions deployment, with no new model setting
* the per-user limiter

The route supplies the model client factory, because the client reads the signed-in user from
the request and a functions module doesn't import a route module.

Nothing here writes a workflow, run or document. The limiter's document in the settings
container is the only write.
"""

import math
import time

from azure.core.exceptions import AzureError
from openai import APITimeoutError, BadRequestError, RateLimitError

from functions_appinsights import log_assist_debug, log_event
from functions_assist_diagnostics import AssistDiagnostics
from functions_workflow_alert_safety import sanitize_workflow_alert_record
from functions_workflow_assist import ASSIST_MAX_REQUEST_REFERENCES, WorkflowAssistError, WorkflowAssistServices
from functions_workflow_assist_limits import CosmosAssistLimitStore, WorkflowAssistLimiter
from functions_workflow_definitions import workflow_definition_for_editor
from functions_workflow_limits import WorkflowLoopLimitError


# The deployment families that take ``max_completion_tokens`` and no temperature. These are the
# markers ``_build_agent_instruction_api_params`` uses, so both assists classify a deployment alike.
ASSIST_COMPLETION_TOKEN_MARKERS = ('o1', 'o3', 'gpt-5')
# A reasoning model spends part of its budget thinking, so it gets more room.
ASSIST_MAX_COMPLETION_TOKENS = 16000
ASSIST_MAX_TOKENS = 4000
ASSIST_TEMPERATURE = 0.2
ASSIST_PROVIDER_RETRY_AFTER_MIN_SECONDS = 1
ASSIST_PROVIDER_RETRY_AFTER_MAX_SECONDS = 60
ASSIST_PROVIDER_RETRY_AFTER_DEFAULT_SECONDS = 10
# A model call is not started with less time than this left.
ASSIST_MIN_CALL_SECONDS = 1.0

# A Cosmos item ID cannot hold these, so a workflow ID with one names no saved workflow.
_COSMOS_ID_FORBIDDEN_CHARACTERS = frozenset('/\\?#')
# Stored M365 connection states that mean the caller isn't connected, rather than unknown.
_M365_NOT_CONNECTED_CODES = frozenset({'m365_connection_required', 'm365_connection_binding_changed'})
# ``resolve_scope_references`` refusals that aren't about one unusable document.
_REFERENCE_REASON_CODES = {
    'too_many': 'reference_limit',
    'invalid_reference': 'invalid_request',
    'unsupported_kind': 'invalid_request',
    'verification_failed': 'reference_check_failed',
}


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def assist_model_parameters(model_name, messages, *, json_mode=True):
    """Chat-completion parameters for one assistant turn."""
    parameters = {'model': model_name, 'messages': messages}
    if any(marker in str(model_name or '').lower() for marker in ASSIST_COMPLETION_TOKEN_MARKERS):
        parameters['max_completion_tokens'] = ASSIST_MAX_COMPLETION_TOKENS
    else:
        parameters['max_tokens'] = ASSIST_MAX_TOKENS
        parameters['temperature'] = ASSIST_TEMPERATURE
    if json_mode:
        parameters['response_format'] = {'type': 'json_object'}
    return parameters


def _provider_error_code(exc):
    body = getattr(exc, 'body', None)
    detail = body.get('error', body) if isinstance(body, dict) else None
    code = detail.get('code') if isinstance(detail, dict) else getattr(exc, 'code', None)
    return str(code or '').strip().lower()


def _provider_retry_after(exc):
    """The provider's ``Retry-After`` in whole seconds, clamped, or the default."""
    headers = getattr(getattr(exc, 'response', None), 'headers', None)
    if headers is not None:
        for name, scale in (('retry-after-ms', 0.001), ('retry-after', 1.0)):
            try:
                seconds = float(headers.get(name)) * scale
            except (TypeError, ValueError):
                continue
            if math.isfinite(seconds):
                return int(min(max(math.ceil(seconds), ASSIST_PROVIDER_RETRY_AFTER_MIN_SECONDS),
                               ASSIST_PROVIDER_RETRY_AFTER_MAX_SECONDS))
    return ASSIST_PROVIDER_RETRY_AFTER_DEFAULT_SECONDS


def provider_error(exc):
    """The ``WorkflowAssistError`` for a failed model call. The provider's text is never passed on."""
    # A timeout is also a connection error, so it is checked first.
    if isinstance(exc, APITimeoutError):
        return WorkflowAssistError('assistant_timeout')
    if isinstance(exc, RateLimitError):
        return WorkflowAssistError('assistant_unavailable', retry_after=_provider_retry_after(exc))
    if isinstance(exc, BadRequestError):
        code = _provider_error_code(exc)
        if code == 'context_length_exceeded':
            return WorkflowAssistError('assistant_input_too_large')
        if code in ('content_filter', 'content_policy_violation'):
            return WorkflowAssistError('assistant_refused')
    return WorkflowAssistError('assistant_unavailable')


def model_reply(response):
    """``(content, finish_reason)`` from a chat completion; a refusal reads as ``content_filter``."""
    choices = getattr(response, 'choices', None) or []
    if not choices:
        return None, None
    choice = choices[0]
    message = getattr(choice, 'message', None)
    if getattr(message, 'refusal', None):
        return None, 'content_filter'
    return getattr(message, 'content', None), getattr(choice, 'finish_reason', None)


def is_json_mode_rejection(exc):
    """True when the deployment refused the ``response_format`` option itself."""
    if not isinstance(exc, BadRequestError):
        return False
    # Lazy: model_endpoint_clients loads Semantic Kernel. The app has already loaded it, and a
    # refused request is the only place the shared classifier is needed.
    from model_endpoint_clients import is_response_format_rejection
    return is_response_format_rejection(exc)


class WorkflowAssistModel:
    """The core's ``call_model``: one attempt per call, bounded by the time the core allows.

    ``client_factory()`` returns ``(client, model_name)``; it runs on the first call, so a model
    that isn't configured fails at the model step, inside the request's telemetry. JSON mode is
    asked for, and dropped for the rest of the request when the deployment refuses it.
    """

    def __init__(self, client_factory, *, clock=time.monotonic, diagnostics=None):
        self._client_factory = client_factory
        self._clock = clock
        self._client = None
        self._model_name = None
        self._json_mode = True
        self._diagnostics = diagnostics or AssistDiagnostics()
        self._provider_calls = 0

    def _ready_client(self):
        if self._client is None:
            try:
                client, model_name = self._client_factory()
            except Exception as exc:
                self._diagnostics.emit('provider_failed', assist_stage='model', assist_code='assistant_unavailable')
                raise WorkflowAssistError('assistant_unavailable') from exc
            self._client, self._model_name = client, model_name
        return self._client

    def __call__(self, messages, timeout):
        client = self._ready_client()
        deadline = self._clock() + timeout
        while True:
            remaining = deadline - self._clock()
            if remaining < ASSIST_MIN_CALL_SECONDS:
                raise WorkflowAssistError('assistant_timeout')
            parameters = assist_model_parameters(self._model_name, messages, json_mode=self._json_mode)
            started = self._clock()
            self._provider_calls += 1
            try:
                response = client.with_options(timeout=remaining, max_retries=0).chat.completions.create(**parameters)
            except Exception as exc:
                if self._json_mode and is_json_mode_rejection(exc):
                    self._diagnostics.emit('json_mode_fallback', assist_stage='model', json_mode=True,
                                           provider_status=getattr(exc, 'status_code', None),
                                           provider_attempt=self._provider_calls)
                    self._json_mode = False
                    continue
                error = provider_error(exc)
                self._diagnostics.emit('provider_failed', assist_stage='model', assist_code=error.code,
                                       provider_status=getattr(exc, 'status_code', None), json_mode=self._json_mode,
                                       provider_attempt=self._provider_calls,
                                       provider_duration_ms=int((self._clock() - started) * 1000))
                raise error from exc
            self._diagnostics.emit('provider_finished', assist_stage='model', json_mode=self._json_mode,
                                   provider_attempt=self._provider_calls,
                                   provider_duration_ms=int((self._clock() - started) * 1000))
            content, finish_reason = model_reply(response)
            # Export only closed finish categories and numeric usage, never model/prompt contents.
            usage = getattr(response, 'usage', None)
            log_event('[WORKFLOW_ASSIST] Model response received', extra={
                'output_code': finish_reason if finish_reason in (
                    'stop', 'length', 'content_filter', 'tool_calls',
                ) else 'unknown',
                'input_count': getattr(usage, 'prompt_tokens', None),
                'output_count': getattr(usage, 'completion_tokens', None),
                'total_count': getattr(usage, 'total_tokens', None),
                'json_mode': self._json_mode,
            })
            return content, finish_reason


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def read_workflow_base(container, user_id, workflow_id, *, group_id=""):
    """The caller's saved workflow as the editor loads it (``get_personal_workflow``), or None.

    Unlike ``get_personal_workflow``, a store failure raises 503 instead of reading as "not found",
    so an outage never looks like a missing workflow.
    """
    if any(character in _COSMOS_ID_FORBIDDEN_CHARACTERS for character in workflow_id):
        return None
    try:
        item = container.read_item(item=workflow_id, partition_key=group_id or user_id)
    except AzureError as exc:
        if getattr(exc, 'status_code', None) in (400, 404):
            return None
        raise WorkflowAssistError('assistant_unavailable') from exc
    if not isinstance(item, dict):
        return None
    if group_id and item.get('group_id') != group_id:
        return None
    cleaned = {key: value for key, value in item.items() if not str(key).startswith('_')}
    return workflow_definition_for_editor(sanitize_workflow_alert_record(cleaned))


def reference_error(exc):
    """The ``WorkflowAssistError`` for a refused `#` reference.

    For a document the caller can't use, the authorizer's own message is kept: it's
    server-authored and names only the label the caller picked.
    """
    reason = getattr(exc, 'reason', None)
    if reason in _REFERENCE_REASON_CODES:
        return WorkflowAssistError(_REFERENCE_REASON_CODES[reason])
    message = getattr(exc, 'message', None)
    return WorkflowAssistError('reference_unavailable', message if isinstance(message, str) and message else None)


def excerpt_reference(identity):
    """A ``reference_inputs`` entry for reading one document's text through ``load_workflow_reference``."""
    scope_type, scope_id, document_id = identity
    return {
        'id': 'excerpt', 'name': 'excerpt', 'document_id': document_id,
        'scope_type': scope_type, 'scope_id': scope_id,
    }


def build_workflow_assist_services(settings, *, client_factory, group_id="", user_info=None, instruction=""):
    """The real services for one assist request.

    ``settings`` are the raw app settings; they stay on the server. ``client_factory()`` returns
    ``(client, model_name)`` for the draft-instructions deployment.
    """
    # Lazy: these modules import config, which connects to Cosmos at import. Loading them here
    # keeps the model invoker and the adapters above importable in tests.
    from config import TENANT_ID, cosmos_personal_workflows_container, cosmos_settings_container
    from functions_m365_connections import get_m365_connection_service
    # The M365 runtime's own source classification, so the warning matches what a run allows.
    from functions_m365_runtime import _manifest_sources, workflow_m365_manifests
    from functions_orchestration_context import ScopeReferenceError, resolve_scope_references
    from functions_workflow_bindings import load_workflow_reference
    from functions_workflow_drafts import dry_run_personal_workflow
    from functions_workflow_editor import get_workflow_editor_options

    if group_id:
        # Group stores and membership services are needed only for authorized group requests.
        from config import cosmos_group_workflows_container
        from functions_group import assert_group_role
        from functions_settings import get_group_workflow_management_roles
        from functions_workflow_drafts import dry_run_group_workflow

    def authorize(user_id):
        if group_id:
            assert_group_role(user_id, group_id, allowed_roles=get_group_workflow_management_roles(settings))

    def read_base(user_id, workflow_id):
        authorize(user_id)
        container = cosmos_group_workflows_container if group_id else cosmos_personal_workflows_container
        return read_workflow_base(container, user_id, workflow_id, group_id=group_id)

    def resolve_references(user_id, references):
        authorize(user_id)
        if group_id and any(
            reference.get('scope', {}).get('kind') != 'group'
            or reference.get('scope', {}).get('id') != group_id for reference in references
        ):
            raise WorkflowAssistError('reference_unavailable')
        try:
            return resolve_scope_references(references, user_id, settings, limit=ASSIST_MAX_REQUEST_REFERENCES)
        except ScopeReferenceError as exc:
            raise reference_error(exc) from exc

    def load_options(user_id):
        authorize(user_id)
        try:
            options = (
                get_workflow_editor_options(user_id, settings, group_id=group_id)
                if group_id else get_workflow_editor_options(user_id, settings)
            )
            if instruction and not group_id and settings.get('enable_collaborative_conversations') is True:
                from functions_workflow_editor import workflow_result_recipient_choices

                options['results_delivery']['recipient_choices'] = workflow_result_recipient_choices(
                    user_id, instruction=instruction,
                )
            return options
        except AzureError as exc:
            raise WorkflowAssistError('assistant_unavailable') from exc

    def load_excerpt(user_id, identity):
        authorize(user_id)
        if group_id and identity[:2] != ('group', group_id):
            raise WorkflowAssistError('reference_unavailable')
        loaded = load_workflow_reference(
            {'user_id': user_id, 'group_id': group_id}, excerpt_reference(identity), actor_user_id=user_id,
        )
        return loaded.get('text') if isinstance(loaded, dict) else None

    def dry_run(user_id, payload):
        authorize(user_id)
        try:
            if group_id:
                return dry_run_group_workflow(
                    group_id, payload, user_id, user_info=user_info or {}, settings=settings,
                )
            return dry_run_personal_workflow(user_id, payload, actor_user_id=user_id, settings=settings)
        except (WorkflowLoopLimitError, AzureError) as exc:
            raise WorkflowAssistError('assistant_unavailable') from exc

    def agent_email_capable(user_id, agent):
        authorize(user_id)
        actions, _fingerprint_workflow = workflow_m365_manifests({
            'user_id': user_id, 'group_id': group_id, 'selected_agent': agent, 'tasks': [],
        })
        return any('email' in _manifest_sources(action) for action in actions)

    def m365_connected(user_id):
        try:
            connection = get_m365_connection_service().current_connection(user_id, TENANT_ID)
        except Exception as exc:
            if getattr(exc, 'code', None) in _M365_NOT_CONNECTED_CODES:
                return False
            raise
        return isinstance(connection, dict) and connection.get('status') == 'connected'

    def log(message, extra, level):
        log_event(message, extra=extra, level=level)

    diagnostics = AssistDiagnostics(log_assist_debug)
    return WorkflowAssistServices(
        limiter=WorkflowAssistLimiter(CosmosAssistLimitStore(cosmos_settings_container)),
        read_base=read_base,
        resolve_references=resolve_references,
        load_options=load_options,
        load_excerpt=load_excerpt,
        call_model=WorkflowAssistModel(client_factory, diagnostics=diagnostics),
        dry_run=dry_run,
        agent_email_capable=agent_email_capable,
        m365_connected=m365_connected,
        log=log,
        diagnostics=diagnostics,
        group_id=group_id,
    )
