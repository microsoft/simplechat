# test_cosmos_wave5a_document_access_read_switch.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 5A/5B document access index read path.
Version: 0.250.047
Implemented in: 0.250.022
Public workspace UI coverage updated in: 0.250.023
Tag listing coverage updated in: 0.250.024
Production read metrics updated in: 0.250.025
Default read enablement updated in: 0.250.027
Redis DAI cache updated in: 0.250.029
Legacy tag family projection updated in: 0.250.030

This test ensures the default DAI read path only serves document list reads
when backfill is complete and repair backlog is clear. It also verifies
projected rows are shaped like source documents so existing list and tag
endpoints can safely fall back to source containers.
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
    def __init__(self, fail_query=False):
        self.items = {}
        self.fail_query = fail_query
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

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        if self.fail_query:
            raise RuntimeError("container query unavailable")

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
            if "IS_NULL(c.percentage_complete)" in query and item.get("percentage_complete") is not None:
                continue
            results.append(copy.deepcopy(item))
        if "SELECT VALUE COUNT" in query.upper():
            return [len(results)]

        return results


class FakeRepairBacklogStateReadFailContainer(FakeCosmosContainer):
    def read_item(self, item, partition_key):
        if item == "document_access_index_repair_backlog_state":
            raise RuntimeError("repair backlog state unavailable")
        return super().read_item(item, partition_key)


def _settings(reads_enabled=True, write_through_enabled=True):
    return {
        "enable_document_access_index_container": True,
        "enable_document_access_index_write_through": write_through_enabled,
        "enable_document_access_index_reads": reads_enabled,
        "enable_document_access_index_shadow_validation": False,
        "enable_startup_document_access_index_backfill": False,
    }


def _succeeded_backfill_state():
    return {
        "id": "document_access_index_backfill_state",
        "type": "document_access_index_backfill_state",
        "status": "succeeded",
        "source_scopes": ["personal", "group", "public"],
        "completed_source_scopes": ["personal", "group", "public"],
        "total_documents_processed": 3,
        "total_documents_failed": 0,
        "schema_version": 2,
    }


def _succeeded_with_errors_backfill_state():
    state = _succeeded_backfill_state()
    state["status"] = "succeeded_with_errors"
    state["total_documents_failed"] = 1
    return state


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
        "authors": ["Ada Lovelace"],
        "keywords": ["Cosmos"],
        "abstract": "Wave 5A projection read test",
        "tags": ["wave5a"],
        "shared_user_ids": [],
        "_ts": 12345,
    }
    document.update(overrides)
    return document


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
    fake_settings.get_settings = lambda: settings or _settings()
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


def test_read_switch_requires_completed_backfill_and_clear_repairs():
    """Reads should remain source-backed until DAI is explicitly ready."""
    with _load_document_access_index_module() as (indexing, _index_container, _settings_container):
        legacy_disabled_setting_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(reads_enabled=False),
        )
        not_ready_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(reads_enabled=True),
        )
        legacy_write_through_false_result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(reads_enabled=True, write_through_enabled=False),
        )

    assert legacy_disabled_setting_result["success"] is False
    assert legacy_disabled_setting_result["status"] == "backfill_not_ready"
    assert legacy_disabled_setting_result["readiness"]["settings"]["reads_enabled"] is True
    assert not_ready_result["success"] is False
    assert not_ready_result["status"] == "backfill_not_ready"
    assert legacy_write_through_false_result["success"] is False
    assert legacy_write_through_false_result["status"] == "backfill_not_ready"
    assert legacy_write_through_false_result["readiness"]["settings"]["write_through_enabled"] is True


def test_read_switch_falls_back_when_repair_backlog_state_is_unknown():
    """A state read failure should block DAI reads and leave source fallback available."""
    settings_container = FakeRepairBacklogStateReadFailContainer()
    with _load_document_access_index_module(settings_container=settings_container) as (
        indexing,
        _index_container,
        settings_container,
    ):
        settings_container.upsert_item(_succeeded_backfill_state())
        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(reads_enabled=True),
        )

    assert result["success"] is False
    assert result["status"] == "repair_backlog_unknown"
    assert result["readiness"]["backfill_status"] == "succeeded"


def test_read_switch_accepts_succeeded_with_errors_when_repairs_are_clear():
    """Resolved historical backfill errors should not block DAI reads forever."""
    with _load_document_access_index_module() as (indexing, index_container, settings_container):
        settings_container.upsert_item(_succeeded_with_errors_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document("doc-owner", "owner-1"),
            force=True,
        )

        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
            settings=_settings(reads_enabled=True),
        )

    assert result["success"] is True
    assert result["status"] == "served_from_index"
    assert result["readiness"]["backfill_status"] == "succeeded_with_errors"
    assert len(result["documents"]) == 1
    assert ("user:owner-1", "dai:user:owner-1:personal:doc-owner:1") in index_container.items


def test_read_switch_returns_list_ready_projection_documents():
    """DAI reads should be single-partition and shaped like source list documents."""
    with _load_document_access_index_module() as (indexing, index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document("doc-owner", "owner-1"),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "doc-shared",
                "owner-2",
                title="Shared Cosmos Notes",
                shared_user_ids=["reader-1,approved", "auditor-1,approved"],
                number_of_pages=12,
                publication_date="2026-07-02",
                enhanced_citations=True,
                blob_path="documents/doc-shared.pdf",
                document_intelligence_extraction_mode="layout",
                generated_artifact_promotion_status="pending_approval",
                file_sync={"enabled": True, "scope": "personal"},
                created_from_chat_upload=True,
                conversation_id="conversation-123",
                conversation_title_at_upload="Cosmos tuning chat",
            ),
            force=True,
        )

        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="reader-1",
            filters={
                "search": "cosmos",
                "author": "ada",
                "keywords": "cosmos",
                "abstract": "projection",
                "tags": ["wave5a"],
                "array_match_mode": "contains",
            },
        )
        read_metrics = indexing.get_document_access_index_read_metrics()
        repair_existence_queries = [
            query
            for query in settings_container.queries
            if "SELECT TOP 1 VALUE c.id" in query["query"]
        ]

    assert result["success"] is True
    assert result["status"] == "served_from_index"
    assert repair_existence_queries
    assert result["scope_keys"] == ["user:reader-1"]
    assert len(result["documents"]) == 1
    document = result["documents"][0]
    assert document["id"] == "doc-shared"
    assert document["user_id"] == "owner-2"
    assert document["shared_user_ids"] == ["reader-1,approved", "auditor-1,approved"]
    assert document["_ts"] == 12345
    assert document["number_of_pages"] == 12
    assert document["publication_date"] == "2026-07-02"
    assert document["enhanced_citations"] is True
    assert document["document_intelligence_extraction_mode"] == "layout"
    assert document["generated_artifact_promotion_status"] == "pending_approval"
    assert document["file_sync"] == {"enabled": True, "scope": "personal"}
    assert document["created_from_chat_upload"] is True
    assert document["conversation_id"] == "conversation-123"
    assert document["conversation_title_at_upload"] == "Cosmos tuning chat"
    read_queries = [
        query for query in index_container.queries
        if query["partition_key"] == "user:reader-1"
    ]
    assert len(read_queries) == 1
    assert all("ORDER BY" not in query["query"] for query in read_queries)
    assert all("OFFSET" not in query["query"] for query in read_queries)
    assert all("LIMIT" not in query["query"] for query in read_queries)
    assert all("TOP" not in query["query"] for query in read_queries)
    assert read_metrics["windows"]["15m"]["sample_count"] == 1
    assert read_metrics["windows"]["15m"]["served_from_index_count"] == 1
    assert read_metrics["windows"]["15m"]["source_fallback_count"] == 0
    assert read_metrics["windows"]["15m"]["item_count"] == 1


def test_read_switch_returns_multi_public_workspace_documents():
    """Public chat document lists should read one DAI partition per visible public workspace."""
    with _load_document_access_index_module() as (indexing, index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document(
                "public-doc-a",
                "owner-public-a",
                public_workspace_id="public-a",
                title="Public Cosmos Notes A",
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "public-doc-b",
                "owner-public-b",
                public_workspace_id="public-b",
                title="Public Cosmos Notes B",
            ),
            force=True,
        )

        result = indexing.query_document_access_index_documents(
            source_scope="public",
            public_workspace_ids=["public-a", "public-b"],
        )

    assert result["success"] is True
    assert result["status"] == "served_from_index"
    assert result["scope_keys"] == ["public:public-a", "public:public-b"]
    assert {document["id"] for document in result["documents"]} == {"public-doc-a", "public-doc-b"}
    read_partitions = {
        query["partition_key"]
        for query in index_container.queries
        if query["partition_key"] in {"public:public-a", "public:public-b"}
    }
    assert read_partitions == {"public:public-a", "public:public-b"}


def test_read_switch_includes_pending_projection_rows_for_approval_ui():
    """Document-list reads should include pending shares so users can approve them."""
    with _load_document_access_index_module() as (indexing, index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document(
                "personal-pending-share",
                "owner-1",
                shared_user_ids=["reader-1,not_approved"],
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "personal-approved-share",
                "owner-2",
                shared_user_ids=["reader-1,approved"],
            ),
            force=True,
        )

        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="reader-1",
        )

    assert result["success"] is True
    assert result["status"] == "served_from_index"
    assert {document["id"] for document in result["documents"]} == {
        "personal-pending-share",
        "personal-approved-share",
    }
    pending_document = next(
        document for document in result["documents"]
        if document["id"] == "personal-pending-share"
    )
    assert pending_document["shared_user_ids"] == ["reader-1,not_approved"]
    candidate_queries = [
        query["query"]
        for query in index_container.queries
        if "c.conversation_title_at_upload" in query["query"]
    ]
    assert candidate_queries
    assert all("c.approval_status = @approval_not_approved" in query for query in candidate_queries)


def test_read_switch_exact_array_filters_are_case_sensitive():
    """Exact author/keyword filters should preserve source route case-sensitive semantics."""
    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document(
                "public-case-sensitive",
                "owner-public",
                public_workspace_id="public-a",
                authors=["Ada Lovelace"],
            ),
            force=True,
        )

        exact_match = indexing.query_document_access_index_documents(
            source_scope="public",
            public_workspace_id="public-a",
            filters={
                "author": "Ada Lovelace",
                "array_match_mode": "exact",
            },
        )
        lower_case_mismatch = indexing.query_document_access_index_documents(
            source_scope="public",
            public_workspace_id="public-a",
            filters={
                "author": "ada lovelace",
                "array_match_mode": "exact",
            },
        )

    assert [document["id"] for document in exact_match["documents"]] == ["public-case-sensitive"]
    assert lower_case_mismatch["documents"] == []


def test_read_switch_classification_filters_are_case_sensitive():
    """Non-none classification filters should preserve source route exact casing."""
    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document(
                "public-classified",
                "owner-public",
                public_workspace_id="public-a",
                document_classification="Confidential",
            ),
            force=True,
        )

        exact_match = indexing.query_document_access_index_documents(
            source_scope="public",
            public_workspace_id="public-a",
            filters={"classification": "Confidential"},
        )
        lower_case_mismatch = indexing.query_document_access_index_documents(
            source_scope="public",
            public_workspace_id="public-a",
            filters={"classification": "confidential"},
        )

    assert [document["id"] for document in exact_match["documents"]] == ["public-classified"]
    assert lower_case_mismatch["documents"] == []


def test_read_switch_public_projection_includes_generated_artifact_requester():
    """Public DAI rows should include requester identity used by generated-artifact actions."""
    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document(
                "public-artifact",
                "owner-public",
                public_workspace_id="public-a",
                generated_artifact_promotion_status="pending_approval",
                generated_artifact_requested_by_user_id="requester-1",
            ),
            force=True,
        )

        result = indexing.query_document_access_index_documents(
            source_scope="public",
            public_workspace_id="public-a",
        )

    document = result["documents"][0]
    assert document["id"] == "public-artifact"
    assert document["generated_artifact_requested_by_user_id"] == "requester-1"
    assert document["user_id"] == "owner-public"


def test_read_switch_normalizes_enhanced_citations_from_blob_state():
    """DAI list rows should mirror source enhanced_citations normalization from blob references."""
    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document(
                "blob-backed",
                "owner-1",
                enhanced_citations=False,
                blob_path="documents/blob-backed.pdf",
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "metadata-only",
                "owner-1",
                enhanced_citations=True,
                blob_path=None,
            ),
            force=True,
        )

        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
        )

    documents_by_id = {document["id"]: document for document in result["documents"]}
    assert documents_by_id["blob-backed"]["enhanced_citations"] is True
    assert documents_by_id["metadata-only"]["enhanced_citations"] is False


def test_read_switch_collapses_legacy_revisions_by_scope_and_file_name():
    """Legacy rows without revision metadata should collapse like source select_current_documents()."""
    older_document = _document("legacy-v1", "owner-1", file_name="legacy.pdf", version=1, _ts=100)
    newer_document = _document("legacy-v2", "owner-1", file_name="legacy.pdf", version=2, _ts=200)
    older_document.pop("revision_family_id", None)
    newer_document.pop("revision_family_id", None)
    older_document.pop("is_current_version", None)
    newer_document.pop("is_current_version", None)

    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(older_document, force=True)
        indexing.sync_document_access_index_for_document(newer_document, force=True)

        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
        )

    assert [document["id"] for document in result["documents"]] == ["legacy-v2"]
    assert result["documents"][0]["version"] == 2


def test_tag_count_read_switch_uses_owner_projection_rows_by_scope():
    """Tag list reads should count current owner-scope projection rows without source scans."""
    with _load_document_access_index_module() as (indexing, index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document("personal-owner", "owner-1", tags=["wave5a", "cosmos"]),
            force=True,
        )
        older_legacy_tag = _document("personal-legacy-tag-v1", "owner-1", file_name="legacy-tag.pdf", version=1, tags=["legacytag"])
        newer_legacy_tag = _document("personal-legacy-tag-v2", "owner-1", file_name="legacy-tag.pdf", version=2, tags=["legacytag"])
        distinct_legacy_tag = _document("personal-legacy-tag-v3", "owner-1", file_name="legacy-tag-2.pdf", version=1, tags=["legacytag"])
        older_legacy_tag.pop("revision_family_id", None)
        newer_legacy_tag.pop("revision_family_id", None)
        distinct_legacy_tag.pop("revision_family_id", None)
        older_legacy_tag.pop("is_current_version", None)
        newer_legacy_tag.pop("is_current_version", None)
        distinct_legacy_tag.pop("is_current_version", None)
        indexing.sync_document_access_index_for_document(older_legacy_tag, force=True)
        indexing.sync_document_access_index_for_document(newer_legacy_tag, force=True)
        indexing.sync_document_access_index_for_document(distinct_legacy_tag, force=True)
        indexing.sync_document_access_index_for_document(
            _document(
                "personal-shared",
                "owner-2",
                tags=["shared-only"],
                shared_user_ids=["owner-1,approved"],
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "group-owned",
                "owner-1",
                group_id="group-a",
                tags=["group-alpha"],
                shared_group_ids=["group-b,approved"],
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "public-owned",
                "owner-public",
                public_workspace_id="public-a",
                tags=["public-alpha"],
            ),
            force=True,
        )

        personal_result = indexing.query_document_access_index_tag_counts(
            source_scope="personal",
            user_id="owner-1",
        )
        group_result = indexing.query_document_access_index_tag_counts(
            source_scope="group",
            group_ids=["group-a", "group-b"],
        )
        public_result = indexing.query_document_access_index_tag_counts(
            source_scope="public",
            public_workspace_ids=["public-a"],
        )

    assert personal_result["success"] is True
    assert personal_result["status"] == "served_from_index"
    assert personal_result["tag_counts"] == {"cosmos": 1, "legacytag": 2, "wave5a": 1}
    assert "shared-only" not in personal_result["tag_counts"]
    assert group_result["success"] is True
    assert group_result["tag_counts_by_scope_key"]["group:group-a"] == {"group-alpha": 1}
    assert group_result["tag_counts_by_scope_key"]["group:group-b"] == {}
    assert public_result["success"] is True
    assert public_result["tag_counts_by_scope_key"]["public:public-a"] == {"public-alpha": 1}
    tag_read_queries = [
        query for query in index_container.queries
        if "tag_read:" in query["query"] or "ARRAY_LENGTH(c.tags)" in query["query"]
    ]
    assert tag_read_queries
    assert all(query["partition_key"] for query in tag_read_queries)
    assert all("ORDER BY" not in query["query"] for query in tag_read_queries)
    assert all("OFFSET" not in query["query"] for query in tag_read_queries)
    assert all("LIMIT" not in query["query"] for query in tag_read_queries)
    assert all("TOP" not in query["query"] for query in tag_read_queries)
    assert all("c.file_name" in query["query"] for query in tag_read_queries)


def test_legacy_count_read_switch_uses_unfiltered_owner_projection_rows():
    """Legacy prompts should use unfiltered owner-scope DAI rows, not current list filters."""
    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        settings_container.upsert_item(_succeeded_backfill_state())
        indexing.sync_document_access_index_for_document(
            _document("personal-owner-legacy", "owner-1", percentage_complete=None),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "personal-old-revision-legacy",
                "owner-1",
                is_current_version=False,
                percentage_complete=None,
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "personal-shared-legacy",
                "owner-2",
                percentage_complete=None,
                shared_user_ids=["owner-1,approved"],
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document("group-owner-legacy", "owner-1", group_id="group-a", percentage_complete=None),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document(
                "group-shared-legacy",
                "owner-1",
                group_id="group-b",
                percentage_complete=None,
                shared_group_ids=["group-a,approved"],
            ),
            force=True,
        )
        indexing.sync_document_access_index_for_document(
            _document("public-owner-legacy", "owner-public", public_workspace_id="public-a", percentage_complete=None),
            force=True,
        )

        personal_result = indexing.query_document_access_index_legacy_count(
            source_scope="personal",
            user_id="owner-1",
        )
        group_result = indexing.query_document_access_index_legacy_count(
            source_scope="group",
            group_ids=["group-a"],
        )
        public_result = indexing.query_document_access_index_legacy_count(
            source_scope="public",
            public_workspace_id="public-a",
        )

    assert personal_result["success"] is True
    assert personal_result["legacy_count"] == 2
    assert group_result["success"] is True
    assert group_result["legacy_count"] == 1
    assert public_result["success"] is True
    assert public_result["legacy_count"] == 1


def test_read_switch_query_failure_reports_source_fallback_status():
    """DAI query failures should return a safe fallback status instead of raising."""
    settings_container = FakeCosmosContainer()
    settings_container.upsert_item(_succeeded_backfill_state())
    with _load_document_access_index_module(
        index_container=FakeCosmosContainer(fail_query=True),
        settings_container=settings_container,
    ) as (indexing, _index_container, _settings_container):
        result = indexing.query_document_access_index_documents(
            source_scope="personal",
            user_id="owner-1",
        )
        read_metrics = indexing.get_document_access_index_read_metrics()

    assert result["success"] is False
    assert result["status"] == "query_failed"
    assert result["documents"] == []
    assert read_metrics["windows"]["15m"]["sample_count"] == 1
    assert read_metrics["windows"]["15m"]["source_fallback_count"] == 1
    assert read_metrics["last_fallback_sample"]["status"] == "query_failed"


def test_wave5b_route_and_admin_contract_are_wired():
    """Routes and Admin Settings should expose the Wave 5B default read path."""
    config_source = open(os.path.join(SINGLE_APP_DIR, "config.py"), "r", encoding="utf-8").read()
    index_source = open(
        os.path.join(SINGLE_APP_DIR, "functions_document_access_index.py"),
        "r",
        encoding="utf-8",
    ).read()
    personal_route = open(os.path.join(SINGLE_APP_DIR, "route_backend_documents.py"), "r", encoding="utf-8").read()
    group_route = open(os.path.join(SINGLE_APP_DIR, "route_backend_group_documents.py"), "r", encoding="utf-8").read()
    public_route = open(os.path.join(SINGLE_APP_DIR, "route_external_public_documents.py"), "r", encoding="utf-8").read()
    backend_public_route = open(
        os.path.join(SINGLE_APP_DIR, "route_backend_public_documents.py"),
        "r",
        encoding="utf-8",
    ).read()
    admin_template = open(
        os.path.join(SINGLE_APP_DIR, "templates", "admin_settings.html"),
        "r",
        encoding="utf-8",
    ).read()
    admin_route = open(
        os.path.join(SINGLE_APP_DIR, "route_frontend_admin_settings.py"),
        "r",
        encoding="utf-8",
    ).read()
    settings_source = open(os.path.join(SINGLE_APP_DIR, "functions_settings.py"), "r", encoding="utf-8").read()

    assert 'VERSION = "0.250.047"' in config_source
    assert "DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION = 2" in index_source
    assert "def query_document_access_index_documents(" in index_source
    assert "def query_document_access_index_tag_counts(" in index_source
    assert "def query_document_access_index_legacy_count(" in index_source
    assert "def get_document_access_index_read_metrics(" in index_source
    assert "def get_document_access_index_cache_metrics(" in index_source
    assert "def invalidate_document_access_index_cache_scope_keys(" in index_source
    assert "_record_document_access_read_metric(" in index_source
    assert "'served_from_index'" in index_source
    assert "'backfill_not_ready'" in index_source
    assert "partition_key=scope_key" in index_source
    assert "c.approval_status = @approval_not_approved" in index_source
    assert "c.projection_version = @projection_version" in index_source
    assert "_safe_int(state.get('schema_version')) != DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION" in index_source
    assert "number_of_pages" in index_source
    assert "generated_artifact_promotion_status" in index_source
    assert "conversation_title_at_upload" in index_source
    assert "query_document_access_index_documents(" in personal_route
    assert "query_document_access_index_documents(" in group_route
    assert "query_document_access_index_documents(" in public_route
    assert "query_document_access_index_documents(" in backend_public_route
    assert "query_document_access_index_tag_counts(" in personal_route
    assert "query_document_access_index_tag_counts(" in group_route
    assert "query_document_access_index_tag_counts(" in backend_public_route
    assert "query_document_access_index_legacy_count(" in personal_route
    assert "query_document_access_index_legacy_count(" in group_route
    assert "query_document_access_index_legacy_count(" in public_route
    assert "query_document_access_index_legacy_count(" in backend_public_route
    assert "build_workspace_tags_from_counts(" in personal_route
    assert "build_workspace_tags_from_counts(" in group_route
    assert "build_workspace_tags_from_counts(" in backend_public_route
    assert "if index_read_result.get('success')" in personal_route
    assert "if index_read_result.get('success')" in group_route
    assert "if index_read_result.get('success')" in public_route
    assert "if index_read_result.get('success')" in backend_public_route
    assert "legacy_count = 0\n        if used_document_access_index:" in personal_route
    assert "public_workspace_ids=workspace_ids" in backend_public_route
    assert "context='api_list_public_documents'" in backend_public_route
    assert "context='api_list_public_workspace_documents'" in backend_public_route
    assert "'enable_document_access_index_reads': True" in settings_source
    assert "normalize_document_access_index_required_settings(merged)" in settings_source
    assert 'name="enable_document_access_index_reads"' in admin_template
    assert "Wave 5B default" in admin_template
    assert "Wave 6" in admin_template
    assert "Redis document list cache" in admin_template
    assert "'enable_document_access_index_reads': True" in admin_route


if __name__ == "__main__":
    tests = [
        test_read_switch_requires_completed_backfill_and_clear_repairs,
        test_read_switch_falls_back_when_repair_backlog_state_is_unknown,
        test_read_switch_accepts_succeeded_with_errors_when_repairs_are_clear,
        test_read_switch_returns_list_ready_projection_documents,
        test_read_switch_returns_multi_public_workspace_documents,
        test_read_switch_includes_pending_projection_rows_for_approval_ui,
        test_read_switch_exact_array_filters_are_case_sensitive,
        test_read_switch_classification_filters_are_case_sensitive,
        test_read_switch_public_projection_includes_generated_artifact_requester,
        test_read_switch_normalizes_enhanced_citations_from_blob_state,
        test_read_switch_collapses_legacy_revisions_by_scope_and_file_name,
        test_tag_count_read_switch_uses_owner_projection_rows_by_scope,
        test_legacy_count_read_switch_uses_unfiltered_owner_projection_rows,
        test_read_switch_query_failure_reports_source_fallback_status,
        test_wave5b_route_and_admin_contract_are_wired,
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
