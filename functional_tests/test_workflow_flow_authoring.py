# test_workflow_flow_authoring.py
"""
Offline compiler contracts for the shared List/Flow draft-editing commands.
Version: 0.261.122
Implemented in: 0.261.122

The companion Node test applies real TypeScript commands to the same canonical
JSON fixture. These tests compile that exact expected definition, including
incomplete/invalid boundary cases, without running a workflow or loading Azure.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))

# Production imports follow the same offline path setup as test_workflow_loop_schema.
from functions_workflow_definitions import (
    WORKFLOW_DEFINITION_FIELDS, WorkflowDefinitionError, normalize_workflow_definition,
    workflow_definition_revision,
)
from functions_workflow_flow import compile_workflow_flow, evaluate_predicate


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "workflow_flow_authoring.json"
CONTRACT = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def definition(edited=True):
    value = copy.deepcopy(CONTRACT["initial"])
    if edited:
        value.update(copy.deepcopy(CONTRACT["expected"]))
    return value


def node(workflow, identifier):
    def walk(region):
        for current in region["nodes"]:
            if current["id"] == identifier:
                return current
            for child in (
                [current["then"], current["else"]] if current["kind"] == "if"
                else [current["body"]] if current["kind"] in {"for_each", "repeat_until"}
                else []
            ):
                found = walk(child)
                if found is not None:
                    return found
        return None

    found = walk(workflow["flow"])
    assert found is not None, identifier
    return found


def task(workflow, identifier):
    return next(current for current in workflow["tasks"] if current["id"] == identifier)


def binding(identifier, name="input", *, output="json", kind="json"):
    return {
        "name": name,
        "source": {"kind": "node_output", "node_id": identifier, "output": output, "scope": "current"},
        "required": True, "expected_kind": kind, "allow_partial": False,
    }


def literal_condition():
    return {"op": "eq", "left": {"literal": True}, "right": {"literal": True}}


def simple_definition(count=1):
    workflow = definition(False)
    template = task(workflow, "spare-task")
    workflow["tasks"] = [
        {**copy.deepcopy(template), "id": f"catalogue-{index}", "name": f"Task {index}", "order": index + 1}
        for index in range(count)
    ]
    workflow["flow"] = {
        "id": "root",
        "nodes": [
            {"id": f"node-{index}", "kind": "task", "task_id": current["id"]}
            for index, current in enumerate(workflow["tasks"])
        ],
        "outputs": [],
    }
    return workflow


def empty_if(identifier):
    return {
        "id": identifier, "kind": "if", "inputs": [], "condition": literal_condition(),
        "then": {"id": f"{identifier}-then", "nodes": []},
        "else": {"id": f"{identifier}-else", "nodes": []},
        "join": {"id": f"{identifier}-join", "exports": []},
    }


def mixed_frames(kinds):
    workflow = simple_definition(2)
    schema = task(definition(), "seed-task")["output_contract"]
    workflow["tasks"][0]["output_contract"] = copy.deepcopy(schema)
    region = workflow["flow"]
    leaf = region["nodes"].pop()
    for index, kind in enumerate(kinds):
        identifier = f"frame-{index}"
        body = {"id": f"{identifier}-body", "nodes": [], "outputs": []}
        if kind == "for_each":
            current = {
                "id": identifier, "kind": kind, "inputs": [],
                "iterable": {"kind": "documents", "documents": [
                    {"document_id": "fictional-document", "scope_type": "personal"},
                ]},
                "item_key": "source_identity", "max_items": 1, "body": body,
            }
        else:
            current = {
                "id": identifier, "kind": kind, "max_iterations": 1,
                "state": [{
                    "name": "review", "initial": binding("node-0")["source"],
                    "next": "retained", "output_contract": copy.deepcopy(schema),
                }],
                "body": body,
                "until": {"op": "eq", "left": {"input": "review", "path": "/ready"}, "right": {"literal": True}},
                "exports": [],
            }
            body["outputs"] = [{
                "name": "retained",
                "source": {"kind": "repeat_state", "loop_id": identifier, "state_name": "review", "scope": "current"},
                "required": True, "expected_kind": "json", "allow_partial": False,
            }]
        region["nodes"].append(current)
        region = body
    region["nodes"].append(leaf)
    return workflow


@pytest.mark.parametrize("edited", [False, True], ids=["before-commands", "after-commands"])
def test_shared_canonical_definition_compiles_without_mutation_or_loss(edited):
    workflow = definition(edited)
    before = copy.deepcopy(workflow)
    compiled = compile_workflow_flow(workflow)
    assert workflow == before
    assert compiled["flow"] == workflow["flow"]
    assert compiled["tasks"] == workflow["tasks"]
    assert compiled["limits"] == workflow["limits"]
    assert compiled["task_nodes"]["spare-task"] == "constructor"
    assert all(task_id != node_id for task_id, node_id in compiled["task_nodes"].items())
    assert workflow["definition_revision"] == CONTRACT["initial"]["definition_revision"]
    assert workflow["future_envelope"] == CONTRACT["initial"]["future_envelope"]
    assert workflow["metadata"]["legacy"]["values"] == [False, 0, None, "雪"]


def test_compiler_order_follows_regions_not_the_task_catalogue():
    workflow = definition()
    compiled = compile_workflow_flow(workflow)
    assert compiled["tasks"][0]["id"] == "report-task"
    assert compiled["flow"]["nodes"][0]["task_id"] == "seed-task"
    assert compiled["successor"]["seed-node"] == "choice"
    assert compiled["successor"]["constructor"] == "yes-node"
    assert compiled["successor"]["route-node"] == "report-node"
    assert compiled["nodes"]["constructor"]["region_id"] == "then-region"
    assert compiled["nodes"]["choice-join"]["if_id"] == "choice"
    assert compiled["nodes"]["route-node"]["node"]["target"] == {"node_id": "report-node"}
    assert ("choice-join", "verdict") in compiled["definite_outputs"]
    assert ("collect-node", "records") in compiled["definite_outputs"]
    assert ("repeat-node", "final_decision") in compiled["definite_outputs"]


def test_actual_typescript_command_save_payload_has_the_canonical_compiler_meaning():
    completed = subprocess.run(
        ["node", str(Path(__file__).with_name("test_workflow_flow_authoring_commands.js")), "--emit-canonical-payload"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    actual = compile_workflow_flow(payload)
    expected = compile_workflow_flow(definition())
    for field in (
        "flow", "limits", "nodes", "regions", "task_nodes", "successor", "dependencies",
        "definite_outputs", "possible_outputs", "node_loop_ids", "loop_item_schemas",
    ):
        assert actual[field] == expected[field], field
    for saved, authored in zip(actual["tasks"], expected["tasks"], strict=True):
        saved, authored = copy.deepcopy(saved), copy.deepcopy(authored)
        assert saved.pop("runner") == {"type": "inherit", "model_endpoint_id": "", "model_id": ""}
        assert authored.pop("runner") == {"type": "inherit"}
        assert saved == authored
    assert payload["definition_revision"] == CONTRACT["initial"]["definition_revision"]
    assert payload["metadata"] == CONTRACT["initial"]["metadata"]
    assert payload["future_envelope"] == CONTRACT["initial"]["future_envelope"]
    assert not {"positions", "viewport", "selectedId", "fieldBuffers", "compilerPreview"}.intersection(payload)


def test_authored_changes_change_the_digest_but_not_the_original_cas_token():
    original, edited = definition(False), definition()
    assert workflow_definition_revision(original) != workflow_definition_revision(edited)
    assert edited["definition_revision"] == original["definition_revision"]
    assert original == CONTRACT["initial"]


def test_actual_typescript_preview_preserves_authored_digest_and_compiler_meaning_without_opaque_metadata():
    completed = subprocess.run(
        ["node", str(Path(__file__).with_name("test_workflow_flow_authoring_commands.js")), "--emit-canonical-preview"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert set(result["fields"]) == set(WORKFLOW_DEFINITION_FIELDS)
    payload, preview = result["payload"], result["preview"]
    assert payload["future_envelope"] == CONTRACT["initial"]["future_envelope"]
    assert payload["metadata"] == CONTRACT["initial"]["metadata"]
    assert "future_envelope" not in preview and "metadata" not in preview
    assert preview["definition_revision"] == payload["definition_revision"]
    assert workflow_definition_revision(preview) == workflow_definition_revision(payload)
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        normalize_workflow_definition(payload, {}, payload["tasks"], user_id="owner")
    normalized = normalize_workflow_definition(preview, {}, preview["tasks"], user_id="owner")
    actual = compile_workflow_flow({**preview, **normalized})
    expected = compile_workflow_flow(payload)
    for field in ("flow", "tasks", "limits", "nodes", "regions", "task_nodes", "successor", "dependencies"):
        assert actual[field] == expected[field], field


def test_typed_current_item_repeat_state_join_and_output_selectors_are_exact():
    workflow = definition()
    compiled = compile_workflow_flow(workflow)
    assert compiled["node_loop_ids"]["each-task-node"] == ["each-node"]
    assert compiled["node_loop_ids"]["repeat-task-node"] == ["repeat-node"]
    assert task(workflow, "each-task")["document_action"] == {
        "type": "analyze", "target_mode": "current_item", "loop_id": "each-node", "analysis_mode": "combined",
    }
    assert task(workflow, "repeat-task")["inputs"][0]["source"] == {
        "kind": "repeat_state", "loop_id": "repeat-node", "state_name": "review", "scope": "current",
    }
    predicate = compiled["nodes"]["route-node"]["node"]["condition"]
    assert evaluate_predicate(predicate, {"decision": {"ready": False}}) is False
    assert evaluate_predicate(predicate, {"decision": {"ready": True}}) is True
    assert node(workflow, "repeat-node")["state"][0]["initial"]["node_id"] == "seed-node"


@pytest.mark.parametrize("mutation", [
    lambda wf: task(wf, "report-task")["inputs"][0]["source"].update(node_id="missing"),
    lambda wf: task(wf, "report-task")["inputs"][0]["source"].update(node_id="yes-node", output="text"),
    lambda wf: node(wf, "choice")["condition"]["left"].update(path="/undeclared"),
    lambda wf: node(wf, "choice")["inputs"][0].update(expected_kind="text"),
    lambda wf: node(wf, "choice")["join"]["exports"][0]["then"].update(node_id="no-node"),
    lambda wf: node(wf, "route-node")["target"].update(node_id="seed-node"),
    lambda wf: node(wf, "route-node")["target"].update(node_id="yes-node"),
    lambda wf: node(wf, "seed-node").update(run_when=literal_condition()),
    lambda wf: node(wf, "each-task-node").update(run_when=literal_condition()),
    lambda wf: node(wf, "each-node")["body"]["outputs"][0]["source"].update(node_id="seed-node", output="json"),
    lambda wf: node(wf, "collect-node")["source"].update(output="undeclared"),
    lambda wf: node(wf, "collect-node")["output_contract"].update(kind="document_results"),
    lambda wf: task(wf, "each-task")["document_action"].update(loop_id="repeat-node"),
    lambda wf: node(wf, "repeat-node")["state"][0].update(next="undeclared"),
    lambda wf: node(wf, "repeat-node")["state"][0]["initial"].update(node_id="constructor", output="text"),
    lambda wf: node(wf, "repeat-node")["until"]["left"].update(input="decision_after"),
    lambda wf: node(wf, "repeat-node")["exports"][0].update(output="undeclared"),
    lambda wf: task(wf, "report-task")["inputs"][2]["source"].update(node_id="repeat-task-node", output="json"),
    lambda wf: task(wf, "report-task")["inputs"][2].update(
        source={"kind": "repeat_state", "loop_id": "repeat-node", "state_name": "review", "scope": "current"},
    ),
], ids=[
    "missing-producer", "branch-escape", "undeclared-schema-field", "typed-input-mismatch",
    "wrong-join-branch", "backward-route", "route-into-branch", "conditional-required-producer",
    "conditional-required-body-output", "body-output-from-outside", "missing-collect-output",
    "collect-kind-coercion", "analyze-not-a-document-loop", "missing-next-state",
    "wrong-initial-state-kind", "until-not-a-state-alias", "missing-final-export",
    "repeat-body-escape", "repeat-state-outside-body",
])
def test_compiler_rejects_unretargeted_broken_references_and_typed_schema_errors(mutation):
    workflow = definition()
    mutation(workflow)
    before = copy.deepcopy(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)
    assert workflow == before


@pytest.mark.parametrize("identifier", ["seed-node", "each-node", "collect-node", "repeat-node"])
def test_reference_breaking_reorders_are_drafts_not_executable_definitions(identifier):
    workflow = definition()
    current = node(workflow, identifier)
    workflow["flow"]["nodes"].remove(current)
    workflow["flow"]["nodes"].append(current)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("maximum", [1, 1000])
def test_repeat_explicit_batch_boundaries_remain_compiler_legal(maximum):
    workflow = definition()
    node(workflow, "repeat-node")["max_iterations"] = maximum
    assert compile_workflow_flow(workflow)["nodes"]["repeat-node"]["node"]["max_iterations"] == maximum


@pytest.mark.parametrize("maximum", [None, 0, -1, True, "", "25", 1001])
def test_incomplete_repeat_maximum_is_not_replaced_with_an_administrator_default(maximum):
    workflow = definition()
    current = node(workflow, "repeat-node")
    if maximum is None:
        current.pop("max_iterations")
    else:
        current["max_iterations"] = maximum
    before = copy.deepcopy(workflow)
    with pytest.raises(WorkflowDefinitionError, match="max_iterations"):
        compile_workflow_flow(workflow)
    assert workflow == before


@pytest.mark.parametrize("maximum", [1, 5000])
def test_for_each_item_boundaries_do_not_expand_the_saved_body(maximum):
    workflow = definition()
    node(workflow, "each-node")["max_items"] = maximum
    compiled = compile_workflow_flow(workflow)
    assert len(compiled["nodes"]["each-node"]["node"]["body"]["nodes"]) == 1
    assert len(compiled["nodes"]) == 13


@pytest.mark.parametrize("count,valid", [(100, True), (101, False)])
def test_task_catalogue_hard_limit_is_one_hundred(count, valid):
    workflow = simple_definition(count)
    if valid:
        assert len(compile_workflow_flow(workflow)["tasks"]) == count
    else:
        with pytest.raises(WorkflowDefinitionError, match="100 tasks"):
            compile_workflow_flow(workflow)


@pytest.mark.parametrize("task_count,valid", [(3, True), (4, False)])
def test_structural_limit_counts_root_branch_regions_and_joins(task_count, valid):
    workflow = simple_definition(task_count)
    workflow["flow"]["nodes"].extend(empty_if(f"if-{index}") for index in range(63))
    if valid:
        compiled = compile_workflow_flow(workflow)
        assert len(compiled["nodes"]) + len(compiled["regions"]) == 256
    else:
        with pytest.raises(WorkflowDefinitionError, match="256"):
            compile_workflow_flow(workflow)


@pytest.mark.parametrize("depth,valid", [(4, True), (5, False)])
def test_region_depth_counts_root_as_one(depth, valid):
    workflow = simple_definition()
    region = workflow["flow"]
    leaf = region["nodes"].pop()
    for index in range(depth - 1):
        current = empty_if(f"depth-{index}")
        region["nodes"].append(current)
        region = current["then"]
    region["nodes"].append(leaf)
    if valid:
        compiled = compile_workflow_flow(workflow)
        assert compiled["nodes"]["node-0"]["region_id"] == f"depth-{depth - 2}-then"
    else:
        with pytest.raises(WorkflowDefinitionError, match="depth 4"):
            compile_workflow_flow(workflow)


@pytest.mark.parametrize("kinds", [
    ["for_each", "repeat_until", "for_each"],
    ["repeat_until", "for_each", "repeat_until"],
])
def test_three_mixed_frames_are_legal_but_a_fourth_cannot_be_authored(kinds):
    workflow = mixed_frames(kinds)
    compiled = compile_workflow_flow(workflow)
    assert compiled["node_loop_ids"]["node-1"] == ["frame-0", "frame-1", "frame-2"]
    with pytest.raises(WorkflowDefinitionError, match="depth 4"):
        compile_workflow_flow(mixed_frames([*kinds, "repeat_until"]))


@pytest.mark.parametrize("mutation", [
    lambda wf: node(wf, "seed-node").update(position={"x": 10, "y": 20}),
    lambda wf: node(wf, "choice")["join"].update(future_join=True),
    lambda wf: node(wf, "each-node")["body"].update(viewport={"zoom": 2}),
    lambda wf: task(wf, "report-task").update(future_task_behavior=True),
    lambda wf: task(wf, "report-task")["inputs"][0]["source"].update(future_scope=True),
    lambda wf: wf["limits"].update(future_budget=True),
    lambda wf: node(wf, "repeat-node").update(exhaustion="complete"),
], ids=["geometry", "join", "region", "task", "binding", "limits", "repeat-exhaustion"])
def test_unknown_executable_fields_are_rejected_not_silently_normalized(mutation):
    workflow = definition()
    mutation(workflow)
    before = copy.deepcopy(workflow)
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        compile_workflow_flow(workflow)
    assert workflow == before


@pytest.mark.parametrize("mutation", [
    lambda wf: node(wf, "choice")["join"].update(id="root"),
    lambda wf: node(wf, "choice")["else"].update(id="then-region"),
    lambda wf: wf["tasks"].append(copy.deepcopy(wf["tasks"][0])),
    lambda wf: node(wf, "seed-node").update(task_id="missing"),
    lambda wf: node(wf, "constructor").update(task_id="seed-task"),
], ids=["join-collision", "region-collision", "catalogue-collision", "missing-catalogue", "reused-catalogue"])
def test_duplicate_or_missing_executable_identities_cannot_compile(mutation):
    workflow = definition()
    mutation(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("policy", ["submitted", "approved", "indexed_ready"])
def test_saved_output_publication_configuration_uses_exact_required_records(policy):
    workflow = definition()
    current = task(workflow, "report-task")
    current["inputs"] = [binding("collect-node", "records", output="records", kind="records")]
    current["publication"] = {
        "source_kind": "saved_output", "artifact_format": "json",
        "workspace_scope": "personal", "completion_policy": policy,
    }
    compiled = compile_workflow_flow(workflow)
    assert compiled["tasks"][0]["publication"] == current["publication"]
    current["inputs"][0]["source"] = {
        "kind": "repeat_state", "loop_id": "repeat-node", "state_name": "review", "scope": "current",
    }
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", __file__]))
