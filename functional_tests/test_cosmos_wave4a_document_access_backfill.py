# test_cosmos_wave4a_document_access_backfill.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 4A document access index backfill.
Version: 0.250.011
Implemented in: 0.250.010

This test ensures the document_access_index backfill is resumable,
scope-limited, and can reconcile repair records left by fail-open
write-through operations.
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


class FakePageIterator:
    def __init__(self, items, continuation_token=None, max_item_count=100):
        self.items = list(items)
        self.index = int(continuation_token or 0)
        self.max_item_count = max(int(max_item_count or 100), 1)
        self.continuation_token = None
        self._used = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._used or self.index >= len(self.items):
            raise StopIteration
        start = self.index
        end = min(start + self.max_item_count, len(self.items))
        self._used = True
        self.continuation_token = str(end) if end < len(self.items) else None
        return copy.deepcopy(self.items[start:end])


class FakePagedResult:
    def __init__(self, items, max_item_count=100):
        self.items = list(items)
        self.max_item_count = max_item_count

    def __iter__(self):
        return iter(copy.deepcopy(self.items))

    def by_page(self, continuation_token=None):
        return FakePageIterator(
            self.items,
            continuation_token=continuation_token,
            max_item_count=self.max_item_count,
        )


class FakeCosmosContainer:
    def __init__(self, initial_items=None):
        self.items = {}
        for item in list(initial_items or []):
            self.upsert_item(item)

    def _partition_key_for_body(self, body):
        return body.get("scope_key") or body.get("id")

    def upsert_item(self, body):
        partition_key = self._partition_key_for_body(body)
        self.items[(partition_key, body["id"])] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def read_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[key])

    def delete_item(self, item, partition_key, **kwargs):
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[key]

    def query_items(self, query, parameters=None, enable_cross_partition_query=False, **kwargs):
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in list(parameters or [])
        }
        item_type = parameter_map.get("@type")
        item_status = parameter_map.get("@status")
        document_metadata_type = parameter_map.get("@document_metadata_type")
        source_scope = parameter_map.get("@source_scope")
        document_id = parameter_map.get("@document_id")
        results = []
        for item in self.items.values():
            if item_type is not None and item.get("type") != item_type:
                continue
            if item_status is not None and item.get("status") != item_status:
                continue
            if document_metadata_type is not None and item.get("type") not in (None, document_metadata_type):
                continue
            if source_scope is not None and item.get("source_scope") != source_scope:
                continue
            if document_id is not None and item.get("source_document_id") != document_id:
                continue
            results.append(copy.deepcopy(item))
        results.sort(key=lambda item: item.get("id", ""))
        return FakePagedResult(results, max_item_count=kwargs.get("max_item_count", 100))


def _document(document_id, owner_id):
    return {
        "id": document_id,
        "type": "document_metadata",
        "user_id": owner_id,
        "file_name": f"{document_id}.pdf",
        "version": 1,
        "is_current_version": True,
        "search_visibility_state": "active",
        "shared_user_ids": [],
    }


@contextmanager
def _load_document_access_index_module(personal_documents=None):
    original_modules = {}
    for module_name in [
        "config",
        "functions_appinsights",
        "functions_settings",
        "functions_document_access_index",
    ]:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]
            del sys.modules[module_name]

    index_container = FakeCosmosContainer()
    settings_container = FakeCosmosContainer()
    personal_container = FakeCosmosContainer(personal_documents)
    group_container = FakeCosmosContainer()
    public_container = FakeCosmosContainer()

    fake_config = types.ModuleType("config")
    fake_config.cosmos_document_access_index_container = index_container
    fake_config.cosmos_settings_container = settings_container
    fake_config.cosmos_user_documents_container = personal_container
    fake_config.cosmos_user_documents_container_name = "documents"
    fake_config.cosmos_group_documents_container = group_container
    fake_config.cosmos_group_documents_container_name = "group_documents"
    fake_config.cosmos_public_documents_container = public_container
    fake_config.cosmos_public_documents_container_name = "public_documents"
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: {
        "enable_document_access_index_container": True,
        "enable_document_access_index_write_through": True,
        "enable_document_access_index_reads": False,
        "enable_document_access_index_shadow_validation": False,
        "enable_startup_document_access_index_backfill": True,
        "document_access_index_backfill_batch_size": 1,
        "document_access_index_repair_batch_size": 10,
    }
    sys.modules["functions_settings"] = fake_settings

    try:
        yield (
            importlib.import_module("functions_document_access_index"),
            index_container,
            settings_container,
            personal_container,
        )
    finally:
        for module_name in [
            "config",
            "functions_appinsights",
            "functions_settings",
            "functions_document_access_index",
        ]:
            sys.modules.pop(module_name, None)
        sys.modules.update(original_modules)


def test_backfill_batches_are_resumable_and_complete():
    """Backfill should checkpoint continuation tokens between bounded batches."""
    source_documents = [
        _document("doc-1", "owner-1"),
        _document("doc-2", "owner-2"),
    ]
    with _load_document_access_index_module(source_documents) as (
        indexing,
        index_container,
        _settings_container,
        _personal_container,
    ):
        first_result = indexing.run_document_access_index_backfill_once(
            batch_size=1,
            source_scopes=["personal"],
            reset=True,
            force=True,
        )
        second_result = indexing.run_document_access_index_backfill_once(
            batch_size=1,
            source_scopes=["personal"],
            force=True,
        )

    assert first_result["success"] is True
    assert first_result["status"] == "in_progress"
    assert first_result["processed_count"] == 1
    assert first_result["state"]["continuation_tokens"]["personal"] == "1"
    assert second_result["success"] is True
    assert second_result["status"] == "succeeded"
    assert second_result["processed_count"] == 1
    assert ("user:owner-1", "dai:user:owner-1:personal:doc-1:1") in index_container.items
    assert ("user:owner-2", "dai:user:owner-2:personal:doc-2:1") in index_container.items


def test_repair_reconciliation_cleans_up_failed_delete_projection_rows():
    """Repair reconciliation should clean stale projection rows for delete repairs."""
    with _load_document_access_index_module([]) as (
        indexing,
        index_container,
        settings_container,
        _personal_container,
    ):
        deleted_document = _document("doc-deleted", "owner-1")
        indexing.sync_document_access_index_for_document(deleted_document, force=True)
        settings_container.upsert_item({
            "id": "document_access_projection_repair:personal:doc-deleted",
            "type": "document_access_index_repair",
            "status": "repair_required",
            "operation": "document_deleted",
            "source_scope": "personal",
            "source_document_id": "doc-deleted",
        })

        result = indexing.reconcile_document_access_index_repair_documents(force=True)

    assert result["success"] is True
    assert result["repairs_processed"] == 1
    assert index_container.items == {}
    assert settings_container.items == {}


def test_wave4a_settings_and_maintenance_contract_are_wired():
    """Contract test for Wave 4A defaults and maintenance hook markers."""
    config_source = open(os.path.join(SINGLE_APP_DIR, "config.py"), "r", encoding="utf-8").read()
    settings_source = open(os.path.join(SINGLE_APP_DIR, "functions_settings.py"), "r", encoding="utf-8").read()
    maintenance_source = open(os.path.join(SINGLE_APP_DIR, "functions_app_maintenance.py"), "r", encoding="utf-8").read()
    route_source = open(os.path.join(SINGLE_APP_DIR, "route_backend_settings.py"), "r", encoding="utf-8").read()

    assert 'VERSION = "0.250.011"' in config_source
    assert "'document_access_index_backfill_batch_size': 200" in settings_source
    assert "'document_access_index_repair_batch_size': 100" in settings_source
    assert "run_document_access_index_backfill_maintenance" in maintenance_source
    assert "run_document_access_backfill=payload.get('run_document_access_index_backfill')" in route_source


if __name__ == "__main__":
    tests = [
        test_backfill_batches_are_resumable_and_complete,
        test_repair_reconciliation_cleans_up_failed_delete_projection_rows,
        test_wave4a_settings_and_maintenance_contract_are_wired,
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
