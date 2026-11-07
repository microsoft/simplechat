# test_v2_document_source_runtime.py
"""
Real-owner retrieval, direct-read and replay regressions for workspace sources.
Version: 0.261.395
Implemented in: 0.261.395

Only storage, identity and embedding/search transport boundaries are replaced.
The installed SDK supplies point-response mappings; cloud network access is blocked.
"""

from contextlib import contextmanager, nullcontext
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from azure.cosmos._cosmos_responses import CosmosDict
import pytest

from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_revisions import AtomicMemoryContainer


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"


@contextmanager
def fresh_application_imports():
    """Keep earlier tests' partial app imports out of the real-owner probes."""
    roots = {path.stem for path in APP.iterdir()
             if path.suffix == ".py" or path.is_dir() and (path / "__init__.py").is_file()}
    previous = {name: module for name, module in sys.modules.copy().items()
                if name.split(".")[0] in roots}
    for name in previous:
        sys.modules.pop(name)
    try:
        with offline_app_imports():
            yield
    finally:
        for name in tuple(sys.modules):
            if name.split(".")[0] in roots:
                sys.modules.pop(name, None)
        sys.modules.update(previous)


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    with fresh_application_imports():
        search = importlib.import_module("functions_search")
        discovery = importlib.import_module("functions_document_source_discovery")
        access = importlib.import_module("content_screening.access")
        documents = importlib.import_module("functions_documents")
        contract = importlib.import_module("document_source_selection")
        catalog = [
            {"kind": "personal", "id": None, "name": "My workspace"},
            {"kind": "group", "id": "group-1", "name": "Group"},
            {"kind": "public", "id": "public-1", "name": "Public"},
        ]
        monkeypatch.setattr(discovery, "source_catalog", lambda *args, **kwargs: list(catalog))
        monkeypatch.setattr(documents, "normalize_document_revision_families", lambda **kwargs: False)
        monkeypatch.setattr(search, "read_embedding_settings", lambda: {})
        monkeypatch.setattr(search, "active_embedding_profile", lambda settings: SimpleNamespace(profile_id="offline"))
        monkeypatch.setattr(search, "embedding_query_slot", lambda profile: nullcontext())
        monkeypatch.setattr(search, "embedding_search_filter", lambda *args: None)
        monkeypatch.setattr(search, "generate_embedding", lambda *args, **kwargs: [0.1, 0.2, 0.3])
        monkeypatch.setattr(search, "get_public_source_workspace_ids", lambda user: [])
        monkeypatch.setattr(search, "CLIENTS", {
            "search_client_user": object(), "search_client_group": object(), "search_client_public": object(),
        })
        monkeypatch.setattr(search, "filter_available_results", lambda rows, **kwargs: rows)
        cached = Mock(return_value=None)
        queries = Mock(return_value=[])
        monkeypatch.setattr(search, "get_cached_search_results", cached)
        monkeypatch.setattr(search, "cache_search_results", Mock())
        monkeypatch.setattr(search, "search_with_embedding_profile", queries)
        yield SimpleNamespace(search=search, discovery=discovery, access=access, contract=contract,
                              catalog=catalog, cached=cached, queries=queries)


def selection(*sources):
    return {"version": 1, "mode": "selected", "sources": list(sources)}


def test_real_hybrid_search_keeps_scoped_union_and_includes_directory_hidden_public(runtime):
    intent = selection(
        {"kind": "workspace", "scope": {"kind": "group", "id": "group-1"}},
        {"kind": "tag", "tag": "policy", "scope": {"kind": "public", "id": "public-1"}},
    )
    result = runtime.search.hybrid_search("policy", "reader", document_source_selection=intent)
    assert result == []
    assert runtime.queries.call_count == 2
    clauses = [call.kwargs["filter"] for call in runtime.queries.call_args_list]
    assert any("group_id eq 'group-1'" in clause and "shared_group_ids" in clause for clause in clauses)
    assert any("public_workspace_id eq 'public-1'" in clause and "document_tags/any(t: t eq 'policy')" in clause for clause in clauses)
    assert all("user_id eq" not in clause for clause in clauses)


def test_real_hybrid_cache_separates_tag_intent_and_live_all_workspace_sets(runtime):
    def run(intent):
        runtime.search.hybrid_search("same question", "reader", document_source_selection=intent)
        return runtime.cached.call_args.args[0]
    first = run(selection({"kind": "tag", "tag": "one", "scope": {"kind": "personal"}}))
    second = run(selection({"kind": "tag", "tag": "two", "scope": {"kind": "personal"}}))
    all_intent = {"version": 1, "mode": "all", "sources": []}
    third = run(all_intent)
    runtime.catalog.append({"kind": "public", "id": "public-2", "name": "New"})
    fourth = run(all_intent)
    assert len({first, second, third, fourth}) == 4


def test_real_source_reader_rejects_out_of_union_sdk_metadata_and_preserves_legacy(runtime):
    document = CosmosDict({"id": "document", "user_id": "reader", "tags": ["finance"]}, response_headers={})
    reader = lambda **kwargs: document
    allowed = [{"kind": "tag", "tag": "policy", "scope": {"kind": "personal"}}]
    with runtime.contract.document_source_scope("reader", allowed):
        with pytest.raises(PermissionError, match="outside"):
            runtime.access.assert_document_available("document", user_id="reader", metadata_reader=reader)
        document["tags"] = ["policy"]
        result = runtime.access.assert_document_available("document", user_id="reader", metadata_reader=reader)
        assert result["id"] == "document" and type(result) is dict
    document["tags"] = ["finance"]
    result = runtime.access.assert_document_available("document", user_id="reader", metadata_reader=reader)
    assert result["tags"] == ["finance"]


def test_real_replay_restores_intent_not_stale_resolved_workspace_ids(runtime):
    routes = importlib.import_module("route_backend_conversations")
    intent = {"version": 1, "mode": "all", "sources": []}
    result = routes._build_replayed_document_context({"workspace_search": {
        "document_source_selection": intent,
        "active_group_ids": ["revoked-group"], "active_public_workspace_ids": ["removed-public"],
        "document_scope": "all", "tags": ["old"], "requested_document_ids": ["old-document"],
    }})
    assert result["document_source_selection"] == intent
    assert result["hybrid_search"] and result["document_context_requested"]
    assert not any(key in result for key in ("active_group_ids", "active_public_workspace_ids", "selected_document_ids", "tags"))


def test_real_source_owners_keep_sdk_points_release_proofs_and_plain_query_rows(monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    from content_screening import access
    from document_source_selection import document_source_scope
    from test_content_screening_access import ScreeningAccessFixture

    case = ScreeningAccessFixture(methodName="runTest")
    case.setUp()
    try:
        personal = AtomicMemoryContainer("id")
        scans = AtomicMemoryContainer("id")
        saved = personal.upsert_item({**case.document, "tags": ["policy"]})
        for scan in case.scans.documents.values():
            scans.upsert_item(scan)
        case.config.cosmos_user_documents_container = personal
        case.config.cosmos_content_screening_container = scans
        assert isinstance(saved, CosmosDict)
        with case.app.test_request_context():
            with document_source_scope("user-1", [{"kind": "tag", "tag": "policy", "scope": {"kind": "personal"}}]):
                current = access.assert_document_available("document-1", "user-1")
                located = access._resolve_blob_document("user-documents", case.document["blob_path"], "user-1")
                native = access._resolve_native_evidence(
                    {"source": "personal", "filename": "reviewed.txt"}, "user-1", resolve_filename=True,
                )
                assert current["id"] == located["id"] == native["id"] == "document-1"
                assert all(type(document) is dict for document in (current, located, native))
            with document_source_scope("user-1", [{"kind": "tag", "tag": "other", "scope": {"kind": "personal"}}]):
                with pytest.raises(PermissionError, match="outside"):
                    access._read_authorized_document("document-1", "user-1")
        assert len(scans.items) == 1 and personal.queries
    finally:
        case.doCleanups()


def test_worker_execution_rebinds_canonical_sources_instead_of_trusting_old_ids(runtime):
    from concurrent.futures import ThreadPoolExecutor
    from public_chat_scope import public_chat_execution_scope
    intent = selection({"kind": "tag", "tag": "policy", "scope": {"kind": "personal"}})
    def worker():
        with public_chat_execution_scope(
            {"seeds": {"document_source_selection": intent}, "conversation_id": "chat"}, "reader", {},
        ):
            with pytest.raises(PermissionError):
                runtime.access.assert_document_available(
                    "outside", "reader",
                    metadata_reader=lambda **kwargs: CosmosDict({"id": "outside", "user_id": "reader", "tags": []}, response_headers={}),
                )
    with ThreadPoolExecutor(max_workers=1) as pool:
        completed = pool.submit(worker).result(timeout=10)
    assert completed is None
