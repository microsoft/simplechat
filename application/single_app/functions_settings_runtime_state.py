# functions_settings_runtime_state.py
"""Settings keys that record the application's own runtime state, not configuration.

Version: 0.261.303
Implemented in: 0.261.303

The settings document also holds values the application writes for itself while it
runs: storage metadata that changes on every save, background monitor readings and
schedule bookkeeping. An administrator never approved any of them as policy, so a
fingerprint of "the settings this work ran under" has to leave them out. Including them
made any background save look like a policy change to saved orchestration progress.

Configuration an administrator saves stays in the fingerprint, so a real policy change
still fails closed. This module imports only owners that never load configuration, so
low-level modules such as orchestration checkpoints can use it.
"""

from app_settings_store import COSMOS_METADATA_FIELDS, SETTINGS_REVISION_FIELD
from functions_logging_timers import LOGGING_TIMERS


# Written by the settings store itself on every save.
SETTINGS_STORAGE_KEYS = frozenset({*COSMOS_METADATA_FIELDS, SETTINGS_REVISION_FIELD, "id"})

# Written by background tasks and request side effects as the application runs.
SETTINGS_RUNTIME_STATE_KEYS = frozenset({
    # Semantic search quota warnings, recorded and cleared by searches.
    "service_health",
    # Control Center auto-refresh bookkeeping.
    "control_center_last_refresh",
    # Retention policy run bookkeeping.
    "retention_policy_last_run",
    "retention_policy_next_run",
    # The cached application release check.
    "last_update_check_time",
    "last_update_check_attempt_time",
    "last_update_check_failed",
    "latest_version_available",
    "update_available",
    # Log switches and their timers, which the background checker turns off.
    *(key for timer in LOGGING_TIMERS.values() for key in timer.values()),
})

SETTINGS_RUNTIME_STATE_PREFIXES = (
    # Cosmos DB throughput monitoring: readings, scale history and the per-container
    # policies whose scale timestamps the monitor updates.
    "cosmos_throughput_",
    # The Control Center auto-refresh schedule the refresh task seeds and advances.
    "control_center_auto_refresh_",
)


def is_settings_runtime_state_key(key):
    """Whether a settings key holds storage metadata or runtime state rather than configuration."""
    return type(key) is str and (
        key in SETTINGS_STORAGE_KEYS
        or key in SETTINGS_RUNTIME_STATE_KEYS
        or key.startswith(SETTINGS_RUNTIME_STATE_PREFIXES)
    )


def configuration_settings(settings):
    """A shallow copy of ``settings`` without storage metadata or runtime state."""
    return {
        key: value for key, value in (settings or {}).items()
        if not is_settings_runtime_state_key(key)
    }
