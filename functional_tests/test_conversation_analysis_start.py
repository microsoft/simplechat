# test_conversation_analysis_start.py
#!/usr/bin/env python3
"""
Functional tests for separate analysis runs over completed conversation captures.
Version: 0.261.029
Implemented in: 0.261.029

These tests execute real memory, analysis, and provider modules with scoped
external-I/O fixtures. Completed/published captures must not be mistaken for
completed analysis, reopened, or rewritten. Initialization and batch restarts
preserve selected evidence, capture provenance, and immutable input bindings.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from threading import Barrier

import pytest

from test_conversation_working_memory import (
    AnalysisBatchResult,
    ConversationAnalysisJobRunner,
    EvidenceChunk,
    EvidenceLocation,
    EvidenceSource,
    MemoryAuthorizationError,
    MemoryConflictError,
    MemoryHarness,
    MemoryIntegrityError,
    MemoryLimitError,
    MemoryStateError,
    MemoryUnavailableError,
)
# Imported pytest fixtures exercise the actual provider-to-memory handoff.
from test_m365_provider_core import (
    ContentGraphFixture,
    execution,
    memory_runtime,
    real_content_helpers,
    retrieval,
)


def prepared_capture(harness, *, shared=True, count=5):
    run_id, source = harness.run(count)
    harness.store.append_checkpoint(
        harness.context, run_id, checkpoint={"m365_file": {"phase": "prepared"}},
        output={"coverage": {"units_read": count, "units_total": count, "complete": True}},
    )
    harness.store.complete_run(harness.context, run_id)
    if shared:
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    return run_id, source


def analysis_runner(harness, *, processor=None, processor_version="exact-v1", batch_chunks=2, authorize=None):
    return ConversationAnalysisJobRunner(
        harness.new_store(),
        processor=processor or (lambda batch: AnalysisBatchResult(
            {"text": [chunk["text"] for chunk in batch.evidence["chunks"]]},
        )),
        authorize_resume=authorize or (lambda ctx, manifest: True),
        processor_version=processor_version,
        batch_chunks=batch_chunks,
    )


def test_published_provider_capture_starts_distinct_private_analysis_with_fresh_cursor():
    harness = MemoryHarness()
    source_run_id, source = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analyze-request")
    source_blobs = {
        key: record for key, record in harness.transport.blobs.items() if f"/{source_run_id}/" in key[1]
    }
    calls = []

    def processor(batch):
        calls.append(batch.batch_id)
        prior = batch.previous_state.get("row_total", 0)
        total = prior + sum(chunk["locator"]["row_start"] for chunk in batch.evidence["chunks"])
        return AnalysisBatchResult({"row_total": total}, state={"row_total": total})

    runner = analysis_runner(harness, processor=processor)
    analysis = runner.start_analysis(ctx, source_run_id, analysis_key="parent-step")
    fresh = harness.store.read_checkpoint(ctx, analysis["run_id"])
    copied = harness.store.list_sources(ctx, analysis["run_id"])["sources"][0]
    repeated = runner.start_analysis(ctx, source_run_id, analysis_key="parent-step")

    assert analysis["run_id"] != source_run_id
    assert analysis["status"] == "queued"
    assert analysis["publication"] is None
    assert analysis["principal_id"] == "reader"
    assert analysis["completed_units"] == 0
    assert fresh["checkpoint"]["analysis_job"]["processed_chunks"] == 0
    assert fresh["checkpoint"]["state"] == {}
    assert "m365_file" not in fresh["checkpoint"]
    assert copied["capture"] == source["capture"]
    assert copied["content_sha256"] == source["content_sha256"]
    assert copied["copied_from"]["run_id"] == source_run_id
    assert copied["copied_from"]["evidence_id"] == source["evidence_id"]
    assert repeated["run_id"] == analysis["run_id"]
    assert repeated["evidence_count"] == 1
    assert calls == []
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_manifest(harness.context, analysis["run_id"])

    first = runner.run_next_batch(ctx, analysis["run_id"])
    second = analysis_runner(harness, processor=processor).run_next_batch(ctx, analysis["run_id"])
    final = analysis_runner(harness, processor=processor).run_next_batch(ctx, analysis["run_id"])
    finished = runner.start_analysis(ctx, source_run_id, analysis_key="parent-step")

    assert first["checkpoint"]["completed_units"] == 2
    assert second["checkpoint"]["completed_units"] == 4
    assert final["status"] == "completed"
    assert final["checkpoint"]["checkpoint"]["state"] == {"row_total": 15}
    assert len(calls) == len(set(calls)) == 3
    assert finished["run_id"] == analysis["run_id"]
    assert finished["status"] == "completed"
    assert all(harness.transport.blobs[key] == record for key, record in source_blobs.items())


@pytest.mark.parametrize("shared", [False, True])
def test_completed_capture_cannot_be_reported_as_completed_analysis(shared):
    harness = MemoryHarness()
    run_id, _ = prepared_capture(harness, shared=shared)
    ctx = replace(harness.context, request_id="analysis")
    with pytest.raises(MemoryStateError, match="call start_analysis"):
        analysis_runner(harness).run_next_batch(ctx, run_id)


def test_analysis_publication_requires_a_grant_bound_to_the_new_run_and_actor():
    harness = MemoryHarness()
    source_run_id, source = prepared_capture(harness, count=1)
    ctx = replace(harness.reader, request_id="analysis")
    runner = analysis_runner(harness)
    analysis = runner.start_analysis(ctx, source_run_id)
    runner.run_next_batch(ctx, analysis["run_id"])
    harness.grant_override = {
        "principal_id": "owner", "run_id": source_run_id, "request_id": "request-1",
    }
    with pytest.raises(MemoryAuthorizationError):
        harness.store.publish(ctx, analysis["run_id"], grant_context=harness.grant_context)
    with pytest.raises(MemoryAuthorizationError):
        harness.store.read_manifest(harness.context, analysis["run_id"])
    harness.grant_override = {
        "authorization_id": "analysis-publication", "approval_ids": ("analysis-approval",),
    }
    published = harness.store.publish(ctx, analysis["run_id"], grant_context=harness.grant_context)
    sources = harness.store.list_sources(harness.context, analysis["run_id"])["sources"]
    page = harness.store.read_evidence_range(harness.context, analysis["run_id"], sources[0]["evidence_id"])

    assert published["publication"]["principal_id"] == "reader"
    assert published["publication"]["authorization_id"] == "analysis-publication"
    assert published["publication"]["includes_all_retained_evidence"] is True
    assert sources[0]["capture"] == source["capture"]
    assert page["chunks"][0]["text"] == "Original evidence 0"


def test_private_capture_is_only_available_to_its_owner_during_analysis_start():
    harness = MemoryHarness()
    run_id, _ = prepared_capture(harness, shared=False)
    reader = replace(harness.reader, request_id="reader-analysis")
    with pytest.raises(MemoryAuthorizationError):
        analysis_runner(harness).start_analysis(reader, run_id)
    owner = replace(harness.context, request_id="owner-analysis")
    analysis = analysis_runner(harness).start_analysis(owner, run_id)
    assert analysis["principal_id"] == owner.principal_id
    assert analysis["evidence_count"] == 1
    assert analysis["publication"] is None


def test_composite_reference_selects_only_its_source_and_preserves_incomplete_coverage():
    harness = MemoryHarness()
    run_id, first = harness.run(2)
    second = harness.store.add_evidence(
        harness.context, run_id,
        source=EvidenceSource("spo", "drive:partial", "excerpt-sha256:test", coverage_complete=False),
        chunks=(EvidenceChunk("Only this retained excerpt", EvidenceLocation(pages=(7,))),),
    )
    harness.publish(run_id)
    ctx = replace(harness.reader, request_id="selected-evidence")
    runner = analysis_runner(harness)
    analysis = runner.start_analysis(ctx, f"{run_id}:{second['evidence_id']}")
    sources = harness.store.list_sources(ctx, analysis["run_id"])["sources"]
    result = runner.run_next_batch(ctx, analysis["run_id"])

    assert len(sources) == 1
    assert sources[0]["content_sha256"] == second["content_sha256"]
    assert sources[0]["content_sha256"] != first["content_sha256"]
    assert sources[0]["copied_from"]["evidence_id"] == second["evidence_id"]
    assert result["status"] == "completed"
    assert result["manifest"]["source_coverage_complete"] is False
    assert result["checkpoint"]["output"]["text"] == ["Only this retained excerpt"]
    assert result["checkpoint"]["total_units"] == 1


def test_analysis_start_rejects_empty_unfinished_and_overlapping_inputs():
    harness = MemoryHarness()
    run_id, source = harness.run()
    ctx = replace(harness.context, request_id="analysis")
    runner = analysis_runner(harness)
    with pytest.raises(MemoryStateError):
        runner.start_analysis(ctx, run_id)
    harness.publish(run_id)
    for references in (
        [], ["../arbitrary-path"], ["https://storage.example/path"], [run_id, run_id],
        [run_id, f"{run_id}:{source['evidence_id']}"], [False],
    ):
        with pytest.raises(ValueError):
            runner.start_analysis(ctx, references)
    with pytest.raises(MemoryLimitError):
        runner.start_analysis(ctx, [f"{index:032x}" for index in range(33)])
    with pytest.raises(MemoryAuthorizationError):
        runner.start_analysis(harness.context, run_id)
    empty = harness.store.create_run(ctx)
    harness.store.complete_run(ctx, empty["run_id"])
    with pytest.raises(MemoryStateError):
        runner.start_analysis(ctx, empty["run_id"])


def test_analysis_key_cannot_be_rebound_to_other_inputs_or_processor():
    harness = MemoryHarness()
    first, _ = prepared_capture(harness)
    second, _ = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    runner = analysis_runner(harness)
    original = runner.start_analysis(ctx, first, analysis_key="step-1")
    with pytest.raises(MemoryStateError):
        runner.start_analysis(ctx, second, analysis_key="step-1")
    with pytest.raises(MemoryStateError):
        analysis_runner(harness, processor_version="different").start_analysis(ctx, first, analysis_key="step-1")
    after = harness.store.read_manifest(ctx, original["run_id"])
    assert after["evidence_count"] == 1
    assert after["checkpoint_count"] == original["checkpoint_count"]


def test_completed_label_without_processed_analysis_is_rejected():
    harness = MemoryHarness()
    source_run_id, _ = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    runner = analysis_runner(harness)
    analysis = runner.start_analysis(ctx, source_run_id)
    harness.store.complete_run(ctx, analysis["run_id"])
    with pytest.raises(MemoryIntegrityError, match="unprocessed"):
        runner.run_next_batch(ctx, analysis["run_id"])


def test_canceled_analysis_start_does_not_resurrect_it_or_change_published_source():
    harness = MemoryHarness()
    source_run_id, _ = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    runner = analysis_runner(harness)
    analysis = runner.start_analysis(ctx, source_run_id, analysis_key="cancel")
    before = harness.store.read_manifest(ctx, source_run_id)
    harness.store.cancel(ctx, analysis["run_id"])
    with pytest.raises(MemoryStateError, match="canceled"):
        runner.start_analysis(ctx, source_run_id, analysis_key="cancel")
    after = harness.store.read_manifest(ctx, source_run_id)
    assert after == before


def test_start_authorization_denial_never_copies_evidence():
    harness = MemoryHarness()
    run_id, _ = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    runner = analysis_runner(harness, authorize=lambda ctx, manifest: False)
    with pytest.raises(MemoryAuthorizationError):
        runner.start_analysis(ctx, run_id)
    runs = harness.store.list_runs(ctx)["runs"]
    analyses = [run for run in runs if run["purpose"] == "conversation_analysis"]
    assert len(analyses) == 1
    assert analyses[0]["evidence_count"] == 0
    assert analyses[0]["checkpoint_count"] == 0


def test_copy_commit_crash_recovers_without_recopying_source_chunks():
    harness = MemoryHarness()
    source_run_id, source = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    target = harness.store.get_or_create_manifest(ctx, kind="conversation_analysis", key="recover")
    target_id = target["run_id"]

    def fail_source_commit(container, name, data, etag):
        if name.endswith(f"{target_id}/manifest.json") and json.loads(data).get("evidence_count") == 1:
            harness.transport.before_put = None
            raise MemoryUnavailableError("Copy commit failed.")

    harness.transport.before_put = fail_source_commit
    with pytest.raises(MemoryUnavailableError):
        analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="recover")
    before = len(harness.transport.calls)
    recovered = analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="recover")
    new_source_reads = [
        call for call in harness.transport.calls[before:]
        if call[0] == "read" and f"/{source_run_id}/objects/" in call[2]
    ]
    copied = harness.store.list_sources(ctx, target_id)["sources"]

    assert recovered["run_id"] == target_id
    assert recovered["status"] == "queued"
    assert len(copied) == 1
    assert copied[0]["content_sha256"] == source["content_sha256"]
    assert new_source_reads == []


def test_incomplete_local_copy_is_fenced_then_retried_from_immutable_evidence():
    harness = MemoryHarness()
    source_run_id, source = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    target = harness.store.get_or_create_manifest(ctx, kind="conversation_analysis", key="retry-copy")
    target_id = target["run_id"]
    delayed = []

    def interrupt_copy(container, name, data, etag):
        if f"/{target_id}/objects/0000000000000001.json" in name:
            harness.transport.before_put = None
            delayed.append((container, name, data))
            raise MemoryUnavailableError("Copy upload interrupted.")

    harness.transport.before_put = interrupt_copy
    with pytest.raises(MemoryUnavailableError):
        analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="retry-copy")
    recovered = analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="retry-copy")
    copied = harness.store.list_sources(ctx, target_id)["sources"]
    with pytest.raises(MemoryConflictError):
        harness.transport.put(*delayed[0])

    assert recovered["evidence_count"] == 1
    assert recovered["source_slots"] == 2
    assert copied[0]["content_sha256"] == source["content_sha256"]
    assert recovered["captured_chunk_count"] == 5


def test_concurrent_starts_share_one_target_and_one_copy():
    harness = MemoryHarness()
    source_run_id, _ = prepared_capture(harness)
    ctx = replace(harness.reader, request_id="analysis")
    target = harness.store.get_or_create_manifest(ctx, kind="conversation_analysis", key="concurrent")
    target_id = target["run_id"]
    barrier = Barrier(2)

    def synchronize_claims(container, name, data, etag):
        if name.endswith(f"{target_id}/manifest.json"):
            payload = json.loads(data)
            if payload.get("generation") == 1 and payload.get("claim") is not None:
                barrier.wait(timeout=5)

    harness.transport.before_put = synchronize_claims

    def start_worker():
        try:
            return analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="concurrent")
        except MemoryConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(start_worker) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    harness.transport.before_put = None
    resumed = analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="concurrent")
    successful = [result for result in results if result is not None]

    assert len(successful) == 1
    assert successful[0]["run_id"] == resumed["run_id"] == target_id
    assert resumed["evidence_count"] == 1
    assert resumed["captured_chunk_count"] == 5


def test_source_revision_change_during_start_is_not_silently_rebound():
    harness = MemoryHarness()
    source_run_id, _ = prepared_capture(harness, shared=False)
    ctx = replace(harness.context, request_id="analysis")
    target = harness.store.get_or_create_manifest(ctx, kind="conversation_analysis", key="revision-check")
    target_id = target["run_id"]
    source_key = next(key for key in harness.transport.blobs if key[1].endswith(f"{source_run_id}/manifest.json"))

    def change_source_revision(container, name, data, etag):
        if f"/{target_id}/checkpoints/" in name:
            harness.transport.before_put = None
            current = harness.transport.blobs[source_key]
            changed = json.loads(current.data)
            changed["content_revision"] += 1
            harness.transport.put(*source_key, json.dumps(changed).encode("utf-8"), etag=current.etag)

    harness.transport.before_put = change_source_revision
    with pytest.raises(MemoryConflictError):
        analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="revision-check")
    with pytest.raises(MemoryStateError):
        analysis_runner(harness).start_analysis(ctx, source_run_id, analysis_key="revision-check")
    target = harness.store.read_manifest(ctx, target_id)
    assert target["evidence_count"] == 0


def test_full_capture_reference_pages_many_sources_without_large_input_arrays():
    harness = MemoryHarness()
    ctx = replace(harness.context, request_id="capture")
    source_run_id = harness.store.create_run(ctx)["run_id"]
    for index in range(35):
        harness.store.add_evidence(
            ctx, source_run_id, source=EvidenceSource("onedrive", f"drive:item-{index}", "v1", coverage_complete=True),
            chunks=(EvidenceChunk(f"Row {index}"),),
        )
    harness.store.complete_run(ctx, source_run_id)
    analysis_ctx = replace(ctx, request_id="analysis")
    analysis = analysis_runner(harness).start_analysis(analysis_ctx, source_run_id)
    initial = harness.store.read_checkpoint(analysis_ctx, analysis["run_id"], index=0)

    assert analysis["evidence_count"] == 35
    assert analysis["captured_chunk_count"] == 35
    assert len(initial["checkpoint"]["analysis_setup"]["inputs"]) == 1
    assert len(json.dumps(analysis).encode("utf-8")) < 4096


@pytest.mark.parametrize("reference_field", ["memory_id", "evidence_reference"])
def test_real_provider_prepared_snapshot_runs_actual_analysis_without_new_graph_calls(
    execution, memory_runtime, real_content_helpers, monkeypatch, reference_field,
):
    execution.shared = True
    text = "Actual provider evidence \u03b1 " * 700
    graph = ContentGraphFixture(text=text)
    prepared = graph.operations().prepare_file("drive-1", "item-1")
    original_context = memory_runtime.binding(execution)[1]
    before = memory_runtime.store.read_manifest(original_context, prepared["memory_run_id"])
    execution.actor_user_id = execution.data_user_id = "user-2"
    execution.request_id = "analysis-request"
    ctx = replace(memory_runtime.binding(execution)[1], request_id=execution.request_id)
    graph_calls = list(graph.calls)
    processed = []

    def no_remote(*args, **kwargs):
        raise AssertionError("Analyzing retained published evidence must not perform fresh remote source authorization.")

    monkeypatch.setattr(retrieval, "authorize_m365_source", no_remote)

    def processor(batch):
        processed.extend(chunk["text"] for chunk in batch.evidence["chunks"])
        return AnalysisBatchResult({"characters": sum(len(chunk["text"]) for chunk in batch.evidence["chunks"])})

    def runner():
        return ConversationAnalysisJobRunner(
            memory_runtime.store, processor=processor, authorize_resume=lambda ctx, manifest: True,
            processor_version="provider-integration-v1", batch_chunks=1,
        )

    analysis = runner().start_analysis(ctx, prepared[reference_field], analysis_key="provider-analysis-step")
    for _ in range(prepared["total_chunks"]):
        result = runner().run_next_batch(ctx, analysis["run_id"])
    after = memory_runtime.store.read_manifest(ctx, prepared["memory_run_id"])

    assert analysis["run_id"] != prepared["memory_run_id"]
    assert analysis["status"] == "queued"
    assert result["status"] == "completed"
    assert "".join(processed) == text
    assert result["checkpoint"]["completed_units"] == prepared["total_chunks"]
    assert after == before
    assert graph.downloads == 1
    assert graph.calls == graph_calls


def test_optimized_python_starts_and_executes_real_separate_analysis():
    probe = """
from dataclasses import replace
from test_conversation_working_memory import MemoryHarness
from functions_m365_analysis_jobs import ConversationAnalysisJobRunner, AnalysisBatchResult
harness = MemoryHarness()
source_run, source = harness.run(3)
harness.publish(source_run)
ctx = replace(harness.reader, request_id='optimized-analysis')
processed = []
def process(batch):
    processed.extend(chunk['text'] for chunk in batch.evidence['chunks'])
    return AnalysisBatchResult({'count': len(processed)})
runner = ConversationAnalysisJobRunner(
    harness.store, processor=process, authorize_resume=lambda ctx, run: True,
    processor_version='v1', batch_chunks=1,
)
analysis = runner.start_analysis(ctx, source_run)
if analysis['run_id'] == source_run or analysis['status'] != 'queued' or processed:
    raise RuntimeError('Source completion was mistaken for analysis completion')
for _ in range(3):
    result = runner.run_next_batch(ctx, analysis['run_id'])
if result['status'] != 'completed' or processed != ['Original evidence 0', 'Original evidence 1', 'Original evidence 2']:
    raise RuntimeError('Required startup/copy/analysis operations disappeared under optimized Python')
"""
    result = subprocess.run(
        [sys.executable, "-O", "-c", probe], cwd=Path(__file__).resolve().parent,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
