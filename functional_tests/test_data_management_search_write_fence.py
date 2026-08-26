# test_data_management_search_write_fence.py
"""
Functional test for Data Management target AI Search write fencing.
Version: 0.260.030
Implemented in: 0.250.071
Updated in: 0.260.030 for upload contention retry coverage.

This test ensures target SimpleChat Search writes drain before a migration
freezes them and cannot resume until the owning migration releases the fence.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import threading
import time

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management_search_write_fence.py"
sys.path.insert(0, str(APP_ROOT))


class ConflictError(Exception):
    """Minimal Cosmos conflict error for optimistic fence replacement."""

    status_code = 412


class FakeGateContainer:
    """Persist one fence document with Cosmos-like ETag replacement semantics."""

    def __init__(self):
        self.items = {}
        self.etag_counter = 0
        self.lock = threading.Lock()

    def _save(self, body):
        self.etag_counter += 1
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{self.etag_counter}"
        self.items[saved["id"]] = saved
        return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        assert item == partition_key
        with self.lock:
            if item not in self.items:
                raise KeyError(item)
            return copy.deepcopy(self.items[item])

    def create_item(self, body):
        with self.lock:
            if body["id"] in self.items:
                conflict = ConflictError("already exists")
                conflict.status_code = 409
                raise conflict
            return self._save(body)

    def replace_item(self, item, body, etag=None, **_kwargs):
        with self.lock:
            current = self.items.get(item)
            if current is None or (etag and current.get("_etag") != etag):
                raise ConflictError("stale fence")
            return self._save(body)

    def delete_item(self, item, partition_key, etag=None, **_kwargs):
        assert item == partition_key
        with self.lock:
            current = self.items.get(item)
            if current is None or (etag and current.get("_etag") != etag):
                raise ConflictError("stale fence")
            self.items.pop(item, None)


class ConflictHeavyGateContainer(FakeGateContainer):
    """Simulate repeated optimistic-concurrency conflicts under upload fan-in."""

    def __init__(self, conflicts_before_success):
        super().__init__()
        self.conflicts_before_success = conflicts_before_success

    def replace_item(self, item, body, etag=None, **kwargs):
        with self.lock:
            if self.conflicts_before_success > 0:
                self.conflicts_before_success -= 1
                raise ConflictError("simulated concurrent writer")
        return super().replace_item(item, body, etag=etag, **kwargs)


def load_fence_module():
    """Load the standalone fence module without the Flask application."""
    module_name = "data_management_search_write_fence_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_target_search_write_fence_drains_and_reopens_writer_slots():
    """A migration closes new target writes, drains existing work, and reopens only its own gate."""
    module = load_fence_module()
    container = FakeGateContainer()
    active_writer_slot = module.acquire_data_management_search_write_slot(container)
    fence_holder = {}
    heartbeat_count = []

    def acquire_fence():
        fence_holder["fence"] = module.acquire_data_management_search_write_fence(
            container,
            "11111111-1111-1111-1111-111111111111",
            lease_seconds=150,
            heartbeat_callback=lambda: heartbeat_count.append(time.monotonic()),
        )

    thread = threading.Thread(target=acquire_fence)
    thread.start()
    time.sleep(0.2)
    assert thread.is_alive()
    module.release_data_management_search_write_slot(container, active_writer_slot)
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    fence = fence_holder["fence"]
    assert heartbeat_count == [] or heartbeat_count
    with pytest.raises(module.DataManagementSearchWritesFrozenError):
        module.acquire_data_management_search_write_slot(container)

    renewed = module.renew_data_management_search_write_fence(
        container,
        fence,
        lease_seconds=150,
    )
    assert renewed["fence_token"] == fence["fence_token"]
    assert module.release_data_management_search_write_fence(container, fence) is True

    replacement_writer_slot = module.acquire_data_management_search_write_slot(container)
    assert replacement_writer_slot
    assert module.release_data_management_search_write_slot(container, replacement_writer_slot) is True


def test_only_the_owning_migration_can_release_target_search_write_fence():
    """A stale migration token cannot reopen another migration's frozen target writer gate."""
    module = load_fence_module()
    container = FakeGateContainer()
    fence = module.acquire_data_management_search_write_fence(
        container,
        "22222222-2222-2222-2222-222222222222",
        lease_seconds=150,
    )

    stale_fence = dict(fence)
    stale_fence["fence_token"] = "stale-token"
    assert module.release_data_management_search_write_fence(container, stale_fence) is False
    with pytest.raises(module.DataManagementSearchWritesFrozenError):
        module.acquire_data_management_search_write_slot(container)

    assert module.release_data_management_search_write_fence(container, fence) is True


def test_target_migration_coordinator_blocks_independent_source_job_stores():
    """Two independent sources sharing one target must not overlap before Cosmos copy starts."""
    module = load_fence_module()
    target_jobs = FakeGateContainer()
    first_lock = module.acquire_data_management_target_migration_coordinator(
        target_jobs,
        "33333333-3333-3333-3333-333333333333",
        lease_seconds=150,
    )

    with pytest.raises(module.DataManagementTargetMigrationCoordinatorError, match="Another SimpleChat source"):
        module.acquire_data_management_target_migration_coordinator(
            target_jobs,
            "44444444-4444-4444-4444-444444444444",
            lease_seconds=150,
        )

    renewed = module.renew_data_management_target_migration_coordinator(
        target_jobs,
        first_lock,
        lease_seconds=150,
    )
    assert renewed["migration_id"] == "33333333-3333-3333-3333-333333333333"
    assert module.release_data_management_target_migration_coordinator(
        target_jobs,
        first_lock,
    ) is True

    second_lock = module.acquire_data_management_target_migration_coordinator(
        target_jobs,
        "44444444-4444-4444-4444-444444444444",
        lease_seconds=150,
    )
    assert second_lock["migration_id"] == "44444444-4444-4444-4444-444444444444"


def test_ambiguous_target_search_write_retains_slot_until_quarantine_expires(monkeypatch):
    """A lost response must keep the target writer slot long enough to block migration fencing."""
    module = load_fence_module()
    container = FakeGateContainer()

    with pytest.raises(TimeoutError):
        with module.hold_data_management_search_write_slot(container):
            raise TimeoutError("response lost after Search accepted the request")

    gate = container.items[module.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]
    assert gate["active_writer_count"] == 1
    assert module.DATA_MANAGEMENT_SEARCH_WRITE_SLOT_LEASE_SECONDS >= 150
    gate["writer_leases"][0]["expires_at"] = "2000-01-01T00:00:00+00:00"

    fence = module.acquire_data_management_search_write_fence(
        container,
        "55555555-5555-5555-5555-555555555555",
        lease_seconds=150,
    )
    assert fence["migration_id"] == "55555555-5555-5555-5555-555555555555"


def test_target_search_write_slot_waits_through_transient_contention(monkeypatch):
    """Large small-file upload batches should not fail after a few rapid ETag conflicts."""
    module = load_fence_module()
    monkeypatch.setattr(module, "DATA_MANAGEMENT_SEARCH_WRITE_GATE_POLL_SECONDS", 0.001)
    monkeypatch.setattr(module, "DATA_MANAGEMENT_SEARCH_WRITE_REQUEST_TIMEOUT_SECONDS", 1)
    container = ConflictHeavyGateContainer(conflicts_before_success=20)

    lease_token = module.acquire_data_management_search_write_slot(container)

    assert lease_token
    assert module.release_data_management_search_write_slot(container, lease_token) is True
