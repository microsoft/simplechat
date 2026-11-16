# test_workflow_repeat_schema.py
"""
Functional tests for typed Repeat state, lexical visibility, and mixed identities.
Version: 0.261.120
Implemented in: 0.261.120

These tests exercise the production compiler and identity helpers without clients,
model calls, or an alternate execution engine.
"""

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated repository path setup.
from functions_workflow_definitions import WorkflowDefinitionError
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_execution import workflow_execution_scope
from functions_workflow_flow import compile_workflow_flow, normalize_flow_bindings
from functions_workflow_identity import (
    normalize_workflow_iteration_path, workflow_execution_id, workflow_node_identity,
)
from functions_workflow_loop_runners import (
    assert_workflow_loop_agent_type, validate_workflow_loop_runners,
)


DECISION_SCHEMA = {
    "type": "object", "required": ["ready"],
    "properties": {"ready": {"type": "boolean"}, "round": {"type": "integer"}},
}


def node_binding(node_id, name, output="json", kind="json", **options):
    return {
        "name": name, "source": {
            "kind": "node_output", "node_id": node_id, "output": output, "scope": "current",
        }, "required": True, "expected_kind": kind, "allow_partial": False, **options,
    }


def state_binding(loop_id="repeat", state_name="decision", *, name="state", kind="json"):
    return {
        "name": name, "source": {
            "kind": "repeat_state", "loop_id": loop_id, "state_name": state_name, "scope": "current",
        }, "required": True, "expected_kind": kind, "allow_partial": False,
    }


def instruction_task(identifier, contract, inputs=None):
    return {
        "id": identifier, "name": identifier, "type": "instructions", "instructions": "Use declared saved inputs.",
        "runner": {"type": "inherit"}, "document_action": {"type": "none"},
        "inputs": inputs or [], "output_contract": copy.deepcopy(contract),
    }


def repeat_definition(maximum=25):
    contract = {"kind": "json", "schema": DECISION_SCHEMA, "allow_partial": False}
    return {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "limits": {"max_executions": 5000, "deadline_seconds": 86400},
        "tasks": [
            instruction_task("seed", contract),
            instruction_task("body", contract, [state_binding()]),
        ],
        "flow": {"id": "root", "nodes": [
            {"id": "seed-node", "kind": "task", "task_id": "seed"},
            {
                "id": "repeat", "kind": "repeat_until", "max_iterations": maximum,
                "state": [{
                    "name": "decision", "initial": node_binding("seed-node", "seed")["source"],
                    "next": "decision_after", "output_contract": copy.deepcopy(contract),
                }],
                "body": {
                    "id": "repeat-body", "nodes": [{"id": "body-node", "kind": "task", "task_id": "body"}],
                    "outputs": [node_binding("body-node", "decision_after")],
                },
                "until": {
                    "op": "eq", "left": {"input": "decision", "path": "/ready"}, "right": {"literal": True},
                },
                "exports": [{"name": "decision", "output": "decision_after"}],
            },
        ], "outputs": [node_binding("repeat", "final", "decision")]},
    }


def add_data_state(workflow, kind):
    schema = {"type": "string"} if kind == "text" else {
        "type": "object",
    } if kind == "json" else {"type": "array", "items": {"type": "object"}}
    selector = "documents" if kind == "document_results" else kind
    contract = {"kind": kind, "schema": schema, "allow_partial": False}
    workflow["tasks"].extend([
        instruction_task("data-seed", contract),
        instruction_task("data-body", contract, [state_binding(state_name="data", kind=kind)]),
    ])
    workflow["flow"]["nodes"].insert(1, {"id": "data-seed-node", "kind": "task", "task_id": "data-seed"})
    repeat = workflow["flow"]["nodes"][-1]
    repeat["state"].append({
        "name": "data", "initial": node_binding("data-seed-node", "data", selector, kind)["source"],
        "next": "data_after", "output_contract": contract,
    })
    repeat["body"]["nodes"].insert(0, {"id": "data-body-node", "kind": "task", "task_id": "data-body"})
    repeat["body"]["outputs"].append(node_binding("data-body-node", "data_after", selector, kind))
    repeat["exports"].append({"name": "data", "output": "data_after"})
    return repeat


def test_repeat_normalization_is_explicit_and_idempotent():
    workflow = repeat_definition()
    compiled = compile_workflow_flow(workflow)
    repeat = compiled["nodes"]["repeat"]["node"]
    assert repeat["max_iterations"] == 25
    assert repeat["state"][0]["output_contract"]["allow_partial"] is False
    assert compiled["node_loop_ids"]["body-node"] == ["repeat"]
    assert compiled["node_loop_ids"]["repeat"] == []
    normalized = {**workflow, **{key: compiled[key] for key in ("flow", "tasks", "limits")}}
    assert compile_workflow_flow(normalized)["flow"] == compiled["flow"]
    assert workflow["flow"]["nodes"][1]["state"][0]["initial"]["node_id"] == "seed-node"


@pytest.mark.parametrize("maximum", [1, 25, 500, 1000])
def test_explicit_repeat_batch_maximum_is_independent_of_for_each(maximum):
    assert compile_workflow_flow(repeat_definition(maximum))["nodes"]["repeat"]["node"]["max_iterations"] == maximum


@pytest.mark.parametrize("maximum", [None, 0, -1, True, False, 25.0, "25", 1001, 5000])
def test_invalid_or_omitted_authored_repeat_maximum_is_rejected(maximum):
    workflow = repeat_definition(maximum)
    if maximum is None:
        workflow["flow"]["nodes"][1].pop("max_iterations")
    with pytest.raises(WorkflowDefinitionError, match="max_iterations"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("kind", ["text", "json", "records", "document_results"])
def test_typed_state_and_final_exports_preserve_original_kind(kind):
    workflow = repeat_definition()
    add_data_state(workflow, kind)
    workflow["flow"]["outputs"].append(node_binding("repeat", "data", "data", kind))
    compiled = compile_workflow_flow(workflow)
    repeat = compiled["nodes"]["repeat"]["node"]
    assert repeat["state"][1]["output_contract"]["kind"] == kind
    assert ("repeat", "data") in compiled["definite_outputs"]


@pytest.mark.parametrize("mutation", [
    lambda node: node.update(state=[]),
    lambda node: node["state"].append(copy.deepcopy(node["state"][0])),
    lambda node: node["state"][0]["output_contract"].update(kind="any"),
    lambda node: node["state"][0].update(initial={"kind": "literal", "value": {"ready": False}}),
    lambda node: node["state"][0]["initial"].update(result_ref={"sha256": "a" * 64}),
    lambda node: node["state"][0].update(initial=state_binding()["source"]),
    lambda node: node["state"][0].update(next="missing"),
    lambda node: node["body"]["outputs"][0].update(required=False),
    lambda node: node["body"]["outputs"][0].update(allow_partial=True),
    lambda node: node["exports"][0].update(output="missing"),
    lambda node: node["exports"].append(copy.deepcopy(node["exports"][0])),
    lambda node: node["until"]["left"].update(path="/undeclared"),
    lambda node: node["until"]["left"].update(input="body-node"),
    lambda node: node.update(exhaustion="complete"),
])
def test_repeat_rejects_ambiguous_unsafe_or_unapproved_shapes(mutation):
    workflow = repeat_definition()
    mutation(workflow["flow"]["nodes"][1])
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_initial_and_next_state_must_have_the_exact_declared_kind():
    workflow = repeat_definition()
    node = add_data_state(workflow, "records")
    node["state"][1]["output_contract"] = {"kind": "json", "schema": {"type": "array"}}
    with pytest.raises(WorkflowDefinitionError, match="exact declared"):
        compile_workflow_flow(workflow)


def test_explicit_partial_state_requires_both_slot_and_body_acceptance():
    workflow = repeat_definition()
    repeat = workflow["flow"]["nodes"][1]
    repeat["state"][0]["output_contract"]["allow_partial"] = True
    repeat["body"]["outputs"][0]["allow_partial"] = True
    workflow["tasks"][1]["output_contract"]["allow_partial"] = True
    workflow["tasks"][1]["inputs"][0]["allow_partial"] = True
    assert compile_workflow_flow(workflow)["nodes"]["repeat"]["node"]["state"][0]["output_contract"]["allow_partial"]


def test_body_can_explicitly_retain_state_without_rewriting_originals():
    workflow = repeat_definition()
    repeat = workflow["flow"]["nodes"][1]
    repeat["body"]["outputs"][0]["source"] = state_binding()["source"]
    compiled = compile_workflow_flow(workflow)
    assert compiled["nodes"]["repeat"]["node"]["body"]["outputs"][0]["source"]["kind"] == "repeat_state"


def test_body_outputs_cannot_escape_repeat_without_declared_boundary_export():
    workflow = repeat_definition()
    workflow["flow"]["outputs"] = [node_binding("body-node", "escaped")]
    with pytest.raises(WorkflowDefinitionError, match="out-of-region"):
        compile_workflow_flow(workflow)


def test_repeat_body_export_cannot_silently_reselect_ancestor_output():
    workflow = repeat_definition()
    workflow["flow"]["nodes"][1]["body"]["outputs"][0]["source"]["node_id"] = "seed-node"
    with pytest.raises(WorkflowDefinitionError, match="own body scope"):
        compile_workflow_flow(workflow)


def test_a_conditional_next_state_requires_an_explicit_join():
    workflow = repeat_definition()
    workflow["flow"]["nodes"][1]["body"]["nodes"][0]["run_when"] = {
        "op": "eq", "left": {"input": "state", "path": "/ready"}, "right": {"literal": False},
    }
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)


def test_repeat_state_is_not_available_outside_its_body():
    workflow = repeat_definition()
    workflow["tasks"][0]["inputs"] = [state_binding()]
    with pytest.raises(WorkflowDefinitionError, match="enclosing Repeat"):
        compile_workflow_flow(workflow)


def test_repeat_is_not_a_fabricated_document_item():
    workflow = repeat_definition()
    workflow["tasks"][1]["inputs"] = [{
        **state_binding(), "source": {"kind": "loop_item", "loop_id": "repeat", "scope": "current"},
    }]
    with pytest.raises(WorkflowDefinitionError, match="enclosing For each"):
        compile_workflow_flow(workflow)


def test_for_each_can_read_an_exact_nonpartial_repeat_collection():
    workflow = repeat_definition()
    repeat = add_data_state(workflow, "records")
    repeat["body"]["nodes"].append({
        "id": "each", "kind": "for_each", "max_items": 500, "item_key": "source_identity",
        "inputs": [state_binding(state_name="data", name="rows", kind="records")],
        "iterable": {"kind": "input", "name": "rows"},
        "body": {"id": "each-body", "nodes": [], "outputs": []},
    })
    compiled = compile_workflow_flow(workflow)
    assert compiled["node_loop_ids"]["each"] == ["repeat"]
    assert compiled["nodes"]["each"]["node"]["max_items"] == 500


def test_saved_record_reporting_can_bind_repeat_collection_without_a_new_exporter():
    workflow = repeat_definition()
    repeat = add_data_state(workflow, "records")
    report = instruction_task("report", {"kind": "text"}, [state_binding(state_name="data", kind="records")])
    report["input_processing"] = "saved_record_report"
    workflow["tasks"].append(report)
    repeat["body"]["nodes"].append({"id": "report-node", "kind": "task", "task_id": "report"})
    assert compile_workflow_flow(workflow)["task_nodes"]["report"] == "report-node"


def test_saved_output_publication_accepts_repeat_records_only_through_final_node_export():
    workflow = repeat_definition()
    add_data_state(workflow, "records")
    publish = instruction_task("publish", {"kind": "text"}, [node_binding("repeat", "rows", "data", "records")])
    publish["publication"] = {"source_kind": "saved_output", "artifact_format": "json"}
    workflow["tasks"].append(publish)
    workflow["flow"]["nodes"].append({"id": "publish-node", "kind": "task", "task_id": "publish"})
    assert compile_workflow_flow(workflow)["task_nodes"]["publish"] == "publish-node"
    publish["inputs"][0]["source"] = state_binding(state_name="data")["source"]
    with pytest.raises(WorkflowDefinitionError, match="enclosing Repeat"):
        compile_workflow_flow(workflow)


def test_repeat_export_cycle_is_rejected_without_recursive_overflow():
    workflow = repeat_definition()
    workflow["flow"]["nodes"][1]["body"]["outputs"][0]["source"] = node_binding("repeat", "cycle", "decision")["source"]
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_lifetime_repeat_index_changes_execution_but_retry_changes_only_attempt():
    workflow = repeat_definition()
    first = [{"loop_id": "repeat", "iteration": 0}]
    second = [{"loop_id": "repeat", "iteration": 1}]
    identifier = workflow_execution_id(workflow, "run", "body-node", first)
    assert identifier != workflow_execution_id(workflow, "run", "body-node", second)
    identities = [
        workflow_node_identity(
            workflow, "run", "body-node", identifier, attempt, task_id="body", iteration_path=first,
        ) for attempt in (1, 2)
    ]
    assert identities[0]["execution_id"] == identities[1]["execution_id"]
    assert identities[0]["iteration_path"] == identities[1]["iteration_path"] == first
    assert identities[0]["attempt"] != identities[1]["attempt"]
    assert workflow_execution_id(workflow, "run", "body-node", [{"loop_id": "repeat", "iteration": 1000}])


@pytest.mark.parametrize("path", [
    [{"loop_id": "repeat", "iteration": -1}],
    [{"loop_id": "repeat", "iteration": True}],
    [{"loop_id": "repeat", "iteration": 5000}],
    [{"loop_id": "repeat", "iteration": 0, "batch": 1}],
    [{"loop_id": "repeat", "iteration": 0, "item_id": "a" * 64, "index": 0}],
    [{"loop_id": "repeat", "iteration": 0}, {"loop_id": "repeat", "iteration": 1}],
])
def test_malformed_repeat_frames_are_rejected(path):
    with pytest.raises(ValueError):
        normalize_workflow_iteration_path(path)


def test_definition_ancestry_and_frame_kind_are_part_of_identity():
    workflow = repeat_definition()
    with pytest.raises(ValueError, match="For-each|Repeat"):
        workflow_execution_id(workflow, "run", "body-node", [{"loop_id": "repeat", "index": 0, "item_id": "a" * 64}])
    with pytest.raises(ValueError, match="ancestors"):
        workflow_execution_id(workflow, "run", "body-node", [])
    with pytest.raises(ValueError, match="ancestors"):
        workflow_execution_id(workflow, "run", "repeat", [{"loop_id": "repeat", "iteration": 0}])
    workflow["limits"]["max_executions"] = 10
    with pytest.raises(ValueError, match="execution limit"):
        workflow_execution_id(workflow, "run", "body-node", [{"loop_id": "repeat", "iteration": 10}])


def test_mixed_for_each_repeat_path_preserves_for_each_frame():
    workflow = repeat_definition()
    child = workflow["flow"]
    child["id"] = "outer-body"
    child["outputs"] = []
    workflow["flow"] = {"id": "root", "nodes": [{
        "id": "outer", "kind": "for_each", "max_items": 500, "item_key": "source_identity", "inputs": [],
        "iterable": {"kind": "documents", "documents": []}, "body": child,
    }], "outputs": []}
    compile_workflow_flow(workflow)
    item = {"loop_id": "outer", "item_id": "a" * 64, "index": 3}
    path = [item, {"loop_id": "repeat", "iteration": 1001}]
    assert normalize_workflow_iteration_path(path) == path
    assert workflow_execution_id(workflow, "run", "body-node", path)
    assert item == {"loop_id": "outer", "item_id": "a" * 64, "index": 3}
    workflow["tasks"].append(instruction_task("deep", {"kind": "text"}, [state_binding()]))
    inner = {
        "id": "inner", "kind": "for_each", "max_items": 10, "item_key": "source_identity", "inputs": [],
        "iterable": {"kind": "documents", "documents": []},
        "body": {
            "id": "inner-body", "nodes": [{"id": "deep-node", "kind": "task", "task_id": "deep"}],
            "outputs": [],
        },
    }
    child["nodes"][1]["body"]["nodes"].insert(0, inner)
    compiled = compile_workflow_flow(workflow)
    assert compiled["node_loop_ids"]["deep-node"] == ["outer", "repeat", "inner"]
    mixed = [*path, {"loop_id": "inner", "item_id": "b" * 64, "index": 2}]
    assert workflow_execution_id(workflow, "run", "deep-node", mixed)
    with pytest.raises(ValueError):
        normalize_workflow_iteration_path([*mixed, {"loop_id": "extra", "iteration": 0}])
    inner["body"]["nodes"] = [{
        "id": "extra", "kind": "for_each", "max_items": 1, "item_key": "source_identity", "inputs": [],
        "iterable": {"kind": "documents", "documents": []},
        "body": {"id": "extra-body", "nodes": inner["body"]["nodes"], "outputs": []},
    }]
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_repeat_state_source_does_not_accept_caller_selected_execution_or_run():
    binding = state_binding()
    binding["source"]["run_id"] = "foreign-run"
    with pytest.raises(WorkflowDefinitionError, match="unsupported fields"):
        normalize_flow_bindings([binding])


def test_nested_repeat_uses_outer_state_without_mutating_its_scope():
    workflow = repeat_definition()
    outer = workflow["flow"]["nodes"][1]
    inner = copy.deepcopy(outer)
    inner["id"] = "inner"
    inner["state"][0]["initial"] = state_binding()["source"]
    inner["body"] = {
        "id": "inner-body", "nodes": [{"id": "inner-node", "kind": "task", "task_id": "inner-task"}],
        "outputs": [node_binding("inner-node", "decision_after")],
    }
    workflow["tasks"].append(instruction_task(
        "inner-task", {"kind": "json", "schema": DECISION_SCHEMA}, [state_binding(loop_id="inner")],
    ))
    outer["body"]["nodes"].append(inner)
    outer["body"]["outputs"][0]["source"] = node_binding("inner", "next", "decision")["source"]
    compiled = compile_workflow_flow(workflow)
    assert compiled["node_loop_ids"]["inner-node"] == ["repeat", "inner"]
    path = [{"loop_id": "repeat", "iteration": 1000}, {"loop_id": "inner", "iteration": 25}]
    assert workflow_execution_id(workflow, "run", "inner-node", path)


def test_legacy_for_each_execution_hash_is_unchanged():
    # Captured with functions_workflow_identity.py from merged M4C-2 commit 80f88903.
    workflow = {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "tasks": [{
            "id": "body", "instructions": "Use declared saved inputs.",
            "inputs": [], "output_contract": {"kind": "text"},
        }],
        "flow": {"id": "root", "nodes": [{
            "id": "each", "kind": "for_each", "inputs": [],
            "iterable": {"kind": "documents", "documents": [
                {"scope_type": "personal", "document_id": "document-1"},
            ]},
            "item_key": "source_identity", "max_items": 500,
            "body": {
                "id": "body-region", "nodes": [{"id": "body-node", "kind": "task", "task_id": "body"}],
                "outputs": [],
            },
        }], "outputs": []},
    }
    compile_workflow_flow(workflow)
    assert workflow_execution_id(
        workflow, "run", "body-node", [{"loop_id": "each", "item_id": "a" * 64, "index": 0}],
    ) == "7b723c1ff080e77ea7be1ae27570cb88841bc5dbeba00510edfc444267909785"


@pytest.mark.parametrize("runner_type", ["model", "local", "foundry", "hosted"])
def test_repeat_admission_requires_locally_metered_body_runners(runner_type):
    workflow = repeat_definition()
    workflow["runner_type"] = "agent"
    workflow["selected_agent"] = {"name": "hosted-seed"}
    workflow["tasks"][1]["runner"] = {
        "type": "model" if runner_type == "model" else "agent",
        **({} if runner_type == "model" else {"selected_agent": {"name": runner_type}}),
    }
    checked = []

    def resolve(selected, **kwargs):
        assert kwargs["user_id"] == "owner"
        checked.append(selected["name"])
        return {"agent_type": selected["name"]}

    if runner_type in {"foundry", "hosted"}:
        with pytest.raises(WorkflowInputError, match="locally metered"):
            validate_workflow_loop_runners(workflow, actor_user_id="owner", settings={}, resolve_agent=resolve)
    else:
        validate_workflow_loop_runners(workflow, actor_user_id="owner", settings={}, resolve_agent=resolve)
    assert "hosted-seed" not in checked
    assert checked == ([] if runner_type == "model" else [runner_type])


def test_repeat_runtime_rechecks_agent_type_without_changing_ordinary_steps():
    workflow = repeat_definition()
    execution = SimpleNamespace(workflow=workflow, node={"task_id": "body"}, iteration_path=[])
    with workflow_execution_scope(execution):
        assert_workflow_loop_agent_type("foundry")
        execution.iteration_path = [{"loop_id": "repeat", "iteration": 0}]
        assert_workflow_loop_agent_type("local")
        with pytest.raises(WorkflowInputError, match="locally metered"):
            assert_workflow_loop_agent_type("foundry")
