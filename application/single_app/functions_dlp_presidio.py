# functions_dlp_presidio.py

"""HTTP adapter for Presidio-compatible Analyzer endpoints."""

import os
from urllib.parse import urlparse

import requests


DEFAULT_PRESIDIO_TIMEOUT_SECONDS = 5
DEFAULT_PRESIDIO_LANGUAGE = "en"
DEFAULT_PRESIDIO_SCORE_THRESHOLD = 0.5
DEFAULT_PRESIDIO_AUTH_HEADER_NAME = "X-DLP-API-Key"


class PresidioEndpointConfigurationError(ValueError):
    """Raised when the configured Presidio endpoint is not safe to call."""


class PresidioEndpointRequestError(RuntimeError):
    """Raised when the Presidio endpoint cannot return a usable analyzer result."""


def validate_presidio_endpoint_url(endpoint_url):
    """Validate and normalize a Presidio Analyzer endpoint URL."""
    normalized = str(endpoint_url or "").strip()
    if not normalized:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint is required.")

    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint must be an absolute HTTP(S) URL.")

    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and host not in local_hosts:
        raise PresidioEndpointConfigurationError("Presidio analyzer endpoint must use HTTPS unless it is localhost.")

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
    secret_env_var = str((settings or {}).get("dlp_presidio_auth_secret_env_var") or "").strip()
    if not header_name or not secret_env_var:
        return {}

    secret_value = os.getenv(secret_env_var, "")
    if not secret_value:
        return {}
    return {header_name: secret_value}


def _normalize_result_item(item):
    if not isinstance(item, dict):
        return None
    if not item.get("entity_type") or item.get("start") is None or item.get("end") is None:
        return None
    try:
        return {
            "entity_type": str(item.get("entity_type")),
            "start": int(item.get("start")),
            "end": int(item.get("end")),
            "score": float(item.get("score", 0.0)),
        }
    except (TypeError, ValueError):
        return None


def analyze_with_presidio_endpoint(text, settings):
    """Call a configured Presidio Analyzer endpoint and return recognizer results."""
    settings = settings or {}
    endpoint_url = validate_presidio_endpoint_url(settings.get("dlp_presidio_analyzer_endpoint"))
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

    try:
        response = requests.post(endpoint_url, json=payload, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        raise PresidioEndpointRequestError(f"Presidio analyzer request failed: {type(exc).__name__}") from exc

    if not isinstance(body, list):
        raise PresidioEndpointRequestError("Presidio analyzer response must be a list.")

    results = []
    for item in body:
        normalized = _normalize_result_item(item)
        if normalized:
            results.append(normalized)
    return results
