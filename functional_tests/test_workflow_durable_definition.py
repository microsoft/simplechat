# test_workflow_durable_definition.py
"""
Functional tests for opt-in durable workflow definitions and task approval.
Version: 0.261.111
Implemented in: 0.261.111
"""

import pytest

from test_workflow_definition_data_flow import definition, normalize
from functions_workflow_definitions import WorkflowDefinitionError, workflow_definition_revision


def test_existing_definitions_do_not_silently_enable_durable_execution():
    workflow = definition()
    result = normalize(workflow)
    assert result["durable_execution"] is False


def test_task_approval_requires_an_explicit_durable_definition():
    workflow = definition()
    workflow["tasks"][0]["approval"] = {"required": True, "message": "Review the intended action."}
    with pytest.raises(WorkflowDefinitionError, match="requires durable"):
        normalize(workflow)
    workflow["durable_execution"] = True
    normalized = normalize(workflow)
    assert normalized["tasks"][0]["approval"] == workflow["tasks"][0]["approval"]
    assert normalized["durable_execution"] is True


@pytest.mark.parametrize("value", ["true", 1, {}, None])
def test_durability_requires_a_real_boolean(value):
    workflow = {**definition(), "durable_execution": value}
    with pytest.raises(WorkflowDefinitionError):
        normalize(workflow)


def test_approval_policy_is_part_of_the_authored_revision():
    workflow = definition()
    before = workflow_definition_revision(workflow)
    workflow["durable_execution"] = True
    assert workflow_definition_revision(workflow) != before
    before = workflow_definition_revision(workflow)
    workflow["tasks"][0]["approval"] = {"required": True, "message": "Review."}
    assert workflow_definition_revision(workflow) != before


def test_approval_cannot_supply_permissions_or_executable_conditions():
    workflow = {**definition(), "durable_execution": True}
    workflow["tasks"][0]["approval"] = {"required": True, "is_admin": True}
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        normalize(workflow)
