# functions_m365_transport.py
"""Cloud-bound delegated Graph I/O. No action manifest can choose a token target."""

import hashlib
import ipaddress
import json
import logging
import re
import tempfile
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests
from opentelemetry.instrumentation.utils import suppress_instrumentation

from functions_m365_operations import M365_INTERNAL_OPERATION_FUNCTIONS, M365_SOURCES


M365_REQUEST_TIMEOUT = (10, 45)
M365_JSON_MAX_BYTES = 4 * 1024 * 1024
M365_FILE_HARD_MAX_BYTES = 100 * 1024 * 1024
M365_DOWNLOAD_CHUNK_BYTES = 64 * 1024
M365_MAX_DOWNLOAD_REDIRECTS = 3
M365_JSON_READ_MAX_SECONDS = 120
M365_DOWNLOAD_MAX_SECONDS = 180
_GRAPH_DOWNLOAD_SUFFIXES = {
    "graph.microsoft.com": ("sharepoint.com",),
    "graph.microsoft.us": ("sharepoint.us",),
    "dod-graph.microsoft.us": ("sharepoint-mil.us",),
    "microsoftgraph.chinacloudapi.cn": ("sharepoint.cn",),
}
_TRANSPORT_CALLBACKS = ContextVar("m365_transport_callbacks", default={})
_TRANSPORT_OPERATIONS = ContextVar("m365_transport_operations", default={})


class M365ProviderError(Exception):
    """Stable, safe error suitable for a tool result, never a raw provider response."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: Optional[int] = None,
        retry_after_seconds: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.details = dict(details or {})

    def as_dict(self) -> Dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.retry_after_seconds is not None:
            result["retry_after_seconds"] = self.retry_after_seconds
        result.update(self.details)
        return result

    def as_result(self, source: str, provider: str = "graph", operation: str = "") -> Dict[str, Any]:
        return {
            "status": "error",
            "source": source,
            "provider": self.details.get("provider", provider),
            "operation": operation,
            "results": [],
            "error": self.as_dict(),
            "coverage": {"complete": False},
        }


def log_m365_failure(code: str, *, source: str = "", operation: str = "") -> None:
    # Logging owns application bootstrap; transport stays cold-importable until execution.
    from functions_appinsights import log_event

    log_event(
        "[MS_GRAPH_PLUGIN] Microsoft 365 operation could not complete.",
        level=logging.WARNING,
        extra={"source": source, "operation": operation, "error_code": code},
    )


def _https_parts(url: str):
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme.lower() == "https"
            and parts.hostname
            and not parts.username
            and not parts.password
            and parts.port in (None, 443)
            and not parts.fragment
            and "\\" not in url
            and not re.search(r"[\x00-\x20\x7f]", url)
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise M365ProviderError("invalid_url", "A valid HTTPS Microsoft 365 URL is required.")
    return parts


def _normalize_host_rule(value: str) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    if host.startswith("*."):
        host = host[2:]
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host:
        raise M365ProviderError("invalid_cloud_configuration", "Configure valid trusted Microsoft 365 download hosts.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise M365ProviderError("invalid_cloud_configuration", "Microsoft 365 download hosts must be DNS names.")


def normalize_m365_transport_settings(provider, hosts):
    if provider not in {"auto", "graph"}:
        raise M365ProviderError("invalid_cloud_configuration", "Choose Auto or Microsoft Graph for retrieval.")
    if isinstance(hosts, str):
        hosts = [value.strip() for value in re.split(r"[\n,;]", hosts) if value.strip()]
    if not isinstance(hosts, (list, tuple)) or len(hosts) > 30:
        raise M365ProviderError("invalid_cloud_configuration", "Specify at most 30 trusted download host names.")
    return {
        "m365_retrieval_provider": provider,
        "m365_trusted_download_hosts": list(dict.fromkeys(_normalize_host_rule(host) for host in hosts)),
    }


@dataclass(frozen=True)
class M365CloudConfig:
    graph_base_url: str
    graph_authority: str
    retrieval_provider: str = "auto"
    trusted_download_hosts: Tuple[str, ...] = ()

    def __post_init__(self):
        base = self.graph_base_url.rstrip("/")
        parts = _https_parts(base)
        _https_parts(self.graph_authority)
        if parts.query or not parts.path.endswith("/v1.0"):
            raise M365ProviderError("invalid_cloud_configuration", "The configured Graph endpoint must identify Graph v1.0.")
        if self.retrieval_provider not in ("auto", "graph"):
            raise M365ProviderError("invalid_cloud_configuration", "Microsoft 365 retrieval provider must be auto or graph.")
        object.__setattr__(self, "graph_base_url", base)
        object.__setattr__(
            self, "trusted_download_hosts",
            tuple(_normalize_host_rule(value) for value in self.trusted_download_hosts),
        )

    @property
    def resource_url(self) -> str:
        return self.graph_base_url[:-len("/v1.0")]

    @property
    def supports_copilot_retrieval(self) -> bool:
        parts = urlsplit(self.graph_base_url)
        authority = urlsplit(self.graph_authority)
        return (
            parts.hostname == "graph.microsoft.com" and parts.path == "/v1.0"
            and authority.hostname == "login.microsoftonline.com"
        )

    @property
    def download_hosts(self) -> Tuple[str, ...]:
        known_hosts = _GRAPH_DOWNLOAD_SUFFIXES.get(urlsplit(self.graph_base_url).hostname, ())
        return tuple(dict.fromkeys((*known_hosts, *self.trusted_download_hosts)))

    def validate_content_url(self, url: str) -> str:
        parts = _https_parts(url)
        host = parts.hostname.lower().rstrip(".")
        if not any(host == suffix or host.endswith(f".{suffix}") for suffix in self.download_hosts):
            raise M365ProviderError("untrusted_download_host", "The file host is not trusted for this Microsoft 365 cloud.")
        return url

    def canonical_web_url(self, url: str) -> str:
        self.validate_content_url(url)
        parts = _https_parts(url)
        path = unquote(parts.path)
        if (
            any(segment in (".", "..") for segment in path.split("/"))
            or any(character in path for character in ('\\', '"', "\x00", "\r", "\n"))
            or re.search(r"%(?:2f|5c|2e|00)", path, flags=re.IGNORECASE)
            or "/_layouts/" in path.lower()
        ):
            raise M365ProviderError("invalid_source_url", "Use the canonical file or folder link, not a download or sharing URL.")
        if parts.query:
            raise M365ProviderError("invalid_source_url", "Use the canonical file or folder link without access or sharing parameters.")
        return urlunsplit(("https", parts.netloc.lower(), quote(path, safe="/:@!$&'()+,;=-._~"), "", ""))


def get_m365_cloud_config() -> M365CloudConfig:
    # These owners initialize config/clients; resolving them is intentionally deferred to a call.
    import functions_authentication
    from functions_settings import get_settings

    if functions_authentication.AZURE_ENVIRONMENT not in ("public", "usgovernment", "custom"):
        raise M365ProviderError("invalid_cloud_configuration", "Select a supported deployment cloud and explicit custom endpoints where required.")
    if (
        functions_authentication.AZURE_ENVIRONMENT == "custom"
        and not functions_authentication.CUSTOM_GRAPH_URL_VALUE
    ):
        raise M365ProviderError("invalid_cloud_configuration", "A custom cloud requires an explicit Microsoft Graph endpoint.")
    settings = get_settings()
    hosts = settings.get("m365_trusted_download_hosts") or ()
    if isinstance(hosts, str):
        hosts = tuple(value.strip() for value in hosts.split(",") if value.strip())
    if not isinstance(hosts, (list, tuple)):
        raise M365ProviderError("invalid_cloud_configuration", "Microsoft 365 trusted download hosts must be a list.")
    return M365CloudConfig(
        graph_base_url=functions_authentication.get_graph_base_url(),
        graph_authority=functions_authentication.get_graph_authority(),
        retrieval_provider=settings.get("m365_retrieval_provider", "auto"),
        trusted_download_hosts=tuple(hosts),
    )


def get_m365_context(*, require_remote: bool = True):
    # Execution/connection modules are wired by the web and workflow owners after bootstrap.
    from functions_m365_execution import (
        M365ExecutionContext,
        get_m365_execution_context,
        require_m365_execution_context,
    )

    if require_remote:
        return require_m365_execution_context()
    context = get_m365_execution_context()
    if not isinstance(context, M365ExecutionContext) or not context.request_id:
        raise M365ProviderError("execution_context_required", "An authorized Microsoft 365 execution context is required.")
    return context


def authorize_m365_capability(action_id: str, operation_name: str, action_type: str, *, context=None):
    from functions_m365_execution import authorize_m365_capability as authorize_capability

    return authorize_capability(
        action_id, M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name),
        action_type, context=context,
    )


def authorize_m365_publication(source, action_id, action_policy, *, operation_name):
    from functions_m365_execution import authorize_m365_publication as authorize_publication

    return authorize_publication(
        source, action_id, action_policy, operation_name=operation_name,
        context=get_m365_context(require_remote=False),
    )


def authorize_m365_source(
    source: str, action_id: str, action_policy: Any, *,
    operation_name: Optional[str] = None, action_type: Optional[str] = None,
):
    from functions_m365_execution import authorize_m365_operation

    if source not in M365_SOURCES:
        raise M365ProviderError("invalid_source", "Unsupported Microsoft 365 source.")
    get_m365_context()
    operation_options = {}
    if operation_name is not None:
        operation_options = {
            "operation_name": M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name),
        }
    decision = authorize_m365_operation(source, action_id, action_policy, **operation_options)
    if (
        not isinstance(decision, dict)
        or decision.get("allowed") is False
        or decision.get("error")
        or decision.get("source") != source
    ):
        decision = decision if isinstance(decision, dict) else {}
        error = decision.get("error")
        error_code = error.get("code") if isinstance(error, dict) else error
        safe_fields = {
            key: decision[key]
            for key in ("approval_id", "approval_required", "request_type", "status", "decisions")
            if key in decision
        }
        raise M365ProviderError(
            str(error_code or "source_not_authorized"),
            "Microsoft 365 source access requires the data user's authorization.",
            details=safe_fields,
        )
    return get_m365_context(), decision


def _delegated_token(scopes: Iterable[str], context):
    from functions_m365_connections import get_m365_access_token

    return get_m365_access_token(list(scopes), context=context)


def _retry_after_seconds(raw_value: Any) -> Optional[int]:
    if raw_value is None:
        return None
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        try:
            retry_time = parsedate_to_datetime(str(raw_value))
            if retry_time.tzinfo is None:
                retry_time = retry_time.replace(tzinfo=timezone.utc)
            return max(0, int((retry_time - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None


def sanitize_m365_graph_payload(value: Any, *, _depth: int = 0):
    """Preauthenticated download links are transport secrets, including on legacy list responses."""
    if _depth > 20:
        raise M365ProviderError("response_depth_limit", "Microsoft Graph returned an excessively nested response.")
    if isinstance(value, dict):
        return {
            key: sanitize_m365_graph_payload(item, _depth=_depth + 1)
            for key, item in value.items()
            if re.sub(r"[^a-z]", "", str(key).lower()) not in ("downloadurl", "microsoftgraphdownloadurl")
        }
    if isinstance(value, list):
        return [sanitize_m365_graph_payload(item, _depth=_depth + 1) for item in value]
    return value


class _NoDownloadCredentials(requests.auth.AuthBase):
    def __call__(self, request):
        request.headers.pop("Authorization", None)
        request.headers.pop("Cookie", None)
        return request


@dataclass(frozen=True)
class M365DownloadedFile:
    path: str
    size_bytes: int
    mime_type: str
    sha256: str


class M365Transport:
    def __init__(
        self,
        source: Optional[str],
        action_id: str = "",
        action_policy: Any = None,
        *,
        cloud: Optional[M365CloudConfig] = None,
        request: Optional[Callable] = None,
        token_provider: Optional[Callable] = None,
        action_type: Optional[str] = None,
    ):
        if source is not None and source not in M365_SOURCES:
            raise M365ProviderError("invalid_source", "Unsupported Microsoft 365 source.")
        self.source = source
        self.action_id = str(action_id or "")
        self.action_policy = action_policy or {"maximum_sharing_acknowledgement": "always"}
        self.action_type = action_type
        self._cloud = cloud
        self._request = request or requests.request
        self._token_provider = token_provider or _delegated_token

    @property
    def before_request(self):
        return _TRANSPORT_CALLBACKS.get().get(id(self), (None, None))[0]

    @property
    def on_progress(self):
        return _TRANSPORT_CALLBACKS.get().get(id(self), (None, None))[1]

    @property
    def current_operation(self):
        return _TRANSPORT_OPERATIONS.get().get(id(self))

    @contextmanager
    def operation_context(self, operation_name):
        operation_name = M365_INTERNAL_OPERATION_FUNCTIONS.get(operation_name, operation_name)
        operations = {**_TRANSPORT_OPERATIONS.get(), id(self): operation_name}
        token = _TRANSPORT_OPERATIONS.set(operations)
        try:
            yield
        finally:
            _TRANSPORT_OPERATIONS.reset(token)

    @contextmanager
    def callback_context(self, before_request, on_progress):
        # A reused plugin must not borrow another actor's cancellation/worker lease callbacks.
        callbacks = {**_TRANSPORT_CALLBACKS.get(), id(self): (before_request, on_progress)}
        token = _TRANSPORT_CALLBACKS.set(callbacks)
        try:
            yield
        finally:
            _TRANSPORT_CALLBACKS.reset(token)

    @property
    def cloud(self) -> M365CloudConfig:
        if self._cloud is None:
            self._cloud = get_m365_cloud_config()
        return self._cloud

    def graph_url(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise M365ProviderError("invalid_graph_path", "A valid Graph operation path is required.")
        if path.startswith("/v1.0/"):
            path = path[len("/v1.0"):]
        url = path if urlsplit(path).scheme else f"{self.cloud.graph_base_url}/{path.lstrip('/')}"
        parts = _https_parts(url)
        base = urlsplit(self.cloud.graph_base_url)
        decoded_path = unquote(unquote(parts.path))
        if (
            parts.hostname != base.hostname
            or (parts.port or 443) != (base.port or 443)
            or not (parts.path == base.path or parts.path.startswith(f"{base.path}/"))
            or "\\" in decoded_path
            or any(segment in (".", "..") for segment in decoded_path.split("/"))
        ):
            raise M365ProviderError("untrusted_graph_url", "Graph links must stay within the configured Microsoft 365 endpoint.")
        return url

    def qualify_scopes(self, scopes: Iterable[str]) -> List[str]:
        qualified = []
        for scope in scopes:
            if not isinstance(scope, str) or not scope:
                raise M365ProviderError("invalid_scope", "A delegated Microsoft Graph scope is required.")
            if "://" in scope:
                prefix = f"{self.cloud.resource_url}/"
                if not scope.startswith(prefix) or not re.fullmatch(r"[A-Za-z][A-Za-z.]+", scope[len(prefix):]):
                    raise M365ProviderError("invalid_scope", "Scopes must target the configured Microsoft Graph resource.")
                qualified.append(scope)
            elif re.fullmatch(r"[A-Za-z][A-Za-z.]+", scope) and scope != ".default":
                qualified.append(f"{self.cloud.resource_url}/{scope}")
            else:
                raise M365ProviderError("invalid_scope", "A delegated Microsoft Graph scope is required.")
        if not qualified:
            raise M365ProviderError("invalid_scope", "At least one delegated Microsoft Graph scope is required.")
        return list(dict.fromkeys(qualified))

    def get_token(self, scopes: Iterable[str]):
        if self.source:
            context, _ = authorize_m365_source(
                self.source, self.action_id, self.action_policy,
                operation_name=self.current_operation, action_type=self.action_type,
            )
        elif self.current_operation is not None:
            authorize_m365_capability(
                self.action_id, self.current_operation, self.action_type,
            )
            context = get_m365_context()
        else:
            context = get_m365_context()
        qualified = self.qualify_scopes(scopes)
        result = self._token_provider(qualified, context)
        if isinstance(result, dict) and isinstance(result.get("access_token"), str) and result["access_token"]:
            return result["access_token"], qualified
        result = result if isinstance(result, dict) else {}
        code = result.get("error")
        code = code.get("code") if isinstance(code, dict) else code
        safe_fields = {
            key: result[key]
            for key in ("approval_id", "requires_interactive_auth", "requires_consent", "auth_url", "consent_url")
            if key in result
        }
        safe_fields["scopes"] = qualified
        requested_names = {scope.rsplit("/", 1)[-1] for scope in qualified}
        reported_scopes = result.get("scopes")
        if (
            isinstance(reported_scopes, list) and reported_scopes
            and all(
                isinstance(scope, str) and (scope in requested_names or scope in qualified)
                for scope in reported_scopes
            )
        ):
            safe_fields["scopes"] = list(dict.fromkeys(reported_scopes))
        message = "The data user must sign in or grant the required delegated Microsoft 365 permissions."
        if result.get("profile_url") == "/profile":
            safe_fields["profile_url"] = "/profile"
            message = "Reconnect Microsoft 365 in Profile with the required permissions for this workflow."
        raise M365ProviderError(
            str(code or "interactive_auth_required"),
            message,
            details=safe_fields,
        )

    def _send(self, method: str, url: str, *, secret_url: bool = False, **kwargs):
        if self.before_request is not None:
            self.before_request()
        if secret_url and self.source and self.current_operation is not None:
            authorize_m365_source(
                self.source, self.action_id, self.action_policy,
                operation_name=self.current_operation, action_type=self.action_type,
            )
        try:
            # Dependency telemetry normally captures full URLs, including preauthenticated query strings.
            with suppress_instrumentation() if secret_url else nullcontext():
                return self._request(
                    method, url,
                    timeout=M365_REQUEST_TIMEOUT,
                    allow_redirects=False,
                    stream=True,
                    **kwargs,
                )
        except requests.Timeout as exc:
            raise M365ProviderError("timeout", "The Microsoft 365 request timed out.") from exc
        except requests.RequestException as exc:
            raise M365ProviderError("transport_error", "The Microsoft 365 service could not be reached.") from exc

    def _read_response_bytes(self, response, max_bytes: int) -> bytes:
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                declared_size = int(length)
            except (TypeError, ValueError) as exc:
                raise M365ProviderError("invalid_content_length", "The Microsoft 365 response has an invalid content length.") from exc
            if declared_size < 0 or declared_size > max_bytes:
                raise M365ProviderError("response_size_limit", "The Microsoft 365 response exceeds the safe response limit.")
        chunks = []
        size = 0
        started = time.monotonic()
        try:
            for chunk in response.iter_content(chunk_size=M365_DOWNLOAD_CHUNK_BYTES):
                if time.monotonic() - started > M365_JSON_READ_MAX_SECONDS:
                    raise M365ProviderError("timeout", "The Microsoft 365 response exceeded its bounded read time.")
                size += len(chunk)
                if size > max_bytes:
                    raise M365ProviderError("response_size_limit", "The Microsoft 365 response exceeds the safe response limit.")
                if self.on_progress is not None:
                    self.on_progress()
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise M365ProviderError("incomplete_response", "The Microsoft 365 response was interrupted.") from exc
        return b"".join(chunks)

    def _response_error(self, response, payload: Any = None, *, auth_scopes=None) -> M365ProviderError:
        status = response.status_code
        provider_error = payload.get("error") if isinstance(payload, dict) else None
        raw_code = provider_error.get("code") if isinstance(provider_error, dict) else ""
        code_map = {
            401: ("authentication_required", "The data user's Microsoft 365 sign-in must be renewed."),
            403: ("access_denied", "Microsoft 365 denied access or blocked this operation by policy."),
            404: ("not_found", "The Microsoft 365 resource was not found or is no longer accessible."),
            409: ("source_conflict", "The Microsoft 365 resource changed during this operation."),
            412: ("source_changed", "The file changed; capture a new source version before continuing."),
            429: ("throttled", "Microsoft 365 throttled this request. Resume after the retry interval."),
            503: ("service_unavailable", "The Microsoft 365 service is temporarily unavailable."),
        }
        code, message = code_map.get(status, ("provider_error", "Microsoft 365 could not complete this operation."))
        details = {}
        if status == 401 and auth_scopes:
            # A rejected Graph bearer token must not be reused just because its cache entry is unexpired.
            from functions_m365_connections import mark_m365_chat_reconnect_required
            mark_m365_chat_reconnect_required(get_m365_context())
            details["scopes"] = list(auth_scopes)
            if self.source:
                details["sources"] = [self.source]
        if status == 403 or str(raw_code).lower() in (
            "blockedbypolicy", "policydenied", "informationprotectionpolicy", "accessdenied",
        ):
            details["policy_refusal"] = True
        if status in (400, 404, 501) and raw_code in ("notSupported", "NotSupported", "UnsupportedApiVersion"):
            details["api_unsupported"] = True
        return M365ProviderError(
            code, message, status_code=status,
            retry_after_seconds=_retry_after_seconds(response.headers.get("Retry-After")),
            details=details,
        )

    def request_json(
        self,
        method: str,
        path: str,
        scopes: Iterable[str],
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        additional_headers: Optional[Dict[str, str]] = None,
        expect_json: bool = True,
    ) -> Dict[str, Any]:
        url = self.graph_url(path)
        token, qualified_scopes = self.get_token(scopes)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        for key, value in (additional_headers or {}).items():
            if key.lower() not in ("prefer", "consistencylevel", "if-match", "if-none-match", "content-type"):
                raise M365ProviderError("invalid_header", "Unsupported Microsoft Graph request header.")
            headers[key] = value
        response = self._send(method.upper(), url, headers=headers, params=params, json=json_body)
        try:
            if 300 <= response.status_code < 400:
                raise M365ProviderError("unexpected_redirect", "Microsoft Graph returned an unsupported API redirect.")
            body = self._read_response_bytes(response, M365_JSON_MAX_BYTES)
            try:
                payload = json.loads(body) if body else {}
            except (UnicodeError, ValueError, RecursionError) as exc:
                if response.status_code >= 400:
                    raise self._response_error(response, auth_scopes=qualified_scopes) from exc
                raise M365ProviderError("invalid_response", "Microsoft Graph returned an invalid JSON response.") from exc
            if response.status_code >= 400:
                raise self._response_error(response, payload, auth_scopes=qualified_scopes)
            if not 200 <= response.status_code < 300:
                raise M365ProviderError("invalid_response", "Microsoft Graph returned an unexpected response status.")
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                raise self._response_error(response, payload, auth_scopes=qualified_scopes)
            if not expect_json:
                result = {"status_code": response.status_code, "accepted": True}
                if payload:
                    result["value"] = sanitize_m365_graph_payload(payload)
                return result
            if not isinstance(payload, dict):
                raise M365ProviderError("invalid_response", "Microsoft Graph returned an unexpected response shape.")
            next_link = payload.get("@odata.nextLink")
            if next_link:
                self.graph_url(next_link)
            return sanitize_m365_graph_payload(payload)
        finally:
            response.close()

    @contextmanager
    def download_file(
        self,
        drive_id: str,
        item_id: str,
        *,
        suffix: str,
        allowed_mime_types: Iterable[str],
        max_bytes: int,
        etag: str = "",
    ):
        if not 0 < max_bytes <= M365_FILE_HARD_MAX_BYTES:
            raise M365ProviderError("invalid_download_limit", "Invalid Microsoft 365 file download limit.")
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            raise M365ProviderError("unsupported_format", "This file format is not supported for extraction.")
        url = self.graph_url(f"/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/content")
        token, qualified_scopes = self.get_token(["Files.Read.All"])
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"}
        if etag:
            headers["If-Match"] = etag
        response = None
        local_path = None
        started = time.monotonic()
        graph_authorized = True
        try:
            response = self._send("GET", url, headers=headers)
            for redirect_index in range(M365_MAX_DOWNLOAD_REDIRECTS + 1):
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                if redirect_index == M365_MAX_DOWNLOAD_REDIRECTS:
                    raise M365ProviderError("redirect_limit", "The Microsoft 365 file exceeded the download redirect limit.")
                location = response.headers.get("Location")
                if not isinstance(location, str) or len(location) > 16384:
                    raise M365ProviderError("invalid_download_redirect", "Microsoft 365 returned an invalid file download redirect.")
                self.cloud.validate_content_url(location)
                response.close()
                response = self._send(
                    "GET", location,
                    headers={"Accept": "application/octet-stream"},
                    auth=_NoDownloadCredentials(),
                    secret_url=True,
                )
                graph_authorized = False
            if response.status_code >= 400:
                if response.status_code == 401 and not graph_authorized:
                    raise M365ProviderError(
                        "download_link_expired", "The temporary file link expired. Request a fresh copy of this file.",
                        status_code=401,
                    )
                raise self._response_error(
                    response, auth_scopes=qualified_scopes if graph_authorized else None,
                )
            if response.status_code != 200:
                raise M365ProviderError("incomplete_download", "Microsoft 365 did not return the complete file.")
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in set(allowed_mime_types) | {"application/octet-stream", "binary/octet-stream"}:
                raise M365ProviderError("unsupported_content_type", "The downloaded file has an unexpected content type.")
            raw_length = response.headers.get("Content-Length")
            try:
                length = int(raw_length) if raw_length is not None else None
            except (TypeError, ValueError) as exc:
                raise M365ProviderError("invalid_content_length", "The file has an invalid content length.") from exc
            if length is not None and (length < 0 or length > max_bytes):
                raise M365ProviderError(
                    "file_size_limit", "The file exceeds the approved download size.",
                    details={"limit_bytes": max_bytes, "observed_bytes": length},
                )
            with tempfile.NamedTemporaryFile(prefix="simplechat-m365-", suffix=suffix, delete=False) as output:
                local_path = Path(output.name)
                digest = hashlib.sha256()
                total = 0
                try:
                    for chunk in response.iter_content(chunk_size=M365_DOWNLOAD_CHUNK_BYTES):
                        if time.monotonic() - started > M365_DOWNLOAD_MAX_SECONDS:
                            raise M365ProviderError("timeout", "The Microsoft 365 file exceeded its bounded download time.")
                        total += len(chunk)
                        if total > max_bytes:
                            raise M365ProviderError(
                                "file_size_limit", "The file exceeds the approved download size.",
                                details={"limit_bytes": max_bytes, "observed_bytes": total},
                            )
                        if self.on_progress is not None:
                            self.on_progress()
                        digest.update(chunk)
                        output.write(chunk)
                except requests.RequestException as exc:
                    raise M365ProviderError("incomplete_download", "The Microsoft 365 file download was interrupted.") from exc
            if length is not None and not response.headers.get("Content-Encoding") and length != total:
                raise M365ProviderError("incomplete_download", "The Microsoft 365 file download was incomplete.")
            yield M365DownloadedFile(str(local_path), total, mime, digest.hexdigest())
        finally:
            if response is not None:
                response.close()
            if local_path is not None:
                try:
                    local_path.unlink(missing_ok=True)
                except OSError as exc:
                    log_m365_failure("temporary_cleanup_failed", source=self.source or "", operation="download_file")
                    raise M365ProviderError("temporary_cleanup_failed", "The temporary Microsoft 365 download could not be cleaned up.") from exc
