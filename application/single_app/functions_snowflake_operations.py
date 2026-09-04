# functions_snowflake_operations.py
"""Shared configuration helpers for Snowflake query actions."""

from typing import Any, Dict


SNOWFLAKE_PLUGIN_TYPE = "snowflake"
SNOWFLAKE_DEFAULT_ENDPOINT = "snowflake://query"
SNOWFLAKE_AUTH_METHOD_PASSWORD = "password"
SNOWFLAKE_AUTH_METHOD_KEY_PAIR = "key_pair"
SNOWFLAKE_AUTH_METHOD_OAUTH = "oauth"
SNOWFLAKE_AUTH_METHODS = {
    SNOWFLAKE_AUTH_METHOD_PASSWORD,
    SNOWFLAKE_AUTH_METHOD_KEY_PAIR,
    SNOWFLAKE_AUTH_METHOD_OAUTH,
}
SNOWFLAKE_ALLOWED_READ_STATEMENTS = {
    "DESC",
    "DESCRIBE",
    "EXPLAIN",
    "SELECT",
    "SHOW",
    "WITH",
}
SNOWFLAKE_SENSITIVE_ADDITIONAL_FIELDS = {
    "password",
    "private_key",
    "private_key_passphrase",
    "token",
}


def _as_bool(value: Any, default_value: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default_value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default_value: int, minimum: int, maximum: int) -> int:
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default_value
    return min(max(parsed_value, minimum), maximum)


def normalize_snowflake_auth_method(raw_auth_method: Any = None, auth_type: str = "") -> str:
    """Normalize UI, manifest, and reusable identity auth names to Snowflake auth methods."""
    normalized = str(raw_auth_method or "").strip().lower().replace("-", "_")
    aliases = {
        "bearer": SNOWFLAKE_AUTH_METHOD_OAUTH,
        "bearer_token": SNOWFLAKE_AUTH_METHOD_OAUTH,
        "keypair": SNOWFLAKE_AUTH_METHOD_KEY_PAIR,
        "key_pair": SNOWFLAKE_AUTH_METHOD_KEY_PAIR,
        "oauth2": SNOWFLAKE_AUTH_METHOD_OAUTH,
        "password": SNOWFLAKE_AUTH_METHOD_PASSWORD,
        "private_key": SNOWFLAKE_AUTH_METHOD_KEY_PAIR,
        "token": SNOWFLAKE_AUTH_METHOD_OAUTH,
        "username_password": SNOWFLAKE_AUTH_METHOD_PASSWORD,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in SNOWFLAKE_AUTH_METHODS:
        return normalized

    normalized_auth_type = str(auth_type or "").strip()
    if normalized_auth_type == "username_password":
        return SNOWFLAKE_AUTH_METHOD_PASSWORD
    if normalized_auth_type == "key":
        return SNOWFLAKE_AUTH_METHOD_KEY_PAIR
    return SNOWFLAKE_AUTH_METHOD_PASSWORD


def normalize_snowflake_additional_fields(raw_fields: Any = None, auth_type: str = "") -> Dict[str, Any]:
    """Normalize Snowflake action-specific settings with conservative limits."""
    fields = dict(raw_fields or {}) if isinstance(raw_fields, dict) else {}
    normalized = dict(fields)
    normalized["account"] = str(fields.get("account") or fields.get("account_identifier") or "").strip()
    normalized["user"] = str(fields.get("user") or fields.get("username") or "").strip()
    normalized["warehouse"] = str(fields.get("warehouse") or "").strip()
    normalized["database"] = str(fields.get("database") or "").strip()
    normalized["schema"] = str(fields.get("schema") or "").strip()
    normalized["role"] = str(fields.get("role") or "").strip()
    normalized["auth_method"] = normalize_snowflake_auth_method(fields.get("auth_method"), auth_type=auth_type)
    normalized["read_only"] = _as_bool(fields.get("read_only"), default_value=True)
    normalized["max_rows"] = _as_int(fields.get("max_rows"), default_value=1000, minimum=1, maximum=10000)
    normalized["timeout"] = _as_int(fields.get("timeout"), default_value=30, minimum=1, maximum=300)
    normalized["login_timeout"] = _as_int(fields.get("login_timeout"), default_value=30, minimum=1, maximum=300)
    normalized["byte_limit"] = _as_int(fields.get("byte_limit"), default_value=250000, minimum=1000, maximum=2000000)
    return normalized