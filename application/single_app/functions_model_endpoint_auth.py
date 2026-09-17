# functions_model_endpoint_auth.py
"""Server-side API key, bearer, OAuth2, and certificate helpers for Custom APIs."""

import hashlib
import json
import threading
import time
from typing import Any

import httpx

from functions_model_endpoint_diagnostics import build_sanitized_model_endpoint_error
from functions_model_endpoint_providers import (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_BEARER,
    AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS,
    DEFAULT_CUSTOM_AUTH_TYPES,
    normalize_custom_endpoint_auth_type,
)
from functions_model_endpoint_validation import (
    ModelEndpointValidationError,
    validate_custom_api_key_header,
    validate_custom_model_endpoint_url,
)


CUSTOM_ENDPOINT_AUTH_TYPES = DEFAULT_CUSTOM_AUTH_TYPES
OAUTH2_EXPIRY_SKEW_SECONDS = 60
OAUTH2_DEFAULT_EXPIRY_SECONDS = 3600
OAUTH2_REQUEST_TIMEOUT_SECONDS = 30
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()


def resolve_api_key_header(auth: dict, default_header: str = "", default_prefix: str = "") -> tuple[str, str]:
    auth = auth or {}
    validate_custom_api_key_header(auth)
    override = str(auth.get("api_key_header") or "").strip()
    if override:
        return override, str(auth.get("api_key_prefix") or "").strip()
    prefix = auth.get("api_key_prefix") if "api_key_prefix" in auth else default_prefix
    return str(default_header or "").strip(), str(prefix or "").strip()


def build_api_key_headers(auth: dict, default_header: str = "", default_prefix: str = "") -> dict[str, str]:
    api_key = str((auth or {}).get("api_key") or "").strip()
    if not api_key:
        raise ModelEndpointValidationError("Selected Custom endpoint is missing an API key.")
    if any(ord(character) < 32 or ord(character) > 126 for character in api_key):
        raise ModelEndpointValidationError("Custom API key contains invalid header characters.")
    name, prefix = resolve_api_key_header(auth, default_header, default_prefix)
    return {name: f"{prefix} {api_key}" if prefix else api_key} if name else {}


def build_bearer_headers(auth: dict) -> dict[str, str]:
    token = str((auth or {}).get("bearer_token") or "").strip()
    if not token:
        raise ModelEndpointValidationError("Selected Custom endpoint is missing a bearer token.")
    if any(ord(character) < 32 or ord(character) > 126 for character in token):
        raise ModelEndpointValidationError("Custom bearer token contains invalid header characters.")
    return {"Authorization": f"Bearer {token}"}


def clear_oauth2_token_cache() -> None:
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()


def fetch_oauth2_client_credentials_token(
    auth: dict,
    *,
    allow_private: bool = False,
    allow_insecure: bool = False,
    ca_bundle_path: str = "",
    client_cert: Any = None,
    http_client_factory=None,
) -> str:
    """Fetch through the pinned transport; cache by credentials AND network policy."""
    auth = auth or {}
    if not all(str(auth.get(field) or "").strip() for field in ("token_url", "client_id", "client_secret")):
        raise ModelEndpointValidationError("Custom OAuth2 requires a token URL, client ID, and client secret.")
    token_url = validate_custom_model_endpoint_url(
        auth["token_url"], allow_private=allow_private, allow_insecure=allow_insecure,
    )
    cache_material = (
        token_url, str(auth["client_id"]), str(auth["client_secret"]), str(auth.get("scope") or ""),
        allow_private, allow_insecure, ca_bundle_path, client_cert,
    )
    cache_key = hashlib.sha256(json.dumps(cache_material).encode("utf-8")).hexdigest()
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
    # Deferred to avoid the auth -> transport -> auth import cycle.
    from model_endpoint_clients import build_custom_openai_sync_http_client

    factory = http_client_factory or build_custom_openai_sync_http_client
    client = factory(
        allow_private=allow_private, allow_insecure=allow_insecure,
        ca_bundle_path=ca_bundle_path, client_cert=client_cert,
    )
    payload = {
        "grant_type": "client_credentials",
        "client_id": str(auth["client_id"]).strip(),
        "client_secret": str(auth["client_secret"]).strip(),
    }
    if auth.get("scope"):
        payload["scope"] = str(auth["scope"]).strip()
    try:
        with client:
            response = client.post(
                token_url, data=payload, timeout=OAUTH2_REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
            )
            response.raise_for_status()
            token_payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise build_sanitized_model_endpoint_error(
            "Custom endpoint token request failed.", exc, request_url=token_url,
            status_code=getattr(getattr(exc, "response", None), "status_code", None),
        ) from exc
    token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
    if not isinstance(token, str) or not token.strip() or any(ord(character) < 32 or ord(character) > 126 for character in token):
        raise build_sanitized_model_endpoint_error(
            "Custom endpoint token response did not contain an access token.", request_url=token_url,
        )
    token_type = str(token_payload.get("token_type") or "Bearer").lower()
    if token_type != "bearer":
        raise build_sanitized_model_endpoint_error("Custom endpoint token response uses an unsupported token type.")
    try:
        expires_in = int(token_payload.get("expires_in", OAUTH2_DEFAULT_EXPIRY_SECONDS))
    except (TypeError, ValueError):
        expires_in = OAUTH2_DEFAULT_EXPIRY_SECONDS
    lifetime = max(0, expires_in - min(OAUTH2_EXPIRY_SKEW_SECONDS, max(0, expires_in // 10)))
    with _TOKEN_CACHE_LOCK:
        now = time.monotonic()
        expired = [key for key, value in _TOKEN_CACHE.items() if value[1] <= now]
        for key in expired:
            _TOKEN_CACHE.pop(key, None)
        if len(_TOKEN_CACHE) >= 256:
            _TOKEN_CACHE.pop(next(iter(_TOKEN_CACHE)))
        _TOKEN_CACHE[cache_key] = (token.strip(), now + lifetime)
    return token.strip()


def resolve_custom_endpoint_credentials(
    auth: dict,
    *,
    default_api_key_header: str = "Authorization",
    default_api_key_prefix: str = "Bearer",
    allow_private: bool = False,
    allow_insecure: bool = False,
    ca_bundle_path: str = "",
    client_cert: Any = None,
) -> tuple[str, dict[str, str]]:
    """Return an OpenAI SDK credential plus exact authentication header overrides.

    Non-Authorization key schemes use a placeholder SDK key and explicitly empty
    Authorization, so the real key is sent only in the configured header. Callers
    must pass both return values, not discard the headers.
    """
    auth = auth or {}
    auth_type = normalize_custom_endpoint_auth_type(auth.get("type") or AUTH_TYPE_API_KEY)
    if auth_type == AUTH_TYPE_API_KEY:
        headers = build_api_key_headers(auth, default_api_key_header, default_api_key_prefix)
        authorization = next((value for name, value in headers.items() if name.lower() == "authorization"), None)
        if authorization is not None:
            return str(auth["api_key"]).strip(), {"Authorization": authorization}
        return "custom-header-auth", {"Authorization": "", **headers}
    if auth_type == AUTH_TYPE_BEARER:
        headers = build_bearer_headers(auth)
        return str(auth["bearer_token"]).strip(), headers
    if auth_type == AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS:
        token = fetch_oauth2_client_credentials_token(
            auth, allow_private=allow_private, allow_insecure=allow_insecure,
            ca_bundle_path=ca_bundle_path, client_cert=client_cert,
        )
        return token, {"Authorization": f"Bearer {token}"}
    raise ModelEndpointValidationError("Custom endpoint authentication type is not supported.")


def resolve_client_certificate(connection: dict):
    """Resolve deployment-mounted PEM paths; private key material never enters settings."""
    connection = connection or {}
    cert = str(connection.get("client_cert_path") or "").strip()
    key = str(connection.get("client_key_path") or "").strip()
    if key and not cert:
        raise ModelEndpointValidationError("A Custom client key requires a client certificate.")
    return (cert, key) if cert and key else cert or None
