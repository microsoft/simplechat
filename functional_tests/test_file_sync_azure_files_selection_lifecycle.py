# test_file_sync_azure_files_selection_lifecycle.py
"""
Functional tests for Azure Files selected-path reconciliation.
Version: 0.261.369
Implemented in: 0.261.369

Execute production selection, staging, run, and deletion-policy functions with
the pinned SDK, paginated offline HTTP, and existing SDK-shaped Cosmos doubles.
Network access and downstream document ingestion/deletion are isolated.
"""

import fnmatch
import hashlib
import logging
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, unquote, urlparse
from xml.sax.saxutils import escape

from azure.core.exceptions import ServiceRequestError
from azure.storage import fileshare
import pytest

from test_file_sync_azure_blob_storage import load_functions
from test_file_sync_azure_files_runtime import (
    OfflineResponse,
    OfflineTransport,
    connector_functions,
    no_network,
    source,
)
from test_file_sync_cosmos_response_contract import storage
from test_support.versioning import assert_app_version_at_least


class TreeTransport(OfflineTransport):
    """Path-aware storage with real SDK pagination and structured failures."""

    def __init__(self):
        super().__init__()
        self.directories = {"team": [("policy.md", False)]}
        self.files = {"team/policy.md": b"Policy revision one"}
        self.failures = {}
        self.page_size = 1

    def send(self, request, **kwargs):
        self.requests.append(request)
        parsed = urlparse(request.url)
        path = unquote(parsed.path).removeprefix("/documents").strip("/")
        query = parse_qs(parsed.query)
        marker = query.get("marker", [""])[0]
        failure = self.failures.get((request.method, path, marker))
        if isinstance(failure, Exception):
            raise failure
        if failure:
            return self.error(request, *failure)
        if query.get("comp") == ["list"]:
            if path not in self.directories:
                return self.error(request, 404, "ResourceNotFound")
            entries = self.directories[path]
            start = int(marker or 0)
            page = entries[start:start + self.page_size]
            next_marker = str(start + len(page)) if start + len(page) < len(entries) else ""
            body = "".join(
                f"<{'Directory' if directory else 'File'}><Name>{escape(name)}</Name>"
                "<Properties><Content-Length>1</Content-Length></Properties>"
                f"</{'Directory' if directory else 'File'}>"
                for name, directory in page
            )
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<EnumerationResults ServiceEndpoint="https://account.file.core.windows.net/"'
                f' ShareName="documents" DirectoryPath="{escape(path)}">'
                f"<Entries>{body}</Entries><NextMarker>{next_marker}</NextMarker>"
                "</EnumerationResults>"
            )
            return OfflineResponse(request, xml.encode(), {"Content-Type": "application/xml"})
        if path not in self.files:
            return self.error(request, 404, "ResourceNotFound")
        content = self.files[path]
        headers = {
            "Content-Length": str(len(content)),
            "Content-Type": "application/octet-stream",
            "ETag": f'"{hashlib.sha256(content).hexdigest()}"',
            "Last-Modified": "Tue, 20 Oct 2026 02:00:00 GMT",
            "x-ms-type": "file",
        }
        if request.method == "GET":
            headers["Content-Range"] = f"bytes 0-{len(content) - 1}/{len(content)}"
        return OfflineResponse(request, content if request.method == "GET" else b"", headers)

    @staticmethod
    def error(request, status, code):
        response = OfflineResponse(request, b"", {"x-ms-error-code": code})
        response.status_code = status
        response.reason = "Offline storage failure"
        return response

    def listings(self):
        return [
            unquote(urlparse(request.url).path)
            for request in self.requests
            if parse_qs(urlparse(request.url).query).get("comp") == ["list"]
        ]


@pytest.fixture
def tree(monkeypatch):
    transport = TreeTransport()
    real_client = fileshare.ShareServiceClient

    class OfflineClient(real_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=transport, retry_total=0)

    monkeypatch.setattr(fileshare, "ShareServiceClient", OfflineClient)
    return transport


@pytest.fixture
def engine(storage, tree):
    env = storage
    item = env.source
    item.update(connection=source()["connection"], auth=source()["auth"], recursive=True)
    config = {
        "enable_file_sync": True, "file_sync_max_files_per_run": 10,
        "file_sync_max_bytes_per_run": 100000,
    }
    deleted = Mock()
    ingested = []

    def ingest(source_item, remote_file, temp_path):
        content = Path(temp_path).read_bytes()
        Path(temp_path).unlink()
        ingested.append(content)
        return f"document-{len(ingested)}"

    functions = load_functions("functions_file_sync.py", {
        "_process_file_sync_source", "_item_id_for_path", "_normalize_remote_path",
        "_remote_file_unchanged", "_record_item_run_result", "_touch_item",
        "_upsert_synced_item", "_upsert_failed_item", "_handle_remote_deletes",
        "_delete_synced_document", "_update_source_after_run", "_file_matches_filters",
    }, {
        **env.functions, "logging": logging,
        "get_file_sync_config": lambda: config,
        "_now": load_functions("functions_file_sync.py", {"_now"})["_now"],
        "_now_iso": lambda: "2026-10-21T12:00:00+00:00",
        "FILE_SYNC_REMOTE_DELETE_POLICIES": {"ignore", "hard_delete"},
        "FILE_SYNC_PUBLIC_RUN_ERROR_MESSAGE": "File Sync run failed.",
        "FILE_SYNC_PUBLIC_ITEM_ERROR_MESSAGE": "File Sync item failed.",
        "debug_file_sync": Mock(), "log_event": Mock(),
        "_log_file_sync_activity": Mock(), "_invalidate_scope_search_cache": Mock(),
        "fnmatch": fnmatch, "allowed_file": lambda name: name.endswith((".md", ".txt")),
        "_apply_sync_tags_to_existing_document": Mock(),
        "_create_document_from_remote_file": ingest,
        "delete_document_revision": deleted,
    })
    connector = connector_functions()
    functions["_list_remote_files"] = connector["_list_azure_files"]
    functions["_stage_remote_file"] = connector["_stage_azure_files_file"]

    def process():
        run = env.functions["_create_run"](item, env.scope_id, "manual")
        return functions["_process_file_sync_source"](item, run, env.scope_id, "manual")

    return SimpleNamespace(
        source=item, config=config, process=process, functions=functions,
        deleted=deleted, ingested=ingested, storage=env,
    )


@pytest.mark.parametrize("policy", ["ignore", "hard_delete"])
@pytest.mark.parametrize("selection", [
    "policy.md", "folder", "folder/deep/policy.md", "folder/policy.md", "",
])
@pytest.mark.parametrize("saved", [False, True])
def test_disappeared_selection_obeys_saved_policy(engine, tree, policy, selection, saved):
    env = engine
    item = env.source
    item["remote_delete_policy"] = policy
    item["identity_id"] = "workspace-identity" if saved else ""
    if saved:
        auth = item.pop("auth")
        connector = connector_functions(_get_identity_auth_for_source=lambda source_item: auth)
        env.functions["_list_remote_files"] = connector["_list_azure_files"]
        env.functions["_stage_remote_file"] = connector["_stage_azure_files_file"]
    path = "folder/policy.md" if selection == "folder" else selection or "policy.md"
    tree.directories = {
        "team": [("folder", True)] if path.startswith("folder/") else [("policy.md", False)],
        "team/folder": [("deep", True)] if "/deep/" in path else [("policy.md", False)],
        "team/folder/deep": [("policy.md", False)],
    }
    tree.files = {f"team/{path}": b"Initial policy"}
    item["connection"]["selected_paths"] = [selection] if selection else []
    baseline = env.process()
    assert baseline["status"] == "completed"
    assert baseline["counts"]["created"] == 1
    tracked = env.storage.items.query_items("", partition_key=item["id"])
    assert len(tracked) == 1
    original = tracked[0]
    tree.files.clear()
    if "/" in selection:
        tree.directories["team/folder"] = []
        expected_listings = ["/documents/team", "/documents/team/folder"]
    else:
        tree.directories["team"] = []
        expected_listings = ["/documents/team"]
    tree.requests.clear()
    result = env.process()
    stored_run = env.storage.runs.read_item(result["id"], item["id"])
    retained = env.storage.items.read_item(original["id"], item["id"])
    assert stored_run["status"] == "completed"
    assert retained["document_id"] == original["document_id"]
    assert retained["status"] == ("remote_deleted" if policy == "hard_delete" else "remote_missing")
    assert tree.listings() == expected_listings
    assert not any(request.method == "HEAD" for request in tree.requests)
    if policy == "hard_delete":
        env.deleted.assert_called_once_with(
            user_id=item.get("user_id") or item.get("created_by"), document_id=original["document_id"],
            delete_mode="all_versions",
            group_id=env.storage.scope_id if env.storage.scope == "group" else None,
            public_workspace_id=env.storage.scope_id if env.storage.scope == "public" else None,
        )
        assert stored_run["counts"]["deleted"] == 1
    else:
        env.deleted.assert_not_called()


@pytest.mark.parametrize("failure", [
    "root", "share", "unauthorized", "forbidden", "transport",
    "late_page", "race", "directory_race", "budget",
])
def test_uncertain_inventory_never_reconciles_deletions(engine, tree, failure):
    env = engine
    env.source["remote_delete_policy"] = "hard_delete"
    env.source["connection"]["selected_paths"] = ["policy.md"]
    baseline = env.process()
    assert baseline["status"] == "completed"
    original = env.storage.items.query_items("", partition_key=env.source["id"])[0]
    tree.files.clear()
    tree.directories["team"] = []
    if failure == "root":
        del tree.directories["team"]
    elif failure == "share":
        tree.failures[("GET", "team", "")] = (404, "ShareNotFound")
    elif failure in {"unauthorized", "forbidden"}:
        tree.failures[("GET", "team", "")] = (401, "AuthenticationFailed") if failure == "unauthorized" else (403, "AuthorizationPermissionMismatch")
    elif failure == "transport":
        tree.failures[("GET", "team", "")] = ServiceRequestError("offline transport failure")
    elif failure == "late_page":
        tree.directories["team"] = [("other.md", False), ("more.md", False)]
        tree.failures[("GET", "team", "1")] = (403, "AuthorizationPermissionMismatch")
    elif failure == "race":
        tree.directories["team"] = [("policy.md", False)]
    elif failure == "directory_race":
        tree.directories["team"] = [("reports", True)]
        env.source["connection"]["selected_paths"] = ["policy.md", "reports"]
    else:
        env.config["file_sync_max_files_per_run"] = 1
        env.source["connection"]["selected_paths"] = ["", "missing.md"]
        tree.directories["team"] = [(f"file-{index}.md", False) for index in range(3)]
        tree.files = {f"team/file-{index}.md": b"content" for index in range(3)}
    result = env.process()
    stored = env.storage.items.read_item(original["id"], env.source["id"])
    stored_run = env.storage.runs.read_item(result["id"], env.source["id"])
    assert stored_run["status"] == "failed"
    assert stored["status"] == "synced"
    assert stored["document_id"] == original["document_id"]
    assert len(env.ingested) == 1
    env.deleted.assert_not_called()
    if failure == "budget":
        limit_log = env.functions["_list_remote_files"].__globals__["log_event"]
        assert limit_log.call_args.kwargs["extra"]["failure_code"] == "azure_files_inventory_limit_exceeded"


def test_missing_selection_does_not_remove_present_or_ignored_copies(engine, tree):
    env = engine
    env.source["remote_delete_policy"] = "hard_delete"
    env.source["connection"]["selected_paths"] = ["policy.md", "gone.md", "ignored.md"]
    tree.directories["team"] += [("gone.md", False), ("ignored.md", False)]
    tree.files.update({"team/gone.md": b"gone", "team/ignored.md": b"ignored"})
    baseline = env.process()
    assert baseline["counts"]["created"] == 3
    tracked = {
        item["file_name"]: item
        for item in env.storage.items.query_items("", partition_key=env.source["id"])
    }
    ignored = tracked["ignored.md"]
    env.storage.items.upsert_item({**ignored, "ignored": True, "status": "ignored"})
    env.storage.items.create_item({
        "id": "foreign-item", "source_id": "other-source",
        "document_id": "foreign-document", "status": "synced",
    })
    tree.directories["team"] = [("policy.md", False)]
    del tree.files["team/gone.md"]
    del tree.files["team/ignored.md"]
    result = env.process()
    remaining = env.storage.items.read_item(tracked["policy.md"]["id"], env.source["id"])
    ignored = env.storage.items.read_item(ignored["id"], env.source["id"])
    foreign = env.storage.items.read_item("foreign-item", "other-source")
    assert result["status"] == "completed"
    assert result["counts"]["deleted"] == 1
    assert remaining["status"] == "unchanged"
    assert remaining["document_id"] == tracked["policy.md"]["document_id"]
    assert ignored["status"] == "ignored"
    assert foreign["status"] == "synced"
    assert env.deleted.call_args.kwargs["document_id"] == tracked["gone.md"]["document_id"]
    assert env.deleted.call_count == 1


def test_filters_and_ingestion_budget_keep_present_copies(engine, tree):
    env = engine
    env.source["connection"]["selected_paths"] = ["policy.md", "second.md"]
    tree.directories["team"].append(("second.md", False))
    tree.files["team/second.md"] = b"second policy"
    first = env.process()
    assert first["counts"]["created"] == 2
    env.source["remote_delete_policy"] = "hard_delete"
    env.source["filters"] = {"exclude_patterns": ["policy.md"]}
    env.config["file_sync_max_bytes_per_run"] = 1
    result = env.process()
    assert result["status"] == "completed"
    assert result["counts"]["skipped"] == 2
    assert len(env.ingested) == 2
    env.deleted.assert_not_called()


def test_overlapping_selections_are_deduplicated_and_keep_updates(engine, tree):
    env = engine
    env.source["connection"]["selected_paths"] = ["reports", "reports/policy.md", "missing.md"]
    tree.directories = {
        "team": [("reports", True), ("unselected.md", False)],
        "team/reports": [("policy.md", False)],
    }
    tree.files = {"team/reports/policy.md": b"Revision one", "team/unselected.md": b"not selected"}
    first = env.process()
    second = env.process()
    tree.files["team/reports/policy.md"] = b"Revision two"
    third = env.process()
    stored = env.storage.items.query_items("", partition_key=env.source["id"])
    assert first["counts"]["created"] == 1
    assert second["counts"]["unchanged"] == 1
    assert third["counts"]["updated"] == 1
    assert len(stored) == 1
    assert stored[0]["document_id"] == "document-2"
    assert stored[0]["last_sync_run_id"] == third["id"]
    assert env.ingested == [b"Revision one", b"Revision two"]
    env.deleted.assert_not_called()
    assert tree.listings().count("/documents/team/reports") == 3
    assert tree.listings().count("/documents/team") == 6  # Two pages per run.


@pytest.mark.parametrize("recursive", [False, True])
def test_nested_selection_preserves_recursion_and_canonical_paths(tree, recursive):
    tree.directories = {
        "team": [("Reports", True)],
        "team/Reports": [("Quarter one", True)],
        "team/Reports/Quarter one": [("policy #1.md", False), ("archive", True)],
        "team/Reports/Quarter one/archive": [("old.md", False)],
    }
    tree.files = {
        "team/Reports/Quarter one/policy #1.md": b"current",
        "team/Reports/Quarter one/archive/old.md": b"old",
    }
    item = source()
    item["recursive"] = recursive
    item["connection"]["selected_paths"] = ["reports/quarter one"]
    result = connector_functions()["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
    expected = {"Reports/Quarter one/policy #1.md"}
    if recursive:
        expected.add("Reports/Quarter one/archive/old.md")
    assert {entry["relative_path"] for entry in result} == expected
    assert all(entry["remote_path"].startswith("https://account.file.core.windows.net/documents/team/Reports/Quarter%20one/") for entry in result)
    assert all(entry["remote_change_token"] for entry in result)


@pytest.mark.parametrize("auth_type", ["managed_identity", "client_secret", "connection_string"])
@pytest.mark.parametrize("saved", [False, True])
def test_selected_file_authentication_dispatch_is_unchanged(tree, auth_type, saved):
    item = source(auth_type, saved=saved)
    auth = item["auth"]
    if auth_type == "connection_string":
        auth["secret"] = (
            "DefaultEndpointsProtocol=https;AccountName=account;"
            "AccountKey=b2ZmbGluZQ==;EndpointSuffix=core.windows.net"
        )
    if saved:
        item["auth"] = {}
    item["connection"]["selected_paths"] = ["policy.md"]
    functions = connector_functions(_get_identity_auth_for_source=lambda source_item: auth if saved else None)
    result = functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
    assert len(result) == 1
    assert result[0]["relative_path"] == "policy.md"
    if auth_type != "connection_string":
        assert all(request.headers["x-ms-file-request-intent"] == "backup" for request in tree.requests)


def test_share_root_selection_and_exact_inventory_limit(tree):
    tree.directories = {"": [("first.md", False), ("second.md", False)]}
    tree.files = {"first.md": b"first", "second.md": b"second"}
    item = source()
    item["connection"]["directory_path"] = ""
    functions = connector_functions()
    result = functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 1})
    assert {entry["relative_path"] for entry in result} == {"first.md", "second.md"}
    item["connection"]["selected_paths"] = ["missing.md"]
    result = functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 1})
    assert result == []


@pytest.mark.parametrize("optimized", [False, True])
def test_required_missing_selection_operations_survive_optimized_python(optimized):
    probe = r'''
import socket
from unittest.mock import patch
from azure.storage import fileshare
from test_file_sync_azure_files_runtime import connector_functions, source
from test_file_sync_azure_files_selection_lifecycle import TreeTransport
def blocked(*args, **kwargs):
    raise RuntimeError("Network forbidden")
transport = TreeTransport()
transport.directories["team"] = []
transport.files.clear()
real_client = fileshare.ShareServiceClient
class Client(real_client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, transport=transport, retry_total=0)
item = source()
item["connection"]["selected_paths"] = ["policy.md"]
with patch.object(socket.socket, "connect", blocked), patch.object(socket, "getaddrinfo", blocked), patch.object(fileshare, "ShareServiceClient", Client):
    result = connector_functions()["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
if result != [] or transport.listings() != ["/documents/team"]:
    raise RuntimeError("Missing selection was not confirmed through readable parent inventory")
print("confirmed-absence-probe-passed")
'''
    completed = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", probe],
        cwd=Path(__file__).parent, capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "confirmed-absence-probe-passed" in completed.stdout


def test_implementation_version():
    assert_app_version_at_least("0.261.369")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
