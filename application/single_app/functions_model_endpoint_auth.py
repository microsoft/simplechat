# functions_model_endpoint_auth.py
"""Authentication schemes for Custom model endpoints.

Custom endpoints originally supported one scheme: an API key sent in whichever
header the built-in providers happened to use. That covers OpenAI and Anthropic
and nothing else. A gateway that expects "x-goog-api-key", a corporate gateway
that issues short-lived OAuth2 tokens, and an on-premises appliance that requires
a client certificate were all unreachable.

This module adds those schemes without widening what the browser can see: every
secret stays server-side, and OAuth2 token responses are never surfaced to a
caller beyond the token itself.

mTLS is deliberately modelled as a transport concern rather than an auth "type",
because a client certificate combines with any of the schemes below. Certificates
are referenced by file path rather than stored in settings, so a private key is
mounted into the deployment and never written to the configuration database.
"""

import threading
import time
from typing import Any, Dict, Tuple

import httpx

from functions_model_endpoint_diagnostics import build_sanitized_model_endpoint_error


AUTH_TYPE_API_KEY = "api_key"
AUTH_TYPE_KEY = "key"
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"

CUSTOM_ENDPOINT_AUTH_TYPES = (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_BEARER,
    AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS,
)

# Refresh slightly before expiry so a token cannot lapse mid-request.
OAUTH2_EXPIRY_SKEW_SECONDS = 60
OAUTH2_DEFAULT_EXPIRY_SECONDS = 3600
OAUTH2_REQUEST_TIMEOUT_SECONDS = 30

_TOKEN_CACHE: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()


def normalize_custom_endpoint_auth_type(auth_type: Any) -> str:
    """Return a supported Custom endpoint auth type, defaulting to API key."""
    normalized = str(auth_type or "").strip().lower()
    if normalized == AUTH_TYPE_KEY:
        return AUTH_TYPE_API_KEY
    return normalized if normalized in CUSTOM_ENDPOINT_AUTH_TYPES else ""


def resolve_api_key_header(
    auth: Dict[str, Any],
    default_header: str = "",
    default_prefix: str = "",
) -> Tuple[str, str]:
    """Return the header name and value prefix used to send an API key.

    Providers disagree about this. OpenAI uses "Authorization: Bearer", Anthropic
    uses "x-api-key" with no prefix, Google uses "x-goog-api-key", and gateways
    invent their own. Making both configurable is what lets one auth type cover
    all of them.

    An administrator override wins over the provider default. An override that
    names a header but no prefix means exactly that, so the provider's prefix is
    not reapplied.
    """
    auth = auth or {}
    override_header = str(auth.get("api_key_header") or "").strip()
    if override_header:
        return override_header, str(auth.get("api_key_prefix") or "").strip()

    header_name = str(default_header or "").strip()
    prefix = str(auth.get("api_key_prefix") or default_prefix or "").strip()
    return header_name, prefix


def build_api_key_headers(
    auth: Dict[str, Any],
    default_header: str = "",
    default_prefix: str = "",
) -> Dict[str, str]:
    """Build the request headers that carry a configured API key."""
    api_key = str((auth or {}).get("api_key") or "").strip()
    if not api_key:
        raise ValueError("Selected model endpoint is missing an API key.")

    header_name, prefix = resolve_api_key_header(auth, default_header, default_prefix)
    if not header_name:
        return {}
    header_value = f"{prefix} {api_key}".strip() if prefix else api_key
    return {header_name: header_value}


def build_bearer_headers(auth: Dict[str, Any]) -> Dict[str, str]:
    """Build the request headers for a static bearer token."""
    token = str((auth or {}).get("bearer_token") or "").strip()
    if not token:
        raise ValueError("Selected model endpoint is missing a bearer token.")
    return {"Authorization": f"Bearer {token}"}


def _token_cache_key(auth: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(auth.get("token_url") or "").strip(),
        str(auth.get("client_id") or "").strip(),
        str(auth.get("scope") or "").strip(),
    )


def clear_oauth2_token_cache() -> None:
    """Drop every cached OAuth2 token."""
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()


def fetch_oauth2_client_credentials_token(
    auth: Dict[str, Any],
    *,
    verify: Any = True,
    http_client_factory=None,
) -> str:
    """Return an OAuth2 client-credentials access token, using the cache when valid.

    The token endpoint is normally a different host from the inference endpoint,
    and commonly redirects, so it is fetched with an ordinary client rather than
    the no-redirect pinned transport used for inference.
    """
    token_url = str(auth.get("token_url") or "").strip()
    client_id = str(auth.get("client_id") or "").strip()
    client_secret = str(auth.get("client_secret") or "").strip()
    if not token_url or not client_id or not client_secret:
        raise ValueError(
            "OAuth2 model endpoints require a token URL, client ID, and client secret."
        )

    cache_key = _token_cache_key(auth)
    now = time.monotonic()
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    scope = str(auth.get("scope") or "").strip()
    if scope:
        payload["scope"] = scope

    client = (http_client_factory or httpx.Client)(
        timeout=OAUTH2_REQUEST_TIMEOUT_SECONDS,
        verify=verify,
        trust_env=False,
    )
    try:
        response = client.post(token_url, data=payload)
        status_code = response.status_code
        if status_code >= 400:
            raise build_sanitized_model_endpoint_error(
                "Custom model endpoint token request failed.",
                request_url=token_url,
                status_code=status_code,
                detail=response.text,
            )
        token_payload = response.json()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise build_sanitized_model_endpoint_error(
            "Custom model endpoint token request failed.",
            exc,
            request_url=token_url,
        ) from None
    finally:
        client.close()

    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise build_sanitized_model_endpoint_error(
            "Custom model endpoint token response did not contain an access token.",
            request_url=token_url,
        )

    try:
        expires_in = int(token_payload.get("expires_in") or OAUTH2_DEFAULT_EXPIRY_SECONDS)
    except (TypeError, ValueError):
        expires_in = OAUTH2_DEFAULT_EXPIRY_SECONDS
    expires_at = time.monotonic() + max(1, expires_in - OAUTH2_EXPIRY_SKEW_SECONDS)

    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[cache_key] = (access_token, expires_at)
    return access_token


def resolve_custom_endpoint_credentials(
    auth: Dict[str, Any],
    *,
    default_api_key_header: str = "",
    default_api_key_prefix: str = "",
    verify: Any = True,
) -> Tuple[str, Dict[str, str]]:
    """Resolve one Custom endpoint's credentials.

    Returns the value to hand to an SDK that takes an api_key argument, plus any
    additional headers the scheme requires. An SDK that sends "Authorization:
    Bearer" natively needs only the first; a scheme using a different header name
    supplies the second and passes a placeholder for the first.
    """
    auth = auth or {}
    auth_type = normalize_custom_endpoint_auth_type(auth.get("type"))

    if auth_type == AUTH_TYPE_BEARER:
        token = str(auth.get("bearer_token") or "").strip()
        if not token:
            raise ValueError("Selected model endpoint is missing a bearer token.")
        return token, {}

    if auth_type == AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS:
        return fetch_oauth2_client_credentials_token(auth, verify=verify), {}

    if auth_type == AUTH_TYPE_API_KEY:
        api_key = str(auth.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Selected model endpoint is missing an API key.")
        header_name, _ = resolve_api_key_header(
            auth,
            default_api_key_header,
            default_api_key_prefix,
        )
        # An explicit non-Authorization header is sent alongside the SDK's own
        # credential argument, because the SDK cannot express it.
        if header_name and header_name.lower() != "authorization":
            return api_key, build_api_key_headers(
                auth,
                default_api_key_header,
                default_api_key_prefix,
            )
        return api_key, {}

    raise ValueError("Custom model endpoints do not support the selected authentication type.")


def resolve_client_certificate(connection: Dict[str, Any]):
    """Return the mTLS client certificate for httpx, or None when not configured.

    Certificates are referenced by path so that a private key is mounted into the
    deployment rather than stored in the configuration database.
    """
    connection = connection or {}
    cert_path = str(connection.get("client_cert_path") or "").strip()
    if not cert_path:
        return None
    key_path = str(connection.get("client_key_path") or "").strip()
    return (cert_path, key_path) if key_path else cert_path
