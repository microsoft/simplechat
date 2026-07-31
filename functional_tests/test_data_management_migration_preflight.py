# test_data_management_migration_preflight.py
"""
Functional test for Data Management migration destination preflight.
Version: 0.250.071
Implemented in: 0.250.075
Updated in: 0.250.071

This test ensures migration preflight proves target Search and Blob data-plane
write/read/delete access and rejects incompatible Cosmos partition keys.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))


class FakeJobContainer:
    """Provide the minimal persistence surface required by module import."""

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def __init__(self):
        self.items = {}

    def create_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def read_item(self, item, partition_key):
        assert item == partition_key
        return copy.deepcopy(self.items[item])

    def delete_item(self, item, partition_key):
        assert item == partition_key
        self.items.pop(item, None)

class FakeSearchClient:
    """Record Search preflight write/read/delete probes."""

    def __init__(self, endpoint=""):
        self.documents = {}
        self.upload_count = 0
        self.delete_count = 0
        self._endpoint = endpoint

    def search(self, **kwargs):
        filter_text = str(kwargs.get("filter") or "")
        if "id eq" not in filter_text:
            return iter([{"id": "source-document"}])
        matching = [
            {"id": document_id}
            for document_id in self.documents
            if document_id in filter_text
        ]
        return iter(matching)

    def upload_documents(self, documents, **_kwargs):
        self.upload_count += 1
        for document in documents:
            self.documents[document["id"]] = copy.deepcopy(document)
        return [{"succeeded": True} for _ in documents]

    def delete_documents(self, documents, **_kwargs):
        self.delete_count += 1
        for document in documents:
            self.documents.pop(document["id"], None)
        return [{"succeeded": True} for _ in documents]


class FakeContainerClient:
    """Provide a lazy source Blob listing for access preflight."""

    def list_blobs(self):
        return iter([])


class FakeBlobClient:
    """Record target Blob preflight writes, reads, and cleanup."""

    def __init__(self):
        self.uploaded = False
        self.read = False
        self.deleted = False

    def upload_blob(self, **_kwargs):
        self.uploaded = True

    def get_blob_properties(self):
        self.read = True
        return types.SimpleNamespace(metadata={})

    def delete_blob(self):
        self.deleted = True


class FakeBlobService:
    """Expose source/target blob client APIs used by preflight."""

    def __init__(self):
        self.created_containers = []
        self.blob_clients = []

    def get_container_client(self, _container_name):
        return FakeContainerClient()

    def create_container(self, container_name):
        self.created_containers.append(container_name)

    def get_blob_client(self, **_kwargs):
        blob_client = FakeBlobClient()
        self.blob_clients.append(blob_client)
        return blob_client


class FakeTargetDatabase:
    """Return a compatible target job container for Search write-gate preflight."""

    def __init__(self):
        self.containers = {}

    def create_container_if_not_exists(self, id=None, **_kwargs):
        container = self.containers.setdefault(id, FakeJobContainer())
        return container


def load_data_management_module(monkeypatch, source_search_client, job_container):
    """Load the production module with lightweight dependency fakes."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {"search_client_user": source_search_client}
    config_module.VERSION = "0.250.075"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
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

    module_name = "data_management_migration_preflight_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_search_and_blob_preflight_probes_destination_data_plane(monkeypatch):
    """Validate Search and Blob preflight creates, reads, and removes probes."""
    source_search = FakeSearchClient()
    target_search = FakeSearchClient()
    source_blob = FakeBlobService()
    target_blob = FakeBlobService()
    module = load_data_management_module(monkeypatch, source_search, FakeJobContainer())
    monkeypatch.setattr(module, "_ensure_target_search_index", lambda *_args, **_kwargs: "ready")
    monkeypatch.setattr(module, "_get_target_search_client", lambda *_args, **_kwargs: target_search)
    monkeypatch.setattr(module, "_get_target_cosmos_database", lambda _settings: FakeTargetDatabase())
    monkeypatch.setattr(module, "_get_source_blob_service_client", lambda: source_blob)
    monkeypatch.setattr(module, "_get_target_enhanced_citations_blob_client", lambda _settings: target_blob)

    migration_plan = {
        "users": {"mode": "selected", "ids": ["user-1"], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "target_ai_search_writes_frozen": True,
        "include_source_blobs": True,
    }

    search_result = module._preflight_target_ai_search_migration_access({}, migration_plan)
    blob_result = module._preflight_target_blob_migration_access({}, migration_plan)

    assert search_result["index_count"] == 1
    assert search_result["target_search_write_gate_verified"] is True
    assert target_search.upload_count == 1
    assert target_search.delete_count == 1
    assert target_search.documents == {}
    assert blob_result["container_count"] == 1
    assert target_blob.created_containers == ["user-documents"]
    assert len(target_blob.blob_clients) == 1
    assert target_blob.blob_clients[0].uploaded is True
    assert target_blob.blob_clients[0].read is True
    assert target_blob.blob_clients[0].deleted is True


def test_search_preflight_requires_frozen_distinct_target(monkeypatch):
    """Reject Search migration writes without an explicit freeze or on the source service."""
    source_search = FakeSearchClient("https://source.search.windows.net")
    module = load_data_management_module(monkeypatch, source_search, FakeJobContainer())
    migration_plan = {
        "users": {"mode": "selected", "ids": ["user-1"], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
    }

    try:
        module._preflight_target_ai_search_migration_access(
            {"target_ai_search_endpoint": "https://target.search.windows.net"},
            migration_plan,
        )
    except module.DataManagementSettingsValidationError as exc:
        assert "writers are frozen" in str(exc)
    else:
        raise AssertionError("Search migration proceeded without a target-write freeze confirmation.")

    migration_plan["target_ai_search_writes_frozen"] = True
    try:
        module._preflight_target_ai_search_migration_access(
            {"target_ai_search_endpoint": "https://source.search.windows.net/"},
            migration_plan,
        )
    except module.DataManagementSettingsValidationError as exc:
        assert "must differ" in str(exc)
    else:
        raise AssertionError("Search migration accepted its source service as a destination.")


def test_partition_key_mismatch_is_rejected_before_data_copy(monkeypatch):
    """Validate a pre-existing incompatible Cosmos container cannot pass preflight."""
    module = load_data_management_module(monkeypatch, FakeSearchClient(), FakeJobContainer())

    class IncompatibleContainer:
        def read(self):
            return {"partitionKey": {"paths": ["/wrong"]}}

    try:
        module._validate_target_cosmos_container_partition_key(
            IncompatibleContainer(),
            "documents",
            "/id",
        )
    except module.DataManagementSettingsValidationError as exc:
        assert "partition key" in str(exc).lower()
    else:
        raise AssertionError("An incompatible target Cosmos partition key was accepted.")