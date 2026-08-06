#!/usr/bin/env python3
# test_data_management_backup_parallelism.py
"""
Functional test for bounded parallel Data Management Cosmos backups.
Version: 0.250.076
Implemented in: 0.250.076

This test ensures a durable Cosmos backup streams deterministic bounded JSONL
batches with parallel staging, retries transient pressure safely, restores an
opt-in source RU boost, resumes only unverified work, fences stale workers,
and exposes only sanitized progress telemetry.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_backup_state import initialize_backup_state


class FakeCosmosError(Exception):
    """Expose status and retry metadata used by production retry helpers."""

    def __init__(self, status_code, headers=None, message="temporary failure"):
        super().__init__(message)
        self.status_code = status_code
        self.response = types.SimpleNamespace(
            status_code=status_code,
            headers=headers or {},
        )


class FakeJobContainer:
    """Persist jobs, locks, and manifests with basic Cosmos semantics."""

    def __init__(self, documents=None):
        self.documents = {
            document["id"]: copy.deepcopy(document)
            for document in (documents or [])
        }
        self.counter = len(self.documents)

    def create_item(self, body):
        if body["id"] in self.documents:
            raise FakeCosmosError(409, message="duplicate")
        return self.upsert_item(body)

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.documents:
            raise FakeCosmosError(404, message="missing")
        return copy.deepcopy(self.documents[item])

    def replace_item(self, item, body, etag=None, match_condition=None):
        if item not in self.documents:
            raise FakeCosmosError(404, message="missing")
        if etag and self.documents[item].get("_etag") != etag:
            raise FakeCosmosError(412, message="stale")
        return self.upsert_item(body)

    def upsert_item(self, body):
        self.counter += 1
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{self.counter}"
        self.documents[saved["id"]] = saved
        return copy.deepcopy(saved)

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(list(self.documents.values())))


class FakeItemStateContainer:
    """Keep differential state outside the source fixture records."""

    def __init__(self):
        self.documents = {}

    def read_item(self, item, partition_key):
        document = self.documents.get((partition_key, item))
        if document is None:
            raise FakeCosmosError(404, message="missing")
        return copy.deepcopy(document)

    def upsert_item(self, body):
        saved = copy.deepcopy(body)
        self.documents[(saved["source_scope"], saved["id"])] = saved
        return copy.deepcopy(saved)


class FakeSourceContainer:
    """Yield source rows lazily and retain the production query contract."""

    def __init__(self, records):
        self.records = list(records)
        self.calls = []

    def query_items(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response_hook = kwargs.get("response_hook")
        if callable(response_hook):
            response_hook({"x-ms-request-charge": "1.25"}, object())
        return iter(copy.deepcopy(self.records))


class FakeBackupContainer:
    """Track concurrent artifact staging and optionally inject a transient failure."""

    def __init__(self, delay_seconds=0.0, transient_failures=0, block_upload=False):
        self.delay_seconds = delay_seconds
        self.transient_failures = transient_failures
        self.block_upload = block_upload
        self.upload_started = threading.Event()
        self.release_upload = threading.Event()
        self.lock = threading.Lock()
        self.active_uploads = 0
        self.max_active_uploads = 0
        self.upload_calls = 0
        self.blobs = {}

    def upload_blob(self, name, data, overwrite=True, content_settings=None):
        with self.lock:
            self.upload_calls += 1
            self.active_uploads += 1
            self.max_active_uploads = max(self.max_active_uploads, self.active_uploads)
        self.upload_started.set()
        try:
            if self.block_upload:
                assert self.release_upload.wait(5.0)
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            with self.lock:
                if self.transient_failures:
                    self.transient_failures -= 1
                    raise FakeCosmosError(
                        429,
                        headers={"x-ms-retry-after-ms": "1"},
                        message="throttled token=should-not-leak",
                    )
            self.blobs[name] = data.read() if hasattr(data, "read") else data
        finally:
            with self.lock:
                self.active_uploads -= 1


def load_module(monkeypatch, job_container, item_state_container, source_container):
    """Load production backup helpers with in-memory infrastructure fakes."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.076"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.cosmos_data_management_backup_item_states_container = item_state_container
    config_module.cosmos_test_source_container = source_container
    config_module.cosmos_test_source_container_name = "test-source"
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

    module_name = "data_management_backup_parallelism_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def build_plan(parallel_operations=4, retry_count=3, boost_enabled=False, policy="continue_without_boost"):
    """Return a secret-free immutable plan for one partial backup fixture."""
    return {
        "backup_type": "partial",
        "source_scope": "simplechat-primary",
        "source_cutoff_at": "2099-01-01T00:00:00+00:00",
        "cosmos_source_cutoff_epoch": 4102444800,
        "differential_mode": "latest_item_state",
        "source_cutoff_semantics": {"deletion_policy": "none"},
        "include_cosmos": True,
        "include_ai_search": False,
        "include_source_blobs": False,
        "backup_storage_container_name": "simplechat-backups",
        "backup_storage_path_prefix": "simplechat-backups",
        "storage_identity": "test-storage-identity",
        "encryption_enabled": False,
        "encryption_key_fingerprint": "",
        "cosmos_execution": {
            "max_parallel_operations": parallel_operations,
            "retry_count": retry_count,
            "temporary_source_ru_enabled": boost_enabled,
            "temporary_source_ru": 10000,
            "capacity_failure_policy": policy,
        },
        "resource_contract": ["cosmos", "ai_search", "source_blobs"],
    }


def source_artifact():
    return {
        "name": "test_source",
        "container_attr": "cosmos_test_source_container",
        "container_name_attr": "cosmos_test_source_container_name",
        "partition_key_path": "/id",
        "category": "tests",
    }


def source_records(count):
    return [
        {
            "id": f"record-{index:05d}",
            "value": index,
            "_ts": 1000,
            "_etag": f"etag-{index}",
        }
        for index in range(count - 1, -1, -1)
    ]


def build_running_job(module, job_id, plan):
    """Create a job and matching source lock accepted by backup lease checks."""
    state = initialize_backup_state(
        None,
        job_id,
        plan,
        plan["source_scope"],
        plan["source_cutoff_at"],
    )
    source_lock_id = module._get_backup_source_lock_id(plan["source_scope"])
    job = {
        "id": job_id,
        "type": "data_management_job",
        "operation": "backup",
        "backup_type": "partial",
        "status": "running",
        "lease_holder_id": "worker-1",
        "lease_expires_at": "2099-01-01T00:00:00+00:00",
        "lease_generation": 1,
        "backup_attempt_id": "attempt-1",
        "backup_plan": copy.deepcopy(plan),
        "backup_state": state,
        "backup_source_lock": {
            "id": source_lock_id,
            "source_scope": plan["source_scope"],
            "lock_token": "lock-1",
            "lease_generation": 1,
            "lease_seconds": 900,
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
        "progress": {},
        "warnings": [],
    }
    return job, {
        "id": source_lock_id,
        "type": module.DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "backup_job_id": job_id,
        "lock_token": "lock-1",
        "lease_generation": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


def setup_job(monkeypatch, records, plan):
    source_container = FakeSourceContainer(records)
    item_state_container = FakeItemStateContainer()
    job_container = FakeJobContainer()
    module = load_module(monkeypatch, job_container, item_state_container, source_container)
    job, lock = build_running_job(module, "11111111-1111-1111-1111-111111111111", plan)
    job_container.documents[job["id"]] = copy.deepcopy(job)
    job_container.documents[lock["id"]] = copy.deepcopy(lock)
    return module, job, job_container, item_state_container, source_container


def run_resource(module, job, backup_container, source_container):
    return module._execute_parallel_backup_cosmos_resource(
        job,
        job["backup_state"],
        {"data_management_job_lease_seconds": 900},
        backup_container,
        "simplechat-backups/test",
        None,
        "cosmos:test_source",
        {
            "name": "test_source",
            "type": "cosmos_container",
            "category": "tests",
            "container_name": "test-source",
            "partition_key_path": "/id",
        },
        source_container,
        source_artifact(),
    )


def manifest_entries(job_container, module, job_id):
    return [
        entry
        for document in job_container.documents.values()
        if document.get("type") == module.DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE
        and document.get("job_id") == job_id
        for entry in document.get("entries") or []
    ]


def test_parallel_cosmos_backup_streams_10000_records_deterministically(monkeypatch):
    """Verify bounded parallel JSONL staging improves elapsed time over serial staging."""
    module, job, job_container, item_states, source_container = setup_job(
        monkeypatch,
        source_records(10_000),
        build_plan(parallel_operations=4),
    )
    backup_container = FakeBackupContainer(delay_seconds=0.05)

    started_at = time.perf_counter()
    result = run_resource(module, job, backup_container, source_container)
    elapsed_seconds = time.perf_counter() - started_at

    assert result["item_count"] == 10_000
    assert result["checkpoint_count"] == 100
    assert result["parallel_operations"] == 4
    assert backup_container.max_active_uploads <= 4
    assert backup_container.max_active_uploads > 1
    serial_module, serial_job, _serial_job_container, _serial_item_states, serial_source_container = setup_job(
        monkeypatch,
        source_records(10_000),
        build_plan(parallel_operations=1),
    )
    serial_container = FakeBackupContainer(delay_seconds=0.05)
    serial_started_at = time.perf_counter()
    run_resource(serial_module, serial_job, serial_container, serial_source_container)
    serial_elapsed_seconds = time.perf_counter() - serial_started_at

    assert elapsed_seconds < serial_elapsed_seconds * 0.9
    assert source_container.calls[0]["query"].endswith("ORDER BY c.id")
    assert source_container.calls[0]["max_item_count"] == 100
    entries = [entry for entry in manifest_entries(job_container, module, job["id"]) if entry["status"] == "succeeded"]
    assert len(entries) == 10_000
    assert len({entry["source_identity"] for entry in entries}) == 10_000
    assert len(item_states.documents) == 10_000
    assert job["backup_state"]["telemetry"]["checkpoint_position"] == 100
    assert job["backup_state"]["telemetry"]["records_processed"] == 10_000
    assert result["records_per_second"] > 0


def test_retry_after_jitter_reduces_pressure_and_keeps_commits_unique(monkeypatch):
    """Verify 429 retries are bounded, adaptive, and do not duplicate manifest outcomes."""
    module, job, job_container, item_states, source_container = setup_job(
        monkeypatch,
        source_records(300),
        build_plan(parallel_operations=4, retry_count=3),
    )
    backup_container = FakeBackupContainer(transient_failures=1)
    retry_error = FakeCosmosError(429, headers={"Retry-After": "2"})
    monkeypatch.setattr(module.random, "uniform", lambda _minimum, _maximum: 0.25)
    assert module._get_backup_retry_delay(retry_error, 1) == 2.25
    monkeypatch.setattr(module, "_get_backup_retry_delay", lambda _error, _attempt: 0.0)

    result = run_resource(module, job, backup_container, source_container)

    assert result["item_count"] == 300
    assert result["retry_attempt_count"] >= 1
    assert result["throttle_count"] >= 1
    assert result["active_parallel_operations"] < result["parallel_operations"]
    entries = [entry for entry in manifest_entries(job_container, module, job["id"]) if entry["status"] == "succeeded"]
    assert len(entries) == len({entry["source_identity"] for entry in entries}) == 300
    assert len(item_states.documents) == 300
    assert "token=" not in str(result)


def test_retry_resume_only_stages_failed_checkpoint_batch(monkeypatch):
    """Verify latest item state skips verified work after a failed batch retry."""
    module, job, _job_container, _item_states, source_container = setup_job(
        monkeypatch,
        source_records(200),
        build_plan(parallel_operations=1, retry_count=1),
    )
    first_container = FakeBackupContainer()
    original_upload = first_container.upload_blob
    upload_count = {"value": 0}

    def fail_second_upload(*args, **kwargs):
        upload_count["value"] += 1
        if upload_count["value"] == 2:
            raise FakeCosmosError(400, message="permanent failure")
        return original_upload(*args, **kwargs)

    monkeypatch.setattr(first_container, "upload_blob", fail_second_upload)
    first_result = run_resource(module, job, first_container, source_container)
    retry_container = FakeBackupContainer()
    retry_result = run_resource(module, job, retry_container, source_container)

    assert first_result["item_count"] == 100
    assert first_result["failed_count"] == 100
    assert retry_result["item_count"] == 200
    assert retry_result["failed_count"] == 0
    assert retry_container.upload_calls == 1


def test_source_capacity_restores_recovery_and_stale_worker_are_fenced(monkeypatch):
    """Verify source capacity restoration is attempt-fenced and stale commits stop."""
    module, job, job_container, _item_states, source_container = setup_job(
        monkeypatch,
        source_records(100),
        build_plan(parallel_operations=1, boost_enabled=True),
    )
    module.DATA_MANAGEMENT_COSMOS_ARTIFACTS = [source_artifact()]
    monkeypatch.setattr(module, "_get_source_cosmos_management_settings", lambda: {"source": "local"})
    monkeypatch.setattr(module, "get_database_throughput", lambda _settings: {"is_scalable": False})
    monkeypatch.setattr(module, "get_container_throughput", lambda _settings, _name: {
        "is_scalable": True,
        "mode": "autoscale",
        "current_ru": 4000,
    })
    capacity_calls = []
    monkeypatch.setattr(
        module,
        "set_database_throughput",
        lambda _settings, target_ru, **kwargs: capacity_calls.append((target_ru, kwargs["reason"])) or {"to_ru": target_ru},
    )
    module._apply_temporary_backup_source_capacity(job, job["backup_state"], {"data_management_job_lease_seconds": 900}, job["backup_plan"])
    assert job["backup_state"]["source_capacity"]["topology"]["scope"] == "dedicated_containers"
    assert job["backup_state"]["source_capacity"]["target_ru"] == 10000
    monkeypatch.setattr(module, "get_container_throughput", lambda _settings, _name: {
        "is_scalable": True,
        "mode": "autoscale",
        "current_ru": 10000,
    })
    module._restore_temporary_backup_source_capacity(job, job["backup_state"], {"data_management_job_lease_seconds": 900})
    assert capacity_calls == [
        (10000, "temporary_backup_source_capacity_boost"),
        (4000, "restore_temporary_backup_source_capacity"),
    ]
    assert job["backup_state"]["source_capacity"]["restore_pending"] is False

    job["backup_state"]["source_capacity"].update({
        "status": "restore_pending",
        "restore_pending": True,
        "attempt_id": "stale-attempt",
        "lease_generation": 1,
        "targets": [{
            "scope": "container", "container_name": "test-source", "mode": "autoscale",
            "original_ru": 4000, "target_ru": 10000, "boosted_to_ru": 10000,
            "changed": True, "boost_attempted": True, "restore_status": "restore_failed",
        }],
    })
    job["backup_attempt_id"] = "recovery-attempt"
    job["lease_generation"] = 2
    job["backup_source_lock"]["lease_generation"] = 2
    job_container.documents[job["id"]] = copy.deepcopy(job)
    job_container.documents[job["backup_source_lock"]["id"]]["lease_generation"] = 2
    module._apply_temporary_backup_source_capacity(job, job["backup_state"], {"data_management_job_lease_seconds": 900}, job["backup_plan"])
    assert job["backup_state"]["source_capacity"]["restore_pending"] is False
    assert job["backup_state"]["source_capacity"]["recovery_attempt_id"] == "recovery-attempt"

    job["backup_plan"]["cosmos_execution"]["temporary_source_ru_enabled"] = False
    job_container.documents[job["id"]] = copy.deepcopy(job)
    blocking_container = FakeBackupContainer(block_upload=True)
    failure_holder = {}

    def stale_worker():
        try:
            run_resource(module, job, blocking_container, source_container)
        except Exception as exc:
            failure_holder["error"] = exc

    worker = threading.Thread(target=stale_worker)
    worker.start()
    assert blocking_container.upload_started.wait(5.0)
    job_container.documents[job["id"]]["lease_holder_id"] = "new-worker"
    blocking_container.release_upload.set()
    worker.join(5.0)
    assert isinstance(failure_holder.get("error"), module.DataManagementBackupLeaseLostError)


def test_capacity_policy_and_admin_progress_remain_sanitized(monkeypatch):
    """Verify boost permission policy and progress never reveal internal capacity routing."""
    module, job, _job_container, _item_states, _source_container = setup_job(
        monkeypatch,
        [],
        build_plan(boost_enabled=True),
    )
    monkeypatch.setattr(
        module,
        "_inspect_backup_source_capacity",
        lambda _plan: (_ for _ in ()).throw(module.CosmosThroughputError("denied")),
    )
    module._apply_temporary_backup_source_capacity(job, job["backup_state"], {"data_management_job_lease_seconds": 900}, job["backup_plan"])
    assert job["backup_state"]["source_capacity"]["status"] == "unavailable_continued"

    job["backup_plan"]["cosmos_execution"]["capacity_failure_policy"] = "fail"
    try:
        module._apply_temporary_backup_source_capacity(job, job["backup_state"], {"data_management_job_lease_seconds": 900}, job["backup_plan"])
    except module.CosmosThroughputError:
        pass
    else:
        raise AssertionError("The fail policy accepted an unavailable capacity boost.")

    state = job["backup_state"]
    state.update({
        "totals": {"processed_count": 100, "request_units": 42.5, "retry_attempt_count": 2},
        "telemetry": {"current_container": "test-source", "records_per_second": 33.3},
        "source_capacity": {
            "status": "restore_pending", "restore_pending": True,
            "management_settings": {"subscription": "secret-subscription"},
            "restore_warnings": ["https://example.invalid/?sig=secret-value"],
            "targets": [{"scope": "database", "target_ru": 10000}],
        },
    })
    public_state = module._sanitize_data_management_backup_state_for_admin(state)
    serialized = str(public_state)
    assert public_state["telemetry"]["current_container"] == "test-source"
    assert public_state["source_capacity"]["targets"][0]["target_ru"] == 10000
    assert "secret-subscription" not in serialized
    assert "secret-value" not in serialized


def test_legacy_plan_uses_fixed_execution_defaults_on_resume(monkeypatch):
    """Older durable plans must not inherit later admin performance setting changes."""
    module, _job, _job_container, _item_states, _source_container = setup_job(
        monkeypatch,
        [],
        build_plan(),
    )
    legacy_plan = {"backup_type": "partial"}
    changed_settings = {
        "backup_max_parallel_operations": 16,
        "backup_retry_count": 10,
        "backup_temporary_source_ru": 5000,
        "backup_capacity_failure_policy": "fail",
    }

    assert module._get_backup_parallel_operations(changed_settings, legacy_plan) == 4
    assert module._get_backup_retry_count(changed_settings, legacy_plan) == 5
    assert module._get_backup_temporary_source_ru(changed_settings, legacy_plan) == 10000
    assert module._get_backup_capacity_failure_policy(changed_settings, legacy_plan) == "continue_without_boost"