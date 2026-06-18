# functions_dlp_presidio.py

"""HTTP adapter for Presidio-compatible Analyzer endpoints."""

import ipaddress
import os
import re
import socket
from urllib.parse import parse_qsl, urlparse

import requests


DEFAULT_PRESIDIO_TIMEOUT_SECONDS = 5
DEFAULT_PRESIDIO_LANGUAGE = "en"
DEFAULT_PRESIDIO_SCORE_THRESHOLD = 0.5
DEFAULT_PRESIDIO_AUTH_HEADER_NAME = "X-DLP-API-Key"
DEFAULT_PRESIDIO_AUTH_SECRET_ENV_VAR = "PRESIDIO_DLP_API_KEY"
PRESIDIO_AUTH_SECRET_ENV_VAR_PREFIX = "DLP_PRESIDIO_"
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


def _validate_resolved_presidio_addresses(host, port, allowed_hosts):
    normalized_host = _normalize_host_identifier(host)
    addresses = _resolve_presidio_host_addresses(normalized_host, port)
    if not addresses:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint host must resolve to an IP address.")
    if normalized_host in allowed_hosts:
        return
    if any(not address.is_global for address in addresses):
        raise PresidioEndpointConfigurationError(
            "Private Presidio analyzer endpoint hosts must be listed in the private host allowlist."
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


def _get_auth_headers(settings):
    header_name = str((settings or {}).get("dlp_presidio_auth_header_name") or DEFAULT_PRESIDIO_AUTH_HEADER_NAME).strip()
    secret_env_var = normalize_presidio_secret_env_var_name(
        (settings or {}).get("dlp_presidio_auth_secret_env_var") or ""
    )
    if not header_name or not secret_env_var:
        return {}

    secret_value = os.getenv(secret_env_var, "")
    if not secret_value:
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
        **_get_auth_headers(settings),
    }

    request_error_type = None
    try:
        response = requests.post(
            endpoint_url,
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=False,
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
