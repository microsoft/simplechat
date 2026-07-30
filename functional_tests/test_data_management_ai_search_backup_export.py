#!/usr/bin/env python3
# test_data_management_ai_search_backup_export.py
"""
Functional test for bounded AI Search backup export.
Version: 0.250.101
Implemented in: 0.250.101

This test ensures Search backups use exhaustive id-keyset pages, durable page
checkpoints, adaptive throttling, isolated index failures, and sanitized state.
"""

import copy
import importlib.util
import inspect
import re
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


class FakeAzureError(Exception):
    """Expose Azure-compatible status and retry metadata."""

    def __init__(self, status_code, message="temporary token=not-safe"):
        super().__init__(message)
        self.status_code = status_code
        self.response = types.SimpleNamespace(
            status_code=status_code,
            headers={"Retry-After": "0"},
        )


class FakeJobContainer:
    """Persist backup jobs, locks, and manifest batches in memory."""

    def __init__(self):
        self.documents = {}
        self.counter = 0

    def read_item(self, item, partition_key):
        if item not in self.documents:
            raise FakeAzureError(404, "missing")
        return copy.deepcopy(self.documents[item])

    def create_item(self, body):
        if body["id"] in self.documents:
            raise FakeAzureError(409, "duplicate")
        return self.upsert_item(body)

    def replace_item(self, item, body, **_kwargs):
        if item not in self.documents:
            raise FakeAzureError(404, "missing")
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
    """Store latest-only state outside source Search documents."""

    def __init__(self):
        self.documents = {}

    def read_item(self, item, partition_key):
        document = self.documents.get((partition_key, item))
        if document is None:
            raise FakeAzureError(404, "missing")
        return copy.deepcopy(document)

    def upsert_item(self, body):
        self.documents[(body["source_scope"], body["id"])] = copy.deepcopy(body)
        return copy.deepcopy(body)


class FakeBackupContainer:
    """Capture bounded page blobs and optionally fail one upload page."""

    def __init__(self, fail_page=None, fail_index="simplechat-user-index"):
        self.blobs = {}
        self.fail_page = fail_page
        self.fail_index = fail_index
        self.failures = 0
        self.lock = threading.Lock()

    def upload_blob(self, name, data, **_kwargs):
        with self.lock:
            if (
                self.fail_page and self.fail_index in name and
                f"/{self.fail_page:06d}.jsonl" in name
            ):
                self.failures += 1
                raise FakeAzureError(503)
            self.blobs[name] = data.read() if hasattr(data, "read") else data


class FakeSearchClient:
    """Return bounded, filter-aware Search pages without supporting skip."""

    global_lock = threading.Lock()
    global_active_calls = 0
    global_max_active_calls = 0

    def __init__(self, documents, delay_seconds=0.0, fail_status=None):
        self.documents = list(documents)
        self.delay_seconds = delay_seconds
        self.fail_status = fail_status
        self.failed = False
        self.calls = []
        self.lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def search(self, **kwargs):
        assert "skip" not in kwargs
        self.calls.append(copy.deepcopy(kwargs))
        with self.lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        with self.global_lock:
            type(self).global_active_calls += 1
            type(self).global_max_active_calls = max(
                type(self).global_max_active_calls,
                type(self).global_active_calls,
            )
        try:
            if self.fail_status and not self.failed:
                self.failed = True
                raise FakeAzureError(self.fail_status)
            if self.delay_seconds:
                time.sleep(self.delay_seconds)
            order = kwargs.get("order_by") or []
            rows = sorted(self.documents, key=lambda document: document["id"], reverse=order == ["id desc"])
            filter_text = kwargs.get("filter") or ""
            gt_match = re.search(r"id gt '((?:''|[^'])*)'", filter_text)
            le_match = re.search(r"id le '((?:''|[^'])*)'", filter_text)
            if gt_match:
                rows = [row for row in rows if row["id"] > gt_match.group(1).replace("''", "'")]
            if le_match:
                rows = [row for row in rows if row["id"] <= le_match.group(1).replace("''", "'")]
            return iter(copy.deepcopy(rows[:kwargs.get("top", len(rows))]))
        finally:
            with self.lock:
                self.active_calls -= 1
            with self.global_lock:
                type(self).global_active_calls -= 1


def load_module(monkeypatch, job_container, item_states, clients):
    """Load production export helpers against local Azure fakes."""
    search_module = types.ModuleType("azure.search")
    search_documents_module = types.ModuleType("azure.search.documents")
    search_indexes_module = types.ModuleType("azure.search.documents.indexes")
    search_models_module = types.ModuleType("azure.search.documents.indexes.models")
    search_documents_module.SearchClient = object
    search_indexes_module.SearchIndexClient = object
    search_models_module.SearchField = object
    search_models_module.SearchFieldDataType = object
    search_models_module.SearchIndex = object
    monkeypatch.setitem(sys.modules, "azure.search", search_module)
    monkeypatch.setitem(sys.modules, "azure.search.documents", search_documents_module)
    monkeypatch.setitem(sys.modules, "azure.search.documents.indexes", search_indexes_module)
    monkeypatch.setitem(sys.modules, "azure.search.documents.indexes.models", search_models_module)
    config_module = types.ModuleType("config")
    config_module.CLIENTS = clients
    config_module.VERSION = "0.250.101"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.cosmos_data_management_backup_item_states_container = item_states
    monkeypatch.setitem(sys.modules, "config", config_module)
    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)
    throughput_module = types.ModuleType("functions_cosmos_throughput")
    throughput_module.CosmosThroughputError = RuntimeError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)
    spec = importlib.util.spec_from_file_location("search_backup_test_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, spec.name, raising=False)
    monkeypatch.setattr(module, "_get_backup_retry_delay", lambda *_args: 0.0)
    return module


def build_plan(parallelism=3, retry_count=2):
    """Build the immutable Search execution contract used by the fakes."""
    return {
        "backup_type": "partial",
        "source_scope": "simplechat-primary",
        "source_cutoff_at": "2099-01-01T00:00:00+00:00",
        "source_lower_bound_at": "2026-01-01T00:00:00+00:00",
        "differential_mode": "latest_item_state",
        "include_ai_search": True,
        "storage_identity": "test-storage",
        "backup_storage_container_name": "backups",
        "backup_storage_path_prefix": "backups",
        "encryption_enabled": False,
        "encryption_key_fingerprint": "",
        "cosmos_execution": {"max_parallel_operations": parallelism, "retry_count": retry_count},
        "ai_search_execution": {
            "max_parallel_operations": parallelism,
            "retry_count": retry_count,
            "page_size": 2,
            "clean_page_recovery_count": 1,
        },
        "resource_contract": ["cosmos", "ai_search", "source_blobs"],
    }


def build_job(module, job_container, plan, job_id="search-backup-job"):
    """Create a fenced running job accepted by durable backup helpers."""
    state = initialize_backup_state(None, job_id, plan, plan["source_scope"], plan["source_cutoff_at"])
    lock_id = module._get_backup_source_lock_id(plan["source_scope"])
    job = {
        "id": job_id,
        "operation": "backup",
        "backup_type": "partial",
        "status": "running",
        "lease_holder_id": "worker",
        "lease_generation": 1,
        "backup_attempt_id": "attempt",
        "lease_expires_at": "2099-01-01T00:00:00+00:00",
        "backup_plan": copy.deepcopy(plan),
        "backup_state": state,
        "backup_source_lock": {
            "id": lock_id,
            "lock_token": "lock",
            "lease_generation": 1,
            "lease_seconds": 900,
        },
        "progress": {},
        "warnings": [],
    }
    job_container.documents[job_id] = copy.deepcopy(job)
    job_container.documents[lock_id] = {
        "id": lock_id,
        "type": module.DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "backup_job_id": job_id,
        "lock_token": "lock",
        "lease_generation": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "_etag": "lock",
    }
    return job


def documents(count, prefix):
    return [
        {
            "id": f"{prefix}-{number:06d}",
            "upload_date": "2026-07-30T12:00:00+00:00",
            "content": f"document {number}",
        }
        for number in range(count)
    ]


def test_keyset_pages_exhaust_more_than_100000_documents_without_skip(monkeypatch):
    """Verify exhaustive logical traversal advances a key cursor rather than skip."""
    module = load_module(monkeypatch, FakeJobContainer(), FakeItemStateContainer(), {})
    client = FakeSearchClient(documents(100_001, "large"))
    plan = build_plan()
    last_id = ""
    received = 0
    while True:
        page = module._read_backup_search_page(client, plan, last_id, "large-100000", 1000, 1)
        rows = page["documents"]
        if not rows:
            break
        received += len(rows)
        last_id = rows[-1]["id"]
    assert received == 100_001
    assert all("skip" not in call for call in client.calls)
    assert all(call["order_by"] == ["id asc"] for call in client.calls)
    assert "id gt 'large-000999'" in client.calls[1]["filter"]


def test_search_page_worker_does_not_accept_live_job_object(monkeypatch):
    """Verify concurrent page staging receives only immutable job identity snapshots."""
    job_container = FakeJobContainer()
    item_states = FakeItemStateContainer()
    clients = {
        "search_client_user": FakeSearchClient(documents(1, "personal")),
        "search_client_group": FakeSearchClient(documents(1, "group")),
        "search_client_public": FakeSearchClient(documents(1, "public")),
    }
    module = load_module(monkeypatch, job_container, item_states, clients)
    plan = build_plan()
    job = build_job(module, job_container, plan, "worker-snapshot")
    original_stage = module._stage_backup_search_page
    worker_arguments = []

    def record_worker_arguments(*args, **kwargs):
        worker_arguments.append(args)
        assert all(argument is not job for argument in args)
        return original_stage(*args, **kwargs)

    monkeypatch.setattr(module, "_stage_backup_search_page", record_worker_arguments)
    module._execute_backup_search_resources(
        job,
        job["backup_state"],
        {"data_management_job_lease_seconds": 900},
        FakeBackupContainer(),
        "backups/worker-snapshot",
        None,
    )

    assert "job" not in inspect.signature(original_stage).parameters
    assert worker_arguments
    assert all(argument is not job for arguments in worker_arguments for argument in arguments)


def test_search_page_scheduler_round_robins_when_one_slot_is_available(monkeypatch):
    """Verify a constrained scheduler gives every active index a page before draining one."""
    job_container = FakeJobContainer()
    item_states = FakeItemStateContainer()
    clients = {
        "search_client_user": FakeSearchClient(documents(6, "personal")),
        "search_client_group": FakeSearchClient(documents(6, "group")),
        "search_client_public": FakeSearchClient(documents(6, "public")),
    }
    module = load_module(monkeypatch, job_container, item_states, clients)
    plan = build_plan(parallelism=1)
    job = build_job(module, job_container, plan, "round-robin")
    original_stage = module._stage_backup_search_page
    scheduled_pages = []

    def record_scheduled_page(*args, **kwargs):
        scheduled_pages.append((args[6]["index_name"], args[10]))
        return original_stage(*args, **kwargs)

    monkeypatch.setattr(module, "_stage_backup_search_page", record_scheduled_page)
    module._execute_backup_search_resources(
        job,
        job["backup_state"],
        {"data_management_job_lease_seconds": 900},
        FakeBackupContainer(),
        "backups/round-robin",
        None,
    )

    assert [index_name for index_name, _page in scheduled_pages[:3]] == [
        "simplechat-user-index",
        "simplechat-group-index",
        "simplechat-public-index",
    ]
    assert all(page_number == 1 for _index_name, page_number in scheduled_pages[:3])


def test_search_export_concurrency_throttle_resume_and_isolated_failure(monkeypatch):
    """Verify page workers adapt to throttling, resume a checkpoint, and isolate one index."""
    job_container = FakeJobContainer()
    item_states = FakeItemStateContainer()
    clients = {
        "search_client_user": FakeSearchClient(documents(5, "personal"), delay_seconds=0.02, fail_status=429),
        "search_client_group": FakeSearchClient(documents(5, "group"), delay_seconds=0.02),
        "search_client_public": FakeSearchClient(documents(5, "public"), delay_seconds=0.02),
    }
    module = load_module(monkeypatch, job_container, item_states, clients)
    FakeSearchClient.global_active_calls = 0
    FakeSearchClient.global_max_active_calls = 0
    plan = build_plan()
    job = build_job(module, job_container, plan)
    backup_container = FakeBackupContainer(fail_page=2)

    first = module._execute_backup_search_resources(
        job, job["backup_state"], {"data_management_job_lease_seconds": 900},
        backup_container, "backups/test", None,
    )
    personal = next(
        item for item in first
        if item.get("type") == "ai_search_documents" and item.get("index_name") == "simplechat-user-index"
    )
    assert personal["available"] is False
    assert any(
        item.get("available") is True
        for item in first
        if item.get("type") == "ai_search_documents" and item.get("index_name") != "simplechat-user-index"
    )
    assert clients["search_client_user"].max_active_calls == 1
    assert FakeSearchClient.global_max_active_calls > 1
    personal_resource = job["backup_state"]["resources"]["ai_search:simplechat-user-index"]
    assert personal_resource["checkpoint"]["last_committed_id"] == "personal-000001"
    assert personal_resource["progress"]["throttle_count"] >= 1
    assert "token=" not in str(module._sanitize_data_management_backup_state_for_admin(job["backup_state"]))

    backup_container.fail_page = None
    resumed = module._execute_backup_search_resources(
        job, job["backup_state"], {"data_management_job_lease_seconds": 900},
        backup_container, "backups/test", None,
    )
    resumed_personal = next(
        item for item in resumed
        if item.get("type") == "ai_search_documents" and item.get("index_name") == "simplechat-user-index"
    )
    assert resumed_personal["available"] is True
    assert resumed_personal["item_count"] == 5
    manifest_entries = [
        entry
        for document in job_container.documents.values()
        if document.get("type") == module.DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE
        for entry in document.get("entries", [])
        if entry.get("resource_name") == "ai_search:simplechat-user-index"
    ]
    assert len({entry["source_identity"] for entry in manifest_entries if entry["status"] == "succeeded"}) == 5

    public_clients = {
        "search_client_user": FakeSearchClient(documents(1, "personal")),
        "search_client_group": FakeSearchClient(documents(1, "group"), fail_status=400),
        "search_client_public": FakeSearchClient(documents(1, "public")),
    }
    failed_module = load_module(monkeypatch, FakeJobContainer(), FakeItemStateContainer(), public_clients)
    failed_job = build_job(failed_module, failed_module.cosmos_data_management_jobs_container, plan, "isolated")
    failed = failed_module._execute_backup_search_resources(
        failed_job, failed_job["backup_state"], {"data_management_job_lease_seconds": 900},
        FakeBackupContainer(), "backups/isolated", None,
    )
    group = next(
        item for item in failed
        if item.get("type") == "ai_search_documents" and item.get("index_name") == "simplechat-group-index"
    )
    assert group["available"] is False
    assert any(
        item.get("available") is True
        for item in failed
        if item.get("type") == "ai_search_documents" and item.get("index_name") == "simplechat-public-index"
    )


def test_schema_validation_latest_state_and_sanitized_metrics(monkeypatch):
    """Verify schema incompatibility fails safely and prior successful state is skipped."""
    job_container = FakeJobContainer()
    item_states = FakeItemStateContainer()
    clients = {
        "search_client_user": FakeSearchClient(documents(1, "personal")),
        "search_client_group": FakeSearchClient(documents(1, "group")),
        "search_client_public": FakeSearchClient(documents(1, "public")),
    }
    module = load_module(monkeypatch, job_container, item_states, clients)
    plan = build_plan()
    job = build_job(module, job_container, plan, "first")
    module._execute_backup_search_resources(
        job, job["backup_state"], {"data_management_job_lease_seconds": 900},
        FakeBackupContainer(), "backups/first", None,
    )
    second_job = build_job(module, job_container, plan, "second")
    second = module._execute_backup_search_resources(
        second_job, second_job["backup_state"], {"data_management_job_lease_seconds": 900},
        FakeBackupContainer(), "backups/second", None,
    )
    assert all(
        item.get("skipped_count") == 1
        for item in second if item.get("type") == "ai_search_documents"
    )
    public_state = module._sanitize_data_management_backup_state_for_admin(second_job["backup_state"])
    assert "last_committed_id" not in str(public_state)
    assert public_state["resources"]["ai_search:simplechat-user-index"]["checkpoint"]["upper_id_captured"] is True

    artifact = module.DATA_MANAGEMENT_SEARCH_ARTIFACTS[0]
    monkeypatch.setattr(module, "_get_search_schema", lambda _name: {"fields": []})
    try:
        module._validate_backup_search_schema(artifact)
    except module.DataManagementSettingsValidationError:
        pass
    else:
        raise AssertionError("An incompatible Search schema was accepted.")
