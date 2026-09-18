# test_workflow_loop_schema.py
"""
Isolated production-backed compiler and iteration identity regression tests.
Version: 0.261.117
Implemented in: 0.261.117

Validates additive loop schemas, frozen-source descriptors, lexical availability,
exact collection types, explicit reporting policies and stable identities.
No app, Azure or storage imports.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Pure production imports follow the worktree module-path setup.
from functions_workflow_definitions import (
    WorkflowDefinitionError, normalize_workflow_definition, workflow_definition_revision,
)
from functions_workflow_flow import compile_workflow_flow, evaluate_predicate, normalize_flow_bindings
from functions_workflow_identity import (
    normalize_workflow_iteration_path, workflow_execution_id, workflow_node_identity,
)
from functions_workflow_loop_schema import normalize_workflow_iterable


def contract(kind="records"):
    return {
        "kind": kind,
        "schema": {
            "type": "array", "items": {
                "type": "object", "properties": {
                    "amount": {"type": "number"}, "approved": {"type": "boolean"},
                    "document_id": {"type": "string"},
                },
            },
            "minItems": 0,
        },
        "require_complete_coverage": True, "allow_partial": False,
    }


def binding(node_id, name="rows", output="records", *, required=True, expected_kind="records", allow_partial=False):
    return {
        "name": name, "source": {"kind": "node_output", "node_id": node_id, "output": output, "scope": "current"},
        "required": required, "expected_kind": expected_kind, "allow_partial": allow_partial,
    }


def item_binding(loop_id="each_source", name="item"):
    return {
        "name": name, "source": {"kind": "loop_item", "loop_id": loop_id, "scope": "current"},
        "required": True, "expected_kind": "json", "allow_partial": False,
    }


def task(identifier, *, inputs=None, output_contract=None):
    return {
        "id": identifier, "type": "instructions", "name": identifier, "instructions": "Use exact declared data.",
        "runner": {"type": "inherit"}, "document_action": {"type": "none"},
        "inputs": inputs or [], "output_contract": output_contract or contract(),
    }


def task_node(identifier):
    return {"id": f"{identifier}_node", "kind": "task", "task_id": identifier}


def loop(identifier="each_source", *, nodes=None, outputs=None, iterable=None, inputs=None, max_items=500):
    return {
        "id": identifier, "kind": "for_each", "inputs": inputs or [],
        "iterable": iterable if iterable is not None else {
            "kind": "documents", "documents": [{"document_id": "source-a", "scope_type": "personal"}],
        },
        "item_key": "source_identity", "max_items": max_items,
        "body": {"id": f"{identifier}_body", "nodes": nodes or [], "outputs": outputs or []},
    }


def collect(loop_id="each_source", identifier="collected", *, output="rows", kind="records"):
    return {
        "id": identifier, "kind": "collect", "source": {"loop_id": loop_id, "output": output},
        "output_contract": contract(kind),
    }


def definition(*, kind="records"):
    selector = "records" if kind == "records" else "documents"
    return {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "tasks": [
            task("analyze", inputs=[item_binding()], output_contract=contract(kind)),
            task("report", inputs=[binding("collected", output=selector, expected_kind=kind)],
                 output_contract={"kind": "text"}),
        ],
        "flow": {
            "id": "root", "nodes": [
                loop(nodes=[task_node("analyze")], outputs=[binding("analyze_node", output=selector, expected_kind=kind)]),
                collect(kind=kind), task_node("report"),
            ],
            "outputs": [binding("collected", output=selector, expected_kind=kind)],
        },
    }


def literal_condition():
    return {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}}


def item_condition(path="/index", *, name="item", literal=0, op="gte"):
    return {"op": op, "left": {"input": name, "path": path}, "right": {"literal": literal}}


def branch_node():
    return {
        "id": "choice", "kind": "if", "inputs": [item_binding("inner")],
        "condition": item_condition("/value/approved", literal=True, op="eq"),
        "then": {"id": "yes_region", "nodes": [task_node("yes")]},
        "else": {"id": "no_region", "nodes": [task_node("no")]},
        "join": {"id": "joined", "exports": [{
            "name": "rows", "expected_kind": "records", "required": True,
            "then": {"node_id": "yes_node", "output": "records"},
            "else": {"node_id": "no_node", "output": "records"},
        }]},
    }


def nested_definition():
    inner = loop(
        "inner", nodes=[branch_node()], outputs=[binding("joined", output="rows")],
        iterable={"kind": "input", "name": "rows"}, inputs=[binding("seed_node")],
    )
    outer = loop(
        "outer", nodes=[inner, collect("inner", "inner_collect")], outputs=[binding("inner_collect")],
    )
    workflow = definition()
    workflow["tasks"] = [
        task("seed"), task("yes", inputs=[item_binding("inner"), item_binding("outer", "document")]),
        task("no"), task("report", inputs=[binding("outer_collect")], output_contract={"kind": "text"}),
    ]
    workflow["flow"]["nodes"] = [task_node("seed"), outer, collect("outer", "outer_collect"), task_node("report")]
    workflow["flow"]["outputs"] = [binding("outer_collect")]
    return workflow


def query(*, mode="all_matches", content=None, count=None):
    value = {
        "kind": "workspace_query", "scopes": [{"scope_type": "personal"}],
        "filters": {"tags": ["review"]}, "selection": {"mode": mode},
    }
    if content is not None:
        value["content"] = {"mode": content, "query": "retention policy"}
    if count is not None:
        value["selection"]["count"] = count
    return value


def frame(loop_id="each_source", *, index=0, item_id="a" * 64):
    return {"loop_id": loop_id, "item_id": item_id, "index": index}


def normalize(workflow):
    return normalize_workflow_definition(workflow, {}, copy.deepcopy(workflow["tasks"]), user_id="owner")


def report_definition(source_kind="records"):
    workflow = definition()
    source_contract = {"kind": "text"} if source_kind == "text" else contract(source_kind)
    workflow["tasks"] = [
        task("source", output_contract=source_contract),
        task("report", inputs=[binding("source_node", output="authoritative", expected_kind="any")],
             output_contract={"kind": "text"}),
    ]
    workflow["tasks"][1]["input_processing"] = "saved_record_report"
    workflow["flow"] = {"id": "root", "nodes": [task_node("source"), task_node("report")], "outputs": []}
    return workflow


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_definitions_keep_absent_and_explicit_inputs_and_no_loop_defaults(version):
    workflow = {"definition_version": version, "tasks": [{"id": "one", "instructions": "Legacy instructions."}]}
    if version == 2:
        workflow["tasks"].append({"id": "two", "instructions": "Explicitly empty inputs.", "inputs": []})
    saved = normalize(workflow)
    assert saved["tasks"] == workflow["tasks"]
    assert "flow" not in saved and "limits" not in saved
    assert "inputs" not in saved["tasks"][0]
    assert not {"workflow_max_loop_items", "max_items", "node_loop_ids"}.intersection(saved)


def test_old_empty_path_revisions_and_execution_digests_are_unchanged():
    workflow = {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "tasks": [{"id": "legacy-task", "instructions": "Preserve legacy behavior."}],
        "flow": {"id": "root", "nodes": [{"id": "legacy-node", "kind": "task", "task_id": "legacy-task"}], "outputs": []},
    }
    saved = normalize(workflow)
    expected = {
        "definition_version": 3, "reference_inputs": [], "durable_execution": True,
        "tasks": [{"id": "legacy-task", "instructions": "Preserve legacy behavior.", "inputs": []}],
        "flow": workflow["flow"], "limits": {"max_executions": 5000, "deadline_seconds": 86400},
    }
    assert saved == expected
    compiled = compile_workflow_flow(workflow)
    workflow.update({key: compiled[key] for key in ("flow", "tasks", "limits")})
    assert workflow_definition_revision(workflow) == "57b2da27fef1f05b1e8e622dd6e7938401f547c8ed1e1360458b37175dc55287"
    assert workflow_execution_id(workflow, "run", "root") == "178c8469360095e478e8ac71be22b62b051bd464aac5be16d262f16eaf87488f"
    expected_execution = "bc96200beeef1cda51152404246135d2e4cfec023732d1121a9eaeac56b324b7"
    assert workflow_execution_id(workflow, "run", "legacy-node", []) == expected_execution
    assert workflow_node_identity(workflow, "run", "legacy-node", expected_execution, 1, task_id="legacy-task")["iteration_path"] == []
    assert compiled["flow"]["outputs"] == [] and compiled["node_loop_ids"] == {"root": [], "legacy-node": []}


@pytest.mark.parametrize("mode", ["full", "saved_record_report"])
def test_explicit_input_processing_roundtrips_without_adding_other_task_defaults(mode):
    workflow = definition()
    workflow["tasks"][1]["input_processing"] = mode
    saved = normalize(workflow)
    assert saved["tasks"][1]["input_processing"] == mode
    assert "input_processing" not in saved["tasks"][0]
    assert compile_workflow_flow({**workflow, **saved})["tasks"] == saved["tasks"]


def test_absent_input_processing_stays_absent_and_keeps_existing_revision():
    workflow = definition()
    workflow.update(normalize(workflow))
    revision = workflow_definition_revision(workflow)
    task_defaults = copy.deepcopy(workflow["tasks"])
    for current in task_defaults:
        current["input_processing"] = "full"
    saved = normalize_workflow_definition(
        {**workflow, "definition_revision": revision}, workflow, task_defaults, user_id="owner",
    )
    assert all("input_processing" not in current for current in saved["tasks"])
    assert workflow_definition_revision({**workflow, **saved}) == revision


@pytest.mark.parametrize("mode", [None, "", True, 1, [], {}, "FULL", "summary", " saved_record_report "])
@pytest.mark.parametrize("normalizer", [normalize, compile_workflow_flow])
def test_input_processing_rejects_malformed_or_unrecognized_modes(mode, normalizer):
    workflow = definition()
    workflow["tasks"][1]["input_processing"] = mode
    with pytest.raises(WorkflowDefinitionError, match="input_processing"):
        normalizer(workflow)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("mode", ["full", "saved_record_report", None])
def test_input_processing_is_rejected_on_older_definition_versions(version, mode):
    workflow = {
        "definition_version": version,
        "tasks": [{"id": "one", "instructions": "Preserve ordinary task behavior.", "input_processing": mode}],
    }
    with pytest.raises(WorkflowDefinitionError, match="version 3"):
        normalize_workflow_definition(
            workflow, {}, [{"id": "one", "instructions": "Preserve ordinary task behavior."}], user_id="owner",
        )


@pytest.mark.parametrize("kind", ["records", "document_results"])
def test_saved_record_report_accepts_proven_collection_inputs_without_loops(kind):
    workflow = report_definition(kind)
    compiled = compile_workflow_flow(workflow)
    assert compiled["tasks"][1]["input_processing"] == "saved_record_report"
    assert compiled["node_loop_ids"]["report_node"] == []
    workflow["tasks"][1]["inputs"][0]["expected_kind"] = "json"
    compile_workflow_flow(workflow)


@pytest.mark.parametrize("change", [
    lambda current: current.update(publication={}),
    lambda current: current.update(publication=False),
    lambda current: current.pop("document_action"),
    lambda current: current.update(document_action=None),
    lambda current: current.update(document_action={"type": "analyze"}),
    lambda current: current.update(document_action={"type": "extract"}),
    lambda current: current.update(output_contract=contract()),
    lambda current: current.update(output_contract={"kind": "json"}),
    lambda current: current.pop("output_contract"),
])
def test_saved_record_report_requires_no_document_action_publication_or_structured_output(change):
    workflow = report_definition()
    change(workflow["tasks"][1])
    with pytest.raises(WorkflowDefinitionError, match="non-publication"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("source_kind", ["text", "json", "any"])
def test_saved_record_report_does_not_infer_record_semantics_from_json_or_unknown_inputs(source_kind):
    workflow = report_definition(source_kind)
    with pytest.raises(WorkflowDefinitionError, match="node-output records"):
        compile_workflow_flow(workflow)
    workflow["tasks"][1]["input_processing"] = "full"
    compile_workflow_flow(workflow)


def test_saved_record_report_requires_a_real_collection_even_with_a_current_loop_item():
    workflow = report_definition()
    workflow["tasks"][1]["inputs"].append(item_binding())
    workflow["flow"]["nodes"] = [task_node("source"), loop(nodes=[task_node("report")])]
    compile_workflow_flow(workflow)
    workflow["tasks"][1]["inputs"] = [item_binding()]
    with pytest.raises(WorkflowDefinitionError, match="node-output records"):
        compile_workflow_flow(workflow)
    workflow["tasks"][1]["inputs"] = []
    with pytest.raises(WorkflowDefinitionError, match="node-output records"):
        compile_workflow_flow(workflow)


def test_saved_record_report_can_capture_other_inputs_alongside_an_exact_record_input():
    workflow = report_definition()
    workflow["tasks"].append(task("context", output_contract={"kind": "text"}))
    workflow["flow"]["nodes"].insert(0, task_node("context"))
    workflow["tasks"][1]["inputs"].insert(0, binding("context_node", "context", "text", expected_kind="text"))
    compile_workflow_flow(workflow)


def test_saved_record_report_checks_every_selected_join_producer_kind():
    workflow = report_definition()
    workflow["tasks"] = [task("yes"), task("no"), workflow["tasks"][1]]
    choice = branch_node()
    choice.update(inputs=[], condition=literal_condition())
    workflow["flow"]["nodes"] = [choice, task_node("report")]
    workflow["tasks"][2]["inputs"] = [binding("joined", output="rows")]
    compile_workflow_flow(workflow)
    workflow["tasks"][1]["output_contract"] = {"kind": "text"}
    choice["join"]["exports"][0]["expected_kind"] = "any"
    choice["join"]["exports"][0]["else"]["output"] = "text"
    workflow["tasks"][2]["inputs"][0]["expected_kind"] = "any"
    with pytest.raises(WorkflowDefinitionError, match="node-output records"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("kind", ["records", "document_results"])
def test_loop_and_collect_normalize_without_changing_authored_data(kind):
    workflow = definition(kind=kind)
    before = copy.deepcopy(workflow)
    saved = normalize(workflow)
    compiled = compile_workflow_flow({**workflow, **saved})
    assert workflow == before
    assert compiled["flow"] == saved["flow"] and compiled["tasks"] == saved["tasks"]
    assert compiled["node_loop_ids"] == {
        "root": [], "each_source": [], "each_source_body": ["each_source"],
        "analyze_node": ["each_source"], "collected": [], "report_node": [],
    }
    assert compiled["flow"]["nodes"][1]["output_contract"]["kind"] == kind
    assert all("task_id" not in entry["node"] for entry in compiled["nodes"].values() if entry["node"]["kind"] != "task")
    assert compiled["dependencies"]["collected"] == [("each_source", "rows")]


def test_nested_loops_if_joins_ancestor_items_and_exact_collect_exports():
    compiled = compile_workflow_flow(nested_definition())
    scopes = compiled["node_loop_ids"]
    assert scopes["inner"] == ["outer"] and scopes["inner_collect"] == ["outer"]
    assert all(scopes[name] == ["outer", "inner"] for name in ("choice", "joined", "yes_node", "no_node"))
    assert scopes["outer_collect"] == [] and scopes["root"] == []
    assert ("inner_collect", "records") not in compiled["possible_outputs"]
    assert ("outer_collect", "records") in compiled["definite_outputs"]
    assert compiled["loop_item_schemas"]["inner"][0]["properties"]["value"]["properties"]["approved"] == {"type": "boolean"}


@pytest.mark.parametrize("path,literal,op", [
    ("/index", 0, "gte"), ("/key", "stable", "eq"),
    ("/value/document_id", "source-a", "eq"), ("/value/scope_type", "personal", "eq"),
])
def test_conditions_use_the_enclosing_document_item_schema(path, literal, op):
    workflow = definition()
    route = {
        "id": "item_route", "kind": "route", "inputs": [item_binding()],
        "condition": item_condition(path, literal=literal, op=op), "target": {"node_id": "analyze_node"},
    }
    workflow["flow"]["nodes"][0]["body"]["nodes"].insert(0, route)
    compiled = compile_workflow_flow(workflow)
    predicate = compiled["nodes"]["item_route"]["node"]["condition"]
    assert isinstance(evaluate_predicate(predicate, {"item": {
        "index": 0, "key": "stable", "value": {"document_id": "source-a", "scope_type": "personal", "scope_id": "owner"},
    }}), bool)


@pytest.mark.parametrize("path", ["/value/storage_ref", "/value/approved", "", "/value"])
def test_document_item_conditions_reject_undeclared_or_nonscalar_fields(path):
    workflow = definition()
    workflow["flow"]["nodes"][0]["body"]["nodes"][0]["run_when"] = item_condition(path, literal=True, op="eq")
    with pytest.raises(WorkflowDefinitionError, match="schema|scalar"):
        compile_workflow_flow(workflow)


def test_collect_conditions_and_saved_collection_item_conditions_require_declared_schema():
    workflow = definition()
    workflow["flow"]["nodes"][-1]["run_when"] = item_condition("/0/amount", name="rows")
    compile_workflow_flow(workflow)
    workflow["flow"]["nodes"][1]["output_contract"]["schema"]["items"]["properties"].pop("amount")
    with pytest.raises(WorkflowDefinitionError, match="schema"):
        compile_workflow_flow(workflow)
    nested = nested_definition()
    nested["tasks"][0]["output_contract"]["schema"]["items"]["properties"].pop("approved")
    with pytest.raises(WorkflowDefinitionError, match="schema"):
        compile_workflow_flow(nested)


def test_record_item_schema_supports_scalars_and_schema_free_key_index_access():
    workflow = nested_definition()
    condition_node = workflow["flow"]["nodes"][1]["body"]["nodes"][0]["body"]["nodes"][0]
    workflow["tasks"][0]["output_contract"]["schema"]["items"] = {"type": "integer"}
    condition_node["condition"] = item_condition("/value", literal=1)
    compile_workflow_flow(workflow)
    workflow["tasks"][0]["output_contract"].pop("schema")
    condition_node["condition"] = item_condition("/index")
    compile_workflow_flow(workflow)
    condition_node["condition"] = item_condition("/value")
    with pytest.raises(WorkflowDefinitionError, match="scalar"):
        compile_workflow_flow(workflow)


def test_repeated_join_exports_keep_schema_expansion_bounded():
    workflow = definition()
    workflow["tasks"].insert(0, task("seed"))
    previous, selector = "seed_node", "records"
    joins = []
    for index in range(40):
        joined = f"join_{index}"
        joins.append({
            "id": f"if_{index}", "kind": "if", "inputs": [], "condition": literal_condition(),
            "then": {"id": f"then_{index}", "nodes": []}, "else": {"id": f"else_{index}", "nodes": []},
            "join": {"id": joined, "exports": [{
                "name": "rows", "expected_kind": "records", "required": True,
                "then": {"node_id": previous, "output": selector},
                "else": {"node_id": previous, "output": selector},
            }]},
        })
        previous, selector = joined, "rows"
    current_loop = workflow["flow"]["nodes"][0]
    current_loop["inputs"] = [binding(previous, output=selector)]
    current_loop["iterable"] = {"kind": "input", "name": "rows"}
    workflow["flow"]["nodes"][:0] = [task_node("seed"), *joins]
    compiled = compile_workflow_flow(workflow)
    assert len(compiled["loop_item_schemas"]["each_source"]) == 1


@pytest.mark.parametrize("target", [{"node_id": "collected"}, {"node_id": "report_node"}])
def test_forward_route_cannot_bypass_a_required_loop_or_collect(target):
    workflow = definition()
    workflow["flow"]["nodes"].insert(0, {
        "id": "skip", "kind": "route", "inputs": [], "condition": literal_condition(), "target": target,
    })
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("target", [
    {"node_id": "collected"}, {"node_id": "skip"}, {"node_id": "each_source"},
    {"exit_region_id": "each_source_body"}, {"exit_region_id": "root"},
])
def test_loop_body_routes_cannot_escape_or_backedge(target):
    workflow = definition()
    workflow["flow"]["nodes"][0]["body"]["nodes"].insert(0, {
        "id": "skip", "kind": "route", "inputs": [], "condition": literal_condition(), "target": target,
    })
    with pytest.raises(WorkflowDefinitionError, match="later sibling|branch join"):
        compile_workflow_flow(workflow)


def test_loop_body_forward_routes_may_skip_only_unrequired_producers():
    workflow = definition()
    workflow["tasks"].append(task("optional"))
    workflow["flow"]["nodes"][0]["body"]["nodes"][:0] = [
        {"id": "skip", "kind": "route", "inputs": [], "condition": literal_condition(), "target": {"node_id": "analyze_node"}},
        task_node("optional"),
    ]
    compile_workflow_flow(workflow)
    workflow["tasks"][0]["inputs"].append(binding("optional_node"))
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)


def test_branch_exits_remain_branch_join_only_inside_a_loop():
    workflow = nested_definition()
    branch = workflow["flow"]["nodes"][1]["body"]["nodes"][0]["body"]["nodes"][0]
    branch["then"]["nodes"].insert(0, {
        "id": "exit_yes", "kind": "route", "inputs": [], "condition": literal_condition(),
        "target": {"exit_region_id": "yes_region"},
    })
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)
    branch["join"]["exports"] = []
    workflow["flow"]["nodes"][1]["body"]["nodes"][0]["body"]["outputs"] = []
    workflow["flow"]["nodes"][1]["body"]["nodes"] = [workflow["flow"]["nodes"][1]["body"]["nodes"][0]]
    workflow["flow"]["nodes"][1]["body"]["outputs"] = []
    workflow["flow"]["nodes"] = workflow["flow"]["nodes"][:2]
    workflow["flow"]["outputs"] = []
    workflow["tasks"] = workflow["tasks"][:3]
    compile_workflow_flow(workflow)
    branch["then"]["nodes"][0]["target"] = {"exit_region_id": "inner_body"}
    with pytest.raises(WorkflowDefinitionError, match="branch join"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("change", [
    lambda wf: wf["tasks"][1].update(inputs=[binding("analyze_node")]),
    lambda wf: wf["tasks"][1].update(inputs=[item_binding()]),
    lambda wf: wf["flow"]["nodes"][0].update(inputs=[item_binding()]),
    lambda wf: wf["tasks"][0]["inputs"][0]["source"].update(loop_id="collected"),
    lambda wf: wf["tasks"][1].update(inputs=[binding("each_source")]),
    lambda wf: wf["flow"]["nodes"][0]["body"].update(outputs=[item_binding()]),
    lambda wf: wf["flow"]["outputs"].append(item_binding()),
    lambda wf: wf["flow"]["nodes"][1]["source"].update(loop_id="analyze_node"),
    lambda wf: wf["flow"]["nodes"][1]["source"].update(output="undeclared"),
])
def test_illegal_loop_scope_and_export_references_are_rejected(change):
    workflow = definition()
    change(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_loop_exports_and_collect_do_not_borrow_ancestor_or_other_loop_instances():
    workflow = nested_definition()
    workflow["flow"]["nodes"][1]["body"]["outputs"] = [binding("seed_node")]
    with pytest.raises(WorkflowDefinitionError, match="own body"):
        compile_workflow_flow(workflow)
    workflow = nested_definition()
    workflow["flow"]["nodes"][2]["source"]["loop_id"] = "inner"
    with pytest.raises(WorkflowDefinitionError, match="enclosing scope"):
        compile_workflow_flow(workflow)
    workflow = nested_definition()
    workflow["flow"]["nodes"][1]["body"]["nodes"].append(collect("outer", "premature"))
    with pytest.raises(WorkflowDefinitionError, match="enclosing scope"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("source", [
    {"kind": "loop_item", "loop_id": "each_source", "scope": "previous"},
    {"kind": "loop_item", "loop_id": "each_source", "output": "records"},
    {"kind": "loop_item", "loop_id": "each_source", "item_id": "a" * 64},
    {"kind": "loop_item", "loop_id": "each_source", "iteration": 0},
    {"kind": "node_output", "node_id": "collected", "loop_id": "each_source"},
    {"kind": "node_output", "node_id": "collected", "result_ref": {"sha256": "a" * 64}},
])
def test_bindings_reject_cross_item_and_runtime_storage_selectors(source):
    with pytest.raises(WorkflowDefinitionError):
        normalize_flow_bindings([{"name": "input", "source": source}])


@pytest.mark.parametrize("change", [
    lambda wf: wf["flow"]["nodes"][0].update(task_id="fake"),
    lambda wf: wf["flow"]["nodes"][1].update(task_id="fake"),
    lambda wf: wf["flow"]["nodes"][0].update(item_key="index"),
    lambda wf: wf["flow"]["nodes"][0].update(parallel=True),
    lambda wf: wf["flow"]["nodes"][0]["body"].pop("outputs"),
    lambda wf: wf["flow"]["nodes"][0]["body"].update(result_ref={}),
    lambda wf: wf["flow"]["nodes"][1]["source"].update(execution_id="a" * 64),
    lambda wf: wf["flow"]["nodes"][0]["body"]["nodes"].append(task_node("analyze")),
    lambda wf: wf["flow"]["nodes"][0]["body"]["nodes"].clear(),
    lambda wf: wf["flow"]["nodes"][0]["body"].update(id="root"),
    lambda wf: wf["tasks"][0]["inputs"][0].update(expected_kind="records"),
])
def test_loop_schema_rejects_unknown_fields_duplicate_tasks_and_missing_exports(change):
    workflow = definition()
    change(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("max_items", [None, True, 0, -1, 5001, 1.0, "500"])
def test_authored_item_cap_is_required_and_technically_bounded(max_items):
    workflow = definition()
    workflow["flow"]["nodes"][0]["max_items"] = max_items
    with pytest.raises(WorkflowDefinitionError, match="max_items"):
        compile_workflow_flow(workflow)


def test_three_loops_fit_root_inclusive_depth_but_a_fourth_does_not():
    workflow = definition()
    workflow["tasks"] = [task("one")]
    current = task_node("one")
    for identifier in ("third", "second", "first"):
        current = loop(identifier, nodes=[current])
    workflow["flow"] = {"id": "root", "nodes": [current], "outputs": []}
    compiled = compile_workflow_flow(workflow)
    assert compiled["node_loop_ids"]["one_node"] == ["first", "second", "third"]
    path = [frame(name) for name in ("first", "second", "third")]
    workflow_execution_id(workflow, "run", "one_node", path)
    workflow["flow"]["nodes"] = [loop("fourth", nodes=[current])]
    with pytest.raises(WorkflowDefinitionError, match="depth 4"):
        compile_workflow_flow(workflow)


def test_structural_id_cap_counts_root_and_engine_nodes_not_only_tasks():
    workflow = definition()
    workflow["tasks"] = [task("one")]
    workflow["flow"] = {"id": "root", "nodes": [
        {"id": f"route_{index}", "kind": "route", "inputs": [], "condition": literal_condition(),
         "target": {"node_id": "one_node"}} for index in range(254)
    ] + [task_node("one")], "outputs": []}
    compiled = compile_workflow_flow(workflow)
    assert len(compiled["nodes"]) + len(compiled["regions"]) == 256
    workflow_execution_id(workflow, "run", "one_node")
    workflow["flow"]["nodes"].insert(0, {
        "id": "excess", "kind": "route", "inputs": [], "condition": literal_condition(), "target": {"node_id": "one_node"},
    })
    with pytest.raises(WorkflowDefinitionError, match="256"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("change", [
    lambda wf: wf["flow"]["nodes"][1]["output_contract"].update(kind="text"),
    lambda wf: wf["flow"]["nodes"][1]["output_contract"].update(kind="json"),
    lambda wf: wf["flow"]["nodes"][1]["output_contract"].update(kind="any"),
    lambda wf: wf["flow"]["nodes"][1]["output_contract"].update(kind="document_results"),
    lambda wf: wf["flow"]["nodes"][1]["output_contract"].update(schema={"type": "object"}),
    lambda wf: wf["flow"]["nodes"][1]["output_contract"].update(identity_field=True),
    lambda wf: wf["tasks"][0].update(output_contract={"kind": "json", "schema": {"type": "array"}}),
    lambda wf: wf["tasks"][1]["inputs"][0]["source"].update(output="json"),
    lambda wf: wf["tasks"][1]["inputs"][0]["source"].update(output="text"),
    lambda wf: wf["tasks"][0]["output_contract"].update(schema={"type": "object"}),
])
def test_collect_preserves_exact_collection_types_and_contracts(change):
    workflow = definition()
    change(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_optional_and_partial_body_exports_cannot_bypass_complete_collect_policy():
    workflow = definition()
    body = workflow["flow"]["nodes"][0]["body"]
    body["nodes"][0]["run_when"] = item_condition()
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)
    body["outputs"][0]["required"] = False
    with pytest.raises(WorkflowDefinitionError, match="partial Collect"):
        compile_workflow_flow(workflow)
    workflow["flow"]["nodes"][1]["output_contract"].update(allow_partial=True, require_complete_coverage=False)
    compiled = compile_workflow_flow(workflow)
    assert compiled["flow"]["nodes"][0]["body"]["outputs"][0]["required"] is False
    body["outputs"][0]["required"] = True
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)


def test_optional_branch_export_cannot_be_disguised_as_a_required_loop_export():
    workflow = nested_definition()
    branch = workflow["flow"]["nodes"][1]["body"]["nodes"][0]["body"]["nodes"][0]
    branch["join"]["exports"][0]["required"] = False
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)


def test_join_cannot_hide_heterogeneous_collection_kinds_behind_json():
    workflow = nested_definition()
    workflow["tasks"][2]["output_contract"] = contract("document_results")
    branch = workflow["flow"]["nodes"][1]["body"]["nodes"][0]["body"]["nodes"][0]
    branch["join"]["exports"][0].update(expected_kind="json")
    branch["join"]["exports"][0]["else"]["output"] = "documents"
    workflow["flow"]["nodes"][1]["body"]["nodes"][0]["body"]["outputs"][0]["expected_kind"] = "json"
    with pytest.raises(WorkflowDefinitionError, match="exact records or document_results"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("change", [
    lambda node: node["inputs"][0].update(required=False),
    lambda node: node["inputs"][0].update(allow_partial=True),
    lambda node: node["iterable"].update(name="missing"),
    lambda node: node["inputs"].__setitem__(0, item_binding("outer", "rows")),
])
def test_saved_iterable_requires_a_complete_required_named_node_output(change):
    workflow = nested_definition()
    change(workflow["flow"]["nodes"][1]["body"]["nodes"][0])
    with pytest.raises(WorkflowDefinitionError, match="saved iterable"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("kind", ["records", "document_results"])
def test_saved_input_iteration_keeps_its_kind_and_never_becomes_a_document_target(kind):
    workflow = nested_definition()
    workflow["tasks"][0]["output_contract"] = contract(kind)
    source = workflow["flow"]["nodes"][1]["body"]["nodes"][0]["inputs"][0]
    source.update(expected_kind=kind)
    source["source"]["output"] = "records" if kind == "records" else "documents"
    compile_workflow_flow(workflow)
    workflow["tasks"][1]["document_action"] = {
        "type": "analyze", "target_mode": "current_item", "loop_id": "inner", "analysis_mode": "combined",
    }
    with pytest.raises(WorkflowDefinitionError, match="document iterable"):
        compile_workflow_flow(workflow)
    workflow["tasks"][1]["document_action"]["loop_id"] = "outer"
    compile_workflow_flow(workflow)


@pytest.mark.parametrize("change", [
    lambda action: action.update(loop_id="missing"),
    lambda action: action.update(loop_id="collected"),
    lambda action: action.update(analysis_mode="per_document"),
    lambda action: action.update(type="extract"),
    lambda action: action.update(documents=[{"document_id": "forged"}]),
    lambda action: action.update(result_ref={}),
])
def test_symbolic_analyze_requires_an_enclosing_document_source_and_exact_shape(change):
    workflow = definition()
    action = {"type": "analyze", "target_mode": "current_item", "loop_id": "each_source", "analysis_mode": "combined"}
    workflow["tasks"][0]["document_action"] = action
    compile_workflow_flow(workflow)
    change(action)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("version", [1, 2])
def test_symbolic_analyze_is_v3_only(version):
    workflow = {
        "definition_version": version, "tasks": [{
            "id": "one", "instructions": "Analyze one document.",
            "document_action": {"type": "analyze", "target_mode": "current_item", "loop_id": "loop", "analysis_mode": "combined"},
        }],
    }
    with pytest.raises(WorkflowDefinitionError, match="version 3"):
        normalize(workflow)
    workflow["document_action"] = workflow["tasks"][0].pop("document_action")
    with pytest.raises(WorkflowDefinitionError, match="version 3"):
        normalize(workflow)


@pytest.mark.parametrize("version", [None, True, 3.0, "3", 4])
def test_structured_compiler_rejects_noninteger_or_unsupported_versions(version):
    workflow = definition()
    workflow["definition_version"] = version
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_symbolic_analyze_cannot_be_run_scoped_or_used_after_the_loop():
    workflow = definition()
    action = {"type": "analyze", "target_mode": "current_item", "loop_id": "each_source", "analysis_mode": "combined"}
    workflow["document_action"] = action
    with pytest.raises(WorkflowDefinitionError, match="inside a document loop"):
        compile_workflow_flow(workflow)
    workflow.pop("document_action")
    workflow["tasks"][1]["document_action"] = action
    with pytest.raises(WorkflowDefinitionError, match="enclosing document loop"):
        compile_workflow_flow(workflow)


@pytest.mark.parametrize("iterable", [
    {"kind": "input", "name": "rows"},
    {"kind": "documents", "documents": []},
    {"kind": "documents", "documents": [
        {"scope_type": "personal", "document_id": "same-id"},
        {"scope_type": "group", "scope_id": "group-one", "document_id": "same-id"},
        {"scope_type": "public", "scope_id": "public-one", "document_id": "same-id"},
    ]},
    query(), query(content="keyword"),
    query(mode="best_n", content="keyword", count=3),
    query(mode="best_n", content="hybrid", count=3),
])
def test_frozen_source_descriptors_are_pure_and_canonical(iterable):
    original = copy.deepcopy(iterable)
    result = normalize_workflow_iterable(iterable, max_items=500)
    assert result == iterable == original
    assert result is not iterable


@pytest.mark.parametrize("change", [
    lambda value: value.update(manifest_ref={}),
    lambda value: value.update(execution_id="a" * 64),
    lambda value: value["scopes"][0].update(scope_id="owner"),
    lambda value: value["scopes"][0].update(user_id="other"),
    lambda value: value["scopes"].append({"scope_type": "personal"}),
    lambda value: value.update(scopes=[]),
    lambda value: value.update(scopes=None),
    lambda value: value["scopes"][0].update(scope_type="group"),
    lambda value: value["filters"].update(odata="id ne null"),
    lambda value: value["filters"].update(authors=["someone"]),
    lambda value: value["filters"].update(tags="review"),
    lambda value: value["filters"].update(tags=[False]),
    lambda value: value["filters"].update(search=12),
    lambda value: value.update(filters=None),
    lambda value: value.update(content=None),
    lambda value: value.update(content={"mode": "hybrid", "query": "retention"}),
    lambda value: value.update(content={"mode": "keyword", "query": "retention", "result_ref": {}}),
    lambda value: value["selection"].update(count=3),
    lambda value: value.update(selection={"mode": "best_n", "count": 3}),
    lambda value: value.update(selection={"mode": "latest"}),
])
def test_query_schema_rejects_unknown_types_storage_refs_and_ambiguous_selection(change):
    value = query()
    change(value)
    with pytest.raises(WorkflowDefinitionError):
        normalize_workflow_iterable(value, max_items=500)


@pytest.mark.parametrize("count", [0, -1, True, 3.5, "3", 501, None])
def test_best_n_must_fit_the_explicit_author_cap(count):
    value = query(mode="best_n", content="hybrid")
    value["selection"]["count"] = count
    with pytest.raises(WorkflowDefinitionError, match="Best N count"):
        normalize_workflow_iterable(value, max_items=500)


@pytest.mark.parametrize("extra", ["result_ref", "blob_url", "execution_id", "item_id", "iteration_path", "source_version", "user_id"])
def test_document_selection_never_accepts_runtime_or_storage_descriptors(extra):
    value = {"kind": "documents", "documents": [{"document_id": "source", "scope_type": "personal", extra: "untrusted"}]}
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        normalize_workflow_iterable(value, max_items=500)


def test_document_identity_deduplication_and_exact_technical_cardinality():
    duplicate = {"kind": "documents", "documents": [
        {"document_id": "source", "scope_type": "group", "scope_id": "group-one"},
        {"document_id": " source ", "scope_type": "group", "scope_id": "group-one"},
    ]}
    with pytest.raises(WorkflowDefinitionError, match="duplicate document identities"):
        normalize_workflow_iterable(duplicate, max_items=500)
    for count in (0, 1, 10, 100, 500, 5000):
        value = {"kind": "documents", "documents": [
            {"document_id": f"source-{index}", "scope_type": "personal"} for index in range(count)
        ]}
        assert len(normalize_workflow_iterable(value, max_items=max(1, count))["documents"]) == count
        if count > 1:
            with pytest.raises(WorkflowDefinitionError, match="max_items"):
                normalize_workflow_iterable(value, max_items=count - 1)


def test_query_metadata_allowlist_matches_document_list_shapes_and_group_policy():
    value = query()
    value["filters"] = {
        "search": "Report", "classification": "Internal", "author": "Analyst",
        "keywords": "retention", "abstract": "policy", "tags": ["review"],
    }
    assert normalize_workflow_iterable(value, max_items=500)["filters"] == value["filters"]
    workflow = definition()
    workflow["group_id"] = "group-one"
    with pytest.raises(WorkflowDefinitionError, match="workflow's group"):
        compile_workflow_flow(workflow)
    value["scopes"] = [{"scope_type": "group", "scope_id": "group-one"}]
    workflow["flow"]["nodes"][0]["iterable"] = value
    compile_workflow_flow(workflow)
    value["scopes"][0]["scope_id"] = "other-group"
    with pytest.raises(WorkflowDefinitionError, match="workflow's group"):
        compile_workflow_flow(workflow)


def test_group_iterable_scope_is_bound_to_the_server_normalization_context():
    workflow = definition()
    with pytest.raises(WorkflowDefinitionError, match="workflow's group"):
        normalize_workflow_definition(workflow, {}, workflow["tasks"], user_id="owner", group_id="group-one")
    workflow["group_id"] = "forged-group"
    workflow["flow"]["nodes"][0]["iterable"]["documents"][0].update(scope_type="group", scope_id="group-one")
    saved = normalize_workflow_definition(workflow, {}, workflow["tasks"], user_id="owner", group_id="group-one")
    assert saved["flow"]["nodes"][0]["iterable"]["documents"][0]["scope_id"] == "group-one"
    workflow["flow"]["nodes"][0]["iterable"]["documents"][0]["scope_id"] = "forged-group"
    with pytest.raises(WorkflowDefinitionError, match="workflow's group"):
        normalize_workflow_definition(workflow, {}, workflow["tasks"], user_id="owner", group_id="group-one")


@pytest.mark.parametrize("path", [
    {}, (), "", [None], [{}], [{**frame(), "iteration": 0}], [{**frame(), "repeat_id": "again"}],
    [{"loop_id": "each_source", "iteration": 0}], [{**frame(), "item_id": "A" * 64}],
    [{**frame(), "item_id": "a" * 63}], [{**frame(), "item_id": "z" * 64}],
    [{**frame(), "index": True}], [{**frame(), "index": -1}], [{**frame(), "index": 5000}],
    [{**frame(), "index": 0.0}], [{**frame(), "index": "0"}], [{**frame(), "loop_id": "bad/path"}],
    [frame(), frame()], [frame(f"loop-{index}") for index in range(4)],
])
def test_iteration_paths_reject_malformed_repeat_and_unstable_frames(path):
    with pytest.raises(ValueError):
        normalize_workflow_iteration_path(path)


def test_iteration_paths_copy_values_and_none_remains_root_scope():
    assert normalize_workflow_iteration_path(None) == normalize_workflow_iteration_path([]) == []
    path = [frame("outer"), frame("inner", index=4)]
    normalized = normalize_workflow_iteration_path(path)
    assert normalized == path and normalized is not path and normalized[0] is not path[0]
    normalized[0]["index"] = 1
    assert path[0]["index"] == 0


def test_execution_and_producer_identities_follow_every_engine_and_task_ancestor():
    workflow = nested_definition()
    compiled = compile_workflow_flow(workflow)
    workflow.update({key: compiled[key] for key in ("flow", "tasks", "limits")})
    for node_id, entry in compiled["nodes"].items():
        path = [frame(loop_id) for loop_id in compiled["node_loop_ids"][node_id]]
        execution_id = workflow_execution_id(workflow, "run", node_id, path)
        task_id = entry["node"].get("task_id")
        producer = workflow_node_identity(workflow, "run", node_id, execution_id, 1, task_id=task_id, iteration_path=path)
        retry = workflow_node_identity(workflow, "run", node_id, execution_id, 2, task_id=task_id, iteration_path=path)
        assert producer["execution_id"] == retry["execution_id"] and producer["attempt"] != retry["attempt"]
        assert producer["iteration_path"] == path
        assert ("task_id" in producer) == (entry["node"]["kind"] == "task")
    assert workflow_node_identity(
        workflow, "run", "root", workflow_execution_id(workflow, "run", "root"), 1,
    )["iteration_path"] == []


@pytest.mark.parametrize("path", [
    [], [frame("outer")], [frame("inner"), frame("outer")],
    [frame("sibling"), frame("inner")], [frame("outer"), frame("inner", index=500)],
])
def test_structurally_forged_or_missing_ancestor_paths_cannot_be_hashed(path):
    with pytest.raises(ValueError, match="ancestor|item limit"):
        workflow_execution_id(nested_definition(), "run", "yes_node", path)


def test_current_loop_frame_never_belongs_on_its_loop_collect_or_root_execution():
    workflow = definition()
    for node_id in ("root", "each_source", "collected", "report_node"):
        with pytest.raises(ValueError, match="ancestors"):
            workflow_execution_id(workflow, "run", node_id, [frame()])
    for node_id in ("each_source_body", "nonexistent"):
        with pytest.raises(ValueError, match="saved flow"):
            workflow_execution_id(workflow, "run", node_id)


def test_distinct_items_have_distinct_executions_but_membership_is_not_inferred_by_hashing():
    workflow = definition()
    first = workflow_execution_id(workflow, "run", "analyze_node", [frame()])
    second = workflow_execution_id(workflow, "run", "analyze_node", [frame(index=1, item_id="b" * 64)])
    assert first != second
    with pytest.raises(ValueError, match="execution"):
        workflow_node_identity(workflow, "run", "analyze_node", first, 1, task_id="analyze",
                               iteration_path=[frame(index=1, item_id="b" * 64)])
    with pytest.raises(ValueError, match="task identity"):
        workflow_node_identity(workflow, "run", "collected", workflow_execution_id(workflow, "run", "collected"), 1, task_id="analyze")
    workflow["flow"]["nodes"][1]["task_id"] = "analyze"
    with pytest.raises(ValueError, match="Engine nodes"):
        workflow_execution_id(workflow, "run", "collected")
