# test_orchestration_retained_analysis_publication.py
"""
Authorized retained Analyze descriptors on replies with downstream failures.
Version: 0.261.398
Implemented in: 0.261.398

Use real native producers, immutable saved readers and SDK-backed storage doubles.
Inspection must preserve partial status, conversation/producer binding and digests.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

# Match the standalone application-path setup used by the native integration harness.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_analysis_access import AnalysisResultUnavailable
from test_orchestration_internal_analysis import analyze, internal


def failed_run(result):
    return {
        "id": "run-1", "conversation_id": "conversation-1", "user_id": "owner", "status": "failed",
        "execution_steps": [{
            "step_id": "analyze", "title": "Source review <not HTML>",
            "status": result["status"], "saved_analyses": result["saved_analyses"],
        }, {"step_id": "compose", "status": "failed"}],
    }


@pytest.mark.parametrize("options", [
    None, {"version": "analysis-options-v2", "mode": "source_observations"},
])
def test_failed_run_advertises_verified_analysis_without_mutating_the_producer(internal, options):
    result = analyze(internal, document_ids=["target-1"], analysis_options=options)
    original = deepcopy(result["saved_analyses"])
    descriptors = internal.saved.orchestration_analysis_descriptors(
        failed_run(result), user_id="owner", message_id="published-failure",
        load_result=internal.fixture.service.store.load_orchestration,
    )
    assert len(descriptors) == 1
    descriptor = descriptors[0]
    assert descriptor["message_id"] == "published-failure"
    assert descriptor["conversation_id"] == "conversation-1"
    assert descriptor["binding"]["run_id"] == "run-1"
    assert descriptor["binding"]["step_id"] == "analyze"
    assert descriptor["record_count"] == 2
    assert descriptor["source_count"] == 1
    assert descriptor["validation_status"] == "valid"
    assert descriptor["label"] == "Source review <not HTML>"
    assert "raw_analysis_items" not in json.dumps(descriptors)
    assert result["saved_analyses"] == original
    if options:
        assert descriptor["semantics"] == options


def test_partial_analysis_remains_partial_and_inspection_does_not_complete_the_run(internal):
    original = internal.model.response_builder

    def unsupported(prompt):
        payload = json.loads(original(prompt))
        payload["findings"][-1]["status"] = "unresolved"
        return json.dumps(payload)

    internal.model.response_builder = unsupported
    result = analyze(internal, document_ids=["target-1"])
    run = failed_run(result)
    descriptors = internal.saved.orchestration_analysis_descriptors(
        run, user_id="owner", message_id="published-failure",
        load_result=internal.fixture.service.store.load_orchestration,
    )
    assert descriptors[0]["validation_status"] == "partial"
    assert descriptors[0]["execution_status"] == "incomplete"
    assert descriptors[0]["record_count"] == 1
    assert run["status"] == "failed"
    assert result["task_result"].status == "partial"


@pytest.mark.parametrize("change", ["user", "run", "conversation", "step", "digest"])
def test_publication_rejects_wrong_identity_or_digest(internal, change):
    result = analyze(internal, document_ids=["target-1"])
    run = deepcopy(failed_run(result))
    descriptor = run["execution_steps"][0]["saved_analyses"][0]
    if change == "digest":
        descriptor["result_sha256"] = "0" * 64
    else:
        field = {"user": "user_id", "run": "run_id", "conversation": "conversation_id", "step": "step_id"}[change]
        descriptor["binding"][field] = "another-owner-or-producer"
    with pytest.raises(AnalysisResultUnavailable):
        internal.saved.orchestration_analysis_descriptors(
            run, user_id="owner", message_id="published-failure",
            load_result=internal.fixture.service.store.load_orchestration,
        )


def test_inspection_counts_come_from_the_immutable_manifest(internal):
    result = analyze(internal, document_ids=["target-1"])
    run = deepcopy(failed_run(result))
    descriptor = run["execution_steps"][0]["saved_analyses"][0]
    descriptor["record_count"] = 999
    descriptor["source_count"] = 999
    descriptors = internal.saved.orchestration_analysis_descriptors(
        run, user_id="owner", message_id="published-failure",
        load_result=internal.fixture.service.store.load_orchestration,
    )
    assert descriptors[0]["record_count"] == 2
    assert descriptors[0]["source_count"] == 1


def test_retry_advertises_the_original_authorized_checkpoint_producer(internal):
    result = analyze(internal, document_ids=["target-1"])
    run = failed_run(result)
    run["id"] = "retry-run"
    run["retry_of_run_id"] = "run-1"
    run["execution_steps"][0]["reused"] = True
    run["inherited_checkpoints"] = {
        "analyze": {"source_run_id": "run-1", "provenance": {"run_id": "run-1", "step_id": "analyze"}},
    }
    descriptors = internal.saved.orchestration_analysis_descriptors(
        run, user_id="owner", message_id="retry-answer",
        load_result=internal.fixture.service.store.load_orchestration,
    )
    assert descriptors[0]["binding"]["run_id"] == "run-1"
    assert descriptors[0]["message_id"] == "retry-answer"


def test_retry_rejects_provenance_for_a_different_step(internal):
    result = analyze(internal, document_ids=["target-1"])
    run = failed_run(result)
    run["id"] = "retry-run"
    run["retry_of_run_id"] = "run-1"
    run["execution_steps"][0]["reused"] = True
    run["inherited_checkpoints"] = {
        "analyze": {"source_run_id": "run-1", "provenance": {"run_id": "run-1", "step_id": "other-step"}},
    }
    with pytest.raises(AnalysisResultUnavailable):
        internal.saved.orchestration_analysis_descriptors(
            run, user_id="owner", message_id="retry-answer",
            load_result=internal.fixture.service.store.load_orchestration,
        )


def test_unrelated_prior_run_is_not_accepted_without_inherited_checkpoint_provenance(internal):
    result = analyze(internal, document_ids=["target-1"])
    run = failed_run(result)
    run["id"] = "another-run"
    run["execution_steps"][0]["reused"] = True
    with pytest.raises(AnalysisResultUnavailable):
        internal.saved.orchestration_analysis_descriptors(
            run, user_id="owner", message_id="another-answer",
            load_result=internal.fixture.service.store.load_orchestration,
        )


def test_uncommitted_analysis_is_not_advertised(internal):
    run = {
        "id": "run-1", "conversation_id": "conversation-1", "user_id": "owner",
        "execution_steps": [{"step_id": "analyze", "status": "running"}],
    }
    descriptors = internal.saved.orchestration_analysis_descriptors(
        run, user_id="owner", message_id="published-failure",
    )
    assert descriptors == []
