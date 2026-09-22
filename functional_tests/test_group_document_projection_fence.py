# test_group_document_projection_fence.py
"""
Functional test for group projection/collaboration exclusion.
Version: 0.261.130
Implemented in: 0.261.130

Conditional in-memory storage exercises the real pure fence helper without
application bootstrap or cloud calls.
"""

import copy
import importlib.util
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ServiceResponseError
from azure.cosmos.exceptions import CosmosHttpResponseError


MODULE_PATH = Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_group_document_projection_fence.py"
SPEC = importlib.util.spec_from_file_location("group_projection_fence_test_module", MODULE_PATH)
fence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fence)


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
