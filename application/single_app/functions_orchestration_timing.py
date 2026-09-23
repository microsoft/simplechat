# functions_orchestration_timing.py
"""Shared orchestration timeout policy, independent of application bootstrap.

Version: 0.261.129
The initial V2 claim owns durable timing. Continuation never derives a new
deadline from current settings; legacy execution retains its monotonic budget.
"""

from datetime import timedelta


_DEFAULT_TOTAL_TIMEOUT_SECONDS = 600


def positive_setting_int(settings, key, default):
    """Preserve the executor's existing positive-integer fallback semantics."""
    try:
        value = int((settings or {}).get(key))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def execution_timeout_seconds(settings):
    return positive_setting_int(
        settings, "chat_orchestration_total_timeout_seconds", _DEFAULT_TOTAL_TIMEOUT_SECONDS,
    )


def initial_execution_deadline(started_at, settings):
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("Execution timing requires a timezone-aware start.")
    return (started_at + timedelta(seconds=execution_timeout_seconds(settings))).isoformat()
