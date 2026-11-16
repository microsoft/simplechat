# test_workflow_durable_definition.py
"""
Functional tests for durable workflow definitions, legacy preservation, and task approval.
Version: 0.261.381
Implemented in: 0.261.111
Updated in: 0.261.381
"""

import pytest

from test_workflow_definition_data_flow import definition, normalize
from functions_workflow_assist_editor import (
    new_workflow_definition,
    normalize_workflow_definition as normalize_editor_workflow,
    workflow_for_save,
)
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


def test_editor_save_keeps_new_and_durable_workflows_durable_and_preserves_legacy_until_upgraded():
    draft = new_workflow_definition({"type": "personal"})
    draft["name"] = "Always durable"
    draft["tasks"][0]["instructions"] = "Summarize findings."

    created = workflow_for_save({**draft, "durable_execution": False}, None)
    assert created["durable_execution"] is True

    stored_durable = normalize_editor_workflow({**draft, "id": "wf-durable", "durable_execution": True})
    saved_durable = workflow_for_save({**stored_durable, "durable_execution": False}, stored_durable)
    assert saved_durable["durable_execution"] is True

    legacy_raw = {key: value for key, value in draft.items() if key != "durable_execution"}
    legacy_raw["id"] = "wf-legacy"
    stored_legacy = normalize_editor_workflow(legacy_raw)
    saved_legacy = workflow_for_save(dict(stored_legacy), stored_legacy)
    assert "durable_execution" not in saved_legacy

    upgraded_legacy = workflow_for_save({**stored_legacy, "durable_execution": True}, stored_legacy)
    assert upgraded_legacy["durable_execution"] is True
