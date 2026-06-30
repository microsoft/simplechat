# test_cosmos_wave1_app_maintenance.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 1 app maintenance framework.
Version: 0.250.010
Implemented in: 0.250.005

This test ensures the maintenance runner initializes cache version documents
and records durable run state without requiring live Azure resources.
"""

import copy
import importlib
import os
import sys
import types


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakeCosmosContainer:
    def __init__(self):
        self.items = {}
        self._etag_counter = 0
        self.container_properties = {
            "id": "fake-container",
            "_etag": "container-etag",
            "indexingPolicy": {
                "indexingMode": "consistent",
                "automatic": True,
                "includedPaths": [{"path": "/*"}],
                "excludedPaths": [{"path": "/\"_etag\"/?"}],
                "compositeIndexes": [],
            },
        }

    def _copy_with_new_etag(self, body):
        self._etag_counter += 1
        item = copy.deepcopy(body)
        item["_etag"] = f"etag-{self._etag_counter}"
        return item

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[item])

    def read(self):
        return copy.deepcopy(self.container_properties)

    def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
            raise FakeCosmosError(409, f"Duplicate item {item_id}")
        self.items[item_id] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[item_id])

    def upsert_item(self, body):
        self.items[body["id"]] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[body["id"]])

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        if etag and self.items[item].get("_etag") != etag:
            raise FakeCosmosError(412, f"ETag mismatch for item {item}")
        self.items[item] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[item])

    def delete_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[item]

    def query_items(self, query, parameters=None, enable_cross_partition_query=False, **kwargs):
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in list(parameters or [])
        }
        item_type = parameter_map.get("@type")
        item_status = parameter_map.get("@status")
        document_metadata_type = parameter_map.get("@document_metadata_type")
        results = []
        for item in self.items.values():
            if item_type is not None and item.get("type") != item_type:
                continue
            if item_status is not None and item.get("status") != item_status:
                continue
            if document_metadata_type is not None and item.get("type") not in (None, document_metadata_type):
                continue
            results.append(copy.deepcopy(item))
        return results


class FakeCosmosDatabase:
    def replace_container(self, **kwargs):
        return kwargs


def _load_maintenance_module(container, governance_container=None):
    fake_config = types.ModuleType("config")
    fake_config.VERSION = "0.250.010"
    fake_config.cosmos_settings_container = container
    fake_config.cosmos_governance_policies_container = governance_container or container
    fake_config.cosmos_document_access_index_container = FakeCosmosContainer()
    fake_config.cosmos_database = FakeCosmosDatabase()
    for name in [
        "cosmos_collaboration_messages",
        "cosmos_conversations",
        "cosmos_group_documents",
        "cosmos_messages",
        "cosmos_public_documents",
        "cosmos_user_documents",
    ]:
        setattr(fake_config, f"{name}_container", container)
        setattr(fake_config, f"{name}_container_name", name.replace("cosmos_", ""))
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: {}
    sys.modules["functions_settings"] = fake_settings

    sys.modules.pop("functions_shared_cache", None)
    sys.modules.pop("functions_cosmos_indexing", None)
    sys.modules.pop("functions_document_access_index", None)
    sys.modules.pop("functions_app_maintenance", None)
    return importlib.import_module("functions_app_maintenance")


def test_maintenance_initializes_cache_version_documents():
    """Maintenance should create all Wave 1 cache version documents."""
    container = FakeCosmosContainer()
    governance_container = FakeCosmosContainer()
    maintenance = _load_maintenance_module(container, governance_container=governance_container)

    result = maintenance.run_app_maintenance_once(triggered_by="test", requested_by="tester@example.com")

    assert result["success"] is True
    assert container.items["app_maintenance_state"]["last_status"] == "succeeded"
    backfill_step = next(step for step in result["steps"] if step["name"] == "document_access_index_backfill")
    assert backfill_step["status"] == "succeeded"
    assert backfill_step["results"]["status"] == "skipped_disabled"
    for version_doc in maintenance.CACHE_VERSION_DOCUMENTS:
        target_container = governance_container if version_doc["container"] == "governance_policies" else container
        item = target_container.items[version_doc["id"]]
        assert item["type"] == "cache_version"
        assert item["version"] == 0


def test_maintenance_status_reports_state_and_versions():
    """Maintenance status should include durable state and version doc status."""
    container = FakeCosmosContainer()
    governance_container = FakeCosmosContainer()
    maintenance = _load_maintenance_module(container, governance_container=governance_container)
    maintenance.run_app_maintenance_once(triggered_by="test", requested_by="tester@example.com")

    status = maintenance.get_app_maintenance_status()

    assert status["success"] is True
    assert status["state"]["last_status"] == "succeeded"
    assert len(status["cache_version_documents"]) == len(maintenance.CACHE_VERSION_DOCUMENTS)
    assert status["cosmos_indexing_policies"]["mode"] == "report_only"
    assert status["document_access_index_backfill"]["state"]["status"] == "not_started"
    assert {
        "app_settings_cache_version",
        "governance_cache_version",
        "document_access_index_projection_version",
    }.issubset({item["id"] for item in status["cache_version_documents"]})


def test_maintenance_settings_are_normalized():
    """Maintenance settings should enforce safe minimum intervals and lease values."""
    container = FakeCosmosContainer()
    maintenance = _load_maintenance_module(container)

    settings = maintenance.get_app_maintenance_settings({
        "enable_app_maintenance": True,
        "enable_startup_app_maintenance": True,
        "app_maintenance_check_interval_seconds": 5,
        "app_maintenance_job_lease_seconds": 10,
    })

    assert settings["enabled"] is True
    assert settings["run_on_startup"] is True
    assert settings["check_interval_seconds"] == 60
    assert settings["lease_seconds"] == 60
    assert settings["run_document_access_index_backfill"] is False


if __name__ == "__main__":
    tests = [
        test_maintenance_initializes_cache_version_documents,
        test_maintenance_status_reports_state_and_versions,
        test_maintenance_settings_are_normalized,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
