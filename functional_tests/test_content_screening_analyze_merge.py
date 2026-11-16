# test_content_screening_analyze_merge.py
"""
Regression coverage for screening combined with durable React V2 Analyze.
Version: 0.261.113
Implemented in: 0.261.113

Run the real analysis producer and screening guards against mutable fake Cosmos
records. Held sources must not be sent, returned, or reused from a checkpoint.
No live documents, model calls, or Azure services are used (Refs #1476).
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from test_document_analysis_final_results import run_analysis
from test_document_analysis_work_recovery import make_checkpoints, run_saved
from test_support.document_analysis import (
    FixtureAnalysisClient,
    document_analysis_runtime,
    extract_fixture_findings,
    original_document,
)
from content_screening.access import PROVENANCE_FIELD
from content_screening.contracts import DocumentHeldError


@pytest.mark.parametrize("mode", ["legacy", "final", "factory", "parallel"])
@pytest.mark.parametrize("hold_phase", ["document_started", "model_response", "window_completed"])
def test_analysis_hold_blocks_sequential_factory_and_parallel_results(mode, hold_phase):
    documents = {"one": original_document("one", ["The service uses a sole supplier."])}

    def hold():
        documents["one"]["document"]["content_screening"] = {"state": "pending_review"}

    def response(prompt):
        result = extract_fixture_findings(prompt)
        if hold_phase == "model_response":
            hold()
        return result

    def activity(event):
        if event["type"] == hold_phase:
            hold()

    client = FixtureAnalysisClient(response)
    with document_analysis_runtime(documents) as runtime, ThreadPoolExecutor(max_workers=2) as executor:
        options = {"activity_callback": activity, "max_retries_per_window": 1}
        if mode == "legacy":
            options["result_version"] = None
        if mode in {"factory", "parallel"}:
            options["invoke_prompt_factory"] = lambda metadata: client.invoke_prompt
        if mode == "parallel":
            options.update(executor=executor, max_window_concurrency=2)
        with pytest.raises(DocumentHeldError):
            run_analysis(runtime, documents, client, **options)
        assert len(client.calls) == (0 if hold_phase == "document_started" else 1)
        assert runtime.screening_reads


def test_final_analysis_retains_screening_provenance_in_durable_coverage():
    documents = {"one": original_document("one", ["The service uses a sole supplier."])}
    with document_analysis_runtime(documents) as runtime:
        result, client = run_analysis(runtime, documents)
        assert len(client.calls) == 1
        proof = result["coverage"]["documents"][0][PROVENANCE_FIELD]
        assert proof["document_id"] == "one"
        assert proof["generation"] is None


def test_completed_checkpoint_cannot_bypass_a_new_screening_hold(monkeypatch):
    documents = {"one": original_document("one", ["The service uses a sole supplier."])}
    with document_analysis_runtime(documents) as runtime:
        first = make_checkpoints(documents)
        initial, client = run_saved(runtime, documents, first)
        assert len(client.calls) == 1
        assert initial["authoritative_result"]["value"]
        documents["one"]["document"]["content_screening"] = {"state": "pending_review"}
        monkeypatch.setattr(
            runtime.search, "get_document_chunks_payload",
            lambda **kwargs: pytest.fail("A completed checkpoint must not re-extract a held source."),
        )
        retry = FixtureAnalysisClient()
        second = make_checkpoints(documents, store=first.store, attempt="assistant-2", previous="assistant-1")
        with pytest.raises(DocumentHeldError):
            run_saved(runtime, documents, second, client=retry)
        assert retry.calls == []
