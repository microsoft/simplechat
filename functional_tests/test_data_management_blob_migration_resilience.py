# test_data_management_blob_migration_resilience.py
"""
Functional test for resilient Data Management blob migration.
Version: 0.250.071
Implemented in: 0.250.075

This test ensures blob migration streams source content, preserves metadata,
uses provenance skips, and exposes concurrent copy progress in job state.
"""

import copy
import importlib.util
from pathlib import Path
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
    """Persist deep copies like the production jobs container."""

    def __init__(self):
        self.manifest_batches = []

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def create_item(self, body):
        self.manifest_batches.append(copy.deepcopy(body))
        return copy.deepcopy(body)


class FakeSourceDocumentsContainer:
    """Expose selected document records through a Cosmos-like iterator."""

    def __init__(self, documents):
        self.documents = documents

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(self.documents))


class FakeDownload:
    """Expose only chunk streaming; readall intentionally does not exist."""

    def __init__(self, payload):
        self.payload = payload

    def chunks(self):
        yield self.payload[:2]
        yield self.payload[2:]


class FakeSourceBlob:
    """Return source properties and a bounded streaming download."""

    def __init__(self, payload):
        self.payload = payload

    def get_blob_properties(self):
        return types.SimpleNamespace(
            metadata={"source": "preserved", "destination": "source-value"},
            size=len(self.payload),
            content_settings="source-content-settings",
            etag=f"etag-{self.payload.decode('utf-8')}",
            last_modified=None,
            blob_tier="Cool",
            blob_type="BlockBlob",
            tags={"classification": "internal"},
        )

    def download_blob(self, **_kwargs):
        if _kwargs.get("etag"):
            assert _kwargs.get("etag") == f"etag-{self.payload.decode('utf-8')}"
            assert _kwargs.get("match_condition") is not None
        assert _kwargs.get("timeout") == 120
        return FakeDownload(self.payload)


class FakeSourceBlobService:
    """Create fake source clients for every persisted blob path."""

    def get_blob_client(self, **kwargs):
        return FakeSourceBlob(f"payload:{kwargs['blob']}".encode("utf-8"))


class MissingSourceBlob(FakeSourceBlob):
    """Represent a persisted source reference whose Blob no longer exists."""

    def get_blob_properties(self):
        from azure.core.exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("not found")


class FakeTargetBlob:
    """Store metadata and track concurrent streaming uploads."""

    def __init__(self, existing_metadata, tracker):
        self.existing_metadata = existing_metadata
        self.tracker = tracker
        self.uploads = []
        self.size = 0
        self.etag = "target-etag"
        self.content_settings = None

    def get_blob_properties(self):
        if self.existing_metadata is None:
            return None
        return types.SimpleNamespace(
            metadata=copy.deepcopy(self.existing_metadata),
            size=self.size,
            etag=self.etag,
            content_settings=self.content_settings,
        )

    def upload_blob(self, data, **kwargs):
        with self.tracker["lock"]:
            self.tracker["active"] += 1
            self.tracker["maximum"] = max(self.tracker["maximum"], self.tracker["active"])
        try:
            time.sleep(0.03)
            self.uploads.append({
                "data": b"".join(data),
                "metadata": copy.deepcopy(kwargs["metadata"]),
                "content_settings": kwargs["content_settings"],
                "length": kwargs["length"],
                "overwrite": kwargs["overwrite"],
                "tags": copy.deepcopy(kwargs.get("tags")),
                "standard_blob_tier": kwargs.get("standard_blob_tier"),
                "blob_type": kwargs.get("blob_type"),
                "etag": kwargs.get("etag"),
                "match_condition": kwargs.get("match_condition"),
                "timeout": kwargs.get("timeout"),
            })
            self.existing_metadata = copy.deepcopy(kwargs["metadata"])
            self.size = kwargs["length"]
            self.content_settings = kwargs["content_settings"]
        finally:
            with self.tracker["lock"]:
                self.tracker["active"] -= 1

    def set_blob_metadata(self, metadata, **kwargs):
        assert kwargs.get("etag") == self.etag
        assert kwargs.get("match_condition") is not None
        self.existing_metadata = copy.deepcopy(metadata)

    def delete_blob(self, **_kwargs):
        self.existing_metadata = None
        self.size = 0


class FakeTargetBlobService:
    """Expose per-path target blobs and successful container creation."""

    def __init__(self, migration_id):
        self.tracker = {"active": 0, "maximum": 0, "lock": threading.Lock()}
        self.blobs = {
            "already-migrated.txt": FakeTargetBlob({
                "simplechatMigrationId": migration_id,
                "simplechatMigratedAtUtc": "2026-07-24T12:00:00+00:00",
                "simplechatMigrationStatus": "succeeded",
            }, self.tracker),
            "copy-one.txt": FakeTargetBlob(None, self.tracker),
            "copy-two.txt": FakeTargetBlob(None, self.tracker),
        }

    def create_container(self, _container_name):
        return object()

    def get_blob_client(self, **kwargs):
        return self.blobs[kwargs["blob"]]


def load_data_management_module(monkeypatch, source_documents, source_blob_service, job_container):
    """Load the production module with migration dependencies replaced by fakes."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {"storage_account_office_docs_client": source_blob_service}
    config_module.VERSION = "0.250.075"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.cosmos_user_documents_container = source_documents
    config_module.storage_account_user_documents_container_name = "user-documents"
    config_module.storage_account_group_documents_container_name = "group-documents"
    config_module.storage_account_public_documents_container_name = "public-documents"
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

    module_name = "data_management_blob_resilience_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_data_management_blob_migration_streams_and_tags_concurrently(monkeypatch):
    """Validate target marker bypass, metadata preservation, and bounded streaming uploads."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    source_documents = FakeSourceDocumentsContainer([
        {"id": "one", "user_id": "user-1", "blob_path": "copy-one.txt", "_ts": 1},
        {"id": "two", "user_id": "user-1", "blob_path": "copy-two.txt", "_ts": 1},
        {"id": "already", "user_id": "user-1", "blob_path": "already-migrated.txt", "_ts": 1},
        {"id": "legacy", "user_id": "user-1", "file_name": "legacy.txt", "_ts": 1},
    ])
    source_blob_service = FakeSourceBlobService()
    target_blob_service = FakeTargetBlobService(migration_id)
    job_container = FakeJobContainer()
    module = load_data_management_module(
        monkeypatch,
        source_documents,
        source_blob_service,
        job_container,
    )
    monkeypatch.setattr(
        module,
        "_get_target_enhanced_citations_blob_client",
        lambda *_args, **_kwargs: target_blob_service,
    )
    already_source = source_blob_service.get_blob_client(
        container="user-documents",
        blob="already-migrated.txt",
    )
    already_hash, already_version = module._build_blob_source_fingerprint(
        already_source.get_blob_properties()
    )
    target_blob_service.blobs["already-migrated.txt"].existing_metadata.update({
        "simplechatMigrationSourceHash": already_hash,
        "simplechatMigrationSourceVersion": already_version,
    })

    settings = {
        "migration_max_parallel_operations": 2,
        "migration_retry_count": 2,
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_source_blobs": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "blobs"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-24T12:00:00+00:00",
    )
    job = {"id": migration_id, "migration_state": migration_state}

    artifacts = module._copy_source_blobs_to_target(
        settings,
        migration_plan,
        job,
        migration_state,
        provenance_context,
    )

    copy_one = target_blob_service.blobs["copy-one.txt"].uploads[0]
    copy_two = target_blob_service.blobs["copy-two.txt"].uploads[0]
    assert not target_blob_service.blobs["already-migrated.txt"].uploads
    assert target_blob_service.tracker["maximum"] >= 2
    assert copy_one["metadata"]["destination"] == "source-value"
    assert copy_one["metadata"]["source"] == "preserved"
    assert copy_one["metadata"]["simplechatMigrationId"] == migration_id
    assert copy_one["metadata"]["simplechatMigrationStatus"] == "pending"
    assert target_blob_service.blobs["copy-one.txt"].existing_metadata[
        "simplechatMigrationStatus"
    ] == "succeeded"
    assert copy_one["metadata"]["simplechatMigrationScopeHash"] == module._document_migration_scope_hash({
        "user_id": "user-1",
    })
    assert copy_two["content_settings"] == "source-content-settings"
    assert copy_two["length"] == len(copy_two["data"])
    assert copy_one["tags"] == {"classification": "internal"}
    assert copy_one["standard_blob_tier"] == "Cool"
    assert copy_one["blob_type"] == "BlockBlob"
    assert copy_one["overwrite"] is False
    assert copy_two["overwrite"] is False
    summary = next(artifact for artifact in artifacts if artifact.get("type") == "source_blobs")
    assert summary["copied_count"] == 2
    assert summary["skipped_count"] == 0
    assert summary["not_applicable_count"] == 1
    resource = job["migration_state"]["resources"]["source_blobs:selected_documents"]
    assert resource["status"] == "completed"

    unowned_target = FakeTargetBlob({"existing": "unowned"}, target_blob_service.tracker)
    collision = module._copy_source_blob_migration_record(
        FakeSourceBlob(b"collision"),
        unowned_target,
        provenance_context,
        retry_count=1,
    )
    assert collision["status"] == "collision"
    assert not unowned_target.uploads


def test_data_management_blob_delta_updates_only_changed_owned_blobs(monkeypatch):
    """Use source versions to create new and conditionally update changed owned blobs."""
    migration_id = "22222222-2222-2222-2222-222222222222"
    baseline_migration_id = "11111111-1111-1111-1111-111111111111"
    source_documents = FakeSourceDocumentsContainer([
        {"id": "unchanged", "user_id": "user-1", "blob_path": "unchanged.txt", "_ts": 1},
        {"id": "changed", "user_id": "user-1", "blob_path": "changed.txt", "_ts": 1},
        {"id": "created", "user_id": "user-1", "blob_path": "created.txt", "_ts": 1},
    ])
    source_blob_service = FakeSourceBlobService()
    job_container = FakeJobContainer()
    module = load_data_management_module(
        monkeypatch,
        source_documents,
        source_blob_service,
        job_container,
    )
    baseline_context = create_migration_provenance_context(
        migration_id=baseline_migration_id,
        migrated_at_utc="2026-07-28T12:00:00+00:00",
    )
    tracker = {"active": 0, "maximum": 0, "lock": threading.Lock()}
    unchanged_source = source_blob_service.get_blob_client(
        container="user-documents",
        blob="unchanged.txt",
    )
    unchanged_hash, unchanged_version = module._build_blob_source_fingerprint(
        unchanged_source.get_blob_properties()
    )
    target_blob_service = FakeTargetBlobService(migration_id)
    target_blob_service.blobs = {
        "unchanged.txt": FakeTargetBlob(
            module.merge_blob_migration_metadata(
                {},
                baseline_context,
                source_hash=unchanged_hash,
                source_version=unchanged_version,
            ),
            tracker,
        ),
        "changed.txt": FakeTargetBlob(
            module.merge_blob_migration_metadata(
                {},
                baseline_context,
                source_version="sha256:old",
            ),
            tracker,
        ),
        "created.txt": FakeTargetBlob(None, tracker),
    }
    monkeypatch.setattr(
        module,
        "_get_target_enhanced_citations_blob_client",
        lambda *_args, **_kwargs: target_blob_service,
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "blob-delta"})
    provenance_context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    provenance_context.update({
        "migration_mode": "delta_upsert",
        "baseline_source_cutoff_at": "2026-07-28T12:00:00+00:00",
    })
    job = {"id": migration_id, "migration_state": migration_state}

    artifacts = module._copy_source_blobs_to_target(
        {
            "migration_max_parallel_operations": 2,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
        {
            "users": {"mode": "all", "ids": [], "include_documents": True},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
            "include_source_blobs": True,
        },
        job,
        migration_state,
        provenance_context,
    )

    summary = next(artifact for artifact in artifacts if artifact.get("type") == "source_blobs")
    assert summary["created_count"] == 1
    assert summary["updated_count"] == 1
    assert summary["unchanged_count"] == 1
    assert not target_blob_service.blobs["unchanged.txt"].uploads
    changed_upload = target_blob_service.blobs["changed.txt"].uploads[0]
    created_upload = target_blob_service.blobs["created.txt"].uploads[0]
    assert changed_upload["overwrite"] is True
    assert changed_upload["etag"] == "target-etag"
    assert changed_upload["match_condition"] is not None
    assert created_upload["overwrite"] is False


def test_blob_transfer_renews_heartbeat_before_long_copy_completes(monkeypatch):
    """Renew the durable lease while a source Blob future is still streaming."""
    migration_id = "33333333-3333-3333-3333-333333333333"

    class SlowDownload(FakeDownload):
        def chunks(self):
            yield self.payload[:2]
            time.sleep(2.2)
            yield self.payload[2:]

    class SlowSourceBlob(FakeSourceBlob):
        def download_blob(self, **kwargs):
            super().download_blob(**kwargs)
            return SlowDownload(self.payload)

    class SlowSourceBlobService(FakeSourceBlobService):
        def get_blob_client(self, **kwargs):
            return SlowSourceBlob(f"payload:{kwargs['blob']}".encode("utf-8"))

    source_documents = FakeSourceDocumentsContainer([
        {"id": "slow", "user_id": "user-1", "blob_path": "slow.txt", "_ts": 1},
    ])
    source_blob_service = SlowSourceBlobService()
    job_container = FakeJobContainer()
    module = load_data_management_module(
        monkeypatch,
        source_documents,
        source_blob_service,
        job_container,
    )
    target_blob_service = FakeTargetBlobService(migration_id)
    target_blob_service.blobs = {
        "slow.txt": FakeTargetBlob(None, target_blob_service.tracker),
    }
    monkeypatch.setattr(
        module,
        "_get_target_enhanced_citations_blob_client",
        lambda *_args, **_kwargs: target_blob_service,
    )
    heartbeat_messages = []
    persist_checkpoint = module._persist_migration_checkpoint

    def capture_checkpoint(*args, **kwargs):
        heartbeat_messages.append(args[5])
        return persist_checkpoint(*args, **kwargs)

    monkeypatch.setattr(module, "_persist_migration_checkpoint", capture_checkpoint)
    migration_state = initialize_migration_state(None, migration_id, {"test": "blob-heartbeat"})
    job = {"id": migration_id, "migration_state": migration_state}

    module._copy_source_blobs_to_target(
        {
            "migration_max_parallel_operations": 1,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
        {
            "users": {"mode": "all", "ids": [], "include_documents": True},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
            "include_source_blobs": True,
        },
        job,
        migration_state,
        create_migration_provenance_context(migration_id=migration_id),
    )

    assert "Migrating source blobs; worker heartbeat renewed" in heartbeat_messages


def test_blob_verification_failure_never_leaves_succeeded_provenance(monkeypatch):
    """Keep a failed create retryable instead of stamping a false success marker."""
    migration_id = "44444444-4444-4444-4444-444444444444"
    source_blob = FakeSourceBlob(b"expected")
    tracker = {"active": 0, "maximum": 0, "lock": threading.Lock()}

    class CorruptTargetBlob(FakeTargetBlob):
        def get_blob_properties(self):
            properties = super().get_blob_properties()
            if properties is not None and self.uploads:
                properties.size += 1
            return properties

    target_blob = CorruptTargetBlob(None, tracker)
    module = load_data_management_module(
        monkeypatch,
        FakeSourceDocumentsContainer([]),
        FakeSourceBlobService(),
        FakeJobContainer(),
    )

    result = module._copy_source_blob_migration_record(
        source_blob,
        target_blob,
        create_migration_provenance_context(migration_id=migration_id),
        retry_count=1,
    )

    assert result["status"] == "failed"
    assert target_blob.existing_metadata is None


def test_missing_persisted_blob_fails_while_legacy_no_blob_is_not_applicable(monkeypatch):
    """Keep missing references retryable without warning on legacy standard citations."""
    migration_id = "55555555-5555-5555-5555-555555555555"

    class MissingSourceBlobService(FakeSourceBlobService):
        def get_blob_client(self, **kwargs):
            if kwargs["blob"] == "missing.txt":
                return MissingSourceBlob(b"")
            return super().get_blob_client(**kwargs)

    source_documents = FakeSourceDocumentsContainer([
        {"id": "missing", "user_id": "user-1", "blob_path": "missing.txt", "_ts": 1},
        {"id": "legacy", "user_id": "user-1", "file_name": "legacy.txt", "_ts": 1},
    ])
    source_blob_service = MissingSourceBlobService()
    job_container = FakeJobContainer()
    module = load_data_management_module(
        monkeypatch,
        source_documents,
        source_blob_service,
        job_container,
    )
    target_blob_service = FakeTargetBlobService(migration_id)
    target_blob_service.blobs = {
        "missing.txt": FakeTargetBlob(None, target_blob_service.tracker),
    }
    monkeypatch.setattr(
        module,
        "_get_target_enhanced_citations_blob_client",
        lambda *_args, **_kwargs: target_blob_service,
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "missing-blob"})
    job = {"id": migration_id, "migration_state": migration_state}

    with pytest.raises(RuntimeError, match="remediation before retry"):
        module._copy_source_blobs_to_target(
            {
                "migration_max_parallel_operations": 1,
                "migration_retry_count": 1,
                "data_management_job_lease_seconds": 900,
            },
            {
                "users": {"mode": "all", "ids": [], "include_documents": True},
                "groups": {"mode": "none", "ids": [], "include_documents": False},
                "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
                "include_source_blobs": True,
            },
            job,
            migration_state,
            create_migration_provenance_context(migration_id=migration_id),
        )

    resource = job["migration_state"]["resources"]["source_blobs:selected_documents"]
    assert resource["status"] == "failed"
    assert resource["progress"]["missing_count"] == 1
    assert resource["progress"]["not_applicable_count"] == 1
    manifest_entries = [
        entry
        for batch in job_container.manifest_batches
        for entry in batch["entries"]
    ]
    assert {entry["status"] for entry in manifest_entries} == {
        "missing",
        "not_applicable",
    }
    assert all(entry["source_identity"].startswith("sha256:") for entry in manifest_entries)