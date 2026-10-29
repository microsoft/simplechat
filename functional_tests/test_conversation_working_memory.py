# test_conversation_working_memory.py
#!/usr/bin/env python3
"""
Functional tests for reusable conversation working memory and analysis jobs.
Version: 0.261.029
Implemented in: 0.261.029

Real modules run against scoped, ETag-aware blob fakes. These tests cover exact
authorization, immutable evidence, bounded reads, approval publication, worker
fencing, interrupted commits, retention, independent forks, and cold imports.
No Azure account, application bootstrap, Flask session, or source ACL is faked
into an authorization decision.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from threading import Barrier, RLock
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
# Standalone functional tests must locate the real application modules first.
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from conversation_memory_storage import (  # noqa: E402
    AzureMemoryBlobTransport,
    BlobRecord,
    MemoryAuthorizationError,
    MemoryCleanupError,
    MemoryConflictError,
    MemoryIntegrityError,
    MemoryLimitError,
    MemoryNotFoundError,
    MemoryStateError,
    MemoryUnavailableError,
)
from functions_conversation_memory import (  # noqa: E402
    ConversationMemoryStore,
    EvidenceChunk,
    EvidenceLocation,
    EvidenceSource,
    MAX_CHUNK_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_RANGE_BYTES,
    MemoryContext,
    PublicationGrant,
    create_conversation_memory_store,
    is_conversation_memory_blob_path,
)
from functions_m365_analysis_jobs import (  # noqa: E402
    AnalysisBatchResult,
    ConversationAnalysisJobRunner,
)


class InMemoryBlobTransport:
    def __init__(self):
        self.blobs = {}
        self.version = 0
        self.lock = RLock()
        self.calls = []
        self.before_put = None
        self.before_delete = None

    def read(self, container, name, *, max_bytes):
        with self.lock:
            self.calls.append(("read", container, name, max_bytes))
            record = self.blobs.get((container, name))
            if record is None:
                raise MemoryNotFoundError("Missing fake blob.")
            if len(record.data) > max_bytes:
                raise MemoryLimitError("Fake read exceeds its bound.")
            return record

    def put(self, container, name, data, *, etag=None):
        if self.before_put is not None:
            self.before_put(container, name, data, etag)
        with self.lock:
            self.calls.append(("put", container, name, len(data)))
            existing = self.blobs.get((container, name))
            if (etag is None and existing is not None) or (
                etag is not None and (existing is None or existing.etag != etag)
            ):
                raise MemoryConflictError("Fake ETag conflict.")
            self.version += 1
            new_etag = f'"{self.version}"'
            self.blobs[(container, name)] = BlobRecord(bytes(data), new_etag)
            return new_etag

    def delete(self, container, name, *, etag):
        if self.before_delete is not None:
            self.before_delete(container, name, etag)
        with self.lock:
            self.calls.append(("delete", container, name, etag))
            record = self.blobs.get((container, name))
            if record is None:
                raise MemoryNotFoundError("Missing fake blob.")
            if record.etag != etag:
                raise MemoryConflictError("Fake delete ETag conflict.")
            del self.blobs[(container, name)]


class MemoryHarness:
    def __init__(self):
        self.transport = InMemoryBlobTransport()
        self.now = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
        self.context = MemoryContext("tenant", "owner", "conversation", "owner")
        self.reader = replace(self.context, principal_id="reader")
        self.members = {
            ("tenant", "conversation", "owner", "personal-chat"): {"owner", "reader"},
            ("tenant", "target", "reader", "group-chat"): {"reader", "other"},
        }
        self.logs = []
        self.authorizations = []
        self.grant_context = object()
        self.grant_override = {}
        self.store = self.new_store()

    def authorize(self, ctx, operation):
        self.authorizations.append((ctx, operation))
        key = (ctx.tenant_id, ctx.conversation_id, ctx.storage_owner, ctx.container)
        allowed = ctx.principal_id in self.members.get(key, set())
        if operation in {"archive", "restore", "archive_export", "delete", "fork_write"}:
            allowed = allowed and ctx.principal_id == ctx.storage_owner
        return allowed

    def publication(self, ctx, manifest, grant_context):
        if grant_context is not self.grant_context:
            raise MemoryAuthorizationError("Unknown persisted approval context.")
        grant = PublicationGrant(
            ctx.tenant_id, ctx.principal_id, ctx.conversation_id, manifest["run_id"],
            manifest["request_id"], manifest["content_revision"], ("approval-share",),
            "publication-grant", "audience-revision-1", self.now.isoformat(),
        )
        return replace(grant, **self.grant_override)

    def new_store(self):
        return ConversationMemoryStore(
            transport=self.transport, authorize_access=self.authorize,
            authorize_publish=self.publication, log_event=lambda *args, **kwargs: self.logs.append(args),
            clock=lambda: self.now,
        )

    def run(self, count=3, *, text_prefix="Original evidence"):
        manifest = self.store.create_run(self.context, request_id="request-1", approval_ids=("capture-approval",))
        chunks = (
            EvidenceChunk(
                f"{text_prefix} {index}",
                EvidenceLocation(pages=(index + 1,), sheet="Ledger", row_start=index + 1, row_end=index + 1),
            )
            for index in range(count)
        )
        source = self.store.add_evidence(
            self.context, manifest["run_id"],
            source=EvidenceSource("m365_sharepoint", "drive:item", '"etag-1"', "Ledger", coverage_complete=True),
            chunks=chunks,
        )
        return manifest["run_id"], source

    def publish(self, run_id):
        self.store.complete_run(self.context, run_id)
        return self.store.publish(self.context, run_id, grant_context=self.grant_context)


def test_real_evidence_survives_notes_restarts_and_range_reads():
    harness = MemoryHarness()
    run_id, source = harness.run(75, text_prefix="Exact source \u03b1")
    checkpoint = harness.store.append_checkpoint(
        harness.context, run_id, checkpoint={"next_source_chunk": 12},
        output={"sum": 12}, note="A deliberately lossy analysis note.", completed_units=12, total_units=75,
    )
    restarted = harness.new_store()
    evidence = restarted.read_evidence_range(harness.context, run_id, source["evidence_id"], start=40, count=3)
    resumed = restarted.read_checkpoint(harness.context, run_id)
    manifest = restarted.read_manifest(harness.context, run_id)

    assert [chunk["text"] for chunk in evidence["chunks"]] == [f"Exact source \u03b1 {i}" for i in range(40, 43)]
    assert evidence["chunks"][0]["locator"]["pages"] == [41]
    assert evidence["chunks"][0]["locator"]["row_start"] == 41
    assert evidence["next_start"] == 43
    assert evidence["trust"] == "untrusted_source_data"
    assert source["source"]["version"] == '"etag-1"'
    assert source["capture"]["principal_id"] == "owner"
    assert source["capture"]["approval_ids"] == ["capture-approval"]
    assert source["content_sha256"] == evidence["source"]["content_sha256"]
    assert resumed == checkpoint
    assert manifest["captured_chunk_count"] == 75
    assert manifest["completed_units"] == 12
    assert manifest["pending_operation"] is None
    assert "claim" not in manifest
    assert not any("Exact source" in str(event) for event in harness.logs)


def test_source_catalog_and_manifest_remain_bounded_and_paged():
    harness = MemoryHarness()
    manifest = harness.store.create_run(harness.context)
    run_id = manifest["run_id"]
    for index in range(70):
        harness.store.add_evidence(
            harness.context, run_id, source=EvidenceSource("test", f"item-{index}", "v1"),
            chunks=(EvidenceChunk(f"Source {index}"),),
        )
    first = harness.store.list_sources(harness.context, run_id, count=32)
    last = harness.store.list_sources(harness.context, run_id, start=64, count=32)
    root = harness.store.read_manifest(harness.context, run_id)

    assert len(first["sources"]) == 32
    assert first["next_start"] == 32
    assert len(last["sources"]) == 6
    assert last["next_start"] is None
    assert root["evidence_count"] == 70
    assert len(json.dumps(root).encode("utf-8")) < 4096
    assert all(len(record.data) <= MAX_MANIFEST_BYTES for record in harness.transport.blobs.values())
    assert all(call[3] <= MAX_MANIFEST_BYTES for call in harness.transport.calls if call[0] in {"read", "put"})


def test_range_response_byte_budget_reports_continuation_without_losing_chunks():
    harness = MemoryHarness()
    manifest = harness.store.create_run(harness.context)
    consumed = []

    def chunks():
        for index in range(20):
            consumed.append(index)
            yield EvidenceChunk("x" * (MAX_CHUNK_BYTES - 64) + str(index))

    source = harness.store.add_evidence(
        harness.context, manifest["run_id"], source=EvidenceSource("test", "large", "v1"), chunks=chunks(),
    )
    start, restored = 0, []
    while True:
        page = harness.store.read_evidence_range(
            harness.context, manifest["run_id"], source["evidence_id"], start=start, count=32,
        )
        restored.extend(chunk["text"] for chunk in page["chunks"])
        assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= MAX_RANGE_BYTES
        assert sum(len(json.dumps(chunk).encode("utf-8")) for chunk in page["chunks"]) < MAX_RANGE_BYTES
        if page["next_start"] is None:
            break
        assert page["next_start"] > start
        start = page["next_start"]

    assert consumed == list(range(20))
    assert restored == ["x" * (MAX_CHUNK_BYTES - 64) + str(index) for index in range(20)]
    assert len(harness.transport.blobs) == 23


def test_staging_is_actor_private_and_publication_requires_a_server_grant():
    harness = MemoryHarness()
    run_id, source = harness.run()
    for action in (
        lambda: harness.store.read_manifest(harness.reader, run_id),
        lambda: harness.store.read_evidence_range(harness.reader, run_id, source["evidence_id"]),
        lambda: harness.store.publish(harness.reader, run_id, grant_context=harness.grant_context),
    ):
        with pytest.raises(MemoryAuthorizationError):
            action()
    hidden = harness.store.list_runs(harness.reader)
    assert hidden["runs"] == []
    with pytest.raises(MemoryStateError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    harness.store.complete_run(harness.context, run_id)
    for forged in (True, False, None, {"approved": True}):
        with pytest.raises(MemoryAuthorizationError):
            harness.store.publish(harness.context, run_id, grant_context=forged)
    published = harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    page = harness.store.read_evidence_range(harness.reader, run_id, source["evidence_id"])

    assert published["publication"]["includes_all_retained_evidence"] is True
    assert published["publication"]["approval_ids"] == ["approval-share"]
    assert len(page["chunks"]) == 3
    with pytest.raises(MemoryStateError):
        harness.store.add_evidence(
            harness.context, run_id, source=EvidenceSource("test", "later", "v2"),
            chunks=(EvidenceChunk("Not part of the approved snapshot"),),
        )
    harness.members[("tenant", "conversation", "owner", "personal-chat")].remove("reader")
    before = len(harness.transport.calls)
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_evidence_range(harness.reader, run_id, source["evidence_id"])
    assert len(harness.transport.calls) == before


@pytest.mark.parametrize("override", [
    {"tenant_id": "other-tenant"}, {"principal_id": "reader"}, {"conversation_id": "other-conversation"},
    {"run_id": "0" * 32}, {"request_id": "another-request"}, {"content_revision": 0},
    {"content_revision": True}, {"approval_ids": ()},
    {"expires_at": "2026-09-16T00:00:00+00:00"}, {"approved_at": "2027-01-01T00:00:00+00:00"},
])
def test_publication_grant_is_bound_to_exact_snapshot_and_current_validity(override):
    harness = MemoryHarness()
    run_id, _ = harness.run()
    harness.store.complete_run(harness.context, run_id)
    harness.grant_override = override
    with pytest.raises(MemoryAuthorizationError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    manifest = harness.store.read_manifest(harness.context, run_id)
    assert manifest["publication"] is None


def test_publication_cas_does_not_allow_a_stale_approval_to_win():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    harness.store.complete_run(harness.context, run_id)
    publish_authorizer = harness.store.authorize_publish

    def change_generation(ctx, manifest, grant_context):
        grant = publish_authorizer(ctx, manifest, grant_context)
        harness.store.archive_conversation_memory(ctx)
        return grant

    harness.store.authorize_publish = change_generation
    with pytest.raises(MemoryConflictError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    manifest = harness.store.read_manifest(harness.context, run_id)
    assert manifest["publication"] is None


@pytest.mark.parametrize("changes", [
    {"tenant_id": "other"}, {"conversation_id": "other"}, {"storage_owner": "other"},
    {"container": "group-chat"}, {"principal_id": "outsider"},
])
def test_exact_backing_conversation_authorization_precedes_blob_access(changes):
    harness = MemoryHarness()
    run_id, source = harness.run()
    forged = replace(harness.context, **changes)
    before = len(harness.transport.calls)
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_evidence_range(forged, run_id, source["evidence_id"])
    assert len(harness.transport.calls) == before


def test_identifiers_and_metadata_do_not_accept_arbitrary_paths_or_secrets():
    harness = MemoryHarness()
    for field in ("tenant_id", "principal_id", "conversation_id", "storage_owner"):
        with pytest.raises(ValueError):
            replace(harness.context, **{field: "../other"})
    run_id, _ = harness.run()
    for bad_run in ("../manifest", "a/b", "https://storage/blob", "x" * 32):
        with pytest.raises(ValueError):
            harness.store.read_manifest(harness.context, bad_run)
    with pytest.raises(ValueError):
        harness.store.read_evidence_range(harness.context, run_id, "../evidence")
    invalid_urls = (
        "http://host/file", "https://u:p@host/file", "https://host/file?sig=secret",
        "javascript:code",  # xss-check: ignore - Rejection-only fixture; this value is never rendered.
    )
    for url in invalid_urls:
        with pytest.raises(ValueError):
            EvidenceSource("test", "item", "v1", canonical_url=url)
    with pytest.raises(ValueError):
        harness.store.append_checkpoint(harness.context, run_id, checkpoint={"nested": {"access_token": "secret"}})
    with pytest.raises(ValueError):
        harness.store.append_checkpoint(
            harness.context, run_id, checkpoint={}, output={"@microsoft.graph.downloadUrl": "secret"},
        )
    with pytest.raises(MemoryLimitError):
        EvidenceChunk("x" * (MAX_CHUNK_BYTES + 1))
    with pytest.raises(MemoryLimitError):
        harness.store.append_checkpoint(harness.context, run_id, checkpoint={}, note="x" * 8193)
    with pytest.raises(ValueError):
        EvidenceLocation(row_start=2, row_end=1)
    with pytest.raises(ValueError):
        EvidenceLocation(pages=[1])
    with pytest.raises(ValueError):
        harness.store.read_evidence_range(harness.context, run_id, "s0000000000000000", count=33)
    assert is_conversation_memory_blob_path("owner/chat/_conversation_memory/v1/file")
    assert is_conversation_memory_blob_path("owner\\chat\\_conversation_memory\\v1\\file")
    assert is_conversation_memory_blob_path("owner%2fchat%2f%5fconversation_memory%2fv1%2ffile")
    assert is_conversation_memory_blob_path("owner%252fchat%252f%255fconversation_memory%252fv1%252ffile")
    assert is_conversation_memory_blob_path("owner/chat/_CONVERSATION_MEMORY/v1/file")
    assert not is_conversation_memory_blob_path("owner/chat/ordinary-document.pdf")
    assert not is_conversation_memory_blob_path("owner/chat/an%20ordinary-document.pdf")


def test_two_workers_cannot_claim_the_same_generation():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    barrier = Barrier(2)

    def before_put(container, name, data, etag):
        if name.endswith(f"{run_id}/manifest.json") and json.loads(data).get("claim") is not None:
            barrier.wait(timeout=5)

    harness.transport.before_put = before_put

    def claim_worker():
        try:
            return harness.new_store().claim(harness.context, run_id)
        except MemoryConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(claim_worker) for _ in range(2)]
        claims = [future.result(timeout=10) for future in futures]
    harness.transport.before_put = None
    winners = [claim for claim in claims if claim is not None]

    assert len(winners) == 1
    manifest = harness.store.read_manifest(harness.context, run_id)
    assert winners[0].generation == manifest["claim_generation"]
    with pytest.raises(MemoryConflictError):
        harness.store.claim(harness.context, run_id)


def test_expired_generations_and_cancellation_fence_old_workers():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    old = harness.store.claim(harness.context, run_id, lease_seconds=2)
    harness.now += timedelta(seconds=3)
    fresh = harness.new_store().claim(harness.context, run_id)
    for action in (
        lambda: harness.store.renew_claim(harness.context, old),
        lambda: harness.store.append_checkpoint(harness.context, run_id, checkpoint={}, claim=old),
    ):
        with pytest.raises(MemoryConflictError):
            action()
    checkpoint = harness.store.append_checkpoint(
        harness.context, run_id, checkpoint={"next": 1}, completed_units=1, claim=fresh,
    )
    canceled = harness.store.cancel(harness.context, run_id)
    with pytest.raises(MemoryConflictError):
        harness.store.append_checkpoint(harness.context, run_id, checkpoint={}, claim=fresh)
    with pytest.raises(MemoryStateError):
        harness.store.resume(harness.context, run_id)
    retained = harness.store.read_checkpoint(harness.context, run_id)
    assert canceled["status"] == "canceled"
    assert retained == checkpoint


def test_cancellation_after_completion_still_blocks_unpublished_release():
    harness = MemoryHarness()
    run_id, source = harness.run()
    harness.store.complete_run(harness.context, run_id)
    canceled = harness.store.cancel(harness.context, run_id)
    with pytest.raises(MemoryStateError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    evidence = harness.store.read_evidence_range(harness.context, run_id, source["evidence_id"])
    assert canceled["status"] == "canceled"
    assert len(evidence["chunks"]) == 3


def test_capture_commit_crash_is_recovered_without_reextracting_evidence():
    harness = MemoryHarness()
    run = harness.store.create_run(harness.context)
    run_id = run["run_id"]

    def fail_source_commit(container, name, data, etag):
        if name.endswith(f"{run_id}/manifest.json") and json.loads(data).get("evidence_count") == 1:
            harness.transport.before_put = None
            raise MemoryUnavailableError("Simulated commit crash.")

    harness.transport.before_put = fail_source_commit
    with pytest.raises(MemoryUnavailableError):
        harness.store.add_evidence(
            harness.context, run_id, source=EvidenceSource("test", "immutable", "v7"),
            chunks=(EvidenceChunk("Exact original bytes"),),
        )
    failed = harness.store.read_manifest(harness.context, run_id)
    with pytest.raises(MemoryNotFoundError):
        harness.store.read_evidence_range(harness.context, run_id, "s0000000000000000")
    restarted = harness.new_store()
    restarted.resume(harness.context, run_id)
    restarted.recover_pending(harness.context, run_id)
    page = restarted.read_evidence_range(harness.context, run_id, "s0000000000000000")
    manifest = restarted.read_manifest(harness.context, run_id)

    assert failed["pending_operation"] == "source"
    assert page["chunks"][0]["text"] == "Exact original bytes"
    assert manifest["evidence_count"] == 1
    assert manifest["pending_operation"] is None


def test_incomplete_capture_requires_explicit_discard_and_remains_in_inventory():
    harness = MemoryHarness()
    run = harness.store.create_run(harness.context)
    run_id = run["run_id"]

    def broken_source():
        yield EvidenceChunk("Partial extraction")
        raise ValueError("Extraction failed explicitly.")

    with pytest.raises(ValueError):
        harness.store.add_evidence(
            harness.context, run_id, source=EvidenceSource("test", "broken", "v1"), chunks=broken_source(),
        )
    harness.store.resume(harness.context, run_id)
    with pytest.raises(MemoryStateError):
        harness.store.recover_pending(harness.context, run_id)
    harness.store.resume(harness.context, run_id)
    harness.store.recover_pending(harness.context, run_id, discard=True)
    source = harness.store.add_evidence(
        harness.context, run_id, source=EvidenceSource("test", "retry", "v1"), chunks=(EvidenceChunk("Full capture"),),
    )
    catalog = harness.store.list_sources(harness.context, run_id)
    assert source["evidence_id"] == "s0000000000000001"
    assert len(catalog["sources"]) == 1
    assert catalog["sources"][0]["evidence_id"] == source["evidence_id"]
    assert not any(b"Partial extraction" in record.data for record in harness.transport.blobs.values())


def test_checkpoint_commit_crash_preserves_output_note_and_cursor():
    harness = MemoryHarness()
    run_id, _ = harness.run()

    def fail_checkpoint_commit(container, name, data, etag):
        if name.endswith(f"{run_id}/manifest.json") and json.loads(data).get("checkpoint_count") == 1:
            harness.transport.before_put = None
            raise MemoryUnavailableError("Simulated checkpoint commit crash.")

    harness.transport.before_put = fail_checkpoint_commit
    with pytest.raises(MemoryUnavailableError):
        harness.store.append_checkpoint(
            harness.context, run_id, checkpoint={"next_chunk": 2}, output={"exact_total": 102},
            note="Retain this intermediate result.", completed_units=2, total_units=3,
        )
    before = harness.store.read_checkpoint(harness.context, run_id)
    harness.store.resume(harness.context, run_id)
    harness.store.recover_pending(harness.context, run_id)
    checkpoint = harness.store.read_checkpoint(harness.context, run_id)

    assert before is None
    assert checkpoint["output"] == {"exact_total": 102}
    assert checkpoint["checkpoint"] == {"next_chunk": 2}
    assert checkpoint["note"] == "Retain this intermediate result."
    assert checkpoint["completed_units"] == 2


def test_tampered_evidence_is_not_returned_as_captured_content():
    harness = MemoryHarness()
    run_id, source = harness.run()
    key = next(key for key in harness.transport.blobs if "/objects/" in key[1])
    record = harness.transport.blobs[key]
    payload = json.loads(record.data)
    payload["text"] = "Replaced after capture"
    harness.transport.put(key[0], key[1], json.dumps(payload).encode("utf-8"), etag=record.etag)
    with pytest.raises(MemoryIntegrityError):
        harness.store.read_evidence_range(harness.context, run_id, source["evidence_id"])


def test_publication_validates_all_retained_evidence_before_issuing_approval():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    harness.store.complete_run(harness.context, run_id)
    key = next(key for key in harness.transport.blobs if "/objects/" in key[1])
    harness.transport.delete(*key, etag=harness.transport.blobs[key].etag)
    with pytest.raises(MemoryNotFoundError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    manifest = harness.store.read_manifest(harness.context, run_id)
    assert manifest["publication"] is None


def test_stored_publication_must_match_the_original_run_actor():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    harness.publish(run_id)
    key = next(key for key in harness.transport.blobs if key[1].endswith(f"{run_id}/manifest.json"))
    record = harness.transport.blobs[key]
    payload = json.loads(record.data)
    payload["publication"]["principal_id"] = "reader"
    harness.transport.put(*key, json.dumps(payload).encode("utf-8"), etag=record.etag)
    with pytest.raises(MemoryIntegrityError):
        harness.store.read_manifest(harness.reader, run_id)


def test_capture_stream_renews_a_live_claim_during_long_persistence():
    harness = MemoryHarness()
    run_id = harness.store.create_run(harness.context)["run_id"]

    def slow_chunks():
        for index in range(6):
            harness.now += timedelta(seconds=55)
            yield EvidenceChunk(str(index))

    source = harness.store.add_evidence(
        harness.context, run_id, source=EvidenceSource("test", "slow-source", "v1"), chunks=slow_chunks(),
    )
    manifest = harness.store.read_manifest(harness.context, run_id)
    assert source["chunk_count"] == 6
    assert manifest["status"] == "queued"
    assert manifest["pending_operation"] is None


def test_orphan_run_creation_is_reserved_for_exact_cleanup():
    harness = MemoryHarness()
    delayed = []

    def interrupt_run(container, name, data, etag):
        if "/runs/" in name and name.endswith("/manifest.json"):
            harness.transport.before_put = None
            delayed.append((container, name, data))
            raise MemoryUnavailableError("Run creation was interrupted.")

    harness.transport.before_put = interrupt_run
    with pytest.raises(MemoryUnavailableError):
        harness.store.create_run(harness.context)
    runs = harness.store.list_runs(harness.context)
    deletion = harness.store.delete_conversation_memory(harness.context)
    assert runs["runs"] == []
    assert deletion["complete"] is True
    with pytest.raises(MemoryConflictError):
        harness.transport.put(*delayed[0])


def test_exact_deletion_covers_reserved_orphans_and_blocks_late_uploads():
    harness = MemoryHarness()
    run_id, source = harness.run()
    unrelated = ("personal-chat", "owner/conversation/ordinary.txt")
    harness.transport.put(*unrelated, b"Do not delete this unrelated attachment.")
    expected = set(harness.transport.blobs) - {unrelated}
    manifest = harness.store.create_run(harness.context)
    orphan_run_id = manifest["run_id"]
    delayed = []

    def interrupt_upload(container, name, data, etag):
        if f"{orphan_run_id}/objects/" in name:
            harness.transport.before_put = None
            delayed.append((container, name, data))
            raise MemoryUnavailableError("Worker crashed after reserving a blob slot.")

    harness.transport.before_put = interrupt_upload
    with pytest.raises(MemoryUnavailableError):
        harness.store.add_evidence(
            harness.context, orphan_run_id, source=EvidenceSource("test", "orphan", "v1"),
            chunks=(EvidenceChunk("Must never reappear"),),
        )
    result = harness.store.delete_conversation_memory(harness.context)
    assert result["complete"] is True
    assert result["empty_fences_retained"] is True
    assert harness.transport.blobs[unrelated].data == b"Do not delete this unrelated attachment."
    assert all(not record.data for key, record in harness.transport.blobs.items() if key != unrelated)
    assert expected <= set(harness.transport.blobs)
    with pytest.raises(MemoryConflictError):
        harness.transport.put(*delayed[0])
    repeated = harness.store.delete_conversation_memory(harness.context)
    assert repeated["complete"] is True
    with pytest.raises(MemoryStateError):
        harness.store.create_run(harness.context)
    with pytest.raises(MemoryStateError):
        harness.store.read_evidence_range(harness.context, run_id, source["evidence_id"])


def test_partial_deletion_is_explicit_and_retriable_with_the_original_inventory():
    harness = MemoryHarness()
    harness.run()

    def unavailable(container, name, etag):
        if "/objects/0000000000000001.json" in name:
            harness.transport.before_delete = None
            raise MemoryUnavailableError("Storage deletion failed.")

    harness.transport.before_delete = unavailable
    with pytest.raises(MemoryCleanupError):
        harness.store.delete_conversation_memory(harness.context)
    assert any(record.data for record in harness.transport.blobs.values())
    result = harness.store.delete_conversation_memory(harness.context)
    assert result["complete"] is True
    assert all(not record.data for record in harness.transport.blobs.values())
    assert any("deletion incomplete" in event[0] for event in harness.logs)


def test_fork_owns_copies_preserves_capture_audit_and_starts_private():
    harness = MemoryHarness()
    run_id, source = harness.run()
    harness.store.append_checkpoint(
        harness.context, run_id, checkpoint={"cursor": 3}, output={"total": 42},
        note="Saved batch analysis", completed_units=3,
    )
    target_ctx = MemoryContext("tenant", "reader", "target", "reader", "group-chat")
    with pytest.raises(MemoryAuthorizationError):
        harness.store.fork_published_run(harness.context, run_id, target_ctx)
    harness.publish(run_id)
    fork = harness.store.fork_published_run(harness.reader, run_id, target_ctx)
    fork_source = harness.store.list_sources(target_ctx, fork["run_id"])["sources"][0]
    fork_checkpoint = harness.store.read_checkpoint(target_ctx, fork["run_id"])
    target_participant = replace(target_ctx, principal_id="other")
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_evidence_range(target_participant, fork["run_id"], fork_source["evidence_id"])
    harness.store.delete_conversation_memory(harness.context)
    page = harness.store.read_evidence_range(target_ctx, fork["run_id"], fork_source["evidence_id"])

    assert fork["principal_id"] == "reader"
    assert fork["publication"] is None
    assert fork["copied_from"]["run_id"] == run_id
    assert fork_source["capture"] == source["capture"]
    assert fork_source["content_sha256"] == source["content_sha256"]
    assert len(page["chunks"]) == 3
    assert fork_checkpoint["output"] == {"total": 42}
    assert fork_checkpoint["note"] == "Saved batch analysis"
    assert not any(
        b"owner/conversation/_conversation_memory" in record.data
        for (container, _), record in harness.transport.blobs.items() if container == "group-chat"
    )


def test_archive_restore_keep_working_evidence_and_gate_private_backup_export():
    harness = MemoryHarness()
    run_id, source = harness.run()
    checkpoint = harness.store.append_checkpoint(
        harness.context, run_id, checkpoint={"cursor": 1}, note="Archive this note.", completed_units=1,
    )
    claim = harness.store.claim(harness.context, run_id)
    with pytest.raises(MemoryStateError):
        list(harness.store.iter_retained_blobs(harness.context))
    archived = harness.store.archive_conversation_memory(harness.context)
    backup = list(harness.store.iter_retained_blobs(harness.context))
    with pytest.raises(MemoryAuthorizationError):
        list(harness.store.iter_retained_blobs(harness.reader))
    with pytest.raises(MemoryStateError):
        harness.store.renew_claim(harness.context, claim)
    restored = harness.store.restore_conversation_memory(harness.context)
    harness.store.resume(harness.context, run_id)
    page = harness.store.read_evidence_range(harness.context, run_id, source["evidence_id"])
    restored_checkpoint = harness.store.read_checkpoint(harness.context, run_id)

    assert archived["state"] == "archived"
    assert restored["state"] == "active"
    assert len(backup) == len(harness.transport.blobs)
    assert restored_checkpoint == checkpoint
    assert len(page["chunks"]) == 3
    assert any(b"Archive this note" in blob.data for blob in backup)


def test_lifecycle_hooks_are_safe_for_conversations_without_memory():
    harness = MemoryHarness()
    archived = harness.store.archive_conversation_memory(harness.context)
    restored = harness.store.restore_conversation_memory(harness.context)
    backup = list(harness.store.iter_retained_blobs(harness.context))
    assert archived == {"state": "absent", "run_count": 0}
    assert restored == {"state": "absent", "run_count": 0}
    assert backup == []
    assert not harness.transport.blobs


def test_request_key_returns_one_manifest_across_plugins_and_restarts():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    onedrive = harness.store.get_or_create_manifest(ctx, kind="m365_request", key=ctx.request_id)
    claim = harness.store.claim(ctx, onedrive["run_id"])
    harness.store.append_checkpoint(
        ctx, onedrive["run_id"], claim=claim,
        checkpoint={"downloads": 1, "file_context_tokens": 1200, "last_source": "onedrive"},
    )
    harness.store.release_claim(ctx, claim, status="queued")
    restarted = harness.new_store()
    sharepoint = restarted.get_or_create_manifest(ctx, kind="m365_request", key=ctx.request_id)
    second_claim = restarted.claim(ctx, sharepoint["run_id"])
    previous = restarted.read_checkpoint(ctx, sharepoint["run_id"])
    restarted.append_checkpoint(
        ctx, sharepoint["run_id"], claim=second_claim,
        checkpoint={
            "downloads": previous["checkpoint"]["downloads"] + 1,
            "file_context_tokens": previous["checkpoint"]["file_context_tokens"] + 2300,
            "last_source": "sharepoint",
        },
    )
    restarted.release_claim(ctx, second_claim, status="queued")
    final = harness.store.read_checkpoint(ctx, onedrive["run_id"])
    runs = harness.store.list_runs(ctx)

    assert onedrive["run_id"] == sharepoint["run_id"]
    assert sharepoint["request_id"] == ctx.request_id
    assert len(runs["runs"]) == 1
    assert final["checkpoint"] == {"downloads": 2, "file_context_tokens": 3500, "last_source": "sharepoint"}


def test_keyed_lookup_is_constant_io_and_has_no_growing_manifest_array():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    original = harness.store.get_or_create_manifest(ctx)
    for index in range(45):
        harness.store.get_or_create_manifest(ctx, kind="m365_file", key=f"file-{index}")
    before = len(harness.transport.calls)
    again = harness.store.get_or_create_manifest(ctx)
    calls = harness.transport.calls[before:]
    root_records = [
        record for (_, name), record in harness.transport.blobs.items()
        if name.endswith("/manifest.json") and "/runs/" not in name
    ]

    assert again["run_id"] == original["run_id"]
    assert len(calls) <= 5
    assert all(call[0] == "read" for call in calls)
    assert len(root_records) == 1
    assert len(root_records[0].data) < 4096
    assert "pending_run" not in json.loads(root_records[0].data)


def test_request_keys_are_scoped_by_actor_request_and_kind():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="request-a")
    first = harness.store.get_or_create_manifest(ctx, key="same-key")
    second_actor = harness.store.get_or_create_manifest(replace(ctx, principal_id="reader"), key="same-key")
    next_request = harness.store.get_or_create_manifest(replace(ctx, request_id="request-b"), key="same-key")
    file_run = harness.store.get_or_create_manifest(ctx, kind="m365_file", key="same-key")
    target_ctx = MemoryContext("tenant", "reader", "target", "reader", "group-chat", request_id="request-a")
    target = harness.store.get_or_create_manifest(target_ctx, key="same-key")

    assert len({item["run_id"] for item in (first, second_actor, next_request, file_run, target)}) == 5
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_manifest(replace(ctx, principal_id="reader"), first["run_id"])
    with pytest.raises(MemoryAuthorizationError):
        harness.store.get_or_create_manifest(harness.context)
    with pytest.raises(MemoryAuthorizationError):
        harness.store.create_run(ctx, request_id="different-request")
    with pytest.raises(ValueError):
        harness.store.get_or_create_manifest(ctx, key="../untrusted-path")


def test_two_workers_create_the_same_key_only_once():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    harness.store.create_run(ctx)
    barrier = Barrier(2)
    gated = []
    gate_lock = RLock()

    def before_put(container, name, data, etag):
        if "/runs/" not in name and json.loads(data).get("pending_run") is not None:
            with gate_lock:
                wait = len(gated) < 2
                if wait:
                    gated.append(name)
            if wait:
                barrier.wait(timeout=5)

    harness.transport.before_put = before_put
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(harness.new_store().get_or_create_manifest, ctx, kind="m365_request")
            for _ in range(2)
        ]
        manifests = [future.result(timeout=10) for future in futures]
    harness.transport.before_put = None
    runs = harness.store.list_runs(ctx)

    assert manifests[0]["run_id"] == manifests[1]["run_id"]
    assert len(runs["runs"]) == 2
    assert len([name for _, name in harness.transport.blobs if "/keys/" in name]) == 1


@pytest.mark.parametrize("phase", ["run", "key", "clear"])
def test_keyed_creation_recovers_each_interrupted_phase_without_resetting_request(phase):
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    reserved = []

    def interrupt(container, name, data, etag):
        payload = json.loads(data)
        matches = (
            phase == "run" and payload.get("kind") == "memory_run"
            or phase == "key" and payload.get("kind") == "memory_key"
            or phase == "clear" and payload.get("kind") == "conversation_memory"
            and payload.get("run_count") == 1 and payload.get("pending_run") is None
        )
        if payload.get("pending_run") is not None:
            reserved.append(payload["pending_run"]["run_id"])
        if matches:
            harness.transport.before_put = None
            raise MemoryUnavailableError("Keyed creation was interrupted.")

    harness.transport.before_put = interrupt
    with pytest.raises(MemoryUnavailableError):
        harness.store.get_or_create_manifest(ctx)
    recovered = harness.new_store().get_or_create_manifest(ctx)
    repeated = harness.store.get_or_create_manifest(ctx)
    runs = harness.store.list_runs(ctx)

    assert recovered["run_id"] == reserved[0]
    assert recovered["run_id"] == repeated["run_id"]
    assert len(runs["runs"]) == 1


def test_another_actor_can_reconcile_empty_reservation_without_reading_private_data():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    reserved = []

    def interrupt(container, name, data, etag):
        payload = json.loads(data)
        if payload.get("kind") == "memory_run":
            reserved.append(payload["run_id"])
            harness.transport.before_put = None
            raise MemoryUnavailableError("Creator restarted.")

    harness.transport.before_put = interrupt
    with pytest.raises(MemoryUnavailableError):
        harness.store.get_or_create_manifest(ctx)
    reader_ctx = replace(ctx, principal_id="reader")
    reader_run = harness.store.get_or_create_manifest(reader_ctx)
    original = harness.store.get_or_create_manifest(ctx)
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_manifest(reader_ctx, original["run_id"])

    assert original["run_id"] == reserved[0]
    assert reader_run["run_id"] != original["run_id"]
    assert reader_run["principal_id"] == "reader"


def test_request_budget_claim_serializes_independent_plugin_updates():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    first = harness.store.get_or_create_manifest(ctx)
    second = harness.new_store().get_or_create_manifest(ctx)
    first_claim = harness.store.claim(ctx, first["run_id"])
    with pytest.raises(MemoryConflictError):
        harness.store.claim(ctx, second["run_id"])
    initial = harness.store.read_checkpoint(ctx, first["run_id"])
    harness.store.append_checkpoint(
        ctx, first["run_id"], claim=first_claim, checkpoint={"downloads": 1, "file_context_tokens": 1000},
    )
    harness.store.release_claim(ctx, first_claim, status="queued")
    next_claim = harness.store.claim(ctx, second["run_id"])
    latest = harness.store.read_checkpoint(ctx, second["run_id"])
    harness.store.release_claim(ctx, next_claim, status="queued")

    assert initial is None
    assert latest["checkpoint"] == {"downloads": 1, "file_context_tokens": 1000}


def test_keyed_creation_survives_an_acknowledgment_lost_after_commit(monkeypatch):
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    original_put = harness.transport.put
    failed = []

    def lost_acknowledgment(container, name, data, *, etag=None):
        written_etag = original_put(container, name, data, etag=etag)
        payload = json.loads(data)
        if not failed and payload.get("kind") == "conversation_memory" and payload.get("pending_run"):
            failed.append(payload["pending_run"]["run_id"])
            raise MemoryUnavailableError("Storage committed but its acknowledgment was lost.")
        return written_etag

    monkeypatch.setattr(harness.transport, "put", lost_acknowledgment)
    with pytest.raises(MemoryUnavailableError):
        harness.store.get_or_create_manifest(ctx)
    recovered = harness.store.get_or_create_manifest(ctx)
    runs = harness.store.list_runs(ctx)

    assert recovered["run_id"] == failed[0]
    assert len(runs["runs"]) == 1


def test_keyed_budget_recovers_the_last_reservation_before_another_download():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    request = harness.store.get_or_create_manifest(ctx)
    run_id = request["run_id"]

    def fail_budget_commit(container, name, data, etag):
        if name.endswith(f"{run_id}/manifest.json") and json.loads(data).get("checkpoint_count") == 1:
            harness.transport.before_put = None
            raise MemoryUnavailableError("Budget reservation commit was interrupted.")

    harness.transport.before_put = fail_budget_commit
    with pytest.raises(MemoryUnavailableError):
        harness.store.append_checkpoint(ctx, run_id, checkpoint={"downloads": 1, "file_context_tokens": 2000})
    request = harness.new_store().get_or_create_manifest(ctx)
    harness.store.resume(ctx, request["run_id"])
    claim = harness.store.claim(ctx, request["run_id"])
    harness.store.recover_pending(ctx, request["run_id"], claim=claim)
    previous = harness.store.read_checkpoint(ctx, request["run_id"])
    harness.store.release_claim(ctx, claim, status="queued")

    assert request["run_id"] == run_id
    assert previous["checkpoint"] == {"downloads": 1, "file_context_tokens": 2000}


def test_file_key_reuses_completed_capture_without_losing_request_identity():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    staged = harness.store.get_or_create_manifest(ctx, kind="m365_file", key="server-file-hash")
    source = harness.store.add_evidence(
        ctx, staged["run_id"], source=EvidenceSource("m365_onedrive", "drive:item", "etag-1"),
        chunks=(EvidenceChunk("Captured once"),),
    )
    harness.store.complete_run(ctx, staged["run_id"])
    existing = harness.new_store().get_or_create_manifest(ctx, kind="m365_file", key="server-file-hash")
    page = harness.store.read_evidence_range(ctx, existing["run_id"], source["evidence_id"])

    assert existing["run_id"] == staged["run_id"]
    assert existing["evidence_count"] == 1
    assert existing["status"] == "completed"
    assert source["request_id"] == ctx.request_id
    assert page["chunks"][0]["text"] == "Captured once"


@pytest.mark.parametrize("phase", ["run", "key"])
def test_keyed_creation_orphans_are_erased_and_fenced_by_exact_cleanup(phase):
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    delayed = []

    def interrupt(container, name, data, etag):
        payload = json.loads(data)
        if payload.get("kind") == ("memory_run" if phase == "run" else "memory_key"):
            delayed.append((container, name, data))
            harness.transport.before_put = None
            raise MemoryUnavailableError("Keyed write delayed until after deletion.")

    harness.transport.before_put = interrupt
    with pytest.raises(MemoryUnavailableError):
        harness.store.get_or_create_manifest(ctx)
    deleted = harness.store.delete_conversation_memory(ctx)

    assert deleted["complete"] is True
    assert any("/keys/" in name for _, name in harness.transport.blobs)
    assert all(not record.data for record in harness.transport.blobs.values())
    with pytest.raises(MemoryConflictError):
        harness.transport.put(*delayed[0])


def test_keyed_budget_archive_contains_index_and_restores_same_counters():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    request = harness.store.get_or_create_manifest(ctx)
    harness.store.append_checkpoint(ctx, request["run_id"], checkpoint={"downloads": 3, "file_context_tokens": 4000})
    harness.store.archive_conversation_memory(ctx)
    archive = list(harness.store.iter_retained_blobs(ctx))
    harness.store.restore_conversation_memory(ctx)
    restored = harness.store.get_or_create_manifest(ctx)
    checkpoint = harness.store.read_checkpoint(ctx, restored["run_id"])

    assert any("/keys/" in blob.blob_name for blob in archive)
    assert len(archive) == len(harness.transport.blobs)
    assert restored["run_id"] == request["run_id"]
    assert checkpoint["checkpoint"] == {"downloads": 3, "file_context_tokens": 4000}
    harness.store.delete_conversation_memory(ctx)
    assert all(not record.data for record in harness.transport.blobs.values())


def test_keyed_lookup_rejects_tampered_run_link_instead_of_replacing_budget():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="logical-request")
    harness.store.get_or_create_manifest(ctx)
    unrelated = harness.store.create_run(ctx)
    key = next(key for key in harness.transport.blobs if "/keys/" in key[1])
    record = harness.transport.blobs[key]
    payload = json.loads(record.data)
    payload["run_id"] = unrelated["run_id"]
    harness.transport.put(*key, json.dumps(payload).encode("utf-8"), etag=record.etag)
    with pytest.raises(MemoryIntegrityError):
        harness.store.get_or_create_manifest(ctx)


def test_repeated_restore_does_not_cancel_an_already_active_worker():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    harness.store.archive_conversation_memory(harness.context)
    harness.store.restore_conversation_memory(harness.context)
    claim = harness.store.claim(harness.context, run_id)
    restored = harness.store.restore_conversation_memory(harness.context)
    checkpoint = harness.store.append_checkpoint(
        harness.context, run_id, checkpoint={"still_active": True}, claim=claim,
    )
    assert restored["state"] == "active"
    assert checkpoint["checkpoint"] == {"still_active": True}


def test_archive_and_restore_cannot_interleave_into_inconsistent_states():
    harness = MemoryHarness()
    run_id, _ = harness.run()
    observed = []

    def try_conflicting_restore(container, name, data, etag):
        if name.endswith(f"{run_id}/manifest.json") and json.loads(data).get("archived") is True:
            harness.transport.before_put = None
            with pytest.raises(MemoryConflictError):
                harness.store.restore_conversation_memory(harness.context)
            observed.append("conflict")

    harness.transport.before_put = try_conflicting_restore
    archived = harness.store.archive_conversation_memory(harness.context)
    manifest = harness.store.read_manifest(harness.context, run_id)
    assert observed == ["conflict"]
    assert archived["state"] == "archived"
    assert manifest["archived"] is True


def test_analysis_job_restarts_by_checkpoint_without_reprocessing_committed_batches():
    harness = MemoryHarness()
    run_id, _ = harness.run(5)
    processed = []

    def processor(batch):
        processed.append(batch.batch_id)
        batch.heartbeat()
        rows = [chunk["locator"]["row_start"] for chunk in batch.evidence["chunks"]]
        previous_sum = batch.previous_state.get("sum", 0)
        return AnalysisBatchResult({"rows": rows}, "Exact row batch.", {"sum": previous_sum + sum(rows)})

    def runner():
        return ConversationAnalysisJobRunner(
            harness.new_store(), processor=processor, authorize_resume=lambda ctx, manifest: True,
            processor_version="sum-v1", batch_chunks=2,
        )

    first = runner().run_next_batch(harness.context, run_id)
    second = runner().run_next_batch(harness.context, run_id)
    last = runner().run_next_batch(harness.context, run_id)
    repeated = runner().run_next_batch(harness.context, run_id)

    assert first["checkpoint"]["completed_units"] == 2
    assert second["checkpoint"]["completed_units"] == 4
    assert last["status"] == "completed"
    assert last["checkpoint"]["completed_units"] == 5
    assert last["checkpoint"]["checkpoint"]["state"] == {"sum": 15}
    assert repeated["checkpoint"] == last["checkpoint"]
    assert len(processed) == len(set(processed)) == 3


def test_job_revalidates_approval_and_claim_after_processing_before_checkpoint():
    harness = MemoryHarness()
    run_id, _ = harness.run(2)

    def processor(batch):
        harness.store.cancel(harness.context, run_id)
        return AnalysisBatchResult({"must_not_commit": True})

    runner = ConversationAnalysisJobRunner(
        harness.store, processor=processor, authorize_resume=lambda ctx, manifest: True, processor_version="v1",
    )
    with pytest.raises(MemoryConflictError):
        runner.run_next_batch(harness.context, run_id)
    latest = harness.store.read_checkpoint(harness.context, run_id)
    assert latest is None
    denied = ConversationAnalysisJobRunner(
        harness.store, processor=processor, authorize_resume=lambda ctx, manifest: False, processor_version="v1",
    )
    with pytest.raises(MemoryAuthorizationError):
        denied.run_next_batch(harness.context, run_id)


def test_job_recovers_committed_output_after_crash_without_calling_processor_twice():
    harness = MemoryHarness()
    run_id, _ = harness.run(4)
    calls = []

    def processor(batch):
        calls.append(batch.batch_id)
        return AnalysisBatchResult({"captured": [chunk["text"] for chunk in batch.evidence["chunks"]]})

    def fail_checkpoint_commit(container, name, data, etag):
        if name.endswith(f"{run_id}/manifest.json") and json.loads(data).get("checkpoint_count") == 1:
            harness.transport.before_put = None
            raise MemoryUnavailableError("Commit was interrupted.")

    def runner():
        return ConversationAnalysisJobRunner(
            harness.new_store(), processor=processor, authorize_resume=lambda ctx, manifest: True,
            processor_version="v1", batch_chunks=2,
        )

    harness.transport.before_put = fail_checkpoint_commit
    with pytest.raises(MemoryUnavailableError):
        runner().run_next_batch(harness.context, run_id)
    failed = harness.store.read_manifest(harness.context, run_id)
    resumed = runner().run_next_batch(harness.context, run_id)
    assert failed["status"] == "failed"
    assert failed["pending_operation"] == "checkpoint"
    assert resumed["status"] == "completed"
    assert resumed["manifest"]["checkpoint_count"] == 2
    assert len(calls) == 2
    assert len(set(calls)) == 2


def test_processing_captured_windows_never_claims_uncaptured_source_coverage():
    harness = MemoryHarness()
    run_id = harness.store.create_run(harness.context)["run_id"]
    harness.store.add_evidence(
        harness.context, run_id, source=EvidenceSource("test", "partial-file", "v1", coverage_complete=False),
        chunks=(EvidenceChunk("Only captured window", EvidenceLocation(pages=(7,))),),
    )
    runner = ConversationAnalysisJobRunner(
        harness.store, processor=lambda batch: AnalysisBatchResult({"note": "Window only"}),
        authorize_resume=lambda ctx, manifest: True, processor_version="v1",
    )
    result = runner.run_next_batch(harness.context, run_id)
    assert result["status"] == "completed"
    assert result["manifest"]["source_coverage_complete"] is False
    assert result["checkpoint"]["total_units"] == 1


def test_processor_failure_is_explicit_and_retry_has_a_stable_batch_identity():
    harness = MemoryHarness()
    run_id, _ = harness.run(1)
    calls = []

    def processor(batch):
        calls.append(batch.batch_id)
        if len(calls) == 1:
            raise ValueError("Processor failed.")
        return AnalysisBatchResult({"answer": "Retried without remote mutation."})

    runner = ConversationAnalysisJobRunner(
        harness.store, processor=processor, authorize_resume=lambda ctx, manifest: True, processor_version="v1",
    )
    with pytest.raises(ValueError):
        runner.run_next_batch(harness.context, run_id)
    failed = harness.store.read_manifest(harness.context, run_id)
    result = runner.run_next_batch(harness.context, run_id)
    assert failed["status"] == "failed"
    assert result["status"] == "completed"
    assert len(calls) == 2
    assert calls[0] == calls[1]


def test_processor_revision_or_source_set_change_does_not_reuse_incompatible_cursor():
    harness = MemoryHarness()
    run_id, _ = harness.run(3)
    processor = lambda batch: AnalysisBatchResult({"batch": batch.batch_id})
    original = ConversationAnalysisJobRunner(
        harness.store, processor=processor, authorize_resume=lambda ctx, manifest: True,
        processor_version="v1", batch_chunks=1,
    )
    original.run_next_batch(harness.context, run_id)
    revised = ConversationAnalysisJobRunner(
        harness.store, processor=processor, authorize_resume=lambda ctx, manifest: True,
        processor_version="v2", batch_chunks=1,
    )
    with pytest.raises(MemoryStateError):
        revised.run_next_batch(harness.context, run_id)
    harness.store.resume(harness.context, run_id)
    harness.store.add_evidence(
        harness.context, run_id, source=EvidenceSource("test", "extra", "v1"),
        chunks=(EvidenceChunk("New source"),),
    )
    with pytest.raises(MemoryStateError):
        original.run_next_batch(harness.context, run_id)


def test_azure_transport_uses_conditional_streams_and_checks_size_before_download():
    class Blob:
        def __init__(self):
            self.size = 6
            self.downloads = []
            self.uploads = []
            self.deletions = []

        def get_blob_properties(self):
            return SimpleNamespace(size=self.size, etag='"original"')

        def download_blob(self, **kwargs):
            self.downloads.append(kwargs)
            return SimpleNamespace(chunks=lambda: iter((b"abc", b"def")))

        def upload_blob(self, data, **kwargs):
            self.uploads.append((data, kwargs))
            return {"etag": '"new"'}

        def delete_blob(self, **kwargs):
            self.deletions.append(kwargs)

    blob = Blob()
    adapter = AzureMemoryBlobTransport(SimpleNamespace(get_blob_client=lambda **kwargs: blob))
    record = adapter.read("personal-chat", "generated/path", max_bytes=6)
    etag = adapter.put("personal-chat", "generated/path", b"new", etag=record.etag)
    adapter.delete("personal-chat", "generated/path", etag=etag)

    assert record.data == b"abcdef"
    assert blob.downloads[0] == {
        "offset": 0, "length": 6, "etag": '"original"', "match_condition": MatchConditions.IfNotModified,
        "max_concurrency": 1,
    }
    assert isinstance(blob.uploads[0][0], BytesIO)
    assert blob.uploads[0][1]["length"] == 3
    assert blob.uploads[0][1]["etag"] == '"original"'
    assert blob.uploads[0][1]["overwrite"] is True
    assert blob.deletions[0]["delete_snapshots"] == "include"
    blob.size = 7
    with pytest.raises(MemoryLimitError):
        adapter.read("personal-chat", "generated/path", max_bytes=6)
    assert len(blob.downloads) == 1


def test_missing_storage_is_an_explicit_dependency_error():
    calls = []

    def missing():
        calls.append("factory")
        return None

    with pytest.raises(MemoryUnavailableError):
        create_conversation_memory_store(
            missing, authorize_access=lambda ctx, operation: True, log_event=lambda *args, **kwargs: None,
        )
    assert calls == ["factory"]


@pytest.mark.parametrize("failure", ["container", "network"])
def test_azure_transport_does_not_treat_missing_container_or_network_as_empty_memory(failure):
    def fail():
        if failure == "container":
            error = ResourceNotFoundError("Container unavailable.")
            error.error_code = "ContainerNotFound"
            raise error
        raise ServiceRequestError("Network unavailable.")

    client = SimpleNamespace(get_blob_client=lambda **kwargs: SimpleNamespace(get_blob_properties=fail))
    adapter = AzureMemoryBlobTransport(client)
    with pytest.raises(MemoryUnavailableError):
        adapter.read("personal-chat", "memory/manifest.json", max_bytes=MAX_MANIFEST_BYTES)


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("reverse_imports", [False, True])
def test_real_cold_import_has_no_settings_config_logging_or_network_dependency(optimized, reverse_imports):
    probe = """
import importlib.abc
import socket
import sys

class RejectBootstrap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'config', 'functions_settings', 'functions_appinsights'}:
            raise RuntimeError('Forbidden bootstrap import: ' + fullname)

def deny_network(*args, **kwargs):
    raise RuntimeError('Network access during cold import')

socket.socket.connect = deny_network
socket.create_connection = deny_network
sys.meta_path.insert(0, RejectBootstrap())
IMPORT_MODULES
if any(name in sys.modules for name in ('config', 'functions_settings', 'functions_appinsights')):
    raise RuntimeError('A bootstrap owner was imported')
if functions_conversation_memory.MEMORY_SCHEMA_VERSION != 1:
    raise RuntimeError('Real module was not imported')
"""
    modules = ["functions_conversation_memory", "functions_m365_analysis_jobs"]
    if reverse_imports:
        modules.reverse()
    probe = probe.replace("IMPORT_MODULES", "\n".join(f"import {module}" for module in modules))
    arguments = [sys.executable]
    if optimized:
        arguments.append("-O")
    result = subprocess.run(
        [*arguments, "-c", probe], cwd=APP_ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_optimized_python_executes_real_persistence_and_authorization_operations():
    probe = """
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd().parents[1] / 'functional_tests'))
from test_conversation_working_memory import MemoryHarness
from functions_conversation_memory import MemoryAuthorizationError
harness = MemoryHarness()
run_id, source = harness.run(2)
try:
    harness.store.read_evidence_range(harness.reader, run_id, source['evidence_id'])
except MemoryAuthorizationError:
    pass
else:
    raise RuntimeError('Staging authorization disappeared under optimized Python')
harness.publish(run_id)
page = harness.store.read_evidence_range(harness.reader, run_id, source['evidence_id'])
if len(page['chunks']) != 2:
    raise RuntimeError('Required persistence/read operations disappeared')
request_context = replace(harness.context, request_id='optimized-request')
request = harness.store.get_or_create_manifest(request_context)
repeated = harness.new_store().get_or_create_manifest(request_context)
if request['run_id'] != repeated['run_id']:
    raise RuntimeError('Request-key idempotence disappeared under optimized Python')
result = harness.store.delete_conversation_memory(harness.context)
if result['complete'] is not True or any(record.data for record in harness.transport.blobs.values()):
    raise RuntimeError('Required cleanup operations disappeared')
"""
    result = subprocess.run(
        [sys.executable, "-O", "-c", probe], cwd=APP_ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
