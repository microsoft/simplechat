# test_data_management_cosmos_migration_resilience.py
"""
Functional test for resilient Data Management Cosmos migration.
Version: 0.250.071
Implemented in: 0.250.075

This test ensures the in-app migration uses concurrent destination writes,
remote provenance skips, durable checkpoints, and request-unit throughput.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types

from azure.core.exceptions import ResourceNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_migration_state import initialize_migration_state
from functions_migration_provenance import create_migration_provenance_context


class FakeJobContainer:
    """Persist a deep copy to emulate Cosmos serialization between checkpoints."""

    def __init__(self):
        self.manifest_batches = []

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def create_item(self, body):
        self.manifest_batches.append(copy.deepcopy(body))
        return copy.deepcopy(body)


class FakeSourceContainer:
    """Return a stable source set below the migration cutoff."""

    def __init__(self, documents):
        self.documents = documents
        self.queries = []

    def query_items(self, **kwargs):
        self.queries.append(copy.deepcopy(kwargs))
        parameters = {
            parameter["name"]: parameter["value"]
            for parameter in (kwargs.get("parameters") or [])
        }
        documents = copy.deepcopy(self.documents)
        if "@source_start_epoch" in parameters:
            documents = [
                document for document in documents
                if document.get("_ts", 0) >= parameters["@source_start_epoch"]
            ]
        if "@source_cutoff_epoch" in parameters:
            documents = [
                document for document in documents
                if document.get("_ts", 0) <= parameters["@source_cutoff_epoch"]
            ]
        return iter(documents)


class FakeTargetContainer:
    """Record concurrent writes and return a current-migration destination marker."""

    def __init__(self, migration_id):
        self.migration_id = migration_id
        self.written = []
        self.updated = []
        self.active_writes = 0
        self.maximum_active_writes = 0
        self.lock = threading.Lock()
        self.write_barrier = threading.Barrier(2)
        self.documents = {
            ("already-migrated", "already-migrated"): {
                "id": "already-migrated",
                "simplechatMigration": {
                    "migrationId": migration_id,
                    "migratedAtUtc": "2026-07-24T12:00:00+00:00",
                    "status": "succeeded",
                    "sourceHash": "",
                    "sourceVersion": "1",
                },
            },
        }

    def read_item(self, item, partition_key, **_kwargs):
        document = self.documents.get((item, partition_key))
        if document is None:
            raise ResourceNotFoundError("not found")
        return copy.deepcopy(document)

    def create_item(self, document, response_hook=None, retry_write=None, **_kwargs):
        assert retry_write == 1
        key = (document["id"], document["id"])
        if key in self.documents:
            conflict = RuntimeError("conflict")
            conflict.status_code = 409
            raise conflict
        with self.lock:
            self.active_writes += 1
            self.maximum_active_writes = max(self.maximum_active_writes, self.active_writes)
        try:
            try:
                self.write_barrier.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
            time.sleep(0.03)
            if response_hook:
                response_hook({"x-ms-request-charge": "3.5"}, document)
            self.written.append(copy.deepcopy(document))
            self.documents[key] = copy.deepcopy(document)
            return document
        finally:
            with self.lock:
                self.active_writes -= 1

    def replace_item(self, item, body, etag=None, match_condition=None, response_hook=None, **_kwargs):
        assert match_condition is not None
        key = (body["id"], body["id"])
        assert self.documents.get(key) == item
        if response_hook:
            response_hook({"x-ms-request-charge": "4.0"}, body)
        self.updated.append(copy.deepcopy(body))
        self.documents[key] = copy.deepcopy(body)
        return body


class FakeTargetDatabase:
    """Return the test target container for every requested migration resource."""

    def __init__(self, target_container):
        self.target_container = target_container

    def create_container_if_not_exists(self, **_kwargs):
        return self.target_container


def load_data_management_module(monkeypatch, source_container, job_container):
    """Load the production module with lightweight service dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.075"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.source_container = source_container
    config_module.target_container_name = "target-container"
    monkeypatch.setitem(sys.modules, "config", config_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    throughput_module = types.ModuleType("functions_cosmos_throughput")

    class FakeCosmosThroughputError(Exception):
        pass

    throughput_module.CosmosThroughputError = FakeCosmosThroughputError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)

    module_name = "data_management_migration_resilience_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_data_management_cosmos_migration_runs_concurrently_with_provenance(monkeypatch):
    """Validate target markers skip and unmarked records checkpoint as parallel writes."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    source_container = FakeSourceContainer([
        {"id": "already-migrated", "_ts": 1},
        {"id": "copy-one", "_ts": 1},
        {"id": "copy-two", "_ts": 1},
    ])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_container, job_container)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "user_settings",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "id_field": "id",
        }],
        "groups": [],
        "public_workspaces": [],
    }

    settings = {
        "migration_max_parallel_operations": 2,
        "migration_retry_count": 2,
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": False},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
    }
    migration_state = initialize_migration_state(
        None,
        migration_id,
        {"test": "cosmos"},
    )
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-24T12:00:00+00:00",
    )
    job = {"id": migration_id, "migration_state": migration_state}
    target_container = FakeTargetContainer(migration_id)
    target_container.documents[("already-migrated", "already-migrated")][
        "simplechatMigration"
    ]["sourceHash"] = module._build_cosmos_source_hash({"id": "already-migrated"})

    artifacts = module._copy_cosmos_records_to_target(
        FakeTargetDatabase(target_container),
        "users",
        migration_plan["users"],
        job,
        migration_state,
        provenance_context,
        settings,
    )

    assert len(target_container.written) == 2
    assert target_container.maximum_active_writes >= 2
    assert all(
        document["simplechatMigration"]["migrationId"] == migration_id
        and document["simplechatMigration"]["status"] == "succeeded"
        for document in target_container.written
    )
    assert artifacts[0]["copied_count"] == 2
    assert artifacts[0]["skipped_count"] == 0
    assert artifacts[0]["destination_provenance_skip_count"] == 1
    assert artifacts[0]["request_units"] == 7.0
    resource = job["migration_state"]["resources"]["cosmos:users:user_settings"]
    assert resource["status"] == "completed"
    assert resource["result"]["items_per_second"] > 0
    manifest_entries = [
        entry
        for batch in job_container.manifest_batches
        for entry in batch["entries"]
    ]
    assert len(manifest_entries) == 3
    assert all(entry["source_identity"].startswith("sha256:") for entry in manifest_entries)

    try:
        module._classify_target_cosmos_document(
            {"id": "unowned"},
            provenance_context,
            "target-container",
        )
    except module.DataManagementSettingsValidationError as exc:
        assert "unowned" in str(exc)
    else:
        raise AssertionError("An unowned destination Cosmos record was accepted for overwrite.")


def test_data_management_cosmos_delta_upserts_only_changed_owned_records(monkeypatch):
    """Use the baseline _ts watermark and update only migration-owned changed items."""
    migration_id = "22222222-2222-2222-2222-222222222222"
    baseline_migration_id = "11111111-1111-1111-1111-111111111111"
    baseline_epoch = 1_700_000_000
    source_documents = [
        {"id": "unchanged", "value": "same", "_ts": baseline_epoch},
        {"id": "changed", "value": "new", "_ts": baseline_epoch},
        {"id": "created", "value": "new", "_ts": baseline_epoch + 2},
    ]
    source_container = FakeSourceContainer(source_documents)
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_container, job_container)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "user_settings",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "id_field": "id",
        }],
        "groups": [],
        "public_workspaces": [],
    }
    target_container = FakeTargetContainer(migration_id)
    target_container.documents.update({
        ("unchanged", "unchanged"): {
            "id": "unchanged",
            "value": "same",
            "_etag": "unchanged-etag",
            "simplechatMigration": {
                "migrationId": baseline_migration_id,
                "migratedAtUtc": "2026-07-28T12:00:00+00:00",
                "status": "succeeded",
                    "sourceHash": module._build_cosmos_source_hash(source_documents[0]),
                "sourceVersion": str(baseline_epoch),
            },
        },
        ("changed", "changed"): {
            "id": "changed",
            "value": "old",
            "_etag": "changed-etag",
            "simplechatMigration": {
                "migrationId": baseline_migration_id,
                "migratedAtUtc": "2026-07-28T12:00:00+00:00",
                "status": "succeeded",
                    "sourceHash": module._build_cosmos_source_hash({
                        "id": "changed",
                        "value": "old",
                    }),
                "sourceVersion": str(baseline_epoch),
            },
        },
    })
    migration_state = initialize_migration_state(None, migration_id, {"test": "cosmos-delta"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    provenance_context.update({
        "migration_mode": "delta_upsert",
        "baseline_source_cutoff_at": "2023-11-14T22:13:20+00:00",
    })
    job = {"id": migration_id, "migration_state": migration_state}

    artifacts = module._copy_cosmos_records_to_target(
        FakeTargetDatabase(target_container),
        "users",
        {"mode": "all", "ids": [], "include_documents": False},
        job,
        migration_state,
        provenance_context,
        {
            "migration_max_parallel_operations": 2,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
    )

    assert artifacts[0]["created_count"] == 1
    assert artifacts[0]["updated_count"] == 1
    assert artifacts[0]["unchanged_count"] == 1
    assert artifacts[0]["source_read_count"] == 3
    assert len(target_container.written) == 1
    assert len(target_container.updated) == 1
    assert target_container.updated[0]["id"] == "changed"
    assert target_container.updated[0]["simplechatMigration"]["sourceVersion"] == str(
        baseline_epoch
    )
    assert target_container.updated[0]["simplechatMigration"]["sourceHash"] == (
        module._build_cosmos_source_hash(source_documents[1])
    )
    assert any(
        "c._ts >= @source_start_epoch" in query["query"]
        for query in source_container.queries
    )


def test_cosmos_write_renews_heartbeat_while_request_is_in_flight(monkeypatch):
    """Renew the migration lease before a slow Cosmos write completes."""
    migration_id = "33333333-3333-3333-3333-333333333333"
    source_container = FakeSourceContainer([{"id": "slow", "_ts": 1}])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_container, job_container)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "user_settings",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "id_field": "id",
        }],
        "groups": [],
        "public_workspaces": [],
    }
    release_write = threading.Event()
    write_started = threading.Event()
    write_completed = threading.Event()

    class SlowTargetContainer(FakeTargetContainer):
        def create_item(self, document, response_hook=None, retry_write=None, **kwargs):
            write_started.set()
            assert release_write.wait(timeout=5.0)
            result = super().create_item(
                document,
                response_hook=response_hook,
                retry_write=retry_write,
                **kwargs,
            )
            write_completed.set()
            return result

    target_container = SlowTargetContainer(migration_id)
    target_container.write_barrier = threading.Barrier(1)
    heartbeats = []
    original_heartbeat = module._persist_migration_heartbeat

    def capture_heartbeat(*args, **kwargs):
        assert write_started.is_set()
        assert not write_completed.is_set()
        heartbeats.append(time.monotonic())
        release_write.set()
        return original_heartbeat(*args, **kwargs)

    monkeypatch.setattr(module, "_persist_migration_heartbeat", capture_heartbeat)
    migration_state = initialize_migration_state(None, migration_id, {"test": "slow-cosmos"})

    module._copy_cosmos_records_to_target(
        FakeTargetDatabase(target_container),
        "users",
        {"mode": "all", "ids": [], "include_documents": False},
        {"id": migration_id, "migration_state": migration_state},
        migration_state,
        create_migration_provenance_context(migration_id=migration_id),
        {
            "migration_max_parallel_operations": 1,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
    )

    assert heartbeats
    assert release_write.is_set()
    assert write_completed.is_set()