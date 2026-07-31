# functions_data_management_restore_state.py
"""Durable, secret-free checkpoint state for Data Management restores."""

import copy
import hashlib
import json
from datetime import datetime, timezone


RESTORE_STATE_SCHEMA_VERSION = 1
RESTORE_RESOURCE_STATUS_PENDING = "pending"
RESTORE_RESOURCE_STATUS_IN_PROGRESS = "in_progress"
RESTORE_RESOURCE_STATUS_COMPLETED = "completed"
RESTORE_RESOURCE_STATUS_FAILED = "failed"
RESTORE_STATE_MAX_ATTEMPT_HISTORY = 20


def _utc_now_iso(current_time=None):
    """Return a normalized UTC timestamp without accepting local wall-clock time."""
    timestamp = current_time if isinstance(current_time, datetime) else datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def build_restore_configuration_fingerprint(configuration):
    """Hash a caller-supplied, secret-free immutable restore plan."""
    encoded = json.dumps(
        configuration if isinstance(configuration, dict) else {},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def initialize_restore_state(
    existing_state,
    restore_id,
    normalized_plan,
    current_time=None,
):
    """Create or resume restore state while protecting immutable plan values."""
    plan = copy.deepcopy(normalized_plan if isinstance(normalized_plan, dict) else {})
    fingerprint = build_restore_configuration_fingerprint(plan)
    timestamp = _utc_now_iso(current_time)
    state = copy.deepcopy(existing_state) if isinstance(existing_state, dict) else {}

    if state:
        if state.get("schema_version") != RESTORE_STATE_SCHEMA_VERSION:
            raise ValueError("Restore state uses an unsupported schema version.")
        if state.get("restore_id") != restore_id:
            raise ValueError("Restore state belongs to a different restore job.")
        if state.get("configuration_fingerprint") != fingerprint:
            raise ValueError("Restore plan changed after the job was checkpointed. Queue a new restore job.")
        state["status"] = RESTORE_RESOURCE_STATUS_IN_PROGRESS
        state["updated_at"] = timestamp
        state["resume_count"] = int(state.get("resume_count") or 0) + 1
        state.setdefault("attempt_history", [])
        state.setdefault("resources", {})
        state.setdefault("preflight", {})
        state.setdefault("totals", {})
        state.setdefault("warnings", [])
        return state

    return {
        "schema_version": RESTORE_STATE_SCHEMA_VERSION,
        "restore_id": restore_id,
        "normalized_plan": plan,
        "configuration_fingerprint": fingerprint,
        "status": RESTORE_RESOURCE_STATUS_PENDING,
        "phase": "queued",
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "resume_count": 0,
        "attempt_history": [],
        "resources": {},
        "preflight": {},
        "totals": {},
        "warnings": [],
    }


def start_restore_attempt(state, attempt_id, lease_generation, current_time=None):
    """Record one fenced execution attempt while retaining a bounded history."""
    if not isinstance(state, dict):
        raise ValueError("Restore state must be a dictionary.")
    timestamp = _utc_now_iso(current_time)
    history = state.setdefault("attempt_history", [])
    if history:
        state["resume_count"] = int(state.get("resume_count") or 0) + 1
    history.append({
        "attempt_id": str(attempt_id or ""),
        "lease_generation": int(lease_generation or 0),
        "started_at": timestamp,
        "completed_at": None,
        "outcome": "running",
    })
    del history[:-RESTORE_STATE_MAX_ATTEMPT_HISTORY]
    state.update({
        "status": RESTORE_RESOURCE_STATUS_IN_PROGRESS,
        "phase": "initializing",
        "updated_at": timestamp,
        "completed_at": None,
    })
    return state


def complete_restore_attempt(state, outcome, current_time=None):
    """Close the current bounded attempt record at a durable terminal boundary."""
    if not isinstance(state, dict):
        raise ValueError("Restore state must be a dictionary.")
    timestamp = _utc_now_iso(current_time)
    history = state.setdefault("attempt_history", [])
    if history and isinstance(history[-1], dict):
        history[-1]["completed_at"] = timestamp
        history[-1]["outcome"] = str(outcome or "completed")
    state["updated_at"] = timestamp
    return state


def get_restore_resource(state, resource_name):
    """Return a resource checkpoint without allocating a missing record."""
    resources = state.get("resources") if isinstance(state, dict) else None
    return resources.get(resource_name) if isinstance(resources, dict) else None


def is_restore_resource_completed(state, resource_name):
    """Return whether one restore resource has a verified durable result."""
    resource = get_restore_resource(state, resource_name)
    return isinstance(resource, dict) and resource.get("status") == RESTORE_RESOURCE_STATUS_COMPLETED


def start_restore_resource(state, resource_name, phase, current_time=None):
    """Start or resume one restore resource while preserving durable progress."""
    if not isinstance(state, dict):
        raise ValueError("Restore state must be a dictionary.")
    timestamp = _utc_now_iso(current_time)
    resources = state.setdefault("resources", {})
    existing = resources.get(resource_name) if isinstance(resources, dict) else None
    if isinstance(existing, dict) and existing.get("status") == RESTORE_RESOURCE_STATUS_COMPLETED:
        return existing

    progress = copy.deepcopy(existing.get("progress") if isinstance(existing, dict) else {})
    checkpoint = copy.deepcopy(existing.get("checkpoint") if isinstance(existing, dict) else {})
    attempts = int(existing.get("attempts") or 0) + 1 if isinstance(existing, dict) else 1
    resource = {
        "status": RESTORE_RESOURCE_STATUS_IN_PROGRESS,
        "phase": str(phase or "restore"),
        "attempts": attempts,
        "started_at": existing.get("started_at") if isinstance(existing, dict) and existing.get("started_at") else timestamp,
        "attempt_started_at": timestamp,
        "updated_at": timestamp,
        "completed_at": None,
        "last_error": None,
        "progress": progress,
        "checkpoint": checkpoint,
        "result": {},
    }
    resources[resource_name] = resource
    state["phase"] = resource["phase"]
    state["updated_at"] = timestamp
    return resource


def update_restore_resource(state, resource_name, progress, checkpoint=None, current_time=None):
    """Persist bounded per-resource restore progress."""
    resource = get_restore_resource(state, resource_name)
    if not isinstance(resource, dict):
        raise ValueError(f"Restore resource '{resource_name}' was not started.")
    if resource.get("status") == RESTORE_RESOURCE_STATUS_COMPLETED:
        raise ValueError(f"Restore resource '{resource_name}' is already completed.")
    timestamp = _utc_now_iso(current_time)
    resource["progress"] = copy.deepcopy(progress if isinstance(progress, dict) else {})
    if checkpoint is not None:
        resource["checkpoint"] = copy.deepcopy(checkpoint if isinstance(checkpoint, dict) else {})
    resource["updated_at"] = timestamp
    state["updated_at"] = timestamp
    return resource


def complete_restore_resource(state, resource_name, result=None, current_time=None):
    """Mark a restore resource complete only after final target writes are known."""
    resource = get_restore_resource(state, resource_name)
    if not isinstance(resource, dict):
        raise ValueError(f"Restore resource '{resource_name}' was not started.")
    timestamp = _utc_now_iso(current_time)
    resource.update({
        "status": RESTORE_RESOURCE_STATUS_COMPLETED,
        "updated_at": timestamp,
        "completed_at": timestamp,
        "last_error": None,
        "result": copy.deepcopy(result if isinstance(result, dict) else {}),
    })
    state["updated_at"] = timestamp
    return resource


def fail_restore_resource(state, resource_name, error_message, current_time=None):
    """Persist a failed restore resource so the same job can resume later."""
    resource = get_restore_resource(state, resource_name)
    if not isinstance(resource, dict):
        resource = start_restore_resource(state, resource_name, "restore", current_time=current_time)
    timestamp = _utc_now_iso(current_time)
    resource.update({
        "status": RESTORE_RESOURCE_STATUS_FAILED,
        "updated_at": timestamp,
        "last_error": str(error_message or "Restore resource failed."),
    })
    state["updated_at"] = timestamp
    return resource
