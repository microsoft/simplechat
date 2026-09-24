# test_group_document_count_predicate.py
"""
Functional test for the group document count shown before a group is deleted.
Version: 0.261.153
Implemented in: 0.261.153

The owner is asked to remove the group's documents before deleting it, so the count
must be the group's own documents exactly as the group document list shows them.
``count_current_group_documents`` and ``load_group_document_browser_documents`` share
``current_group_document_records``: each document family's current revision, per
owning group, and never a revision marked ``is_current_version: false``.

This test runs both for real, in ``test_group_document_read_apis``'s environment, over
superseded revisions, a legacy family without revision fields, a document still
processing, a family whose only revision is not current, documents shared into the
group and another group's document, and pins that the count equals the list's owned
rows, while the list itself also carries the shared rows the count leaves out.
"""

import ast
from pathlib import Path

import pytest

from test_group_document_read_apis import document, environment  # noqa: F401 - the shared fixture


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


def legacy_revision(document_id, version):
    """A revision stored before revision families: grouped by file name, with no current flag."""
    record = document(document_id, version=version, file_name="legacy-handbook.pdf")
    record.pop("revision_family_id")
    record.pop("is_current_version")
    return record


def seed_library(environment):
    records = environment.source.records
    records.clear()
    records.update({
        "report-v1": document("report-v1", revision_family_id="report", version=1, is_current_version=False),
        "report-v2": document("report-v2", revision_family_id="report", version=2, is_current_version=False),
        "report-v3": document("report-v3", revision_family_id="report", version=3),
        "legacy-1": legacy_revision("legacy-1", 1),
        "legacy-2": legacy_revision("legacy-2", 2),
        "memo": document("memo"),
        "draft": document("draft", percentage_complete=40, status="Processing"),
        "orphan": document("orphan", is_current_version=False),
        "shared-in": document("shared-in", "group-b", shared_group_ids=["group-a,approved"]),
        "shared-held": document("shared-held", "group-b", shared_group_ids=["group-a,not_approved"]),
        "elsewhere": document("elsewhere", "group-b"),
    })


def listed(environment, group_id="group-a"):
    return environment.helper.load_group_document_browser_documents("reader", group_id)


def test_the_count_is_the_owned_rows_of_the_group_document_list(environment):
    seed_library(environment)
    rows = listed(environment)
    owned = sorted(row["id"] for row in rows if row["owner_group_id"] == "group-a")
    assert owned == ["draft", "legacy-2", "memo", "report-v3"]
    assert sorted(row["id"] for row in rows if row["owner_group_id"] != "group-a") == ["shared-held", "shared-in"]
    assert environment.helper.count_current_group_documents("group-a") == len(owned) == 4


def test_the_count_of_the_sharing_group_includes_what_it_shares(environment):
    seed_library(environment)
    environment.groups["group-b"]["users"].append({"userId": "reader"})
    owned = [row for row in listed(environment, "group-b") if row["owner_group_id"] == "group-b"]
    assert sorted(row["id"] for row in owned) == ["elsewhere", "shared-held", "shared-in"]
    assert environment.helper.count_current_group_documents("group-b") == 3


def test_an_empty_library_counts_zero(environment):
    environment.source.records.clear()
    assert environment.helper.count_current_group_documents("group-a") == 0
    assert listed(environment) == []


def test_the_count_changes_as_the_list_does(environment):
    seed_library(environment)
    environment.source.records["report-v4"] = document("report-v4", revision_family_id="report", version=4)
    environment.source.records["report-v3"]["is_current_version"] = False
    environment.source.records.pop("memo")
    owned = [row["id"] for row in listed(environment) if row["owner_group_id"] == "group-a"]
    assert "report-v4" in owned and "memo" not in owned
    assert environment.helper.count_current_group_documents("group-a") == len(owned) == 3


def _function(file_name, name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _calls(function):
    return {
        node.func.id for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize("file_name,function_name,callee", [
    ("functions_group_document_reads.py", "load_group_document_browser_documents", "current_group_document_records"),
    ("functions_group_document_reads.py", "count_current_group_documents", "current_group_document_records"),
    ("functions_group_document_reads.py", "count_current_group_documents", "_query_group_document_records"),
    ("functions_group_insights.py", "read_group_file_count", "count_current_group_documents"),
])
def test_the_list_and_the_count_share_one_predicate(file_name, function_name, callee):
    assert callee in _calls(_function(file_name, function_name))
