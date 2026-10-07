# document_search_sync.py
"""
Test support for the durable document search metadata sync.
Version: 0.261.268
Implemented in: 0.261.268

Several suites execute the real update_document() from functions_documents.py in an isolated
namespace. update_document() now records search metadata sync requests and projects access
changes, so those namespaces need the sync constants and helpers too. This module copies the real
definitions into a namespace, with an in-memory settings container and an executor that only
records queued work, so no test reaches Cosmos, Search, or a background thread.
"""

import ast
import contextlib
import copy
import importlib
import json
import logging
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"
DOCUMENTS_PATH = APP_ROOT / "functions_documents.py"
# The section of functions_documents.py that holds the sync constants and helpers.
SECTION_START = "DOCUMENT_SEARCH_SYNC_RECORD_TYPE"
SECTION_END = "get_pdf_page_count"
DOCUMENT_SEARCH_SYNC_CLASSES = (
    "DocumentSearchAclProjectionDeferredError",
    "DocumentSearchAclProjectionError",
    "DocumentSearchSyncLeaseLostError",
    "DocumentMutationPropagationError",
)


class FakeSettingsContainer:
    """In-memory Cosmos container with etag preconditions and real Cosmos error types."""

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
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        if body["id"] in self.items:
            raise CosmosHttpResponseError(status_code=409, message="Conflict")
        return self._store(body)

    def replace_item(self, item, body, etag=None, match_condition=None):
        if self.before_replace is not None:
            self.before_replace(item)
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        if etag is not None and self.items[item]["_etag"] != etag:
            raise CosmosHttpResponseError(status_code=412, message="Precondition failed")
        return self._store(body)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        if etag is not None and self.items[item]["_etag"] != etag:
            raise CosmosHttpResponseError(status_code=412, message="Precondition failed")
        del self.items[item]

    def query_items(self, query, parameters, enable_cross_partition_query=False):
        values = {parameter["name"]: parameter["value"] for parameter in parameters}
        due = [
            item for item in self.items.values()
            if item.get("type") == values["@type"] and str(item.get("next_attempt_at") or "") <= values["@now"]
        ]
        due.sort(key=lambda item: item.get("next_attempt_at") or "")
        return [{"id": item["id"]} for item in due[: values["@limit"]]]

    def sync_records(self):
        return [item for item in self.items.values() if item.get("type") == "document_search_metadata_sync"]


class RecordingExecutor:
    """Capture queued sync work so a test decides when, or whether, it runs."""

    def __init__(self, max_workers=None, thread_name_prefix=None):
        self.submitted = []

    def submit(self, function, *args):
        self.submitted.append((function, args))


class FakeSearchClient:
    """AI Search client that evaluates the chunk key-paging filter and applies merges."""

    FILTER_PATTERN = re.compile(
        r"^document_id eq '(?P<document_id>(?:[^']|'')*)' "
        r"and (?P<scope_field>user_id|group_id|public_workspace_id) eq '(?P<scope_value>(?:[^']|'')*)'"
        r"(?: and id gt '(?P<last_key>(?:[^']|'')*)')?$"
    )

    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.chunks = {}
        self.search_calls = []
        self.merge_batches = []
        self.fail_merges = False
        self.merge_error = None
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
        if self.merge_error is not None:
            raise self.merge_error
        self.merge_batches.append(copy.deepcopy(documents))
        self.events.append(("merge", [document["id"] for document in documents]))
        if self.fail_merges:
            return [{"succeeded": False} for _ in documents]
        for document in documents:
            self.chunks[document["id"]].update({key: value for key, value in document.items() if key != "id"})
        return [{"succeeded": True} for _ in documents]


def install_fake_search(namespace, search_client=None):
    """Point a namespace's Search client and Search write helper at one in-memory index.

    The write helper keeps the production contract that matters to callers: it raises unless every
    document in the batch is acknowledged. The projection fence and write slot have their own suite.
    Returns the search client.
    """
    search_client = search_client or FakeSearchClient()

    def execute_search_write(client, operation_name, *args, group_id=None, document_id=None, document_version=None, **kwargs):
        results = getattr(client, operation_name)(*args, **kwargs)
        if not all(result.get("succeeded") for result in results):
            raise RuntimeError(f"Azure AI Search did not acknowledge every {operation_name} document mutation.")
        return results

    namespace["_get_search_client"] = lambda group_id=None, public_workspace_id=None: search_client
    namespace["_execute_document_search_write"] = execute_search_write
    return search_client


def run_document_search_syncs(namespace):
    """Run every recorded sync request now, the way the in-process worker or the reconciler would."""
    container = namespace["cosmos_settings_container"]
    return [
        namespace["run_document_search_metadata_sync"](record["id"])
        for record in list(container.sync_records())
    ]


def _fence_writer_field():
    """Return the projection fence's claim field from the real, bootstrap-free fence module."""
    original_path = list(sys.path)
    try:
        sys.path.insert(0, str(APP_ROOT))
        fence = importlib.import_module("functions_group_document_projection_fence")
    finally:
        sys.path[:] = original_path
    # A suite may have replaced the module with a stub; the field name itself is a stable contract.
    return getattr(fence, "GROUP_DOCUMENT_PROJECTION_WRITER", "group_document_projection_writer")


def document_search_sync_nodes(skip_names=()):
    """Return the AST nodes of the sync classes, constants and helpers in functions_documents.py."""
    tree = ast.parse(DOCUMENTS_PATH.read_text(encoding="utf-8"), filename=str(DOCUMENTS_PATH))
    start_line = next(
        node.lineno for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == SECTION_START for target in node.targets)
    )
    end_line = next(
        node.lineno for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == SECTION_END
    )
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in DOCUMENT_SEARCH_SYNC_CLASSES
        and node.name not in skip_names
    ]
    for node in tree.body:
        if not start_line <= node.lineno < end_line:
            continue
        name = getattr(node, "name", None)
        if name is not None and name in skip_names:
            continue
        nodes.append(node)
    return nodes


def load_document_search_sync_definitions(namespace, *, settings_container=None, keep=()):
    """Execute the real sync definitions into namespace and fill in their dependencies.

    Dependencies the harness already provides win, so its own fakes for Search writes, containers
    and logging stay in place. Names in keep are left as the harness defined them. Returns the
    settings container the definitions use.
    """
    settings_container = settings_container or namespace.get("cosmos_settings_container") or FakeSettingsContainer()
    defaults = {
        "json": json,
        "logging": logging,
        "threading": threading,
        "time": time,
        "uuid": uuid,
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "nullcontext": contextlib.nullcontext,
        "MatchConditions": MatchConditions,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "ThreadPoolExecutor": RecordingExecutor,
        "GROUP_DOCUMENT_PROJECTION_WRITER": _fence_writer_field(),
        "log_event": lambda *_args, **_kwargs: None,
        "propagate_tags_to_blob_metadata": lambda *_args, **_kwargs: None,
        "add_file_task_to_file_processing_log": lambda **_kwargs: None,
        "invalidate_personal_search_cache": lambda *_args, **_kwargs: 0,
        "invalidate_group_search_cache": lambda *_args, **_kwargs: 0,
        "invalidate_public_workspace_search_cache": lambda *_args, **_kwargs: 0,
    }
    for name, value in defaults.items():
        namespace.setdefault(name, value)
    namespace["cosmos_settings_container"] = settings_container
    for name in ("DataManagementSearchWritesFrozenError", "ScreeningConflictError"):
        namespace.setdefault(name, type(name, (Exception,), {}))
    skip = {name for name in DOCUMENT_SEARCH_SYNC_CLASSES if name in namespace} | set(keep)
    module = ast.Module(body=document_search_sync_nodes(skip_names=skip), type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(DOCUMENTS_PATH), "exec"), namespace)
    return settings_container
