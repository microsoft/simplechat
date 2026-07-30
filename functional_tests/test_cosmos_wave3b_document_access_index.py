# test_cosmos_wave3b_document_access_index.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 3B document access index write-through.
Version: 0.250.047
Implemented in: 0.250.009
Default read enablement updated in: 0.250.027
Redis DAI cache invalidation updated in: 0.250.029
Repair backlog state cleanup updated in: 0.250.030

This test ensures document_access_index projection rows are deterministic,
scope-partitioned, clean up stale access rows, and fail open with repair state
when projection writes are unavailable.
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
    def __init__(self, fail_upsert=False):
        self.items = {}
        self.fail_upsert = fail_upsert

    def _partition_key_for_body(self, body):
        return body.get("scope_key") or body.get("id")

    def upsert_item(self, body):
        if self.fail_upsert:
            raise RuntimeError("projection container unavailable")
        partition_key = self._partition_key_for_body(body)
        self.items[(partition_key, body["id"])] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def delete_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[key]

    def read_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[key])

    def query_items(self, query, parameters=None, enable_cross_partition_query=False, **kwargs):
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in list(parameters or [])
        }
        document_id = parameter_map.get("@document_id")
        source_scope = parameter_map.get("@source_scope")
        item_type = parameter_map.get("@type")
        results = []
        for (scope_key, item_id), item in self.items.items():
            if item_type is not None and item.get("type") != item_type:
                continue
            if source_scope is not None and item.get("source_scope") != source_scope:
                continue
            if document_id is not None and item.get("source_document_id") != document_id:
                continue
            results.append({"id": item_id, "scope_key": scope_key})
        return results


class FakeRepairBacklogStateWriteFailContainer(FakeCosmosContainer):
    def upsert_item(self, body):
        if body.get("type") == "document_access_index_repair_backlog_state":
            raise RuntimeError("state write throttled")
        return super().upsert_item(body)


@contextmanager
def _load_document_access_index_module(index_container=None, settings_container=None, settings=None):
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

    index_container = index_container or FakeCosmosContainer()
    settings_container = settings_container or FakeCosmosContainer()
    fake_config = types.ModuleType("config")
    fake_config.cosmos_document_access_index_container = index_container
    fake_config.cosmos_settings_container = settings_container
    fake_config.cosmos_user_documents_container = FakeCosmosContainer()
    fake_config.cosmos_user_documents_container_name = "documents"
    fake_config.cosmos_group_documents_container = FakeCosmosContainer()
    fake_config.cosmos_group_documents_container_name = "group_documents"
    fake_config.cosmos_public_documents_container = FakeCosmosContainer()
    fake_config.cosmos_public_documents_container_name = "public_documents"
    fake_config.cosmos_groups_container = FakeCosmosContainer()
    fake_config.cosmos_public_workspaces_container = FakeCosmosContainer()
    fake_config.cosmos_user_settings_container = FakeCosmosContainer()
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: settings or {
        "enable_document_access_index_container": True,
        "enable_document_access_index_write_through": True,
        "enable_document_access_index_reads": True,
        "enable_document_access_index_shadow_validation": False,
        "enable_startup_document_access_index_backfill": False,
    }
    sys.modules["functions_settings"] = fake_settings

    try:
        yield importlib.import_module("functions_document_access_index"), index_container, settings_container
    finally:
        for module_name in [
            "config",
            "functions_appinsights",
            "functions_settings",
            "functions_document_access_index",
        ]:
            sys.modules.pop(module_name, None)
        sys.modules.update(original_modules)


def _personal_document(shared_user_ids=None):
    return {
        "id": "doc-1",
        "type": "document_metadata",
        "user_id": "owner-1",
        "file_name": "report.pdf",
        "title": "Report",
        "version": 2,
        "revision_family_id": "family-1",
        "is_current_version": True,
        "search_visibility_state": "active",
        "status": "Processing complete",
        "percentage_complete": 100,
        "last_updated": "2026-06-30T10:00:00Z",
        "shared_user_ids": list(shared_user_ids or []),
    }


def test_projection_rows_are_scope_partitioned_and_deterministic():
    """Personal owner and shared-user rows should share user scope partitions."""
    with _load_document_access_index_module() as (indexing, _index_container, _settings_container):
        rows = indexing.build_document_access_index_rows(
            _personal_document(["user-2,not_approved", "user-3,approved"])
        )

    rows_by_scope = {row["scope_key"]: row for row in rows}
    assert set(rows_by_scope) == {"user:owner-1", "user:user-2", "user:user-3"}
    assert rows_by_scope["user:owner-1"]["access_role"] == "owner"
    assert rows_by_scope["user:user-2"]["approval_status"] == "not_approved"
    assert rows_by_scope["user:user-2"]["access_granted"] is False
    assert rows_by_scope["user:user-3"]["access_granted"] is True
    assert all(row["id"].endswith(":2") for row in rows)


def test_projection_share_collisions_prefer_least_privilege():
    """Duplicate explicit statuses and legacy bare shares prefer least privilege."""
    with _load_document_access_index_module() as (indexing, _index_container, _settings_container):
        rows = indexing.build_document_access_index_rows(
            _personal_document(["user-2,approved", "user-2,not_approved", "legacy-user"])
        )

    rows_by_scope = {row["scope_key"]: row for row in rows}
    assert rows_by_scope["user:user-2"]["approval_status"] == "not_approved"
    assert rows_by_scope["user:user-2"]["access_granted"] is False
    assert rows_by_scope["user:legacy-user"]["approval_status"] == "not_approved"
    assert rows_by_scope["user:legacy-user"]["access_granted"] is False


def test_projection_sync_removes_stale_share_rows():
    """Sync should remove rows for users no longer present in source sharing fields."""
    with _load_document_access_index_module() as (indexing, index_container, _settings_container):
        indexing.sync_document_access_index_for_document(_personal_document(["user-2,approved"]))
        assert ("user:user-2", "dai:user:user-2:personal:doc-1:2") in index_container.items

        result = indexing.sync_document_access_index_for_document(_personal_document([]))

    assert result["deleted_count"] == 1
    assert ("user:user-2", "dai:user:user-2:personal:doc-1:2") not in index_container.items
    assert ("user:owner-1", "dai:user:owner-1:personal:doc-1:2") in index_container.items


def test_projection_delete_removes_all_source_rows():
    """Delete synchronization should remove every projection row for the source document."""
    with _load_document_access_index_module() as (indexing, index_container, _settings_container):
        document = _personal_document(["user-2,approved", "user-3,approved"])
        indexing.sync_document_access_index_for_document(document)
        result = indexing.delete_document_access_index_for_document(document)

    assert result["deleted_count"] == 3
    assert index_container.items == {}


def test_projection_failure_records_repair_state_without_raising():
    """Fail-open wrapper should record repair state when projection writes fail."""
    with _load_document_access_index_module(index_container=FakeCosmosContainer(fail_upsert=True)) as (
        indexing,
        _index_container,
        settings_container,
    ):
        result = indexing.sync_document_access_index_for_document_fail_open(
            _personal_document(["user-2,approved"]),
            operation="test_failure",
        )

    assert result["success"] is False
    repair_docs = [
        item
        for item in settings_container.items.values()
        if item.get("type") == "document_access_index_repair"
    ]
    assert len(repair_docs) == 1
    assert repair_docs[0]["source_document_id"] == "doc-1"
    assert repair_docs[0]["operation"] == "test_failure"
    repair_backlog_state = settings_container.items.get((
        "document_access_index_repair_backlog_state",
        "document_access_index_repair_backlog_state",
    ))
    assert repair_backlog_state["has_repair_backlog"] is True


def test_projection_failure_records_repair_doc_when_backlog_state_write_fails():
    """Backlog state write failures must not suppress source repair records."""
    settings_container = FakeRepairBacklogStateWriteFailContainer()
    with _load_document_access_index_module(
        index_container=FakeCosmosContainer(fail_upsert=True),
        settings_container=settings_container,
    ) as (
        indexing,
        _index_container,
        _settings_container,
    ):
        result = indexing.sync_document_access_index_for_document_fail_open(
            _personal_document(["user-2,approved"]),
            operation="test_state_failure",
        )

    repair_docs = [
        item
        for item in settings_container.items.values()
        if item.get("type") == "document_access_index_repair"
    ]
    repair_backlog_states = [
        item
        for item in settings_container.items.values()
        if item.get("type") == "document_access_index_repair_backlog_state"
    ]
    assert result["success"] is False
    assert len(repair_docs) == 1
    assert repair_docs[0]["operation"] == "test_state_failure"
    assert repair_backlog_states == []


def test_projection_repair_clear_removes_stale_backlog_state_when_false_write_fails():
    """A successful repair clear should not leave a stale true backlog state behind."""
    settings_container = FakeRepairBacklogStateWriteFailContainer()
    with _load_document_access_index_module(settings_container=settings_container) as (
        indexing,
        _index_container,
        _settings_container,
    ):
        document = _personal_document(["user-2,approved"])
        source_scope = "personal"
        repair_doc_id = indexing._repair_document_id(source_scope, document["id"])
        state_doc_id = indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID
        settings_container.items[(repair_doc_id, repair_doc_id)] = {
            "id": repair_doc_id,
            "type": "document_access_index_repair",
            "status": "repair_required",
            "operation": "stale_state_test",
            "source_scope": source_scope,
            "source_document_id": document["id"],
        }
        settings_container.items[(state_doc_id, state_doc_id)] = {
            "id": state_doc_id,
            "type": "document_access_index_repair_backlog_state",
            "has_repair_backlog": True,
            "schema_version": indexing.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        }

        result = indexing.sync_document_access_index_for_document(document, force=True)

    assert result["success"] is True
    assert (repair_doc_id, repair_doc_id) not in settings_container.items
    assert (state_doc_id, state_doc_id) not in settings_container.items


def test_wave3b_container_flags_and_hooks_are_wired():
    """Contract test for Wave 3B config, settings, and write-through hook markers."""
    config_source = open(os.path.join(SINGLE_APP_DIR, "config.py"), "r", encoding="utf-8").read()
    settings_source = open(os.path.join(SINGLE_APP_DIR, "functions_settings.py"), "r", encoding="utf-8").read()
    documents_source = open(os.path.join(SINGLE_APP_DIR, "functions_documents.py"), "r", encoding="utf-8").read()
    personal_route_source = open(os.path.join(SINGLE_APP_DIR, "route_backend_documents.py"), "r", encoding="utf-8").read()

    assert "cosmos_document_access_index_container_name = \"document_access_index\"" in config_source
    assert "PartitionKey(path=\"/scope_key\")" in config_source
    assert "'enable_document_access_index_container': True" in settings_source
    assert "'enable_document_access_index_write_through': True" in settings_source
    assert "'enable_document_access_index_reads': True" in settings_source
    assert "'enable_startup_document_access_index_backfill': True" in settings_source
    for marker in [
        "operation='document_created'",
        "operation='document_updated'",
        "operation='document_deleted'",
        "operation='document_revision_promoted'",
        "operation='document_shared_with_user'",
        "operation='document_unshared_from_user'",
        "operation='document_shared_with_group'",
        "operation='document_unshared_from_group'",
    ]:
        assert marker in documents_source
    assert "operation='document_share_approved'" in personal_route_source


if __name__ == "__main__":
    tests = [
        test_projection_rows_are_scope_partitioned_and_deterministic,
        test_projection_share_collisions_prefer_least_privilege,
        test_projection_sync_removes_stale_share_rows,
        test_projection_delete_removes_all_source_rows,
        test_projection_failure_records_repair_state_without_raising,
        test_projection_failure_records_repair_doc_when_backlog_state_write_fails,
        test_projection_repair_clear_removes_stale_backlog_state_when_false_write_fails,
        test_wave3b_container_flags_and_hooks_are_wired,
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
