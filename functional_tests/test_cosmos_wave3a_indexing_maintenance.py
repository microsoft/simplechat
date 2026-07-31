# test_cosmos_wave3a_indexing_maintenance.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 3A indexing policy maintenance.
Version: 0.250.104
Implemented in: 0.250.008
Maintenance cleanup integration updated in: 0.250.038
Manual admin apply override updated in: 0.250.039
Data Management history pagination index updated in: 0.250.103
CodeQL remediation version alignment updated in: 0.250.104

This test ensures expected Cosmos indexing policies can be compared, safely
merged, and invoked through the app maintenance framework without live Azure
resources.
"""

import copy
import importlib
import os
import sys
import types
from contextlib import contextmanager


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakeCosmosContainer:
    def __init__(self, container_name, indexing_policy=None, default_ttl=None, full_text_policy=None):
        self.container_name = container_name
        self.items = {}
        self._etag_counter = 0
        self.container_properties = {
            "id": container_name,
            "_etag": f"{container_name}-etag-0",
            "indexingPolicy": copy.deepcopy(indexing_policy or {
                "indexingMode": "consistent",
                "automatic": True,
                "includedPaths": [{"path": "/*"}],
                "excludedPaths": [{"path": "/\"_etag\"/?"}],
                "compositeIndexes": [],
            }),
        }
        if default_ttl is not None:
            self.container_properties["defaultTtl"] = default_ttl
        if full_text_policy is not None:
            self.container_properties["fullTextPolicy"] = copy.deepcopy(full_text_policy)

    def _copy_with_new_etag(self, body):
        self._etag_counter += 1
        item = copy.deepcopy(body)
        item["_etag"] = f"{self.container_name}-item-etag-{self._etag_counter}"
        return item

    def read(self):
        return copy.deepcopy(self.container_properties)

    def replace_properties(self, kwargs):
        self._etag_counter += 1
        self.container_properties = {
            "id": kwargs["container"],
            "_etag": f"{self.container_name}-etag-{self._etag_counter}",
            "partitionKey": kwargs.get("partition_key"),
            "indexingPolicy": copy.deepcopy(kwargs["indexing_policy"]),
        }
        property_mappings = {
            "default_ttl": "defaultTtl",
            "analytical_storage_ttl": "analyticalStorageTtl",
            "conflict_resolution_policy": "conflictResolutionPolicy",
            "full_text_policy": "fullTextPolicy",
        }
        for call_key, property_key in property_mappings.items():
            if call_key in kwargs:
                self.container_properties[property_key] = copy.deepcopy(kwargs[call_key])
        self.container_properties["_etag"] = f"{self.container_name}-etag-{self._etag_counter}"

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[item])

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
    def __init__(self, containers):
        self.containers = containers
        self.replace_calls = []

    def replace_container(self, **kwargs):
        self.replace_calls.append(copy.deepcopy(kwargs))
        container_name = kwargs["container"]
        self.containers[container_name].replace_properties(kwargs)
        return self.containers[container_name]


def _build_fake_environment():
    containers = {
        "conversations": FakeCosmosContainer("conversations"),
        "messages": FakeCosmosContainer("messages"),
        "data_management_jobs": FakeCosmosContainer("data_management_jobs"),
        "collaboration_messages": FakeCosmosContainer("collaboration_messages"),
        "document_access_index": FakeCosmosContainer("document_access_index"),
        "documents": FakeCosmosContainer(
            "documents",
            indexing_policy={
                "indexingMode": "consistent",
                "automatic": True,
                "includedPaths": [{"path": "/*"}, {"path": "/id/?"}],
                "excludedPaths": [{"path": "/large_unused_payload/*"}],
                "compositeIndexes": [[{"path": "/existing", "order": "ascending"}]],
            },
            default_ttl=-1,
            full_text_policy={
                "defaultLanguage": "en-US",
                "fullTextPaths": [{"path": "/content", "language": "en-US"}],
            },
        ),
        "group_documents": FakeCosmosContainer("group_documents"),
        "public_documents": FakeCosmosContainer("public_documents"),
        "groups": FakeCosmosContainer("groups"),
        "public_workspaces": FakeCosmosContainer("public_workspaces"),
        "user_settings": FakeCosmosContainer("user_settings"),
    }
    database = FakeCosmosDatabase(containers)
    settings_container = FakeCosmosContainer("settings")
    governance_container = FakeCosmosContainer("governance_policies")
    return containers, database, settings_container, governance_container


@contextmanager
def _load_wave3_modules():
    original_modules = {}
    module_names = [
        "config",
        "functions_appinsights",
        "functions_group",
        "functions_shared_cache",
        "functions_cosmos_stale_cleanup",
        "functions_cosmos_indexing",
        "functions_document_access_index",
        "functions_app_maintenance",
        "functions_settings",
    ]
    for module_name in module_names:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]
            del sys.modules[module_name]

    containers, database, settings_container, governance_container = _build_fake_environment()
    fake_config = types.ModuleType("config")
    fake_config.VERSION = "0.250.039"
    fake_config.cosmos_database = database
    fake_config.cosmos_settings_container = settings_container
    fake_config.cosmos_governance_policies_container = governance_container
    fake_config.cosmos_conversations_container = containers["conversations"]
    fake_config.cosmos_conversations_container_name = "conversations"
    fake_config.cosmos_messages_container = containers["messages"]
    fake_config.cosmos_messages_container_name = "messages"
    fake_config.cosmos_data_management_jobs_container = containers["data_management_jobs"]
    fake_config.cosmos_data_management_jobs_container_name = "data_management_jobs"
    fake_config.cosmos_collaboration_messages_container = containers["collaboration_messages"]
    fake_config.cosmos_collaboration_messages_container_name = "collaboration_messages"
    fake_config.cosmos_user_documents_container = containers["documents"]
    fake_config.cosmos_user_documents_container_name = "documents"
    fake_config.cosmos_group_documents_container = containers["group_documents"]
    fake_config.cosmos_group_documents_container_name = "group_documents"
    fake_config.cosmos_public_documents_container = containers["public_documents"]
    fake_config.cosmos_public_documents_container_name = "public_documents"
    fake_config.cosmos_document_access_index_container = containers["document_access_index"]
    fake_config.cosmos_groups_container = containers["groups"]
    fake_config.cosmos_public_workspaces_container = containers["public_workspaces"]
    fake_config.cosmos_user_settings_container = containers["user_settings"]
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    fake_appinsights.debug_print = lambda *args, **kwargs: None
    fake_appinsights.is_debug_enabled = lambda: False
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_group = types.ModuleType("functions_group")
    fake_group.find_group_by_id = lambda group_id: None
    sys.modules["functions_group"] = fake_group

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: {}
    sys.modules["functions_settings"] = fake_settings

    try:
        indexing = importlib.import_module("functions_cosmos_indexing")
        maintenance = importlib.import_module("functions_app_maintenance")
        yield indexing, maintenance, database, containers
    finally:
        for module_name in module_names:
            sys.modules.pop(module_name, None)
        sys.modules.update(original_modules)


def _canonical_composite(index):
    return tuple((path["path"], path["order"]) for path in index)


def test_indexing_policy_report_is_read_only():
    """Report-only mode should find missing indexes without replacing containers."""
    with _load_wave3_modules() as (indexing, _maintenance, database, _containers):
        report = indexing.run_cosmos_indexing_policy_maintenance(apply_changes=False)

    assert report["success"] is True
    assert report["mode"] == "report_only"
    assert report["containers_missing_expected_indexes"] > 0
    assert report["updated_container_count"] == 0
    assert database.replace_calls == []
    data_management_definition = next(
        definition
        for definition in indexing.COSMOS_INDEXING_POLICY_DEFINITIONS
        if definition["container_name"] == "data_management_jobs"
    )
    assert indexing.COSMOS_INDEXING_POLICY_DEFINITION_VERSION == 2
    assert data_management_definition["expected_policy"]["compositeIndexes"] == [[
        {"path": "/created_at", "order": "descending"},
        {"path": "/id", "order": "descending"},
    ]]


def test_indexing_policy_apply_merges_without_removing_existing_paths():
    """Apply mode should add missing composites while preserving current policy paths."""
    with _load_wave3_modules() as (indexing, _maintenance, database, containers):
        report = indexing.run_cosmos_indexing_policy_maintenance(apply_changes=True)
        documents_policy = containers["documents"].container_properties["indexingPolicy"]
        documents_call = next(call for call in database.replace_calls if call["container"] == "documents")

    assert report["success"] is True
    assert report["updated_container_count"] == len(indexing.COSMOS_INDEXING_POLICY_DEFINITIONS)
    assert documents_policy["includedPaths"] == [{"path": "/*"}, {"path": "/id/?"}]
    assert documents_policy["excludedPaths"] == [{"path": "/large_unused_payload/*"}]
    assert _canonical_composite([{"path": "/existing", "order": "ascending"}]) in {
        _canonical_composite(index)
        for index in documents_policy["compositeIndexes"]
    }
    assert documents_call["default_ttl"] == -1
    assert documents_call["full_text_policy"] == {
        "defaultLanguage": "en-US",
        "fullTextPaths": [{"path": "/content", "language": "en-US"}],
    }
    assert containers["documents"].container_properties["fullTextPolicy"] == documents_call["full_text_policy"]


def test_app_maintenance_runs_indexing_policy_step():
    """App maintenance should include the Wave 3A indexing policy maintenance step."""
    with _load_wave3_modules() as (indexing, maintenance, database, _containers):
        result = maintenance.run_app_maintenance_once(
            triggered_by="test",
            requested_by="tester@example.com",
            settings={indexing.COSMOS_INDEXING_POLICY_APPLY_SETTING: True},
        )
        status = maintenance.get_app_maintenance_status(
            settings={indexing.COSMOS_INDEXING_POLICY_APPLY_SETTING: True},
        )

    indexing_step = next(step for step in result["steps"] if step["name"] == "cosmos_indexing_policy_maintenance")
    assert result["success"] is True
    assert indexing_step["status"] == "succeeded"
    assert indexing_step["results"]["mode"] == "apply"
    assert database.replace_calls
    assert status["cosmos_indexing_policies"]["mode"] == "report_only"
    assert status["stale_cache_cleanup"]["status"] == "skipped_disabled"
    assert status["settings"]["apply_cosmos_indexing_policies"] is True
    assert status["document_access_index_backfill"]["state"]["status"] == "succeeded"


def test_app_maintenance_manual_indexing_apply_override():
    """Manual admin runs should apply indexes when payload override is true."""
    with _load_wave3_modules() as (_indexing, maintenance, database, _containers):
        result = maintenance.run_app_maintenance_once(
            triggered_by="admin_manual",
            requested_by="tester@example.com",
            settings={},
            apply_indexing_policies=True,
            run_document_access_backfill=False,
            run_stale_cache_cleanup=False,
        )

    indexing_step = next(step for step in result["steps"] if step["name"] == "cosmos_indexing_policy_maintenance")
    cleanup_step = next(step for step in result["steps"] if step["name"] == "stale_cache_document_cleanup")
    backfill_step = next(step for step in result["steps"] if step["name"] == "document_access_index_backfill")
    assert result["success"] is True
    assert indexing_step["apply_requested"] is True
    assert indexing_step["results"]["mode"] == "apply"
    assert indexing_step["results"]["updated_container_count"] > 0
    assert database.replace_calls
    assert cleanup_step["run_requested"] is False
    assert cleanup_step["results"]["status"] == "skipped_disabled"
    assert backfill_step["run_requested"] is False


if __name__ == "__main__":
    tests = [
        test_indexing_policy_report_is_read_only,
        test_indexing_policy_apply_merges_without_removing_existing_paths,
        test_app_maintenance_runs_indexing_policy_step,
        test_app_maintenance_manual_indexing_apply_override,
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
