# test_ai_search_document_cleanup_scope.py
"""
Functional test for workspace-scoped Azure AI Search document cleanup.
Version: 0.250.060
Implemented in: 0.250.060

This test ensures chunk cleanup and visibility updates constrain document IDs
to the owning user, group, or public workspace before mutating a shared index.
"""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_FILE = ROOT / "application" / "single_app" / "functions_documents.py"
RETENTION_FILE = ROOT / "application" / "single_app" / "functions_retention_policy.py"
CONTROL_CENTER_FILE = ROOT / "application" / "single_app" / "route_backend_control_center.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
TARGET_FUNCTIONS = {
    "_get_search_client",
    "_build_archived_scope_value",
    "_escape_ai_search_odata_literal",
    "_build_document_chunk_filter",
    "set_document_chunk_visibility",
    "delete_document_chunks",
    "delete_document_version_chunks",
}
SCOPE_ARGUMENTS = {"user_id", "group_id", "public_workspace_id"}


class FakeIndexDocumentsBatch:
    """Capture delete actions without importing the Azure Search SDK."""

    def __init__(self):
        self.actions = []

    def add_delete_actions(self, documents):
        self.actions.extend(documents)


class FakeSearchClient:
    """Capture Search client calls made by the extracted production helpers."""

    def __init__(self, search_results=None):
        self.search_results = list(search_results or [])
        self.search_calls = []
        self.index_batches = []
        self.delete_actions = []
        self.uploaded_documents = []

    def search(self, search_text, filter, select=None):
        self.search_calls.append({
            "search_text": search_text,
            "filter": filter,
            "select": select,
        })
        return [dict(result) for result in self.search_results]

    def index_documents(self, batch):
        self.index_batches.append(list(batch.actions))
        return []

    def delete_documents(self, actions):
        self.delete_actions.append(list(actions))
        return []

    def upload_documents(self, documents):
        self.uploaded_documents.append(list(documents))
        return []


def read_text(path):
    return path.read_text(encoding="utf-8")


def read_version():
    for line in read_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split('"')[1]
    raise AssertionError("VERSION assignment was not found in config.py")


def load_cleanup_functions(clients):
    source = read_text(DOCUMENTS_FILE)
    parsed = ast.parse(source, filename=str(DOCUMENTS_FILE))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]
    assert {node.name for node in selected_nodes} == TARGET_FUNCTIONS

    namespace = {
        "ARCHIVED_SCOPE_PREFIX": "__archived__::",
        "CLIENTS": clients,
        "IndexDocumentsBatch": FakeIndexDocumentsBatch,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(module, str(DOCUMENTS_FILE), "exec"), namespace)
    return namespace


def test_version_header_matches_config():
    assert read_version() == "0.250.060"


def test_delete_document_chunks_scopes_every_workspace_type():
    clients = {
        "search_client_user": FakeSearchClient([{"id": "personal-chunk"}]),
        "search_client_group": FakeSearchClient([{"id": "group-chunk"}]),
        "search_client_public": FakeSearchClient([{"id": "public-chunk"}]),
    }
    namespace = load_cleanup_functions(clients)
    delete_chunks = namespace["delete_document_chunks"]

    cases = [
        (
            "search_client_user",
            {"user_id": "user'1"},
            (
                "document_id eq 'doc''1' and "
                "(user_id eq 'user''1' or user_id eq '__archived__::user''1')"
            ),
            "personal-chunk",
        ),
        (
            "search_client_group",
            {"group_id": "group'1"},
            (
                "document_id eq 'doc''1' and "
                "(group_id eq 'group''1' or group_id eq '__archived__::group''1')"
            ),
            "group-chunk",
        ),
        (
            "search_client_public",
            {"public_workspace_id": "public'1"},
            (
                "document_id eq 'doc''1' and "
                "(public_workspace_id eq 'public''1' or "
                "public_workspace_id eq '__archived__::public''1')"
            ),
            "public-chunk",
        ),
    ]

    for client_name, scope, expected_filter, expected_chunk_id in cases:
        delete_chunks("doc'1", **scope)
        client = clients[client_name]
        assert client.search_calls[-1]["filter"] == expected_filter
        assert client.index_batches[-1] == [{"id": expected_chunk_id}]


def test_personal_cleanup_fails_closed_without_user_scope():
    personal_client = FakeSearchClient([{"id": "personal-chunk"}])
    namespace = load_cleanup_functions({
        "search_client_user": personal_client,
        "search_client_group": FakeSearchClient(),
        "search_client_public": FakeSearchClient(),
    })

    with pytest.raises(ValueError, match="user_id is required"):
        namespace["delete_document_chunks"]("document-1")

    assert personal_client.search_calls == []
    assert personal_client.index_batches == []


def test_version_cleanup_is_scoped_and_rejects_filter_injection():
    group_client = FakeSearchClient([{"id": "group-version-chunk"}])
    namespace = load_cleanup_functions({
        "search_client_user": FakeSearchClient(),
        "search_client_group": group_client,
        "search_client_public": FakeSearchClient(),
    })
    delete_version_chunks = namespace["delete_document_version_chunks"]

    delete_version_chunks("document-1", "7", group_id="group-1")

    assert group_client.search_calls[-1]["filter"] == (
        "document_id eq 'document-1' and "
        "(group_id eq 'group-1' or group_id eq '__archived__::group-1') and version eq 7"
    )
    assert group_client.delete_actions[-1] == [
        {"@search.action": "delete", "id": "group-version-chunk"}
    ]

    search_call_count = len(group_client.search_calls)
    with pytest.raises(ValueError, match="version must be an integer"):
        delete_version_chunks("document-1", "7 or version gt 0", group_id="group-1")
    assert len(group_client.search_calls) == search_call_count


def test_visibility_updates_use_the_same_workspace_scope_filter():
    group_client = FakeSearchClient([{
        "id": "group-chunk",
        "document_id": "document-1",
        "group_id": "group-1",
        "shared_group_ids": [],
    }])
    namespace = load_cleanup_functions({
        "search_client_user": FakeSearchClient(),
        "search_client_group": group_client,
        "search_client_public": FakeSearchClient(),
    })

    updated_count = namespace["set_document_chunk_visibility"]({
        "id": "document-1",
        "group_id": "group-1",
        "shared_group_ids": ["group-2,approved"],
    })

    assert updated_count == 1
    assert group_client.search_calls[-1]["filter"] == (
        "document_id eq 'document-1' and "
        "(group_id eq 'group-1' or group_id eq '__archived__::group-1')"
    )
    assert group_client.uploaded_documents[-1][0]["shared_group_ids"] == ["group-2,approved"]


def test_all_production_cleanup_calls_supply_a_workspace_scope():
    for path in (DOCUMENTS_FILE, RETENTION_FILE, CONTROL_CENTER_FILE):
        parsed = ast.parse(read_text(path), filename=str(path))
        for node in ast.walk(parsed):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "delete_document_chunks":
                continue

            keyword_names = {keyword.arg for keyword in node.keywords}
            assert keyword_names & SCOPE_ARGUMENTS, (
                f"Unscoped delete_document_chunks call in {path}:{node.lineno}"
            )