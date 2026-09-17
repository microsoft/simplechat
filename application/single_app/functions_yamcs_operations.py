# functions_yamcs_operations.py
"""Shared defaults and normalization helpers for Yamcs mission control action plugins."""

import re
from copy import deepcopy
from typing import Any, Dict, Optional


YAMCS_PLUGIN_TYPE = "yamcs"
YAMCS_DEFAULT_PROCESSOR = "realtime"
YAMCS_DEFAULT_PORT = 8090
YAMCS_SCHEME_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

YAMCS_AUTH_METHOD_USERNAME_PASSWORD = "username_password"
YAMCS_AUTH_METHOD_HTTP_BASIC = "http_basic"
YAMCS_AUTH_METHOD_API_KEY = "api_key"
YAMCS_AUTH_METHOD_BEARER_TOKEN = "bearer_token"
YAMCS_AUTH_METHOD_NONE = "none"
YAMCS_SUPPORTED_AUTH_METHODS = {
    YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    YAMCS_AUTH_METHOD_HTTP_BASIC,
    YAMCS_AUTH_METHOD_API_KEY,
    YAMCS_AUTH_METHOD_BEARER_TOKEN,
    YAMCS_AUTH_METHOD_NONE,
}
YAMCS_SUPPORTED_AUTH_TYPES = {"NoAuth", "key", "identity", "username_password", "basic"}
YAMCS_PROFILE_AUTH_METHODS = {
    "yamcs_login": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    "http_basic": YAMCS_AUTH_METHOD_HTTP_BASIC,
    "bearer_token": YAMCS_AUTH_METHOD_BEARER_TOKEN,
    "api_key": YAMCS_AUTH_METHOD_API_KEY,
}

# Yamcs archive SQL is a full engine that also supports DDL/DML. Only these leading
# keywords are accepted, and only when archive SQL is explicitly enabled.
YAMCS_ALLOWED_READ_STATEMENTS = {
    "DESC",
    "DESCRIBE",
    "SELECT",
    "SHOW",
}

# Secrets always live in auth.key, but the constant keeps redaction plumbing symmetric
# with the other connector action types.
YAMCS_SENSITIVE_ADDITIONAL_FIELDS = {
    "api_key",
    "access_token",
    "password",
    "token",
}

YAMCS_DEFAULT_MAX_ROWS = 500
YAMCS_MIN_MAX_ROWS = 1
YAMCS_MAX_MAX_ROWS = 5000
YAMCS_DEFAULT_TIMEOUT = 30
YAMCS_MIN_TIMEOUT = 1
YAMCS_MAX_TIMEOUT = 300
YAMCS_DEFAULT_BYTE_LIMIT = 250000
YAMCS_MIN_BYTE_LIMIT = 1000
YAMCS_MAX_BYTE_LIMIT = 2000000


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in [None, ""]:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    return max(minimum, min(maximum, parsed_value))


def normalize_yamcs_server_url(endpoint: Any) -> str:
    """Normalize a Yamcs server base URL so the Yamcs client can derive TLS from the scheme.

    Yamcs addresses are commonly written as ``host:port``. ``urlparse`` misreads that form as
    a scheme, so the scheme is detected explicitly rather than inferred from ``urlparse``.
    """
    value = str(endpoint or "").strip().rstrip("/")
    if not value:
        return ""

    if not YAMCS_SCHEME_PATTERN.match(value):
        value = f"https://{value}"
    return value.rstrip("/")


def normalize_yamcs_auth_method(
    additional_fields: Optional[Dict[str, Any]] = None,
    auth_type: str = "username_password",
    credential_requirement: Optional[Dict[str, Any]] = None,
) -> str:
    """Return the Yamcs auth method represented by a manifest."""
    if credential_requirement is not None:
        if not isinstance(credential_requirement, dict):
            raise ValueError("Invalid Yamcs credential requirement.")
        profile = credential_requirement.get("profile")
        if not isinstance(profile, str) or profile not in YAMCS_PROFILE_AUTH_METHODS:
            raise ValueError("Invalid Yamcs authentication profile.")
        return YAMCS_PROFILE_AUTH_METHODS[profile]
    if auth_type == "basic":
        return YAMCS_AUTH_METHOD_HTTP_BASIC
    fields = additional_fields if isinstance(additional_fields, dict) else {}
    aliases = {
        "basic": YAMCS_AUTH_METHOD_HTTP_BASIC,
        "http_basic": YAMCS_AUTH_METHOD_HTTP_BASIC,
        "apikey": YAMCS_AUTH_METHOD_API_KEY,
        "api_key": YAMCS_AUTH_METHOD_API_KEY,
        "bearer": YAMCS_AUTH_METHOD_BEARER_TOKEN,
        "bearer_token": YAMCS_AUTH_METHOD_BEARER_TOKEN,
        "access_token": YAMCS_AUTH_METHOD_BEARER_TOKEN,
        "token": YAMCS_AUTH_METHOD_BEARER_TOKEN,
        "noauth": YAMCS_AUTH_METHOD_NONE,
        "none": YAMCS_AUTH_METHOD_NONE,
        "anonymous": YAMCS_AUTH_METHOD_NONE,
        "password": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
        "username_password": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
        "yamcs_login": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    }

    explicit_method = str(fields.get("auth_method") or "").strip().lower().replace("-", "_")
    explicit_method = aliases.get(explicit_method, explicit_method)
    if explicit_method in YAMCS_SUPPORTED_AUTH_METHODS:
        return explicit_method

    identity_auth_type = str(fields.get("identity_auth_type") or "").strip().lower().replace("-", "_")
    identity_auth_type = aliases.get(identity_auth_type, identity_auth_type)
    if identity_auth_type in YAMCS_SUPPORTED_AUTH_METHODS:
        return identity_auth_type

    normalized_auth_type = str(auth_type or "").strip()
    if normalized_auth_type == "NoAuth":
        return YAMCS_AUTH_METHOD_NONE
    if normalized_auth_type == "key":
        return YAMCS_AUTH_METHOD_API_KEY
    return YAMCS_AUTH_METHOD_USERNAME_PASSWORD


def normalize_yamcs_additional_fields(
    additional_fields: Optional[Dict[str, Any]] = None,
    auth_type: str = "username_password",
    credential_requirement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize Yamcs additionalFields with bounded, read-only-safe defaults."""
    fields = dict(additional_fields or {}) if isinstance(additional_fields, dict) else {}
    fields["server_url"] = normalize_yamcs_server_url(
        fields.get("server_url") or fields.get("serverUrl") or ""
    )
    fields["instance"] = str(fields.get("instance") or fields.get("yamcs_instance") or "").strip()
    fields["processor"] = str(
        fields.get("processor") or fields.get("yamcs_processor") or ""
    ).strip() or YAMCS_DEFAULT_PROCESSOR
    fields["auth_method"] = normalize_yamcs_auth_method(
        fields, auth_type=auth_type, credential_requirement=credential_requirement
    )
    fields["tls_verify"] = _as_bool(fields.get("tls_verify"), default=True)
    # Yamcs actions never issue commands or write parameters; the flag is stored for parity
    # with the other connector action types and is always forced on.
    fields["read_only"] = True
    fields["enable_archive_sql"] = _as_bool(fields.get("enable_archive_sql"), default=False)
    fields["max_rows"] = _as_int(
        fields.get("max_rows"),
        YAMCS_DEFAULT_MAX_ROWS,
        YAMCS_MIN_MAX_ROWS,
        YAMCS_MAX_MAX_ROWS,
    )
    fields["timeout"] = _as_int(
        fields.get("timeout"),
        YAMCS_DEFAULT_TIMEOUT,
        YAMCS_MIN_TIMEOUT,
        YAMCS_MAX_TIMEOUT,
    )
    fields["byte_limit"] = _as_int(
        fields.get("byte_limit"),
        YAMCS_DEFAULT_BYTE_LIMIT,
        YAMCS_MIN_BYTE_LIMIT,
        YAMCS_MAX_BYTE_LIMIT,
    )
    return fields


def normalize_yamcs_manifest(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy action configuration without resolving or retaining any user's identity."""
    manifest = deepcopy(config or {})
    if not isinstance(manifest, dict):
        raise ValueError("Yamcs action configuration must be an object.")
    if "credential_requirement" in manifest:
        if not isinstance(manifest["credential_requirement"], dict):
            raise ValueError("Invalid Yamcs credential requirement.")
        # Requirement validation is metadata-only; keep the auth service out of legacy imports.
        from functions_action_auth import (
            get_action_auth_destination,
            normalize_action_credential_requirement,
            validate_action_credential_requirement,
        )

        manifest.setdefault("type", YAMCS_PLUGIN_TYPE)
        try:
            manifest = normalize_action_credential_requirement(manifest)
            validate_action_credential_requirement(manifest)
            manifest["endpoint"] = get_action_auth_destination(manifest)
            manifest["additionalFields"]["server_url"] = manifest["endpoint"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Invalid Yamcs credential requirement or destination.") from None

    auth = dict(manifest.get("auth") or {}) if isinstance(manifest.get("auth"), dict) else {}
    auth_type = str(auth.get("type") or "username_password").strip() or "username_password"
    auth["type"] = auth_type
    requirement = manifest.get("credential_requirement")
    fields = normalize_yamcs_additional_fields(
        manifest.get("additionalFields"), auth_type=auth_type, credential_requirement=requirement
    )
    if requirement is None:
        if auth_type == "username_password":
            fields["auth_method"] = YAMCS_AUTH_METHOD_USERNAME_PASSWORD
        elif auth_type == "NoAuth":
            fields["auth_method"] = YAMCS_AUTH_METHOD_NONE
        elif auth_type == "key" and fields["auth_method"] == YAMCS_AUTH_METHOD_NONE:
            fields["auth_method"] = YAMCS_AUTH_METHOD_API_KEY

    endpoint = normalize_yamcs_server_url(manifest.get("endpoint") or fields["server_url"])
    if endpoint:
        manifest["endpoint"] = endpoint
        fields["server_url"] = endpoint
    manifest["type"] = YAMCS_PLUGIN_TYPE
    manifest["auth"] = auth
    manifest["additionalFields"] = fields
    manifest.setdefault("metadata", {})
    return manifest
