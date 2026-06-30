# test_cosmos_wave1_app_maintenance.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 1 app maintenance framework.
Version: 0.250.005
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

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
            raise FakeCosmosError(409, f"Duplicate item {item_id}")
        self.items[item_id] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def upsert_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)


def _load_maintenance_module(container, governance_container=None):
    fake_config = types.ModuleType("config")
    fake_config.VERSION = "0.250.005"
    fake_config.cosmos_settings_container = container
    fake_config.cosmos_governance_policies_container = governance_container or container
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    sys.modules.pop("functions_shared_cache", None)
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
