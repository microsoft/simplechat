#!/usr/bin/env python3
# test_orchestration_merge_layout_question.py
"""
Functional test for the question chat asks before merging spreadsheets into one Excel file.
Version: 0.261.246
Implemented in: 0.261.246
Refs: microsoft/simplechat#1619

Several CSV or Excel files merged into one Excel file can mean every row on one sheet
(tabular_merge) or each file on its own sheet (document_merge with kind workbook). This test
ensures that the planner is told to ask which, with exactly those two choices, only when the plan
could deliver either one; that the general clarification rule names this exception while still
preferring stated assumptions; that proposed workflow merges ask the same question with the same
choices; that the question reaches the user in a shape the server accepts and the V2 card renders;
and that each answer plans to a valid merge through the real validator and deliverables contract.
"""

import json
import re
from copy import deepcopy

import pytest

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import input_binding
from test_support.versioning import assert_app_version_at_least


MESSAGE = "Merge these three regional sales files into one Excel file."


def _collapsed(text):
    return re.sub(r"\s+", " ", text)


def _modules():
    import functions_orchestration_deliverables as deliverables
    import functions_orchestration_registry as registry

    return deliverables, registry


def _all_capability_ids():
    _, registry = _modules()
    # render_file is described from the export catalog, so the full list comes from the description.
    return list(registry.describe_registry()["capability_ids"])


def _truth(harness, *, without=()):
    """The deliverables truth a real plan request computes, with some capabilities narrowed out."""
    deliverables, registry = _modules()
    allowed = [capability_id for capability_id in _all_capability_ids() if capability_id not in without]
    unavailable = {}
    capabilities = registry.resolve_available_capabilities(
        harness.settings, allowed_ids=allowed, unavailable=unavailable, contract_version=2,
        request_context=harness.services().capability_request_bindings(),
    )
    truth = deliverables.build_deliverable_availability(
        harness.settings, capabilities=capabilities, unavailable=unavailable,
    )
    return truth, [item["id"] for item in capabilities]


def _layout_question():
    deliverables, _ = _modules()
    return {
        "kind": "elicitation",
        "message": "Merged spreadsheets can share one sheet or keep a sheet each.",
        "requested_schema": {
            "type": "object",
            "properties": {"layout": {
                "type": "string", "title": "How should the merged workbook be laid out?",
                "enum": [deliverables.MERGE_LAYOUT_ONE_SHEET, deliverables.MERGE_LAYOUT_SHEET_PER_FILE],
            }},
            "required": ["layout"],
        },
    }


def _plan_request(harness, replies, *, settings=None):
    harness.replies = [json.dumps(reply) for reply in replies]
    return harness.planner.plan_request(
        MESSAGE, {}, "conversation-1", "owner", settings=settings or harness.settings, seeds={},
        contract_version=2, request_context=harness.services().capability_request_bindings(),
    )


def _merge_plan(layout):
    deliverables, _ = _modules()
    if layout == deliverables.MERGE_LAYOUT_ONE_SHEET:
        merge = {
            "step_id": "merge", "capability_id": "tabular_merge", "title": "Merge spreadsheets",
            "arguments": {"document_ids": ["east-doc", "west-doc", "north-doc"]}, "inputs": {},
        }
        render = {"profile": "exact_tabular_workbook_v1", "output": "records"}
    else:
        merge = {
            "step_id": "merge", "capability_id": "document_merge", "title": "Merge documents",
            "arguments": {"document_ids": ["east-doc", "west-doc", "north-doc"], "kind": "workbook"},
            "inputs": {},
        }
        render = {"profile": "assembled_document_v1", "output": "assembly"}
    return {
        "run_id": "run-1", "plan_id": "plan-1", "turn_id": "turn-1", "kind": "plan",
        "intent": {"summary": "Merge three regional sales files into one Excel file.", "complexity": "simple"},
        "assumptions": [],
        "deliverables": [{
            "id": "merged", "kind": "file", "requested": "explicit", "status": "planned",
            "description": "One Excel file merged from the regional sales files", "format": "xlsx",
        }],
        "steps": [merge, {
            "step_id": "save", "capability_id": "render_file", "title": "Save the Excel file",
            "arguments": {
                "file_name": "Regional sales.xlsx", "output_format": "xlsx", "profile": render["profile"],
                "options": {},
            },
            "inputs": {"source": {"binding": input_binding("merge", render["output"]), "allow_partial": False}},
            "outputs": [], "delivers": ["merged"],
        }],
        "final_response": None,
    }


def test_version_includes_the_merge_layout_question():
    assert_app_version_at_least("0.261.246")


def test_the_question_is_offered_only_when_both_layouts_can_be_delivered(harness):
    deliverables, _ = _modules()
    truth, available = _truth(harness)
    assert {"tabular_merge", "document_merge", "render_file"} <= set(available)
    assert truth["facts"].count(deliverables.MERGE_LAYOUT_FACT) == 1
    fact = deliverables.MERGE_LAYOUT_FACT
    for phrase in (
        f'"{deliverables.MERGE_LAYOUT_ONE_SHEET}"', f'"{deliverables.MERGE_LAYOUT_SHEET_PER_FILE}"',
        "tabular_merge", "document_merge with kind workbook", "required single-choice string enum",
        "CSV output means one sheet", "When the user declines to answer, put every row on one sheet",
    ):
        assert phrase in fact, phrase
    # Without either layout, or without a way to deliver a file, there is nothing to choose between.
    for narrowed in ("document_merge", "tabular_merge", "render_file"):
        truth, available = _truth(harness, without=(narrowed,))
        assert narrowed not in available
        assert deliverables.MERGE_LAYOUT_FACT not in truth["facts"], narrowed


def test_the_clarification_rule_names_its_exceptions_and_still_prefers_assumptions(harness):
    prompt = _collapsed(harness.planner.PLANNER_SYSTEM_PROMPT)
    assert (
        "Only ask when you truly cannot proceed, or when a capability's when_to_use, a fact in "
        "capability_availability.deliverables or the workflow instructions say to ask; otherwise a "
        'reasonable assumption about what the user means, stated in "assumptions", is better than a question.'
    ) in prompt


def test_proposed_workflow_merges_ask_the_same_question(harness):
    deliverables, _ = _modules()
    instructions = _collapsed(harness.planner.WORKFLOW_PROPOSAL_INSTRUCTIONS)
    assert (
        f'one required single-choice string enum of exactly "{deliverables.MERGE_LAYOUT_ONE_SHEET}" and '
        f'"{deliverables.MERGE_LAYOUT_SHEET_PER_FILE}"'
    ) in instructions
    assert 'kind "tabular" with "xlsx"' in instructions and 'own sheet (kind "workbook")' in instructions
    assert '"csv" output always means one sheet' in instructions


def test_the_planner_is_told_and_its_question_reaches_the_user(harness):
    deliverables, _ = _modules()
    kind, question = _plan_request(harness, [_layout_question()])
    assert kind == "elicitation"
    context = json.loads(harness.model_calls[0]["messages"][1]["content"])
    assert deliverables.MERGE_LAYOUT_FACT in context["capability_availability"]["deliverables"]["facts"]
    assert "a fact in capability_availability.deliverables" in _collapsed(harness.model_calls[0]["messages"][0]["content"])

    assert question["requested_schema"] == {
        "type": "object",
        "properties": {"layout": {
            "type": "string", "title": "How should the merged workbook be laid out?",
            "enum": [deliverables.MERGE_LAYOUT_ONE_SHEET, deliverables.MERGE_LAYOUT_SHEET_PER_FILE],
        }},
        "required": ["layout"],
    }
    assert question["ui_hints"]["pages"] == [["layout"]] and "fields" not in question["ui_hints"]
    for choice in (deliverables.MERGE_LAYOUT_ONE_SHEET, deliverables.MERGE_LAYOUT_SHEET_PER_FILE):
        answer, errors = harness.schema.validate_elicitation_response(
            question, {"action": "accept", "content": {"layout": choice}},
        )
        assert errors == [] and answer["content"] == {"layout": choice}
    refused, errors = harness.schema.validate_elicitation_response(
        question, {"action": "accept", "content": {"layout": "One sheet per region"}},
    )
    assert refused is None
    assert errors == ["'layout' is not one of the offered choices.", "'layout' is required."]
    declined, errors = harness.schema.validate_elicitation_response(question, {"action": "decline"})
    assert errors == [] and declined == {"action": "decline", "content": {}}


def test_a_planner_that_cannot_build_a_sheet_per_file_is_not_told_to_ask(harness):
    deliverables, _ = _modules()
    settings = deepcopy(harness.settings)
    settings["chat_orchestration_enabled_capabilities"] = [
        capability_id for capability_id in _all_capability_ids() if capability_id != "document_merge"
    ]
    kind, _question = _plan_request(harness, [_layout_question()], settings=settings)
    assert kind == "elicitation"
    context = json.loads(harness.model_calls[0]["messages"][1]["content"])
    available = context["capability_availability"]["available"]
    # Only Merge documents is narrowed out; the plan could still merge rows and create a file.
    assert "document_merge" not in available and {"tabular_merge", "render_file"} <= set(available)
    assert deliverables.MERGE_LAYOUT_FACT not in context["capability_availability"]["deliverables"]["facts"]


@pytest.mark.parametrize("layout", ["All rows on one sheet", "Each file on its own sheet"])
def test_each_answer_plans_to_a_valid_merge(harness, layout):
    deliverables, _ = _modules()
    assert layout in (deliverables.MERGE_LAYOUT_ONE_SHEET, deliverables.MERGE_LAYOUT_SHEET_PER_FILE)
    truth, available = _truth(harness)
    plan = harness.schema.normalize_plan(
        _merge_plan(layout), "conversation-1", "owner", settings=harness.settings, contract_version=2,
        available_capability_ids=available, deliverable_availability=truth,
        composition_profiles=harness.service_bindings.composition_profiles(),
    )
    steps = {step["step_id"]: step for step in plan["steps"]}
    assert steps["save"]["depends_on"] == ["merge"]
    if layout == deliverables.MERGE_LAYOUT_ONE_SHEET:
        assert steps["merge"]["capability_id"] == "tabular_merge"
        assert steps["save"]["arguments"]["profile"] == "exact_tabular_workbook_v1"
    else:
        assert steps["merge"]["capability_id"] == "document_merge"
        assert steps["merge"]["arguments"]["kind"] == "workbook"
        assert steps["save"]["arguments"]["profile"] == "assembled_document_v1"
    assert [item["id"] for item in plan["deliverables"]] == ["merged"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
