# test_workflow_definition_data_flow.py
"""
Functional tests for versioned workflow authoring and stable data-flow bindings.
Version: 0.261.116
Implemented in: 0.261.108

These tests cover stale saves, V1 protection, task ordering, scoped reference
descriptors, and deterministic output contracts without live Azure resources.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Import application helpers after adding the worktree's module path.
from functions_workflow_definitions import (
    WorkflowDefinitionConflict,
    WorkflowDefinitionError,
    normalize_workflow_definition,
    normalize_workflow_output_contract,
    workflow_definition_for_editor,
    workflow_definition_revision,
)


def definition():
    return {
        "definition_version": 2,
        "name": "Inventory",
        "reference_inputs": [{
            "id": "criteria", "name": "criteria", "document_id": "policy-document",
            "scope_type": "personal", "scope_id": "owner",
        }],
        "tasks": [
            {"id": "extract", "name": "Extract", "instructions": "Extract inventory.",
             "output_contract": {"kind": "records", "identity_field": "item_id"}},
            {"id": "explain", "name": "Explain", "instructions": "Explain inventory."},
            {"id": "report", "name": "Report", "instructions": "Create a final report.",
             "inputs": [{
                 "name": "findings", "task_id": "extract", "output": "authoritative",
                 "required": True, "expected_kind": "records",
             }]},
        ],
    }


def normalized_tasks(payload):
    return [
        {key: task[key] for key in ("id", "name", "instructions")}
        for task in payload["tasks"]
    ]


def normalize(payload, existing=None, **kwargs):
    return normalize_workflow_definition(
        payload, existing or {}, normalized_tasks(payload), user_id="owner", **kwargs,
    )


def test_nonadjacent_inputs_remain_bound_to_stable_task_ids():
    result = normalize(definition())
    assert result["tasks"][2]["inputs"][0]["task_id"] == "extract"
    assert result["tasks"][0]["output_contract"]["kind"] == "records"
    assert "inputs" not in result["tasks"][1]
    assert result["reference_inputs"][0]["document_id"] == "policy-document"


def test_absent_empty_and_selected_reference_inputs_remain_distinct():
    payload = definition()
    payload["tasks"][0]["inputs"] = []
    payload["tasks"][1]["reference_ids"] = []
    payload["tasks"][2]["reference_ids"] = ["criteria"]
    result = normalize(payload)
    assert result["tasks"][0]["inputs"] == []
    assert "inputs" not in result["tasks"][1]
    assert "reference_ids" not in result["tasks"][0]
    assert result["tasks"][1]["reference_ids"] == []
    assert result["tasks"][2]["reference_ids"] == ["criteria"]


@pytest.mark.parametrize("producer", ["missing", "report", "future-task"])
def test_missing_self_and_forward_bindings_are_rejected(producer):
    payload = definition()
    payload["tasks"][2]["inputs"][0]["task_id"] = producer
    with pytest.raises(WorkflowDefinitionError, match="earlier"):
        normalize(payload)


def test_reordering_cannot_silently_retarget_a_binding():
    payload = definition()
    payload["tasks"] = [payload["tasks"][2], payload["tasks"][0], payload["tasks"][1]]
    with pytest.raises(WorkflowDefinitionError, match="earlier"):
        normalize(payload)


@pytest.mark.parametrize("output", ["diagnostics", "presentation", "manifest", "../../secret"])
def test_only_final_named_sections_can_be_task_inputs(output):
    payload = definition()
    payload["tasks"][2]["inputs"][0]["output"] = output
    with pytest.raises(WorkflowDefinitionError, match="final output"):
        normalize(payload)


def test_task_binding_cannot_supply_a_storage_reference():
    payload = definition()
    payload["tasks"][2]["inputs"][0]["result_ref"] = {"sha256": "forged"}
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        normalize(payload)


def test_static_kind_mismatch_is_explained_before_execution():
    payload = definition()
    payload["tasks"][0]["output_contract"] = {"kind": "text"}
    with pytest.raises(WorkflowDefinitionError, match="producer"):
        normalize(payload)


def test_explicit_representation_and_expected_kind_cannot_disagree():
    payload = definition()
    payload["tasks"][2]["inputs"][0].update(output="text", expected_kind="records")
    with pytest.raises(WorkflowDefinitionError, match="representation"):
        normalize(payload)


def test_v1_roundtrip_keeps_legacy_task_behavior():
    payload = {"name": "Legacy", "tasks": [{"id": "one", "name": "One", "instructions": "Explain."}]}
    result = normalize(payload)
    assert result == {"definition_version": 1, "tasks": normalized_tasks(payload)}


def test_v1_cannot_send_unversioned_advanced_configuration():
    payload = definition()
    payload.pop("definition_version")
    with pytest.raises(WorkflowDefinitionError, match="version 2"):
        normalize(payload)


def test_classic_save_cannot_strip_an_advanced_definition():
    existing = definition()
    payload = {"name": "Legacy save", "tasks": normalized_tasks(existing)}
    with pytest.raises(WorkflowDefinitionConflict, match="Open it in V2"):
        normalize(payload, existing)


def test_current_revision_is_required_for_native_updates():
    existing = definition()
    payload = copy.deepcopy(existing)
    payload["name"] = "Updated"
    with pytest.raises(WorkflowDefinitionConflict, match="Reload"):
        normalize(payload, existing)
    payload["definition_revision"] = workflow_definition_revision(existing)
    assert normalize(payload, existing)["definition_version"] == 2


def test_progress_does_not_invalidate_an_editor_but_authored_changes_do():
    existing = definition()
    revision = workflow_definition_revision(existing)
    runtime = {**existing, "status": "idle", "run_count": 2, "updated_at": "later"}
    assert workflow_definition_revision(runtime) == revision
    changed = copy.deepcopy(existing)
    changed["tasks"][0]["instructions"] = "A concurrent authored change."
    assert workflow_definition_revision(changed) != revision
    assert workflow_definition_for_editor(existing)["definition_revision"] == revision


def test_native_update_does_not_change_an_active_run_definition():
    existing = {**definition(), "active_run_id": "active-run"}
    payload = {**definition(), "definition_revision": workflow_definition_revision(existing)}
    with pytest.raises(WorkflowDefinitionConflict, match="active run"):
        normalize(payload, existing)


@pytest.mark.parametrize("version", [True, 0, 4, "2", None])
def test_unsupported_version_never_downgrades(version):
    payload = definition()
    payload["definition_version"] = version
    with pytest.raises(WorkflowDefinitionConflict):
        normalize(payload)


@pytest.mark.parametrize("scope,scope_id", [("personal", "other-owner"), ("group", "other-group"), ("public", "public")])
def test_group_references_cannot_escape_the_workflow_group(scope, scope_id):
    payload = definition()
    payload["reference_inputs"][0].update(scope_type=scope, scope_id=scope_id)
    with pytest.raises(WorkflowDefinitionError):
        normalize(payload, group_id="authorized-group")


def test_group_reference_descriptors_preserve_explicit_scope():
    payload = definition()
    payload["reference_inputs"][0].update(scope_type="group", scope_id="authorized-group")
    result = normalize(payload, group_id="authorized-group")
    assert result["reference_inputs"][0]["scope_id"] == "authorized-group"


def test_duplicate_or_missing_reference_names_fail():
    payload = definition()
    payload["reference_inputs"].append(dict(payload["reference_inputs"][0], id="another"))
    with pytest.raises(WorkflowDefinitionError, match="unique"):
        normalize(payload)
    payload = definition()
    payload["tasks"][0]["reference_ids"] = ["not-shared"]
    with pytest.raises(WorkflowDefinitionError, match="not in"):
        normalize(payload)


@pytest.mark.parametrize("schema", [
    {"$ref": "https://example.invalid/schema"},
    {"pattern": "(a+)+$"},
    {"properties": {"nested": {"$ref": "file:///private"}}},
    {"items": {"allOf": [{"type": "string"}]}},
])
def test_schema_never_resolves_external_refs_or_runs_regexes(schema):
    with pytest.raises(WorkflowDefinitionError, match="not supported"):
        normalize_workflow_output_contract({"kind": "records", "schema": schema})


def test_output_schema_and_zero_expected_count_are_preserved():
    contract = {"kind": "records", "expected_count": 0, "schema": {
        "type": "array",
        "items": {"type": "object", "properties": {"id": {"type": "string"}},
                  "required": ["id"], "additionalProperties": False},
    }}
    normalized = normalize_workflow_output_contract(contract)
    assert normalized["expected_count"] == 0
    assert normalized["schema"] == contract["schema"]
    assert normalized["allow_partial"] is False
