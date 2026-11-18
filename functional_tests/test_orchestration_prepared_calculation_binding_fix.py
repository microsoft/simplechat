#!/usr/bin/env python3
# test_orchestration_prepared_calculation_binding_fix.py
"""
Functional test for the prepared calculation binding fix.
Version: 0.261.456
Implemented in: 0.261.456

This test ensures that a multi-file calculation planned without its preparation step is
rejected at planning time, where the planner can correct it, instead of failing when the run
starts, and that the planner prompt describes the two-step shape the capability requires.
"""

import os
import sys
from copy import deepcopy

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_dependency_planner import planner  # noqa: E402,F401 (fixture)
from test_orchestration_dependency_runtime import runtime  # noqa: E402,F401 (fixture)

SOURCES = ["orders", "prices"]


def _plan():
    return {"steps": [
        {
            "step_id": "prepare", "capability_id": "tabular_analyze",
            "arguments": {
                "question": "Prepare the calculation context.", "native_operation": "prepare",
                "document_ids": list(SOURCES),
                "preparation_request": {
                    "version": "tabular-context-request-v1",
                    "datasets": [
                        {"alias": name, "document_id": name, "context_columns": [], "key_profiles": []}
                        for name in SOURCES
                    ],
                },
            },
        },
        {
            "step_id": "calculate", "capability_id": "tabular_analyze",
            "arguments": {
                "question": "Calculate the totals.", "native_operation": "relate",
                "document_ids": list(SOURCES), "calculation_mode": "prepared-v1",
            },
            "inputs": {"preparation": {
                "binding": {"step_id": "prepare", "output_name": "context"}, "allow_partial": False,
            }},
        },
    ]}


def _rejection(runtime, plan):
    with pytest.raises(runtime.schema.PlanValidationError) as error:
        runtime.schema.validate_generated_plan_tabular_admission(plan)
    return error.value


def test_the_two_step_prepared_calculation_is_admitted(runtime):
    assert runtime.schema.validate_generated_plan_tabular_admission(_plan()) is None


def test_a_calculation_without_its_preparation_step_is_rejected_at_planning(runtime):
    """The shape seen in production: one calculation step over several files, then the answer."""
    plan = _plan()
    plan["steps"] = [plan["steps"][1]]
    plan["steps"][0].pop("inputs")
    error = _rejection(runtime, plan)
    assert error.code == "plan_arguments_invalid"
    assert error.rule == "prepared_calculation_binding_required"
    assert error.diagnostics == {"binding_problem": "preparation_input_missing"}
    assert error.feedback["problem"] == "preparation_input_missing"
    assert [step["native_operation"] for step in error.feedback["required_steps"]] == ["prepare", "relate"]


@pytest.mark.parametrize("change, problem", [
    (lambda plan: plan["steps"][1]["inputs"].update(extra=deepcopy(plan["steps"][1]["inputs"]["preparation"])),
     "other_inputs_bound"),
    (lambda plan: plan["steps"][1]["inputs"]["preparation"]["binding"].update(step_id="missing"),
     "preparation_producer_invalid"),
    (lambda plan: plan["steps"][0]["arguments"].update(native_operation="analysis"),
     "preparation_producer_invalid"),
    (lambda plan: plan["steps"][0].update(enabled=False), "preparation_producer_invalid"),
    (lambda plan: plan["steps"][1]["inputs"]["preparation"]["binding"].update(output_name="coverage"),
     "preparation_output_invalid"),
    (lambda plan: plan["steps"][1]["inputs"]["preparation"].update(allow_partial=True),
     "preparation_partial_not_allowed"),
    (lambda plan: plan["steps"][1]["arguments"].update(document_ids=["prices", "orders"]),
     "preparation_sources_differ"),
    (lambda plan: plan["steps"][0]["arguments"]["preparation_request"]["datasets"].pop(),
     "preparation_sources_differ"),
])
def test_each_binding_the_run_would_refuse_is_named(runtime, change, problem):
    plan = _plan()
    change(plan)
    error = _rejection(runtime, plan)
    assert error.rule == "prepared_calculation_binding_required"
    assert error.diagnostics["binding_problem"] == problem


def test_a_disabled_or_single_step_operation_is_not_checked(runtime):
    plan = _plan()
    plan["steps"][1]["enabled"] = False
    plan["steps"][1].pop("inputs")
    assert runtime.schema.validate_generated_plan_tabular_admission(plan) is None
    query = {"steps": [{
        "step_id": "rows", "capability_id": "tabular_analyze",
        "arguments": {"question": "Rows.", "native_operation": "query", "document_ids": ["orders"]},
    }]}
    assert runtime.schema.validate_generated_plan_tabular_admission(query) is None


def test_the_legacy_explicit_program_is_still_rejected_with_the_required_shape(runtime):
    plan = _plan()
    plan["steps"][1]["arguments"].pop("calculation_mode")
    error = _rejection(runtime, plan)
    assert error.rule == "prepared_calculation_required"
    assert error.feedback["required_steps"][1]["calculation_mode"] == "prepared-v1"


def test_the_planner_prompt_describes_the_shape_the_capability_requires(planner):
    prompt = planner.planner_system_prompt(["tabular_analyze", "compose"])
    assert 'native_operation="prepare"' in prompt
    assert 'calculation_mode="prepared-v1"' in prompt
    assert "It has no relational_spec" in prompt
    # The earlier wording told the planner to write the program the server now authors.
    assert "complete tabular-relate-v1 relational_spec" not in planner.PLANNER_SYSTEM_PROMPT
    # A request that offers no tabular capability is not sent this section.
    assert 'native_operation="prepare"' not in planner.planner_system_prompt(["compose"])


def test_the_correction_request_tells_the_planner_the_required_shape(planner, runtime):
    plan = _plan()
    plan["steps"] = [plan["steps"][1]]
    plan["steps"][0].pop("inputs")
    message = planner.plan_repair_message(_rejection(runtime, plan))
    assert "preparation_input_missing" in message
    assert '"native_operation": "prepare"' in message


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
