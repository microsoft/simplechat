# test_data_management_migration_manifest.py
"""
Functional test for durable Data Management migration manifests.
Version: 0.250.078
Implemented in: 0.250.077

This test ensures per-item migration outcomes are written in bounded, sanitized
job-scoped batches and can be filtered for retry/export workflows.
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


class FakeManifestContainer:
    """Persist manifest batches and expose Cosmos-like filtered iteration."""

    def __init__(self):
        self.items = []

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
        ])

    def read_item(self, item, partition_key):
        assert item == partition_key
        return {
            "id": item,
            "type": "data_management_job",
            "operation": "migration",
        }


class FakeJobContainer:
    """Provide the unrelated job storage imports required by the module."""

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def read_item(self, item, partition_key):
        assert item == partition_key
        return {
            "id": item,
            "type": "data_management_job",
            "operation": "migration",
        }


def load_data_management_module(monkeypatch, manifest_container):
    """Load the production helpers with lightweight storage dependencies."""
    job_container = FakeJobContainer()
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.077"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = manifest_container
    config_module.cosmos_settings_container = job_container
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

    module_name = "data_management_manifest_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_migration_manifest_batches_sanitize_and_filter(monkeypatch):
    """Write bounded item outcomes and filter retryable failures safely."""
    manifest_container = FakeManifestContainer()
    module = load_data_management_module(monkeypatch, manifest_container)
    module.DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_SIZE = 2
    append_entry, flush_entries = module._create_migration_manifest_writer(
        "11111111-1111-1111-1111-111111111111",
        "source_blobs:selected_documents",
    )

    append_entry({
        "service": "source_blobs",
        "source_identity": "sha256:source-one",
        "destination_identity": "sha256:destination-one",
        "status": "copied",
        "bytes": 10,
        "connection_string": "must-not-persist",
        "_locator": {
            "service": "source_blobs",
            "resource_name": "source_blobs:selected_documents",
            "container_name": "user-documents",
            "blob_name": "source-one.txt",
        },
    })
    append_entry({
        "service": "source_blobs",
        "source_identity": "sha256:source-two",
        "destination_identity": "sha256:destination-two",
        "status": "missing",
        "error": "missing source",
        "_locator": {
            "service": "source_blobs",
            "resource_name": "source_blobs:selected_documents",
            "container_name": "user-documents",
            "blob_name": "source-two.txt",
        },
    })
    append_entry({
        "service": "source_blobs",
        "source_identity": "sha256:source-three",
        "destination_identity": "sha256:destination-three",
        "status": "failed",
        "error": "write failed",
    })
    flush_entries()

    assert [item["entry_count"] for item in manifest_container.items] == [2, 1]
    assert all(
        "connection_string" not in entry
        for item in manifest_container.items
        for entry in item["entries"]
    )
    retryable = list(module.iter_data_management_migration_manifest_entries(
        "11111111-1111-1111-1111-111111111111",
        statuses={"missing", "failed"},
    ))
    assert [entry["status"] for entry in retryable] == ["missing", "failed"]
    exported = module.export_data_management_migration_manifest(
        "11111111-1111-1111-1111-111111111111",
        statuses={"missing", "failed"},
    )
    assert exported["entry_count"] == 2
    assert exported["statuses"] == ["failed", "missing"]
    assert "must-not-persist" not in exported["content"]
    assert "source-two.txt" not in exported["content"]
    missing_entry = retryable[0]
    assert missing_entry["item_ref"]
    resolved = module.resolve_data_management_migration_manifest_item(
        "11111111-1111-1111-1111-111111111111",
        missing_entry["item_ref"],
    )
    assert resolved["container_name"] == "user-documents"
    assert resolved["blob_name"] == "source-two.txt"
