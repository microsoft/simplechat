# functions_orchestration_directory_readiness.py
"""Whether the application can read Microsoft Entra ID for orchestration's external sources.

Version: 0.261.204
Implemented in: 0.261.204

Before Chat Orchestration uses or reuses web, linked-page, deep-research, agent or action
results, it rereads the requesting user's account and app-role assignments from Microsoft
Graph with the application's own identity. That read needs the Microsoft Graph
Directory.Read.All application permission with administrator consent. Without it, every
such step fails for every user, however their roles are assigned.

This module owns the application's Graph token source for those reads, the check the admin
settings page runs for the signed-in administrator, and the notifier that tells
administrators when live requests are refused. No token, directory response or exception
text leaves it.
"""

import logging
import re
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

import requests

import functions_authentication as authentication
from functions_appinsights import log_event
from functions_orchestration_directory_access import (
    DIRECTORY_GATED_CAPABILITIES,
    DIRECTORY_PERMISSION_MISSING,
    DIRECTORY_SIGN_IN_FAILED,
    GRAPH_DIRECTORY_PERMISSION,
    GRAPH_DIRECTORY_PERMISSION_ID,
    GRAPH_RESOURCE_APP_ID,
)
from functions_orchestration_registry import (
    CAPABILITY_WEB_SEARCH,
    CapabilityResolutionError,
    get_capability,
    resolve_available_capability_ids,
)
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_results import ResultUnavailableError


LOG_TAG = '[ORCHESTRATION_DIRECTORY]'
ADMIN_SETTINGS_LINK = '/admin/settings#chat-orchestration'

STATUS_NOT_REQUIRED = 'not_required'
STATUS_READY = 'ready'
STATUS_PERMISSION_MISSING = 'permission_missing'
STATUS_SIGN_IN_FAILED = 'sign_in_failed'
STATUS_UNVERIFIED = 'unverified'

# Microsoft Entra ID refusing the client-credential sign-in itself. None of these can be
# fixed by retrying or by an interactive prompt; an administrator has to act.
_SIGN_IN_REFUSALS = frozenset({
    'invalid_client', 'invalid_grant', 'unauthorized_client', 'invalid_scope',
    'access_denied', 'consent_required', 'interaction_required',
})
# Decisions about the signed-in administrator. Reaching one proves the directory was read.
_USER_DECISIONS = frozenset({
    'external_identity_role_required', 'external_identity_role_unavailable',
    'external_identity_account_unavailable', 'external_identity_access_restricted',
})
_DIRECTORY_STATUSES = {
    DIRECTORY_PERMISSION_MISSING: STATUS_PERMISSION_MISSING,
    DIRECTORY_SIGN_IN_FAILED: STATUS_SIGN_IN_FAILED,
}
_SAFE_CODE = re.compile(r'[a-z][a-z0-9_]{0,79}\Z')
_GUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z', re.IGNORECASE)
_PROBE_CONVERSATION_ID = 'orchestration-directory-access-check'
_PROBE_TIMEOUT_SECONDS = 10.0
_PROBE_MAX_ELAPSED_SECONDS = 20.0
# A successful check is reused briefly so reopening admin settings does not reread Graph.
_READY_CACHE_SECONDS = 300.0

_ready_cache = {}
_ready_cache_lock = Lock()
_reported = set()
_report_lock = Lock()


def _safe_code(value):
    return value if type(value) is str and _SAFE_CODE.fullmatch(value) is not None else None


def _utc_now():
    return datetime.now(timezone.utc)


def graph_directory_token_provider(*, timeout):
    """The application's own Microsoft Graph token source for directory reads.

    Returns ``(graph_base_url, graph_scope, app_client_id, get_access_token)`` for the
    configured cloud. The MSAL confidential client is built on first use, against the
    Graph authority, and never falls back to an interactive or delegated sign-in.
    A refused client-credential sign-in is reported as ``DIRECTORY_SIGN_IN_FAILED``;
    outages and throttling stay operational so they are never mistaken for a refusal.
    """
    # Optional directory authorization is initialized only when external data is accessed.
    from functions_orchestration_external_identity import ExternalIdentityServiceError

    graph_base = authentication.get_graph_base_url()
    graph_origin = urlsplit(graph_base)
    graph_scope = f"{graph_origin.scheme}://{graph_origin.netloc}/.default"
    app_client_id = authentication.CLIENT_ID
    application = None

    def get_access_token(scope):
        nonlocal application
        if scope != graph_scope or authentication.CLIENT_ID != app_client_id:
            raise ResultUnavailableError('external_identity_access_denied')
        if application is None:
            application = authentication._build_msal_app(
                authority_override=authentication.get_graph_authority(), timeout=timeout,
            )
        result = application.acquire_token_for_client(scopes=[scope])
        if type(result) is not dict:
            raise ExternalIdentityServiceError('external_identity_response_invalid')
        token = result.get('access_token')
        if type(token) is str and token:
            return token
        error = result.get('error')
        if error in ('server_error', 'temporarily_unavailable'):
            raise ExternalIdentityServiceError()
        if error == 'too_many_requests':
            raise ExternalIdentityServiceError('external_identity_throttled')
        if error in _SIGN_IN_REFUSALS:
            raise ResultUnavailableError(DIRECTORY_SIGN_IN_FAILED)
        raise ExternalIdentityServiceError('external_identity_response_invalid')

    return graph_base, graph_scope, app_client_id, get_access_token


def identity_gated_capabilities(settings):
    """Enabled orchestration capabilities whose steps reread the user's directory state."""
    if not isinstance(settings, dict) or not settings.get('enable_chat_orchestration'):
        return []
    try:
        available = resolve_available_capability_ids(
            settings, candidate_ids=DIRECTORY_GATED_CAPABILITIES, include_runtime_bindings=False,
        )
    except CapabilityResolutionError:
        # A malformed capability allowlist already stops every orchestration capability.
        return []
    return [capability_id for capability_id in DIRECTORY_GATED_CAPABILITIES if capability_id in available]


def _probe_result(status, reason=None):
    return {'status': status, 'reason': reason, 'checked_at': _utc_now().isoformat()}


def probe_directory_access(user_id, *, refresh=False):
    """Read the signed-in administrator's directory state exactly as orchestration does.

    Uses the real directory reader and token source, with only the conversation and user
    settings reads replaced, so the result reflects the permission and credentials a live
    request would use. Returns ``{status, reason, checked_at}``.
    """
    # Optional directory authorization is initialized only when it is checked.
    from functions_orchestration_external_identity import (
        ExternalIdentityCancelledError,
        ExternalIdentityServiceError,
        GraphExternalIdentityReader,
    )

    try:
        graph_base, graph_scope, app_client_id, get_access_token = graph_directory_token_provider(
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except Exception as error:
        log_event(
            f'{LOG_TAG} The directory access check could not prepare its token source.',
            level=logging.WARNING, extra={'error_type': type(error).__name__},
        )
        return _probe_result(STATUS_UNVERIFIED, 'directory_check_failed')

    cache_key = (user_id, app_client_id, graph_base)
    if not refresh:
        with _ready_cache_lock:
            cached = _ready_cache.get(cache_key)
            if cached is not None and cached[0] > monotonic():
                return dict(cached[1])

    def authorize_conversation(*, user_id, conversation_id):
        return {'id': conversation_id, 'user_id': user_id}

    def read_user_settings(user_id):
        return {'id': user_id, 'settings': {}}

    try:
        reader = GraphExternalIdentityReader(
            user_id=user_id, conversation_id=_PROBE_CONVERSATION_ID,
            app_client_id=app_client_id, graph_base_url=graph_base, graph_scope=graph_scope,
            get_access_token=get_access_token, http_get=requests.get,
            authorize_conversation=authorize_conversation, read_user_settings=read_user_settings,
            request_timeout=_PROBE_TIMEOUT_SECONDS, max_elapsed=_PROBE_MAX_ELAPSED_SECONDS,
        )
        reader(user_id=user_id, conversation_id=_PROBE_CONVERSATION_ID)
        result = _probe_result(STATUS_READY)
    except ResultUnavailableError as error:
        code = _safe_code(getattr(error, 'code', None))
        if code in _DIRECTORY_STATUSES:
            result = _probe_result(_DIRECTORY_STATUSES[code], code)
        elif code in _USER_DECISIONS:
            result = _probe_result(STATUS_READY)
        else:
            result = _probe_result(STATUS_UNVERIFIED, code)
    except (ExternalIdentityServiceError, ExternalIdentityCancelledError, ResultContractError) as error:
        result = _probe_result(STATUS_UNVERIFIED, _safe_code(getattr(error, 'code', None)))
    except Exception as error:
        log_event(
            f'{LOG_TAG} The directory access check failed unexpectedly.',
            level=logging.WARNING, extra={'error_type': type(error).__name__},
        )
        result = _probe_result(STATUS_UNVERIFIED, 'directory_check_failed')

    if result['status'] == STATUS_READY:
        with _ready_cache_lock:
            _ready_cache[cache_key] = (monotonic() + _READY_CACHE_SECONDS, dict(result))
    else:
        with _ready_cache_lock:
            _ready_cache.pop(cache_key, None)
    return result


def _notification_content(reason):
    if reason == DIRECTORY_SIGN_IN_FAILED:
        return (
            "Chat Orchestration can't sign in to Microsoft Entra ID",
            "Microsoft Entra ID refused SimpleChat's application sign-in when Chat Orchestration "
            "tried to confirm a user's access to web search and other external sources (linked "
            "pages, deep research, agents and actions). Check that the app registration's client "
            "secret is current and that the application is enabled. Until then, those steps fail "
            "for every user.",
        )
    return (
        "Chat Orchestration can't verify access to web search",
        "SimpleChat can't read Microsoft Entra ID, so Chat Orchestration can't confirm that "
        "users may use web search and other external sources (linked pages, deep research, "
        f"agents and actions). Grant the Microsoft Graph {GRAPH_DIRECTORY_PERMISSION} "
        "application permission to SimpleChat's app registration and give administrator "
        "consent. Until then, those steps fail for every user.",
    )


def _notify_administrators(reason, day):
    # Notifications load Cosmos-backed workspace modules, needed only once a failure is reported.
    from functions_notifications import (
        ORCHESTRATION_DIRECTORY_ACCESS_NOTIFICATION_TYPE,
        create_notification,
    )

    title, message = _notification_content(reason)
    return create_notification(
        notification_type=ORCHESTRATION_DIRECTORY_ACCESS_NOTIFICATION_TYPE,
        title=title,
        message=message,
        link_url=ADMIN_SETTINGS_LINK,
        metadata={
            'reason': reason,
            'graph_permission': GRAPH_DIRECTORY_PERMISSION,
            'graph_permission_id': GRAPH_DIRECTORY_PERMISSION_ID,
            'graph_resource_app_id': GRAPH_RESOURCE_APP_ID,
        },
        assignment={'roles': ['Admin']},
        idempotency_key=f'orchestration-directory-access:{reason}:{day}',
    )


def report_directory_access_failure(reason):
    """Tell administrators, at most once per reason and UTC day, that directory reads fail.

    Called on the failing request's path, so it never raises. Each process remembers what
    it reported; the notification's retry key keeps other processes and instances from
    adding a duplicate. A notification that could not be saved is retried by a later
    failure instead of being remembered as sent.
    """
    try:
        if type(reason) is not str or reason not in _DIRECTORY_STATUSES:
            return None
        day = _utc_now().date().isoformat()
        key = (reason, day)
        with _report_lock:
            if key in _reported:
                return None
            _reported.add(key)
        log_event(
            f"{LOG_TAG} Microsoft Entra ID refused the application's directory read.",
            level=logging.WARNING,
            extra={'authority_reason': reason},
        )
        notification = _notify_administrators(reason, day)
        if notification is None:
            with _report_lock:
                _reported.discard(key)
        return notification
    except Exception as error:
        try:
            with _report_lock:
                _reported.discard((reason, _utc_now().date().isoformat()))
            log_event(
                f'{LOG_TAG} Administrators could not be notified about directory access.',
                level=logging.WARNING, extra={'error_type': type(error).__name__},
            )
        except Exception:
            pass
        return None


def reset_directory_access_state():
    """Forget cached checks and reported failures. For tests and diagnostics only."""
    with _ready_cache_lock:
        _ready_cache.clear()
    with _report_lock:
        _reported.clear()


def check_orchestration_directory_access(user_id, settings, *, refresh=False):
    """What the admin settings page shows about orchestration's directory access.

    Performs no Graph I/O unless an enabled capability needs it. A missing permission or a
    refused sign-in found here is also reported to administrators.
    """
    capabilities = identity_gated_capabilities(settings)
    client_id = authentication.CLIENT_ID
    report = {
        'status': STATUS_NOT_REQUIRED,
        'required': bool(capabilities),
        'reason': None,
        'capabilities': [
            {'id': capability_id, 'label': (get_capability(capability_id) or {}).get('label') or capability_id}
            for capability_id in capabilities
        ],
        'web_search_enabled': CAPABILITY_WEB_SEARCH in capabilities,
        'application_client_id': client_id if type(client_id) is str and _GUID.fullmatch(client_id) else None,
        'graph_permission': GRAPH_DIRECTORY_PERMISSION,
        'graph_permission_id': GRAPH_DIRECTORY_PERMISSION_ID,
        'graph_resource_app_id': GRAPH_RESOURCE_APP_ID,
        'checked_at': None,
    }
    if not capabilities:
        return report
    probe = probe_directory_access(user_id, refresh=refresh)
    report.update(status=probe['status'], reason=probe['reason'], checked_at=probe['checked_at'])
    if probe['status'] in (STATUS_PERMISSION_MISSING, STATUS_SIGN_IN_FAILED):
        report_directory_access_failure(probe['reason'])
    return report
