# functions_dlp_presidio.py

"""HTTP adapter for Presidio-compatible Analyzer endpoints."""

import ipaddress
import os
import re
import socket
from urllib.parse import parse_qsl, urlparse

import requests
from urllib3 import connection as urllib3_connection
from urllib3 import connectionpool as urllib3_connectionpool
from urllib3 import poolmanager as urllib3_poolmanager
from urllib3.util import connection as urllib3_util_connection
from urllib3.util.timeout import Timeout as _Urllib3Timeout


# urllib3 uses a sentinel to mean "leave the socket on its default timeout instead of
# calling settimeout()". That sentinel is only exposed privately, and under a different
# name per major version: urllib3 2.x has urllib3.util.timeout._DEFAULT_TIMEOUT while
# urllib3 1.x uses socket._GLOBAL_DEFAULT_TIMEOUT. Timeout.DEFAULT_TIMEOUT is the public
# alias and is the identical object on both, so resolving it here keeps the connect
# behavior byte-for-byte the same without importing a private, version-specific symbol
# on the DLP request path.
try:
    PRESIDIO_DEFAULT_SOCKET_TIMEOUT = _Urllib3Timeout.DEFAULT_TIMEOUT
except AttributeError:  # pragma: no cover - only if urllib3 drops the public alias
    PRESIDIO_DEFAULT_SOCKET_TIMEOUT = socket._GLOBAL_DEFAULT_TIMEOUT


def _build_presidio_name_resolution_error(connection, exc):
    """Return the urllib3 DNS failure error for the installed urllib3 version.

    urllib3 2.x raises NameResolutionError, which does not exist on 1.x. It subclasses
    NewConnectionError, so callers that catch the base class behave the same either way.
    """
    name_resolution_error = getattr(urllib3_connection, "NameResolutionError", None)
    if name_resolution_error is not None:
        return name_resolution_error(connection.host, connection, exc)
    return urllib3_connection.NewConnectionError(
        connection,
        f"Failed to resolve {connection.host}: {exc}",
    )


DEFAULT_PRESIDIO_TIMEOUT_SECONDS = 5
DEFAULT_PRESIDIO_LANGUAGE = "en"
DEFAULT_PRESIDIO_SCORE_THRESHOLD = 0.5
DEFAULT_PRESIDIO_AUTH_HEADER_NAME = "X-DLP-API-Key"
DEFAULT_PRESIDIO_AUTH_SECRET_ENV_VAR = "PRESIDIO_DLP_API_KEY"
PRESIDIO_AUTH_SECRET_ENV_VAR_PREFIX = "DLP_PRESIDIO_"
PRESIDIO_AUTH_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
PRESIDIO_RESERVED_AUTH_HEADERS = {
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "expect",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "set-cookie",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
PRESIDIO_CREDENTIAL_QUERY_NAMES = {
    "key",
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "connection",
    "sig",
}
PRESIDIO_CREDENTIAL_QUERY_WORDS = {
    "key",
    "secret",
    "token",
    "password",
    "connection",
    "sig",
}
PRESIDIO_PRIVATE_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localdomain",
    ".lan",
    ".home",
    ".corp",
)
PRESIDIO_LOCAL_HOSTS = {"localhost"}
PRESIDIO_SECRET_ENV_VAR_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class PresidioEndpointConfigurationError(ValueError):
    """Raised when the configured Presidio endpoint is not safe to call."""


class PresidioEndpointRequestError(RuntimeError):
    """Raised when the Presidio endpoint cannot return a usable analyzer result."""


def _normalize_host_identifier(host):
    normalized = str(host or "").strip().lower().strip(".")
    if normalized.startswith("[") and "]" in normalized:
        normalized = normalized[1:normalized.index("]")]
    if "://" in normalized:
        normalized = (urlparse(normalized).hostname or "").strip().lower().strip(".")
    return normalized


def normalize_presidio_allowed_private_hosts(value):
    """Normalize the admin allowlist for private Presidio endpoint hosts."""
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = re.split(r"[\n,]+", str(value or ""))

    normalized_hosts = []
    seen_hosts = set()
    for item in raw_items:
        host = _normalize_host_identifier(item)
        if not host or host in seen_hosts:
            continue
        normalized_hosts.append(host)
        seen_hosts.add(host)
    return ", ".join(normalized_hosts)


def _get_allowed_private_hosts(allowed_private_hosts):
    normalized_allowlist = normalize_presidio_allowed_private_hosts(allowed_private_hosts)
    if not normalized_allowlist:
        return set()
    return {
        item.strip()
        for item in normalized_allowlist.split(",")
        if item.strip()
    }


def _is_private_presidio_host(host):
    normalized_host = _normalize_host_identifier(host)
    if not normalized_host:
        return True
    if normalized_host in PRESIDIO_LOCAL_HOSTS or normalized_host.endswith(".localhost"):
        return True
    try:
        ip_address = ipaddress.ip_address(normalized_host)
        return not ip_address.is_global
    except ValueError:
        return normalized_host.endswith(PRESIDIO_PRIVATE_HOST_SUFFIXES)


def _is_loopback_presidio_host(host):
    normalized_host = _normalize_host_identifier(host)
    if normalized_host in PRESIDIO_LOCAL_HOSTS or normalized_host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False


def _is_ip_literal(host):
    try:
        ipaddress.ip_address(_normalize_host_identifier(host))
        return True
    except ValueError:
        return False


def _resolve_presidio_host_addresses(host, port):
    normalized_host = _normalize_host_identifier(host)
    if not normalized_host:
        return []
    if _is_ip_literal(normalized_host):
        return [ipaddress.ip_address(normalized_host)]

    try:
        address_info = socket.getaddrinfo(
            normalized_host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint host must resolve in DNS.") from exc

    return _extract_presidio_addresses(address_info)


def _extract_presidio_addresses(address_info):
    addresses = []
    seen_addresses = set()
    for item in address_info:
        sockaddr = item[4] if len(item) > 4 else None
        if not sockaddr:
            continue
        raw_address = str(sockaddr[0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            continue
        if address in seen_addresses:
            continue
        addresses.append(address)
        seen_addresses.add(address)
    return addresses


def _validate_presidio_address_list(host, addresses, allowed_hosts):
    normalized_host = _normalize_host_identifier(host)
    if not addresses:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint host must resolve to an IP address.")
    if normalized_host in allowed_hosts:
        return
    if any(not address.is_global for address in addresses):
        raise PresidioEndpointConfigurationError(
            "Private Presidio analyzer endpoint hosts must be listed in the private host allowlist."
        )


def _validate_resolved_presidio_addresses(host, port, allowed_hosts):
    normalized_host = _normalize_host_identifier(host)
    addresses = _resolve_presidio_host_addresses(normalized_host, port)
    _validate_presidio_address_list(normalized_host, addresses, allowed_hosts)


def _set_socket_options(sock, socket_options):
    for option in socket_options or []:
        sock.setsockopt(*option)


def _create_presidio_safe_socket_connection(host, port, timeout, source_address, socket_options, allowed_hosts):
    connect_host = str(host or "")
    if connect_host.startswith("["):
        connect_host = connect_host.strip("[]")
    connect_host.encode("idna")

    address_info = socket.getaddrinfo(
        connect_host,
        port,
        urllib3_util_connection.allowed_gai_family(),
        socket.SOCK_STREAM,
    )
    _validate_presidio_address_list(connect_host, _extract_presidio_addresses(address_info), allowed_hosts)

    last_error = None
    for family, socktype, proto, _canonname, sockaddr in address_info:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            _set_socket_options(sock, socket_options)
            if timeout is not PRESIDIO_DEFAULT_SOCKET_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            last_error = None
            return sock
        except OSError as exc:
            last_error = exc
            if sock is not None:
                sock.close()

    if last_error is not None:
        raise last_error
    raise OSError("getaddrinfo returns an empty list")


class _PresidioSSRFConnectionMixin:
    presidio_allowed_private_hosts = frozenset()

    def _new_conn(self):
        try:
            return _create_presidio_safe_socket_connection(
                self._dns_host,
                self.port,
                self.timeout,
                self.source_address,
                self.socket_options,
                self.presidio_allowed_private_hosts,
            )
        except socket.gaierror as exc:
            raise _build_presidio_name_resolution_error(self, exc) from exc
        except urllib3_connection.SocketTimeout as exc:
            raise urllib3_connection.ConnectTimeoutError(
                self,
                f"Connection to {self.host} timed out. (connect timeout={self.timeout})",
            ) from exc
        except OSError as exc:
            raise urllib3_connection.NewConnectionError(
                self,
                f"Failed to establish a new connection: {exc}",
            ) from exc


def _build_presidio_pool_classes(allowed_hosts):
    class PresidioSSRFHTTPConnection(_PresidioSSRFConnectionMixin, urllib3_connection.HTTPConnection):
        presidio_allowed_private_hosts = allowed_hosts

    class PresidioSSRFHTTPSConnection(_PresidioSSRFConnectionMixin, urllib3_connection.HTTPSConnection):
        presidio_allowed_private_hosts = allowed_hosts

    class PresidioSSRFHTTPConnectionPool(urllib3_connectionpool.HTTPConnectionPool):
        ConnectionCls = PresidioSSRFHTTPConnection

    class PresidioSSRFHTTPSConnectionPool(urllib3_connectionpool.HTTPSConnectionPool):
        ConnectionCls = PresidioSSRFHTTPSConnection

    return {
        "http": PresidioSSRFHTTPConnectionPool,
        "https": PresidioSSRFHTTPSConnectionPool,
    }


class _PresidioSSRFHTTPAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, allowed_hosts, *args, **kwargs):
        self._presidio_pool_classes = _build_presidio_pool_classes(frozenset(allowed_hosts))
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = urllib3_poolmanager.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )
        self.poolmanager.pool_classes_by_scheme = self._presidio_pool_classes


def _build_presidio_endpoint_session(allowed_private_hosts):
    session = requests.Session()
    session.trust_env = False
    adapter = _PresidioSSRFHTTPAdapter(_get_allowed_private_hosts(allowed_private_hosts))
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _post_presidio_endpoint(endpoint_url, json, headers, timeout, allow_redirects, allowed_private_hosts):
    with _build_presidio_endpoint_session(allowed_private_hosts) as session:
        return session.post(
            endpoint_url,
            json=json,
            headers=headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )


def normalize_presidio_secret_env_var_name(secret_env_var):
    """Return an allowed Presidio secret env var name, or blank when invalid."""
    normalized = str(secret_env_var or "").strip()
    if not normalized:
        return ""
    if normalized == DEFAULT_PRESIDIO_AUTH_SECRET_ENV_VAR:
        return normalized
    if (
        normalized.startswith(PRESIDIO_AUTH_SECRET_ENV_VAR_PREFIX)
        and PRESIDIO_SECRET_ENV_VAR_PATTERN.fullmatch(normalized)
    ):
        return normalized
    return ""


def normalize_presidio_auth_header_name(header_name):
    """Return an allowed Presidio auth header name, or blank when invalid."""
    normalized = str(header_name or "").strip()
    if not normalized:
        return DEFAULT_PRESIDIO_AUTH_HEADER_NAME
    if not PRESIDIO_AUTH_HEADER_NAME_PATTERN.fullmatch(normalized):
        return ""
    if normalized.lower() in PRESIDIO_RESERVED_AUTH_HEADERS:
        return ""
    return normalized


def _is_credential_like_query_name(query_name):
    normalized = str(query_name or "").strip().lower()
    if not normalized:
        return False
    compact_name = re.sub(r"[^a-z0-9]+", "", normalized)
    query_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalized)
        if token
    }
    if normalized in PRESIDIO_CREDENTIAL_QUERY_NAMES or compact_name in PRESIDIO_CREDENTIAL_QUERY_NAMES:
        return True
    if query_tokens & PRESIDIO_CREDENTIAL_QUERY_WORDS:
        return True
    return any(credential_word in compact_name for credential_word in PRESIDIO_CREDENTIAL_QUERY_WORDS)


def validate_presidio_endpoint_url(endpoint_url, allowed_private_hosts=None):
    """Validate and normalize a Presidio Analyzer endpoint URL."""
    normalized = str(endpoint_url or "").strip()
    if not normalized:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint is required.")

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    normalized_host = _normalize_host_identifier(host)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint URL must not include userinfo.")
    if parsed.fragment:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint URL must not include a fragment.")
    for query_name, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_credential_like_query_name(query_name):
            raise PresidioEndpointConfigurationError(
                "Presidio analyzer endpoint URL must not include credential-like query parameters."
            )

    host_is_private = _is_private_presidio_host(host)
    allowed_hosts = _get_allowed_private_hosts(allowed_private_hosts)
    if host_is_private and normalized_host not in allowed_hosts:
        raise PresidioEndpointConfigurationError(
            "Private Presidio analyzer endpoint hosts must be listed in the private host allowlist."
        )
    if parsed.scheme == "http" and not _is_loopback_presidio_host(host):
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint must use HTTPS unless it is localhost.")
    _validate_resolved_presidio_addresses(
        host,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        allowed_hosts,
    )

    return normalized


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_entities(settings):
    entities = (settings or {}).get("dlp_presidio_entities", [])
    if isinstance(entities, str):
        entities = [item.strip().upper() for item in entities.split(",")]
    if not isinstance(entities, list):
        return []
    return [str(item).strip().upper() for item in entities if str(item).strip()]


def _get_auth_headers(settings, require_secret=False):
    header_name = normalize_presidio_auth_header_name(
        (settings or {}).get("dlp_presidio_auth_header_name") or DEFAULT_PRESIDIO_AUTH_HEADER_NAME
    )
    if not header_name:
        raise PresidioEndpointConfigurationError("Presidio auth header name is not allowed.")

    secret_env_var = normalize_presidio_secret_env_var_name(
        (settings or {}).get("dlp_presidio_auth_secret_env_var") or DEFAULT_PRESIDIO_AUTH_SECRET_ENV_VAR
    )
    if not secret_env_var:
        if require_secret:
            raise PresidioEndpointConfigurationError(
                "Presidio analyzer endpoints outside localhost require an auth secret env var."
            )
        return {}

    secret_value = os.getenv(secret_env_var, "")
    if not secret_value:
        if require_secret:
            raise PresidioEndpointConfigurationError(
                "Presidio analyzer endpoints outside localhost require the configured auth secret env var to be set."
            )
        return {}
    return {header_name: secret_value}


def _normalize_result_item(item):
    if not isinstance(item, dict):
        return None
    if "entity_type" not in item or item.get("start") is None or item.get("end") is None:
        return None
    try:
        return {
            "entity_type": str(item.get("entity_type") or ""),
            "start": int(item.get("start")),
            "end": int(item.get("end")),
            "score": float(item.get("score", 0.0)),
        }
    except (TypeError, ValueError):
        return None


def analyze_with_presidio_endpoint(text, settings):
    """Call a configured Presidio Analyzer endpoint and return recognizer results."""
    settings = settings or {}
    endpoint_url = validate_presidio_endpoint_url(
        settings.get("dlp_presidio_analyzer_endpoint"),
        settings.get("dlp_presidio_allowed_private_hosts"),
    )
    endpoint_host = urlparse(endpoint_url).hostname or ""
    require_auth_secret = not _is_loopback_presidio_host(endpoint_host)
    timeout_seconds = max(
        1,
        min(30, _safe_int(settings.get("dlp_presidio_timeout_seconds"), DEFAULT_PRESIDIO_TIMEOUT_SECONDS)),
    )
    score_threshold = max(
        0.0,
        min(1.0, _safe_float(settings.get("dlp_presidio_score_threshold"), DEFAULT_PRESIDIO_SCORE_THRESHOLD)),
    )
    language = str(settings.get("dlp_presidio_language") or DEFAULT_PRESIDIO_LANGUAGE).strip() or DEFAULT_PRESIDIO_LANGUAGE
    payload = {
        "text": str(text or ""),
        "language": language,
        "entities": _get_entities(settings),
        "score_threshold": score_threshold,
    }
    headers = {
        "Content-Type": "application/json",
        **_get_auth_headers(settings, require_secret=require_auth_secret),
    }

    request_error_type = None
    try:
        response = _post_presidio_endpoint(
            endpoint_url,
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=False,
            allowed_private_hosts=settings.get("dlp_presidio_allowed_private_hosts"),
        )
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 300 <= status_code < 400:
            request_error_type = "RedirectResponse"
            body = None
        else:
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        request_error_type = type(exc).__name__

    if request_error_type:
        raise PresidioEndpointRequestError(f"Presidio analyzer request failed: {request_error_type}") from None

    if not isinstance(body, list):
        raise PresidioEndpointRequestError("Presidio analyzer response must be a list.")

    results = []
    for item in body:
        normalized = _normalize_result_item(item)
        if normalized:
            results.append(normalized)
    return results
