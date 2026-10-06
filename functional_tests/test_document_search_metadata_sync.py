#!/usr/bin/env python3
# test_document_search_metadata_sync.py
"""
Functional test for durable, batched document search metadata sync.
Version: 0.261.052
Implemented in: 0.261.052

This test ensures that document metadata edits no longer do per-chunk Search work inside the
request: update_document() records a durable sync request in the same save, a background worker
merges only the changed fields into every chunk in key-paged batches, failures retry with
backoff, and access-control changes are projected to the chunks before they are saved.
"""

import ast
import copy
import json
import logging
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
DOCUMENTS_PATH = APP_ROOT / "functions_documents.py"
sys.path.append(str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


LOADED_FUNCTIONS = {
    "_search_indexing_results_succeeded",
    "_execute_document_search_write",
    "_get_documents_container",
    "ensure_list",
    "update_document",
    "share_document_with_user",
    "_escape_search_filter_literal",
    "_resolve_document_chunk_scope",
    "get_document_search_acl_fields",
    "iter_document_chunk_key_pages",
    "project_fields_to_document_chunks",
    "project_document_acl_to_chunks",
    "build_document_search_metadata_fields",
    "_document_search_sync_now",
    "_format_document_search_sync_time",
    "_parse_document_search_sync_time",
    "_get_document_search_sync_scope_name",
    "get_document_search_sync_record_id",
    "_document_search_sync_lease_is_active",
    "_document_search_sync_intent_is_stale",
    "_is_cosmos_write_conflict",
    "_is_cosmos_not_found",
    "_normalize_search_acl_entries",
    "_read_document_search_sync_record",
    "_replace_document_search_sync_record",
    "request_document_search_metadata_sync",
    "_get_document_search_sync_executor",
    "schedule_document_search_metadata_sync",
    "_run_scheduled_document_search_metadata_sync",
    "_acquire_document_search_sync_lease",
    "_renew_document_search_sync_lease",
    "_release_document_search_sync_lease",
    "_record_document_search_sync_failure",
    "_complete_document_search_sync_pass",
    "_delete_document_search_sync_record",
    "_read_document_for_search_sync",
    "run_document_search_metadata_sync",
    "process_due_document_search_metadata_syncs",
}
LOADED_CLASSES = {
    "DocumentSearchAclProjectionDeferredError",
    "DocumentSearchAclProjectionError",
    "DocumentSearchSyncLeaseLostError",
}


class FakeNotFoundError(Exception):
    status_code = 404

    def __init__(self, message=None, status=None):
        super().__init__(message or "Not found")


class FakeHttpError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeSearchWritesFrozenError(Exception):
    pass


class FakeExecutor:
    """Capture queued sync work so a test decides when it runs."""

    def __init__(self, max_workers=None, thread_name_prefix=None):
        self.submitted = []

    def submit(self, function, *args):
        self.submitted.append((function, args))


class FakeSettingsContainer:
    """In-memory Cosmos container with etag preconditions."""

    def __init__(self):
        self.items = {}
        self.before_replace = None

    def _store(self, body):
        item = copy.deepcopy(body)
        item["_etag"] = uuid.uuid4().hex
        self.items[item["id"]] = item
        return copy.deepcopy(item)

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.items:
            raise FakeNotFoundError()
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        if body["id"] in self.items:
            raise FakeHttpError(409)
        return self._store(body)

    def replace_item(self, item, body, etag=None, match_condition=None):
        if self.before_replace is not None:
            self.before_replace(item)
        if item not in self.items:
            raise FakeNotFoundError()
        if etag is not None and self.items[item]["_etag"] != etag:
            raise FakeHttpError(412)
        return self._store(body)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        if item not in self.items:
            raise FakeNotFoundError()
        if etag is not None and self.items[item]["_etag"] != etag:
            raise FakeHttpError(412)
        del self.items[item]

    def query_items(self, query, parameters, enable_cross_partition_query=False):
        values = {parameter["name"]: parameter["value"] for parameter in parameters}
        due = [
            item for item in self.items.values()
            if item.get("type") == values["@type"] and str(item.get("next_attempt_at") or "") <= values["@now"]
        ]
        due.sort(key=lambda item: item.get("next_attempt_at") or "")
        return [{"id": item["id"]} for item in due[: values["@limit"]]]


class FakeDocumentsContainer:
    """Document container keyed by id and scoped by one owner field."""

    def __init__(self, scope_field):
        self.scope_field = scope_field
        self.documents = {}

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        values = {parameter["name"]: parameter["value"] for parameter in parameters}
        document = self.documents.get(values["@document_id"])
        if not document or document.get(self.scope_field) != values[f"@{self.scope_field}"]:
            return []
        return [copy.deepcopy(document)]

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.documents:
            raise FakeNotFoundError()
        return copy.deepcopy(self.documents[item])


class FakeSearchClient:
    """AI Search client that evaluates the key-paging filter and applies merges."""

    FILTER_PATTERN = re.compile(
        r"^document_id eq '(?P<document_id>(?:[^']|'')*)' "
        r"and (?P<scope_field>user_id|group_id|public_workspace_id) eq '(?P<scope_value>(?:[^']|'')*)'"
        r"(?: and id gt '(?P<last_key>(?:[^']|'')*)')?$"
    )

    def __init__(self, events):
        self.events = events
        self.chunks = {}
        self.search_calls = []
        self.merge_batches = []
        self.fail_merges = False
        self.before_merge = None

    def add_chunk(self, chunk):
        self.chunks[chunk["id"]] = dict(chunk)

    def search(self, search_text, filter, select, order_by, top):
        self.search_calls.append({
            "search_text": search_text,
            "filter": filter,
            "select": list(select),
            "order_by": list(order_by),
            "top": top,
        })
        match = self.FILTER_PATTERN.match(filter)
        assert match, f"Unexpected chunk filter: {filter}"
        document_id = match.group("document_id").replace("''", "'")
        scope_field = match.group("scope_field")
        scope_value = match.group("scope_value").replace("''", "'")
        last_key = match.group("last_key")
        last_key = last_key.replace("''", "'") if last_key is not None else None
        keys = sorted(
            chunk_id for chunk_id, chunk in self.chunks.items()
            if chunk.get("document_id") == document_id
            and chunk.get(scope_field) == scope_value
            and (last_key is None or chunk_id > last_key)
        )
        return [{"id": key} for key in keys[:top]]

    def merge_documents(self, documents, **_kwargs):
        if self.before_merge is not None:
            self.before_merge(documents)
        self.merge_batches.append(copy.deepcopy(documents))
        self.events.append(("merge", [document["id"] for document in documents]))
        if self.fail_merges:
            return [{"succeeded": False} for _ in documents]
        for document in documents:
            self.chunks[document["id"]].update({key: value for key, value in document.items() if key != "id"})
        return [{"succeeded": True} for _ in documents]


class FakeSlot:
    def __init__(self, harness):
        self.harness = harness

    def __enter__(self):
        if self.harness.search_writes_frozen:
            raise FakeSearchWritesFrozenError("AI Search writes are temporarily frozen.")
        return self

    def __exit__(self, *_args):
        return False


class Harness:
    """Load the production sync code with in-memory Cosmos and Search fakes."""

    def __init__(self):
        self.events = []
        self.logs = []
        self.blob_tag_calls = []
        self.search_writes_frozen = False
        self.settings = FakeSettingsContainer()
        self.user_documents = FakeDocumentsContainer("user_id")
        self.group_documents = FakeDocumentsContainer("group_id")
        self.public_documents = FakeDocumentsContainer("public_workspace_id")
        self.user_search = FakeSearchClient(self.events)
        self.group_search = FakeSearchClient(self.events)
        self.public_search = FakeSearchClient(self.events)
        self.clock = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
        self.namespace = self._load()

    def _load(self):
        source = DOCUMENTS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(DOCUMENTS_PATH))
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in LOADED_FUNCTIONS:
                nodes.append(node)
            elif isinstance(node, ast.ClassDef) and node.name in LOADED_CLASSES:
                nodes.append(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and (target.id.startswith("DOCUMENT_SEARCH_") or target.id.startswith("_document_search_sync_"))
                for target in node.targets
            ):
                nodes.append(node)
        loaded_names = {getattr(node, "name", None) for node in nodes}
        missing = (LOADED_FUNCTIONS | LOADED_CLASSES) - loaded_names
        assert not missing, f"Expected production definitions are missing: {sorted(missing)}"

        harness = self

        def upsert_document(container, document_item, operation):
            harness.events.append(("upsert", document_item["id"], operation))
            container.documents[document_item["id"]] = copy.deepcopy(document_item)
            return copy.deepcopy(document_item)

        namespace = {
            "json": json,
            "logging": logging,
            "re": re,
            "threading": threading,
            "time": time,
            "traceback": traceback,
            "uuid": uuid,
            "datetime": datetime,
            "timezone": timezone,
            "timedelta": timedelta,
            "ThreadPoolExecutor": FakeExecutor,
            "MatchConditions": type("MatchConditions", (), {"IfNotModified": "IfNotModified"}),
            "CosmosResourceNotFoundError": FakeNotFoundError,
            "DataManagementSearchWritesFrozenError": FakeSearchWritesFrozenError,
            "hold_data_management_search_write_slot": lambda _container: FakeSlot(harness),
            "cosmos_data_management_jobs_container": object(),
            "cosmos_settings_container": self.settings,
            "cosmos_user_documents_container": self.user_documents,
            "cosmos_group_documents_container": self.group_documents,
            "cosmos_public_documents_container": self.public_documents,
            "_get_search_client": lambda group_id=None, public_workspace_id=None: (
                harness.public_search if public_workspace_id is not None
                else harness.group_search if group_id is not None
                else harness.user_search
            ),
            "_upsert_document_and_sync_access_index": upsert_document,
            "add_file_task_to_file_processing_log": lambda **_kwargs: None,
            "calculate_processing_percentage": lambda document_item: document_item.get("percentage_complete", 0),
            "propagate_tags_to_blob_metadata": lambda *args: harness.blob_tag_calls.append(args),
            "log_event": lambda message, extra=None, **kwargs: harness.logs.append((message, extra, kwargs)),
        }
        module = ast.Module(body=nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(DOCUMENTS_PATH), "exec"), namespace)
        namespace["_document_search_sync_now"] = lambda: harness.clock
        return namespace

    def __getitem__(self, name):
        return self.namespace[name]

    def advance(self, seconds):
        self.clock += timedelta(seconds=seconds)

    def add_personal_document(self, document_id="doc-1", user_id="owner-1", chunk_count=7, **fields):
        document = {
            "id": document_id,
            "user_id": user_id,
            "title": "Large XML",
            "tags": [],
            "authors": [],
            "status": "Processing Complete",
            "percentage_complete": 100,
            "shared_user_ids": [],
            **fields,
        }
        self.user_documents.documents[document_id] = document
        for index in range(chunk_count):
            self.user_search.add_chunk({
                "id": f"{document_id}_{index + 1:03d}",
                "document_id": document_id,
                "user_id": user_id,
                "chunk_text": f"chunk text {index}",
                "embedding": [0.1, 0.2, 0.3],
                "document_tags": [],
                "title": "Large XML",
                "shared_user_ids": [],
            })
        return document

    def add_group_document(self, document_id="group-doc-1", group_id="group-1", chunk_count=4, **fields):
        document = {
            "id": document_id,
            "group_id": group_id,
            "user_id": "editor-1",
            "title": "Group XML",
            "tags": [],
            "status": "Processing Complete",
            "percentage_complete": 100,
            "shared_group_ids": [],
            **fields,
        }
        self.group_documents.documents[document_id] = document
        for index in range(chunk_count):
            self.group_search.add_chunk({
                "id": f"{document_id}_{index + 1:03d}",
                "document_id": document_id,
                "group_id": group_id,
                "embedding": [0.4, 0.5],
                "shared_group_ids": list(fields.get("shared_group_ids", [])),
                "document_tags": [],
            })
        return document

    def sync_records(self):
        return [item for item in self.settings.items.values() if item.get("type") == "document_search_metadata_sync"]


def test_chunk_key_paging_is_key_ordered_scoped_and_id_only():
    """Chunk listing pages by key within the document's active scope and never selects content."""
    harness = Harness()
    harness.add_personal_document(chunk_count=7)
    harness.user_search.add_chunk({"id": "doc-1_archived", "document_id": "doc-1", "user_id": "__archived__::owner-1"})
    harness.user_search.add_chunk({"id": "doc-2_001", "document_id": "doc-2", "user_id": "owner-1"})

    pages = list(harness["iter_document_chunk_key_pages"]("doc-1", "owner-1", page_size=3))

    assert pages == [
        ["doc-1_001", "doc-1_002", "doc-1_003"],
        ["doc-1_004", "doc-1_005", "doc-1_006"],
        ["doc-1_007"],
    ]
    calls = harness.user_search.search_calls
    assert all(call["select"] == ["id"] and call["order_by"] == ["id asc"] and call["top"] == 3 for call in calls)
    assert calls[0]["filter"] == "document_id eq 'doc-1' and user_id eq 'owner-1'"
    assert calls[1]["filter"].endswith("and id gt 'doc-1_003'")
    assert calls[2]["filter"].endswith("and id gt 'doc-1_006'")


def test_projection_merges_only_requested_fields_in_batches():
    """Merges carry only the chunk key and supplied fields, so embeddings never round-trip."""
    harness = Harness()
    harness.add_personal_document(chunk_count=7)

    updated = harness["project_fields_to_document_chunks"](
        "doc-1", {"document_tags": ["bills"]}, "owner-1", batch_size=3,
    )

    assert updated == 7
    assert [len(batch) for batch in harness.user_search.merge_batches] == [3, 3, 1]
    assert all(set(action) == {"id", "document_tags"} for batch in harness.user_search.merge_batches for action in batch)
    assert all(chunk["document_tags"] == ["bills"] for chunk in harness.user_search.chunks.values())
    assert all(chunk["embedding"] == [0.1, 0.2, 0.3] for chunk in harness.user_search.chunks.values())


def test_projection_batch_size_respects_payload_byte_cap():
    """Large field payloads shrink the batch so a merge request stays under the byte cap."""
    harness = Harness()
    harness.add_personal_document(chunk_count=6)
    harness.namespace["DOCUMENT_SEARCH_SYNC_MAX_BATCH_BYTES"] = 2000

    harness["project_fields_to_document_chunks"]("doc-1", {"document_tags": ["x" * 400]}, "owner-1")

    assert max(len(batch) for batch in harness.user_search.merge_batches) <= 4
    assert sum(len(batch) for batch in harness.user_search.merge_batches) == 6


def test_projection_fails_loudly_when_a_merge_is_not_acknowledged():
    """An unacknowledged merge raises instead of reporting a completed projection."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness.user_search.fail_merges = True

    with pytest.raises(RuntimeError, match="did not acknowledge"):
        harness["project_fields_to_document_chunks"]("doc-1", {"title": "New"}, "owner-1")


def test_update_document_queues_metadata_sync_without_chunk_work():
    """A metadata save records a durable sync request and never touches chunks inline."""
    harness = Harness()
    harness.add_personal_document(chunk_count=12)

    result = harness["update_document"](
        document_id="doc-1", user_id="owner-1", tags=["bills"], title="Large XML 2026", abstract="Summary",
    )

    assert result == {
        "updated": True,
        "search_sync": {"status": "pending", "revision": 1, "fields": ["tags", "title"]},
    }
    assert harness.user_search.merge_batches == []
    assert harness.user_search.search_calls == []
    saved = harness.user_documents.documents["doc-1"]
    (record,) = harness.sync_records()
    assert saved["tags"] == ["bills"]
    assert record["latest_request_token"] and saved["search_metadata_sync_token"] == record["latest_request_token"]
    assert record["id"] == "document_search_metadata_sync:personal:doc-1"
    assert record["revision"] == 1 and record["pending_fields"] == ["tags", "title"]
    assert record["status"] == "pending" and record["user_id"] == "owner-1"
    executor = harness["_document_search_sync_executor"]
    assert len(executor.submitted) == 1
    first_token = record["latest_request_token"]

    second = harness["update_document"](document_id="doc-1", user_id="owner-1", authors=["Ada"])
    assert second["search_sync"]["revision"] == 2
    (record,) = harness.sync_records()
    assert record["pending_fields"] == ["authors", "tags", "title"]
    assert record["latest_request_token"] != first_token
    assert harness.user_documents.documents["doc-1"]["search_metadata_sync_token"] == record["latest_request_token"]

    unrelated = harness["update_document"](document_id="doc-1", user_id="owner-1", abstract="New summary")
    assert unrelated["search_sync"] == {"status": "not_required"}
    assert harness.sync_records()[0]["revision"] == 2


def test_worker_projects_latest_pending_values_and_clears_the_request():
    """The worker merges the latest saved values for every pending field, then deletes the request."""
    harness = Harness()
    harness.add_personal_document(chunk_count=5)
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"], title="Renamed")

    result = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-1")

    assert result["status"] == "complete" and result["chunks_updated"] == 5
    assert harness.sync_records() == []
    assert all(chunk["document_tags"] == ["bills"] and chunk["title"] == "Renamed" for chunk in harness.user_search.chunks.values())
    assert all(set(action) == {"id", "document_tags", "title"} for batch in harness.user_search.merge_batches for action in batch)
    assert harness.blob_tag_calls == [("doc-1", ["bills"], "owner-1", None, None)]


def test_worker_projects_a_newer_edit_that_arrives_mid_sync():
    """A save during a running sync is picked up by the same worker instead of being lost."""
    harness = Harness()
    harness.add_personal_document(chunk_count=4)
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["first"])
    harness.namespace["DOCUMENT_SEARCH_SYNC_BATCH_SIZE"] = 2
    edits = []

    def edit_during_first_merge(_documents):
        if not edits:
            edits.append(harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["second"]))

    harness.user_search.before_merge = edit_during_first_merge

    result = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-1")

    assert edits and edits[0]["search_sync"]["revision"] == 2
    assert result["status"] == "complete"
    assert harness.sync_records() == []
    assert all(chunk["document_tags"] == ["second"] for chunk in harness.user_search.chunks.values())


def test_worker_failure_backs_off_and_reconciler_heals_it():
    """A failed sync keeps its request with backoff, and the reconciler finishes it later."""
    harness = Harness()
    harness.add_personal_document(chunk_count=3)
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"])
    record_id = "document_search_metadata_sync:personal:doc-1"
    harness.user_search.fail_merges = True

    failed = harness["run_document_search_metadata_sync"](record_id)

    assert failed == {"status": "failed", "record_id": record_id, "error_type": "RuntimeError"}
    (record,) = harness.sync_records()
    assert record["status"] == "failed" and record["attempts"] == 1
    assert record["last_error_type"] == "RuntimeError" and record["lease_token"] is None
    assert record["next_attempt_at"] == "2026-10-06T16:01:00.000000+00:00"
    assert any("[DOCUMENT_SEARCH_SYNC]" in message for message, _extra, _kwargs in harness.logs)

    harness.user_search.fail_merges = False
    assert harness["process_due_document_search_metadata_syncs"]()["due"] == 0
    harness.advance(61)
    summary = harness["process_due_document_search_metadata_syncs"]()

    assert summary == {"due": 1, "processed": 1, "complete": 1, "failed": 0}
    assert harness.sync_records() == []
    assert all(chunk["document_tags"] == ["bills"] for chunk in harness.user_search.chunks.values())


def test_worker_respects_an_active_lease_and_stops_when_it_loses_one():
    """Only one worker projects a document at a time, and a worker that loses its lease stops."""
    harness = Harness()
    harness.add_personal_document(chunk_count=4)
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"])
    record_id = "document_search_metadata_sync:personal:doc-1"
    held = harness["_acquire_document_search_sync_lease"](record_id)

    assert harness["run_document_search_metadata_sync"](record_id)["status"] == "not_started"
    assert harness.user_search.merge_batches == []

    released = dict(harness.settings.items[record_id], lease_token=None, lease_expires_at=None)
    harness.settings.items[record_id] = released
    harness.namespace["DOCUMENT_SEARCH_SYNC_BATCH_SIZE"] = 2

    def steal_lease(_documents):
        harness.settings.items[record_id]["lease_token"] = "other-worker"

    harness.user_search.before_merge = steal_lease
    result = harness["run_document_search_metadata_sync"](record_id)

    assert held is not None
    assert result["status"] == "lost"
    assert len(harness.user_search.merge_batches) == 1


def test_worker_waits_for_an_uncommitted_document_write():
    """A request whose document save has not landed is re-checked rather than closed early."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness["request_document_search_metadata_sync"]("doc-1", ["tags"], "owner-1")
    record_id = "document_search_metadata_sync:personal:doc-1"

    deferred = harness["run_document_search_metadata_sync"](record_id)

    assert deferred["status"] == "deferred"
    (record,) = harness.sync_records()
    assert record["status"] == "pending" and record["lease_token"] is None

    harness.advance(601)
    assert harness["run_document_search_metadata_sync"](record_id)["status"] == "complete"
    assert harness.sync_records() == []


def test_token_from_an_earlier_request_does_not_count_as_a_landed_save():
    """A new request is not completed by a document token left over from an earlier request."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    record_id = "document_search_metadata_sync:personal:doc-1"
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["first"])
    assert harness["run_document_search_metadata_sync"](record_id)["status"] == "complete"
    earlier_token = harness.user_documents.documents["doc-1"]["search_metadata_sync_token"]

    # The next request restarts the record at revision 1 before its document save lands.
    new_record = harness["request_document_search_metadata_sync"]("doc-1", ["tags"], "owner-1")
    assert new_record["revision"] == 1 and new_record["latest_request_token"] != earlier_token

    result = harness["run_document_search_metadata_sync"](record_id)

    assert result["status"] == "deferred"
    (record,) = harness.sync_records()
    assert record["latest_request_token"] == new_record["latest_request_token"]


def test_request_retries_when_a_worker_removes_the_record_mid_write():
    """A save is not failed when a finishing worker deletes the record between read and replace."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    record_id = "document_search_metadata_sync:personal:doc-1"
    harness["request_document_search_metadata_sync"]("doc-1", ["tags"], "owner-1")
    removals = []

    def remove_once(item):
        if not removals:
            removals.append(item)
            del harness.settings.items[item]

    harness.settings.before_replace = remove_once

    record = harness["request_document_search_metadata_sync"]("doc-1", ["title"], "owner-1")

    assert removals == [record_id]
    assert record["revision"] == 1 and record["pending_fields"] == ["title"]
    assert harness.settings.items[record_id]["latest_request_token"] == record["latest_request_token"]


def test_frozen_search_writes_retry_on_a_fixed_delay():
    """A Data Management write freeze is retried shortly without climbing the failure backoff."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"])
    harness.search_writes_frozen = True

    result = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-1")

    assert result["status"] == "failed"
    (record,) = harness.sync_records()
    assert record["status"] == "pending" and record["attempts"] == 0
    assert record["last_error_type"] == "FakeSearchWritesFrozenError"
    assert record["next_attempt_at"] == "2026-10-06T16:05:00.000000+00:00"

    harness.search_writes_frozen = False
    harness.advance(301)
    assert harness["process_due_document_search_metadata_syncs"]()["complete"] == 1
    assert all(chunk["document_tags"] == ["bills"] for chunk in harness.user_search.chunks.values())


def test_equivalent_access_lists_are_not_projected():
    """A missing access list and an empty one grant the same access, so no Search write is needed."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    del harness.user_documents.documents["doc-1"]["shared_user_ids"]
    harness.user_search.fail_merges = True

    result = harness["update_document"](document_id="doc-1", user_id="owner-1", shared_user_ids=[])

    assert result == {"updated": True, "search_sync": {"status": "not_required"}}
    assert harness.user_search.merge_batches == []
    assert harness.user_documents.documents["doc-1"]["shared_user_ids"] == []

    harness.add_group_document(shared_group_ids=["group-2,approved"])
    harness.group_search.fail_merges = True
    reordered = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        shared_group_ids=["group-2,approved", "group-2,approved"],
    )
    assert reordered["updated"] is True
    assert harness.group_search.merge_batches == []


def test_worker_drops_requests_for_missing_or_moved_documents():
    """A request for a deleted document, or one that left its scope, is discarded safely."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"])
    del harness.user_documents.documents["doc-1"]

    result = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-1")

    assert result["status"] == "document_missing"
    assert harness.sync_records() == []
    assert harness.user_search.merge_batches == []


def test_group_acl_change_is_projected_before_it_is_saved():
    """Group sharing changes reach every chunk before Cosmos records them, including ACL-only saves."""
    harness = Harness()
    harness.add_group_document(shared_group_ids=["group-2,approved"])

    result = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1", shared_group_ids=[],
    )

    assert result["search_sync"] == {"status": "not_required"}
    assert [event[0] for event in harness.events] == ["merge", "upsert"]
    assert all(set(action) == {"id", "shared_group_ids"} for batch in harness.group_search.merge_batches for action in batch)
    assert all(chunk["shared_group_ids"] == [] for chunk in harness.group_search.chunks.values())
    assert harness.group_documents.documents["group-doc-1"]["shared_group_ids"] == []
    assert harness.sync_records() == []


def test_group_acl_change_is_not_saved_when_search_cannot_enforce_it():
    """A failed or frozen ACL projection raises and leaves the stored access unchanged."""
    harness = Harness()
    harness.add_group_document(shared_group_ids=["group-2,approved"])
    harness.group_search.fail_merges = True

    with pytest.raises(harness["DocumentSearchAclProjectionError"]):
        harness["update_document"](
            document_id="group-doc-1", group_id="group-1", user_id="editor-1", shared_group_ids=[],
        )
    assert harness.group_documents.documents["group-doc-1"]["shared_group_ids"] == ["group-2,approved"]

    harness.group_search.fail_merges = False
    harness.search_writes_frozen = True
    with pytest.raises(harness["DocumentSearchAclProjectionDeferredError"], match="temporarily frozen"):
        harness["update_document"](
            document_id="group-doc-1", group_id="group-1", user_id="editor-1", shared_group_ids=[],
        )
    assert harness.group_documents.documents["group-doc-1"]["shared_group_ids"] == ["group-2,approved"]
    assert not any(event[0] == "upsert" for event in harness.events)


def test_public_documents_have_no_acl_projection():
    """Public workspace documents carry no per-document ACL fields to project."""
    harness = Harness()
    assert harness["get_document_search_acl_fields"](public_workspace_id="ws-1") == ()
    assert harness["get_document_search_acl_fields"](group_id="group-1") == ("shared_group_ids",)
    assert harness["get_document_search_acl_fields"]() == ("shared_user_ids",)


def test_pending_share_is_saved_even_when_projection_fails():
    """A pending share grants no search access, so its projection is best effort after the save."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness.user_search.fail_merges = True

    assert harness["share_document_with_user"]("doc-1", "owner-1", "viewer-1") is True
    assert harness.user_documents.documents["doc-1"]["shared_user_ids"] == ["viewer-1,not_approved"]
    assert any("pending share" in message for message, _extra, _kwargs in harness.logs)


def test_scheduler_deduplicates_queued_documents():
    """Repeated saves of one document queue a single in-process sync until it starts."""
    harness = Harness()

    assert harness["schedule_document_search_metadata_sync"]("doc-1") is True
    assert harness["schedule_document_search_metadata_sync"]("doc-1") is True
    assert harness["schedule_document_search_metadata_sync"]("doc-1", group_id="group-1") is True

    executor = harness["_document_search_sync_executor"]
    assert [args for _function, args in executor.submitted] == [
        ("document_search_metadata_sync:personal:doc-1",),
        ("document_search_metadata_sync:group:doc-1",),
    ]


def test_routes_and_client_no_longer_drive_per_chunk_sync():
    """Metadata routes save once, tag routes drop duplicate passes, and the browser loop is gone."""
    assert_app_version_at_least("0.261.052")
    route_files = {
        "route_backend_documents.py": "api_patch_user_document",
        "route_backend_group_documents.py": "api_patch_group_document",
        "route_backend_public_documents.py": "api_patch_public_document",
    }
    for file_name, patch_route_name in route_files.items():
        source = (APP_ROOT / file_name).read_text(encoding="utf-8")
        assert "propagate_tags_to_chunks" not in source, f"{file_name} still runs a duplicate tag pass"
        tree = ast.parse(source)
        patch_route = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == patch_route_name
        )
        update_calls = [
            node for node in ast.walk(patch_route)
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "update_document"
        ]
        assert len(update_calls) == 1, f"{patch_route_name} must save every field in one update_document call"
        assert "search_sync" in ast.get_source_segment(source, patch_route)
        assert "_metadata_chunk_sync" not in ast.get_source_segment(source, patch_route)

    documents_source = DOCUMENTS_PATH.read_text(encoding="utf-8")
    assert "def propagate_tags_to_chunks" not in documents_source
    assert "chunk_sync_limit" not in documents_source

    workspace_js = (APP_ROOT / "static" / "js" / "workspace" / "workspace-documents.js").read_text(encoding="utf-8")
    assert "_metadata_chunk_sync" not in workspace_js
    assert "search_sync" in workspace_js

    background_source = (APP_ROOT / "background_tasks.py").read_text(encoding="utf-8")
    assert "def run_document_search_metadata_sync_loop():" in background_source
    assert "acquire_distributed_task_lock('document_search_metadata_sync_scan'" in background_source
    assert "run_document_search_metadata_sync_loop)," in background_source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
