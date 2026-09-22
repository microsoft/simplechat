# test_group_document_projection_fence.py
"""
Functional test for group projection/collaboration exclusion.
Version: 0.261.130
Implemented in: 0.261.130

Conditional in-memory storage exercises the real pure fence helper without
application bootstrap or cloud calls.
"""

import copy
import ast
import importlib
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ServiceResponseError
from azure.cosmos.exceptions import CosmosHttpResponseError


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
original_path = list(sys.path)
try:
    sys.path.insert(0, str(APP_DIR))
    fence = importlib.import_module("functions_group_document_projection_fence")
finally:
    sys.path[:] = original_path


class ConditionalSource:
    def __init__(self):
        self.document = {"id": "doc", "group_id": "owner", "version": 2, "_etag": "1", "shared_group_ids": ["recipient,approved"]}
        self.lock = Lock()
        self.before_replace = None
        self.replacements = 0

    def read_item(self, item, partition_key):
        assert item == partition_key == "doc"
        with self.lock:
            if self.document is None:
                raise CosmosHttpResponseError(status_code=404, message="Fixture missing")
            return copy.deepcopy(self.document)

    def replace_item(self, *, item, body, etag, match_condition):
        assert item == "doc" and match_condition == MatchConditions.IfNotModified
        if self.before_replace:
            callback, self.before_replace = self.before_replace, None
            callback(self)
        with self.lock:
            if self.document is None:
                raise CosmosHttpResponseError(status_code=404, message="Fixture missing")
            if etag != self.document["_etag"]:
                raise CosmosHttpResponseError(status_code=412, message="Fixture conflict")
            self.document = {**copy.deepcopy(body), "_etag": str(int(etag) + 1)}
            self.replacements += 1
            return copy.deepcopy(self.document)


def operation(phase="executing"):
    return {
        "schema_version": 1, "id": "operation", "document_id": "doc",
        "source_group_id": "owner", "document_version": 2, "phase": phase,
        "execution_token": "execution",
    }


def test_writer_claim_blocks_collaboration_and_another_writer_until_completion():
    store = ConditionalSource()
    with fence.hold_group_document_projection(store, "doc", "owner", expected_version=2) as current:
        assert current[fence.GROUP_DOCUMENT_PROJECTION_WRITER]["state"] == "executing"
        with pytest.raises(fence.GroupDocumentProjectionConflict):
            fence.assert_no_group_document_projection_writer(current)
        with fence.hold_group_document_projection(store, "doc", "owner") as nested:
            assert nested["_etag"] == current["_etag"]
        assert store.replacements == 1
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in store.document
    assert store.replacements == 2


@pytest.mark.parametrize("phase", ["claimed", "executing", "repair", "uncertain"])
def test_unfinished_collaboration_blocks_an_ordinary_projection(phase):
    store = ConditionalSource()
    store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION] = operation(phase)
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            pytest.fail("Projection must not execute.")
    assert store.replacements == 0


def test_only_exact_executing_collaboration_context_may_project():
    store = ConditionalSource()
    store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION] = operation()
    with fence.group_collaboration_projection_context("doc", "operation", "wrong-token"):
        with pytest.raises(fence.GroupDocumentProjectionConflict):
            with fence.hold_group_document_projection(store, "doc", "owner"):
                pytest.fail("Wrong executor must not project.")
    with fence.group_collaboration_projection_context("doc", "operation", "execution"):
        with fence.hold_group_document_projection(store, "doc", "owner") as current:
            assert current["id"] == "doc"
    assert store.replacements == 0
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            pytest.fail("Executor context must not leak.")


def test_late_writer_cannot_overwrite_a_collaboration_claim():
    store = ConditionalSource()
    def claim(current_store):
        current_store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION] = operation("claimed")
        current_store.document["_etag"] = "2"
    store.before_replace = claim
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            pytest.fail("Losing writer must not execute.")
    assert store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION]["phase"] == "claimed"
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in store.document


@pytest.mark.parametrize("error", [TimeoutError("fixture"), ServiceResponseError("fixture")])
def test_ambiguous_effect_never_expires_or_releases_its_claim(error):
    store = ConditionalSource()
    with pytest.raises(type(error)):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            raise error
    assert store.document[fence.GROUP_DOCUMENT_PROJECTION_WRITER]["state"] == "uncertain"
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        fence.assert_no_group_document_projection_writer(store.document)
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            pytest.fail("Unknown outcome must not admit another writer.")


def test_known_service_refusal_releases_claim_without_changing_acl():
    store = ConditionalSource()
    with pytest.raises(CosmosHttpResponseError):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            raise CosmosHttpResponseError(status_code=403, message="Fixture denial")
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in store.document
    assert store.document["shared_group_ids"] == ["recipient,approved"]


@pytest.mark.parametrize("group_id,version", [("other", 2), ("owner", 3)])
def test_wrong_scope_or_revision_cannot_claim(group_id, version):
    store = ConditionalSource()
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        with fence.hold_group_document_projection(store, "doc", group_id, expected_version=version):
            pytest.fail("Wrong identity must not execute.")
    assert store.replacements == 0


def test_deleted_source_is_not_recreated():
    store = ConditionalSource()
    store.document = None
    with pytest.raises(fence.GroupDocumentProjectionConflict):
        with fence.hold_group_document_projection(store, "doc", "owner"):
            pytest.fail("Missing source must not project.")
    with fence.hold_group_document_projection(store, "doc", "owner", allow_missing=True) as current:
        assert current is None
    assert store.document is None
    assert store.replacements == 0


def test_remote_writer_cannot_finish_after_a_successful_revocation():
    store = ConditionalSource()
    started, finish = Event(), Event()
    failures = []
    projected = []
    def publish():
        try:
            with fence.hold_group_document_projection(store, "doc", "owner") as current:
                started.set()
                if not finish.wait(5):
                    raise TimeoutError("Fixture barrier did not open")
                projected.append(current["shared_group_ids"])
        except Exception as error:
            failures.append(error)
    worker = Thread(target=publish)
    worker.start()
    try:
        ready = started.wait(5)
        assert ready
        snapshot = store.read_item(item="doc", partition_key="doc")
        with pytest.raises(fence.GroupDocumentProjectionConflict):
            fence.assert_no_group_document_projection_writer(snapshot)
        with pytest.raises(fence.GroupDocumentProjectionConflict):
            with fence.hold_group_document_projection(store, "doc", "owner"):
                pytest.fail("A second thread must not inherit the writer token.")
    finally:
        finish.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert not failures
    assert projected == [["recipient,approved"]]
    snapshot = store.read_item(item="doc", partition_key="doc")
    fence.assert_no_group_document_projection_writer(snapshot)
    snapshot["shared_group_ids"] = []
    snapshot[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION] = operation("complete")
    saved = store.replace_item(item="doc", body=snapshot, etag=snapshot["_etag"], match_condition=MatchConditions.IfNotModified)
    with fence.hold_group_document_projection(store, "doc", "owner") as current:
        assert current["shared_group_ids"] == saved["shared_group_ids"] == []


def _search_writer(store, *, frozen=False):
    names = {"_execute_document_search_write", "_search_indexing_results_succeeded"}
    tree = ast.parse((APP_DIR / "functions_documents.py").read_text(encoding="utf-8"))
    module = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    events = []
    @contextmanager
    def migration_slot(*args, **kwargs):
        events.append("migration")
        if frozen:
            raise RuntimeError("Fixture migration freeze")
        yield
    from contextlib import nullcontext
    scope = {
        "hold_group_document_projection": fence.hold_group_document_projection,
        "GroupDocumentProjectionConflict": fence.GroupDocumentProjectionConflict,
        "nullcontext": nullcontext,
        "cosmos_group_documents_container": store,
        "cosmos_data_management_jobs_container": object(),
        "hold_data_management_search_write_slot": migration_slot,
        "prepare_embedding_search_documents": lambda *args: events.append("embedding"),
        "_build_archived_scope_value": lambda value: f"archived_{value}",
        "log_event": lambda *args, **kwargs: None,
    }
    exec(compile(module, "functions_documents.py", "exec"), scope)
    return scope["_execute_document_search_write"], events


def test_real_search_boundary_drops_revoked_snapshot_grants_and_blocks_overlapping_collaboration():
    store = ConditionalSource()
    store.document["shared_group_ids"] = []
    store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION] = operation("complete")
    execute, events = _search_writer(store)
    captured = []
    class Search:
        def upload_documents(self, *, documents, **kwargs):
            current = store.read_item(item="doc", partition_key="doc")
            with pytest.raises(fence.GroupDocumentProjectionConflict):
                fence.assert_no_group_document_projection_writer(current)
            captured.extend(copy.deepcopy(documents))
            return [{"succeeded": True}]
    old_chunk = {
        "id": "doc_1", "document_id": "doc", "group_id": "owner", "version": 2,
        "shared_group_ids": ["recipient,approved"],
    }
    results = execute(
        Search(), "upload_documents", documents=[old_chunk],
        group_id="owner", document_id="doc", document_version=2,
    )
    assert results == [{"succeeded": True}]
    assert captured[0]["shared_group_ids"] == []
    assert events == ["migration"]
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in store.document


def test_existing_migration_freeze_still_precedes_embedding_preparation():
    store = ConditionalSource()
    execute, events = _search_writer(store, frozen=True)
    class Search:
        def upload_documents(self, **kwargs):
            pytest.fail("A frozen migration cannot publish.")
    with pytest.raises(RuntimeError, match="Fixture migration freeze"):
        execute(Search(), "upload_documents", documents=[{"id": "personal_1", "embedding": [1.0]}])
    assert events == ["migration"]


def test_real_dai_boundary_reloads_source_instead_of_regranting_a_stale_snapshot():
    from test_cosmos_wave5a_document_access_read_switch import _load_document_access_index_module, _document
    with _load_document_access_index_module() as (indexing, index, _settings):
        source = _document("doc", "author", group_id="owner", version=2, _etag="source", shared_group_ids=[])
        stale = {**source, "shared_group_ids": ["recipient,approved"]}
        indexing.cosmos_group_documents_container.upsert_item(source)
        original_upsert = index.upsert_item
        def captured_upsert(body):
            current = indexing.cosmos_group_documents_container.read_item(item="doc", partition_key="doc")
            with pytest.raises(fence.GroupDocumentProjectionConflict):
                fence.assert_no_group_document_projection_writer(current)
            return original_upsert(body)
        index.upsert_item = captured_upsert
        try:
            outcome = indexing.sync_document_access_index_for_document(stale, force=True)
        finally:
            index.upsert_item = original_upsert
        rows = list(index.items.values())
        current = indexing.cosmos_group_documents_container.read_item(item="doc", partition_key="doc")
    assert outcome["success"] is True
    assert rows
    assert not [row for row in rows if row.get("scope_id") == "recipient"]
    assert fence.GROUP_DOCUMENT_PROJECTION_WRITER not in current


def test_legacy_group_source_update_cannot_overwrite_a_new_collaboration_claim():
    store = ConditionalSource()
    source = store.read_item(item="doc", partition_key="doc")
    source["title"] = "An older metadata request"
    tree = ast.parse((APP_DIR / "functions_documents.py").read_text(encoding="utf-8"))
    module = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
              and node.name == "_upsert_document_and_sync_access_index"],
        type_ignores=[],
    )
    projected = []
    scope = {
        "CosmosResourceNotFoundError": type("Missing", (Exception,), {}),
        "SCREENING_FIELD": "content_screening",
        "ScreeningConflictError": fence.GroupDocumentProjectionConflict,
        "assert_group_document_source_writable": fence.assert_group_document_source_writable,
        "MatchConditions": MatchConditions,
        "sync_document_access_index_for_document_fail_open": lambda *args, **kwargs: projected.append(args),
    }
    exec(compile(module, "functions_documents.py", "exec"), scope)
    def concurrent_claim(current_store):
        current_store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION] = operation("claimed")
        current_store.document["shared_group_ids"] = []
        current_store.document["_etag"] = "2"
    store.before_replace = concurrent_claim
    with pytest.raises(CosmosHttpResponseError):
        scope["_upsert_document_and_sync_access_index"](store, source, "document_updated", strict=False)
    assert projected == []
    assert store.document["shared_group_ids"] == []
    assert store.document[fence.GROUP_DOCUMENT_COLLABORATION_OPERATION]["phase"] == "claimed"
    assert "title" not in store.document


@pytest.mark.parametrize("optimized", [False, True])
def test_fence_helper_cold_import_has_no_application_bootstrap_or_network(optimized):
    probe = """
import importlib
import socket
import sys
def deny(*args, **kwargs):
    raise RuntimeError("Unexpected network access")
socket.socket.connect = deny
socket.create_connection = deny
sys.path.insert(0, sys.argv[1])
module = importlib.import_module("functions_group_document_projection_fence")
if "config" in sys.modules or "functions_settings" in sys.modules:
    raise RuntimeError("Fence helper crossed an application bootstrap boundary")
if module.GROUP_DOCUMENT_PROJECTION_WRITER != "group_document_projection_writer":
    raise RuntimeError("Unexpected writer-field contract")
"""
    command = [sys.executable, *(["-O"] if optimized else []), "-c", probe, str(APP_DIR)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
