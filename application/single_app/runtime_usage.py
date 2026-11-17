# runtime_usage.py
"""Content-free runtime usage contracts. Importing this module performs no bootstrap."""

import math
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


USAGE_KINDS = ("agent", "action", "workflow")
USAGE_OUTCOMES = ("succeeded", "failed", "cancelled", "timeout", "partial", "unknown")
USAGE_SCHEMA_VERSION = 1


def bounded_text(value, limit=256):
    return value[:limit] if isinstance(value, str) else ""


def configured_host(value):
    """Keep only a configured DNS host/IP, never userinfo, path, query, or fragment."""
    try:
        parsed = urlsplit(value if isinstance(value, str) else "")
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return "unknown"
        return host.encode("idna").decode("ascii").lower()[:253]
    except (ValueError, UnicodeError):
        return "unknown"


def normalize_outcome(value):
    aliases = {"completed": "succeeded", "success": "succeeded", "canceled": "cancelled"}
    value = aliases.get(value, value) if isinstance(value, str) else "unknown"
    return value if value in USAGE_OUTCOMES else "unknown"


def finite_duration(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return round(value, 3)
    return None


@dataclass(frozen=True)
class UsageTarget:
    kind: str
    entity_id: str
    name: str
    scope_type: str = "personal"
    scope_id: str = ""
    entity_type: str = "unknown"
    endpoint_host: str = "not_applicable"
    auth_type: str = "not_applicable"
    operation: str = ""

    def __post_init__(self):
        if self.kind not in USAGE_KINDS:
            raise ValueError("Invalid usage entity kind.")


def build_usage_record(target, *, user_id, attempt_id, outcome, duration_ms=None,
                       workspace_type="", group_id="", public_workspace_id="",
                       conversation_id="", workflow_id="", run_id="", trigger_type=""):
    """Explicit allowlist: this API deliberately accepts no generic metadata or payload."""
    if not isinstance(user_id, str) or not user_id or not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("Usage requires a server execution identity and attempt ID.")
    timestamp = datetime.now(timezone.utc).isoformat()
    usage = {
        "version": USAGE_SCHEMA_VERSION,
        "kind": target.kind,
        "entity_id": bounded_text(target.entity_id),
        "name": bounded_text(target.name),
        "scope_type": bounded_text(target.scope_type, 32),
        "scope_id": bounded_text(target.scope_id),
        "entity_type": bounded_text(target.entity_type, 80),
        "endpoint_host": bounded_text(target.endpoint_host, 253),
        "auth_type": bounded_text(target.auth_type, 80),
        "operation": bounded_text(target.operation),
        "attempt_id": bounded_text(attempt_id),
        "outcome": normalize_outcome(outcome),
        "duration_ms": finite_duration(duration_ms),
        "workflow_id": bounded_text(workflow_id),
        "run_id": bounded_text(run_id),
        "trigger_type": bounded_text(trigger_type, 80),
    }
    return {
        "id": str(uuid.uuid4()),
        "user_id": bounded_text(user_id),
        "activity_type": f"{target.kind}_run",
        "timestamp": timestamp,
        "created_at": timestamp,
        "entity_type": target.kind,
        "operation": "run",
        "status": usage["outcome"],
        "workspace_type": bounded_text(workspace_type, 32),
        "workspace_context": {
            key: bounded_text(value) for key, value in (
                ("group_id", group_id), ("public_workspace_id", public_workspace_id),
            ) if value
        },
        "conversation_id": bounded_text(conversation_id),
        "runtime_usage": usage,
    }


def emit_usage(target, **fields):
    # Storage is owned by the initialized activity logger, not this bootstrap-free contract.
    from functions_activity_logging import log_runtime_usage

    log_runtime_usage(target, **fields)


def exception_outcome(error):
    if isinstance(error, TimeoutError) or "Timeout" in type(error).__name__:
        return "timeout"
    if "Cancel" in type(error).__name__ or isinstance(error, GeneratorExit):
        return "cancelled"
    return "failed"


@contextmanager
def usage_attempt(target, *, user_id, attempt_id=None, **context):
    """Emit once when an actual runtime attempt exits, without intercepting its result."""
    started = time.perf_counter()
    attempt_id = attempt_id or str(uuid.uuid4())
    outcome = "succeeded"
    try:
        yield
    except BaseException as error:
        outcome = exception_outcome(error)
        raise
    finally:
        emit_usage(
            target, user_id=user_id, attempt_id=attempt_id, outcome=outcome,
            duration_ms=(time.perf_counter() - started) * 1000, **context,
        )
