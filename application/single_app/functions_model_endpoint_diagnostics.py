# functions_model_endpoint_diagnostics.py
"""Correlated, user-safe Custom endpoint failures with server-side stack context."""

import logging
import re
import traceback
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from functions_appinsights import log_event


CORRELATION_ID_LENGTH = 8
MAX_LOGGED_DETAIL_LENGTH = 2000
_REDACTION_PATTERNS = (
    re.compile(r'(?i)((?:api[-_]?key|x-goog-api-key|client[-_]?secret|access[-_]?token|refresh[-_]?token|bearer[-_]?token|password)["\']?\s*[:=]\s*["\']?)([^"\'\s,&]+)'),
    re.compile(r'(?i)(bearer\s+)([A-Za-z0-9\-._~+/]+=*)'),
    re.compile(r'(sk-[A-Za-z0-9_-]{8,})'),
)


class SanitizedModelEndpointError(RuntimeError):
    """Only stable messages and a correlation reference may cross an API boundary."""

    def __init__(self, public_message):
        super().__init__(public_message)
        self.public_message = public_message


def redact_model_endpoint_secrets(value: Any) -> str:
    text = str(value or "")
    for pattern in _REDACTION_PATTERNS:
        text = pattern.sub(
            (lambda match: f"{match.group(1)}[REDACTED]") if pattern.groups >= 2 else "[REDACTED]",
            text,
        )
    return text[:MAX_LOGGED_DETAIL_LENGTH]


def new_model_endpoint_correlation_id() -> str:
    return uuid.uuid4().hex[:CORRELATION_ID_LENGTH]


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
    """Log the stack and transport context, never an arbitrary provider body.

    Provider bodies and exception strings may echo credentials without labels.
    A frame-only traceback keeps the failing code path without dumping those
    strings or local variables. ``detail`` is accepted for historical callers but
    intentionally not recorded.
    """
    correlation_id = new_model_endpoint_correlation_id()
    context = {"correlation_id": correlation_id, "api_type": str(api_type), "protocol": str(protocol)}
    if request_url:
        try:
            parsed = urlsplit(str(request_url))
            host = parsed.hostname or ""
            context["request_url"] = redact_model_endpoint_secrets(
                urlunsplit((parsed.scheme, host, parsed.path, "", ""))
            )
        except ValueError:
            context["request_url"] = "[invalid URL]"
    if status_code is not None:
        context["status_code"] = status_code
    if exception is not None:
        context["error_type"] = type(exception).__name__
        context["traceback"] = "\n".join(
            f"{frame.filename}:{frame.lineno} in {frame.name}"
            for frame in traceback.extract_tb(exception.__traceback__)
        )
        if exception.__cause__ is not None:
            context["cause_type"] = type(exception.__cause__).__name__
    log_event(
        f"[MODEL_ENDPOINT] {summary} (reference {correlation_id})",
        extra=context, level=logging.ERROR,
    )
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
) -> SanitizedModelEndpointError:
    reference = log_custom_model_endpoint_failure(
        message, exception, api_type=api_type, protocol=protocol,
        request_url=request_url, status_code=status_code, detail=detail,
    )
    return SanitizedModelEndpointError(f"{message} (reference {reference})")
