# functions_model_endpoint_identity_header.py
"""Identity header helpers for configured model endpoint calls."""

import hashlib
import hmac
import os
import re
from typing import Any, Dict

from flask import current_app, has_app_context, has_request_context, session


DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME = "x-simplechat-identity-key"
DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE = "user_oid_tenant_id"
MODEL_ENDPOINT_IDENTITY_HEADER_MODES = ("inherit", "enabled", "disabled")
MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPES = (
    "user_upn",
    "user_upn_tenant_id",
    "user_oid",
    "user_oid_tenant_id",
)
MODEL_ENDPOINT_IDENTITY_HEADER_SETTING_KEYS = (
    "model_endpoint_identity_header_enabled",
    "model_endpoint_identity_header_name",
    "model_endpoint_identity_header_value_type",
    "model_endpoint_identity_header_hmac_secret",
)

_HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9!#$%&'*+\-.^_`|~]{1,128}$")
_RESERVED_HEADER_NAMES = {
    "accept",
    "anthropic-version",
    "api-key",
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "host",
    "ocp-apim-subscription-key",
    "openai-organization",
    "openai-project",
    "proxy-authorization",
    "x-api-key",
}


def normalize_model_endpoint_identity_header_name(value: Any, fallback: str = "") -> str:
    """Return a safe custom identity header name or the supplied fallback."""
    header_name = str(value or "").strip()
    if _is_safe_identity_header_name(header_name):
        return header_name

    fallback_name = str(fallback or "").strip()
    if fallback_name and _is_safe_identity_header_name(fallback_name):
        return fallback_name
    return ""


def normalize_model_endpoint_identity_header_value_type(
    value: Any,
    fallback: str = DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE,
) -> str:
    """Return a supported identity header value type."""
    normalized_value = str(value or "").strip().lower()
    if normalized_value in MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPES:
        return normalized_value
    if fallback == "":
        return ""
    if fallback in MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPES:
        return fallback
    return DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE


def normalize_model_endpoint_identity_header_override(value: Any) -> Dict[str, str]:
    """Normalize a per-endpoint identity header override payload."""
    override = value if isinstance(value, dict) else {}
    raw_mode = str(override.get("mode") or "").strip().lower()
    if not raw_mode:
        if override.get("enabled") is True:
            raw_mode = "enabled"
        elif override.get("enabled") is False:
            raw_mode = "disabled"

    mode = raw_mode if raw_mode in MODEL_ENDPOINT_IDENTITY_HEADER_MODES else "inherit"
    header_name = normalize_model_endpoint_identity_header_name(
        override.get("header_name") or override.get("name"),
    )
    value_type = normalize_model_endpoint_identity_header_value_type(override.get("value_type"), fallback="")

    return {
        "mode": mode,
        "header_name": header_name,
        "value_type": value_type,
    }


def resolve_model_endpoint_identity_context(identity_context: Any = None) -> Dict[str, str]:
    """Resolve user identity values from the request session and explicit context."""
    context: Dict[str, str] = {}
    if has_request_context():
        session_user = session.get("user") if isinstance(session.get("user"), dict) else {}
        _merge_identity_context(context, session_user, override=True)

    if isinstance(identity_context, dict):
        _merge_identity_context(context, identity_context, override=False)
    elif identity_context not in (None, ""):
        _set_if_present(context, "user_oid", identity_context, override=False)

    return context


def resolve_effective_model_endpoint_identity_header_config(
    settings: Any,
    endpoint_config: Any = None,
) -> Dict[str, Any]:
    """Resolve global identity header settings with a per-endpoint override."""
    source_settings = settings if isinstance(settings, dict) else {}
    endpoint = endpoint_config if isinstance(endpoint_config, dict) else {}
    endpoint_override = normalize_model_endpoint_identity_header_override(endpoint.get("identity_header"))

    global_enabled = source_settings.get("model_endpoint_identity_header_enabled") is True
    global_header_name = normalize_model_endpoint_identity_header_name(
        source_settings.get("model_endpoint_identity_header_name"),
        fallback=DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME,
    )
    global_value_type = normalize_model_endpoint_identity_header_value_type(
        source_settings.get("model_endpoint_identity_header_value_type"),
    )

    mode = endpoint_override["mode"]
    enabled = global_enabled
    if mode == "enabled":
        enabled = True
    elif mode == "disabled":
        enabled = False

    return {
        "enabled": enabled,
        "header_name": endpoint_override["header_name"] or global_header_name,
        "value_type": endpoint_override["value_type"] or global_value_type,
        "hmac_secret": str(
            source_settings.get("model_endpoint_identity_header_hmac_secret")
            or _get_fallback_hmac_secret()
        ),
    }


def build_model_endpoint_identity_headers(
    settings: Any,
    endpoint_config: Any = None,
    identity_context: Any = None,
) -> Dict[str, str]:
    """Build the configured model endpoint identity header, if enabled and resolvable."""
    effective_config = resolve_effective_model_endpoint_identity_header_config(
        settings,
        endpoint_config=endpoint_config,
    )
    if effective_config.get("enabled") is not True:
        return {}

    header_name = normalize_model_endpoint_identity_header_name(effective_config.get("header_name"))
    if not header_name:
        return {}

    identity = resolve_model_endpoint_identity_context(identity_context)
    canonical_identity = _build_canonical_identity(
        identity,
        str(effective_config.get("value_type") or DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_VALUE_TYPE),
    )
    if not canonical_identity:
        return {}

    secret = str(effective_config.get("hmac_secret") or "")
    if not secret:
        return {}

    digest = hmac.new(
        secret.encode("utf-8"),
        canonical_identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {header_name: digest}


def _is_safe_identity_header_name(header_name: str) -> bool:
    normalized_header_name = str(header_name or "").strip()
    return (
        bool(normalized_header_name)
        and bool(_HEADER_NAME_PATTERN.fullmatch(normalized_header_name))
        and normalized_header_name.lower() not in _RESERVED_HEADER_NAMES
    )


def _get_fallback_hmac_secret() -> str:
    if has_app_context():
        return str(current_app.config.get("SECRET_KEY") or "")
    return str(os.environ.get("SECRET_KEY") or "")


def _merge_identity_context(target: Dict[str, str], source: Dict[str, Any], *, override: bool) -> None:
    _set_if_present(
        target,
        "user_oid",
        source.get("user_oid") or source.get("oid") or source.get("sub") or source.get("user_id") or source.get("userId"),
        override=override,
    )
    _set_if_present(
        target,
        "user_upn",
        source.get("user_upn") or source.get("upn") or source.get("preferred_username") or source.get("email"),
        override=override,
    )
    _set_if_present(
        target,
        "tenant_id",
        source.get("tenant_id") or source.get("tid") or source.get("tenantId"),
        override=override,
    )


def _set_if_present(target: Dict[str, str], key: str, value: Any, *, override: bool) -> None:
    normalized_value = str(value or "").strip()
    if normalized_value and (override or not target.get(key)):
        target[key] = normalized_value


def _build_canonical_identity(identity: Dict[str, str], value_type: str) -> str:
    normalized_value_type = normalize_model_endpoint_identity_header_value_type(value_type)
    user_oid = str(identity.get("user_oid") or "").strip().lower()
    user_upn = str(identity.get("user_upn") or "").strip().lower()
    tenant_id = str(identity.get("tenant_id") or "").strip().lower()

    if normalized_value_type == "user_upn" and user_upn:
        return f"{normalized_value_type}:{user_upn}"
    if normalized_value_type == "user_upn_tenant_id" and user_upn and tenant_id:
        return f"{normalized_value_type}:{user_upn}|{tenant_id}"
    if normalized_value_type == "user_oid" and user_oid:
        return f"{normalized_value_type}:{user_oid}"
    if normalized_value_type == "user_oid_tenant_id" and user_oid and tenant_id:
        return f"{normalized_value_type}:{user_oid}|{tenant_id}"
    return ""
