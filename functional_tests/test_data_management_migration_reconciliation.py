# test_data_management_migration_reconciliation.py
"""
Functional test for Data Management migration reconciliation.
Version: 0.250.078
Implemented in: 0.250.077
Updated in: 0.250.078

This test ensures mirror reconciliation deletes only destination extras with
successful migration ownership and retains unowned or out-of-scope data.
"""

import copy
import importlib.util
from pathlib import Path
import re
import sys
import time
import types

import pytest
from azure.core.exceptions import ResourceNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_migration_provenance import create_migration_provenance_context
from functions_data_management_migration_state import initialize_migration_state


class FakeJobContainer:
    """Provide the minimum persistence surface required by the module import."""

    def __init__(self):
        self.items = []
        self.job = None

    def upsert_item(self, body):
        self.job = copy.deepcopy(body)
        return copy.deepcopy(body)

    def read_item(self, item, partition_key):
        assert item == partition_key
        if self.job and self.job.get("id") == item:
            return copy.deepcopy(self.job)
        raise ResourceNotFoundError("not found")

    def create_item(self, body):
        self.items.append(copy.deepcopy(body))
        return copy.deepcopy(body)

    def query_items(self, **kwargs):
        parameters = {
            parameter["name"]: parameter["value"]
            for parameter in kwargs.get("parameters") or []
        }
        return iter([
            copy.deepcopy(item)
            for item in self.items
            if item.get("job_id") == parameters.get("@job_id")
            and item.get("type") == parameters.get("@type")
            and item.get("plan_id") == parameters.get("@plan_id")
        ])


class FakeCosmosContainer:
    """Expose source/target records and conditional deletion tracking."""

    def __init__(self, documents):
        self.documents = {document["id"]: copy.deepcopy(document) for document in documents}
        self.deleted = []

    def query_items(self, **kwargs):
        selected_id = next(
            (
                parameter["value"]
                for parameter in (kwargs.get("parameters") or [])
                if parameter["name"] == "@selected_id"
            ),
            None,
        )
        documents = list(self.documents.values())
        blob_path = next(
            (
                parameter["value"]
                for parameter in (kwargs.get("parameters") or [])
                if parameter["name"] == "@blob_path"
            ),
            None,
        )
        if blob_path is not None:
            documents = [
                document for document in documents
                if blob_path in {
                    document.get("blob_path"),
                    document.get("archived_blob_path"),
                }
            ]
        if selected_id is not None:
            documents = [
                document for document in documents
                if document.get("user_id") == selected_id
            ]
        return iter(copy.deepcopy(documents))

    def read_item(self, item, partition_key):
        if item != partition_key or item not in self.documents:
            raise ResourceNotFoundError("not found")
        return copy.deepcopy(self.documents[item])

    def delete_item(self, item, partition_key, **kwargs):
        assert item == partition_key
        if self.documents[item].get("_etag"):
            assert kwargs.get("etag") == self.documents[item]["_etag"]
            assert kwargs.get("match_condition") is not None
        self.deleted.append(item)
        del self.documents[item]


class FakeTargetDatabase:
    """Return document and dedicated target Data Management job containers."""

    def __init__(self, container):
        self.container = container
        self.search_gate_container = FakeSearchGateContainer()

    def create_container_if_not_exists(self, id=None, **_kwargs):
        if id == "data_management_jobs":
            return self.search_gate_container
        return self.container


class FakeSearchGateContainer:
    """Persist a target Search write fence with Cosmos-like optimistic replacement."""

    def __init__(self):
        self.items = {}
        self.etag_counter = 0

    def _save(self, body):
        self.etag_counter += 1
        saved = copy.deepcopy(body)
        saved["_etag"] = f"gate-etag-{self.etag_counter}"
        self.items[saved["id"]] = saved
        return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.items:
            raise ResourceNotFoundError("not found")
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        if body["id"] in self.items:
            conflict = RuntimeError("already exists")
            conflict.status_code = 409
            raise conflict
        return self._save(body)

    def replace_item(self, item, body, etag=None, **_kwargs):
        current = self.items.get(item)
        if current is None or (etag and current.get("_etag") != etag):
            conflict = RuntimeError("stale gate")
            conflict.status_code = 412
            raise conflict
        return self._save(body)


class FakeSearchClient:
    """Provide deterministic keyset pages and per-document deletes."""

    def __init__(self, documents):
        self.documents = {document["id"]: copy.deepcopy(document) for document in documents}
        self.deleted = []

    def search(self, **kwargs):
        documents = sorted(self.documents.values(), key=lambda document: document["id"])
        cursor_match = re.search(r"id gt '([^']+)'", str(kwargs.get("filter") or ""))
        if cursor_match:
            documents = [
                document for document in documents
                if document["id"] > cursor_match.group(1)
            ]
        return iter(copy.deepcopy(documents[:int(kwargs.get("top") or len(documents))]))

    def delete_documents(self, documents, **_kwargs):
        for document in documents:
            self.deleted.append(document["id"])
            self.documents.pop(document["id"], None)
        return [{"succeeded": True} for _ in documents]


class GeneratedReconciliationSearchClient:
    """Generate bounded ordered Search pages without materializing a large index."""

    def __init__(self, document_count, decorate_document=None):
        self.document_count = document_count
        self.decorate_document = decorate_document
        self.queries = []

    def search(self, **kwargs):
        assert "skip" not in kwargs
        assert kwargs.get("order_by") == ["id asc"]
        page_size = int(kwargs.get("top") or 0)
        assert 0 < page_size <= 1000
        self.queries.append(copy.deepcopy(kwargs))
        cursor_match = re.search(
            r"id gt 'document-(\d+)'",
            str(kwargs.get("filter") or ""),
        )
        start_index = int(cursor_match.group(1)) + 1 if cursor_match else 0
        end_index = min(self.document_count, start_index + page_size)
        documents = []
        for index in range(start_index, end_index):
            document = {
                "id": f"document-{index:06d}",
                "user_id": "user-1",
            }
            if self.decorate_document:
                document = self.decorate_document(document)
            documents.append(document)
        return iter(documents)


class FakeTargetBlob:
    """Record ETag-guarded blob deletion."""

    def __init__(self, container, name):
        self.container = container
        self.name = name

    def get_blob_properties(self):
        blob = self.container.blobs[self.name]
        return types.SimpleNamespace(
            metadata=copy.deepcopy(blob.get("metadata") or {}),
            etag=blob.get("etag"),
            size=blob.get("size", 0),
            content_settings=blob.get("content_settings"),
        )

    def delete_blob(self, **kwargs):
        blob = self.container.blobs[self.name]
        assert kwargs.get("etag") == blob["etag"]
        assert kwargs.get("match_condition") is not None
        self.container.deleted.append(self.name)


class FakeTargetBlobContainer:
    """List target Blob metadata and expose deletion clients."""

    def __init__(self, blobs):
        self.blobs = {blob["name"]: copy.deepcopy(blob) for blob in blobs}
        self.deleted = []

    def list_blobs(self, **kwargs):
        assert "metadata" in kwargs.get("include", [])
        return iter(copy.deepcopy(list(self.blobs.values())))

    def get_blob_client(self, blob_name):
        return FakeTargetBlob(self, blob_name)


class FakeTargetBlobService:
    """Return one target Blob container."""

    def __init__(self, container):
        self.container = container

    def get_container_client(self, _container_name):
        return self.container

    def get_blob_client(self, container, blob):
        return self.container.get_blob_client(blob)


class FakeSourceBlob:
    """Return stable source properties or a missing-source response."""

    def __init__(self, properties=None):
        self.properties = properties

    def get_blob_properties(self):
        if self.properties is None:
            raise ResourceNotFoundError("not found")
        return copy.deepcopy(self.properties)


class FakeSourceBlobService:
    """Expose only source blobs that currently exist."""

    def __init__(self, blobs):
        self.blobs = copy.deepcopy(blobs)

    def get_blob_client(self, container, blob):
        return FakeSourceBlob(self.blobs.get((container, blob)))


def load_data_management_module(monkeypatch, source_cosmos, source_search):
    """Load the production module with lightweight service dependencies."""
    job_container = FakeJobContainer()
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {"search_client_user": source_search}
    config_module.VERSION = "0.250.077"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.source_container = source_cosmos
    config_module.cosmos_user_documents_container = source_cosmos
    config_module.target_container_name = "target-container"
    config_module.storage_account_user_documents_container_name = "user-documents"
    config_module.storage_account_group_documents_container_name = "group-documents"
    config_module.storage_account_public_documents_container_name = "public-documents"
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

    module_name = "data_management_reconciliation_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_mirror_reconciliation_collectors_are_read_only(monkeypatch):
    """Collect owned deletion candidates without mutating any destination service."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    source_cosmos = FakeCosmosContainer([
        {"id": "keep", "user_id": "user-1", "blob_path": "keep.txt", "_ts": 1},
    ])
    source_search = FakeSearchClient([{"id": "keep", "user_id": "user-1"}])
    module = load_data_management_module(monkeypatch, source_cosmos, source_search)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "documents",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "filter_field": "user_id",
            "documents": True,
        }],
        "groups": [],
        "public_workspaces": [],
    }
    context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    owned_cosmos = lambda document_id: module.add_cosmos_migration_provenance(
        {"id": document_id, "user_id": "user-1", "_etag": f"etag-{document_id}"},
        context,
    )
    target_cosmos = FakeCosmosContainer([
        owned_cosmos("keep"),
        owned_cosmos("delete-owned"),
        {"id": "retain-unowned", "user_id": "user-1", "_etag": "etag-unowned"},
    ])
    target_search = FakeSearchClient([
        module.add_search_migration_provenance({"id": "keep", "user_id": "user-1"}, context),
        module.add_search_migration_provenance({"id": "delete-owned", "user_id": "user-1"}, context),
        {"id": "retain-unowned", "user_id": "user-1"},
    ])
    user_scope_hash = module._document_migration_scope_hash({"user_id": "user-1"})
    other_scope_hash = module._document_migration_scope_hash({"user_id": "user-2"})
    owned_blob_metadata = lambda scope_hash: module.merge_blob_migration_metadata(
        {},
        context,
        scope_hash=scope_hash,
    )
    target_blob_container = FakeTargetBlobContainer([
        {"name": "keep.txt", "metadata": owned_blob_metadata(user_scope_hash), "etag": "etag-keep"},
        {"name": "delete-owned.txt", "metadata": owned_blob_metadata(user_scope_hash), "etag": "etag-delete"},
        {"name": "other-scope.txt", "metadata": owned_blob_metadata(other_scope_hash), "etag": "etag-other"},
        {"name": "retain-unowned.txt", "metadata": {}, "etag": "etag-unowned"},
    ])
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_search)
    monkeypatch.setattr(
        module,
        "_get_target_enhanced_citations_blob_client",
        lambda *_args, **_kwargs: FakeTargetBlobService(target_blob_container),
    )
    source_blob_properties = types.SimpleNamespace(
        metadata={},
        size=4,
        content_settings=None,
        etag="source-etag",
        last_modified=None,
        blob_tier=None,
        blob_type="BlockBlob",
        tags={},
    )
    monkeypatch.setattr(
        module,
        "_get_source_blob_service_client",
        lambda: FakeSourceBlobService({
            ("user-documents", "keep.txt"): source_blob_properties,
        }),
    )
    migration_plan = {
        "users": {"mode": "selected", "ids": ["user-1"], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
        "include_source_blobs": True,
        "migration_mode": "mirror_with_deletions",
        "mirror_deletions_confirmed": True,
    }
    migration_state = {"source_cutoff_at": "2026-07-29T12:00:00+00:00"}

    cosmos_report = module._reconcile_cosmos_migration(
        FakeTargetDatabase(target_cosmos),
        migration_plan,
        migration_state,
        context,
    )
    search_report = module._reconcile_ai_search_migration({}, migration_plan)
    blob_report = module._reconcile_blob_migration({}, migration_plan)

    assert target_cosmos.deleted == []
    assert target_search.deleted == []
    assert target_blob_container.deleted == []
    for report in (cosmos_report, search_report, blob_report):
        assert report["deleted_count"] == 0
        assert report["remaining_destination_only_owned_count"] == 1
        assert report["delete_candidate_count"] == 1
        assert "_deletion_candidates" not in report
    assert cosmos_report["destination_only_unowned_count"] == 1
    assert search_report["destination_only_unowned_count"] == 1
    assert "other-scope.txt" not in target_blob_container.deleted
    assert "retain-unowned.txt" not in target_blob_container.deleted


def test_two_phase_mirror_deletes_only_after_clean_preview_parity(monkeypatch):
    """Apply owned deletes only after read-only readiness and preview counts agree."""
    migration_id = "22222222-2222-2222-2222-222222222222"
    source_cosmos = FakeCosmosContainer([
        {"id": "keep", "user_id": "user-1", "blob_path": "keep.txt", "_ts": 1},
    ])
    source_search = FakeSearchClient([{"id": "keep", "user_id": "user-1"}])
    module = load_data_management_module(monkeypatch, source_cosmos, source_search)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "documents",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "filter_field": "user_id",
            "documents": True,
        }],
        "groups": [],
        "public_workspaces": [],
    }
    context = create_migration_provenance_context(
        migration_id=migration_id,
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    source_keep = {"id": "keep", "user_id": "user-1", "blob_path": "keep.txt"}
    target_cosmos = FakeCosmosContainer([
        module.add_cosmos_migration_provenance(
            {"id": "keep", "user_id": "user-1", "_etag": "etag-keep"},
            context,
            source_hash=module._build_cosmos_source_hash(source_keep),
            source_version="1",
        ),
        module.add_cosmos_migration_provenance(
            {"id": "delete-owned", "user_id": "user-1", "_etag": "etag-delete"},
            context,
        ),
    ])
    target_search = FakeSearchClient([
        module.add_search_migration_provenance(
            {"id": "keep", "user_id": "user-1"},
            context,
            source_hash=module._build_search_source_hash({"id": "keep", "user_id": "user-1"}),
        ),
        module.add_search_migration_provenance({"id": "delete-owned", "user_id": "user-1"}, context),
    ])
    user_scope_hash = module._document_migration_scope_hash({"user_id": "user-1"})
    source_blob_properties = types.SimpleNamespace(
        metadata={},
        size=4,
        content_settings=None,
        etag="source-etag",
        last_modified=None,
        blob_tier=None,
        blob_type="BlockBlob",
        tags={},
    )
    source_blob_hash, source_blob_version = module._build_blob_source_fingerprint(
        source_blob_properties
    )
    target_blob_container = FakeTargetBlobContainer([
        {
            "name": "keep.txt",
            "metadata": module.merge_blob_migration_metadata(
                {},
                context,
                source_hash=source_blob_hash,
                source_version=source_blob_version,
                scope_hash=user_scope_hash,
            ),
            "etag": "etag-keep",
            "size": 4,
        },
        {
            "name": "delete-owned.txt",
            "metadata": module.merge_blob_migration_metadata({}, context, scope_hash=user_scope_hash),
            "etag": "etag-delete",
        },
    ])
    source_blob_service = FakeSourceBlobService({
        ("user-documents", "keep.txt"): source_blob_properties,
    })
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_search)
    monkeypatch.setattr(
        module,
        "_get_target_enhanced_citations_blob_client",
        lambda *_args, **_kwargs: FakeTargetBlobService(target_blob_container),
    )
    monkeypatch.setattr(module, "_get_source_blob_service_client", lambda: source_blob_service)
    monkeypatch.setattr(module, "_assert_migration_job_lease", lambda *_args, **_kwargs: None)
    migration_plan = {
        "users": {"mode": "selected", "ids": ["user-1"], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
        "include_source_blobs": True,
        "migration_mode": "mirror_with_deletions",
        "mirror_deletions_confirmed": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "mirror-two-phase"})
    job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "running",
        "migration_state": migration_state,
        "result": {},
    }
    preview = {
        "estimated_outcomes": {
                "create_count": 0,
            "update_count": 0,
            "unchanged_count": 3,
            "delete_count": 3,
            "not_applicable_count": 0,
            "missing_count": 0,
            "conflict_count": 0,
            "failed_count": 0,
        },
    }
    artifacts = [
        {"type": "cosmos_container", "created_count": 0, "updated_count": 0, "unchanged_count": 1},
        {"type": "ai_search_documents", "created_count": 0, "updated_count": 0, "unchanged_count": 1},
        {"type": "source_blobs", "created_count": 0, "updated_count": 0, "unchanged_count": 1, "missing_count": 0},
    ]

    result = module._run_data_management_migration_reconciliation(
        {},
        migration_plan,
        job,
        migration_state,
        context,
        FakeTargetDatabase(target_cosmos),
        preview_snapshot=preview,
        migration_artifacts=artifacts,
    )

    assert result["deletion_status"] == "completed"
    assert result["readiness"] == "ready"
    assert result["deleted_count"] == 3
    assert target_cosmos.deleted == ["delete-owned"]
    assert target_search.deleted == ["delete-owned"]
    assert target_blob_container.deleted == ["delete-owned.txt"]
    deleted_entries = list(module.iter_data_management_migration_manifest_entries(
        migration_id,
        statuses={"deleted"},
    ))
    assert len(deleted_entries) == 3
    assert all(entry["item_ref"] for entry in deleted_entries)


def test_mirror_blocks_all_deletes_when_current_source_record_exists_after_cutoff(monkeypatch):
    """Never infer deletion when a current source identity was updated after the cutoff."""
    migration_id = "33333333-3333-3333-3333-333333333333"
    source_cosmos = FakeCosmosContainer([
        {"id": "updated-after-cutoff", "user_id": "user-1", "_ts": 200},
    ])
    source_search = FakeSearchClient([])
    module = load_data_management_module(monkeypatch, source_cosmos, source_search)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "documents",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "filter_field": "user_id",
            "documents": True,
        }],
        "groups": [],
        "public_workspaces": [],
    }
    context = create_migration_provenance_context(migration_id=migration_id)
    target_cosmos = FakeCosmosContainer([
        module.add_cosmos_migration_provenance(
            {"id": "updated-after-cutoff", "user_id": "user-1", "_etag": "etag-updated"},
            context,
        ),
        module.add_cosmos_migration_provenance(
            {"id": "other-owned-extra", "user_id": "user-1", "_etag": "etag-extra"},
            context,
        ),
    ])
    monkeypatch.setattr(module, "_assert_migration_job_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_reconcile_ai_search_migration", lambda *_args, **_kwargs: {
        "service": "ai_search", "resources": [], "_deletion_candidates": [],
    })
    monkeypatch.setattr(module, "_reconcile_blob_migration", lambda *_args, **_kwargs: {
        "service": "source_blobs", "resources": [], "_deletion_candidates": [],
    })
    migration_plan = {
        "users": {"mode": "selected", "ids": ["user-1"], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": False,
        "include_source_blobs": False,
        "migration_mode": "mirror_with_deletions",
        "mirror_deletions_confirmed": True,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "post-cutoff"})
    migration_state["source_cutoff_at"] = "1970-01-01T00:01:40+00:00"
    job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "running",
        "migration_state": migration_state,
        "result": {},
    }
    preview = {"estimated_outcomes": {
        "create_count": 0, "update_count": 0, "unchanged_count": 0,
        "delete_count": 2, "not_applicable_count": 0, "missing_count": 0,
        "conflict_count": 0, "failed_count": 0,
    }}

    with pytest.raises(RuntimeError, match="not ready for cutover"):
        module._run_data_management_migration_reconciliation(
            {},
            migration_plan,
            job,
            migration_state,
            context,
            FakeTargetDatabase(target_cosmos),
            preview_snapshot=preview,
            migration_artifacts=[],
        )

    result = job["migration_state"]["resources"]["reconciliation:cutover"]["result"]
    assert result["deletion_status"] == "blocked"
    assert result["readiness"] == "not_ready"
    assert target_cosmos.deleted == []
    detail = module.get_data_management_job_detail(migration_id)
    reconciliation_artifacts = [
        artifact
        for artifact in detail["job"]["result"]["artifacts"]
        if artifact.get("type") == "migration_reconciliation"
    ]
    assert reconciliation_artifacts[0]["readiness"] == "not_ready"
    assert reconciliation_artifacts[0]["deletion_status"] == "blocked"


def test_reconciliation_persists_preview_actual_divergence(monkeypatch):
    """Record actual migration outcomes and their delta from the server preview."""
    source_cosmos = FakeCosmosContainer([])
    source_search = FakeSearchClient([])
    module = load_data_management_module(monkeypatch, source_cosmos, source_search)
    empty_report = {
        "matched_count": 0,
        "missing_count": 0,
        "destination_only_owned_count": 0,
        "remaining_destination_only_owned_count": 0,
        "destination_only_unowned_count": 0,
        "conflict_count": 0,
        "deleted_count": 1,
        "unresolved_scope_count": 0,
        "create_count": 0,
        "update_count": 0,
        "unchanged_count": 0,
        "delete_candidate_count": 1,
        "not_applicable_count": 0,
        "source_missing_count": 0,
        "resources": [],
    }
    monkeypatch.setattr(
        module,
        "_reconcile_cosmos_migration",
        lambda *_args, **_kwargs: {"service": "cosmos", **empty_report},
    )
    monkeypatch.setattr(
        module,
        "_reconcile_ai_search_migration",
        lambda *_args, **_kwargs: {"service": "ai_search", **empty_report, "deleted_count": 0},
    )
    monkeypatch.setattr(
        module,
        "_reconcile_blob_migration",
        lambda *_args, **_kwargs: {"service": "source_blobs", **empty_report, "deleted_count": 0},
    )
    migration_id = "99999999-9999-9999-9999-999999999999"
    migration_state = initialize_migration_state(None, migration_id, {"test": "divergence"})
    job = {"id": migration_id, "migration_state": migration_state}
    preview = {
        "estimated_outcomes": {
            "create_count": 4,
            "update_count": 2,
            "unchanged_count": 2,
            "delete_count": 1,
            "not_applicable_count": 1,
            "missing_count": 0,
            "conflict_count": 0,
            "failed_count": 0,
        },
    }
    artifacts = [
        {
            "type": "cosmos_container",
            "created_count": 3,
            "updated_count": 3,
            "unchanged_count": 1,
            "failed_count": 0,
            "collision_count": 0,
        },
        {
            "type": "source_blobs",
            "created_count": 1,
            "updated_count": 0,
            "unchanged_count": 1,
            "not_applicable_count": 2,
            "missing_count": 1,
            "failed_count": 0,
            "collision_count": 0,
        },
    ]

    result = module._run_data_management_migration_reconciliation(
        {},
        {"migration_mode": "mirror_with_deletions"},
        job,
        migration_state,
        create_migration_provenance_context(migration_id=migration_id),
        object(),
        preview_snapshot=preview,
        migration_artifacts=artifacts,
    )

    assert result["actual_outcomes"] == {
        "create_count": 4,
        "update_count": 3,
        "unchanged_count": 2,
        "delete_count": 0,
        "not_applicable_count": 2,
        "missing_count": 1,
        "conflict_count": 0,
        "failed_count": 0,
    }
    assert result["preview_actual_divergence"] == {
        "create_count": 0,
        "update_count": 1,
        "unchanged_count": 0,
        "delete_count": -1,
        "not_applicable_count": 1,
        "missing_count": 1,
        "conflict_count": 0,
        "failed_count": 0,
    }


def test_ai_search_reconciliation_merges_more_than_one_hundred_thousand_keys(monkeypatch):
    """Reconcile a large index with bounded keyset pages and no full identity maps."""
    document_count = 100_001
    source_cosmos = FakeCosmosContainer([])
    placeholder_source = GeneratedReconciliationSearchClient(0)
    module = load_data_management_module(monkeypatch, source_cosmos, placeholder_source)
    context = create_migration_provenance_context(
        migration_id="44444444-4444-4444-4444-444444444444",
        migrated_at_utc="2026-07-29T12:00:00+00:00",
    )
    source_client = GeneratedReconciliationSearchClient(document_count)

    def decorate_target(document):
        return module.add_search_migration_provenance(
            document,
            context,
            source_hash=module._build_search_source_hash(document),
        )

    target_client = GeneratedReconciliationSearchClient(
        document_count,
        decorate_document=decorate_target,
    )
    module.CLIENTS["search_client_user"] = source_client
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_client)

    report = module._reconcile_ai_search_migration(
        {},
        {
            "users": {"mode": "all", "ids": [], "include_documents": True},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
            "include_ai_search": True,
            "migration_mode": "delta_upsert",
        },
    )

    assert report["matched_count"] == document_count
    assert report["unchanged_count"] == document_count
    assert report["missing_count"] == 0
    assert report["stale_count"] == 0
    assert len(source_client.queries) > 100
    assert len(target_client.queries) > 100
    assert all("skip" not in query for query in source_client.queries + target_client.queries)


def test_reconciliation_renews_heartbeat_during_slow_service_call(monkeypatch):
    """Renew the lease by time even when fewer than threshold items are returned."""
    migration_id = "55555555-5555-5555-5555-555555555555"
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    heartbeat_messages = []
    original_persist_state = module._persist_migration_state

    def capture_persist_state(job, state, settings, message, **kwargs):
        heartbeat_messages.append(message)
        return original_persist_state(job, state, settings, message, **kwargs)

    def slow_cosmos(*_args, **_kwargs):
        time.sleep(2.2)
        return {"service": "cosmos", "resources": []}

    monkeypatch.setattr(module, "_persist_migration_state", capture_persist_state)
    monkeypatch.setattr(module, "_assert_migration_job_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_reconcile_cosmos_migration", slow_cosmos)
    monkeypatch.setattr(module, "_reconcile_ai_search_migration", lambda *_args, **_kwargs: {
        "service": "ai_search", "resources": [],
    })
    monkeypatch.setattr(module, "_reconcile_blob_migration", lambda *_args, **_kwargs: {
        "service": "source_blobs", "resources": [],
    })
    migration_state = initialize_migration_state(None, migration_id, {"test": "slow-heartbeat"})
    job = {"id": migration_id, "migration_state": migration_state}

    module._run_data_management_migration_reconciliation(
        {},
        {"migration_mode": "new_only"},
        job,
        migration_state,
        create_migration_provenance_context(migration_id=migration_id),
        object(),
        preview_snapshot={"estimated_outcomes": {}},
        migration_artifacts=[],
    )

    assert "Reconciliation worker heartbeat renewed" in heartbeat_messages


def test_partial_mirror_delete_flushes_prior_success_evidence(monkeypatch):
    """Persist a successful delete before a later candidate failure is raised."""
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    flushed_entries = []
    pending_entries = []
    validation_count = 0

    def fake_validate(candidate, **_kwargs):
        nonlocal validation_count
        validation_count += 1
        if validation_count == 1:
            candidate["target_blob"] = types.SimpleNamespace(
                delete_blob=lambda **_delete_kwargs: None
            )
            return True, ""
        return False, "second candidate changed"

    def append_manifest(entry):
        pending_entries.append(copy.deepcopy(entry))

    def flush_manifest():
        flushed_entries.extend(pending_entries)
        pending_entries.clear()

    monkeypatch.setattr(module, "_validate_mirror_deletion_candidate", fake_validate)
    candidates = [
        {
            "service": "source_blobs",
            "target_type": "users",
            "container_name": "user-documents",
            "blob_name": "first.txt",
            "target_etag": "etag-first",
        },
        {
            "service": "source_blobs",
            "target_type": "users",
            "container_name": "user-documents",
            "blob_name": "second.txt",
            "target_etag": "etag-second",
        },
    ]

    with pytest.raises(module.DataManagementSettingsValidationError, match="second candidate changed"):
        module._apply_mirror_deletion_candidates(
            iter(candidates),
            manifest_append=append_manifest,
            manifest_flush=flush_manifest,
        )

    assert [entry["status"] for entry in flushed_entries] == ["deleted"]
    assert flushed_entries[0]["_locator"]["blob_name"] == "first.txt"


def test_partial_search_delete_flushes_success_before_batch_failure(monkeypatch):
    """Persist successful Search deletions from a mixed-result batch before raising."""
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    flushed_entries = []
    pending_entries = []

    class MixedDeleteClient:
        def delete_documents(self, documents, **_kwargs):
            assert len(documents) == 2
            return [{"succeeded": True}, {"succeeded": False}]

    def fake_validate(candidate, **_kwargs):
        candidate["target_client"] = MixedDeleteClient()
        candidate["index_name"] = "simplechat-user-index"
        return True, ""

    def append_manifest(entry):
        pending_entries.append(copy.deepcopy(entry))

    def flush_manifest():
        flushed_entries.extend(pending_entries)
        pending_entries.clear()

    monkeypatch.setattr(module, "_validate_mirror_deletion_candidate", fake_validate)
    candidates = [
        {
            "service": "ai_search",
            "target_type": "users",
            "index_name": "simplechat-user-index",
            "document_id": "first",
        },
        {
            "service": "ai_search",
            "target_type": "users",
            "index_name": "simplechat-user-index",
            "document_id": "second",
        },
    ]

    with pytest.raises(RuntimeError, match="failed to delete 1 document"):
        module._apply_mirror_deletion_candidates(
            iter(candidates),
            manifest_append=append_manifest,
            manifest_flush=flush_manifest,
        )

    assert [entry["status"] for entry in flushed_entries] == ["deleted"]
    assert flushed_entries[0]["_locator"]["document_id"] == "first"


def test_slow_mirror_search_validation_heartbeats_before_delete(monkeypatch):
    """Keep the target Search fence renewable while a large delete batch is revalidated."""
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    heartbeat_calls = []
    release_validation = __import__("threading").Event()

    class DeleteClient:
        def __init__(self):
            self.deleted = []

        def delete_documents(self, documents, **_kwargs):
            assert heartbeat_calls
            self.deleted.extend(document["id"] for document in documents)
            return [{"succeeded": True} for _ in documents]

    delete_client = DeleteClient()
    validation_count = 0

    def fake_validate(candidate, **_kwargs):
        nonlocal validation_count
        validation_count += 1
        if validation_count == 2:
            assert release_validation.wait(timeout=5.0)
        candidate["target_client"] = delete_client
        candidate["index_name"] = "simplechat-user-index"
        return True, ""

    def heartbeat(_message, _completed_count=0):
        heartbeat_calls.append(time.monotonic())
        release_validation.set()

    monkeypatch.setattr(module, "_validate_mirror_deletion_candidate", fake_validate)
    module._apply_mirror_deletion_candidates(
        iter([
            {
                "service": "ai_search",
                "target_type": "users",
                "index_name": "simplechat-user-index",
                "document_id": "first",
            },
            {
                "service": "ai_search",
                "target_type": "users",
                "index_name": "simplechat-user-index",
                "document_id": "second",
            },
        ]),
        heartbeat_callback=heartbeat,
    )

    assert validation_count >= 4
    assert delete_client.deleted == ["first", "second"]


def test_reconciliation_exception_fails_resource_checkpoint(monkeypatch):
    """Persist failed reconciliation state before propagating a scan exception."""
    migration_id = "66666666-6666-6666-6666-666666666666"
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    monkeypatch.setattr(module, "_assert_migration_job_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_reconcile_cosmos_migration",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scan failed")),
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "scan-failure"})
    job = {"id": migration_id, "migration_state": migration_state}

    with pytest.raises(RuntimeError, match="scan failed"):
        module._run_data_management_migration_reconciliation(
            {},
            {"migration_mode": "new_only"},
            job,
            migration_state,
            create_migration_provenance_context(migration_id=migration_id),
            object(),
            preview_snapshot={"estimated_outcomes": {}},
            migration_artifacts=[],
        )

    resource = job["migration_state"]["resources"]["reconciliation:cutover"]
    assert resource["status"] == "failed"
    assert resource["last_error"] == "scan failed"
    assert resource["result"]["readiness"] == "not_ready"
    assert resource["result"]["services_completed"] == 0
    assert resource["result"]["error"] == "scan failed"


def test_later_service_failure_preserves_completed_reconciliation_report(monkeypatch):
    """Retain completed Cosmos evidence when a later Search scan fails."""
    migration_id = "77777777-7777-7777-7777-777777777777"
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    monkeypatch.setattr(module, "_assert_migration_job_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_reconcile_cosmos_migration", lambda *_args, **_kwargs: {
        "service": "cosmos",
        "matched_count": 2,
        "resources": [{"container_name": "documents", "matched_count": 2}],
    })
    monkeypatch.setattr(
        module,
        "_reconcile_ai_search_migration",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("search scan failed")),
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "search-failure"})
    job = {"id": migration_id, "migration_state": migration_state}

    with pytest.raises(RuntimeError, match="search scan failed"):
        module._run_data_management_migration_reconciliation(
            {},
            {"migration_mode": "new_only"},
            job,
            migration_state,
            create_migration_provenance_context(migration_id=migration_id),
            object(),
            preview_snapshot={"estimated_outcomes": {}},
            migration_artifacts=[],
        )

    result = job["migration_state"]["resources"]["reconciliation:cutover"]["result"]
    assert result["readiness"] == "not_ready"
    assert result["services_completed"] == 1
    assert result["matched_count"] == 2
    assert result["services"][0]["service"] == "cosmos"


def test_deletion_plan_flush_failure_still_fails_resource_with_evidence(monkeypatch):
    """Record reconciliation failure even when candidate-plan persistence fails."""
    migration_id = "88888888-8888-8888-8888-888888888888"
    module = load_data_management_module(
        monkeypatch,
        FakeCosmosContainer([]),
        FakeSearchClient([]),
    )
    monkeypatch.setattr(module, "_assert_migration_job_lease", lambda *_args, **_kwargs: None)

    def cosmos_report(*_args, deletion_candidate_callback=None, **_kwargs):
        deletion_candidate_callback({
            "service": "cosmos",
            "target_type": "users",
            "container_name": "documents",
            "document_id": "candidate",
            "partition_key": "candidate",
            "target_etag": "etag-candidate",
        })
        return {
            "service": "cosmos",
            "destination_only_owned_count": 1,
            "delete_candidate_count": 1,
            "resources": [],
        }

    monkeypatch.setattr(module, "_reconcile_cosmos_migration", cosmos_report)
    monkeypatch.setattr(
        module,
        "_write_mirror_deletion_candidate_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("plan write failed")),
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "plan-failure"})
    job = {"id": migration_id, "migration_state": migration_state}

    with pytest.raises(RuntimeError, match="plan write failed"):
        module._run_data_management_migration_reconciliation(
            {},
            {"migration_mode": "mirror_with_deletions", "mirror_deletions_confirmed": True},
            job,
            migration_state,
            create_migration_provenance_context(migration_id=migration_id),
            object(),
            preview_snapshot={"estimated_outcomes": {}},
            migration_artifacts=[],
        )

    resource = job["migration_state"]["resources"]["reconciliation:cutover"]
    assert resource["status"] == "failed"
    assert resource["last_error"] == "plan write failed"
    assert resource["result"]["readiness"] == "not_ready"
    assert resource["result"]["services_completed"] == 1
    assert resource["result"]["persistence_warnings"]