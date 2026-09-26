# test_analyze_orchestration_saved_integration.py
"""
Behavioral tests for saved Analyze references through orchestration.
Version: 0.261.139
Implemented in: 0.261.109
Single orchestration contract updated in: 0.261.139

Adapters, collection, section persistence/readers and checkpoint codecs are
production functions. Only provider, storage and source-access boundaries are
offline doubles; saved Analyze results are consumed through retained result
bindings instead of the removed legacy response path.
"""

import hashlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_analyze_backend_saved_integration import access, budget, model_budget, saved
from test_analyze_native_saved_integration import native_run  # noqa: F401  # imported by downstream tests
from test_orchestration_conversation_context import load_modules
from test_support.app_stubs import import_app_module
from test_support.orchestration_results import ResultFixture
from test_support.versioning import assert_app_version_at_least

from content_screening import access as screening_access
from functions_orchestration_result_contracts import ProducerIdentity


IMPLEMENTED_IN = "0.261.109"
SINGLE_CONTRACT_UPDATED_IN = "0.261.139"


class Sections:
    def __init__(self):
        self.contents = {}
        self.fail = False

    def save(self, user_id, conversation_id, run_id, step_id, section, **kwargs):
        if self.fail:
            raise OSError("offline persistence failure")
        payload = json.dumps(section, ensure_ascii=True, sort_keys=True)
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
        self.contents[(user_id, conversation_id, run_id, step_id, digest)] = payload
        return {"storage": "cosmos", "schema_version": 1, "sha256": digest, "size_bytes": len(payload)}

    def load(self, user_id, conversation_id, run_id, step_id, reference):
        return json.loads(self.contents[(
            user_id, conversation_id, run_id, step_id,
            reference["sha256"],
        )])


class StepCheckpoints:
    def __init__(self, token):
        self.token = token
        self.prepared = False
        self.cancelled = []

    def prepare(self):
        self.prepared = True

    def cancel(self, reason=None):
        self.cancelled.append(reason)


@pytest.fixture
def orchestration(monkeypatch):
    original_document_actions = sys.modules.get("functions_document_actions")
    modules = load_modules()
    modules.composition = import_app_module("functions_orchestration_composition")
    modules.schema = import_app_module("functions_orchestration_schema")
    checkpoints = import_app_module("functions_orchestration_checkpoints")
    store = Sections()
    state = {"allowed": True, "cancelled": False, "producer_calls": [], "model_calls": []}
    source = {
        "document_id": "source-1", "scope": "personal", "scope_id": "owner",
        "source_kind": "narrative", "source_version": "v1", "source_revision": "etag-1",
        "authorization_status": "authorized", "file_name": "controls.txt",
    }
    result = {
        "analysis_result_version": "analyze-final-v1",
        "analysis_reply": "## Findings\n\nThe saved review contains sixty findings.",
        "reply": "The saved review contains sixty findings.",
        "source_manifest": [source],
        "authoritative_result": {"kind": "records", "value": [{
            "record_id": f"finding-{index:03}", "document_id": "source-1",
            "values": {"finding": f"Complete finding {index:03}", "detail": "supported detail " * 70},
            "evidence_refs": [f"evidence-{index}"],
        } for index in range(60)]},
        "analysis_evidence": [{
            "evidence_id": f"evidence-{index}", "document_id": "source-1", "quote": f"Evidence {index}",
        } for index in range(60)],
        "analysis_validation": {
            "status": "valid",
            "coverage": {
                "status": "complete", "assigned_work_units": 60, "completed_work_units": 60,
                "failed_work_units": 0, "pending_work_units": 0,
                "assigned_sources": 1, "completed_sources": 1,
            },
            "limitations": ["Factual review was not independently performed."],
        },
        "coverage": {"documents": [{"document_id": "source-1", "total_windows": 1, "processed_windows": 1}]},
        "raw_analysis_items": [{"text": "RAW-WINDOW-DIAGNOSTIC-NOT-FINAL"}],
    }

    def resolve(ids, **kwargs):
        assert ids == ["source-1"]
        return [{**source, "authorization_status": "authorized" if state["allowed"] else "unresolved"}]

    def read_screening_document(document_id, user_id, **kwargs):
        if user_id != "owner" or document_id != "source-1" or not state["allowed"]:
            raise PermissionError("Fixture source access denied.")
        document = {"id": document_id, "user_id": user_id, "version": "v1"}
        if state.get("screening_held"):
            document["content_screening"] = {"state": "pending_review"}
        return document

    monkeypatch.setattr(screening_access, "_read_authorized_document", read_screening_document)

    def authorize_run(user_id, binding):
        assert user_id == "owner"
        assert binding == {
            "kind": "orchestration", "user_id": "owner", "conversation_id": "conversation-1",
            "run_id": "run-1", "step_id": "analyze-1",
        }

    def produce(*args, **kwargs):
        state["producer_calls"].append((args, kwargs))
        return deepcopy(result)

    original_save = saved.save_orchestration_analysis

    def save_result(value, **kwargs):
        kwargs["authorize_run"] = authorize_run
        kwargs["save_result"] = store.save
        kwargs["source_resolver"] = resolve
        return original_save(value, **kwargs)

    original_read = saved.load_orchestration_analysis_input

    def read_result(user_id, descriptor, **kwargs):
        kwargs["authorize_run"] = authorize_run
        kwargs["load_result"] = store.load
        kwargs["source_resolver"] = resolve
        return original_read(user_id, descriptor, **kwargs)

    results = ResultFixture()
    results.sources = {"source-1": {key: source[key] for key in ("document_id", "scope", "scope_id", "source_version", "source_revision")}}
    results.service.access.source_resolver = resolve
    results.service.access.source_metadata_reader = read_screening_document
    for producer in (
        ProducerIdentity("owner", "conversation-1", "run-1", 1, "analyze-1", "document_analyze", "analyze-final-v1"),
        ProducerIdentity("owner", "conversation-1", "run-1", 1, "answer", "compose", "compose-v1"),
    ):
        results.add_producer(producer)
    results.runs["run-1"].update(status="running", attempt_index=1)

    monkeypatch.setattr(saved, "save_orchestration_analysis", save_result)
    monkeypatch.setattr(saved, "load_orchestration_analysis_input", read_result)
    monkeypatch.setitem(sys.modules, "functions_document_analysis", SimpleNamespace(run_document_analysis=produce))
    monkeypatch.setitem(sys.modules, "functions_saved_analysis", saved)

    def invoke(messages, **kwargs):
        state["model_calls"].append((deepcopy(messages), kwargs))
        return "The complete saved findings were used."

    invoke.model_metadata = {"modelName": "selected-offline-model"}
    invoke.provider = "aoai"
    invoke.output_tokens = 4096
    monkeypatch.setattr(budget, "resolve_model_token_budget", lambda *args, **kwargs: model_budget({
        "context_window_tokens": 200000, "max_input_tokens": None, "max_output_tokens": 4096,
        "tokenizer": None, "source": "configured", "model_id": "selected-offline-model", "status": "known",
    }))

    context = modules.executor.RunContext(
        run_id="run-1", attempt_index=1, conversation_id="conversation-1", user_id="owner",
        invoke_prompt=invoke, user_message="Explain the review.", resolve_source_manifest=resolve,
        result_service=results.service,
        result_guard_token_for_step=lambda step_id: getattr(context, "_guard_token", "server-attempt-token"),
        result_input_fingerprint_for_step=lambda step_id: "a" * 64,
    )

    def checkpoint_factory(step_id):
        context._guard_token = getattr(context, "_guard_token", "server-attempt-token")
        return StepCheckpoints(context._guard_token)

    context.analysis_checkpoint_factory = checkpoint_factory
    yield SimpleNamespace(
        modules=modules, checkpoints=checkpoints, store=store, state=state,
        context=context, result=result, source=source, read=read_result, results=results,
    )
    if original_document_actions is None:
        sys.modules.pop("functions_document_actions", None)
    else:
        sys.modules["functions_document_actions"] = original_document_actions


def analyze(fixture):
    return fixture.modules.adapters.run_document_analyze(
        {"step_id": "analyze-1", "capability_id": "document_analyze", "arguments": {"document_ids": ["source-1"], "analysis_prompt": "Find risks."}},
        fixture.context, settings={}, user_id="owner", emit=None,
        cancel_requested=lambda: fixture.state["cancelled"],
    )


def bind_result(fixture, result):
    if result.get("task_result") is not None:
        fixture.context.task_results["analyze-1"] = result["task_result"]
    fixture.context.saved_analyses.extend(result.get("saved_analyses") or [])


def compose(fixture):
    step = {
        "step_id": "answer", "capability_id": "compose", "role": "reason",
        "enabled": True, "depends_on": ["analyze-1"],
        "arguments": {"instruction": "Explain the retained Analyze result.", "knowledge_basis": "sources"},
        "inputs": {"findings": {"binding": {
            "version": "orchestration-input-binding-v1", "step_id": "analyze-1",
            "output_name": "findings", "existing_result": None,
        }, "allow_partial": False}},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    }
    return fixture.modules.composition.adapter_compose(
        step, fixture.context, settings={}, user_id="owner", emit=None,
        cancel_requested=lambda: fixture.state["cancelled"],
    )


def test_version_includes_single_contract_update():
    assert_app_version_at_least(IMPLEMENTED_IN)
    assert_app_version_at_least(SINGLE_CONTRACT_UPDATED_IN)


def test_orchestration_keeps_full_data_in_saved_sections_not_evidence_or_checkpoints(orchestration):
    fixture = orchestration
    result = analyze(fixture)
    assert result["status"] == "completed", result
    descriptor = result["saved_analyses"][0]
    assert descriptor["binding"]["step_id"] == "analyze-1"
    assert descriptor["record_count"] == 60
    producer_arguments = fixture.state["producer_calls"][0][1]
    assert producer_arguments["result_version"] == "analyze-final-v1"
    assert producer_arguments["source_manifest"] == [fixture.source]
    bind_result(fixture, result)
    state = fixture.checkpoints.context_state(fixture.context)
    assert state["saved_analyses"] == []
    assert "finding-059" not in json.dumps(state)
    fixture.result["authoritative_result"]["value"] = []
    answer = compose(fixture)
    assert answer["status"] == "completed", answer
    submitted = json.dumps(fixture.state["model_calls"][0][0])
    assert "finding-059" in submitted and "Complete finding 059" in submitted
    assert "RAW-WINDOW-DIAGNOSTIC" not in submitted
    assert fixture.state["model_calls"][0][1]["metadata"]["complete_named_inputs"] is True
    assert len(fixture.state["producer_calls"]) == 1


def test_orchestration_source_revocation_blocks_saved_compose(orchestration):
    fixture = orchestration
    bind_result(fixture, analyze(fixture))
    fixture.state["allowed"] = False
    with pytest.raises(Exception) as failure:
        compose(fixture)
    assert type(failure.value).__name__ in {"AnalysisResultUnavailable", "ResultUnavailableError"}
    assert fixture.state["model_calls"] == []


def test_orchestration_new_screening_hold_blocks_saved_compose(orchestration):
    fixture = orchestration
    bind_result(fixture, analyze(fixture))
    fixture.state["screening_held"] = True
    with pytest.raises(Exception) as failure:
        compose(fixture)
    assert type(failure.value).__name__ in {"DocumentHeldError", "ResultUnavailableError"}
    assert fixture.state["model_calls"] == []


def test_orchestration_save_failure_is_not_completed_evidence(orchestration):
    fixture = orchestration
    fixture.store.fail = True
    result = analyze(fixture)
    assert result["status"] == "failed"
    assert not result.get("saved_analyses")
    assert result["evidence"] == []
    assert "analyze-1" not in fixture.context.task_results


def test_orchestration_model_boundary_blocks_oversized_saved_records(monkeypatch):
    execution = import_app_module("functions_orchestration_execution")
    limits = {
        "context_window_tokens": 1024, "max_input_tokens": None, "max_output_tokens": 512,
        "tokenizer": None, "source": "catalog", "model_id": "chosen-small-model", "status": "known",
    }
    monkeypatch.setattr(execution, "calculate_workflow_context_budget", lambda *args, **kwargs: {
        **limits, "decision": "too_large", "truncated": False,
        "input_tokens": 2000, "input_budget_tokens": 512,
    })
    calls = []
    model = SimpleNamespace(
        deployment="chosen-deployment", provider="aoai", behavior_name="chosen-model",
        response_length=256, model_metadata={"id": "chosen-small-model"},
        create_completion=lambda **kwargs: calls.append(kwargs),
    )
    invoke = execution.build_harness_invoke_prompt(model, token_usage={}, revalidate=lambda: None)
    with pytest.raises(budget.WorkflowContextBudgetError):
        invoke(
            [{"role": "system", "content": "Explain saved data."}, {"role": "user", "content": "record" * 2000}],
            stage="orchestration_compose", metadata={"complete_saved_analysis_input": True},
        )
    assert calls == []
    assert invoke.context_budget["model_id"] == "chosen-small-model"
    assert invoke.context_budget["truncated"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
