# functions_microsoft_decision_operations.py
"""Normalization and validation helpers for Microsoft Decision-1 actions."""

import re
from typing import Any, Dict
from urllib.parse import urlparse


MICROSOFT_DECISION_PLUGIN_TYPE = "microsoft_decision"
MICROSOFT_DECISION_PATH = "/openai/v1/responses"
MICROSOFT_DECISION_LEGACY_PATH = "/providers/microsoft/v1/systemone"
MICROSOFT_DECISION_AUTH_TYPES = {"key", "identity"}
MICROSOFT_DECISION_URL_MODES = {"foundry", "exact"}
MICROSOFT_DECISION_DEFAULT_TIMEOUT_SECONDS = 60
MICROSOFT_DECISION_MIN_TIMEOUT_SECONDS = 1
MICROSOFT_DECISION_MAX_TIMEOUT_SECONDS = 120
MICROSOFT_DECISION_DEFAULT_MINIMUM_CONFIDENCE = 0.75
MICROSOFT_DECISION_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
MICROSOFT_DECISION_DEFAULT_API_KEY_HEADER = "api-key"
MICROSOFT_DECISION_APIM_API_KEY_HEADER = "Ocp-Apim-Subscription-Key"
MICROSOFT_DECISION_MAX_STATE_BYTES = 65536
MICROSOFT_DECISION_MAX_INSTRUCTIONS_LENGTH = 4000
MICROSOFT_DECISION_MAX_CRITERIA_ITEMS = 20
MICROSOFT_DECISION_IDENTITY_HOST_SUFFIXES = (
    ".services.ai.azure.com",
    ".services.ai.azure.us",
    ".services.ai.azure.cn",
    ".cognitiveservices.azure.com",
    ".azure-api.net",
    ".azure-api.us",
    ".azure-api.cn",
)


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_microsoft_decision_endpoint(endpoint: Any, url_mode: str = "foundry") -> str:
    """Return the Decision API URL for a Foundry resource or exact endpoint."""
    normalized_endpoint = str(endpoint or "").strip().rstrip("/")
    if not normalized_endpoint:
        return ""
    parsed_endpoint = urlparse(normalized_endpoint)
    if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
        raise ValueError("Microsoft Decision actions require an HTTPS endpoint.")
    if parsed_endpoint.username or parsed_endpoint.password:
        raise ValueError("Microsoft Decision endpoints must not contain credentials.")
    if url_mode == "foundry":
        return f"{normalized_endpoint}{MICROSOFT_DECISION_PATH}"
    if url_mode == "exact":
        if not (
            normalized_endpoint.endswith(MICROSOFT_DECISION_PATH)
            or normalized_endpoint.endswith(MICROSOFT_DECISION_LEGACY_PATH)
        ):
            raise ValueError(
                "Exact Microsoft Decision endpoints must end with "
                f"'{MICROSOFT_DECISION_PATH}' or '{MICROSOFT_DECISION_LEGACY_PATH}'."
            )
        return normalized_endpoint
    raise ValueError("Microsoft Decision URL mode must be 'foundry' or 'exact'.")


def normalize_microsoft_decision_additional_fields(
    additional_fields: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Normalize bounded action configuration without altering supplied endpoint paths."""
    fields = dict(additional_fields or {})
    url_mode = str(fields.get("url_mode") or "foundry").strip().lower()
    if url_mode not in MICROSOFT_DECISION_URL_MODES:
        url_mode = "foundry"
    api_key_header = str(
        fields.get("api_key_header") or MICROSOFT_DECISION_DEFAULT_API_KEY_HEADER
    ).strip()
    if not MICROSOFT_DECISION_HEADER_NAME_PATTERN.fullmatch(api_key_header):
        raise ValueError("Microsoft Decision API key header name is invalid.")

    fields["url_mode"] = url_mode
    fields["deployment_name"] = str(fields.get("deployment_name") or "").strip()
    fields["api_key_header"] = api_key_header
    fields["timeout_seconds"] = _as_int(
        fields.get("timeout_seconds"),
        MICROSOFT_DECISION_DEFAULT_TIMEOUT_SECONDS,
        MICROSOFT_DECISION_MIN_TIMEOUT_SECONDS,
        MICROSOFT_DECISION_MAX_TIMEOUT_SECONDS,
    )
    fields["minimum_confidence"] = _as_float(
        fields.get("minimum_confidence"),
        MICROSOFT_DECISION_DEFAULT_MINIMUM_CONFIDENCE,
        0.0,
        1.0,
    )
    return fields


def _is_trusted_identity_endpoint(endpoint: str) -> bool:
    hostname = (urlparse(endpoint).hostname or "").lower()
    return any(hostname.endswith(suffix) for suffix in MICROSOFT_DECISION_IDENTITY_HOST_SUFFIXES)


def validate_microsoft_decision_manifest(manifest: Dict[str, Any]) -> list[str]:
    """Return user-safe validation errors for a Decision-1 action manifest."""
    errors: list[str] = []
    auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
    auth_type = str(auth.get("type") or "").strip()
    additional_fields = manifest.get("additionalFields")
    try:
        additional_fields = normalize_microsoft_decision_additional_fields(additional_fields)
    except ValueError as exc:
        return [str(exc)]

    if auth_type not in MICROSOFT_DECISION_AUTH_TYPES:
        errors.append("Microsoft Decision actions support auth.type values 'key' or 'identity'.")
    if auth_type == "key" and not auth.get("key"):
        errors.append("Microsoft Decision API-key authentication requires auth.key.")
    if auth_type == "identity" and not (auth.get("identity") or manifest.get("identity_id")):
        errors.append("Microsoft Decision managed identity authentication requires auth.identity or identity_id.")
    if not additional_fields["deployment_name"]:
        errors.append("Microsoft Decision actions require additionalFields.deployment_name.")
    try:
        normalized_endpoint = normalize_microsoft_decision_endpoint(
            manifest.get("endpoint"), additional_fields["url_mode"]
        )
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if auth_type == "identity" and not _is_trusted_identity_endpoint(normalized_endpoint):
            errors.append(
                "Microsoft Decision managed identity authentication requires a trusted Azure Foundry or Azure API Management endpoint."
            )
    return errors
