# test_v2_document_index_coverage.py
"""
Runtime regressions for shared V2 document access index coverage.
Version: 0.261.407
Implemented in: 0.261.407

Real application owners execute with network blocked. Storage point responses
use the installed SDK CosmosDict, query rows are plain dictionaries, and the
query seam enforces selected columns instead of concealing projection omissions.
"""

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.cosmos._cosmos_responses import CosmosDict
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError
import pytest

from test_cosmos_wave5a_document_access_read_switch import (
    FakeCosmosContainer,
    _document,
    _succeeded_backfill_state,
)
from test_cosmos_wave6_document_access_cache import FakeRedisClient
from test_v2_document_source_runtime import fresh_application_imports


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"


class SdkDocumentContainer(FakeCosmosContainer):
    """Conditional storage semantics from the shared seam, with SDK-default points."""

    def __init__(self):
        super().__init__()
        self.etag_counter = 0

    def upsert_item(self, body):
        self.etag_counter += 1
        saved = {**deepcopy(dict(body)), "_etag": f"etag-{self.etag_counter}"}
        return CosmosDict(super().upsert_item(saved), response_headers={})

    def read_item(self, item, partition_key):
        return CosmosDict(super().read_item(item, partition_key), response_headers={})

    def replace_item(self, **kwargs):
        return CosmosDict(super().replace_item(**kwargs), response_headers={})

    def delete_item(self, item, partition_key):
        self.items.pop((partition_key, item), None)

    def query_items(self, query, parameters=None, **kwargs):
        rows = super().query_items(query, parameters=parameters, **kwargs)
        values = {item["name"]: item["value"] for item in parameters or []}
        if "@document_ids" in values:
            rows = [row for row in rows if row["id"] in values["@document_ids"]]
        if "@group_id" in values:
            group_id = values["@group_id"]
            rows = [
                row for row in rows
                if row.get("group_id") == group_id or any(
                    entry.split(",", 1)[0] == group_id for entry in row.get("shared_group_ids") or []
                )
            ]
        if "@workspace_id" in values:
            rows = [row for row in rows if row.get("public_workspace_id") == values["@workspace_id"]]
        if "@user_id" in values:
            user_id = values["@user_id"]
            rows = [
                row for row in rows
                if row.get("user_id") == user_id or any(
                    entry.split(",", 1)[0] == user_id for entry in row.get("shared_user_ids") or []
                )
            ]
        if "c.is_current_version = true" in query:
            rows = [row for row in rows if row.get("is_current_version") is True]
        selected = re.match(r"\s*SELECT\s+((?:c\.\w+(?:,\s*)?)+)\s+FROM", query)
        if selected:
            fields = re.findall(r"c\.(\w+)", selected.group(1))
            return [{field: row[field] for field in fields if field in row} for row in rows]
        return [dict(row) if isinstance(row, dict) else row for row in rows]


@pytest.fixture
def owners(monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    with fresh_application_imports():
        dai = importlib.import_module("functions_document_access_index")
        documents = importlib.import_module("functions_documents")
        group = importlib.import_module("functions_group_document_reads")
        public = importlib.import_module("functions_public_document_reads")
        knowledge = importlib.import_module("functions_assigned_knowledge")
        search = importlib.import_module("functions_search")
        cache = importlib.import_module("utils_cache")
        settings = {"enable_search_result_caching": True, "enable_document_access_index_cache": True}
        index, state = SdkDocumentContainer(), SdkDocumentContainer()
        state.upsert_item(_succeeded_backfill_state())
        sources = {scope: SdkDocumentContainer() for scope in ("personal", "group", "public")}
        monkeypatch.setattr(dai, "cosmos_document_access_index_container", index)
        monkeypatch.setattr(dai, "cosmos_settings_container", state)
        monkeypatch.setattr(dai, "get_settings", lambda: settings)
        monkeypatch.setattr(dai.app_settings_cache, "get_app_cache_redis_client", lambda: None)
        for module in (documents, knowledge, cache):
            for scope, name in (
                ("personal", "cosmos_user_documents_container"),
                ("group", "cosmos_group_documents_container"),
                ("public", "cosmos_public_documents_container"),
            ):
                if hasattr(module, name):
                    monkeypatch.setattr(module, name, sources[scope])
        monkeypatch.setattr(group, "cosmos_group_documents_container", sources["group"])
        monkeypatch.setattr(public, "cosmos_public_documents_container", sources["public"])
        monkeypatch.setattr(group, "require_group_document_read_context", lambda *args: ({}, "Owner"))
        monkeypatch.setattr(public, "require_public_document_read_context", lambda *args: ({}, "Owner"))
        monkeypatch.setattr(knowledge, "filter_available_results", lambda rows, **kwargs: rows)
        case = SimpleNamespace(
            dai=dai, documents=documents, group=group, public=public, knowledge=knowledge,
            search=search, cache=cache, index=index, state=state, sources=sources,
            settings=settings,
        )

        def seed(identifier, scope="personal", indexed=True, **fields):
            owner = {"group_id": "group-a"} if scope == "group" else (
                {"public_workspace_id": "public-a"} if scope == "public" else {}
            )
            saved = sources[scope].upsert_item(_document(identifier, "reader", **{**owner, **fields}))
            if indexed:
                for row in dai.build_document_access_index_rows(saved):
                    index.upsert_item(row)
            return saved

        case.seed = seed
        yield case


def test_indexed_size_and_owner_family_parity(owners):
    owners.seed("large", file_size=4096)
    owners.seed("small", file_size=128)
    result = owners.dai.query_document_access_index_documents("personal", user_id="reader")
    ordered = owners.documents.sort_documents(result["documents"], "file_size", "asc")
    assert result["success"]
    assert [row["id"] for row in ordered] == ["small", "large"]
    owners.seed("owned", "group", revision_family_id="same")
    owners.seed(
        "shared", "group", group_id="other-group", revision_family_id="same",
        shared_group_ids=["group-a,approved"],
    )
    grouped = owners.dai.query_document_access_index_documents("group", group_ids=["group-a"])
    assert {row["id"] for row in grouped["documents"]} == {"owned", "shared"}


def test_legacy_schema_identity_uses_logical_path(owners):
    for path in ("folder-a/schema.xsd", "folder-b/schema.xsd"):
        owners.seed(
            path, file_name="schema.xsd", document_kind="xml_schema",
            revision_family_id=None, xsd_revision_identity=path,
        )
    result = owners.dai.query_document_access_index_documents("personal", user_id="reader")
    assert result["success"] and len(result["documents"]) == 2


@pytest.mark.parametrize("scope,scope_id", [("personal", "reader"), ("group", "group-a"), ("public", "public-a")])
def test_fingerprint_matches_source_and_includes_history(owners, scope, scope_id):
    saved = owners.seed("current", scope, tags=["policy"])
    assert isinstance(saved, CosmosDict)
    owners.seed("historical", scope, is_current_version=False)
    scope_arguments = (
        {"user_id": scope_id} if scope == "personal" else
        {"group_ids": [scope_id]} if scope == "group" else {"public_workspace_ids": [scope_id]}
    )
    result = owners.dai.query_document_access_index_fingerprint(scope, **scope_arguments)
    fingerprint_reader = {
        "personal": owners.cache.get_personal_document_fingerprint,
        "group": owners.cache.get_group_document_fingerprint,
        "public": owners.cache.get_public_workspace_document_fingerprint,
    }[scope]
    source_fingerprint = fingerprint_reader(scope_id)
    assert result["success"] and result["fingerprint"] == source_fingerprint
    queries = [item for item in owners.index.queries if "c.cache_identity" in item["query"]]
    partition = f"{'user' if scope == 'personal' else scope}:{scope_id}"
    assert queries and all(item["partition_key"] == partition for item in queries)
    assert all("is_current_version" not in item["query"] for item in queries)
    current_only = owners.dai.query_document_access_index_documents(scope, **scope_arguments)
    assert [row["id"] for row in current_only["documents"]] == ["current"]


@pytest.mark.parametrize("scope", ["group", "public"])
def test_named_readers_use_index_ids_not_full_source_discovery(owners, scope):
    owners.seed("indexed", scope)
    owners.seed("not-yet-indexed", scope, indexed=False)
    module, scope_id = (owners.group, "group-a") if scope == "group" else (owners.public, "public-a")
    load = getattr(module, f"load_{scope}_document_browser_documents")
    records = load("reader", scope_id)
    assert [record["id"] for record in records] == ["indexed"]
    queries = owners.sources[scope].queries
    assert queries and all("@document_ids" in query["query"] for query in queries)


@pytest.mark.parametrize("scope", ["group", "public"])
def test_healthy_empty_index_does_not_scan_sources(owners, scope):
    owners.seed("source-only", scope, indexed=False)
    module, scope_id = (owners.group, "group-a") if scope == "group" else (owners.public, "public-a")
    records = getattr(module, f"load_{scope}_document_browser_documents")("reader", scope_id)
    assert records == [] and owners.sources[scope].queries == []


@pytest.mark.parametrize("failure", ["old_schema", "backfill", "repair", "query"])
def test_named_readers_fall_back_for_unusable_index(owners, failure):
    owners.seed("source-only", "group", indexed=False)
    state = _succeeded_backfill_state()
    if failure == "old_schema":
        state["schema_version"] = owners.dai.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION - 1
    elif failure == "backfill":
        state["status"] = "running"
    elif failure == "repair":
        owners.state.upsert_item({
            "id": "repair", "type": owners.dai.DOCUMENT_ACCESS_REPAIR_TYPE, "status": "repair_required",
        })
    else:
        owners.index.fail_query = True
    owners.state.upsert_item(state)
    records = owners.group.load_group_document_browser_documents("reader", "group-a")
    assert [record["id"] for record in records] == ["source-only"]
    assert any("@document_ids" not in item["query"] for item in owners.sources["group"].queries)


def test_stale_shared_hit_is_not_a_permission_grant(owners):
    owners.seed("shared", "group", group_id="other-group", shared_group_ids=["group-a,approved"])
    owners.seed("shared", "group", indexed=False, group_id="other-group", shared_group_ids=[])
    records = owners.group.load_group_document_browser_documents("reader", "group-a")
    assert records == []


def test_runtime_inventory_resolves_beyond_editor_window(owners):
    for number in range(1001):
        owners.seed(f"document-{number:04d}", _ts=number)
    catalog = owners.knowledge._get_personal_catalog_documents("reader")
    active = owners.knowledge.resolve_assigned_knowledge_active_documents("reader", {
        "has_workspace_knowledge": True,
        "assigned_knowledge": {
            "scopes": {"personal": True}, "document_ids": ["document-0000"], "tags": [],
        },
    })
    assert len(catalog) == 1000 and "document-0000" not in {row["id"] for row in catalog}
    assert [row["id"] for row in active] == ["document-0000"]
    assert all("@document_ids" in item["query"] for item in owners.sources["personal"].queries)


def test_catalog_source_failure_is_not_empty_success(owners):
    owners.index.fail_query = True
    owners.sources["personal"].fail_query = True
    with pytest.raises(owners.knowledge.AssignedKnowledgeError, match="temporarily unavailable"):
        owners.knowledge._get_personal_catalog_documents("reader")


def configure_search(owners, monkeypatch, *, caching):
    search = owners.search
    monkeypatch.setattr(search, "get_cache_settings", lambda: (caching, 300))
    monkeypatch.setattr(search, "read_embedding_settings", lambda: {})
    monkeypatch.setattr(search, "active_embedding_profile", lambda settings: SimpleNamespace(profile_id="profile"))
    monkeypatch.setattr(search, "embedding_query_slot", lambda profile: nullcontext())
    monkeypatch.setattr(search, "_resolve_public_workspace_ids_for_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(search, "filter_available_results", lambda rows, **kwargs: rows)
    return search


def test_indexed_cache_hit_skips_source_enumeration_and_repair(owners, monkeypatch):
    owners.seed("document")
    search = configure_search(owners, monkeypatch, caching=True)
    repair = Mock(side_effect=AssertionError("Cache hits must not enumerate revisions."))
    monkeypatch.setattr(owners.documents, "normalize_document_revision_families", repair)
    cache_store = Mock()
    cache_store.read_item.return_value = CosmosDict({
        "expiry_time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "results": [{"document_id": "document"}],
    }, response_headers={})
    monkeypatch.setattr(owners.cache, "get_cache_settings", lambda: (True, 300))
    monkeypatch.setattr(owners.cache, "cosmos_search_cache_container", cache_store)
    owners.sources["personal"].fail_query = True
    first = search.hybrid_search("policy", "reader", doc_scope="personal")
    second = search.hybrid_search("policy", "reader", doc_scope="personal")
    assert first == second == [{"document_id": "document"}]
    assert not repair.called and owners.sources["personal"].queries == []
    assert cache_store.read_item.call_count == 2


def test_disabled_result_cache_does_no_fingerprinting(owners, monkeypatch):
    search = configure_search(owners, monkeypatch, caching=False)
    fingerprint = Mock(side_effect=AssertionError("Disabled caching must not fingerprint."))
    monkeypatch.setattr(owners.dai, "query_document_access_index_fingerprint", fingerprint)
    monkeypatch.setattr(search, "generate_search_cache_key", fingerprint)
    monkeypatch.setattr(search, "generate_embedding", lambda *args, **kwargs: None)
    monkeypatch.setattr(owners.documents, "normalize_document_revision_families", lambda **kwargs: False)
    result = search.hybrid_search("policy", "reader", doc_scope="personal")
    assert result is None and not fingerprint.called


def test_normalization_memo_uses_existing_generation(owners, monkeypatch):
    redis = FakeRedisClient()
    monkeypatch.setattr(owners.dai.app_settings_cache, "get_app_cache_redis_client", lambda: redis)
    context = owners.dai.get_document_access_normalization_context("personal", user_id="reader")
    saved = owners.dai.remember_document_access_normalization(context)
    cached = owners.dai.document_access_normalization_is_cached(context)
    assert saved and cached
    invalidated = owners.dai.invalidate_document_access_index_cache_scope_keys(["user:reader"])
    assert invalidated["success"]
    next_context = owners.dai.get_document_access_normalization_context("personal", user_id="reader")
    next_cached = owners.dai.document_access_normalization_is_cached(next_context)
    assert not next_cached
    owners.dai.invalidate_document_access_index_cache_scope_keys(["user:reader"])
    stale_saved = owners.dai.remember_document_access_normalization(next_context)
    assert not stale_saved


@pytest.mark.parametrize("normalization", ["unchanged", "generation_changed", "repair_changed", "failure"])
def test_search_caches_only_with_unchanged_normalization(owners, monkeypatch, normalization):
    owners.seed("document")
    search = configure_search(owners, monkeypatch, caching=True)
    redis = FakeRedisClient()
    monkeypatch.setattr(owners.dai.app_settings_cache, "get_app_cache_redis_client", lambda: redis)
    monkeypatch.setattr(search, "get_cached_search_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(search, "generate_embedding", lambda *args, **kwargs: [1.0, 0.0])
    monkeypatch.setattr(search, "embedding_search_filter", lambda *args: None)
    monkeypatch.setattr(search, "CLIENTS", {
        f"search_client_{scope}": object() for scope in ("user", "group", "public")
    })
    transport = Mock(return_value=[])
    store = Mock()
    monkeypatch.setattr(search, "search_with_embedding_profile", transport)
    monkeypatch.setattr(search, "cache_search_results", store)
    monkeypatch.setattr(search, "clear_semantic_search_quota_warning", lambda **kwargs: None)

    def normalize(**kwargs):
        if normalization == "generation_changed":
            owners.dai.invalidate_document_access_index_cache_scope_keys(["user:reader"])
        if normalization == "failure":
            raise RuntimeError("Injected normalization failure.")
        return normalization == "repair_changed"

    monkeypatch.setattr(owners.documents, "normalize_document_revision_families", normalize)
    result = search.hybrid_search("policy", "reader", doc_scope="personal")
    assert result == [] and transport.call_count == 1
    assert store.call_count == (1 if normalization == "unchanged" else 0)


def test_document_search_plugin_uses_real_service_binding(owners, monkeypatch):
    plugin = importlib.import_module("semantic_kernel_plugins.document_search_plugin")
    service = importlib.import_module("functions_search_service")
    transport = Mock(return_value=[])
    monkeypatch.setattr(service, "hybrid_search", transport)
    monkeypatch.setattr(service, "_resolve_active_group_ids", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_resolve_public_workspace_ids", lambda *args, **kwargs: [])
    result = plugin.DocumentSearchPlugin._run_scope_limited_search(
        None, query="policy", user_id="reader", top_n=3, scope_requests=["personal"],
        document_ids=["document"], tags_filter=["policy"],
        active_group_ids=[], active_public_workspace_id=[],
    )
    assert result["result_count"] == 0 and transport.call_count == 1
    assert transport.call_args.kwargs["document_ids"] == ["document"]


def test_sdk_container_point_and_query_contract():
    container = SdkDocumentContainer()
    created = container.upsert_item({"id": "document", "user_id": "reader"})
    read = container.read_item("document", "document")
    assert isinstance(created, CosmosDict) and isinstance(read, CosmosDict)
    assert read["_etag"] == created["_etag"]
    replaced = container.replace_item(
        item="document", body={**read, "title": "Changed"}, etag=read["_etag"],
        match_condition=MatchConditions.IfNotModified,
    )
    assert isinstance(replaced, CosmosDict) and replaced["_etag"] != read["_etag"]
    with pytest.raises(CosmosHttpResponseError) as failure:
        container.replace_item(
            item="document", body=dict(read), etag=read["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    assert failure.value.status_code == 412
    queried = container.query_items("SELECT * FROM c")
    assert type(queried[0]) is dict and queried[0]["_etag"] == replaced["_etag"]


def test_agent_migration_catalog_retains_plain_query_records(owners, monkeypatch):
    routes = importlib.import_module("route_backend_agents")
    for name in (
        "cosmos_global_agents_container", "cosmos_group_agents_container", "cosmos_personal_agents_container",
    ):
        container = SdkDocumentContainer()
        container.upsert_item({"id": name, "name": "Agent", "user_id": "reader", "group_id": "group-a"})
        monkeypatch.setattr(routes, name, container)
    records = routes._load_all_agent_records_for_default_migration()
    assert {record["scope"] for record in records} == {"global", "group", "personal"}
    assert all(type(record["agent"]) is dict and "_etag" not in record["agent"] for record in records)
