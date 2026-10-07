# functions_editor_assist_runtime.py
"""
The agent and action editor assistant's services: the Azure-backed side of ``functions_editor_assist``.

Version: 0.261.278
Implemented in: 0.261.278

``build_editor_assist_services`` wires the core to the draft-instructions model deployment, through
the workflow assistant's model invoker, and to a per-user limiter whose lease documents are kept
apart from the workflow assistant's. The route supplies the model client factory, because the
client reads the signed-in user from the request.

Nothing here writes an agent, action or document. The limiter's document in the settings
container is the only write.
"""

import json
import logging

from flask import current_app, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from functions_appinsights import log_event
from functions_editor_assist import (
    EDITOR_ASSIST_MAX_BODY_BYTES,
    EditorAssistError,
    EditorAssistServices,
    parse_editor_assist_body,
)
from functions_workflow_assist import WorkflowAssistError
from functions_workflow_assist_runtime import WorkflowAssistModel


EDITOR_ASSIST_LIMIT_DOCUMENT_TYPE = 'editor_assist_rate_limit'
# Fields the route reads to authorize the request; the core never sees them.
EDITOR_ASSIST_SCOPE_FIELDS = ('scope', 'group_id')


class _ConvertingLimiter:
    """The shared limiter, with its errors converted to ``EditorAssistError``."""

    def __init__(self, limiter):
        self._limiter = limiter

    def acquire(self, user_id):
        try:
            return self._limiter.acquire(user_id)
        except WorkflowAssistError as exc:
            raise EditorAssistError.from_assist_error(exc) from exc

    def release(self, lease, refund=False):
        return self._limiter.release(lease, refund=refund)


class _ConvertingModel:
    """The workflow assistant's model invoker, with its errors converted to ``EditorAssistError``."""

    def __init__(self, model):
        self._model = model

    def __call__(self, messages, timeout):
        try:
            return self._model(messages, timeout)
        except WorkflowAssistError as exc:
            raise EditorAssistError.from_assist_error(exc) from exc


def build_editor_assist_services(*, client_factory, limiter=None):
    """The real services for one editor assist request.

    ``client_factory()`` returns ``(client, model_name)`` for the draft-instructions deployment.
    """
    if limiter is None:
        # Lazy: config connects to Cosmos at import, so tests can build the adapters without it.
        from config import cosmos_settings_container
        from functions_workflow_assist_limits import CosmosAssistLimitStore, WorkflowAssistLimiter
        limiter = WorkflowAssistLimiter(
            CosmosAssistLimitStore(cosmos_settings_container),
            document_type=EDITOR_ASSIST_LIMIT_DOCUMENT_TYPE,
        )

    def log(message, extra, level):
        log_event(message, extra=extra, level=level)

    return EditorAssistServices(
        limiter=_ConvertingLimiter(limiter),
        call_model=_ConvertingModel(WorkflowAssistModel(client_factory)),
        log=log,
    )


def read_editor_assist_body():
    """The request body as strict JSON. A body that declares too many bytes is refused unread."""
    if not request.is_json:
        raise EditorAssistError('invalid_request', 'The request body must be a JSON object.')
    declared = request.content_length
    if declared is not None and declared > EDITOR_ASSIST_MAX_BODY_BYTES:
        raise EditorAssistError('request_too_large')
    try:
        raw = (
            request.get_data(cache=False)
            if declared is not None
            else request.stream.read(EDITOR_ASSIST_MAX_BODY_BYTES + 1)
        )
    except RequestEntityTooLarge:
        raise EditorAssistError('request_too_large') from None
    except BadRequest:
        raise EditorAssistError('invalid_request', 'The request body must be a JSON object.') from None
    return parse_editor_assist_body(raw)


def editor_assist_response(payload, status, *, retry_after=None, user_id=None):
    """The answer as strict JSON, never cached, because it carries the caller's draft."""
    try:
        body = json.dumps(payload, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError, RecursionError) as exc:
        log_event(
            '[EditorAssist] Assist response could not be serialized',
            extra={'user_id': user_id, 'status': status, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        failure = EditorAssistError('assistant_failed')
        body = json.dumps(failure.payload(), allow_nan=False, sort_keys=True)
        status, retry_after = failure.status, None
    response = current_app.response_class(f'{body}\n', status=status, mimetype='application/json')
    response.headers['Cache-Control'] = 'no-store, private'
    if retry_after is not None:
        response.headers['Retry-After'] = str(retry_after)
    return response


def editor_assist_error_response(error, *, settings=None, user_id=None):
    """The JSON response for an ``EditorAssistError``."""
    return editor_assist_response(
        error.payload(settings), error.status, retry_after=error.retry_after, user_id=user_id,
    )


def split_editor_assist_scope(body):
    """Remove and return ``(scope, group_id)`` from the request body.

    The route authorizes on these; the core rejects unknown keys, so they must not reach it.
    """
    if not isinstance(body, dict):
        raise EditorAssistError('invalid_request', 'The request body must be a JSON object.')
    scope = body.pop('scope', 'personal')
    group_id = body.pop('group_id', None)
    if scope not in ('personal', 'group', 'global'):
        raise EditorAssistError('invalid_request', 'The workspace scope is not valid.')
    if group_id is not None and (not isinstance(group_id, str) or not group_id.strip() or len(group_id) > 200):
        raise EditorAssistError('invalid_request', 'The group is not valid.')
    if scope != 'group':
        group_id = None
    return scope, group_id


def is_session_admin(user):
    """Whether the signed-in session user holds the app Admin role."""
    roles = (user or {}).get('roles') or []
    return isinstance(roles, (list, tuple)) and 'Admin' in roles


def authorize_group_editor_scope(user_id, group_id, *, write_roles, available):
    """Resolve the group the caller edits in, or raise ``scope_forbidden`` / ``scope_not_found``.

    ``available`` is ``(bool, reason)`` from the surface's availability predicate. A named group
    authorizes the caller's role in THAT group; with none, the active group is used.
    """
    is_available, _reason = available
    if not is_available:
        raise EditorAssistError('scope_forbidden')
    from functions_agent_delegation import resolve_delegation_group_scope
    try:
        return resolve_delegation_group_scope(user_id, group_id, allowed_roles=write_roles)
    except LookupError:
        raise EditorAssistError('scope_not_found') from None
    except (PermissionError, ValueError):
        raise EditorAssistError('scope_forbidden') from None


def handle_editor_assist_request(*, kind, user_id, settings, authorize, client_factory):
    """Run one editor assist request end to end and return the Flask response.

    ``authorize(scope, group_id)`` raises ``EditorAssistError`` when the caller cannot edit
    ``kind`` items in that scope. Nothing is saved: the answer is a candidate draft for review.
    """
    from functions_editor_assist import run_editor_assist

    try:
        body = read_editor_assist_body()
        scope, group_id = split_editor_assist_scope(body)
        authorize(scope, group_id)
        services = build_editor_assist_services(client_factory=client_factory)
        result = run_editor_assist(body, kind=kind, scope=scope, user_id=user_id, services=services)
    except EditorAssistError as exc:
        return editor_assist_error_response(exc, settings=settings, user_id=user_id)
    except Exception as exc:
        log_event(
            '[EditorAssist] Assist request failed before the assistant ran',
            extra={'user_id': user_id, 'kind': kind, 'error_type': type(exc).__name__},
            level=logging.ERROR,
        )
        return editor_assist_error_response(EditorAssistError('assistant_failed'), user_id=user_id)
    return editor_assist_response(result, 200, user_id=user_id)
