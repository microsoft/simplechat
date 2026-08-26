# functions_data_management_search_write_fence.py
"""Cross-app Azure AI Search write fencing for Data Management migrations."""

import copy
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError


DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID = "data_management_search_write_gate_global"
DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE = "data_management_search_write_gate"
DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_OPEN = "open"
DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_CLOSING = "closing"
DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_FROZEN = "frozen"
DATA_MANAGEMENT_SEARCH_WRITE_REQUEST_TIMEOUT_SECONDS = 30
DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS = 150
DATA_MANAGEMENT_SEARCH_WRITE_GATE_POLL_SECONDS = 0.1
DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID = (
    "data_management_target_migration_coordinator_global"
)
DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_TYPE = (
    "data_management_target_migration_coordinator"
)


class DataManagementSearchWriteGateError(RuntimeError):
    """Raised when the durable Search write gate cannot be coordinated safely."""


class DataManagementSearchWritesFrozenError(DataManagementSearchWriteGateError):
    """Raised when a target migration has frozen SimpleChat Search writes."""


class DataManagementSearchWriteFenceLostError(DataManagementSearchWriteGateError):
    """Raised when a migration no longer owns its target Search write fence."""


class DataManagementTargetMigrationCoordinatorError(DataManagementSearchWriteGateError):
    """Raised when a target migration coordinator cannot be acquired safely."""


class DataManagementTargetMigrationCoordinatorLostError(
    DataManagementTargetMigrationCoordinatorError
):
    """Raised when a migration no longer owns its target coordinator lease."""


def _now_utc():
    return datetime.now(timezone.utc)


def _parse_utc_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value, default=0, minimum=0):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, normalized)


def _is_not_found_error(exc):
    return (
        getattr(exc, "status_code", None) == 404 or
        isinstance(exc, (KeyError, ResourceNotFoundError))
    )


def _is_conflict_error(exc):
    return getattr(exc, "status_code", None) in {409, 412}


def _read_gate(container):
    try:
        gate = container.read_item(
            item=DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID,
            partition_key=DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID,
        )
    except Exception as exc:
        if _is_not_found_error(exc):
            return None
        raise DataManagementSearchWriteGateError(
            "The Data Management Search write gate could not be read."
        ) from exc
    if not isinstance(gate, dict):
        raise DataManagementSearchWriteGateError(
            "The Data Management Search write gate has an invalid record."
        )
    return gate


def _new_open_gate(now=None):
    timestamp = now or _now_utc()
    return {
        "id": DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID,
        "type": DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE,
        "state": DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_OPEN,
        "writer_leases": [],
        "active_writer_count": 0,
        "updated_at": timestamp.isoformat(),
    }


def _create_or_read_gate(container):
    gate = _read_gate(container)
    if gate is not None:
        return gate
    try:
        return container.create_item(body=_new_open_gate())
    except Exception as exc:
        if _is_conflict_error(exc):
            gate = _read_gate(container)
            if gate is not None:
                return gate
        raise DataManagementSearchWriteGateError(
            "The Data Management Search write gate could not be created."
        ) from exc


def _replace_gate(container, existing_gate, replacement_gate):
    try:
        return container.replace_item(
            item=DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID,
            body=replacement_gate,
            etag=existing_gate.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        if _is_conflict_error(exc):
            return None
        raise DataManagementSearchWriteGateError(
            "The Data Management Search write gate could not be updated."
        ) from exc


def _active_writer_leases(gate, now=None):
    timestamp = now or _now_utc()
    active_leases = []
    for lease in (gate or {}).get("writer_leases") or []:
        if not isinstance(lease, dict) or not lease.get("token"):
            continue
        expires_at = _parse_utc_datetime(lease.get("expires_at"))
        if expires_at and expires_at > timestamp:
            active_leases.append({
                "token": str(lease.get("token")),
                "expires_at": expires_at.isoformat(),
            })
    return active_leases


def _is_active_migration_fence(gate, now=None):
    timestamp = now or _now_utc()
    expires_at = _parse_utc_datetime((gate or {}).get("expires_at"))
    return bool(
        (gate or {}).get("type") == DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE and
        (gate or {}).get("state") in {
            DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_CLOSING,
            DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_FROZEN,
        } and
        expires_at and
        expires_at > timestamp
    )


def _open_expired_gate(container, gate, now=None):
    timestamp = now or _now_utc()
    if _is_active_migration_fence(gate, timestamp):
        return gate
    replacement = _new_open_gate(timestamp)
    replacement["writer_leases"] = _active_writer_leases(gate, timestamp)
    replacement["active_writer_count"] = len(replacement["writer_leases"])
    return _replace_gate(container, gate, replacement)


def acquire_data_management_search_write_slot(container):
    """Reserve one bounded target Search write before issuing the data-plane request."""
    deadline = time.monotonic() + DATA_MANAGEMENT_SEARCH_WRITE_REQUEST_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        now = _now_utc()
        gate = _create_or_read_gate(container)
        if gate.get("type") != DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE:
            raise DataManagementSearchWriteGateError(
                "The Data Management Search write gate has an unexpected record type."
            )
        if _is_active_migration_fence(gate, now):
            raise DataManagementSearchWritesFrozenError(
                "AI Search writes are temporarily frozen while a Data Management migration is running."
            )
        if gate.get("state") != DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_OPEN:
            if _open_expired_gate(container, gate, now) is None:
                continue
            continue
        lease_token = uuid.uuid4().hex
        replacement = copy.deepcopy(gate)
        active_leases = _active_writer_leases(gate, now)
        active_leases.append({
            "token": lease_token,
            "expires_at": (
                now + timedelta(seconds=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS)
            ).isoformat(),
        })
        replacement.update({
            "writer_leases": active_leases,
            "active_writer_count": len(active_leases),
            "updated_at": now.isoformat(),
        })
        if _replace_gate(container, gate, replacement) is not None:
            return lease_token
        time.sleep(DATA_MANAGEMENT_SEARCH_WRITE_GATE_POLL_SECONDS)
    raise DataManagementSearchWriteGateError(
        "The Data Management Search write gate could not reserve a write slot before the request timeout."
    )


def release_data_management_search_write_slot(container, lease_token):
    """Release one target Search write slot without masking the caller's result."""
    for _attempt in range(12):
        try:
            gate = _read_gate(container)
        except DataManagementSearchWriteGateError:
            return False
        if gate is None or gate.get("type") != DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE:
            return False
        now = _now_utc()
        replacement = copy.deepcopy(gate)
        active_leases = [
            lease
            for lease in _active_writer_leases(gate, now)
            if lease.get("token") != lease_token
        ]
        replacement.update({
            "writer_leases": active_leases,
            "active_writer_count": len(active_leases),
            "updated_at": now.isoformat(),
        })
        if _replace_gate(container, gate, replacement) is not None:
            return True
    return False


@contextmanager
def hold_data_management_search_write_slot(container):
    """Hold a target Search write slot until a response is known or its ambiguity lease expires."""
    lease_token = acquire_data_management_search_write_slot(container)
    response_confirmed = False
    try:
        yield
        response_confirmed = True
    finally:
        if response_confirmed:
            release_data_management_search_write_slot(container, lease_token)


def acquire_data_management_search_write_fence(
    container,
    migration_id,
    lease_seconds,
    heartbeat_callback=None,
):
    """Close target SimpleChat Search writes, drain active slots, and freeze the gate."""
    normalized_migration_id = str(migration_id or "").strip()
    if not normalized_migration_id:
        raise DataManagementSearchWriteGateError(
            "A migration ID is required to acquire the target Search write fence."
        )
    normalized_lease_seconds = _safe_int(
        lease_seconds,
        default=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS,
        minimum=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS,
    )
    fence_token = uuid.uuid4().hex
    last_heartbeat = 0.0
    last_fence_renewal = 0.0
    while True:
        now = _now_utc()
        gate = _create_or_read_gate(container)
        if gate.get("type") != DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE:
            raise DataManagementSearchWriteGateError(
                "The Data Management Search write gate has an unexpected record type."
            )
        state = gate.get("state")
        same_fence = (
            gate.get("migration_id") == normalized_migration_id and
            gate.get("fence_token") == fence_token
        )
        if _is_active_migration_fence(gate, now) and not same_fence:
            raise DataManagementSearchWritesFrozenError(
                "Another migration is already freezing target AI Search writes."
            )
        if state != DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_CLOSING or not same_fence:
            replacement = copy.deepcopy(gate)
            active_leases = _active_writer_leases(gate, now)
            replacement.update({
                "state": DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_CLOSING,
                "migration_id": normalized_migration_id,
                "fence_token": fence_token,
                "expires_at": (
                    now + timedelta(seconds=normalized_lease_seconds)
                ).isoformat(),
                "writer_leases": active_leases,
                "active_writer_count": len(active_leases),
                "updated_at": now.isoformat(),
            })
            if _replace_gate(container, gate, replacement) is None:
                continue
            gate = replacement
        if (
            state == DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_CLOSING and
            same_fence and
            time.monotonic() - last_fence_renewal >= 2.0
        ):
            replacement = copy.deepcopy(gate)
            replacement.update({
                "expires_at": (
                    now + timedelta(seconds=normalized_lease_seconds)
                ).isoformat(),
                "updated_at": now.isoformat(),
            })
            persisted = _replace_gate(container, gate, replacement)
            if persisted is None:
                continue
            gate = persisted
            last_fence_renewal = time.monotonic()
        active_leases = _active_writer_leases(gate, now)
        if not active_leases:
            replacement = copy.deepcopy(gate)
            replacement.update({
                "state": DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_FROZEN,
                "writer_leases": [],
                "active_writer_count": 0,
                "updated_at": now.isoformat(),
            })
            if _replace_gate(container, gate, replacement) is not None:
                return {
                    "id": DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID,
                    "migration_id": normalized_migration_id,
                    "fence_token": fence_token,
                    "lease_seconds": normalized_lease_seconds,
                    "expires_at": replacement.get("expires_at"),
                }
            continue
        if callable(heartbeat_callback) and time.monotonic() - last_heartbeat >= 2.0:
            heartbeat_callback()
            last_heartbeat = time.monotonic()
        time.sleep(DATA_MANAGEMENT_SEARCH_WRITE_GATE_POLL_SECONDS)


def renew_data_management_search_write_fence(container, fence, lease_seconds):
    """Renew a migration-owned frozen target Search gate."""
    if not isinstance(fence, dict) or not fence.get("fence_token"):
        return None
    now = _now_utc()
    gate = _read_gate(container)
    if (
        not isinstance(gate, dict) or
        gate.get("type") != DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE or
        gate.get("migration_id") != fence.get("migration_id") or
        gate.get("fence_token") != fence.get("fence_token") or
        not _is_active_migration_fence(gate, now)
    ):
        raise DataManagementSearchWriteFenceLostError(
            "The target AI Search write fence was lost or expired."
        )
    normalized_lease_seconds = _safe_int(
        lease_seconds,
        default=fence.get("lease_seconds"),
        minimum=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS,
    )
    replacement = copy.deepcopy(gate)
    replacement.update({
        "expires_at": (now + timedelta(seconds=normalized_lease_seconds)).isoformat(),
        "updated_at": now.isoformat(),
    })
    renewed = _replace_gate(container, gate, replacement)
    if renewed is None:
        raise DataManagementSearchWriteFenceLostError(
            "The target AI Search write fence changed during renewal."
        )
    fence["expires_at"] = renewed.get("expires_at", replacement.get("expires_at"))
    fence["lease_seconds"] = normalized_lease_seconds
    return fence


def release_data_management_search_write_fence(container, fence):
    """Open only the exact target Search gate owned by the completed migration."""
    if not isinstance(fence, dict) or not fence.get("fence_token"):
        return False
    for _attempt in range(12):
        gate = _read_gate(container)
        if (
            not isinstance(gate, dict) or
            gate.get("type") != DATA_MANAGEMENT_SEARCH_WRITE_GATE_TYPE or
            gate.get("migration_id") != fence.get("migration_id") or
            gate.get("fence_token") != fence.get("fence_token")
        ):
            return False
        now = _now_utc()
        replacement = _new_open_gate(now)
        replacement["writer_leases"] = _active_writer_leases(gate, now)
        replacement["active_writer_count"] = len(replacement["writer_leases"])
        if _replace_gate(container, gate, replacement) is not None:
            return True
    return False


def _read_target_migration_coordinator(container):
    try:
        coordinator = container.read_item(
            item=DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
            partition_key=DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
        )
    except Exception as exc:
        if _is_not_found_error(exc):
            return None
        raise DataManagementTargetMigrationCoordinatorError(
            "The target migration coordinator could not be read."
        ) from exc
    if not isinstance(coordinator, dict):
        raise DataManagementTargetMigrationCoordinatorError(
            "The target migration coordinator has an invalid record."
        )
    return coordinator


def _replace_target_migration_coordinator(container, existing, replacement):
    try:
        return container.replace_item(
            item=DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
            body=replacement,
            etag=existing.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        if _is_conflict_error(exc):
            return None
        raise DataManagementTargetMigrationCoordinatorError(
            "The target migration coordinator could not be updated."
        ) from exc


def _target_migration_coordinator_is_active(coordinator, now=None):
    timestamp = now or _now_utc()
    expires_at = _parse_utc_datetime((coordinator or {}).get("expires_at"))
    return bool(
        (coordinator or {}).get("type") ==
        DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_TYPE and
        expires_at and
        expires_at > timestamp
    )


def inspect_data_management_target_migration_coordinator(container):
    """Return secret-free destination coordinator readiness."""
    coordinator = _read_target_migration_coordinator(container)
    active = _target_migration_coordinator_is_active(coordinator)
    return {
        "available": not active,
        "active": active,
        "expires_at": coordinator.get("expires_at") if active else None,
    }


def inspect_data_management_search_write_gate(container):
    """Return secret-free Search write-gate readiness."""
    gate = _read_gate(container)
    if gate is None:
        return {
            "available": True,
            "state": DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_OPEN,
            "active_writer_count": 0,
            "expires_at": None,
        }
    active_fence = _is_active_migration_fence(gate)
    return {
        "available": not active_fence,
        "state": gate.get("state") or DATA_MANAGEMENT_SEARCH_WRITE_GATE_STATE_OPEN,
        "active_writer_count": len(_active_writer_leases(gate)),
        "expires_at": gate.get("expires_at") if active_fence else None,
    }


def _new_target_migration_coordinator(migration_id, lock_token, lease_seconds, now=None):
    timestamp = now or _now_utc()
    return {
        "id": DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
        "type": DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_TYPE,
        "migration_id": str(migration_id),
        "lock_token": str(lock_token),
        "acquired_at": timestamp.isoformat(),
        "updated_at": timestamp.isoformat(),
        "lease_seconds": int(lease_seconds),
        "expires_at": (timestamp + timedelta(seconds=int(lease_seconds))).isoformat(),
    }


def acquire_data_management_target_migration_coordinator(
    container,
    migration_id,
    lease_seconds,
    existing_lock=None,
):
    """Acquire one destination-wide coordinator before any migration mutation begins."""
    normalized_migration_id = str(migration_id or "").strip()
    if not normalized_migration_id:
        raise DataManagementTargetMigrationCoordinatorError(
            "A migration ID is required to acquire the target migration coordinator."
        )
    normalized_lease_seconds = _safe_int(
        lease_seconds,
        default=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS,
        minimum=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS,
    )
    existing_lock = existing_lock if isinstance(existing_lock, dict) else {}
    existing_token = str(existing_lock.get("lock_token") or "").strip()
    for _attempt in range(12):
        now = _now_utc()
        coordinator = _read_target_migration_coordinator(container)
        if coordinator is None:
            lock_token = existing_token or uuid.uuid4().hex
            replacement = _new_target_migration_coordinator(
                normalized_migration_id,
                lock_token,
                normalized_lease_seconds,
                now,
            )
            try:
                persisted = container.create_item(body=replacement)
            except Exception as exc:
                if _is_conflict_error(exc):
                    continue
                raise DataManagementTargetMigrationCoordinatorError(
                    "The target migration coordinator could not be created."
                ) from exc
            return {
                "id": DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
                "migration_id": normalized_migration_id,
                "lock_token": lock_token,
                "lease_seconds": normalized_lease_seconds,
                "expires_at": persisted.get("expires_at", replacement["expires_at"]),
            }

        if coordinator.get("type") != DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_TYPE:
            raise DataManagementTargetMigrationCoordinatorError(
                "The target migration coordinator has an unexpected record type."
            )
        if _target_migration_coordinator_is_active(coordinator, now):
            if (
                coordinator.get("migration_id") == normalized_migration_id and
                existing_token and
                coordinator.get("lock_token") == existing_token
            ):
                reused_lock = {
                    "id": DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
                    "migration_id": normalized_migration_id,
                    "lock_token": existing_token,
                    "lease_seconds": normalized_lease_seconds,
                    "expires_at": coordinator.get("expires_at"),
                }
                return renew_data_management_target_migration_coordinator(
                    container,
                    reused_lock,
                    normalized_lease_seconds,
                )
            raise DataManagementTargetMigrationCoordinatorError(
                "Another SimpleChat source is actively migrating to this destination."
            )

        replacement = _new_target_migration_coordinator(
            normalized_migration_id,
            existing_token or uuid.uuid4().hex,
            normalized_lease_seconds,
            now,
        )
        persisted = _replace_target_migration_coordinator(
            container,
            coordinator,
            replacement,
        )
        if persisted is None:
            continue
        return {
            "id": DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
            "migration_id": normalized_migration_id,
            "lock_token": replacement["lock_token"],
            "lease_seconds": normalized_lease_seconds,
            "expires_at": persisted.get("expires_at", replacement["expires_at"]),
        }
    raise DataManagementTargetMigrationCoordinatorError(
        "The target migration coordinator changed too often to acquire safely."
    )


def renew_data_management_target_migration_coordinator(container, lock, lease_seconds):
    """Renew an exact target-wide coordinator lease held by this migration."""
    if not isinstance(lock, dict) or not lock.get("lock_token"):
        raise DataManagementTargetMigrationCoordinatorLostError(
            "The target migration coordinator handle is missing."
        )
    coordinator = _read_target_migration_coordinator(container)
    now = _now_utc()
    if (
        not isinstance(coordinator, dict) or
        coordinator.get("type") != DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_TYPE or
        coordinator.get("migration_id") != lock.get("migration_id") or
        coordinator.get("lock_token") != lock.get("lock_token") or
        not _target_migration_coordinator_is_active(coordinator, now)
    ):
        raise DataManagementTargetMigrationCoordinatorLostError(
            "The target migration coordinator was lost, superseded, or expired."
        )
    normalized_lease_seconds = _safe_int(
        lease_seconds,
        default=lock.get("lease_seconds"),
        minimum=DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS,
    )
    replacement = copy.deepcopy(coordinator)
    replacement.update({
        "lease_seconds": normalized_lease_seconds,
        "updated_at": now.isoformat(),
        "expires_at": (
            now + timedelta(seconds=normalized_lease_seconds)
        ).isoformat(),
    })
    persisted = _replace_target_migration_coordinator(
        container,
        coordinator,
        replacement,
    )
    if persisted is None:
        raise DataManagementTargetMigrationCoordinatorLostError(
            "The target migration coordinator changed during renewal."
        )
    lock["lease_seconds"] = normalized_lease_seconds
    lock["expires_at"] = persisted.get("expires_at", replacement["expires_at"])
    return lock


def release_data_management_target_migration_coordinator(container, lock):
    """Release only the exact target coordinator held by a finished migration."""
    if not isinstance(lock, dict) or not lock.get("lock_token"):
        return False
    try:
        coordinator = _read_target_migration_coordinator(container)
    except DataManagementTargetMigrationCoordinatorError:
        return False
    if (
        not isinstance(coordinator, dict) or
        coordinator.get("type") != DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_TYPE or
        coordinator.get("migration_id") != lock.get("migration_id") or
        coordinator.get("lock_token") != lock.get("lock_token")
    ):
        return False
    try:
        container.delete_item(
            item=DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
            partition_key=DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_ID,
            etag=coordinator.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        if _is_conflict_error(exc):
            return False
        return False
    return True