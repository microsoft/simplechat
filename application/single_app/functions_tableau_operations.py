# functions_tableau_operations.py
"""Shared defaults and normalization helpers for Tableau action plugins."""

from typing import Any, Dict, Optional
from urllib.parse import urlparse


TABLEAU_PLUGIN_TYPE = "tableau"
TABLEAU_AUTH_METHOD_PAT = "personal_access_token"
TABLEAU_AUTH_METHOD_USERNAME_PASSWORD = "username_password"
TABLEAU_SUPPORTED_AUTH_METHODS = {
    TABLEAU_AUTH_METHOD_PAT,
    TABLEAU_AUTH_METHOD_USERNAME_PASSWORD,
}
TABLEAU_DEFAULT_PAGE_SIZE = 100
TABLEAU_DEFAULT_MAX_RESULTS = 100
TABLEAU_DEFAULT_TIMEOUT = 30
TABLEAU_MIN_PAGE_SIZE = 1
TABLEAU_MAX_PAGE_SIZE = 1000
TABLEAU_MIN_MAX_RESULTS = 1
TABLEAU_MAX_MAX_RESULTS = 1000
TABLEAU_MIN_TIMEOUT = 1
TABLEAU_MAX_TIMEOUT = 300


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


def normalize_tableau_server_url(endpoint: Any) -> str:
    """Normalize a Tableau Server or Tableau Cloud base URL."""
    value = str(endpoint or "").strip().rstrip("/")
    if not value:
        return ""

    parsed_url = urlparse(value)
    if not parsed_url.scheme and parsed_url.netloc == "":
        value = f"https://{value}"
    return value.rstrip("/")


def normalize_tableau_auth_method(
    additional_fields: Optional[Dict[str, Any]] = None,
    auth_type: str = "key",
) -> str:
    """Return the Tableau auth method represented by a manifest."""
    fields = additional_fields if isinstance(additional_fields, dict) else {}
    explicit_method = str(fields.get("auth_method") or "").strip().lower()
    if explicit_method in TABLEAU_SUPPORTED_AUTH_METHODS:
        return explicit_method

    identity_auth_type = str(fields.get("identity_auth_type") or "").strip().lower()
    normalized_auth_type = str(auth_type or "key").strip()
    if normalized_auth_type == "username_password" or identity_auth_type == "username_password":
        return TABLEAU_AUTH_METHOD_USERNAME_PASSWORD
    return TABLEAU_AUTH_METHOD_PAT


def normalize_tableau_additional_fields(
    additional_fields: Optional[Dict[str, Any]] = None,
    auth_type: str = "key",
) -> Dict[str, Any]:
    """Normalize Tableau additionalFields with bounded defaults."""
    fields = dict(additional_fields or {}) if isinstance(additional_fields, dict) else {}
    fields["auth_method"] = normalize_tableau_auth_method(fields, auth_type=auth_type)
    fields["site_content_url"] = str(
        fields.get("site_content_url")
        or fields.get("siteContentUrl")
        or fields.get("site_id")
        or fields.get("siteId")
        or ""
    ).strip().strip("/")
    fields["pat_name"] = str(
        fields.get("pat_name")
        or fields.get("personal_access_token_name")
        or fields.get("token_name")
        or ""
    ).strip()
    fields["page_size"] = _as_int(
        fields.get("page_size"),
        TABLEAU_DEFAULT_PAGE_SIZE,
        TABLEAU_MIN_PAGE_SIZE,
        TABLEAU_MAX_PAGE_SIZE,
    )
    fields["max_results"] = _as_int(
        fields.get("max_results"),
        TABLEAU_DEFAULT_MAX_RESULTS,
        TABLEAU_MIN_MAX_RESULTS,
        TABLEAU_MAX_MAX_RESULTS,
    )
    fields["timeout"] = _as_int(
        fields.get("timeout"),
        TABLEAU_DEFAULT_TIMEOUT,
        TABLEAU_MIN_TIMEOUT,
        TABLEAU_MAX_TIMEOUT,
    )
    fields["use_server_version"] = _as_bool(fields.get("use_server_version"), default=True)
    return fields