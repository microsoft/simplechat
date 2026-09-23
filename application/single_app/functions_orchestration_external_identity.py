# functions_orchestration_external_identity.py
"""Read current external-result identity through injected Microsoft Graph I/O.

Version: 0.261.127

Only the owner supplies credentials, the trusted cloud endpoint, conversation
authorization and uncached, read-only user settings. No directory authority,
tokens or settings are persisted or cached by this module.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import string
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit

from azure.core.exceptions import AzureError, ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from requests import Response
from requests.exceptions import RequestException, Timeout

from functions_orchestration_external_sources import CurrentExternalSourceIdentity
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationServiceError,
)
from functions_orchestration_result_contracts import ResultContractError, identifier
from functions_orchestration_results import ResultUnavailableError


_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_ZERO_GUID = "00000000-0000-0000-0000-000000000000"
_ASSIGNMENT_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_BEARER_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*\Z")
_ROLE_CHARACTERS = frozenset(string.ascii_letters + string.digits + ":!#$%&'()*+,-./;<=>?@[]^_`{|}~")
_PATH_CHARACTERS = frozenset(string.ascii_letters + string.digits + "/-._~")
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
        super().__init__("Current directory authorization could not be verified.")


class ExternalIdentityCancelledError(OrchestrationInvocationCancelledError):
    """An owning execution check explicitly stopped directory authorization."""

    code = "external_identity_cancelled"

    def __init__(self):
        super().__init__("Current directory authorization was cancelled.")


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


def _guid(value, *, allow_zero=False):
    return (
        type(value) is str and _GUID.fullmatch(value) is not None
        and (allow_zero or value != _ZERO_GUID)
    )


def _url_parts(value):
    if (
        type(value) is not str or not 1 <= len(value) <= 8192
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
        or "\\" in value or "#" in value or re.search(r"%(?![0-9A-Fa-f]{2})", value)
    ):
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
        query = tuple(sorted(parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=32)))
    except ValueError:
        parts = None
    if parts is None:
        return None
    if (
        parts.scheme != "https" or not parts.hostname or parts.username is not None
        or parts.password is not None or parts.fragment or not set(parts.path) <= _PATH_CHARACTERS
        or not set(parts.hostname) <= set(string.ascii_letters + string.digits + ".-_:")
        or parts.netloc.endswith(":") or (port is not None and not 1 <= port <= 65535)
        or any(segment in {".", ".."} for segment in parts.path.split("/"))
        or "//" in parts.path or len({key for key, _ in query}) != len(query)
    ):
        return None
    return parts, ("https", parts.hostname, port if port is not None else 443), query


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate directory response field.")
        value[key] = item
    return value


def _invalid_json_constant(_value):
    raise ValueError("Invalid directory response number.")


@dataclass
class _ReadBudget:
    deadline: float
    max_pages: int
    max_records: int
    execution_check: Callable | None
    pages: int = 0
    records: int = 0

    def check(self):
        if monotonic() >= self.deadline:
            raise ExternalIdentityServiceError("external_identity_timeout")
        if self.execution_check is not None:
            allowed = self.execution_check()
            if allowed is False:
                raise ExternalIdentityCancelledError()
            if allowed is not None and allowed is not True:
                raise ExternalIdentityServiceError("external_identity_callback_invalid")
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise ExternalIdentityServiceError("external_identity_timeout")
        return remaining

    def add_records(self, count):
        self.records += count
        if self.records > self.max_records:
            raise ExternalIdentityServiceError("external_identity_limit_exceeded")


class GraphExternalIdentityReader:
    """Callable read_identity boundary for OrchestrationExternalSourceProvider.

    get_access_token(scope) returns a bearer string. The owner may lazily acquire
    it through its existing MSAL application or an initialized credential.
    http_get is an initialized, non-caching requests.Session.get-compatible
    transport. authorize_conversation(*, user_id, conversation_id) returns the
    current owned conversation. read_user_settings(user_id) returns its current
    actor-bound document, without caching, repairs, defaults for missing records,
    or writes. Owner callbacks must bound their own I/O and may raise normal
    Azure/requests I/O errors, PermissionError, or ExternalIdentityServiceError.
    """

    def __init__(
        self, *, user_id, conversation_id, app_client_id, graph_base_url, graph_scope,
        get_access_token, http_get, authorize_conversation, read_user_settings,
        execution_check=None, request_timeout=10.0, max_elapsed=30.0,
        max_pages=20, max_records=4096, max_response_bytes=1048576,
    ):
        if not _guid(user_id) or not _guid(app_client_id):
            raise ResultContractError("external_identity_configuration_invalid")
        identifier(conversation_id, limit=256)
        base = _url_parts(graph_base_url)
        scope = _url_parts(graph_scope)
        if (
            base is None or "?" in graph_base_url or scope is None or "?" in graph_scope
            or not scope[0].path.endswith("/.default")
        ):
            raise ResultContractError("external_identity_configuration_invalid")
        for callback in (get_access_token, http_get, authorize_conversation, read_user_settings):
            if not callable(callback):
                raise ResultContractError("external_identity_callback_required")
        if execution_check is not None and not callable(execution_check):
            raise ResultContractError("external_identity_callback_required")
        for value, maximum in ((request_timeout, 30), (max_elapsed, 120)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ResultContractError("external_identity_limit_invalid")
        for value, maximum in ((max_pages, 100), (max_records, 10000), (max_response_bytes, 8388608)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ResultContractError("external_identity_limit_invalid")
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.app_client_id = app_client_id
        self.graph_base_url = graph_base_url.rstrip("/")
        self.graph_scope = graph_scope
        self._origin = base[1]
        self._path_prefix = base[0].path.rstrip("/")
        self.get_access_token = get_access_token
        self.http_get = http_get
        self.authorize_conversation = authorize_conversation
        self.read_user_settings = read_user_settings
        self.execution_check = execution_check
        self.request_timeout = request_timeout
        self.max_elapsed = max_elapsed
        self.max_pages = max_pages
        self.max_records = max_records
        self.max_response_bytes = max_response_bytes

    def _authorize_conversation(self, budget):
        budget.check()
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
        budget.check()

    def _settings(self, budget):
        budget.check()
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
        budget.check()
        return document["settings"], preference

    def _checked_url(self, url, path):
        checked = _url_parts(url)
        if (
            checked is None or checked[1] != self._origin
            or not checked[0].path.startswith(f"{self._path_prefix}/")
            or checked[0].path != path
        ):
            raise ExternalIdentityServiceError("external_identity_pagination_invalid")
        return checked[1], checked[0].path, checked[2]

    def _read_response(self, response, url_key, path, budget):
        try:
            if (
                type(response.history) is not list or response.history
                or self._checked_url(response.url, path) != url_key
                or type(response.status_code) is not int
            ):
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            if response.status_code != 200:
                raise _http_error(response.status_code)
            content_type = response.headers.get("Content-Type")
            if type(content_type) is not str or content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            chunks = []
            size = 0
            iterator = response.iter_content(chunk_size=16384)
            while True:
                budget.check()
                try:
                    chunk = _call_io(next, iterator)
                except StopIteration:
                    break
                if type(chunk) is not bytes:
                    raise ExternalIdentityServiceError("external_identity_response_invalid")
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_response_bytes:
                    raise ExternalIdentityServiceError("external_identity_limit_exceeded")
                chunks.append(chunk)
            budget.check()
            try:
                value = json.loads(
                    b"".join(chunks).decode("utf-8"), object_pairs_hook=_unique_object,
                    parse_constant=_invalid_json_constant,
                )
            except (ValueError, UnicodeError, RecursionError):
                value = None
            if type(value) is not dict or "@odata.deltaLink" in value or "error" in value:
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            return value
        finally:
            _call_io(response.close)

    def _get(self, url, path, budget, *, counted=False):
        url_key = self._checked_url(url, path)
        self._authorize_conversation(budget)
        if budget.pages >= budget.max_pages:
            raise ExternalIdentityServiceError("external_identity_limit_exceeded")
        budget.pages += 1
        token = _call_io(self.get_access_token, self.graph_scope)
        if type(token) is not str or not 1 <= len(token) <= 65536 or _BEARER_TOKEN.fullmatch(token) is None:
            raise ExternalIdentityServiceError("external_identity_callback_invalid")
        remaining = budget.check()
        headers = {
            "Authorization": f"Bearer {token}", "Accept": "application/json",
            "Cache-Control": "no-cache, no-store", "Accept-Encoding": "identity",
        }
        if counted:
            headers["ConsistencyLevel"] = "eventual"
        response = _call_io(
            self.http_get, url, headers=headers, timeout=min(self.request_timeout, remaining),
            allow_redirects=False, stream=True,
        )
        if not isinstance(response, Response):
            raise ExternalIdentityServiceError("external_identity_callback_invalid")
        return self._read_response(response, url_key, path, budget)

    def _collection(self, path, parameters, budget, *, counted=False):
        url = f"{self.graph_base_url}{path.removeprefix(self._path_prefix)}?{urlencode(parameters)}"
        seen = set()
        values = []
        expected_count = None
        while True:
            url_key = self._checked_url(url, path)
            if url_key in seen:
                raise ExternalIdentityServiceError("external_identity_pagination_invalid")
            seen.add(url_key)
            page = self._get(url, path, budget, counted=counted)
            items = page.get("value")
            if type(items) is not list or any(type(item) is not dict for item in items):
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            count = page.get("@odata.count")
            if "@odata.count" in page:
                if type(count) is not int or count < 0 or (expected_count is not None and count != expected_count):
                    raise ExternalIdentityServiceError("external_identity_response_invalid")
                if count > budget.max_records:
                    raise ExternalIdentityServiceError("external_identity_limit_exceeded")
                expected_count = count
            if counted and expected_count is None:
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            budget.add_records(len(items))
            values.extend(items)
            if expected_count is not None and len(values) > expected_count:
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            if "@odata.nextLink" not in page:
                break
            url = page["@odata.nextLink"]
        if expected_count is not None and len(values) != expected_count:
            raise ExternalIdentityServiceError("external_identity_response_invalid")
        return values

    @staticmethod
    def _active_object(value, object_type, expected_id=None):
        if (
            not _guid(value.get("id")) or type(value.get("accountEnabled")) is not bool
            or "@odata.nextLink" in value
            or ("@odata.type" in value and value["@odata.type"] != f"#microsoft.graph.{object_type}")
        ):
            raise ExternalIdentityServiceError("external_identity_response_invalid")
        if (
            (expected_id is not None and value["id"] != expected_id)
            or not value["accountEnabled"] or value.get("deletedDateTime") is not None
            or "@removed" in value
        ):
            raise ResultUnavailableError("external_identity_account_unavailable")

    def _role_definitions(self, principal, budget):
        definitions = principal.get("appRoles")
        if type(definitions) is not list or "appRoles@odata.nextLink" in principal:
            raise ExternalIdentityServiceError("external_identity_response_invalid")
        if "appRoles@odata.count" in principal and (
            type(principal["appRoles@odata.count"]) is not int
            or principal["appRoles@odata.count"] != len(definitions)
        ):
            raise ExternalIdentityServiceError("external_identity_response_invalid")
        budget.add_records(len(definitions))
        roles = {}
        names = set()
        for role in definitions:
            if type(role) is not dict:
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            role_id, value, members = role.get("id"), role.get("value"), role.get("allowedMemberTypes")
            if (
                not _guid(role_id) or role_id in roles or type(role.get("isEnabled")) is not bool
                or type(value) is not str or not 1 <= len(value) <= 120
                or value.startswith(".") or not set(value) <= _ROLE_CHARACTERS
                or type(members) is not list or not 1 <= len(members) <= 2
                or any(type(member) is not str or member not in {"User", "Application"} for member in members)
                or len(set(members)) != len(members)
            ):
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            eligible = role["isEnabled"] and "User" in members
            if eligible and value in names:
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            roles[role_id] = value if eligible else None
            if eligible:
                names.add(value)
        return roles

    def _assigned_roles(self, assignments, principal_id, definitions):
        identities = set()
        roles = set()
        for assignment in assignments:
            assignment_id = assignment.get("id")
            role_id = assignment.get("appRoleId")
            principal_type = assignment.get("principalType")
            principal = assignment.get("principalId")
            resource = assignment.get("resourceId")
            if (
                type(assignment_id) is not str or _ASSIGNMENT_ID.fullmatch(assignment_id) is None
                or assignment_id in identities or not _guid(role_id, allow_zero=True)
                or not _guid(principal) or not _guid(resource)
                or type(principal_type) is not str or principal_type not in {"User", "Group"}
                or (principal_type == "User" and principal != self.user_id)
                or (principal_type == "Group" and principal == self.user_id)
                or assignment.get("deletedDateTime") is not None or "@removed" in assignment
                or ("@odata.type" in assignment and assignment["@odata.type"] != "#microsoft.graph.appRoleAssignment")
            ):
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            identities.add(assignment_id)
            if resource != principal_id or role_id == _ZERO_GUID:
                continue
            if role_id not in definitions:
                raise ResultUnavailableError("external_identity_role_unavailable")
            value = definitions[role_id]
            if value is not None:
                roles.add(value)
        if not {"User", "Admin"}.intersection(roles):
            raise ResultUnavailableError("external_identity_role_required")
        if len(roles) > 64:
            raise ExternalIdentityServiceError("external_identity_limit_exceeded")
        return tuple(sorted(roles))

    @staticmethod
    def _check_access(settings, roles):
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
        budget = _ReadBudget(
            monotonic() + self.max_elapsed, self.max_pages, self.max_records, self.execution_check,
        )
        self._authorize_conversation(budget)
        self._settings(budget)
        user_path = f"{self._path_prefix}/users/{self.user_id}"
        user = self._get(
            f"{self.graph_base_url}/users/{self.user_id}?{urlencode({'$select': 'id,accountEnabled,userPrincipalName'})}",
            user_path, budget,
        )
        budget.add_records(1)
        self._active_object(user, "user", self.user_id)
        email = user.get("userPrincipalName")
        if email is not None:
            if type(email) is not str or not 1 <= len(email) <= 320 or any(character.isspace() for character in email):
                raise ExternalIdentityServiceError("external_identity_response_invalid")
            identifier(email, limit=320)
        principals = self._collection(
            f"{self._path_prefix}/servicePrincipals",
            {"$filter": f"appId eq '{self.app_client_id}'", "$select": "id,appId,accountEnabled,appRoles"},
            budget,
        )
        if not principals:
            raise ResultUnavailableError("external_identity_application_unavailable")
        if len(principals) != 1:
            raise ExternalIdentityServiceError("external_identity_response_invalid")
        principal = principals[0]
        self._active_object(principal, "servicePrincipal")
        if not _guid(principal.get("appId")) or principal["appId"] != self.app_client_id:
            raise ResultUnavailableError("external_identity_application_unavailable")
        definitions = self._role_definitions(principal, budget)
        assignments = self._collection(
            f"{user_path}/appRoleAssignments",
            {
                "$filter": f"resourceId eq {principal['id']}",
                "$select": "id,appRoleId,principalId,principalType,resourceId",
                "$count": "true",
            },
            budget, counted=True,
        )
        roles = self._assigned_roles(assignments, principal["id"], definitions)
        self._authorize_conversation(budget)
        settings, enable_agents = self._settings(budget)
        self._check_access(settings, roles)
        budget.check()
        return CurrentExternalSourceIdentity(self.user_id, roles, enable_agents, email)
