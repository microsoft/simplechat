# functions_data_management_migration_state.py
"""Durable, secret-free checkpoint state for Data Management migrations."""

import copy
import hashlib
import json
from datetime import datetime, timezone


MIGRATION_STATE_SCHEMA_VERSION = 1
MIGRATION_RESOURCE_STATUS_PENDING = "pending"
MIGRATION_RESOURCE_STATUS_IN_PROGRESS = "in_progress"
MIGRATION_RESOURCE_STATUS_COMPLETED = "completed"
MIGRATION_RESOURCE_STATUS_FAILED = "failed"


def _utc_now_iso(current_time=None):
    """Return a normalized UTC timestamp without accepting local wall-clock time."""
    timestamp = current_time if isinstance(current_time, datetime) else datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _parse_utc_datetime(value):
    """Parse a durable checkpoint timestamp when it is valid."""
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_migration_configuration_fingerprint(configuration):
    """Hash a caller-supplied, secret-free configuration snapshot."""
    encoded = json.dumps(
        configuration if isinstance(configuration, dict) else {},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def initialize_migration_state(existing_state, migration_id, configuration, current_time=None):
    """Create or resume an in-job migration state with fingerprint protection."""
    fingerprint = build_migration_configuration_fingerprint(configuration)
    timestamp = _utc_now_iso(current_time)
    state = copy.deepcopy(existing_state) if isinstance(existing_state, dict) else {}

    if state:
        if state.get("schema_version") != MIGRATION_STATE_SCHEMA_VERSION:
            raise ValueError("Migration state uses an unsupported schema version.")
        if state.get("migration_id") != migration_id:
            raise ValueError("Migration state belongs to a different migration ID.")
        if state.get("configuration_fingerprint") != fingerprint:
            raise ValueError("Migration settings changed after the job was checkpointed. Queue a new migration job.")
        state["status"] = MIGRATION_RESOURCE_STATUS_IN_PROGRESS
        state["updated_at"] = timestamp
        state["resume_count"] = int(state.get("resume_count") or 0) + 1
        state.setdefault("resources", {})
        state.setdefault("preflight", {})
        state.setdefault("capacity", {})
        state.setdefault("totals", {})
        return state

    return {
        "schema_version": MIGRATION_STATE_SCHEMA_VERSION,
        "migration_id": migration_id,
        "configuration": copy.deepcopy(configuration if isinstance(configuration, dict) else {}),
        "configuration_fingerprint": fingerprint,
        "status": MIGRATION_RESOURCE_STATUS_IN_PROGRESS,
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "source_cutoff_at": timestamp,
        "resume_count": 0,
        "resources": {},
        "preflight": {},
        "capacity": {},
        "totals": {},
    }


def get_migration_resource(state, resource_name):
    """Return a resource checkpoint without allocating a missing record."""
    resources = state.get("resources") if isinstance(state, dict) else None
    return resources.get(resource_name) if isinstance(resources, dict) else None


def is_migration_resource_completed(state, resource_name):
    """Return whether a resource completed successfully in this migration."""
    resource = get_migration_resource(state, resource_name)
    return isinstance(resource, dict) and resource.get("status") == MIGRATION_RESOURCE_STATUS_COMPLETED


def start_migration_resource(state, resource_name, current_time=None):
    """Start or resume one resource while preserving its last durable counters."""
    if not isinstance(state, dict):
        raise ValueError("Migration state must be a dictionary.")
    timestamp = _utc_now_iso(current_time)
    resources = state.setdefault("resources", {})
    existing = resources.get(resource_name) if isinstance(resources, dict) else None
    if isinstance(existing, dict) and existing.get("status") == MIGRATION_RESOURCE_STATUS_COMPLETED:
        return existing

    progress = copy.deepcopy(existing.get("progress") if isinstance(existing, dict) else {})
    attempts = int(existing.get("attempts") or 0) + 1 if isinstance(existing, dict) else 1
    resource = {
        "status": MIGRATION_RESOURCE_STATUS_IN_PROGRESS,
        "attempts": attempts,
        "started_at": existing.get("started_at") if isinstance(existing, dict) and existing.get("started_at") else timestamp,
        "attempt_started_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "last_error": None,
        "progress": progress,
        "result": {},
    }
    resources[resource_name] = resource
    state["updated_at"] = timestamp
    return resource


def update_migration_resource(state, resource_name, progress, current_time=None):
    """Persist counters for an active resource checkpoint."""
    resource = get_migration_resource(state, resource_name)
    if not isinstance(resource, dict):
        raise ValueError(f"Migration resource '{resource_name}' was not started.")
    if resource.get("status") == MIGRATION_RESOURCE_STATUS_COMPLETED:
        raise ValueError(f"Migration resource '{resource_name}' is already completed.")
    timestamp = _utc_now_iso(current_time)
    resource["progress"] = copy.deepcopy(progress if isinstance(progress, dict) else {})
    resource["updated_at"] = timestamp
    state["updated_at"] = timestamp
    return resource


def complete_migration_resource(state, resource_name, result=None, current_time=None):
    """Mark a resource completed only after its final target writes are known."""
    resource = get_migration_resource(state, resource_name)
    if not isinstance(resource, dict):
        raise ValueError(f"Migration resource '{resource_name}' was not started.")
    timestamp = _utc_now_iso(current_time)
    resource.update({
        "status": MIGRATION_RESOURCE_STATUS_COMPLETED,
        "updated_at": timestamp,
        "completed_at": timestamp,
        "last_error": None,
        "result": copy.deepcopy(result if isinstance(result, dict) else {}),
    })
    state["updated_at"] = timestamp
    return resource


def fail_migration_resource(state, resource_name, error_message, current_time=None):
    """Persist an interrupted resource so the same job can resume it later."""
    resource = get_migration_resource(state, resource_name)
    if not isinstance(resource, dict):
        resource = start_migration_resource(state, resource_name, current_time=current_time)
    timestamp = _utc_now_iso(current_time)
    resource.update({
        "status": MIGRATION_RESOURCE_STATUS_FAILED,
        "updated_at": timestamp,
        "last_error": str(error_message or "Migration resource failed."),
    })
    state["updated_at"] = timestamp
    return resource


def build_transfer_metrics(
    started_at,
    copied_count=0,
    skipped_count=0,
    failed_count=0,
    byte_count=0,
    request_units=0.0,
    current_time=None,
):
    """Calculate bounded, JSON-safe counters and transfer rates for job details."""
    started = _parse_utc_datetime(started_at)
    now = _parse_utc_datetime(current_time) if current_time is not None else datetime.now(timezone.utc)
    elapsed_seconds = max(0.001, (now - started).total_seconds()) if started else 0.001
    copied = max(0, int(copied_count or 0))
    skipped = max(0, int(skipped_count or 0))
    failed = max(0, int(failed_count or 0))
    bytes_transferred = max(0, int(byte_count or 0))
    consumed_request_units = max(0.0, float(request_units or 0.0))
    return {
        "copied_count": copied,
        "skipped_count": skipped,
        "failed_count": failed,
        "processed_count": copied + skipped + failed,
        "bytes": bytes_transferred,
        "request_units": round(consumed_request_units, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "items_per_second": round((copied + skipped + failed) / elapsed_seconds, 3),
        "bytes_per_second": round(bytes_transferred / elapsed_seconds, 3),
        "request_units_per_second": round(consumed_request_units / elapsed_seconds, 3),
    }