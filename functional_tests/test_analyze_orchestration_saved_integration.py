# test_analyze_orchestration_saved_integration.py
"""
Behavioral tests for saved Analyze references through orchestration.
Version: 0.261.109
Implemented in: 0.261.109

Adapters, collection, section persistence/readers and checkpoint codecs are
production functions. Only provider, storage and source-access boundaries are
offline doubles; no displayed assistant message is fabricated for the reader.
"""

import hashlib
import json
import logging
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_analyze_backend_saved_integration import access, budget, load_functions, mixed, saved
from test_analyze_native_saved_integration import native_run
from test_orchestration_conversation_context import load_modules
from test_support.app_stubs import import_app_module


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


@pytest.fixture
def orchestration(monkeypatch):
    original_document_actions = sys.modules.get("functions_document_actions")
    modules = load_modules()
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
        "analysis_validation": {"status": "valid", "limitations": ["Factual review was not independently performed."]},
        "coverage": {"documents": [{"document_id": "source-1", "total_windows": 1, "processed_windows": 1}]},
        "raw_analysis_items": [{"text": "RAW-WINDOW-DIAGNOSTIC-NOT-FINAL"}],
    }

    def resolve(ids, **kwargs):
        assert ids == ["source-1"]
        return [{**source, "authorization_status": "authorized" if state["allowed"] else "unresolved"}]

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
        return original_save(
            value, **kwargs, authorize_run=authorize_run, save_result=store.save, source_resolver=resolve,
        )

    original_read = saved.load_orchestration_analysis_input

    def read_result(user_id, descriptor, **kwargs):
        return original_read(
            user_id, descriptor, authorize_run=authorize_run, load_result=store.load,
            source_resolver=resolve, **kwargs,
        )

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
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda *args, **kwargs: {
        "context_window_tokens": 200000, "max_input_tokens": None, "max_output_tokens": 4096,
        "tokenizer": None, "source": "configured", "model_id": "selected-offline-model", "status": "known",
    })
    context = modules.executor.RunContext(
        run_id="run-1", conversation_id="conversation-1", user_id="owner",
        invoke_prompt=invoke, user_message="Explain the review.", resolve_source_manifest=resolve,
    )
    yield SimpleNamespace(
        modules=modules, checkpoints=checkpoints, store=store, state=state,
        context=context, result=result, source=source, read=read_result,
    )
    if original_document_actions is None:
        sys.modules.pop("functions_document_actions", None)
    else:
        sys.modules["functions_document_actions"] = original_document_actions


def analyze(fixture):
    return fixture.modules.adapters.run_document_analyze(
        {"step_id": "analyze-1", "arguments": {"document_ids": ["source-1"], "analysis_prompt": "Find risks."}},
        fixture.context, settings={}, user_id="owner", emit=None,
        cancel_requested=lambda: fixture.state["cancelled"],
    )


def respond(fixture):
    return fixture.modules.adapters.run_respond(
        {"step_id": "respond-1", "arguments": {}}, fixture.context,
        settings={}, user_id="owner", emit=None, cancel_requested=lambda: fixture.state["cancelled"],
    )


def test_orchestration_keeps_full_data_in_saved_sections_not_evidence_or_checkpoints(orchestration):
    fixture = orchestration
    result = analyze(fixture)
    assert result["status"] == "completed", result
    descriptor = result["saved_analyses"][0]
    assert descriptor["binding"]["step_id"] == "analyze-1"
    assert "message_id" not in descriptor
    assert "workflow_id" not in descriptor["binding"]
    assert descriptor["record_count"] == 60
    producer_arguments = fixture.state["producer_calls"][0][1]
    assert producer_arguments["result_version"] == "analyze-final-v1"
    assert producer_arguments["source_manifest"] == [fixture.source]
    fixture.context.merge_step_result(result, step_id="analyze-1")
    state = fixture.checkpoints.context_state(fixture.context)
    assert state["saved_analyses"] == [descriptor]
    assert "finding-059" not in json.dumps(state)
    fixture.store.contents = deepcopy(fixture.store.contents)
    fixture.result["authoritative_result"]["value"] = []
    answer = respond(fixture)
    assert answer["status"] == "completed", answer
    submitted = json.dumps(fixture.state["model_calls"][0][0])
    assert "finding-059" in submitted and "Complete finding 059" in submitted
    assert "RAW-WINDOW-DIAGNOSTIC" not in submitted
    assert fixture.state["model_calls"][0][1]["metadata"]["complete_saved_analysis_input"] is True
    assert "not independently rechecked" in answer["message"]
    respond(fixture)
    assert len(fixture.state["producer_calls"]) == 1


def test_orchestration_source_revocation_blocks_whole_saved_answer(orchestration):
    fixture = orchestration
    fixture.context.merge_step_result(analyze(fixture), step_id="analyze-1")
    fixture.state["allowed"] = False
    answer = respond(fixture)
    assert answer["status"] == "failed"
    assert "unavailable" in answer["summary"].lower()
    assert fixture.state["model_calls"] == []
    assert "Complete finding" not in json.dumps(answer)


def test_orchestration_save_failure_is_not_completed_evidence(orchestration):
    fixture = orchestration
    fixture.store.fail = True
    result = analyze(fixture)
    assert result["status"] == "failed"
    assert not result.get("saved_analyses")
    assert result["evidence"] == []


def test_legacy_checkpoint_state_and_fingerprint_stay_identical_without_references(orchestration):
    fixture = orchestration
    context = fixture.context
    checkpoints = fixture.checkpoints
    legacy_state = {key: deepcopy(getattr(context, key)) for key in checkpoints.STATE_FIELDS}
    assert checkpoints.context_state(context) == legacy_state
    plan = {"steps": [{"step_id": "respond", "capability_id": "respond", "arguments": {}}]}
    expected_binding = checkpoints.fingerprint({
        "plan": checkpoints.effective_plan(plan),
        "inputs": {key: getattr(context, key, None) for key in checkpoints.INPUT_FIELDS},
        "model": {key: None for key in ("model_id", "endpoint_id", "provider", "model_deployment")},
        "memory_digest": checkpoints.fingerprint({}), "agent_catalog_digest": checkpoints.fingerprint([]),
        "action_catalog_digest": checkpoints.fingerprint([]), "settings_digest": checkpoints.fingerprint({}),
    })
    assert checkpoints.context_binding(context, plan, {}) == expected_binding
    result = analyze(fixture)
    context.merge_step_result(result, step_id="analyze-1")
    reference_state = checkpoints.context_state(context)
    restored = fixture.modules.executor.RunContext()
    checkpoints.restore_context(restored, {"state": reference_state})
    assert restored.saved_analyses == context.saved_analyses
    checkpoints.restore_context(restored, {"state": legacy_state})
    assert restored.saved_analyses == []


def test_pending_native_analysis_is_not_synthesized_as_a_completed_dataset(orchestration):
    fixture = orchestration
    adapters = fixture.modules.adapters
    assert adapters._tabular_evidence_status("queued", "Working", [{"background_export": True}]) == "pending"
    assert adapters._tabular_evidence_status("foreground", "A result", []) == "completed"
    envelope = mixed.build_evidence_envelope(
        document_id="source-1", source_kind="tabular", engine=mixed.EVIDENCE_ENGINE_TABULAR_TOOLS,
        status="pending", summary="Still processing", coverage={"terminal": False},
    )
    fixture.context.evidence = [envelope]
    result = respond(fixture)
    assert "still processing" in result["message"]
    assert fixture.state["model_calls"] == []


def test_orchestration_model_boundary_blocks_oversized_saved_records(monkeypatch):
    limits = {
        "context_window_tokens": 1024, "max_input_tokens": None, "max_output_tokens": 512,
        "tokenizer": None, "source": "catalog", "model_id": "chosen-small-model", "status": "known",
    }
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda *args, **kwargs: limits)
    calls = []
    model = SimpleNamespace(
        deployment="chosen-deployment", provider="aoai", behavior_name="chosen-model",
        response_length=256, model_metadata={"id": "chosen-small-model"},
        create_completion=lambda **kwargs: calls.append(kwargs),
    )
    namespace = {
        "calculate_workflow_context_budget": budget.calculate_workflow_context_budget,
        "WorkflowContextBudgetError": budget.WorkflowContextBudgetError,
        "ANSWER_MAX_TOKENS": 4000, "REASONING_COMPLETION_BUDGET": 8192,
    }
    load_functions("route_backend_orchestration.py", {"_build_invoke_prompt"}, namespace)
    invoke = namespace["_build_invoke_prompt"]({}, model=model)
    with pytest.raises(budget.WorkflowContextBudgetError):
        invoke(
            [{"role": "system", "content": "Explain saved data."}, {"role": "user", "content": "record" * 2000}],
            stage="orchestration_respond", metadata={"complete_saved_analysis_input": True},
        )
    assert calls == []
    assert invoke.context_budget["model_id"] == "chosen-small-model"
    assert invoke.context_budget["truncated"] is False


def test_orchestration_respond_pages_all_records_without_a_second_source_pass(orchestration, monkeypatch):
    fixture = orchestration
    fixture.context.merge_step_result(analyze(fixture), step_id="analyze-1")
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda *args, **kwargs: {
        "context_window_tokens": 16000, "max_input_tokens": 16000, "max_output_tokens": 2048,
        "tokenizer": None, "source": "configured", "model_id": "selected-offline-model", "status": "known",
    })
    seen = []

    def invoke(messages, **kwargs):
        fixture.state["model_calls"].append((messages, kwargs))
        data = json.loads(messages[-1]["content"].split("[Saved Analyze result — complete data]\n", 1)[1])
        if "records" in data:
            seen.extend(record["record_id"] for record in data["records"])
            return json.dumps({"record_explanations": [{
                "record_ref": record["record_ref"], "text": record["values"]["finding"],
            } for record in data["records"]]})
        return json.dumps({"conclusions": []})

    invoke.model_metadata = {"id": "selected-offline-model", "responseLength": 2048}
    fixture.context.invoke_prompt = invoke
    answer = respond(fixture)
    assert answer["status"] == "completed", answer
    assert answer["analysis_consumption"]["record_count"] == 60
    assert answer["analysis_consumption"]["mode"] == "record_pages"
    assert len(seen) == len(set(seen)) == 60
    assert len(fixture.state["producer_calls"]) == 1


@pytest.mark.parametrize("native_status,step_status", [("completed", "completed"), ("queued", "pending")])
def test_orchestration_native_output_is_saved_through_the_real_adapter(
    orchestration, native_run, monkeypatch, native_status, step_status,
):
    fixture = orchestration
    fixture.source.update({
        **native_run.source, "document_id": "source-1", "scope_id": "owner",
    })
    native_run.source.update(fixture.source)
    native_run.run.update(user_id="owner", status=native_status)
    monkeypatch.setitem(sys.modules, "functions_tabular_analysis", SimpleNamespace(
        orchestrate_tabular_request=lambda *args, **kwargs: {"generated_output_metadata": {
            "run_id": "native-run", "export_run_id": "native-run", "status": native_status,
        }},
    ))
    result = fixture.modules.adapters.run_tabular_analyze(
        {"step_id": "analyze-1", "arguments": {"document_ids": ["source-1"], "question": "Read the inventory."}},
        fixture.context, settings={}, user_id="owner", emit=None, cancel_requested=lambda: False,
    )
    assert result["status"] == step_status, result
    assert result["saved_analyses"][0]["record_count"] == (150 if native_status == "completed" else 0)
    fixture.context.merge_step_result(result, step_id="analyze-1")
    answer = respond(fixture)
    if native_status == "queued":
        assert fixture.state["model_calls"] == [] and "still processing" in answer["message"]
    else:
        assert answer["status"] == "completed"
        assert "Complete output row 149" in json.dumps(fixture.state["model_calls"])
        assert len(native_run.reads) == 3
    assert fixture.state["producer_calls"] == []
