#!/usr/bin/env python3
# test_v2_control_center_activity_display.py
"""
Functional tests for the V2 Activity Logs presentation: labels, summaries and names.
Version: 0.261.296
Implemented in: 0.261.296

The V2 Activity Logs table showed raw user and group IDs, so administrators could not tell
who did what or filter by a person they knew by name. The classic Control Center resolved
names from user_settings. These tests run the real, dependency-neutral display module
against fake containers: per-writer summaries, actor and workspace resolution, batched and
cached name lookups, the person and workspace pickers' searches, and CSV columns.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.cosmos_query_guard import assert_cosmos_query_supported
from test_support.versioning import assert_app_version_at_least


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


display = _load("activity_display", "functions_control_center_activity_display.py")
activity = _load("activity_queries_for_display", "functions_control_center_activity.py")


class Container:
    """Answers name lookups and searches from in-memory documents, recording every query."""

    def __init__(self, documents):
        self.documents = {document["id"]: document for document in documents}
        self.queries = []

    def query_items(self, query, parameters, enable_cross_partition_query):
        assert enable_cross_partition_query is True
        assert_cosmos_query_supported(query)
        params = {item["name"]: item["value"] for item in parameters}
        self.queries.append((query, params))
        if "ARRAY_CONTAINS(@ids, c.id)" in query:
            return iter([doc for doc_id, doc in self.documents.items() if doc_id in params["@ids"]])
        term = params["@term"].casefold()
        fields = ("display_name", "email") if "c.display_name" in query else ("name",)
        matches = [
            doc for doc in self.documents.values()
            if doc["id"] == params["@term"] or any(term in str(doc.get(field, "")).casefold() for field in fields)
        ]
        return iter(matches[:params["@limit"]])


def test_catalog_labels_categories_and_unknown_types():
    assert display.activity_label("token_usage") == "Token usage"
    assert display.activity_category("group_member_deleted") == "groups"
    assert display.activity_label("brand_new_event") == "Brand new event"
    assert display.activity_category("brand_new_event") == "other"
    assert display.activity_label(None) == "Unknown activity"
    catalog = display.activity_type_catalog()
    assert len(catalog) == len(display.ACTIVITY_TYPES)
    order = list(display.ACTIVITY_CATEGORY_LABELS)
    assert [order.index(item["category"]) for item in catalog] == sorted(order.index(item["category"]) for item in catalog)
    assert all(item["category_label"] == display.ACTIVITY_CATEGORY_LABELS[item["category"]] for item in catalog)
    facets = display.label_activity_facets([{"activity_type": "user_login", "count": 4}])
    assert facets == [{"activity_type": "user_login", "count": 4, "label": "User login", "category": "sign_in"}]


@pytest.mark.parametrize("record, summary, detail, facts, status", [
    ({"activity_type": "user_login", "login_method": "azure_ad"}, "Signed in", "Method: azure_ad",
     {"Login method": "azure_ad"}, None),
    ({"activity_type": "chat_activity", "message_type": "user_message", "chat_context": "personal",
      "message_length": 1234, "conversation_id": "conv-1", "has_document_search": True,
      "additional_context": {"conversation_source": "standard_chat", "agent_name": "Helper"}},
     "User message · Standard chat · Personal", "1,234 characters",
     {"Conversation ID": "conv-1", "Document search": "Yes", "Agent": "Helper"}, None),
    ({"activity_type": "conversation_creation", "conversation": {"title": "Q3 plan", "conversation_id": "c1",
                                                                 "tags": ["finance", 3, None]}},
     "Q3 plan", "finance, 3", {"Conversation ID": "c1"}, None),
    ({"activity_type": "document_creation", "document": {"file_name": "report.pdf", "file_type": ".pdf",
                                                         "file_size_bytes": 2048, "page_count": 12,
                                                         "status": "Processing failed: timeout"}},
     "report.pdf", "PDF · 2.0 KB · 12 pages", {"Pages": "12", "Processing status": "Processing failed: timeout"},
     "failed"),
    ({"activity_type": "document_metadata_update", "document": {"file_name": "a.docx"},
      "updated_fields": {"title": "x", "authors": []}}, "a.docx", "Updated: authors, title", {}, None),
    ({"activity_type": "token_usage", "token_type": "chat",
      "usage": {"total_tokens": 12345, "model": "gpt-4o", "prompt_tokens": 12000, "completion_tokens": 345}},
     "12,345 tokens · gpt-4o", "Chat · prompt 12,000 · completion 345", {"Model": "gpt-4o"}, None),
    ({"activity_type": "token_usage", "token_type": "embedding", "usage": {"total_tokens": 900},
      "embedding_details": {"file_name": "notes.txt"}}, "900 tokens", "Embedding · notes.txt",
     {"File": "notes.txt"}, None),
    ({"activity_type": "group_status_change", "group": {"group_id": "g1", "group_name": "Research"},
      "status_change": {"old_status": "active", "new_status": "upload_disabled", "reason": "Audit"}},
     "Active → Upload disabled", "Audit", {"Reason": "Audit", "New status": "upload_disabled"}, None),
    ({"activity_type": "group_member_deleted", "removed_member": {"name": "Bo", "email": "bo@example.test"},
      "group": {"group_id": "g1", "group_name": "Research"}}, "Removed Bo", "Research",
     {"Member": "Bo", "Member email": "bo@example.test"}, None),
    ({"activity_type": "update_member_role", "member_name": "Cy", "old_role": "User", "new_role": "Admin",
      "group_id": "g1", "group_name": "Research"}, "Cy: User → Admin", "Research", {"New role": "Admin"}, None),
    ({"activity_type": "public_add_member_directly", "member_name": "Di", "member_role": "Admin",
      "public_workspace_id": "p1", "public_workspace_name": "Library"}, "Added Di", "Role: Admin · Library",
     {"Role": "Admin"}, None),
    ({"activity_type": "delete_all_documents_approved", "description": "All documents deleted",
      "requester_email": "req@example.test", "approver_email": "ok@example.test", "documents_deleted": 7,
      "approval_id": "ap-1"}, "All documents deleted", "Requested by req@example.test · approved by ok@example.test",
     {"Documents deleted": "7", "Approval ID": "ap-1"}, None),
    ({"activity_type": "file_sync", "action": "sync_completed", "workspace_context": {"source_name": "SharePoint"},
      "additional_context": {"counts": {"scanned": 10, "failed": 0, "queued": 2}}},
     "Sync completed · SharePoint", "Scanned 10 · Queued 2 · Failed 0", {"Source": "SharePoint"}, None),
    ({"activity_type": "data_management", "action": "job_finished",
      "additional_context": {"operation": "backup", "status": "failed", "job_id": "job-9"}},
     "Job finished · Backup", "Failed · Job job-9", {"Job ID": "job-9"}, "failed"),
    ({"activity_type": "workflow_run", "entity": {"name": "Nightly"}, "workspace_type": "personal",
      "run": {"status": "failed", "trigger_source": "schedule", "error": "Timeout"}},
     "Nightly", "Personal · Failed · Schedule", {"Error": "Timeout"}, "failed"),
    ({"activity_type": "agent_run", "agent": {"display_name": "Analyst"}, "workspace_type": "group",
      "model_deployment_name": "gpt-4o"}, "Analyst", "Group · gpt-4o", {"Model": "gpt-4o"}, None),
    ({"activity_type": "governance", "action": "policy_updated", "workspace_context": {"scope": "model", "target_id": "m1"}},
     "Policy updated", "Model · m1", {"Target": "m1"}, None),
    ({"activity_type": "brand_new_event", "description": "Something happened"}, "Something happened", "", {}, None),
])
def test_descriptions_for_each_writer_shape(record, summary, detail, facts, status):
    view = display.describe_activity(record)
    assert view["summary"] == summary
    assert view["detail"] == detail
    recorded = {fact["label"]: fact["value"] for fact in view["facts"]}
    for label, value in facts.items():
        assert recorded.get(label) == value, (label, recorded)
    assert view["status"] == status
    assert view["label"] == display.activity_label(record["activity_type"])
    assert all(isinstance(fact["value"], str) and fact["value"] for fact in view["facts"])


def test_malformed_records_never_raise():
    for record in (None, [], {"activity_type": 7}, {"activity_type": "document_creation", "document": "x"},
                   {"activity_type": "token_usage", "usage": [1, 2]},
                   {"activity_type": "chat_activity", "additional_context": "bad", "message_length": "long"},
                   {"activity_type": "group_status_change", "status_change": None, "group": "Research"}):
        view = display.present_activity_record(record, display.empty_activity_names())
        assert view["summary"] and view["actor"]["kind"] in {"user", "system"}


def test_actor_resolution_order_and_system_actors():
    assert display.activity_actor({"user_id": "u1", "admin_user_id": "a1"})["id"] == "u1"
    assert display.activity_actor({"changed_by": {"user_id": "a2", "email": "a2@example.test"}}) == {
        "id": "a2", "email": "a2@example.test", "kind": "user"}
    assert display.activity_actor({"requester_id": "r1", "requester_email": "r@example.test"})["id"] == "r1"
    assert display.activity_actor({"removed_by": {"user_id": "x1"}})["id"] == "x1"
    assert display.activity_actor({"user_id": "system"}) == {"id": "", "email": "", "kind": "system"}
    assert display.activity_actor({"user_id": "system", "admin_email": "ops@example.test"})["kind"] == "user"
    assert display.activity_actor({})["kind"] == "system"


def test_actor_fields_match_the_person_filter():
    """The Person column and the Person filter must agree on who acted."""
    dotted = tuple(".".join(path) for path in display.ACTOR_ID_PATHS)
    assert dotted == activity.ACTIVITY_ACTOR_FIELDS


def test_workspace_resolution_covers_every_writer_shape():
    assert display.activity_workspace({"workspace_context": {"group_id": "g1"}, "workspace_type": "group"}) == {
        "type": "group", "id": "g1", "recorded_name": ""}
    assert display.activity_workspace({"group": {"group_id": "g2", "group_name": "Ops"}})["recorded_name"] == "Ops"
    assert display.activity_workspace({"group_id": "g3", "group_name": "Lab"})["id"] == "g3"
    status = display.activity_workspace({"workspace_type": "public_workspace",
                                         "public_workspace": {"workspace_id": "p1", "workspace_name": "Library"},
                                         "workspace_context": {"public_workspace_id": "p1"}})
    assert status == {"type": "public", "id": "p1", "recorded_name": "Library"}
    assert display.activity_workspace({"workspace_type": "personal"})["type"] == "personal"
    assert display.activity_workspace({"workspace_type": "admin"})["type"] == "admin"
    assert display.activity_workspace({})["type"] == ""
    # Public membership audits (removed, requested, canceled) nest the workspace this way.
    removed = display.activity_workspace({"activity_type": "public_member_removed",
                                          "public_workspace": {"public_workspace_id": "p2",
                                                               "public_workspace_name": "Archive"}})
    assert removed == {"type": "public", "id": "p2", "recorded_name": "Archive"}
    # Public workspace ownership approvals store only a bare workspace_id.
    owner = display.activity_workspace({"type": "workspace_ownership_change",
                                        "activity_type": "transfer_ownership_approved",
                                        "workspace_id": "p3", "workspace_name": "Docs"})
    assert owner == {"type": "public", "id": "p3", "recorded_name": "Docs"}
    # Group user agreements store workspace_context.group_workspace_id.
    agreement = display.activity_workspace({"workspace_type": "group",
                                            "workspace_context": {"group_workspace_id": "g9", "workspace_name": None}})
    assert agreement == {"type": "group", "id": "g9", "recorded_name": ""}
    # A bare workspace_id on a record that says it is a group is not read as a public workspace.
    assert display.activity_workspace({"workspace_type": "group", "workspace_id": "x"}) == {
        "type": "group", "id": "", "recorded_name": ""}


def test_workspace_locations_match_the_workspace_filters():
    """A workspace shown in a row must be one its Workspace filter matches."""
    assert [".".join(path) for path in display.GROUP_ID_PATHS] == list(activity.GROUP_REFERENCE_FIELDS)
    assert [".".join(path) for path in display.PUBLIC_ID_PATHS] + ["workspace_id"] == list(
        activity.PUBLIC_REFERENCE_FIELDS)


def test_name_lookups_are_batched_cached_and_mark_missing_entries():
    clock = [100.0]
    users = Container([{"id": "u1", "display_name": "Ada Admin", "email": "ada@example.test"}])
    groups = Container([{"id": "g1", "name": "Research (renamed)"}])
    public = Container([])
    cache = display.ActivityNameCache(ttl_seconds=60, max_entries=10, clock=lambda: clock[0])
    records = [
        {"id": "1", "user_id": "u1", "workspace_context": {"group_id": "g1"}, "workspace_type": "group"},
        {"id": "2", "user_id": "u-gone", "group": {"group_id": "g1", "group_name": "Research"}},
        {"id": "3", "changed_by": {"user_id": "u1"}, "workspace_context": {"public_workspace_id": "p-gone"},
         "workspace_type": "public_workspace", "public_workspace": {"workspace_name": "Old library"}},
    ]
    selected = activity.parse_activity_filters({"user_id": "u-filter", "workspace_type": "group", "workspace_id": "g1"})
    kwargs = {"user_container": users, "groups_container": groups, "public_container": public, "cache": cache}
    names = display.resolve_activity_names(records, selected, **kwargs)
    assert len(users.queries) == len(groups.queries) == len(public.queries) == 1
    assert sorted(users.queries[0][1]["@ids"]) == ["u-filter", "u-gone", "u1"]
    assert names["people"]["u1"] == {"display_name": "Ada Admin", "email": "ada@example.test"}
    assert names["people"]["u-gone"] is None
    views = display.present_activity_rows(records, names)
    assert views[0]["actor"] == {"id": "u1", "name": "Ada Admin", "email": "ada@example.test",
                                 "kind": "user", "resolved": True}
    assert views[0]["workspace"] == {"type": "group", "id": "g1", "name": "Research (renamed)", "resolved": True}
    assert views[1]["actor"]["resolved"] is False and views[1]["actor"]["name"] == ""
    assert views[2]["workspace"] == {"type": "public", "id": "p-gone", "name": "Old library", "resolved": False}
    labels = display.activity_filter_labels(selected, names)
    assert labels["person"] == {"id": "u-filter", "name": "", "email": "", "resolved": False}
    assert labels["workspace"] == {"type": "group", "id": "g1", "name": "Research (renamed)", "resolved": True}
    display.resolve_activity_names(records, selected, **kwargs)
    assert len(users.queries) == len(groups.queries) == len(public.queries) == 1
    clock[0] += 61
    display.resolve_activity_names(records[:1], None, **kwargs)
    assert len(users.queries) == 2 and len(groups.queries) == 2
    for index in range(20):
        cache.set("person", f"extra-{index}", None)
    assert len(cache.entries) == 10


def test_lookups_split_large_pages_into_batches():
    users = Container([{"id": f"u{index}", "display_name": f"User {index}"} for index in range(150)])
    records = [{"id": str(index), "user_id": f"u{index}"} for index in range(150)]
    names = display.resolve_activity_names(records, user_container=users, groups_container=Container([]),
                                           public_container=Container([]))
    assert [len(params["@ids"]) for _, params in users.queries] == [100, 50]
    assert names["people"]["u149"]["display_name"] == "User 149"


def test_csv_columns_use_the_presentation():
    view = display.present_activity_record(
        {"activity_type": "token_usage", "user_id": "u1", "usage": {"total_tokens": 5, "model": "m"},
         "token_type": "chat", "workspace_context": {"group_id": "g1"}, "workspace_type": "group"},
        {"people": {"u1": {"display_name": "Ada", "email": "ada@example.test"}}, "groups": {"g1": "Research"},
         "public_workspaces": {}},
    )
    assert display.activity_csv_columns(view) == (
        "Ada", "ada@example.test", "Token usage", "5 tokens · m (Chat)", "g1", "Research")


def test_people_and_workspace_searches_are_parameterized_ranked_and_bounded():
    users = Container([
        {"id": "u2", "display_name": "Janet Smith", "email": "janet@example.test"},
        {"id": "u1", "display_name": "Jane Doe", "email": "jane@example.test"},
        {"id": "u3", "display_name": "Mary-Jane Ray", "email": "mj@example.test"},
    ])
    assert display.search_activity_people(users, "j") == []
    assert users.queries == []
    people = display.search_activity_people(users, "jane")
    assert [person["id"] for person in people] == ["u1", "u2", "u3"]
    query, params = users.queries[-1]
    assert params == {"@limit": display.ACTIVITY_LOOKUP_LIMIT, "@term": "jane"} and "jane" not in query
    assert [person["id"] for person in display.search_activity_people(users, "u3")] == ["u3"]
    exact = display.search_activity_people(users, "jane@example.test")
    assert exact[0]["id"] == "u1"
    many = Container([{"id": f"p{index}", "display_name": f"Pat {index}"} for index in range(40)])
    ids, truncated = display.search_activity_people_ids(many, "pat")
    assert len(ids) == display.ACTIVITY_SEARCH_PEOPLE_MAX and truncated is True
    assert display.search_activity_people_ids(many, " ") == ([], False)
    groups = Container([{"id": "g1", "name": "Finance"}, {"id": "g2", "name": "Finance archive"}])
    public = Container([{"id": "p1", "name": "Finance library"}])
    found = display.search_activity_workspaces(groups, public, "finance")
    assert [(item["type"], item["id"]) for item in found] == [("group", "g1"), ("group", "g2"), ("public", "p1")]
    assert display.search_activity_workspaces(groups, public, "p1") == [{"type": "public", "id": "p1", "name": "Finance library"}]


def test_version_is_at_least_the_implementation_version():
    assert_app_version_at_least("0.261.296")
