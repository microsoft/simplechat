# test_cosmos_wave1_app_maintenance.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 1 app maintenance framework.
Version: 0.250.043
Implemented in: 0.250.005
Conversation cache metrics updated in: 0.250.034
Stale cache cleanup maintenance updated in: 0.250.038
DAI version marker TTL hygiene updated in: 0.250.043

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
        if "SELECT VALUE COUNT" in query.upper():
            return [len(results)]
        return results


class FakeCosmosDatabase:
    def replace_container(self, **kwargs):
        return kwargs


def _load_maintenance_module(container, governance_container=None):
    fake_config = types.ModuleType("config")
    fake_config.VERSION = "0.250.043"
    fake_config.cosmos_settings_container = container
    fake_config.cosmos_governance_policies_container = governance_container or container
    fake_config.cosmos_document_access_index_container = FakeCosmosContainer()
    fake_config.cosmos_groups_container = FakeCosmosContainer()
    fake_config.cosmos_public_workspaces_container = FakeCosmosContainer()
    fake_config.cosmos_user_settings_container = FakeCosmosContainer()
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
    fake_appinsights.debug_print = lambda *args, **kwargs: None
    fake_appinsights.is_debug_enabled = lambda: False
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_app_settings_cache = types.ModuleType("app_settings_cache")
    fake_app_settings_cache.get_app_cache_redis_client = lambda: None
    sys.modules["app_settings_cache"] = fake_app_settings_cache

    fake_group = types.ModuleType("functions_group")
    fake_group.find_group_by_id = lambda group_id: None
    sys.modules["functions_group"] = fake_group

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: {}
    sys.modules["functions_settings"] = fake_settings

    sys.modules.pop("functions_shared_cache", None)
    sys.modules.pop("functions_conversation_cache", None)
    sys.modules.pop("functions_cosmos_stale_cleanup", None)
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
    assert backfill_step["results"]["status"] == "completed"
    assert backfill_step["results"]["current_status"]["maintenance"]["next_action"] == "monitor"
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
    assert isinstance(status["shared_cache_metrics"], dict)
    assert "counts" in status["shared_cache_metrics"]
    assert status["conversation_cache"]["settings"]["enabled"] is True
    assert status["conversation_cache"]["settings"]["ttl_seconds"] == 120
    assert "15m" in status["conversation_cache"]["metrics"]["windows"]
    assert status["cosmos_indexing_policies"]["mode"] == "report_only"
    assert status["stale_cache_cleanup"]["status"] == "skipped_disabled"
    assert status["stale_cache_cleanup"]["candidate_count"] == 0
    assert status["document_access_index_backfill"]["state"]["status"] == "succeeded"
    assert status["document_access_index_backfill"]["maintenance"]["auto_maintenance_enabled"] is True
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
    assert settings["run_document_access_index_backfill"] is True
    assert settings["document_access_index_auto_maintenance"] is True
    assert settings["document_access_index_active_interval_seconds"] == 30

    disabled_settings = maintenance.get_app_maintenance_settings({
        "enable_app_maintenance": False,
        "enable_startup_app_maintenance": True,
    })
    startup_disabled_settings = maintenance.get_app_maintenance_settings({
        "enable_app_maintenance": True,
        "enable_startup_app_maintenance": False,
    })

    assert disabled_settings["run_document_access_index_backfill"] is True
    assert disabled_settings["document_access_index_auto_maintenance"] is False
    assert startup_disabled_settings["run_document_access_index_backfill"] is True
    assert startup_disabled_settings["document_access_index_auto_maintenance"] is False


def test_explicit_backfill_skip_is_preserved_for_manual_runs():
    """Manual maintenance calls should be able to skip a backfill batch for that run."""
    container = FakeCosmosContainer()
    maintenance = _load_maintenance_module(container)

    result = maintenance.run_app_maintenance_once(
        triggered_by="test",
        requested_by="tester@example.com",
        run_document_access_backfill=False,
    )

    backfill_step = next(step for step in result["steps"] if step["name"] == "document_access_index_backfill")
    assert backfill_step["run_requested"] is False
    assert backfill_step["results"]["backfill"]["status"] == "skipped_disabled"
    assert backfill_step["results"]["maintenance_pending"] is True


def _seed_stale_cleanup_documents(container):
    container.items["conversation_cache_version:user-1"] = {
        "id": "conversation_cache_version:user-1",
        "type": "cache_version",
        "version": 42,
    }
    container.items["shared_cache_entry:conversation_cache:list:user-1:abc"] = {
        "id": "shared_cache_entry:conversation_cache:list:user-1:abc",
        "type": "shared_cache_entry",
        "namespace": "conversation_cache",
        "key": "list:user-1:abc",
    }
    container.items["shared_cache_entry:chat_bootstrap:user:user-1:abc"] = {
        "id": "shared_cache_entry:chat_bootstrap:user:user-1:abc",
        "type": "shared_cache_entry",
        "namespace": "chat_bootstrap",
        "key": "user:user-1:abc",
    }
    container.items["shared_cache_entry:custom_pages:old"] = {
        "id": "shared_cache_entry:custom_pages:old",
        "type": "shared_cache_entry",
        "namespace": "custom_pages",
        "key": "old",
        "expires_at": "2000-01-01T00:00:00+00:00",
    }
    container.items["shared_cache_entry:custom_pages:active"] = {
        "id": "shared_cache_entry:custom_pages:active",
        "type": "shared_cache_entry",
        "namespace": "custom_pages",
        "key": "active",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    container.items["chat_bootstrap_global_cache_version"] = {
        "id": "chat_bootstrap_global_cache_version",
        "type": "cache_version",
        "version": 10,
    }
    container.items["app_settings"] = {
        "id": "app_settings",
        "type": "app_settings",
    }


def test_stale_cache_cleanup_dry_run_preserves_candidates():
    """Dry-run cleanup should report allowlisted stale docs without deleting them."""
    container = FakeCosmosContainer()
    _seed_stale_cleanup_documents(container)
    maintenance = _load_maintenance_module(container)

    result = maintenance.run_app_maintenance_once(
        triggered_by="test",
        requested_by="tester@example.com",
        run_document_access_backfill=False,
        run_stale_cache_cleanup=True,
        apply_stale_cache_cleanup=False,
    )

    cleanup_step = next(step for step in result["steps"] if step["name"] == "stale_cache_document_cleanup")
    assert result["success"] is True
    assert cleanup_step["run_requested"] is True
    assert cleanup_step["apply_requested"] is False
    assert cleanup_step["results"]["status"] == "dry_run_completed"
    assert cleanup_step["results"]["candidate_count"] == 4
    assert cleanup_step["results"]["deleted_count"] == 0
    assert "conversation_cache_version:user-1" in container.items
    assert "shared_cache_entry:conversation_cache:list:user-1:abc" in container.items
    assert "shared_cache_entry:chat_bootstrap:user:user-1:abc" in container.items
    assert "shared_cache_entry:custom_pages:old" in container.items


def test_stale_cache_cleanup_apply_deletes_only_allowlisted_documents():
    """Apply cleanup should delete stale cache artifacts and preserve active settings docs."""
    container = FakeCosmosContainer()
    _seed_stale_cleanup_documents(container)
    maintenance = _load_maintenance_module(container)

    result = maintenance.run_app_maintenance_once(
        triggered_by="test",
        requested_by="tester@example.com",
        run_document_access_backfill=False,
        run_stale_cache_cleanup=True,
        apply_stale_cache_cleanup=True,
    )

    cleanup_step = next(step for step in result["steps"] if step["name"] == "stale_cache_document_cleanup")
    assert result["success"] is True
    assert cleanup_step["results"]["status"] == "completed"
    assert cleanup_step["results"]["candidate_count"] == 4
    assert cleanup_step["results"]["deleted_count"] == 4
    assert "conversation_cache_version:user-1" not in container.items
    assert "shared_cache_entry:conversation_cache:list:user-1:abc" not in container.items
    assert "shared_cache_entry:chat_bootstrap:user:user-1:abc" not in container.items
    assert "shared_cache_entry:custom_pages:old" not in container.items
    assert "shared_cache_entry:custom_pages:active" in container.items
    assert "chat_bootstrap_global_cache_version" in container.items
    assert "app_settings" in container.items


def test_failed_maintenance_step_sets_top_level_failure():
    """A failed step should not be reported as a fully successful maintenance run."""
    container = FakeCosmosContainer()
    maintenance = _load_maintenance_module(container)
    maintenance.run_document_access_index_backfill_maintenance = lambda **_kwargs: {
        "success": False,
        "status": "failed",
        "error": "simulated failure",
    }

    result = maintenance.run_app_maintenance_once(triggered_by="test", requested_by="tester@example.com")

    backfill_step = next(step for step in result["steps"] if step["name"] == "document_access_index_backfill")
    assert result["success"] is False
    assert result["error"] == "One or more maintenance steps failed."
    assert result["state"]["last_status"] == "succeeded_with_warnings"
    assert backfill_step["status"] == "failed"


if __name__ == "__main__":
    tests = [
        test_maintenance_initializes_cache_version_documents,
        test_maintenance_status_reports_state_and_versions,
        test_maintenance_settings_are_normalized,
        test_explicit_backfill_skip_is_preserved_for_manual_runs,
        test_stale_cache_cleanup_dry_run_preserves_candidates,
        test_stale_cache_cleanup_apply_deletes_only_allowlisted_documents,
        test_failed_maintenance_step_sets_top_level_failure,
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
