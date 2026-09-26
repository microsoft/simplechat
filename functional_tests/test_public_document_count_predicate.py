# test_public_document_count_predicate.py
"""
Functional test for the public workspace document count shown in the Settings danger zone.
Version: 0.261.181
Implemented in: 0.261.181

The owner's danger zone shows how many documents the workspace holds, so the count must
be the workspace's documents exactly as the public document list shows them.
``count_current_public_documents`` and ``load_public_document_browser_documents`` share
``current_public_document_records``: each document family's current revision, and never
a revision marked ``is_current_version: false``.

This test runs both for real, in ``test_public_document_read_apis``'s environment, over
superseded revisions, a legacy family without revision fields, a document still
processing, a family whose only revision is not current and another workspace's
document, and pins that the count equals the list's rows. It also records what the
classic ``/fileCount`` counts instead, for the danger zone's copy: every stored document
record of the workspace, superseded revisions and non-current records included.
"""

import ast
from pathlib import Path

import pytest

from test_public_document_read_apis import document, environment as environment  # noqa: F401 - the shared fixture

_PYTEST_FIXTURES = (environment,)


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
        "elsewhere": document("elsewhere", "public-b"),
    })


def listed(environment, workspace_id="public-a"):
    return environment.reads.load_public_document_browser_documents("reader", workspace_id)


def test_the_count_is_the_rows_of_the_public_document_list(environment):
    seed_library(environment)
    rows = listed(environment)
    assert sorted(row["id"] for row in rows) == ["draft", "legacy-2", "memo", "report-v3"]
    assert environment.reads.count_current_public_documents("public-a") == len(rows) == 4


def test_the_classic_count_counts_every_stored_record_instead(environment):
    """``SELECT VALUE COUNT(1) FROM d WHERE d.public_workspace_id = @wsId``, the classic
    ``/fileCount``, which the classic manage page checks before it offers to delete."""
    seed_library(environment)
    stored = sum(1 for record in environment.source.records.values() if record["public_workspace_id"] == "public-a")
    assert stored == 8
    assert environment.reads.count_current_public_documents("public-a") == 4


def test_another_workspace_counts_only_its_own(environment):
    seed_library(environment)
    assert environment.reads.count_current_public_documents("public-b") == 1


def test_an_empty_library_counts_zero(environment):
    environment.source.records.clear()
    assert environment.reads.count_current_public_documents("public-a") == 0
    assert listed(environment) == []


def test_the_count_changes_as_the_list_does(environment):
    seed_library(environment)
    environment.source.records["report-v4"] = document("report-v4", revision_family_id="report", version=4)
    environment.source.records["report-v3"]["is_current_version"] = False
    environment.source.records.pop("memo")
    rows = [row["id"] for row in listed(environment)]
    assert "report-v4" in rows and "memo" not in rows
    assert environment.reads.count_current_public_documents("public-a") == len(rows) == 3


def test_the_count_needs_no_read_context(environment):
    """The owner's danger zone reads the count in every status; the document list does not
    open while the workspace is inactive."""
    seed_library(environment)
    environment.workspaces["public-a"]["status"] = "inactive"
    assert environment.reads.count_current_public_documents("public-a") == 4


def _function(file_name, name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _calls(function):
    return {
        node.func.id for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize("file_name,function_name,callee", [
    ("functions_public_document_reads.py", "load_public_document_browser_documents", "current_public_document_records"),
    ("functions_public_document_reads.py", "count_current_public_documents", "current_public_document_records"),
    ("functions_public_document_reads.py", "count_current_public_documents", "_query_public_document_records"),
    ("functions_public_insights.py", "read_public_file_count", "count_current_public_documents"),
])
def test_the_list_and_the_count_share_one_predicate(file_name, function_name, callee):
    assert callee in _calls(_function(file_name, function_name))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
