# functions_yamcs_operations.py
"""Shared defaults and normalization helpers for Yamcs mission control action plugins."""

import re
from typing import Any, Dict, Optional


YAMCS_PLUGIN_TYPE = "yamcs"
YAMCS_DEFAULT_PROCESSOR = "realtime"
YAMCS_DEFAULT_PORT = 8090
YAMCS_SCHEME_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

YAMCS_AUTH_METHOD_USERNAME_PASSWORD = "username_password"
YAMCS_AUTH_METHOD_API_KEY = "api_key"
YAMCS_AUTH_METHOD_BEARER_TOKEN = "bearer_token"
YAMCS_AUTH_METHOD_NONE = "none"
YAMCS_SUPPORTED_AUTH_METHODS = {
    YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
    YAMCS_AUTH_METHOD_API_KEY,
    YAMCS_AUTH_METHOD_BEARER_TOKEN,
    YAMCS_AUTH_METHOD_NONE,
}
YAMCS_SUPPORTED_AUTH_TYPES = {"NoAuth", "key", "identity", "username_password"}

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
) -> str:
    """Return the Yamcs auth method represented by a manifest."""
    fields = additional_fields if isinstance(additional_fields, dict) else {}
    aliases = {
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
    fields["auth_method"] = normalize_yamcs_auth_method(fields, auth_type=auth_type)
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
