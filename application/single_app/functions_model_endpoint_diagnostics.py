# functions_model_endpoint_diagnostics.py
"""Server-side diagnostics for Custom model endpoint failures.

Custom endpoint errors are sanitized before they reach the browser, because an
upstream error body can echo back a URL, a header, or an API key. The first
implementation achieved that by discarding the cause entirely:

    raise RuntimeError("Custom model request failed.") from None

That is safe and undebuggable. An administrator saw the same sentence for a
wrong path, a wrong key, a wrong model name, a TLS failure, and a blocked
address, with nothing in the log to tell them apart.

This module keeps the browser message generic while recording the real cause
server-side, and stamps both with a short correlation id so an administrator can
join the message they were shown to the log entry that explains it.
"""

import logging
import re
import uuid
from typing import Any, Dict

from functions_appinsights import log_event


CORRELATION_ID_LENGTH = 8

# Credentials can appear in an upstream error body, in a repeated request URL, or
# in a header dump. Redact them before anything is written to the log.
_REDACTION_PATTERNS = (
    re.compile(r"(?i)(api[-_]?key\"?\s*[:=]\s*\"?)([^\"\s,&]+)"),
    re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?)([^\"\s,&]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/]+=*)"),
    re.compile(r"(?i)([?&](?:key|api[-_]?key|access[-_]?token)=)([^&\s\"]+)"),
    re.compile(r"(?i)(x-api-key\"?\s*[:=]\s*\"?)([^\"\s,&]+)"),
    re.compile(r"(?i)(x-goog-api-key\"?\s*[:=]\s*\"?)([^\"\s,&]+)"),
    re.compile(r"(sk-[A-Za-z0-9\-_]{8,})"),
)

MAX_LOGGED_DETAIL_LENGTH = 2000


def redact_model_endpoint_secrets(value: Any) -> str:
    """Return text with credential-looking values replaced by a redaction marker."""
    text = str(value or "")
    if not text:
        return ""
    for pattern in _REDACTION_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    if len(text) > MAX_LOGGED_DETAIL_LENGTH:
        text = f"{text[:MAX_LOGGED_DETAIL_LENGTH]}...[truncated]"
    return text


def new_model_endpoint_correlation_id() -> str:
    """Return a short id that links a sanitized message to its log entry."""
    return uuid.uuid4().hex[:CORRELATION_ID_LENGTH]


def _build_log_context(
    correlation_id: str,
    *,
    api_type: Any = "",
    protocol: Any = "",
    request_url: Any = "",
    status_code: Any = None,
    detail: Any = "",
) -> Dict[str, Any]:
    context: Dict[str, Any] = {"correlation_id": correlation_id}
    if api_type:
        context["api_type"] = str(api_type)
    if protocol:
        context["protocol"] = str(protocol)
    if request_url:
        # The resolved URL is the single most useful diagnostic, because URL
        # normalization can rewrite what the administrator typed.
        context["request_url"] = redact_model_endpoint_secrets(request_url)
    if status_code is not None:
        context["status_code"] = status_code
    if detail:
        context["detail"] = redact_model_endpoint_secrets(detail)
    return context


def log_custom_model_endpoint_failure(
    summary: str,
    exception: BaseException | None = None,
    *,
    api_type: Any = "",
    protocol: Any = "",
    request_url: Any = "",
    status_code: Any = None,
    detail: Any = "",
) -> str:
    """Record a Custom endpoint failure server-side and return its correlation id."""
    correlation_id = new_model_endpoint_correlation_id()
    context = _build_log_context(
        correlation_id,
        api_type=api_type,
        protocol=protocol,
        request_url=request_url,
        status_code=status_code,
        detail=detail,
    )
    if exception is not None:
        context["error_type"] = type(exception).__name__
        context["error"] = redact_model_endpoint_secrets(exception)

    try:
        log_event(
            f"[CUSTOM_MODEL_ENDPOINT] {summary} (correlation_id={correlation_id})",
            extra=context,
            level=logging.ERROR,
            exceptionTraceback=exception is not None,
        )
    except Exception:
        # Diagnostics must never replace the original failure with a logging error.
        pass
    return correlation_id


def build_sanitized_model_endpoint_error(
    message: str,
    exception: BaseException | None = None,
    *,
    api_type: Any = "",
    protocol: Any = "",
    request_url: Any = "",
    status_code: Any = None,
    detail: Any = "",
) -> RuntimeError:
    """Log the real cause and return the sanitized error to raise in its place."""
    correlation_id = log_custom_model_endpoint_failure(
        message,
        exception,
        api_type=api_type,
        protocol=protocol,
        request_url=request_url,
        status_code=status_code,
        detail=detail,
    )
    return RuntimeError(f"{message} (reference {correlation_id})")
