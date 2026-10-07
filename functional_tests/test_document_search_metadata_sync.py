#!/usr/bin/env python3
# test_document_search_metadata_sync.py
"""
Functional test for durable, batched document search metadata sync.
Version: 0.261.268
Implemented in: 0.261.268

This test ensures that document metadata edits no longer do per-chunk Search work inside the
request: update_document() records a durable sync request whose token rides in the same save
(strict or not), a background worker merges only the changed fields into every chunk in key-paged
batches without ever writing to the document and then clears cached search results for the
workspace and approved share recipients, failures retry with backoff, and access-control changes
are projected safely: personal lists before the save, group revocations before the save through
the projection fence, and group grants once Cosmos records them.
"""

import ast
import copy
import json
import logging
import re
import sys
import traceback
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
DOCUMENTS_PATH = APP_ROOT / "functions_documents.py"
sys.path.append(str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_ROOT))

from content_screening.contracts import (  # noqa: E402
    SCREENING_FIELD,
    ScreeningConflictError,
    ScreeningValidationError,
    document_is_available,
)
import functions_group_document_projection_fence as fence  # noqa: E402
from test_support.document_search_sync import (  # noqa: E402
    FakeSearchClient,
    FakeSettingsContainer,
    RecordingExecutor,
    load_document_search_sync_definitions,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


LOADED_FUNCTIONS = {
    "_search_indexing_results_succeeded",
    "_execute_document_search_write",
    "_get_documents_container",
    "_build_archived_scope_value",
    "_upsert_document_and_sync_access_index",
    "ensure_list",
    "update_document",
    "share_document_with_user",
    "unshare_document_from_user",
}
METADATA_INDEX_FIELDS = {"title", "author", "file_name", "document_classification", "document_tags"}


class FakeSearchWritesFrozenError(Exception):
    pass


class FakeOriginError(Exception):
    pass


class FakeDocumentsContainer:
    """Cosmos documents container with etag preconditions, scoped queries and Cosmos error types."""

    def __init__(self, scope_field):
        self.scope_field = scope_field
        self.documents = {}
        self.writes = []

    def _store(self, body):
        item = copy.deepcopy(body)
        item["_etag"] = uuid.uuid4().hex
        self.documents[item["id"]] = item
        self.writes.append(item["id"])
        return copy.deepcopy(item)

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        values = {parameter["name"]: parameter["value"] for parameter in parameters}
        document = self.documents.get(values["@document_id"])
        if not document or document.get(self.scope_field) != values[f"@{self.scope_field}"]:
            return []
        return [copy.deepcopy(document)]

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.documents:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(self.documents[item])

    def replace_item(self, item, body, etag=None, match_condition=None):
        if item not in self.documents:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        if etag is not None and self.documents[item]["_etag"] != etag:
            raise CosmosHttpResponseError(status_code=412, message="Precondition failed")
        return self._store(body)

    def create_item(self, body):
        if body["id"] in self.documents:
            raise CosmosHttpResponseError(status_code=409, message="Conflict")
        return self._store(body)

    def upsert_item(self, body):
        return self._store(body)


class Harness:
    """Load the production sync code with in-memory Cosmos and Search fakes and the real fence."""

    def __init__(self):
        self.events = []
        self.logs = []
        self.blob_tag_calls = []
        self.cache_invalidations = []
        self.index_syncs = []
        self.index_success = True
        self.slot_holds = 0
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
        nodes = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in LOADED_FUNCTIONS
        ]
        missing = LOADED_FUNCTIONS - {node.name for node in nodes}
        assert not missing, f"Expected production definitions are missing: {sorted(missing)}"

        harness = self

        @contextmanager
        def write_slot(_container, **_options):
            if harness.search_writes_frozen:
                raise FakeSearchWritesFrozenError("AI Search writes are temporarily frozen.")
            harness.slot_holds += 1
            yield

        def sync_index(document_item, operation=None, **_kwargs):
            harness.index_syncs.append((document_item["id"], operation))
            return {"success": harness.index_success}

        namespace = {
            "json": json,
            "logging": logging,
            "re": re,
            "traceback": traceback,
            "uuid": uuid,
            "datetime": datetime,
            "timezone": timezone,
            "timedelta": timedelta,
            "nullcontext": nullcontext,
            "MatchConditions": MatchConditions,
            "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
            "DataManagementSearchWritesFrozenError": FakeSearchWritesFrozenError,
            "hold_data_management_search_write_slot": write_slot,
            "cosmos_data_management_jobs_container": object(),
            "prepare_embedding_search_documents": lambda *_args: None,
            "hold_group_document_projection": fence.hold_group_document_projection,
            "assert_group_document_source_writable": fence.assert_group_document_source_writable,
            "GroupDocumentProjectionConflict": fence.GroupDocumentProjectionConflict,
            "GROUP_DOCUMENT_PROJECTION_WRITER": fence.GROUP_DOCUMENT_PROJECTION_WRITER,
            "SCREENING_FIELD": SCREENING_FIELD,
            "ScreeningConflictError": ScreeningConflictError,
            "ScreeningValidationError": ScreeningValidationError,
            "document_is_available": document_is_available,
            "ORIGIN_FIELD_NAMES": frozenset({"origin_kind"}),
            "DocumentOriginError": FakeOriginError,
            "current_extraction": lambda _document_id: None,
            "is_publication": lambda *_args: False,
            "subject_from_document": lambda _document: None,
            "validate_screened_metadata_update": lambda *_args: None,
            "sync_document_access_index_for_document_fail_open": sync_index,
            "cosmos_user_documents_container": self.user_documents,
            "cosmos_group_documents_container": self.group_documents,
            "cosmos_public_documents_container": self.public_documents,
            "_get_search_client": lambda group_id=None, public_workspace_id=None: (
                harness.public_search if public_workspace_id is not None
                else harness.group_search if group_id is not None
                else harness.user_search
            ),
            "add_file_task_to_file_processing_log": lambda **_kwargs: None,
            "calculate_processing_percentage": lambda document_item: document_item.get("percentage_complete", 0),
            "propagate_tags_to_blob_metadata": lambda *args: harness.blob_tag_calls.append(args),
            "invalidate_personal_search_cache": lambda user_id: harness.cache_invalidations.append(("personal", user_id)),
            "invalidate_group_search_cache": lambda group_id, **_kwargs: harness.cache_invalidations.append(("group", group_id)),
            "invalidate_public_workspace_search_cache": (
                lambda workspace_id: harness.cache_invalidations.append(("public", workspace_id))
            ),
            "log_event": lambda message, extra=None, **kwargs: harness.logs.append((message, extra, kwargs)),
        }
        module = ast.Module(body=nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(DOCUMENTS_PATH), "exec"), namespace)
        load_document_search_sync_definitions(namespace, settings_container=self.settings)
        namespace["_document_search_sync_now"] = lambda: harness.clock

        real_upsert = namespace["_upsert_document_and_sync_access_index"]

        def recorded_upsert(cosmos_container, document_item, operation, **kwargs):
            harness.events.append(("upsert", document_item["id"], operation))
            return real_upsert(cosmos_container, document_item, operation, **kwargs)

        namespace["_upsert_document_and_sync_access_index"] = recorded_upsert
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
            "version": 1,
            "status": "Processing Complete",
            "percentage_complete": 100,
            "shared_user_ids": [],
            "_etag": uuid.uuid4().hex,
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
                "shared_user_ids": list(fields.get("shared_user_ids", [])),
            })
        return document

    def add_group_document(self, document_id="group-doc-1", group_id="group-1", chunk_count=4, **fields):
        document = {
            "id": document_id,
            "group_id": group_id,
            "user_id": "editor-1",
            "title": "Group XML",
            "tags": [],
            "version": 1,
            "status": "Processing Complete",
            "percentage_complete": 100,
            "shared_group_ids": [],
            "_etag": uuid.uuid4().hex,
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
        return self.settings.sync_records()


def released_marker():
    return {"state": "cleared", "scan_id": "scan-1"}


# --- Engine -------------------------------------------------------------------------------------

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


def test_projection_fails_loudly_when_a_batch_is_not_acknowledged():
    """An unacknowledged merge raises instead of reporting a completed projection."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness.user_search.fail_merges = True

    with pytest.raises(RuntimeError, match="did not acknowledge"):
        harness["project_fields_to_document_chunks"]("doc-1", {"title": "New"}, "owner-1")


def test_metadata_merges_carry_only_mirrored_fields_and_hold_the_write_slot():
    """Unfenced metadata merges carry only mirrored metadata, never access lists or scope fields,
    and every merge still holds the Data Management Search write slot."""
    harness = Harness()
    harness.add_group_document(chunk_count=5, shared_group_ids=["group-2,approved"])
    harness.namespace["DOCUMENT_SEARCH_SYNC_BATCH_SIZE"] = 2
    harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        title="Renamed", authors=["Ada"], document_classification="Internal", tags=["bills"],
    )
    etag_before_sync = harness.group_documents.documents["group-doc-1"]["_etag"]
    writes_before_sync = len(harness.group_documents.writes)

    result = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:group:group-doc-1")

    assert result["status"] == "complete" and result["chunks_updated"] == 5
    merges = harness.group_search.merge_batches
    assert len(merges) == 3 and harness.slot_holds == len(merges)
    for batch in merges:
        for action in batch:
            assert set(action) - {"id"} <= METADATA_INDEX_FIELDS, action
            assert "shared_group_ids" not in action and "shared_user_ids" not in action
    # The worker never writes to the document: no fence claim, no sync state, no etag change.
    assert harness.group_documents.documents["group-doc-1"]["_etag"] == etag_before_sync
    assert len(harness.group_documents.writes) == writes_before_sync
    assert all(chunk["shared_group_ids"] == ["group-2,approved"] for chunk in harness.group_search.chunks.values())

    for field_values, scope in (
        ({"title": "x", "shared_group_ids": []}, {"group_id": "group-1"}),
        ({"shared_user_ids": []}, {"group_id": "group-1"}),
        ({"shared_group_ids": []}, {}),
        ({"group_id": "group-2"}, {"group_id": "group-1"}),
        ({"user_id": "someone-else"}, {}),
    ):
        with pytest.raises(ValueError):
            harness["project_fields_to_document_chunks"]("group-doc-1", field_values, "editor-1", **scope)


# --- Durable sync request and worker ------------------------------------------------------------

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
    assert harness.cache_invalidations == [("personal", "owner-1")]


def test_worker_clears_cached_search_results_for_the_owner_and_approved_recipients():
    """A sync that changed chunks clears cached results for every scope that can see the document."""
    harness = Harness()
    harness.add_personal_document(
        chunk_count=3,
        shared_user_ids=["viewer-1,approved", "viewer-2,not_approved"],
    )
    harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"])

    harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-1")

    assert harness.cache_invalidations == [("personal", "owner-1"), ("personal", "viewer-1")]

    harness.cache_invalidations.clear()
    harness.add_group_document(shared_group_ids=["group-2,approved", "group-3,not_approved"])
    harness["update_document"](document_id="group-doc-1", group_id="group-1", user_id="editor-1", tags=["q3"])
    harness["run_document_search_metadata_sync"]("document_search_metadata_sync:group:group-doc-1")

    assert harness.cache_invalidations == [("group", "group-1"), ("group", "group-2")]

    harness.cache_invalidations.clear()
    harness.add_personal_document(document_id="doc-empty", chunk_count=0)
    harness["update_document"](document_id="doc-empty", user_id="owner-1", tags=["bills"])
    result = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-empty")

    assert result["status"] == "complete" and result["chunks_updated"] == 0
    assert harness.cache_invalidations == []


def test_a_sync_clears_the_workspace_search_cache_only_when_chunks_changed():
    """A search that ran mid-sync could have cached the old values, so a sync that changed chunks
    clears its workspace's cached results; a document with no chunks changes nothing to clear."""
    harness = Harness()
    harness.add_group_document(chunk_count=2)
    harness.add_group_document(document_id="no-chunks", chunk_count=0)
    harness["update_document"](document_id="group-doc-1", user_id="editor-1", group_id="group-1", strict=True,
                               expected_etag=harness.group_documents.documents["group-doc-1"]["_etag"], title="New")
    harness["update_document"](document_id="no-chunks", user_id="editor-1", group_id="group-1", strict=True,
                               expected_etag=harness.group_documents.documents["no-chunks"]["_etag"], title="New")

    results = [harness["run_document_search_metadata_sync"](record["id"]) for record in list(harness.sync_records())]

    assert sorted(result["status"] for result in results) == ["complete", "complete"]
    assert harness.cache_invalidations == [("group", "group-1")]
    harness.namespace["invalidate_group_search_cache"] = lambda *_args, **_kwargs: 1 / 0
    harness["update_document"](document_id="group-doc-1", user_id="editor-1", group_id="group-1", strict=True,
                               expected_etag=harness.group_documents.documents["group-doc-1"]["_etag"], title="Newer")
    assert harness["run_document_search_metadata_sync"]("document_search_metadata_sync:group:group-doc-1")["status"] == "complete"
    assert any("Cached search results were not cleared" in message for message, _extra, _kwargs in harness.logs)


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


def test_held_screened_documents_have_nothing_to_sync():
    """A held screened document has no released chunks: a save requests no sync, and a worker that
    finds the document held completes without projecting anything."""
    harness = Harness()
    harness.add_personal_document(chunk_count=3, content_screening={"state": "pending_review", "scan_id": "scan-1"})

    result = harness["update_document"](document_id="doc-1", user_id="owner-1", tags=["bills"])

    assert result == {"updated": True, "search_sync": {"status": "not_required"}}
    assert harness.sync_records() == []
    harness["request_document_search_metadata_sync"]("doc-1", ["tags"], "owner-1")
    harness.advance(601)
    outcome = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:personal:doc-1")
    assert outcome["status"] == "complete" and outcome["chunks_updated"] == 0
    assert harness.user_search.merge_batches == [] and harness.blob_tag_calls == []
    assert harness.sync_records() == []


def test_scheduler_deduplicates_queued_documents():
    """Repeated saves of one document queue a single in-process sync until it starts."""
    harness = Harness()

    assert harness["schedule_document_search_metadata_sync"]("doc-1") is True
    assert harness["schedule_document_search_metadata_sync"]("doc-1") is True
    assert harness["schedule_document_search_metadata_sync"]("doc-1", group_id="group-1") is True

    executor = harness["_document_search_sync_executor"]
    assert isinstance(executor, RecordingExecutor)
    assert [args for _function, args in executor.submitted] == [
        ("document_search_metadata_sync:personal:doc-1",),
        ("document_search_metadata_sync:group:doc-1",),
    ]


# --- Strict mode (native group and public APIs) -------------------------------------------------

def test_strict_update_carries_the_token_in_the_same_save_without_chunk_work():
    """A strict save requests the sync before it saves, stores the token in that same save, does no
    Search work, and re-requests the sync for every projected field it was sent (retry repairs)."""
    harness = Harness()
    harness.add_group_document(chunk_count=6, shared_group_ids=["group-2,approved"])
    document = harness.group_documents.documents["group-doc-1"]

    saved, search_sync = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        strict=True, expected_etag=document["_etag"], return_search_sync=True,
        tags=["bills"], abstract="Summary",
    )

    (record,) = harness.sync_records()
    assert search_sync == {"status": "pending", "revision": 1, "fields": ["tags"]}
    assert saved["search_metadata_sync_token"] == record["latest_request_token"]
    assert harness.group_documents.documents["group-doc-1"]["search_metadata_sync_token"] == record["latest_request_token"]
    assert harness.group_search.merge_batches == [] and harness.group_search.search_calls == []
    assert len([event for event in harness.events if event[0] == "upsert"]) == 1

    again = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        strict=True, expected_etag=saved["_etag"], tags=["bills"],
    )
    assert isinstance(again, dict) and again["id"] == "group-doc-1"
    (record,) = harness.sync_records()
    assert record["revision"] == 2 and again["search_metadata_sync_token"] == record["latest_request_token"]


def test_strict_group_metadata_edits_no_longer_race_the_projection_fence():
    """Strict group metadata edits used to project per chunk through the projection fence, whose
    claim rewrote the document etag after the first chunk and failed the edit. Metadata now syncs
    outside the fence, so the saved etag stays current and the next strict edit succeeds."""
    harness = Harness()
    harness.add_group_document(chunk_count=5)
    document = harness.group_documents.documents["group-doc-1"]

    saved = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        strict=True, expected_etag=document["_etag"], title="Renamed", tags=["bills"],
    )
    outcome = harness["run_document_search_metadata_sync"]("document_search_metadata_sync:group:group-doc-1")

    assert outcome["status"] == "complete" and outcome["chunks_updated"] == 5
    assert harness.group_documents.documents["group-doc-1"]["_etag"] == saved["_etag"]
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in harness.group_documents.documents["group-doc-1"]
    follow_up = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        strict=True, expected_etag=saved["_etag"], title="Renamed again",
    )
    assert follow_up["title"] == "Renamed again"
    assert all(chunk["document_tags"] == ["bills"] for chunk in harness.group_search.chunks.values())


def test_strict_access_index_failure_still_reports_incomplete_propagation():
    """Metadata projection no longer fails a strict save, but the access index projection still does."""
    harness = Harness()
    harness.add_group_document(chunk_count=2)
    harness.index_success = False
    document = harness.group_documents.documents["group-doc-1"]

    with pytest.raises(harness["DocumentMutationPropagationError"]):
        harness["update_document"](
            document_id="group-doc-1", group_id="group-1", user_id="editor-1",
            strict=True, expected_etag=document["_etag"], tags=["bills"],
        )
    assert harness.group_search.merge_batches == []


# --- Access control ------------------------------------------------------------------------------

def test_group_revocation_is_projected_before_it_is_saved():
    """A group revocation reaches every chunk through the projection fence before Cosmos records it.
    The fence's claim changes the document etag, which the save adopts."""
    harness = Harness()
    harness.add_group_document(shared_group_ids=["group-2,approved"])

    result = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1", shared_group_ids=[],
    )

    assert result["search_sync"] == {"status": "not_required"}
    kinds = [event[0] for event in harness.events]
    assert "merge" in kinds and kinds.index("merge") < kinds.index("upsert")
    assert all(set(action) == {"id", "shared_group_ids"} for batch in harness.group_search.merge_batches for action in batch)
    assert all(chunk["shared_group_ids"] == [] for chunk in harness.group_search.chunks.values())
    stored = harness.group_documents.documents["group-doc-1"]
    assert stored["shared_group_ids"] == []
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in stored
    # The fence claimed and released the document around the merge, then the save adopted its etag.
    assert harness.group_documents.writes == ["group-doc-1", "group-doc-1", "group-doc-1"]
    assert harness.sync_records() == []


def test_group_revocation_is_not_saved_when_search_cannot_enforce_it():
    """A failed or frozen revocation projection raises and leaves the stored access unchanged."""
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
    stored = harness.group_documents.documents["group-doc-1"]
    assert stored["shared_group_ids"] == ["group-2,approved"]
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in stored
    assert not any(event[0] == "upsert" for event in harness.events)


def test_concurrent_change_during_a_revocation_restores_search_to_cosmos():
    """When another writer changes the document while a revocation is being projected, the update
    is refused with a conflict and Search is projected back to the list Cosmos records."""
    harness = Harness()
    harness.add_group_document(shared_group_ids=["group-2,approved"])
    concurrent = []

    def concurrent_title_change(_documents):
        if not concurrent:
            concurrent.append(True)
            harness.group_documents.documents["group-doc-1"]["title"] = "Concurrent winner"

    harness.group_search.before_merge = concurrent_title_change

    with pytest.raises(ScreeningConflictError):
        harness["update_document"](
            document_id="group-doc-1", group_id="group-1", user_id="editor-1", shared_group_ids=[],
        )

    stored = harness.group_documents.documents["group-doc-1"]
    assert stored["title"] == "Concurrent winner" and stored["shared_group_ids"] == ["group-2,approved"]
    assert all(chunk["shared_group_ids"] == ["group-2,approved"] for chunk in harness.group_search.chunks.values())
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in stored
    assert not any(event[0] == "upsert" for event in harness.events)


def test_group_grant_is_projected_once_cosmos_records_it():
    """The projection fence admits a group grant only after it is saved, so approvals are projected
    after the save. A grant that does not reach Search is reported for a retry to complete it, while
    a pending share, which grants nothing, is projected best effort."""
    harness = Harness()
    harness.add_group_document(shared_group_ids=["group-2,not_approved"])

    harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1", shared_group_ids=["group-2,approved"],
    )

    kinds = [event[0] for event in harness.events]
    assert kinds.index("upsert") < kinds.index("merge")
    assert all(chunk["shared_group_ids"] == ["group-2,approved"] for chunk in harness.group_search.chunks.values())
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in harness.group_documents.documents["group-doc-1"]

    harness.group_search.fail_merges = True
    with pytest.raises(harness["DocumentMutationPropagationError"]) as failed:
        harness["update_document"](
            document_id="group-doc-1", group_id="group-1", user_id="editor-1",
            shared_group_ids=["group-2,approved", "group-3,approved"],
        )
    assert failed.value.search_writes_frozen is False
    assert harness.group_documents.documents["group-doc-1"]["shared_group_ids"] == ["group-2,approved", "group-3,approved"]
    assert harness["describe_document_search_acl_error"](failed.value)[1] == 500

    harness.group_search.fail_merges = False
    harness.search_writes_frozen = True
    with pytest.raises(harness["DocumentMutationPropagationError"]) as frozen:
        harness["update_document"](
            document_id="group-doc-1", group_id="group-1", user_id="editor-1",
            shared_group_ids=["group-2,approved", "group-3,approved", "group-4,approved"],
        )
    assert frozen.value.search_writes_frozen is True
    message, status, retry_after = harness["describe_document_search_acl_error"](frozen.value)
    assert status == 503 and retry_after and "frozen" in message

    harness.search_writes_frozen = False
    harness.group_search.fail_merges = True
    pending = harness["update_document"](
        document_id="group-doc-1", group_id="group-1", user_id="editor-1",
        shared_group_ids=["group-2,approved", "group-3,approved", "group-4,approved", "group-5,not_approved"],
    )
    assert pending["updated"] is True
    assert any("grants no search access" in message for message, _extra, _kwargs in harness.logs)


def test_reprojection_repairs_a_saved_approval():
    """Approving an already-approved share projects the recorded list again, which completes an
    approval saved before its search update finished. Held documents are rebuilt on publication."""
    harness = Harness()
    harness.add_group_document(shared_group_ids=["group-2,approved"])
    for chunk in harness.group_search.chunks.values():
        chunk["shared_group_ids"] = []
    document = harness.group_documents.documents["group-doc-1"]

    assert harness["reproject_document_search_acl"](document, "editor-1", group_id="group-1") == 4
    assert all(chunk["shared_group_ids"] == ["group-2,approved"] for chunk in harness.group_search.chunks.values())

    harness.add_personal_document(document_id="doc-9", shared_user_ids=["viewer-1,approved"], chunk_count=2)
    for chunk in harness.user_search.chunks.values():
        chunk["shared_user_ids"] = []
    assert harness["reproject_document_search_acl"](harness.user_documents.documents["doc-9"], "viewer-1") == 2
    assert all(chunk["shared_user_ids"] == ["viewer-1,approved"] for chunk in harness.user_search.chunks.values())

    held = dict(document, content_screening={"state": "pending_review", "scan_id": "scan-1"})
    merges = len(harness.group_search.merge_batches)
    assert harness["reproject_document_search_acl"](held, "editor-1", group_id="group-1") == 0
    assert len(harness.group_search.merge_batches) == merges

    harness.group_search.fail_merges = True
    with pytest.raises(harness["DocumentMutationPropagationError"]):
        harness["reproject_document_search_acl"](document, "editor-1", group_id="group-1")


def test_personal_access_changes_project_before_save_and_held_documents_project_only_revocations():
    """A personal access change reaches Search before Cosmos records it. A held document projects
    only the revocation part; its grants are rebuilt when it is published."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2, shared_user_ids=["viewer-1,approved"])

    harness["update_document"](
        document_id="doc-1", user_id="owner-1", shared_user_ids=["viewer-2,approved"],
    )
    kinds = [event[0] for event in harness.events]
    assert kinds.index("merge") < kinds.index("upsert")
    assert all(chunk["shared_user_ids"] == ["viewer-2,approved"] for chunk in harness.user_search.chunks.values())

    harness.add_personal_document(
        document_id="doc-held", chunk_count=2, shared_user_ids=["viewer-1,approved"],
        content_screening={"state": "pending_review", "scan_id": "scan-1"},
    )
    harness["update_document"](
        document_id="doc-held", user_id="owner-1", shared_user_ids=["viewer-3,approved"],
    )
    held_chunks = [chunk for chunk in harness.user_search.chunks.values() if chunk["document_id"] == "doc-held"]
    assert all(chunk["shared_user_ids"] == [] for chunk in held_chunks)


def test_public_documents_have_no_acl_projection():
    """Public workspace documents carry no per-document ACL fields to project."""
    harness = Harness()
    assert harness["get_document_search_acl_fields"](public_workspace_id="ws-1") == ()
    assert harness["get_document_search_acl_fields"](group_id="group-1") == ("shared_group_ids",)
    assert harness["get_document_search_acl_fields"]() == ("shared_user_ids",)


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


def test_pending_share_is_saved_even_when_projection_fails():
    """A pending share grants no search access, so its projection is best effort after the save."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2)
    harness.user_search.fail_merges = True

    assert harness["share_document_with_user"]("doc-1", "owner-1", "viewer-1") is True
    assert harness.user_documents.documents["doc-1"]["shared_user_ids"] == ["viewer-1,not_approved"]
    assert any("pending share" in message for message, _extra, _kwargs in harness.logs)


def test_unshare_fails_closed_and_reports_why():
    """An unshare projects before it saves; a failed or frozen projection is raised, not hidden as
    a generic failure, and the stored access is unchanged."""
    harness = Harness()
    harness.add_personal_document(chunk_count=2, shared_user_ids=["viewer-1,approved"])
    harness.user_search.fail_merges = True

    with pytest.raises(harness["DocumentSearchAclProjectionError"]):
        harness["unshare_document_from_user"]("doc-1", "owner-1", "viewer-1")
    assert harness.user_documents.documents["doc-1"]["shared_user_ids"] == ["viewer-1,approved"]

    harness.user_search.fail_merges = False
    harness.search_writes_frozen = True
    with pytest.raises(harness["DocumentSearchAclProjectionDeferredError"]):
        harness["unshare_document_from_user"]("doc-1", "owner-1", "viewer-1")
    assert harness.user_documents.documents["doc-1"]["shared_user_ids"] == ["viewer-1,approved"]

    harness.search_writes_frozen = False
    assert harness["unshare_document_from_user"]("doc-1", "owner-1", "viewer-1") is True
    assert harness.user_documents.documents["doc-1"]["shared_user_ids"] == []
    assert all(chunk["shared_user_ids"] == [] for chunk in harness.user_search.chunks.values())


def test_access_errors_map_to_fixed_safe_responses():
    """Every access-change failure maps to a fixed message, with Retry-After while writes are frozen."""
    harness = Harness()
    describe = harness["describe_document_search_acl_error"]

    deferred = describe(harness["DocumentSearchAclProjectionDeferredError"]("raw provider text"))
    failed = describe(harness["DocumentSearchAclProjectionError"]("raw provider text"))
    incomplete = describe(harness["DocumentMutationPropagationError"]("raw provider text"))
    conflict = describe(ScreeningConflictError())

    assert deferred[1:] == (503, 150) and failed[1:] == (500, None)
    assert incomplete[1:] == (500, None) and conflict[1:] == (409, None)
    assert all("raw provider text" not in message for message, _status, _retry in (deferred, failed, incomplete, conflict))
    assert describe(ValueError("other")) is None


# --- Routes, receipts, client and background wiring ----------------------------------------------

def _function(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def test_routes_and_client_no_longer_drive_per_chunk_sync():
    """Metadata routes save once, tag routes drop duplicate passes, and the background loop is wired."""
    assert_app_version_at_least("0.261.268")
    route_files = {
        "route_backend_documents.py": "api_patch_user_document",
        "route_backend_group_documents.py": "api_patch_group_document",
        "route_backend_public_documents.py": "api_patch_public_document",
        "route_external_public_documents.py": "external_patch_public_document",
    }
    for file_name, patch_route_name in route_files.items():
        source = (APP_ROOT / file_name).read_text(encoding="utf-8")
        assert "propagate_tags_to_chunks" not in source, f"{file_name} still runs a duplicate tag pass"
        tree = ast.parse(source)
        patch_route = _function(tree, patch_route_name)
        update_calls = [
            node for node in ast.walk(patch_route)
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "update_document"
        ]
        assert len(update_calls) == 1, f"{patch_route_name} must save every field in one update_document call"
        route_source = ast.get_source_segment(source, patch_route)
        assert "search_sync" in route_source
        assert "str(e)" not in route_source

    documents_source = DOCUMENTS_PATH.read_text(encoding="utf-8")
    assert "def propagate_tags_to_chunks" not in documents_source
    assert "chunk_sync_limit" not in documents_source

    for script in (
        APP_ROOT / "static" / "js" / "workspace" / "workspace-documents.js",
        APP_ROOT / "static" / "js" / "public" / "public_workspace.js",
        APP_ROOT / "templates" / "group_workspaces.html",
    ):
        assert "search_sync?.status === \"pending\"" in script.read_text(encoding="utf-8"), script.name

    background_source = (APP_ROOT / "background_tasks.py").read_text(encoding="utf-8")
    assert "def run_document_search_metadata_sync_loop():" in background_source
    assert "acquire_distributed_task_lock('document_search_metadata_sync_scan'" in background_source
    assert "run_document_search_metadata_sync_loop)," in background_source


def test_native_receipts_report_search_sync_and_approvals_repair():
    """Native receipts carry search_sync, and every approve route repairs an already-approved share."""
    for file_name, metadata_name, tag_names in (
        ("functions_group_document_management.py", "update_group_document_metadata",
         ("tag_group_documents", "change_group_document_tag")),
        ("functions_public_document_management.py", "update_public_document_metadata",
         ("tag_public_documents", "change_public_document_tag")),
    ):
        source = (APP_ROOT / file_name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        metadata_source = ast.get_source_segment(source, _function(tree, metadata_name))
        assert "return_search_sync=True" in metadata_source and '"search_sync": search_sync' in metadata_source
        for tag_name in tag_names:
            assert 'result["search_sync"] = summarize_document_search_sync(' in ast.get_source_segment(source, _function(tree, tag_name))

    collaboration_source = (APP_ROOT / "functions_group_document_collaboration.py").read_text(encoding="utf-8")
    change_share = ast.get_source_segment(collaboration_source, _function(ast.parse(collaboration_source), "change_group_document_share"))
    assert "_repair_approved_share_search_acl(user_id, group_id, document)" in change_share
    repair = ast.get_source_segment(collaboration_source, _function(ast.parse(collaboration_source), "_repair_approved_share_search_acl"))
    assert repair.index("_search_acl_is_current(document)") < repair.index("_search_acl(document, operation_guard=guard)")

    group_source = (APP_ROOT / "route_backend_group_documents.py").read_text(encoding="utf-8")
    group_tree = ast.parse(group_source)
    approve_group = ast.get_source_segment(group_source, _function(group_tree, "api_approve_shared_group_document"))
    assert "reproject_document_search_acl(" in approve_group
    for route_name in (
        "api_approve_shared_group_document",
        "api_share_document_with_group",
        "api_unshare_document_with_group",
        "api_remove_self_from_group_document",
    ):
        route_source = ast.get_source_segment(group_source, _function(group_tree, route_name))
        assert "_group_share_search_acl_error_response(exc)" in route_source, route_name
        assert "str(e)" not in route_source, route_name

    personal_source = (APP_ROOT / "route_backend_documents.py").read_text(encoding="utf-8")
    approve_personal = ast.get_source_segment(personal_source, _function(ast.parse(personal_source), "api_approve_shared_document"))
    assert approve_personal.index("project_document_acl_to_chunks(") < approve_personal.index("upsert_item(document_item)")
    assert 'elif f"{user_id},approved" in shared_user_ids:' in approve_personal
    assert "reproject_document_search_acl(document_item, user_id)" in approve_personal


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
