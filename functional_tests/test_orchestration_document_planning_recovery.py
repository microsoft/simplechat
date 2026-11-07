# test_orchestration_document_planning_recovery.py
#!/usr/bin/env python3
"""
Functional regressions for picked-document planning and debug diagnostics.
Version: 0.261.419
Implemented in: 0.261.413
Server-owned Auto handoff integration: 0.261.415
Shared draft-contract recovery integration: 0.261.419

Real authenticated routes, source metadata, planner, validation and logger
serialization run with external model/storage I/O isolated. Diagnostics must
identify source loss and invalid Analyze declarations without private payloads.
"""

import hashlib
import importlib
import io
import json
import logging
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
from flask import Response
from jsonschema import Draft202012Validator
from openai import APITimeoutError
from openpyxl import Workbook

from test_orchestration_source_kind_planning import (
    LEFT, RIGHT, candidates, enrich, modules, real_http_harness, source_runtime,
)
from test_support.orchestration_harness_execution import compose_step, input_binding


__all__ = ["modules", "real_http_harness", "source_runtime"]
DIAGNOSTIC_MESSAGES = {
    "[ORCHESTRATION_PLANNER] Planning diagnostic.",
    "[ORCHESTRATION_PLANNER] Source binding diagnostic.",
    "[ORCHESTRATION_PLANNER] Step binding diagnostic.",
}
PRIVATE = "PRIVATE_DOCUMENT_PROMPT_OR_PROVIDER_VALUE"
OPTIONS = {"version": "analysis-options-v2", "mode": "source_observations"}


@pytest.fixture
def planning(source_runtime, monkeypatch):
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.orchestration.document_planning")
    flags = {"enable_debug_logging": True}
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: flags)
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    source_runtime.telemetry = telemetry
    source_runtime.logger = logger
    source_runtime.debug_flags = flags
    return source_runtime


def proposal(document_ids=(), *, capability="document_search", options=None):
    producer = {
        "step_id": "read", "capability_id": capability,
        "arguments": {"document_ids": list(document_ids)},
    }
    if capability == "document_analyze":
        producer["arguments"]["analysis_prompt"] = PRIVATE
        if options is not None:
            producer["arguments"]["analysis_options"] = deepcopy(options)
        output = "findings"
    elif capability == "tabular_inspect":
        output = "inspection"
    else:
        producer["arguments"]["query"] = PRIVATE
        output = "prepared"
    answer = compose_step("answer", inputs={
        "source": {"binding": input_binding("read", output), "allow_partial": False},
    } if document_ids else {})
    answer["arguments"].update(
        instruction=PRIVATE, knowledge_basis="sources" if document_ids else "general_knowledge",
    )
    answer["delivers"] = ["answer"]
    return {
        "kind": "plan",
        "deliverables": [{
            "id": "answer", "kind": "answer", "requested": "explicit",
            "description": "Answer from the selected sources.", "status": "planned",
        }],
        "steps": [producer, answer] if document_ids else [answer],
        "final_response": input_binding("answer"),
    }


def run_plan(
    runtime, replies, *, identifiers=(LEFT,), context_updates=None, seed_updates=None,
    message=PRIVATE, **options,
):
    harness = runtime.harness
    selected, seeds = candidates(runtime, identifiers)
    seeds.update(seed_updates or {})
    offered = enrich(runtime, selected, seeds)
    context = runtime.context.build_planner_context(message, candidates=offered, seeds=seeds)
    context.update(context_updates or {})
    harness.replies = [json.dumps(reply) if isinstance(reply, dict) else reply for reply in replies]
    return harness.planner.plan_request(
        message, context, "conversation-1", "owner",
        settings=harness.settings, seeds=seeds, authorized_document_ids=list(identifiers),
        turn_id="document-planning-turn", request_context=harness.services().capability_request_bindings(),
        **options,
    )


def diagnostic_records(caplog, *, stage=None, message=None):
    return [
        record for record in caplog.records
        if getattr(record, "sc_message", None) in DIAGNOSTIC_MESSAGES
        and (stage is None or getattr(record, "sc_stage", None) == stage)
        and (message is None or record.sc_message == message)
    ]


def serialized_records(records):
    return json.dumps([
        {name: value for name, value in record.__dict__.items() if name.startswith("sc_")}
        for record in records
    ])


@pytest.mark.parametrize("debug", [False, True])
def test_debug_diagnostics_identify_model_omission_in_both_sinks(planning, caplog, capsys, debug):
    planning.debug_flags["enable_debug_logging"] = debug
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        with pytest.raises(planning.harness.planner.PlannerError):
            run_plan(planning, [proposal(), proposal()])
    records = diagnostic_records(caplog)
    assert bool(records) is debug
    if debug:
        initial = diagnostic_records(caplog, stage="planner_input", message="[ORCHESTRATION_PLANNER] Planning diagnostic.")[0]
        assert initial.sc_remaining_corrections == 1
        summaries = [
            record for record in diagnostic_records(caplog, stage="plan_normalized")
            if record.sc_message == "[ORCHESTRATION_PLANNER] Planning diagnostic."
        ]
        assert summaries
        assert all(record.sc_selected_document_count == record.sc_missing_document_count == 1 for record in summaries)
        assert all(record.sc_used_document_count == record.sc_normalization_lost_document_count == 0 for record in summaries)
        source = diagnostic_records(caplog, stage="plan_proposal", message="[ORCHESTRATION_PLANNER] Source binding diagnostic.")[0]
        assert source.sc_document_id_hash == hashlib.sha256(LEFT.encode()).hexdigest()
        assert source.sc_selected is True and source.sc_used is False
        failure = next(
            record for record in reversed(caplog.records)
            if getattr(record, "sc_message", None) == "[ORCHESTRATION_PLANNER] The request could not be planned."
        )
        assert failure.sc_validation_rule == "selected_documents_missing"
        assert failure.sc_attempt >= 1
    else:
        assert any(
            getattr(record, "sc_message", None) == "[ORCHESTRATION_PLANNER] The request could not be planned."
            for record in caplog.records
        )
    console = capsys.readouterr().out
    assert ("Source binding diagnostic." in console) is debug
    assert PRIVATE not in console + serialized_records(records)


def test_debug_options_show_exact_owner_rule_before_defaulting(planning, caplog, capsys):
    invalid = proposal([LEFT], capability="document_analyze", options={"mode": "source_observations"})
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        with pytest.raises(planning.harness.planner.PlannerError):
            run_plan(planning, [invalid, invalid])
    steps = diagnostic_records(caplog, stage="plan_proposal", message="[ORCHESTRATION_PLANNER] Step binding diagnostic.")
    analysis = next(record for record in steps if record.sc_capability_id == "document_analyze")
    assert analysis.sc_options_mode_observations is True
    assert analysis.sc_options_version_present is False
    rejected = diagnostic_records(caplog, stage="plan_normalization", message="[ORCHESTRATION_PLANNER] Planning diagnostic.")
    assert rejected[-1].sc_validation_rule == "version_mode_mismatch"
    console = capsys.readouterr().out
    assert PRIVATE not in console + serialized_records(diagnostic_records(caplog))


def test_diagnostic_hashes_survive_serialization_without_expanding_text_allowlists(planning):
    fingerprint = hashlib.sha256(PRIVATE.encode()).hexdigest()
    for key in ("document_id_hash", "planner_binding_hash", "document_set_hash", "consumer_run_id_hash"):
        valid = planning.telemetry._build_logger_extra("Diagnostic", {key: fingerprint})
        invalid = planning.telemetry._build_logger_extra("Diagnostic", {key: PRIVATE})
        assert valid[f"sc_{key}"] == fingerprint
        assert f"sc_{key}" not in invalid
        assert PRIVATE not in json.dumps(invalid)
    private = planning.telemetry._build_logger_extra("Diagnostic", {
        "filename": PRIVATE, "analysis_options": {"mode": PRIVATE}, "documents": [PRIVATE],
    })
    assert PRIVATE not in json.dumps(private)


def test_debug_snapshot_bounds_are_explicit(planning, caplog):
    identifiers = tuple(f"document-{index}" for index in range(101))
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        with pytest.raises(planning.harness.planner.PlannerError):
            run_plan(planning, [proposal(), proposal()], identifiers=identifiers)
    summary = diagnostic_records(caplog, stage="plan_proposal", message="[ORCHESTRATION_PLANNER] Planning diagnostic.")[0]
    assert summary.sc_selected_document_count == summary.sc_missing_document_count == 101
    assert summary.sc_omitted_document_count == 101 - planning.harness.planner.PLANNER_DEBUG_MAX_ITEMS
    sources = diagnostic_records(caplog, stage="plan_proposal", message="[ORCHESTRATION_PLANNER] Source binding diagnostic.")
    first = [record for record in sources if record.sc_attempt == 1]
    assert len(first) == planning.harness.planner.PLANNER_DEBUG_MAX_ITEMS


@pytest.mark.parametrize("options,rule", [
    ({"mode": "source_observations"}, "version_mode_mismatch"),
    ({"version": "analysis-options-v2", "mode": "narrative_findings"}, "supported_mode_required"),
    ({"version": "analysis-options-v2"}, "supported_mode_required"),
    ({"version": PRIVATE}, "unsupported_options_version"),
    ({**OPTIONS, "required_fields": [PRIVATE]}, "observation_requirements_conflict"),
    ({**OPTIONS, "required_fields": [" "]}, "required_fields_invalid"),
    ({**OPTIONS, PRIVATE: PRIVATE}, "unsupported_option_fields"),
    ({**OPTIONS, "transformation_spec": PRIVATE}, "calculation_rules_object_required"),
    ({**OPTIONS, "transformation_spec": {"fields": [PRIVATE]}}, "calculation_rules_invalid"),
    ({**OPTIONS, "transformation_spec": None}, "analysis_options_schema_invalid"),
    ([PRIVATE], "options_object_required"),
])
def test_invalid_analyze_options_are_corrected_once_with_owner_rule(planning, caplog, options, rule):
    invalid = proposal([LEFT], capability="document_analyze", options=options)
    valid = proposal([LEFT], capability="document_analyze", options=OPTIONS)
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(planning, [invalid, valid])
    assert kind == "plan"
    assert len(planning.harness.model_calls) == 2
    assert {call["model"] for call in planning.harness.model_calls} == {"gpt-4o"}
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert plan["steps"][0]["arguments"]["analysis_options"]["mode"] == "source_observations"
    rejected = next(
        record for record in caplog.records
        if getattr(record, "sc_message", None) == "[ORCHESTRATION_PLANNER] Asking the planner to correct a rejected plan."
    )
    assert rejected.sc_validation_code == "analysis_options_invalid"
    assert rejected.sc_validation_rule == rule
    assert rejected.sc_attempt == 1
    assert "PRIVATE_" not in serialized_records(diagnostic_records(caplog))


@pytest.mark.parametrize("options", [
    {}, {"version": "analysis-options-v1"}, {"mode": "narrative_findings"},
    {"version": "analysis-options-v1", "mode": "narrative_findings", "required_fields": ["amount"]},
    OPTIONS, {**OPTIONS, "required_fields": [], "transformation_spec": {}},
    {"version": "analysis-options-v2", "mode": "reconciled_records", "required_fields": ["amount"]},
])
def test_previously_valid_analyze_options_remain_valid(planning, options):
    registry = importlib.import_module("functions_orchestration_registry")
    normalizer = importlib.import_module("functions_document_analysis_results")
    normalized = normalizer.normalize_analysis_options(options)
    schema_valid = Draft202012Validator(
        registry.get_capability("document_analyze")["inputs"]["properties"]["analysis_options"],
    ).is_valid(options)
    assert schema_valid is True
    kind, plan = run_plan(planning, [proposal([LEFT], capability="document_analyze", options=options)])
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert plan["steps"][0]["arguments"]["analysis_options"] == normalized
    context = json.loads(planning.harness.model_calls[0]["messages"][1]["content"])
    assert "document_analyze" in {capability["id"] for capability in context["capabilities"]}


@pytest.mark.parametrize("options", [
    {"mode": "source_observations"},
    {"version": "analysis-options-v1", "mode": "reconciled_records"},
    {"version": "analysis-options-v2", "mode": "narrative_findings"},
    {"version": "analysis-options-v2"},
    {**OPTIONS, "required_fields": ["amount"]},
    {**OPTIONS, "transformation_spec": {"fields": []}},
])
def test_advertised_analyze_schema_rejects_incompatible_semantics(planning, options):
    registry = importlib.import_module("functions_orchestration_registry")
    schema = registry.get_capability("document_analyze")["inputs"]["properties"]["analysis_options"]
    schema_valid = Draft202012Validator(schema).is_valid(options)
    assert schema_valid is False


@pytest.mark.parametrize("extension", ["png", "pdf", "docx", "csv", "xlsx"])
@pytest.mark.parametrize("approval", ["manual", "auto"])
def test_http_picked_document_recovery_preserves_scope_and_does_not_execute(
    planning, modules, monkeypatch, caplog, extension, approval,
):
    """Planning stays side-effect free; only approved Auto plans hand off afterward."""
    harness = planning.harness
    documents = harness.config.cosmos_user_documents_container
    record = documents.read_item(LEFT, LEFT)
    record["file_name"] = f"selected.{extension}"
    documents.upsert_item(record)
    if extension == "xlsx":
        book = Workbook()
        book.active.append(["Code", "Amount"])
        book.active.append(["001", 25])
        content = io.BytesIO()
        book.save(content)
        book.close()
        harness.blobs.records[("PRIVATE_CONTAINER", "PRIVATE_PATH")]["data"] = content.getvalue()
    execute = Mock(side_effect=AssertionError("Planning must not execute a step."))
    monkeypatch.setattr(harness.execution, "prepare_harness_execution", execute)
    handoff = Mock(return_value=Response(mimetype="text/event-stream"))
    monkeypatch.setattr(modules.route, "_prepare_execution_stream", handoff)
    adapters = importlib.import_module("functions_orchestration_adapters")
    monkeypatch.setitem(adapters.ADAPTER_REGISTRY, "document_analyze", execute)
    request = "Answer the question using only the selected file."
    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": request, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal()),
        json.dumps(proposal([LEFT])),
    ]
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        response = planning.client.post("/api/v2/orchestration/plan", json={
            "conversation_id": "conversation-1", "turn_id": "picked-document-turn",
            "message": request, "selected_document_ids": [LEFT],
            "context_documents": [{"id": LEFT, "label": "Not an authoritative file type"}],
            "approval_mode": approval,
        }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2])
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    assert response.status_code == 200 and "plan" in frames[-1], frames
    plan = frames[-1]["plan"]
    calls = [
        call for call in harness.model_calls
        if call["messages"][0]["content"].startswith("Plan bounded work")
    ]
    assert len(calls) == 2
    if extension in ("csv", "xlsx"):
        context = json.loads(calls[0]["messages"][1]["content"])
        inspection = context["selected_sources"][0]["inspection"]
        assert inspection["status"] == "inspected"
        assert inspection["tables"][0]["columns"] == ["Code", "Amount"]
        assert inspection["tables"][0]["sample_rows"]
        assert inspection["content_complete"] is False
    assert plan["approval"]["mode"] == approval
    assert harness.schema.effective_plan_document_ids(plan, {"document_ids": [LEFT]}) == [LEFT]
    assert plan["steps"][0]["capability_id"] == "document_search"
    assert handoff.call_count == (1 if approval == "auto" else 0)
    if approval == "auto":
        admitted = handoff.call_args.args[0]
        assert admitted["id"] == plan["run_id"]
        assert harness.schema.effective_plan_document_ids(admitted["plan"], {"document_ids": [LEFT]}) == [LEFT]
    assert execute.call_count == 0
    assert harness.blobs.file_uploads == 0 and harness.assistant_messages() == []
    summary = diagnostic_records(caplog, stage="plan_validated", message="[ORCHESTRATION_PLANNER] Planning diagnostic.")[-1]
    assert summary.sc_selected_document_count == summary.sc_used_document_count == 1
    assert summary.sc_missing_document_count == 0


@pytest.mark.parametrize("first,second,stage", [
    ("options", "selection", "selected_requirements"),
    ("selection", "options", "plan_normalization"),
    ("selection", "selection", "selected_requirements"),
    ("options", "options", "plan_normalization"),
])
def test_every_failure_path_shares_exactly_one_correction(planning, caplog, first, second, stage):
    bad = {
        "options": proposal([LEFT], capability="document_analyze", options={"mode": "source_observations"}),
        "selection": proposal(),
    }
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        with pytest.raises(planning.harness.planner.PlannerError) as failure:
            run_plan(planning, [bad[first], bad[second], proposal([LEFT])])
    assert len(planning.harness.model_calls) == 2
    assert len(planning.harness.replies) == 1
    assert "PRIVATE_" not in str(failure.value)
    expected_message = "selected" if second == "selection" else "document-analysis"
    assert expected_message in str(failure.value)
    terminal = next(
        record for record in reversed(caplog.records)
        if getattr(record, "sc_message", None) == "[ORCHESTRATION_PLANNER] The request could not be planned."
    )
    assert terminal.sc_attempt == 2 and terminal.sc_stage == stage


def test_unavailable_capabilities_are_not_made_repairable(planning):
    invalid = proposal([LEFT])
    invalid["steps"][0]["capability_id"] = "unavailable_capability"
    with pytest.raises(planning.harness.planner.PlannerError):
        run_plan(planning, [invalid, proposal([LEFT])])
    assert len(planning.harness.model_calls) == 1
    assert len(planning.harness.replies) == 1


def test_partial_mixed_source_omission_is_corrected_without_dropping_either_file(planning):
    kind, plan = run_plan(
        planning, [proposal([LEFT]), proposal([LEFT, RIGHT])], identifiers=(LEFT, RIGHT),
    )
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert set(planning.harness.schema.plan_document_ids(plan)) == {LEFT, RIGHT}


def test_implicit_search_scope_keeps_every_selected_document_without_a_retry(planning):
    raw = proposal([LEFT])
    raw["steps"][0]["arguments"].pop("document_ids")
    kind, plan = run_plan(planning, [raw], identifiers=(LEFT, RIGHT))
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert planning.harness.schema.effective_plan_document_ids(
        plan, {"document_ids": [LEFT, RIGHT]},
    ) == [LEFT, RIGHT]


def test_a_disabled_read_does_not_satisfy_a_selected_document(planning):
    raw = proposal()
    disabled = proposal([LEFT])["steps"][0]
    disabled["enabled"] = False
    raw["steps"].insert(0, disabled)
    kind, plan = run_plan(planning, [raw, proposal([LEFT])])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert planning.harness.schema.plan_document_ids(plan) == [LEFT]


def test_source_free_request_does_not_gain_an_analyze_step(planning):
    kind, plan = run_plan(planning, [proposal()], identifiers=())
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]


def test_selected_document_does_not_prevent_explicit_editor_narrowing(planning):
    previous = proposal([LEFT])
    before = deepcopy(previous)
    narrowed = proposal()
    narrowed["revised_request"] = "Rewrite only the existing answer."
    kind, plan = run_plan(planning, [narrowed], edit_context={"current_plan": previous})
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert previous == before
    assert any("selected documents" in warning for warning in plan["validation"]["repairs"])


def test_edit_failure_preserves_previous_plan_and_legacy_options(planning):
    previous = proposal([LEFT], capability="document_analyze", options={})
    before = deepcopy(previous)
    invalid = proposal([LEFT], capability="document_analyze", options={"mode": "source_observations"})
    invalid["revised_request"] = "Describe the selected source."
    with pytest.raises(planning.harness.planner.PlannerError) as failure:
        run_plan(planning, [invalid, invalid], edit_context={"current_plan": previous})
    assert "previous plan is unchanged" in str(failure.value)
    assert previous == before
    omitted = proposal([LEFT], capability="document_analyze")
    omitted["revised_request"] = "Describe the selected source."
    kind, plan = run_plan(planning, [omitted], edit_context={"current_plan": previous})
    assert kind == "plan"
    assert plan["steps"][0]["arguments"]["analysis_options"]["mode"] == "narrative_findings"


def test_limited_spreadsheet_preview_can_still_produce_an_inspection_plan(planning):
    source = {
        "document_id": RIGHT, "file_name": "workbook.xlsx", "source_kind": "tabular",
        "availability": "available",
        "inspection": {"status": "limited", "content_complete": False, "tables": []},
    }
    raw = proposal([RIGHT], capability="tabular_inspect")
    kind, plan = run_plan(
        planning, [raw], identifiers=(RIGHT,), context_updates={"selected_sources": [source]},
    )
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert plan["steps"][0]["capability_id"] == "tabular_inspect"


def test_http_auto_routing_repairs_analyze_options_without_running_analysis(planning, monkeypatch):
    harness = planning.harness
    authentication = importlib.import_module("functions_authentication")
    # Creating the fixture user's preferences must not fetch a Graph profile photo.
    monkeypatch.setattr(authentication, "get_user_profile_image", lambda: None)
    execute = Mock(side_effect=AssertionError("An Analyze adapter ran while planning."))
    adapters = importlib.import_module("functions_orchestration_adapters")
    monkeypatch.setitem(adapters.ADAPTER_REGISTRY, "document_analyze", execute)
    request = "Read the text from the selected source."
    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": request, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal([LEFT], capability="document_analyze", options={"mode": "source_observations"})),
        json.dumps(proposal([LEFT], capability="document_analyze")),
    ]
    response = planning.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "auto-model-turn",
        "message": request, "selected_document_ids": [LEFT],
        "approval_mode": "manual", "model_routing": "auto",
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2])
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    assert response.status_code == 200 and "plan" in frames[-1], frames
    plan = frames[-1]["plan"]
    assert plan["steps"][0]["arguments"]["analysis_options"]["mode"] == "source_observations"
    assert all(step.get("model_binding") for step in plan["steps"])
    assert execute.call_count == 0
    assert len(harness.model_calls) == 3


def test_provider_timeout_is_not_retried_as_a_validation_problem(planning):
    error = APITimeoutError(request=httpx.Request("POST", f"https://private.invalid/{PRIVATE}"))
    with pytest.raises(planning.harness.planner.PlannerError) as failure:
        run_plan(planning, [error, proposal([LEFT])])
    assert failure.value.reason == "model_request_failed"
    assert len(planning.harness.model_calls) == 1
    assert len(planning.harness.replies) == 1
    assert PRIVATE not in str(failure.value)


@pytest.mark.parametrize("count", [200, 201])
def test_required_analysis_fields_are_bounded_without_trimming(planning, count):
    raw = proposal([LEFT], capability="document_analyze", options={
        "version": "analysis-options-v2", "mode": "reconciled_records",
        "required_fields": [f"field_{index}" for index in range(count)],
    })
    kind, plan = run_plan(planning, [raw, proposal([LEFT], capability="document_analyze")])
    assert kind == "plan"
    if count == 200:
        assert len(planning.harness.model_calls) == 1
        assert len(plan["steps"][0]["arguments"]["analysis_options"]["required_fields"]) == count
    else:
        assert len(planning.harness.model_calls) == 2
        assert plan["steps"][0]["arguments"]["analysis_options"]["mode"] == "source_observations"


@pytest.mark.parametrize("debug", [False, True])
def test_debug_diagnostics_do_not_change_invalid_unicode_rejection(planning, debug):
    planning.debug_flags["enable_debug_logging"] = debug
    raw = proposal(["\ud800"])
    with pytest.raises(planning.harness.planner.PlannerError):
        run_plan(planning, [raw])
    assert len(planning.harness.model_calls) == 1


def test_correction_preserves_explicit_reconciled_field_requirements(planning):
    invalid = proposal([LEFT], capability="document_analyze", options={
        **OPTIONS, "required_fields": ["amount"],
    })
    corrected = proposal([LEFT], capability="document_analyze", options={
        "version": "analysis-options-v2", "mode": "reconciled_records",
        "required_fields": ["amount"],
    })
    kind, plan = run_plan(
        planning, [invalid, corrected],
        message="Extract reconciled records from the selected source; every record must include amount.",
    )
    assert kind == "plan"
    assert plan["steps"][0]["arguments"]["analysis_options"]["required_fields"] == ["amount"]
    repair = planning.harness.model_calls[-1]["messages"][-1]["content"]
    assert "Do not discard user-required fields or calculations" in repair


def test_correction_cannot_widen_the_authorized_document_selection(planning):
    with pytest.raises(planning.harness.planner.PlannerError):
        run_plan(planning, [proposal(), proposal([LEFT, RIGHT])])
    assert len(planning.harness.model_calls) == 2
    for call in planning.harness.model_calls:
        context = json.loads(call["messages"][1]["content"])
        assert context["user_selected"]["documents"] == [LEFT]


@pytest.mark.parametrize("retain_source,rule", [
    (True, "selected_capabilities_missing"),
    (False, "selected_documents_and_capabilities_missing"),
])
def test_positive_operation_requirements_are_not_dropped(planning, caplog, retain_source, rule):
    initial = proposal([LEFT]) if retain_source else proposal()
    corrected = proposal([LEFT], capability="document_analyze")
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(
            planning, [initial, corrected], seed_updates={"required_capabilities": ["document_analyze"]},
        )
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert plan["steps"][0]["capability_id"] == "document_analyze"
    correction = next(
        record for record in caplog.records
        if getattr(record, "sc_message", None) == "[ORCHESTRATION_PLANNER] Asking the planner to correct a rejected plan."
    )
    assert correction.sc_validation_rule == rule


@pytest.mark.parametrize("first", ["selection", "options", "question"])
def test_unrenderable_question_cannot_reset_the_shared_correction_budget(planning, first):
    question = {
        "kind": "elicitation", "message": "Choose a business rule.",
        "clarification_context": {"reason": "business_rule", "document_ids": [LEFT]},
        "requested_schema": {"type": "object", "properties": {"nested": {"type": "object"}}},
    }
    initial = {
        "selection": proposal(),
        "options": proposal([LEFT], capability="document_analyze", options={"mode": "source_observations"}),
        "question": question,
    }[first]
    with pytest.raises(planning.harness.planner.PlannerError):
        run_plan(planning, [initial, question, proposal([LEFT])])
    assert len(planning.harness.model_calls) == 2
    assert len(planning.harness.replies) == 1


def test_unrenderable_question_keeps_the_same_model_and_selected_sources(planning):
    question = {
        "kind": "elicitation", "message": "Choose a business rule.",
        "clarification_context": {"reason": "business_rule", "document_ids": [LEFT]},
        "requested_schema": {"type": "object", "properties": {"nested": {"type": "object"}}},
    }
    kind, plan = run_plan(planning, [question, proposal([LEFT])])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert len(planning.harness.clients) == 1
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
