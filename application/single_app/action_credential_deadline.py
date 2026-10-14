# action_credential_deadline.py
"""Account for human credential waits without changing retained deadline guards."""

from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
import math


MAX_HUMAN_WAIT_SECONDS = 86400


def execution_deadline(value, *, now=None):
    getter = value.get if isinstance(value, Mapping) else lambda key, default=None: getattr(value, key, default)
    deadline = datetime.fromisoformat(getter("execution_deadline_at"))
    if deadline.tzinfo is None:
        raise ValueError("An aware execution deadline is required.")
    seconds = getter("credential_wait_seconds", 0)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= MAX_HUMAN_WAIT_SECONDS:
        raise ValueError("Invalid credential wait accounting.")
    started = getter("credential_wait_started_at")
    if started and getter("status") == "waiting":
        waits = getter("pending_results", {}) or {}
        if any(wait.get("kind") == "action_credentials" for wait in waits.values()):
            moment = datetime.fromisoformat(started)
            if moment.tzinfo is None:
                raise ValueError("An aware credential wait timestamp is required.")
            seconds = min(MAX_HUMAN_WAIT_SECONDS, seconds + max(0, ((now or datetime.now(timezone.utc)) - moment).total_seconds()))
    return deadline + timedelta(seconds=seconds)


def finish_human_wait(record, *, now):
    """Only the owned continuation CAS admits this server-recorded clock adjustment."""
    deadline = execution_deadline(record, now=now)
    original = datetime.fromisoformat(record["execution_deadline_at"])
    return {
        "credential_wait_seconds": (deadline - original).total_seconds(),
        "credential_wait_started_at": None,
    }
