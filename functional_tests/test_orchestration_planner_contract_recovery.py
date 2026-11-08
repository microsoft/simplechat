# test_orchestration_planner_contract_recovery.py
"""
Functional regressions for effective planner contracts and document action binding.
Version: 0.261.422
Implemented in: 0.261.419; 0.261.422

Real registry, planner, validation, source preparation and logger owners run with
external model/storage I/O isolated. A corrected draft must retain the original
scope, model, deliverables and shared correction budget without executing tools.
"""

import importlib
import json
import logging
from copy import deepcopy

import pytest

from test_orchestration_document_planning_recovery import planning, proposal, run_plan
from test_orchestration_harness_routes import modules, real_http_harness
from test_orchestration_source_kind_planning import LEFT, RIGHT, candidates, enrich, source_runtime
from test_support.orchestration_harness_execution import compose_step, input_binding


__all__ = ["planning", "modules", "real_http_harness", "source_runtime"]
ACTION = {
    "action_ref": "personal:owner:native", "id": "native", "name": "Native inspection",
    "display_name": "Native inspection", "type": "document_search",
    "scope_type": "personal", "scope_id": "owner", "scope_label": "Personal",
}
PRIVATE = "PRIVATE_PROMPT_OR_DOCUMENT_CONTENT"


def action_proposal(document_ids=(LEFT,), *, action=ACTION):
    reader = {
        "step_id": "inspect", "capability_id": "action_invoke",
        "arguments": {"action_ref": action["action_ref"], "task": PRIVATE},
    }
    if document_ids is not None:
        reader["arguments"]["document_ids"] = list(document_ids)
    answer = compose_step("answer", inputs={
        "native_findings": {
            "binding": input_binding("inspect", "prepared"), "allow_partial": False,
        },
    })
    answer["arguments"]["knowledge_basis"] = "sources"
    answer["delivers"] = ["answer"]
    return {
        "kind": "plan",
        "deliverables": [{
            "id": "answer", "kind": "answer", "requested": "explicit",
            "description": "Answer using the selected sources.", "status": "planned",
        }],
        "steps": [reader, answer], "final_response": input_binding("answer"),
    }


def run_action_plan(runtime, replies, *, identifiers=(LEFT,), action=ACTION, prepare_sources=False):
    harness = runtime.harness
    harness.settings.update(enable_semantic_kernel=True, enable_chat_orchestration_actions=True)
    selected, seeds = candidates(runtime, identifiers)
    if prepare_sources:
        from functions_orchestration_source_context import build_selected_source_context

        offered = runtime.context.enrich_planner_candidates(
            selected, "owner", conversation_id="conversation-1", seeds=seeds,
            selected_source_context_reader=lambda sources: build_selected_source_context(
                sources, read_bytes=lambda *args, **kwargs: pytest.fail("Narrative planning must not read file bytes."),
            ),
        )
    else:
        offered = enrich(runtime, selected, seeds)
    context = runtime.context.build_planner_context(PRIVATE, candidates=offered, seeds=seeds, actions=[action])
    caller = {**harness.services().capability_request_bindings(), "action_catalog": [action]}
    harness.replies = [json.dumps(reply) for reply in replies]
    return harness.planner.plan_request(
        PRIVATE, context, "conversation-1", "owner",
        settings=harness.settings, seeds=seeds, authorized_document_ids=list(identifiers),
        turn_id="contract-turn", request_context=caller,
    )


def correction_records(caplog):
    return [
        record for record in caplog.records
        if getattr(record, "sc_message", None)
        == "[ORCHESTRATION_PLANNER] Asking the planner to correct a rejected plan."
    ]


@pytest.mark.parametrize("options,records", [
    (None, False),
    ({}, True),
    ({"version": "analysis-options-v1"}, True),
    ({"version": "analysis-options-v2", "mode": "source_observations"}, False),
    ({"version": "analysis-options-v2", "mode": "reconciled_records"}, True),
    ({"version": "analysis-options-v1", "mode": "narrative_findings"}, True),
])
def test_advertised_analyze_variants_match_effective_validation(planning, options, records):
    registry = importlib.import_module("functions_orchestration_registry")
    capability = registry.get_capability("document_analyze")
    advertised = registry.build_planner_capability_projection([capability])[0]
    assert "records" not in advertised["optional_result_outputs"]
    assert advertised["default_arguments"]["analysis_options"]["mode"] == "source_observations"
    analysis = importlib.import_module("functions_document_analysis_results")
    effective = (
        advertised["default_arguments"]["analysis_options"] if options is None
        else analysis.normalize_analysis_options(options)
    )
    variant = next(
        item for item in advertised["result_output_variants"]
        if all(effective.get(key) == value for key, value in item["analysis_options"].items())
    )
    assert ("records" in variant["optional_result_outputs"]) is records
    raw = proposal([LEFT], capability="document_analyze", options=options)
    raw["steps"][0]["outputs"] = [
        {"name": name, "kind": kind} for name, kind in variant["result_outputs"].items()
    ]
    if records:
        raw["steps"][0]["outputs"].append({"name": "records", "kind": "records-v1"})
    kind, plan = run_plan(planning, [raw])
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert ("records" in {item["name"] for item in plan["steps"][0]["outputs"]}) is records


def test_requested_records_are_corrected_by_explicit_semantics_not_dropped(planning, caplog):
    raw = proposal([LEFT], capability="document_analyze")
    raw["steps"][0]["outputs"] = [
        {"name": "findings", "kind": "records-v1"},
        {"name": "coverage", "kind": "structured-v1"},
        {"name": "records", "kind": "records-v1"},
    ]
    corrected = deepcopy(raw)
    corrected["steps"][0]["arguments"]["analysis_options"] = {
        "version": "analysis-options-v2", "mode": "reconciled_records", "required_fields": ["amount"],
    }
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(planning, [raw, corrected])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert "records" in {item["name"] for item in plan["steps"][0]["outputs"]}
    assert plan["steps"][0]["arguments"]["analysis_options"]["required_fields"] == ["amount"]
    assert correction_records(caplog)[0].sc_validation_rule == "fixed_output_not_supported"
    assert {call["model"] for call in planning.harness.model_calls} == {"gpt-4o"}


@pytest.mark.parametrize("invalid", ["kind", "missing", "shape", "input"])
def test_owned_contract_errors_receive_one_precise_correction(planning, caplog, invalid):
    raw = proposal([LEFT])
    if invalid == "kind":
        raw["steps"][0]["outputs"] = [{"name": "prepared", "kind": "markdown-v1"}]
    elif invalid == "missing":
        raw["steps"][0]["outputs"] = [{"name": "prepared", "kind": "structured-v1"}]
    elif invalid == "shape":
        raw["steps"][0]["outputs"] = "not-a-list"
    else:
        raw["steps"][-1]["inputs"] = {"evidence": {}}
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(planning, [raw, proposal([LEFT])])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    record = correction_records(caplog)[0]
    assert record.sc_validation_code in ("plan_outputs_invalid", "plan_inputs_invalid")
    assert record.sc_validation_rule
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert planning.harness.assistant_messages() == []


@pytest.mark.parametrize("extension", ["pdf", "docx", "png", "csv", "xlsx"])
def test_native_action_binds_a_selected_document_without_a_redundant_reader(planning, extension):
    documents = planning.harness.config.cosmos_user_documents_container
    source = documents.read_item(LEFT, LEFT)
    source["file_name"] = f"selected.{extension}"
    documents.upsert_item(source)
    kind, plan = run_action_plan(planning, [action_proposal()])
    assert kind == "plan"
    assert [step["capability_id"] for step in plan["steps"]] == ["action_invoke", "compose"]
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert planning.harness.schema.effective_plan_document_ids(plan) == [LEFT]
    assert len(planning.harness.model_calls) == 1
    context = json.loads(planning.harness.model_calls[0]["messages"][1]["content"])
    assert context["actions"][0]["document_binding_supported"] is True
    assert planning.harness.assistant_messages() == [] and planning.harness.blobs.file_uploads == 0


def test_missing_action_source_declaration_is_corrected_without_extra_work(planning, caplog):
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_action_plan(
            planning, [action_proposal(None), action_proposal((LEFT, RIGHT))], identifiers=(LEFT, RIGHT),
        )
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert [step["capability_id"] for step in plan["steps"]] == ["action_invoke", "compose"]
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT, RIGHT]
    assert correction_records(caplog)[0].sc_validation_rule == "selected_documents_missing"


def test_single_selected_action_source_is_connected_locally(planning, caplog):
    raw = action_proposal(None)
    original = deepcopy(raw)
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_action_plan(planning, [raw], prepare_sources=True)
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert raw == original
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert [step["capability_id"] for step in plan["steps"]] == ["action_invoke", "compose"]
    assert plan["validation"]["ok"] and plan["validation"]["repairs"]
    assert not correction_records(caplog)
    context = json.loads(planning.harness.model_calls[0]["messages"][1]["content"])
    assert context["actions"][0]["default_arguments"]["document_ids"] == [LEFT]
    assert planning.harness.assistant_messages() == [] and planning.harness.blobs.file_uploads == 0


def test_single_selected_analyze_source_is_connected_before_validation(planning):
    raw = proposal([LEFT], capability="document_analyze")
    del raw["steps"][0]["arguments"]["document_ids"]
    kind, plan = run_plan(planning, [raw], prepare_sources=True)
    assert kind == "plan" and len(planning.harness.model_calls) == 1
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert plan["steps"][0]["arguments"]["analysis_options"]["mode"] == "source_observations"
    assert plan["steps"][-1]["inputs"]["source"]["binding"]["step_id"] == "read"
    assert plan["validation"]["repairs"]
    context = json.loads(planning.harness.model_calls[0]["messages"][1]["content"])
    analyze = next(item for item in context["capabilities"] if item["id"] == "document_analyze")
    assert analyze["default_arguments"]["document_ids"] == [LEFT]


@pytest.mark.parametrize("change", ["explicit", "disabled", "dynamic", "ambiguous", "unavailable"])
def test_local_source_wiring_never_replaces_explicit_or_ambiguous_work(planning, change):
    planner = planning.harness.planner
    raw = action_proposal(None)
    selected_sources = [{
        "document_id": LEFT, "source_kind": "narrative", "availability": "available",
    }]
    if change == "explicit":
        raw["steps"][0]["arguments"]["document_ids"] = []
    elif change == "disabled":
        raw["steps"][0]["enabled"] = False
    elif change == "dynamic":
        raw["steps"][0]["inputs"] = {"sources": {"binding": input_binding("discover", "sources")}}
    elif change == "ambiguous":
        selected_sources.append({"document_id": RIGHT, "source_kind": "tabular", "availability": "available"})
    else:
        selected_sources[0]["availability"] = "unavailable"
    original = deepcopy(raw)
    result, repairs = planner._with_selected_source_bindings(
        raw, selected_sources=selected_sources,
        selected_document_ids=[item["document_id"] for item in selected_sources],
        authorized_document_ids=[LEFT, RIGHT], actions=[ACTION],
    )
    assert result == original and raw == original and repairs == []


def test_non_document_action_cannot_claim_sources_using_a_forged_catalog_flag(planning):
    action = {**ACTION, "type": "openapi", "document_binding_supported": True}
    with pytest.raises(planning.harness.planner.PlannerError):
        run_action_plan(planning, [action_proposal(action=action)], action=action)
    assert len(planning.harness.model_calls) == 1


def test_source_set_cannot_be_passed_as_prepared_action_findings(planning, caplog):
    action = {**ACTION, "type": "openapi"}
    raw = action_proposal(None, action=action)
    raw["steps"].insert(0, deepcopy(proposal([LEFT])["steps"][0]))
    raw["steps"][1]["inputs"] = {
        "evidence": {"binding": input_binding("read", "sources"), "allow_partial": False},
    }
    corrected = deepcopy(raw)
    corrected["steps"][1]["inputs"]["evidence"]["binding"] = input_binding("read", "prepared")
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_action_plan(planning, [raw, corrected], action=action)
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert correction_records(caplog)[0].sc_validation_rule == "input_kind_mismatch"
    assert plan["steps"][1]["inputs"]["evidence"]["binding"]["output_name"] == "prepared"


def test_different_contract_errors_share_two_corrections_and_keep_private_values_out(planning, caplog):
    first = proposal([LEFT])
    first["steps"][0]["outputs"] = []
    second = proposal([LEFT])
    second["steps"][-1]["inputs"] = {"private": {}}
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(planning, [first, second, proposal([LEFT])])
    assert kind == "plan" and plan["validation"]["ok"]
    assert len(planning.harness.model_calls) == 3 and not planning.harness.replies
    assert len(correction_records(caplog)) == 2
    records = [
        {name: value for name, value in record.__dict__.items() if name.startswith("sc_")}
        for record in caplog.records
    ]
    assert PRIVATE not in json.dumps(records)


def test_third_invalid_proposal_stops_without_a_new_error_budget(planning, caplog):
    first = proposal([LEFT])
    first["steps"][0]["outputs"] = []
    second = proposal([LEFT], capability="document_analyze", options={"version": "invalid"})
    third = proposal([LEFT])
    third["steps"][-1]["inputs"] = {"evidence": {}}
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        with pytest.raises(planning.harness.planner.PlannerError) as failure:
            run_plan(planning, [first, second, third, proposal([LEFT])])
    assert len(planning.harness.model_calls) == 3 and len(planning.harness.replies) == 1
    assert len(correction_records(caplog)) == 2
    assert failure.value.code == "plan_inputs_invalid"
    assert failure.value.rule == "input_binding_required"
    assert planning.harness.assistant_messages() == []


def test_source_free_draft_uses_the_same_contract_correction_without_adding_retrieval(planning):
    invalid = proposal()
    invalid["steps"][0]["outputs"] = []
    kind, plan = run_plan(planning, [invalid, proposal()], identifiers=())
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]
    assert planning.harness.schema.effective_plan_document_ids(plan) == []


def test_argument_type_feedback_names_only_the_registered_field(planning, caplog):
    invalid = proposal([LEFT])
    invalid["steps"][0]["arguments"]["query"] = 42
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(planning, [invalid, proposal([LEFT])])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    diagnostic = next(
        record for record in caplog.records
        if getattr(record, "sc_schema_keyword", None) == "type"
    )
    assert diagnostic.sc_argument_field == "query"
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]


def test_correction_cannot_authorize_an_unselected_source(planning):
    invalid = proposal([LEFT])
    invalid["steps"][0]["outputs"] = []
    with pytest.raises(planning.harness.planner.PlannerError):
        run_plan(planning, [invalid, proposal([RIGHT]), proposal([LEFT])])
    assert len(planning.harness.model_calls) == 2 and len(planning.harness.replies) == 1
    assert planning.harness.assistant_messages() == []


def test_unknown_argument_names_are_corrected_but_never_logged(planning, caplog):
    invalid = proposal([LEFT])
    invalid["steps"][0]["arguments"][PRIVATE] = PRIVATE
    with caplog.at_level(logging.INFO, logger=planning.logger.name):
        kind, plan = run_plan(planning, [invalid, proposal([LEFT])])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert correction_records(caplog)[0].sc_validation_rule == "unknown_argument"
    records = [
        {name: value for name, value in record.__dict__.items() if name.startswith("sc_")}
        for record in caplog.records
    ]
    assert PRIVATE not in json.dumps(records)
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]


@pytest.mark.parametrize("shape", ["field", "id", "dependencies", "flags", "arguments", "cycle", "duplicate"])
def test_model_owned_step_and_graph_declarations_are_corrected_once(planning, shape):
    invalid = proposal([LEFT])
    first = invalid["steps"][0]
    if shape == "field":
        first[PRIVATE] = PRIVATE
    elif shape == "id":
        first["step_id"] = "invalid step identifier"
    elif shape == "dependencies":
        first["depends_on"] = "answer"
    elif shape == "flags":
        first["enabled"] = "yes"
    elif shape == "arguments":
        first["arguments"] = []
    elif shape == "cycle":
        first["depends_on"] = ["answer"]
    else:
        invalid["steps"][-1]["step_id"] = first["step_id"]
    kind, plan = run_plan(planning, [invalid, proposal([LEFT])])
    assert kind == "plan" and len(planning.harness.model_calls) == 2
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    assert [step["capability_id"] for step in plan["steps"]] == ["document_search", "compose"]
