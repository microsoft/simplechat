# test_v2_document_source_selection.py
"""
Runtime regressions for workspace-sidebar discovery and additive source admission.
Version: 0.261.400
Implemented in: 0.261.395
Real configuration container naming covered in: 0.261.400

Real contract/discovery modules run with storage and identity boundaries replaced;
no cloud clients or network calls are initialized.
"""

import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"


def dependency(monkeypatch, name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def sources(monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    contract = importlib.import_module("document_source_selection")
    discovery = importlib.import_module("functions_document_source_discovery")
    settings = {"enable_group_workspaces": True, "enable_public_workspaces": True}
    groups = [{"id": f"group-{i}", "name": f"Group {i:03}"} for i in range(65)]
    public = [{"id": "public-1", "name": "Policy library"}]
    conversation = {"scope_locked": False}
    config = ModuleType("config")
    config.cosmos_conversations_container = SimpleNamespace(query_items=Mock(side_effect=lambda **kwargs: [conversation]))
    for kind in ("user_documents", "group_documents", "public_documents"):
        setattr(config, f"cosmos_{kind}_container", SimpleNamespace(query_items=Mock(return_value=[])))
    monkeypatch.setitem(sys.modules, "config", config)
    dependency(monkeypatch, "functions_settings", get_settings=lambda: settings)
    dependency(monkeypatch, "functions_group", get_user_groups=lambda user_id: groups)
    dependency(monkeypatch, "functions_public_workspaces",
               get_all_public_workspaces=lambda: public,
               resolve_public_chat_workspace_ids=lambda *args, **kwargs: [row["id"] for row in public])
    documents = {"doc-1": {"id": "doc-1", "group_id": "group-1"}}
    dependency(monkeypatch, "content_screening.access",
               assert_document_available=lambda document_id, **kwargs: documents[document_id],
               public_document_payload=lambda row: row)
    return SimpleNamespace(contract=contract, discovery=discovery, settings=settings, groups=groups,
                           public=public, conversation=conversation, config=config, documents=documents)


def selected(*items):
    return {"version": 1, "mode": "selected", "sources": list(items)}


def workspace(kind, identity=None):
    return {"kind": "workspace", "scope": {"kind": kind, **({"id": identity} if identity else {})}}


def test_additive_union_is_scoped_and_has_no_implicit_personal_source(sources):
    value = selected(
        workspace("group", "group-1"),
        {"kind": "tag", "tag": "policy", "scope": {"kind": "public", "id": "public-1"}},
        {"kind": "document", "id": "doc-1", "scope": {"kind": "group", "id": "group-1"}},
    )
    intent, admitted = sources.discovery.admit_document_source_selection(value, "reader")
    assert intent == value
    group = sources.contract.source_union_filter(admitted, "group")
    public = sources.contract.source_union_filter(admitted, "public")
    personal = sources.contract.source_union_filter(admitted, "personal")
    assert " or " in group and "document_id eq 'doc-1'" in group
    assert "group_id eq 'group-1'" in group
    assert public == "((public_workspace_id eq 'public-1' and document_tags/any(t: t eq 'policy')))"
    assert personal == "false"
    projection = sources.contract.selection_scope_fields(admitted)
    assert projection["selected_document_ids"] == [] and projection["tags"] == []


def test_all_resolves_complete_live_scope_and_respects_conversation_locks(sources):
    intent = {"version": 1, "mode": "all", "sources": []}
    _, first = sources.discovery.admit_document_source_selection(intent, "reader")
    assert len(first) == 67
    sources.public.append({"id": "public-2", "name": "New public"})
    _, second = sources.discovery.admit_document_source_selection(intent, "reader")
    assert len(second) == 68
    sources.conversation.update(scope_locked=True, locked_contexts=[{"scope": "public", "id": "public-1"}])
    _, locked = sources.discovery.admit_document_source_selection(intent, "reader", conversation_id="chat")
    assert locked == [workspace("public", "public-1")]


def test_revocation_and_forged_document_scope_fail_explicitly(sources):
    with pytest.raises(sources.contract.DocumentSourceSelectionError, match="no longer available"):
        sources.discovery.admit_document_source_selection(selected(workspace("group", "forged")), "reader")
    with pytest.raises(sources.contract.DocumentSourceSelectionError, match="does not belong"):
        sources.discovery.admit_document_source_selection(selected({
            "kind": "document", "id": "doc-1", "scope": {"kind": "public", "id": "public-1"},
        }), "reader")
    saved = selected(workspace("group", "group-1"))
    sources.groups[:] = []
    with pytest.raises(sources.contract.DocumentSourceSelectionError):
        sources.discovery.admit_document_source_selection(saved, "reader")


@pytest.mark.parametrize("value", [
    {}, {"version": True, "mode": "all", "sources": []},
    {"version": 2, "mode": "all", "sources": []},
    {"version": 1, "mode": "selected", "sources": []},
    {"version": 1, "mode": "all", "sources": [workspace("personal")]},
    selected({"kind": "tag", "tag": "x", "scope": {"kind": "public"}}),
    selected({"kind": "document", "id": "", "scope": {"kind": "personal"}}),
])
def test_invalid_intent_never_falls_back_to_all(sources, value):
    with pytest.raises(sources.contract.DocumentSourceSelectionError):
        sources.contract.normalize_document_source_selection(value)


def test_tag_identity_union_and_odata_escaping(sources):
    value = selected(
        {"kind": "tag", "tag": "owner's policy", "scope": {"kind": "personal"}},
        {"kind": "tag", "tag": "policy", "scope": {"kind": "personal"}},
        {"kind": "tag", "tag": "policy", "scope": {"kind": "public", "id": "public-1"}},
    )
    normalized = sources.contract.normalize_document_source_selection(value)
    clause = sources.contract.source_union_filter(normalized["sources"], "personal")
    assert "owner''s policy" in clause and " or " in clause
    assert len(normalized["sources"]) == 3


def test_directory_is_independently_paged_and_finds_name_only_matches(sources):
    first = sources.discovery.discover_document_sources("reader", sources.settings)
    second = sources.discovery.discover_document_sources("reader", sources.settings, workspace_offset=40)
    assert first["matching_workspace_count"] == 67
    assert len(first["workspaces"]) == 40 and len(second["workspaces"]) == 27
    assert first["workspace_next"] == 40 and second["workspace_next"] is None
    filtered = sources.discovery.discover_document_sources("reader", sources.settings, query=" POLICY ")
    assert filtered["matching_workspace_count"] == 1
    assert filtered["workspaces"][0]["match_reason"] == "workspace name"
    assert filtered["workspaces"][0]["id"] == "public-1"


def test_document_matches_survive_beyond_suggestion_caps_and_pages(sources):
    personal = sources.config.cosmos_user_documents_container
    def query_items(**kwargs):
        query = kwargs["query"]
        if "GROUP BY" in query:
            return [{"owner": "reader", "count": 90}]
        offset = next(p["value"] for p in kwargs["parameters"] if p["name"] == "@offset")
        limit = next(p["value"] for p in kwargs["parameters"] if p["name"] == "@limit")
        return [{"id": f"policy-{i}", "file_name": f"Policy {i}.pdf"} for i in range(offset, min(offset + limit, 90))]
    personal.query_items.side_effect = query_items
    first = sources.discovery.discover_document_sources("reader", sources.settings, query="policy")
    second = sources.discovery.discover_document_sources("reader", sources.settings, query="policy", source_offset=40)
    assert first["source_total"] == second["source_total"] == 90
    assert first["source_next"] == 40 and second["source_next"] == 80
    assert second["documents"][0]["document"]["id"] == "policy-40"
    assert {s["kind"] for s in first["workspaces"]} == {"personal", "public"}
    for call in personal.query_items.call_args_list:
        assert "CONTAINS(c.title" in call.kwargs["query"] and "c.tags" in call.kwargs["query"]
        assert "chunk_text" not in call.kwargs["query"] and "SELECT *" not in call.kwargs["query"]


def test_discovery_failure_is_not_an_empty_success(sources):
    sources.config.cosmos_user_documents_container.query_items.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        sources.discovery.discover_document_sources("reader", sources.settings)


def test_legacy_conflicts_are_rejected_without_overriding_canonical_intent(sources):
    value = selected(workspace("public", "public-1"))
    with pytest.raises(sources.contract.DocumentSourceSelectionError, match="conflict"):
        sources.discovery.prepare_document_source_selection(
            {"document_source_selection": value, "active_group_ids": ["group-1"]},
            "reader", sources.settings,
        )
    request = {"document_source_selection": value, "hybrid_search": True}
    sources.discovery.prepare_document_source_selection(request, "reader", sources.settings)
    assert request["active_public_workspace_ids"] == ["public-1"] and request["active_group_ids"] == []


def test_approved_group_shares_are_selectable_without_widening_to_other_workspaces(sources):
    sources.documents["shared"] = {"id": "shared", "group_id": "outside", "shared_group_ids": ["group-1,approved"]}
    value = selected({"kind": "document", "id": "shared", "scope": {"kind": "group", "id": "group-1"}})
    _, admitted = sources.discovery.admit_document_source_selection(value, "reader")
    clause = sources.contract.source_union_filter(admitted, "group")
    assert "shared_group_ids/any(g: g eq 'group-1,approved')" in clause
    sources.documents["shared"]["shared_group_ids"] = ["group-1,pending"]
    with pytest.raises(sources.contract.DocumentSourceSelectionError):
        sources.discovery.admit_document_source_selection(value, "reader")


def test_shared_metadata_counts_and_document_rows_use_the_same_workspace(sources):
    sources.settings["enable_file_sharing"] = True
    group = sources.config.cosmos_group_documents_container
    def query_items(**kwargs):
        query = kwargs["query"]
        if "GROUP BY REPLACE" in query:
            return [{"owner": "group-1", "count": 1}]
        if "GROUP BY" in query or "DISTINCT" in query:
            return []
        assert "ARRAY_CONTAINS(c.shared_group_ids, @approved_owner)" in query
        return [{"id": "shared", "file_name": "Shared policy.pdf"}]
    group.query_items.side_effect = query_items
    result = sources.discovery.discover_document_sources(
        "reader", sources.settings, query="policy", workspace="group:group-1",
    )
    assert result["source_total"] == 1
    assert result["documents"][0]["scope"]["id"] == "group-1"
    personal_queries = sources.config.cosmos_user_documents_container.query_items.call_args_list
    assert "ARRAY_CONTAINS(c.shared_user_ids, @approved_user)" in personal_queries[0].kwargs["query"]


def test_direct_reads_respect_scoped_tag_document_workspace_union_and_restore_context(sources):
    contract = sources.contract
    allowed = [
        {"kind": "tag", "tag": "policy", "scope": {"kind": "personal"}},
        workspace("group", "group-1"),
        {"kind": "document", "id": "explicit", "scope": {"kind": "public", "id": "public-1"}},
    ]
    with contract.document_source_scope("reader", allowed):
        for document in (
            {"id": "tagged", "user_id": "reader", "tags": ["policy"]},
            {"id": "group", "group_id": "group-1"},
            {"id": "explicit", "public_workspace_id": "public-1"},
        ):
            contract.assert_document_in_source_scope(document, "reader")
        for document in (
            {"id": "untagged", "user_id": "reader"},
            {"id": "other", "public_workspace_id": "public-1", "tags": ["policy"]},
            {"id": "outside", "group_id": "group-2"},
        ):
            with pytest.raises(PermissionError):
                contract.assert_document_in_source_scope(document, "reader")
        with pytest.raises(PermissionError):
            contract.assert_document_in_source_scope({"id": "group", "group_id": "group-1"}, "other-reader")
    contract.assert_document_in_source_scope({"id": "unrestricted"}, "reader")
