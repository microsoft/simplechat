# functions_mcp_server_enterprise.py

import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from azure.core import MatchConditions

from config import cosmos_settings_container
from functions_appinsights import log_event
from functions_mcp_server_config import get_inbound_mcp_runtime_config


MCP_ENTERPRISE_CATEGORY = "InboundMCP"
RATE_LIMIT_COUNTER_PREFIX = "inbound_mcp_rate_limit"
RATE_LIMIT_RETRY_ATTEMPTS = 4
MAX_CORRELATION_ID_LENGTH = 128
SAFE_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class InboundMcpRateLimitDecision:
    allowed: bool
    category: str
    limit: int
    window_seconds: int
    remaining: int
    reset_after_seconds: int
    counter_id_hash: str

    def to_public_dict(self):
        return {
            "category": self.category,
            "limit": self.limit,
            "window_seconds": self.window_seconds,
            "remaining": self.remaining,
            "reset_after_seconds": self.reset_after_seconds,
        }


class InboundMcpRateLimitStoreError(Exception):
    """Raised when the durable inbound MCP rate counter cannot be updated safely."""


def resolve_inbound_mcp_request_id(auth_context=None, flask_request=None):
    """Resolve or create an audit-safe correlation id for an inbound MCP request."""
    context_id = normalize_inbound_mcp_correlation_id(getattr(auth_context, "correlation_id", ""))
    if context_id:
        return context_id
    if flask_request is not None:
        for header_name in ("x-ms-client-request-id", "x-correlation-id", "x-request-id"):
            header_value = normalize_inbound_mcp_correlation_id(flask_request.headers.get(header_name, ""))
            if header_value:
                return header_value
    return str(uuid.uuid4())


def normalize_inbound_mcp_correlation_id(value):
    normalized_value = str(value or "").replace("\r", "").replace("\n", "").strip()
    if not normalized_value:
        return ""
    bounded_value = normalized_value[:MAX_CORRELATION_ID_LENGTH]
    if SAFE_CORRELATION_ID_RE.fullmatch(bounded_value):
        return bounded_value
    return hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()[:32]


def build_inbound_mcp_log_context(auth_context=None, mcp_request_id="", **extra):
    """Build safe, reusable inbound MCP telemetry context without token or content values."""
    context = {
        "mcp_request_id": str(mcp_request_id or "").strip(),
    }
    if auth_context is not None:
        context.update({
            "tenant_id": getattr(auth_context, "tenant_id", ""),
            "caller_app_id": getattr(auth_context, "caller_app_id", ""),
            "source_id": getattr(auth_context, "source_id", ""),
            "source_signal_type": getattr(auth_context, "source_signal_type", ""),
            "source_trust_level": getattr(auth_context, "source_trust_level", ""),
            "token_type": getattr(auth_context, "token_type", ""),
            "delegated_user_id": getattr(auth_context, "delegated_user_id", ""),
        })
    context.update({key: value for key, value in extra.items() if value is not None})
    return context


def log_inbound_mcp_event(message, auth_context=None, mcp_request_id="", level=logging.INFO, **extra):
    """Log a structured inbound MCP event through the shared App Insights entrypoint."""
    log_event(
        message,
        extra=build_inbound_mcp_log_context(auth_context, mcp_request_id, **extra),
        level=level,
        category=MCP_ENTERPRISE_CATEGORY,
    )


def get_rate_limit_for_category(runtime_config, category):
    normalized_category = str(category or "read").strip().lower()
    limit_key_by_category = {
        "read": "inbound_mcp_rate_limit_read_per_window",
        "search": "inbound_mcp_rate_limit_search_per_window",
        "write": "inbound_mcp_rate_limit_write_per_window",
    }
    limit_key = limit_key_by_category.get(normalized_category, "inbound_mcp_rate_limit_read_per_window")
    return int(runtime_config.get(limit_key) or 1)


def _rate_limit_subject(auth_context, category):
    subject_parts = [
        str(getattr(auth_context, "token_type", "") or ""),
        str(getattr(auth_context, "delegated_user_id", "") or ""),
        str(getattr(auth_context, "caller_app_id", "") or ""),
        str(getattr(auth_context, "tenant_id", "") or ""),
        str(category or "read"),
    ]
    return "|".join(subject_parts)


def _counter_id_for_subject(subject):
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
    return f"{RATE_LIMIT_COUNTER_PREFIX}:{digest}", digest[:16]


def _current_utc_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reset_after(window_start_epoch, window_seconds, now_epoch):
    return max(0, int(window_start_epoch + window_seconds - now_epoch))


def _build_allowed_decision(category, limit, window_seconds, remaining, reset_after_seconds, counter_id_hash):
    return InboundMcpRateLimitDecision(
        allowed=True,
        category=category,
        limit=limit,
        window_seconds=window_seconds,
        remaining=max(0, remaining),
        reset_after_seconds=max(0, reset_after_seconds),
        counter_id_hash=counter_id_hash,
    )


def _build_denied_decision(category, limit, window_seconds, reset_after_seconds, counter_id_hash):
    return InboundMcpRateLimitDecision(
        allowed=False,
        category=category,
        limit=limit,
        window_seconds=window_seconds,
        remaining=0,
        reset_after_seconds=max(1, reset_after_seconds),
        counter_id_hash=counter_id_hash,
    )


def check_inbound_mcp_tool_rate_limit(auth_context, tool_metadata, runtime_config=None, now_epoch=None):
    """Check and update a Cosmos-backed per-caller inbound MCP tool rate limit."""
    runtime_config = runtime_config or get_inbound_mcp_runtime_config()
    category = str((tool_metadata or {}).get("rate_limit_category") or "read").strip().lower()
    if not runtime_config.get("enable_inbound_mcp_rate_limits", True):
        return _build_allowed_decision(category, 0, 0, 0, 0, "")

    limit = get_rate_limit_for_category(runtime_config, category)
    window_seconds = int(runtime_config.get("inbound_mcp_rate_limit_window_seconds") or 60)
    resolved_epoch = int(now_epoch if now_epoch is not None else time.time())
    counter_id, counter_id_hash = _counter_id_for_subject(_rate_limit_subject(auth_context, category))

    for attempt_index in range(RATE_LIMIT_RETRY_ATTEMPTS):
        try:
            counter = cosmos_settings_container.read_item(item=counter_id, partition_key=counter_id)
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise InboundMcpRateLimitStoreError("Unable to read inbound MCP rate-limit counter.") from exc
            new_counter = {
                "id": counter_id,
                "type": RATE_LIMIT_COUNTER_PREFIX,
                "counter_id_hash": counter_id_hash,
                "category": category,
                "window_start_epoch": resolved_epoch,
                "window_seconds": window_seconds,
                "count": 1,
                "updated_at": _current_utc_iso(),
            }
            try:
                cosmos_settings_container.create_item(body=new_counter)
                return _build_allowed_decision(
                    category,
                    limit,
                    window_seconds,
                    limit - 1,
                    window_seconds,
                    counter_id_hash,
                )
            except Exception as create_exc:
                if getattr(create_exc, "status_code", None) == 409:
                    continue
                raise InboundMcpRateLimitStoreError("Unable to create inbound MCP rate-limit counter.") from create_exc

        window_start_epoch = int(counter.get("window_start_epoch") or resolved_epoch)
        count = int(counter.get("count") or 0)
        if resolved_epoch - window_start_epoch >= window_seconds:
            window_start_epoch = resolved_epoch
            count = 0

        reset_after_seconds = _reset_after(window_start_epoch, window_seconds, resolved_epoch)
        if count >= limit:
            return _build_denied_decision(category, limit, window_seconds, reset_after_seconds, counter_id_hash)

        updated_counter = dict(counter)
        updated_counter.update({
            "category": category,
            "counter_id_hash": counter_id_hash,
            "window_start_epoch": window_start_epoch,
            "window_seconds": window_seconds,
            "count": count + 1,
            "updated_at": _current_utc_iso(),
        })
        try:
            cosmos_settings_container.replace_item(
                item=counter_id,
                body=updated_counter,
                etag=counter.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
            return _build_allowed_decision(
                category,
                limit,
                window_seconds,
                limit - (count + 1),
                reset_after_seconds,
                counter_id_hash,
            )
        except Exception as replace_exc:
            if getattr(replace_exc, "status_code", None) in (409, 412) and attempt_index < RATE_LIMIT_RETRY_ATTEMPTS - 1:
                continue
            raise InboundMcpRateLimitStoreError("Unable to update inbound MCP rate-limit counter.") from replace_exc

    raise InboundMcpRateLimitStoreError("Unable to update inbound MCP rate-limit counter after retries.")
