# test_cosmos_wave6_document_access_cache.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 6 document access Redis cache.
Version: 0.250.031
Implemented in: 0.250.029
DAI cache TTL default updated in: 0.250.031

This test ensures DAI document-list reads use Redis read-through caching with
scope-version invalidation, bounded TTLs, and safe fallback to direct DAI reads
when Redis cache operations fail.
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
    def __init__(self):
        self.items = {}
        self.queries = []

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

    def delete_item(self, item, partition_key):
        self.items.pop((partition_key, item), None)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        self.queries.append({
            "query": query,
            "partition_key": partition_key,
            "parameters": copy.deepcopy(parameters or []),
        })
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in list(parameters or [])
        }
        item_type = parameter_map.get("@type")
        source_scope = parameter_map.get("@source_scope")
        document_id = parameter_map.get("@document_id")
        projection_version = parameter_map.get("@projection_version")
        status = parameter_map.get("@status")
        access_role = parameter_map.get("@access_role")
        scope_key = parameter_map.get("@scope_key") or partition_key
        results = []

        for (item_partition_key, _item_id), item in self.items.items():
            if scope_key is not None and item_partition_key != scope_key:
                continue
            if item_type is not None and item.get("type") != item_type:
                continue
            if source_scope is not None and item.get("source_scope") != source_scope:
                continue
            if document_id is not None and item.get("source_document_id") != document_id:
                continue
            if projection_version is not None and item.get("projection_version") != projection_version:
                continue
            if status is not None and item.get("status") != status:
                continue
            if access_role is not None and item.get("access_role") != access_role:
                continue
            if (
                "AND c.access_granted = true" in query
                and "OR c.approval_status = @approval_not_approved" not in query
                and item.get("access_granted") is not True
            ):
                continue
            if (
                "OR c.approval_status = @approval_not_approved" in query
                and item.get("access_granted") is not True
                and item.get("approval_status") != parameter_map.get("@approval_not_approved")
            ):
                continue
            if "ARRAY_LENGTH(c.tags) > 0" in query and not item.get("tags"):
                continue
            if "IS_NULL(c.percentage_complete)" in query and item.get("percentage_complete") is not None:
                continue
            results.append(copy.deepcopy(item))

        query_upper = query.upper()
        if "SELECT VALUE COUNT" in query_upper:
            return [len(results)]
        if "SELECT TOP 1 VALUE C.ID" in query_upper:
            return [item["id"] for item in results[:1]]
        return results


class FakeRedisClient:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.get_calls = []
        self.setex_calls = []
        self.incr_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self.values.get(key)

    def setnx(self, key, value):
        if key not in self.values:
            self.values[key] = str(value)
            return True
        return False

    def incr(self, key):
        next_value = int(self.values.get(key) or 0) + 1
        self.values[key] = str(next_value)
        self.incr_calls.append(key)
        return next_value

    def setex(self, key, ttl_seconds, value):
        self.values[key] = value
        self.ttls[key] = ttl_seconds
        self.setex_calls.append((key, ttl_seconds, value))
        return True


class FailingRepairDocumentContainer(FakeCosmosContainer):
    def __init__(self):
        super().__init__()
        self.fail_repair_upserts = False

    def upsert_item(self, body):
        if self.fail_repair_upserts and body.get("type") == "document_access_index_repair":
            raise RuntimeError("repair document write failed")
        return super().upsert_item(body)


class ToggleFailUpsertContainer(FakeCosmosContainer):
    def __init__(self):
        super().__init__()
        self.fail_upsert = False

    def upsert_item(self, body):
        if self.fail_upsert:
            raise RuntimeError("projection upsert failed")
        return super().upsert_item(body)


class FailingRedisClient(FakeRedisClient):
    def get(self, key):
        raise RuntimeError("redis unavailable")


class FailingIncrRedisClient(FakeRedisClient):
    def __init__(self):
        super().__init__()
        self.fail_incr = False

    def incr(self, key):
        if self.fail_incr:
            raise RuntimeError("redis incr unavailable")
        return super().incr(key)


def _settings():
    return {
        "enable_document_access_index_container": True,
        "enable_document_access_index_write_through": True,
        "enable_document_access_index_reads": True,
        "enable_document_access_index_shadow_validation": False,
        "enable_startup_document_access_index_backfill": True,
        "enable_document_access_index_cache": True,
        "document_access_index_cache_ttl_seconds": 900,
    }


def _succeeded_backfill_state():
    return {
        "id": "document_access_index_backfill_state",
        "type": "document_access_index_backfill_state",
        "status": "succeeded",
        "source_scopes": ["personal", "group", "public"],
        "completed_source_scopes": ["personal", "group", "public"],
        "total_documents_processed": 1,
        "total_documents_failed": 0,
        "schema_version": 2,
    }


def _document(document_id, owner_id, **overrides):
    document = {
        "id": document_id,
        "type": "document_metadata",
        "user_id": owner_id,
        "file_name": f"{document_id}.pdf",
        "title": document_id.title(),
        "version": 1,
        "revision_family_id": document_id,
        "is_current_version": True,
        "search_visibility_state": "active",
        "status": "Processing complete",
        "percentage_complete": 100,
        "tags": ["wave6", "cosmos"],
        "shared_user_ids": [],
        "_ts": 12345,
    }
    document.update(overrides)
    return document


@contextmanager
def _load_document_access_index_module(redis_client, settings=None, settings_container=None, index_container=None):
    original_modules = {}
    for module_name in [
        "app_settings_cache",
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

    fake_app_settings_cache = types.ModuleType("app_settings_cache")
    fake_app_settings_cache.get_app_cache_redis_client = lambda: redis_client
    sys.modules["app_settings_cache"] = fake_app_settings_cache

    fake_config = types.ModuleType("config")
    fake_config.cosmos_document_access_index_container = index_container
    fake_config.cosmos_settings_container = settings_container
    fake_config.cosmos_user_documents_container = FakeCosmosContainer()
    fake_config.cosmos_user_documents_container_name = "documents"
    fake_config.cosmos_group_documents_container = FakeCosmosContainer()
    fake_config.cosmos_group_documents_container_name = "group_documents"
    fake_config.cosmos_public_documents_container = FakeCosmosContainer()
    fake_config.cosmos_public_documents_container_name = "public_documents"
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: settings or _settings()
    sys.modules["functions_settings"] = fake_settings

    try:
        yield importlib.import_module("functions_document_access_index"), index_container, settings_container
    finally:
        for module_name in [
            "app_settings_cache",
            "config",
            "functions_appinsights",
            "functions_settings",
            "functions_document_access_index",
        ]:
            sys.modules.pop(module_name, None)
        sys.modules.update(original_modules)


def _prepare_ready_projection(indexing, index_container, settings_container, document=None):
    settings_container.upsert_item(_succeeded_backfill_state())
    indexing.sync_document_access_index_for_document(
        document or _document("doc-1", "owner-1"),
        operation="test_projection_seed",
        force=True,
    )
    index_container.queries.clear()


def test_document_list_cache_hit_and_scope_version_invalidation():
    """Document list reads should hit Redis until the scope version changes."""
    redis_client = FakeRedisClient()
    with _load_document_access_index_module(redis_client) as (indexing, index_container, settings_container):
        _prepare_ready_projection(indexing, index_container, settings_container)

        first_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        second_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        indexing.invalidate_document_access_index_cache_scope_keys(
            ["user:owner-1"],
            reason="test_document_added",
            settings=_settings(),
        )
        third_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        cache_metrics = indexing.get_document_access_index_cache_metrics()
        read_metrics = indexing.get_document_access_index_read_metrics()

    assert first_result["status"] == "served_from_index"
    assert second_result["status"] == "served_from_cache"
    assert third_result["status"] == "served_from_index"
    assert [document["id"] for document in second_result["documents"]] == ["doc-1"]
    candidate_queries = [
        query for query in index_container.queries
        if "SELECT c.id, c.document_id" in query["query"]
    ]
    assert len(candidate_queries) == 2
    assert redis_client.setex_calls
    assert all(ttl_seconds == 900 for _key, ttl_seconds, _value in redis_client.setex_calls)
    assert len(redis_client.incr_calls) >= 2
    assert cache_metrics["windows"]["15m"]["hit_count"] == 1
    assert cache_metrics["windows"]["15m"]["miss_count"] == 2
    assert cache_metrics["windows"]["15m"]["invalidation_count"] >= 1
    assert read_metrics["windows"]["15m"]["served_from_cache_count"] == 1


def test_invalidation_runs_when_cache_setting_is_disabled():
    """Mutations should bump Redis scope versions even while cache reads are disabled."""
    redis_client = FakeRedisClient()
    disabled_cache_settings = _settings()
    disabled_cache_settings["enable_document_access_index_cache"] = False

    with _load_document_access_index_module(redis_client) as (indexing, index_container, settings_container):
        _prepare_ready_projection(indexing, index_container, settings_container)
        cached_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        updated_document = _document("doc-1", "owner-1", title="Updated Title")
        sync_result = indexing.sync_document_access_index_for_document(
            updated_document,
            operation="test_cache_disabled_update",
            settings=disabled_cache_settings,
            force=True,
        )
        fresh_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )

    assert cached_result["status"] == "served_from_index"
    assert sync_result["success"] is True
    assert fresh_result["status"] == "served_from_index"
    assert fresh_result["documents"][0]["title"] == "Updated Title"
    assert len(redis_client.incr_calls) >= 2


def test_failed_invalidation_marks_repair_and_blocks_cached_reads():
    """Redis invalidation failures should prevent stale cached access lists from being served."""
    redis_client = FailingIncrRedisClient()

    with _load_document_access_index_module(redis_client) as (indexing, index_container, settings_container):
        _prepare_ready_projection(indexing, index_container, settings_container)
        cached_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )

        redis_client.fail_incr = True
        update_result = indexing.sync_document_access_index_for_document_fail_open(
            _document("doc-1", "owner-1", title="Should Not Serve From Cache"),
            operation="test_invalidation_failure",
            settings=_settings(),
        )
        blocked_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )

    assert cached_result["status"] == "served_from_index"
    assert update_result["success"] is False
    assert update_result["status"] == "repair_required"
    assert blocked_result["success"] is False
    assert blocked_result["status"] == "repair_backlog_present"


def test_missing_redis_client_when_configured_marks_repair():
    """Configured Redis outages during invalidation should block DAI/cache until repair succeeds."""
    redis_client = None
    redis_configured_settings = _settings()
    redis_configured_settings["enable_redis_cache"] = True

    with _load_document_access_index_module(redis_client) as (indexing, _index_container, settings_container):
        _prepare_ready_projection(indexing, indexing.cosmos_document_access_index_container, settings_container)
        update_result = indexing.sync_document_access_index_for_document_fail_open(
            _document("doc-1", "owner-1", title="Redis Unavailable"),
            operation="test_redis_unavailable_update",
            settings=redis_configured_settings,
        )
        blocked_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=redis_configured_settings,
        )

    assert update_result["success"] is False
    assert update_result["status"] == "repair_required"
    assert blocked_result["success"] is False
    assert blocked_result["status"] == "repair_backlog_present"


def test_repair_invalidates_removed_share_scope_after_invalidation_failure():
    """Repair should invalidate cache scopes that were removed before invalidation failed."""
    redis_client = FailingIncrRedisClient()
    shared_document = _document("doc-1", "owner-1", shared_user_ids=["user-2,approved"])

    with _load_document_access_index_module(redis_client) as (indexing, index_container, settings_container):
        _prepare_ready_projection(indexing, index_container, settings_container, document=shared_document)
        cached_shared_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="user-2",
            settings=_settings(),
        )

        redis_client.fail_incr = True
        updated_document = _document("doc-1", "owner-1", shared_user_ids=[])
        update_result = indexing.sync_document_access_index_for_document_fail_open(
            updated_document,
            operation="test_share_revocation",
            settings=_settings(),
        )
        repair_docs = indexing._query_repair_documents()

        redis_client.fail_incr = False
        indexing.cosmos_user_documents_container.upsert_item(updated_document)
        repair_result = indexing.reconcile_document_access_index_repair_documents(
            settings=_settings(),
            force=True,
        )
        post_repair_shared_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="user-2",
            settings=_settings(),
        )

    assert cached_shared_result["status"] == "served_from_index"
    assert cached_shared_result["documents"][0]["id"] == "doc-1"
    assert update_result["success"] is False
    assert update_result["status"] == "repair_required"
    assert repair_docs and "user:user-2" in repair_docs[0].get("cache_scope_keys", [])
    assert repair_result["repairs_failed"] == 0
    assert repair_result["repairs_succeeded"] == 1
    assert post_repair_shared_result["status"] == "served_from_index"
    assert post_repair_shared_result["documents"] == []


def test_partial_projection_failure_preserves_removed_share_scope_for_repair():
    """Non-cache projection failures after stale-row deletion should keep revoked scopes for repair."""
    redis_client = FakeRedisClient()
    index_container = ToggleFailUpsertContainer()
    shared_document = _document("doc-1", "owner-1", shared_user_ids=["user-2,approved"])

    with _load_document_access_index_module(
        redis_client,
        index_container=index_container,
    ) as (indexing, loaded_index_container, settings_container):
        _prepare_ready_projection(indexing, loaded_index_container, settings_container, document=shared_document)
        cached_shared_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="user-2",
            settings=_settings(),
        )

        index_container.fail_upsert = True
        update_result = indexing.sync_document_access_index_for_document_fail_open(
            _document("doc-1", "owner-1", shared_user_ids=[]),
            operation="test_partial_projection_failure",
            settings=_settings(),
        )
        repair_docs = indexing._query_repair_documents()

    assert cached_shared_result["documents"][0]["id"] == "doc-1"
    assert update_result["success"] is False
    assert update_result["status"] == "repair_required"
    assert repair_docs and "user:user-2" in repair_docs[0].get("cache_scope_keys", [])


def test_stale_false_repair_backlog_state_is_verified_against_repair_docs():
    """A stale false backlog state should not allow DAI/cache reads when repair docs exist."""
    redis_client = FakeRedisClient()

    with _load_document_access_index_module(redis_client) as (indexing, _index_container, settings_container):
        settings_container.upsert_item({
            "id": indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
            "type": indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_TYPE,
            "has_repair_backlog": False,
            "schema_version": indexing.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        })
        settings_container.upsert_item({
            "id": indexing._repair_document_id("personal", "doc-stale"),
            "type": indexing.DOCUMENT_ACCESS_REPAIR_TYPE,
            "status": "repair_required",
            "operation": "test_stale_false_state",
            "source_scope": "personal",
            "source_document_id": "doc-stale",
            "schema_version": indexing.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        })

        has_backlog = indexing.has_document_access_index_repair_backlog()

    assert has_backlog is True


def test_repair_doc_write_failure_keeps_backlog_uncleared():
    """Repair-count refresh should not clear backlog state after repair tracking fails."""
    redis_client = FailingIncrRedisClient()
    settings_container = FailingRepairDocumentContainer()

    with _load_document_access_index_module(
        redis_client,
        settings_container=settings_container,
    ) as (indexing, index_container, loaded_settings_container):
        _prepare_ready_projection(indexing, index_container, loaded_settings_container)

        redis_client.fail_incr = True
        settings_container.fail_repair_upserts = True
        update_result = indexing.sync_document_access_index_for_document_fail_open(
            _document("doc-1", "owner-1", title="Repair Tracking Failed"),
            operation="test_repair_doc_write_failure",
            settings=_settings(),
        )
        repair_count = indexing.count_document_access_index_repair_documents()
        repair_result = indexing.reconcile_document_access_index_repair_documents(
            settings=_settings(),
            force=True,
        )
        has_backlog = indexing.has_document_access_index_repair_backlog()
        state = loaded_settings_container.read_item(
            item=indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
            partition_key=indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
        )
        blocked_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )

    assert update_result["success"] is False
    assert update_result["status"] == "repair_required"
    assert repair_count is None
    assert repair_result["success"] is True
    assert repair_result["repairs_processed"] == 0
    assert has_backlog is True
    assert state["has_repair_backlog"] is True
    assert state["repair_tracking_failed"] is True
    assert blocked_result["success"] is False
    assert blocked_result["status"] == "repair_backlog_present"


def test_tag_and_legacy_count_cache_hits_use_separate_keys():
    """Tag and legacy count reads should cache independently from document lists."""
    redis_client = FakeRedisClient()
    document = _document("doc-legacy", "owner-1", percentage_complete=None)
    with _load_document_access_index_module(redis_client) as (indexing, index_container, settings_container):
        _prepare_ready_projection(indexing, index_container, settings_container, document=document)

        first_tags = indexing.query_document_access_index_tag_counts(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        second_tags = indexing.query_document_access_index_tag_counts(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        first_legacy = indexing.query_document_access_index_legacy_count(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        second_legacy = indexing.query_document_access_index_legacy_count(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )

    assert first_tags["status"] == "served_from_index"
    assert second_tags["status"] == "served_from_cache"
    assert second_tags["tag_counts"] == {"cosmos": 1, "wave6": 1}
    assert first_legacy["status"] == "served_from_index"
    assert second_legacy["status"] == "served_from_cache"
    assert second_legacy["legacy_count"] == 1


def test_redis_failures_bypass_cache_without_forcing_source_fallback():
    """Redis cache failures should still allow direct DAI reads to succeed."""
    redis_client = FailingRedisClient()
    with _load_document_access_index_module(redis_client) as (indexing, index_container, settings_container):
        _prepare_ready_projection(indexing, index_container, settings_container)

        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(),
        )
        cache_metrics = indexing.get_document_access_index_cache_metrics()

    assert result["success"] is True
    assert result["status"] == "served_from_index"
    assert result["documents"][0]["id"] == "doc-1"
    assert cache_metrics["windows"]["15m"]["error_count"] >= 1


if __name__ == "__main__":
    tests = [
        test_document_list_cache_hit_and_scope_version_invalidation,
        test_invalidation_runs_when_cache_setting_is_disabled,
        test_failed_invalidation_marks_repair_and_blocks_cached_reads,
        test_missing_redis_client_when_configured_marks_repair,
        test_repair_invalidates_removed_share_scope_after_invalidation_failure,
        test_partial_projection_failure_preserves_removed_share_scope_for_repair,
        test_stale_false_repair_backlog_state_is_verified_against_repair_docs,
        test_repair_doc_write_failure_keeps_backlog_uncleared,
        test_tag_and_legacy_count_cache_hits_use_separate_keys,
        test_redis_failures_bypass_cache_without_forcing_source_fallback,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
