# functions_model_endpoint_diagnostics.py
"""Correlated, user-safe Custom endpoint failures with server-side stack context."""

import logging
import re
import traceback
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import httpx
import requests
from openai import APIError
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

from functions_appinsights import log_event
from model_endpoint_profiles import GenAIMilRequestError


CORRELATION_ID_LENGTH = 8
MAX_LOGGED_DETAIL_LENGTH = 2000
MODEL_INVOCATION_ERRORS = (
    APIError, httpx.HTTPError, requests.RequestException,
    HttpResponseError, ServiceRequestError, ServiceResponseError,
)


def build_genai_mil_error(exception=None, *, status_code=None, headers=None):
    """GenAI diagnostics contain status/type only, never echoed key/error bodies."""
    status_code = status_code or getattr(exception, "status_code", None)
    headers = headers or getattr(getattr(exception, "response", None), "headers", {}) or {}
    retry_after = None
    raw_delay = headers.get("Retry-After")
    if status_code == 429 and isinstance(raw_delay, str) and re.fullmatch(r"[0-9]{1,6}", raw_delay):
        retry_after = int(raw_delay)
    correlation_id = new_model_endpoint_correlation_id()
    log_event(
        "[GENAI_MIL] Provider request failed.",
        extra={
            "status_code": status_code, "error_type": type(exception).__name__ if exception else "HTTPResponse",
            "correlation_id": correlation_id,
        },
        level=logging.ERROR,
    )
    return GenAIMilRequestError(status_code, retry_after=retry_after, reference=correlation_id)


# Credentials can appear in an upstream error body, in a repeated request URL, or
# in a header dump. Redact them before anything is written to the log.
_REDACTION_PATTERNS = (
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)([^\"'\r\n,}]+)"),
    re.compile(r"(?i)([?&](?:key|api[-_]?key|access[-_]?token)=)([^&\s\"']+)"),
    re.compile(r'(?i)((?:api[-_]?key|x-goog-api-key|client[-_]?secret|access[-_]?token|refresh[-_]?token|bearer[-_]?token|password)["\']?\s*[:=]\s*["\']?)([^"\'\s,&]+)'),
    re.compile(r'(?i)(bearer\s+)([A-Za-z0-9\-._~+/]+=*)'),
    re.compile(r'(sk-[A-Za-z0-9_-]{8,})'),
)


class SanitizedModelEndpointError(RuntimeError):
    """Only stable messages and a correlation reference may cross an API boundary."""

    def __init__(
        self,
        public_message,
        *,
        correlation_reference="",
        status_code=None,
        api_type="",
        protocol="",
        error_type="",
        request_stage="request",
        operation_effect_certainty=None,
    ):
        super().__init__(public_message)
        self.public_message = public_message
        self.correlation_reference = str(correlation_reference or "")
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        self.api_type = str(api_type or "")
        self.protocol = str(protocol or "")
        self.error_type = error_type if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}", str(error_type or "")) else ""
        self.request_stage = request_stage if request_stage in ("request", "stream", "response") else "request"
        self.operation_effect_certainty = operation_effect_certainty or (
            "none" if self.status_code is not None and self.request_stage == "request" else "possible"
        )


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
            if ":" in host:
                host = f"[{host}]"
            if parsed.port:
                host = f"{host}:{parsed.port}"
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
    try:
        log_event(
            f"[CUSTOM_MODEL_ENDPOINT] {summary} (correlation_id={correlation_id})",
            extra=context, level=logging.ERROR,
        )
    except (RuntimeError, OSError, ValueError, TypeError) as logging_error:
        logging.getLogger(__name__).error(
            "[CUSTOM_MODEL_ENDPOINT] Telemetry logging failed; reference %s; logger error type %s",
            correlation_id, type(logging_error).__name__, extra=context,
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
    request_stage: str = "request",
    operation_effect_certainty: str | None = None,
) -> SanitizedModelEndpointError:
    if status_code is None:
        status_code = getattr(exception, "status_code", None)
    if status_code is None:
        response = getattr(exception, "response", None)
        status_code = getattr(response, "status_code", None)
    reference = log_custom_model_endpoint_failure(
        message, exception, api_type=api_type, protocol=protocol,
        request_url=request_url, status_code=status_code, detail=detail,
    )
    return SanitizedModelEndpointError(
        f"{message} (reference {reference})",
        correlation_reference=reference,
        status_code=status_code,
        api_type=api_type,
        protocol=protocol,
        error_type=type(exception).__name__ if exception is not None else "HTTPResponse",
        request_stage=request_stage,
        operation_effect_certainty=operation_effect_certainty,
    )
