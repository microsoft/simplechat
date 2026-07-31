# test_data_management_ai_search_migration_resilience.py
"""
Functional test for resilient Data Management AI Search migration.
Version: 0.250.071
Implemented in: 0.250.075
Updated in: 0.250.071

This test ensures the in-app migration skips matching destination provenance,
uploads bounded batches concurrently, and tags every copied Search document.
"""

import copy
import importlib.util
from pathlib import Path
import re
import sys
import threading
import time
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_migration_state import initialize_migration_state
from functions_migration_provenance import create_migration_provenance_context


class FakeJobContainer:
    """Persist deep copies like the production job container."""

    def __init__(self):
        self.manifest_batches = []

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def create_item(self, body):
        self.manifest_batches.append(copy.deepcopy(body))
        return copy.deepcopy(body)


class FakeSearchClient:
    """Simulate Search reads, target provenance lookup, and parallel uploads."""

    def __init__(self, documents=None, migration_id="", migrated_source_hash=""):
        self.documents = documents or []
        self.migration_id = migration_id
        self.migrated_source_hash = migrated_source_hash
        self.source_queries = []
        self.uploaded = []
        self.active_uploads = 0
        self.maximum_active_uploads = 0
        self.lock = threading.Lock()

    def search(self, **kwargs):
        selected_fields = kwargs.get("select") or []
        if "simplechatMigrationId" in selected_fields:
            if "already-migrated" not in str(kwargs.get("filter") or ""):
                return iter([])
            return iter([{
                "id": "already-migrated",
                "simplechatMigrationId": self.migration_id,
                "simplechatMigratedAtUtc": "2026-07-24T12:00:00+00:00",
                "simplechatMigrationStatus": "succeeded",
                "simplechatMigrationSourceHash": self.migrated_source_hash,
            }])
        self.source_queries.append(copy.deepcopy(kwargs))
        assert "skip" not in kwargs
        assert kwargs.get("order_by") == ["id asc"]
        documents = sorted(copy.deepcopy(self.documents), key=lambda item: item["id"])
        cursor_match = re.search(
            r"id gt '([^']+)'",
            str(kwargs.get("filter") or ""),
        )
        if cursor_match:
            documents = [item for item in documents if item["id"] > cursor_match.group(1)]
        return iter(documents[:int(kwargs.get("top") or len(documents))])

    def upload_documents(self, documents, **_kwargs):
        with self.lock:
            self.active_uploads += 1
            self.maximum_active_uploads = max(self.maximum_active_uploads, self.active_uploads)
        try:
            time.sleep(0.03)
            self.uploaded.extend(copy.deepcopy(documents))
            return [{"succeeded": True} for _ in documents]
        finally:
            with self.lock:
                self.active_uploads -= 1


class GeneratedSearchClient:
    """Generate deterministic keyset pages without materializing a large index."""

    def __init__(self, document_count):
        self.document_count = document_count
        self.source_queries = []

    def search(self, **kwargs):
        assert "skip" not in kwargs
        assert kwargs.get("order_by") == ["id asc"]
        page_size = int(kwargs.get("top") or 0)
        assert 0 < page_size <= 1000
        self.source_queries.append(copy.deepcopy(kwargs))
        cursor_match = re.search(
            r"id gt 'document-(\d+)'",
            str(kwargs.get("filter") or ""),
        )
        start_index = int(cursor_match.group(1)) + 1 if cursor_match else 0
        end_index = min(self.document_count, start_index + page_size)
        return iter(
            {"id": f"document-{index:06d}", "user_id": "user-1"}
            for index in range(start_index, end_index)
        )


class CountingTargetSearchClient:
    """Count uploaded Search documents while returning per-document outcomes."""

    def __init__(self):
        self.uploaded_count = 0
        self.lock = threading.Lock()

    def search(self, **_kwargs):
        return iter([])

    def upload_documents(self, documents, **_kwargs):
        with self.lock:
            self.uploaded_count += len(documents)
        return [{"succeeded": True} for _ in documents]


class DeltaTargetSearchClient:
    """Expose owned target hashes and capture create/update Search uploads."""

    def __init__(self, documents):
        self.documents = copy.deepcopy(documents)
        self.uploaded = []

    def search(self, **kwargs):
        filter_text = str(kwargs.get("filter") or "")
        requested_ids = re.findall(r"id eq '([^']+)'", filter_text)
        return iter(
            copy.deepcopy(self.documents[document_id])
            for document_id in requested_ids
            if document_id in self.documents
        )

    def upload_documents(self, documents, **_kwargs):
        self.uploaded.extend(copy.deepcopy(documents))
        for document in documents:
            self.documents[document["id"]] = copy.deepcopy(document)
        return [{"succeeded": True} for _ in documents]


class FailOnceTargetSearchClient(CountingTargetSearchClient):
    """Fail one document result once, then accept the same key on retry."""

    def __init__(self, failed_document_id):
        super().__init__()
        self.failed_document_id = failed_document_id
        self.failure_returned = False
        self.attempted_ids = []
        self.documents = {}

    def search(self, **kwargs):
        requested_ids = re.findall(
            r"id eq '([^']+)'",
            str(kwargs.get("filter") or ""),
        )
        return iter(
            copy.deepcopy(self.documents[document_id])
            for document_id in requested_ids
            if document_id in self.documents
        )

    def upload_documents(self, documents, **_kwargs):
        self.attempted_ids.extend(document["id"] for document in documents)
        results = []
        for document in documents:
            should_fail = (
                document["id"] == self.failed_document_id and
                not self.failure_returned
            )
            if should_fail:
                self.failure_returned = True
                results.append({"succeeded": False})
                continue
            with self.lock:
                self.uploaded_count += 1
            self.documents[document["id"]] = copy.deepcopy(document)
            results.append({"succeeded": True})
        return results


class AmbiguousTargetSearchClient:
    """Simulate a response-lost Search write whose target state changes before retry."""

    def __init__(self, response_lost_document):
        self.documents = {}
        self.response_lost_document = response_lost_document
        self.upload_attempts = 0

    def search(self, **kwargs):
        requested_ids = re.findall(
            r"id eq '([^']+)'",
            str(kwargs.get("filter") or ""),
        )
        return iter(
            copy.deepcopy(self.documents[document_id])
            for document_id in requested_ids
            if document_id in self.documents
        )

    def upload_documents(self, documents, **_kwargs):
        self.upload_attempts += 1
        if self.upload_attempts > 1:
            raise AssertionError("An ambiguous AI Search write must be reclassified before retry.")
        document = documents[0]
        self.documents[document["id"]] = copy.deepcopy(self.response_lost_document(document))
        raise TimeoutError("Search response was lost after the request reached the service.")


def load_data_management_module(monkeypatch, source_client, job_container):
    """Load the production module without loading the full Flask application config."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {"search_client_user": source_client}
    config_module.VERSION = "0.250.075"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
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

    module_name = "data_management_ai_search_resilience_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_data_management_ai_search_migration_parallel_provenance(monkeypatch):
    """Validate target marker skips and concurrent tagged uploads through the app path."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    source_client = FakeSearchClient([
        {"id": "already-migrated", "user_id": "user-1", "chunk_text": "skip"},
        {"id": "copy-one", "user_id": "user-1", "chunk_text": "one"},
        {"id": "copy-two", "user_id": "user-1", "chunk_text": "two"},
        {"id": "copy-three", "user_id": "user-1", "chunk_text": "three"},
        {"id": "copy-four", "user_id": "user-1", "chunk_text": "four"},
    ])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_client, job_container)
    module.DATA_MANAGEMENT_MIGRATION_BATCH_SIZE = 2
    target_client = FakeSearchClient(
        migration_id=migration_id,
        migrated_source_hash=module._build_search_source_hash(source_client.documents[0]),
    )
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "updated_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)

    settings = {
        "migration_max_parallel_operations": 2,
        "migration_retry_count": 2,
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "search"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-24T12:00:00+00:00",
    )
    job = {"id": migration_id, "migration_state": migration_state}

    artifacts = module._copy_ai_search_to_target(
        settings,
        migration_plan,
        job,
        migration_state,
        provenance_context,
    )

    assert len(target_client.uploaded) == 4
    assert target_client.maximum_active_uploads >= 2
    assert all(
        document["simplechatMigrationId"] == migration_id
        and document["simplechatMigrationStatus"] == "succeeded"
        and document["simplechatMigratedAtUtc"]
        for document in target_client.uploaded
    )
    assert artifacts[0]["copied_count"] == 4
    assert artifacts[0]["skipped_count"] == 0
    assert artifacts[0]["destination_provenance_skip_count"] == 1
    assert artifacts[0]["batch_size"] == 2
    assert artifacts[0]["source_read_count"] == 5
    assert artifacts[0]["keyset_cursor"]["completed"] is True
    assert artifacts[0]["checkpoint_count"] >= 2
    assert len(source_client.source_queries) >= 2
    assert any("id gt" in str(query.get("filter") or "") for query in source_client.source_queries)
    resource = job["migration_state"]["resources"]["ai_search:users:simplechat-user-index"]
    assert resource["status"] == "completed"

    try:
        module._classify_target_search_document(
            {"id": "unowned"},
            provenance_context,
            "simplechat-user-index",
        )
    except module.DataManagementSettingsValidationError as exc:
        assert "unowned" in str(exc)
    else:
        raise AssertionError("An unowned destination AI Search document was accepted for overwrite.")


def test_target_search_schema_client_uses_migration_request_bounds(monkeypatch):
    """Keep schema reads and writes inside the same bounded migration request budget."""
    source_client = FakeSearchClient()
    module = load_data_management_module(monkeypatch, source_client, FakeJobContainer())
    captured_kwargs = {}

    class FakeIndexClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        def get_index(self, _index_name):
            return types.SimpleNamespace(name="simplechat-user-index", fields=[])

        def create_or_update_index(self, index):
            return index

    monkeypatch.setattr(module, "SearchIndexClient", FakeIndexClient)

    assert module._ensure_target_search_index(
        {"target_ai_search_endpoint": "https://target.search.windows.net"},
        "simplechat-user-index",
        "unused.json",
    ) == "updated_with_migration_provenance"
    assert captured_kwargs["connection_timeout"] == (
        module.DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS
    )
    assert captured_kwargs["read_timeout"] == (
        module.DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS
    )
    assert captured_kwargs["retry_total"] == 0


def test_data_management_ai_search_keyset_migrates_beyond_skip_limit(monkeypatch):
    """Migrate more than 100,000 source keys without SDK continuation or deep skip."""
    document_count = 100_001
    migration_id = "22222222-2222-2222-2222-222222222222"
    source_client = GeneratedSearchClient(document_count)
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_client, job_container)
    target_client = CountingTargetSearchClient()
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "exists_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)

    settings = {
        "migration_max_parallel_operations": 8,
        "migration_retry_count": 1,
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "search-scale"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    job = {"id": migration_id, "migration_state": migration_state}

    artifacts = module._copy_ai_search_to_target(
        settings,
        migration_plan,
        job,
        migration_state,
        provenance_context,
    )

    assert target_client.uploaded_count == document_count
    assert artifacts[0]["copied_count"] == document_count
    assert artifacts[0]["source_read_count"] == document_count
    assert artifacts[0]["keyset_cursor"]["completed"] is True
    assert len(source_client.source_queries) > 100
    assert all("skip" not in query for query in source_client.source_queries)


def test_data_management_ai_search_resumes_from_persisted_keyset_cursor(monkeypatch):
    """Resume after a durable Search page without rescanning completed source keys."""
    migration_id = "33333333-3333-3333-3333-333333333333"
    source_client = FakeSearchClient([
        {"id": f"document-{index:03d}", "user_id": "user-1"}
        for index in range(10)
    ])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_client, job_container)
    module.DATA_MANAGEMENT_MIGRATION_BATCH_SIZE = 2
    target_client = CountingTargetSearchClient()
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "exists_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)

    settings = {
        "migration_max_parallel_operations": 2,
        "migration_retry_count": 1,
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "search-resume"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    job = {"id": migration_id, "migration_state": migration_state}
    persist_checkpoint = module._persist_migration_checkpoint
    interrupted = False

    def interrupt_after_first_checkpoint(*args, **kwargs):
        nonlocal interrupted
        state = persist_checkpoint(*args, **kwargs)
        if not interrupted:
            interrupted = True
            raise RuntimeError("simulated worker interruption")
        return state

    monkeypatch.setattr(module, "_persist_migration_checkpoint", interrupt_after_first_checkpoint)
    with pytest.raises(RuntimeError, match="simulated worker interruption"):
        module._copy_ai_search_to_target(
            settings,
            migration_plan,
            job,
            migration_state,
            provenance_context,
        )

    persisted_progress = job["migration_state"]["resources"][
        "ai_search:users:simplechat-user-index"
    ]["progress"]
    assert persisted_progress["keyset_cursor"]["last_id"] == "document-003"
    first_attempt_query_count = len(source_client.source_queries)
    monkeypatch.setattr(module, "_persist_migration_checkpoint", persist_checkpoint)

    artifacts = module._copy_ai_search_to_target(
        settings,
        migration_plan,
        job,
        job["migration_state"],
        provenance_context,
    )

    resumed_queries = source_client.source_queries[first_attempt_query_count:]
    assert resumed_queries
    assert "id gt 'document-003'" in str(resumed_queries[0].get("filter") or "")
    assert target_client.uploaded_count == 10
    assert artifacts[0]["copied_count"] == 10


def test_data_management_ai_search_batches_large_selected_scope_filters(monkeypatch):
    """Keep a 2,000-user selection below Search filter complexity limits."""
    source_client = FakeSearchClient()
    module = load_data_management_module(monkeypatch, source_client, FakeJobContainer())
    selected_ids = [f"user-{index:04d}" for index in range(2000)]

    search_filters = module._build_search_scope_filter_batches(
        "user_id",
        {"mode": "selected", "ids": selected_ids},
    )

    assert len(search_filters) == 20
    assert all(search_filter.count("user_id eq") <= 100 for search_filter in search_filters)
    assert sum(search_filter.count("user_id eq") for search_filter in search_filters) == 2000


def test_data_management_ai_search_delta_writes_only_changed_owned_documents(monkeypatch):
    """Use source hashes to create new and update changed migration-owned Search keys."""
    migration_id = "66666666-6666-6666-6666-666666666666"
    baseline_migration_id = "55555555-5555-5555-5555-555555555555"
    source_documents = [
        {"id": "unchanged", "user_id": "user-1", "chunk_text": "same"},
        {"id": "changed", "user_id": "user-1", "chunk_text": "new"},
        {"id": "created", "user_id": "user-1", "chunk_text": "new"},
    ]
    source_client = FakeSearchClient(source_documents)
    module = load_data_management_module(monkeypatch, source_client, FakeJobContainer())
    baseline_context = create_migration_provenance_context(
        migration_id=baseline_migration_id,
        migrated_at_utc="2026-07-28T12:00:00+00:00",
    )
    target_client = DeltaTargetSearchClient({
        "unchanged": module.add_search_migration_provenance(
            {"id": "unchanged"},
            baseline_context,
            source_hash=module._build_search_source_hash(source_documents[0]),
        ),
        "changed": module.add_search_migration_provenance(
            {"id": "changed"},
            baseline_context,
            source_hash="sha256:old",
        ),
    })
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "exists_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)
    migration_state = initialize_migration_state(None, migration_id, {"test": "search-delta"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    provenance_context.update({
        "migration_mode": "delta_upsert",
        "baseline_source_cutoff_at": "2026-07-28T12:00:00+00:00",
    })
    job = {"id": migration_id, "migration_state": migration_state}

    artifacts = module._copy_ai_search_to_target(
        {
            "migration_max_parallel_operations": 2,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
        {
            "users": {"mode": "all", "ids": [], "include_documents": True},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
            "include_ai_search": True,
        },
        job,
        migration_state,
        provenance_context,
    )

    assert artifacts[0]["created_count"] == 1
    assert artifacts[0]["updated_count"] == 1
    assert artifacts[0]["unchanged_count"] == 1
    assert {document["id"] for document in target_client.uploaded} == {"created", "changed"}
    assert all(
        document["simplechatMigrationSourceHash"].startswith("sha256:")
        for document in target_client.uploaded
    )


def test_data_management_ai_search_partial_failure_retries_same_keyset_page(monkeypatch):
    """Keep the cursor before a partially failed page and clear attempt failures on retry."""
    migration_id = "77777777-7777-7777-7777-777777777777"
    source_client = FakeSearchClient([
        {"id": f"document-{index:03d}", "user_id": "user-1"}
        for index in range(4)
    ])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_client, job_container)
    module.DATA_MANAGEMENT_MIGRATION_BATCH_SIZE = 2
    target_client = FailOnceTargetSearchClient("document-001")
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "exists_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)
    settings = {
        "migration_max_parallel_operations": 1,
        "migration_retry_count": 1,
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "search-partial"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    job = {"id": migration_id, "migration_state": migration_state}

    with pytest.raises(RuntimeError, match="before its keyset cursor could advance"):
        module._copy_ai_search_to_target(
            settings,
            migration_plan,
            job,
            migration_state,
            provenance_context,
        )

    failed_progress = job["migration_state"]["resources"][
        "ai_search:users:simplechat-user-index"
    ]["progress"]
    assert failed_progress["failed_count"] == 1
    assert failed_progress["keyset_cursor"]["last_id"] == ""
    first_query_count = len(source_client.source_queries)

    artifacts = module._copy_ai_search_to_target(
        settings,
        migration_plan,
        job,
        job["migration_state"],
        provenance_context,
    )

    resumed_queries = source_client.source_queries[first_query_count:]
    assert resumed_queries
    assert "id gt" not in str(resumed_queries[0].get("filter") or "")
    assert target_client.attempted_ids.count("document-001") == 2
    assert artifacts[0]["failed_count"] == 0
    assert artifacts[0]["prior_failed_count"] == 1
    assert (
        artifacts[0]["created_count"] +
        artifacts[0]["updated_count"] +
        artifacts[0]["unchanged_count"]
    ) == 4
    manifest_entries = [
        entry
        for batch in job_container.manifest_batches
        for entry in batch["entries"]
    ]
    failed_entries = [entry for entry in manifest_entries if entry["status"] == "failed"]
    assert len(failed_entries) == 1
    assert failed_entries[0]["source_identity"].startswith("sha256:")
    assert "document-001" not in failed_entries[0]["source_identity"]


def test_ai_search_ambiguous_write_reclassifies_before_retry(monkeypatch):
    """Fail closed on a new unowned target key while recovering a response-lost own write."""
    migration_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    module = load_data_management_module(monkeypatch, FakeSearchClient(), FakeJobContainer())
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    source_document = {"id": "race", "user_id": "user-1", "chunk_text": "content"}
    migration_document = module.add_search_migration_provenance(
        copy.deepcopy(source_document),
        provenance_context,
        source_hash=module._build_search_source_hash(source_document),
    )

    unowned_target = AmbiguousTargetSearchClient(
        lambda document: {"id": document["id"], "chunk_text": "external"}
    )
    with pytest.raises(module.DataManagementSettingsValidationError, match="unowned document"):
        module._upload_search_migration_batch(
            unowned_target,
            [migration_document],
            retry_count=2,
            dispositions=["create"],
            provenance_context=provenance_context,
            index_name="simplechat-user-index",
        )
    assert unowned_target.upload_attempts == 1

    response_lost_own_write = AmbiguousTargetSearchClient(lambda document: document)
    result = module._upload_search_migration_batch(
        response_lost_own_write,
        [migration_document],
        retry_count=2,
        dispositions=["create"],
        provenance_context=provenance_context,
        index_name="simplechat-user-index",
    )
    assert response_lost_own_write.upload_attempts == 1
    assert result["copied"] == 1
    assert result["created"] == 1
    assert result["failed"] == 0


def test_ai_search_upload_renews_heartbeat_while_request_is_in_flight(monkeypatch):
    """Renew the migration lease before a slow Search upload completes."""
    migration_id = "88888888-8888-8888-8888-888888888888"
    source_client = FakeSearchClient([{"id": "slow", "user_id": "user-1"}])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_client, job_container)
    release_upload = threading.Event()
    upload_started = threading.Event()
    upload_completed = threading.Event()

    class SlowTargetClient(CountingTargetSearchClient):
        def upload_documents(self, documents, **kwargs):
            upload_started.set()
            assert release_upload.wait(timeout=5.0)
            result = super().upload_documents(documents, **kwargs)
            upload_completed.set()
            return result

    target_client = SlowTargetClient()
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "exists_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)
    heartbeats = []
    original_heartbeat = module._persist_migration_heartbeat

    def capture_heartbeat(*args, **kwargs):
        assert upload_started.is_set()
        assert not upload_completed.is_set()
        heartbeats.append(time.monotonic())
        release_upload.set()
        return original_heartbeat(*args, **kwargs)

    monkeypatch.setattr(module, "_persist_migration_heartbeat", capture_heartbeat)
    migration_state = initialize_migration_state(None, migration_id, {"test": "slow-search"})

    module._copy_ai_search_to_target(
        {
            "migration_max_parallel_operations": 1,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
        {
            "users": {"mode": "all", "ids": [], "include_documents": True},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
            "include_ai_search": True,
        },
        {"id": migration_id, "migration_state": migration_state},
        migration_state,
        create_migration_provenance_context(migration_id=migration_id),
    )

    assert heartbeats
    assert release_upload.is_set()
    assert upload_completed.is_set()


def test_ai_search_cancellation_records_in_flight_success_before_stopping(monkeypatch):
    """Persist an accepted upload without advancing its keyset cursor on cancellation."""
    migration_id = "99999999-9999-9999-9999-999999999999"
    source_client = FakeSearchClient([{"id": "slow", "user_id": "user-1"}])
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, source_client, job_container)
    release_upload = threading.Event()
    upload_started = threading.Event()

    class SlowTargetClient(CountingTargetSearchClient):
        def upload_documents(self, documents, **kwargs):
            upload_started.set()
            assert release_upload.wait(timeout=5.0)
            return super().upload_documents(documents, **kwargs)

    target_client = SlowTargetClient()
    monkeypatch.setattr(
        module,
        "_ensure_target_search_index",
        lambda *_args, **_kwargs: "exists_with_migration_provenance",
    )
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)

    def cancel_during_upload(*_args, **_kwargs):
        assert upload_started.is_set()
        release_upload.set()
        raise module.DataManagementMigrationCanceledError("requested")

    monkeypatch.setattr(module, "_persist_migration_heartbeat", cancel_during_upload)
    migration_state = initialize_migration_state(None, migration_id, {"test": "cancel-search"})
    job = {"id": migration_id, "migration_state": migration_state}

    with pytest.raises(module.DataManagementMigrationCanceledError, match="requested"):
        module._copy_ai_search_to_target(
            {
                "migration_max_parallel_operations": 1,
                "migration_retry_count": 1,
                "data_management_job_lease_seconds": 900,
            },
            {
                "users": {"mode": "all", "ids": [], "include_documents": True},
                "groups": {"mode": "none", "ids": [], "include_documents": False},
                "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
                "include_ai_search": True,
            },
            job,
            migration_state,
            create_migration_provenance_context(migration_id=migration_id),
        )

    progress = job["migration_state"]["resources"][
        "ai_search:users:simplechat-user-index"
    ]["progress"]
    assert progress["copied_count"] == 1
    assert progress["created_count"] == 1
    assert progress["keyset_cursor"]["last_id"] == ""
    manifest_entries = [
        entry
        for batch in job_container.manifest_batches
        for entry in batch["entries"]
    ]
    assert [entry["status"] for entry in manifest_entries] == ["created"]