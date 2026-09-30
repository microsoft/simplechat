# functions_orchestration_external_identity.py
"""Read current external-result identity from the signed-in session.

Version: 0.261.205
Implemented in: 0.261.127
Signed-in session roles replaced per-call Microsoft Graph reads in: 0.261.205

Orchestration trusts the app roles in the signed-in session, the same authority
classic chat uses. The owner captures those roles while a request context is
available, then supplies current conversation authorization and uncached,
read-only user settings. This module makes no directory calls and persists or
caches no roles, tokens or settings.
"""

from datetime import datetime, timezone

from azure.core.exceptions import AzureError, ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from requests.exceptions import RequestException, Timeout

from functions_orchestration_external_sources import CurrentExternalSourceIdentity
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationServiceError,
)
from functions_orchestration_result_contracts import (
    EXTERNAL_SESSION_UNAVAILABLE_REASON, ResultContractError, identifier,
)
from functions_orchestration_results import ResultUnavailableError


MAX_SESSION_ROLES = 64
_SERVICE_ERRORS = {
    "external_identity_service_unavailable": True,
    "external_identity_timeout": True,
    "external_identity_throttled": True,
    "external_identity_incomplete": True,
    "external_identity_response_invalid": False,
    "external_identity_pagination_invalid": False,
    "external_identity_limit_exceeded": False,
    "external_identity_callback_invalid": False,
}


class ExternalIdentityServiceError(OrchestrationInvocationServiceError):
    """Safe operational failure, never an empty/denied identity.

    The owner may map retryable failures to a temporary service response rather
    than reporting revoked access. Provider exception text is never retained.
    """

    def __init__(self, code="external_identity_service_unavailable"):
        if type(code) is not str or code not in _SERVICE_ERRORS:
            raise ValueError("Invalid external identity error code.")
        self.code = code
        self.retryable = _SERVICE_ERRORS[code]
        super().__init__("Current user authorization could not be verified.")


class ExternalIdentityCancelledError(OrchestrationInvocationCancelledError):
    """An owning execution check explicitly stopped current authorization."""

    code = "external_identity_cancelled"

    def __init__(self):
        super().__init__("Current user authorization was cancelled.")


def _http_error(status):
    if type(status) is not int:
        return ExternalIdentityServiceError("external_identity_response_invalid")
    if status in (401, 403, 404, 410):
        return ResultUnavailableError("external_identity_access_denied")
    if status == 429:
        return ExternalIdentityServiceError("external_identity_throttled")
    if status == 408:
        return ExternalIdentityServiceError("external_identity_timeout")
    if status == 202:
        return ExternalIdentityServiceError("external_identity_incomplete")
    if 500 <= status <= 599:
        return ExternalIdentityServiceError()
    return ExternalIdentityServiceError("external_identity_response_invalid")


def _call_io(callback, *args, **kwargs):
    """Translate expected owner/SDK I/O errors outside their exception context."""
    try:
        return callback(*args, **kwargs)
    except ExternalIdentityCancelledError:
        raise
    except ExternalIdentityServiceError as error:
        failure = ExternalIdentityServiceError(error.code)
    except (ResultUnavailableError, ClientAuthenticationError, ResourceNotFoundError, PermissionError):
        failure = ResultUnavailableError("external_identity_access_denied")
    except HttpResponseError as error:
        failure = _http_error(error.status_code)
    except (Timeout, TimeoutError):
        failure = ExternalIdentityServiceError("external_identity_timeout")
    except (RequestException, AzureError, OSError):
        failure = ExternalIdentityServiceError()
    except (TypeError, ValueError, LookupError, RuntimeError):
        failure = ExternalIdentityServiceError("external_identity_callback_invalid")
    raise failure


def _valid_text(value, limit):
    try:
        identifier(value, limit=limit)
    except ResultContractError:
        return False
    return True


def _session_roles(roles):
    if roles is None:
        return None
    if type(roles) not in (list, tuple):
        raise ResultContractError("external_identity_configuration_invalid")
    return tuple(sorted({role for role in roles if _valid_text(role, 128)}))


def _session_email(email):
    if not _valid_text(email, 320) or any(character.isspace() for character in email):
        return None
    return email


class SessionExternalIdentityReader:
    """Callable read_identity boundary for OrchestrationExternalSourceProvider.

    roles and email come from the signed-in session that the owner captured
    while a request context existed. roles=None means no signed-in session was
    available, for example in a scheduler continuation, and every read then
    fails closed. Saved run roles are never restored.
    authorize_conversation(*, user_id, conversation_id) returns the current owned
    conversation. read_user_settings(user_id) returns its current actor-bound
    document, without caching, repairs, defaults for missing records, or writes.
    Owner callbacks must bound their own I/O and may raise normal Azure/requests
    I/O errors, PermissionError, or ExternalIdentityServiceError.
    """

    def __init__(
        self, *, user_id, conversation_id, roles, email, authorize_conversation,
        read_user_settings, execution_check=None,
    ):
        try:
            identifier(user_id)
            identifier(conversation_id, limit=256)
        except ResultContractError:
            raise ResultContractError("external_identity_configuration_invalid") from None
        for callback in (authorize_conversation, read_user_settings):
            if not callable(callback):
                raise ResultContractError("external_identity_callback_required")
        if execution_check is not None and not callable(execution_check):
            raise ResultContractError("external_identity_callback_required")
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.roles = _session_roles(roles)
        self.email = _session_email(email)
        self.authorize_conversation = authorize_conversation
        self.read_user_settings = read_user_settings
        self.execution_check = execution_check

    def _check(self):
        # Owner lease and cancellation errors are theirs to report; don't reclassify them.
        if self.execution_check is None:
            return
        allowed = self.execution_check()
        if allowed is False:
            raise ExternalIdentityCancelledError()
        if allowed is not None and allowed is not True:
            raise ExternalIdentityServiceError("external_identity_callback_invalid")

    def _authorize_conversation(self):
        conversation = _call_io(
            self.authorize_conversation, user_id=self.user_id, conversation_id=self.conversation_id,
        )
        if (
            type(conversation) is not dict or type(conversation.get("id")) is not str
            or conversation["id"] != self.conversation_id
            or type(conversation.get("user_id")) is not str or conversation["user_id"] != self.user_id
            or any(conversation.get(key) is not None and conversation.get(key) is not False
                   for key in ("deleted", "orchestration_deleted"))
        ):
            raise ResultUnavailableError("external_identity_conversation_unavailable")

    def _settings(self):
        document = _call_io(self.read_user_settings, self.user_id)
        if (
            type(document) is not dict or type(document.get("id")) is not str or document["id"] != self.user_id
            or type(document.get("settings")) is not dict
            or ("user_id" in document and (type(document["user_id"]) is not str or document["user_id"] != self.user_id))
        ):
            raise ResultUnavailableError("external_identity_settings_unavailable")
        preference = document["settings"].get("enable_agents", True)
        if type(preference) is not bool:
            raise ResultUnavailableError("external_identity_settings_unavailable")
        return document["settings"], preference

    @staticmethod
    def _check_access(settings, roles):
        """Apply the Control Center restriction that user_required enforces for chat."""
        if "Admin" in roles:
            return
        access = settings.get("access", {})
        if type(access) is not dict:
            raise ResultUnavailableError("external_identity_access_restricted")
        status = access.get("status", "allow")
        if type(status) is not str or status not in {"allow", "deny"}:
            raise ResultUnavailableError("external_identity_access_restricted")
        if status == "allow":
            return
        until = access.get("datetime_to_allow")
        if type(until) is not str or not 1 <= len(until) <= 64:
            raise ResultUnavailableError("external_identity_access_restricted")
        try:
            allow_time = datetime.fromisoformat(until.replace("Z", "+00:00"))
        except ValueError:
            allow_time = None
        if allow_time is None or allow_time.utcoffset() is None or datetime.now(timezone.utc) < allow_time:
            raise ResultUnavailableError("external_identity_access_restricted")

    def __call__(self, *, user_id, conversation_id):
        if (
            type(user_id) is not str or user_id != self.user_id
            or type(conversation_id) is not str or conversation_id != self.conversation_id
        ):
            raise ResultUnavailableError("external_identity_actor_mismatch")
        if self.roles is None:
            raise ResultUnavailableError(EXTERNAL_SESSION_UNAVAILABLE_REASON)
        if len(self.roles) > MAX_SESSION_ROLES:
            raise ExternalIdentityServiceError("external_identity_limit_exceeded")
        if not {"User", "Admin"}.intersection(self.roles):
            raise ResultUnavailableError("external_identity_role_required")
        self._check()
        self._authorize_conversation()
        self._check()
        settings, enable_agents = self._settings()
        self._check_access(settings, self.roles)
        self._check()
        return CurrentExternalSourceIdentity(self.user_id, self.roles, enable_agents, self.email)
