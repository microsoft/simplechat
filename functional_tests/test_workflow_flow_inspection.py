# test_workflow_flow_inspection.py
"""
Offline tests for compiler-derived Flow inspection and exact frozen executions.
Version: 0.261.121
Implemented in: 0.261.121

Production compilers, identity, snapshot, journal and lineage readers use only
fictional transactional stores. No model, source query or publication is invoked.
"""

import base64
import copy
import json
import sys
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated worktree import setup.
import functions_workflow_inspection as inspection
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_definitions import WorkflowDefinitionConflict, WorkflowDefinitionError, workflow_definition_revision
from functions_workflow_execution import WorkflowSuspended
from functions_workflow_execution_history import workflow_execution_history, workflow_execution_result_page
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_identity import workflow_execution_id, workflow_node_identity
from functions_workflow_inspection import (
    WorkflowFlowDetailTooLarge, WorkflowFlowUnsupported, preview_workflow_flow,
    workflow_flow_inspection, workflow_run_flow_inspection,
)
from functions_workflow_journal import journal_record_id
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_runtime_store import CONTROL_ID, WorkflowRuntimeConflict
from test_workflow_for_each_execution import execute_loop, loop_definition, loop_runtime
from test_workflow_repeat_execution import continue_repeat, execute_repeat, repeat_definition, repeat_runtime
from test_workflow_structured_flow import binding, create_structured_runtime, definition, run_flow, task


def forbidden(*args, **kwargs):
    raise AssertionError("Inspection crossed a forbidden read, scan, or mutation boundary.")


def details(workflow, node_id, section, **options):
    return workflow_flow_inspection(
        workflow, node_id=node_id, section=section, revision=workflow_definition_revision(workflow), **options,
    )


def test_topology_follows_regions_not_catalogue_and_is_lightweight():
    workflow = definition()
    workflow["name"] = "Fictional workflow"
    workflow["model_binding_summary"] = {"endpoint": "https://private.invalid", "secret": "PRIVATE"}
    workflow["last_run_response_preview"] = "PRIVATE_RESULT"
    workflow["lease"] = {"token": "PRIVATE_TOKEN"}
    workflow["tasks"][3]["document_action"] = {"type": "analyze", "document_ids": ["HEAVY_DOCUMENT"]}
    workflow["tasks"][0]["publication"] = {
        "artifact_format": "json", "workspace_scope": "personal", "completion_policy": "submitted",
    }
    before = copy.deepcopy(workflow)
    compiled = compile_workflow_flow(workflow)
    result = workflow_flow_inspection(workflow)
    indexed = {node["id"]: node for node in result["nodes"]}
    assert set(indexed) == set(compiled["nodes"]) | set(compiled["regions"])
    assert result["projection_version"] == 1 and result["definition_version"] == 3
    assert result["source"]["definition_revision"] == workflow_definition_revision(workflow)
    assert [node["id"] for node in result["nodes"] if node["parent_id"] == "root"] == [
        "classify-node", "choice", "joined", "report-node",
    ]
    assert [indexed[key]["order"] for key in ("classify-node", "choice", "joined", "report-node")] == [0, 1, 2, 3]
    assert indexed["positive"]["parent_id"] == "choice"
    assert indexed["yes-node"]["parent_id"] == indexed["yes-node"]["region_id"] == "positive"
    assert indexed["joined"]["kind"] == "join" and "task_id" not in indexed["joined"]
    assert indexed["classify-node"]["label"].startswith("Analyze:")
    assert indexed["report-node"]["label"].startswith("Publish:")
    serialized = json.dumps(result)
    for private in ("PRIVATE", "HEAVY_DOCUMENT", "instructions", "schema", "result_ref", "model_binding_summary", "lease"):
        assert private not in serialized
    assert workflow == before
    assert workflow_flow_inspection(workflow) == result


def test_empty_branches_forward_routes_region_exits_and_skip_edges():
    predicate = {"op": "eq", "left": {"literal": 1}, "right": {"literal": 2}}
    workflow = {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "tasks": [task("first"), task("last")],
        "flow": {"id": "root", "nodes": [
            {"id": "first", "kind": "task", "task_id": "first", "run_when": predicate},
            {"id": "forward", "kind": "route", "inputs": [], "condition": predicate, "target": {"node_id": "last"}},
            {"id": "choice", "kind": "if", "inputs": [], "condition": predicate,
             "then": {"id": "then", "nodes": [
                 {"id": "exit", "kind": "route", "inputs": [], "condition": predicate, "target": {"exit_region_id": "then"}},
             ]}, "else": {"id": "else", "nodes": []}, "join": {"id": "join", "exports": []}},
            {"id": "last", "kind": "task", "task_id": "last"},
        ], "outputs": []},
    }
    result = workflow_flow_inspection(workflow)
    connections = {(edge["source"], edge["target"], edge["kind"]): edge["label"] for edge in result["edges"]}
    assert connections["choice", "then", "then"] == "True"
    assert connections["choice", "else", "else"] == "False"
    assert "Empty" in connections["else", "join", "join"]
    assert "True" in connections["exit", "join", "exit"]
    assert "False" in connections["exit", "join", "join"]
    assert "True" in connections["forward", "last", "route"]
    assert "False" in connections["forward", "choice", "sequence"]
    assert "skip" in connections["first", "forward", "sequence"]
    assert connections["join", "last", "sequence"] == "Next"
    assert connections["last", "root", "complete"] == "Workflow complete"


def mixed_definition():
    workflow = repeat_definition(1000)
    body = workflow["flow"]
    body["id"], body["outputs"] = "outer-body", []
    workflow["flow"] = {"id": "root", "nodes": [{
        "id": "outer", "kind": "for_each", "max_items": 5000, "item_key": "source_identity", "inputs": [],
        "iterable": {"kind": "documents", "documents": []}, "body": body,
    }], "outputs": []}
    workflow["tasks"].append(task("deep"))
    body["nodes"][1]["body"]["nodes"].insert(0, {
        "id": "inner", "kind": "for_each", "max_items": 5000, "item_key": "source_identity", "inputs": [],
        "iterable": {"kind": "documents", "documents": []},
        "body": {"id": "inner-body", "nodes": [{"id": "deep-node", "kind": "task", "task_id": "deep"}], "outputs": []},
    })
    return workflow


def test_mixed_loops_have_one_template_and_post_body_finite_repeat():
    workflow = mixed_definition()
    result = workflow_flow_inspection(workflow)
    nodes = {node["id"]: node for node in result["nodes"]}
    assert nodes["deep-node"]["loop_ids"] == ["outer", "repeat", "inner"]
    assert nodes["inner-body"]["parent_id"] == "inner"
    assert nodes["repeat"]["max_iterations"] == 1000 and nodes["outer"]["max_items"] == 5000
    assert len(result["nodes"]) == len(compile_workflow_flow(workflow)["node_loop_ids"])
    assert len([node for node in result["nodes"] if node.get("task_id") == "body"]) == 1
    assert any(edge["kind"] == "repeat" and "After body" in edge["label"] for edge in result["edges"])
    assert any(edge["kind"] == "complete" and edge["label"] == "After body: Until true" for edge in result["edges"])
    assert "state" not in nodes["repeat"] and "until" not in nodes["repeat"]
    initial = details(workflow, "repeat", "inputs")["items"][0]["value"]
    assert initial["name"] == "state" and initial["source"]["node_id"] == "source-node"
    assert initial["expected_kind"] == "json" and initial["required"] is True
    state = details(workflow, "repeat", "state")["items"][0]["value"]
    assert set(state) == {"name", "initial", "next", "output_contract"}
    assert details(workflow, "repeat", "condition")["items"][0]["value"]["op"] == "eq"
    assert details(workflow, "repeat", "outputs")["items"][0]["value"] == {"name": "state", "output": "next"}


def test_maximum_structural_ids_depth_and_loop_frames_do_not_expand_instances():
    predicate = {"op": "eq", "left": {"literal": 1}, "right": {"literal": 2}}
    body = {"id": "deep-region", "nodes": [
        *[{"id": f"route-{index}", "kind": "route", "inputs": [], "condition": predicate,
           "target": {"node_id": "task-node"}} for index in range(248)],
        {"id": "task-node", "kind": "task", "task_id": "task"},
    ], "outputs": []}
    for index in range(3):
        body = {"id": f"region-{index}", "nodes": [{
            "id": f"loop-{index}", "kind": "for_each", "inputs": [],
            "iterable": {"kind": "documents", "documents": []}, "max_items": 5000, "item_key": "source_identity",
            "body": body,
        }], "outputs": []}
    workflow = {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "tasks": [task("task")], "flow": body,
    }
    result = workflow_flow_inspection(workflow)
    assert len(result["nodes"]) == 256
    selected = next(node for node in result["nodes"] if node["id"] == "task-node")
    assert selected["loop_ids"] == ["loop-2", "loop-1", "loop-0"]
    assert len(json.dumps(result, ensure_ascii=True).encode("ascii")) < 512 * 1024
    inner = workflow["flow"]["nodes"][0]["body"]["nodes"][0]["body"]["nodes"][0]["body"]
    inner["nodes"].insert(0, {
        "id": "one-too-many", "kind": "route", "inputs": [], "condition": predicate, "target": {"node_id": "task-node"},
    })
    with pytest.raises(WorkflowDefinitionError, match="256"):
        workflow_flow_inspection(workflow)


def test_nested_configuration_allowlists_remove_private_runner_and_action_data():
    workflow = definition()
    workflow["tasks"][0]["runner"] = {
        "type": "model", "model_endpoint_id": "fictional-model", "model_id": "fictional",
        "selected_agent": {"id": "agent", "name": "safe", "api_key": "PRIVATE", "settings": {"secret": "PRIVATE"}},
        "model_binding_summary": {"url": "https://provider.invalid", "api_key": "PRIVATE"},
    }
    workflow["tasks"][0]["document_action"] = {
        "type": "analyze", "target_mode": "selected", "provider_url": "https://provider.invalid",
        "api_key": "PRIVATE", "metadata": {"secret": "PRIVATE"},
    }
    page = details(workflow, "report-node", "configuration")
    serialized = json.dumps(page)
    assert "Use only declared inputs." in serialized and "fictional-model" in serialized
    for value in ("PRIVATE", "provider.invalid", "model_binding_summary", "metadata", "api_key"):
        assert value not in serialized
    assert details(workflow, "joined", "outputs")["items"][0]["value"]["then"]["node_id"] == "yes-node"
    workflow["tasks"][0]["runner"]["model_endpoint_id"] = "https://private.invalid"
    with pytest.raises(WorkflowDefinitionError):
        details(workflow, "report-node", "configuration")


def test_full_authored_names_are_lazy_and_never_shortened_on_byte_overflow():
    workflow = definition()
    workflow["name"] = "Workflow " + "界" * 200 + " complete"
    workflow["tasks"][0]["name"] = "Task " + "界" * 200 + " complete"
    projection = workflow_flow_inspection(workflow)
    assert projection["name"] == workflow["name"][:120]
    task_node = next(node for node in projection["nodes"] if node["id"] == "report-node")
    assert task_node["label"] == workflow["tasks"][0]["name"][:120]
    for node_id, label, expected in (
        ("root", "Workflow name", workflow["name"]),
        ("report-node", "Task name", workflow["tasks"][0]["name"]),
    ):
        page = details(workflow, node_id, "configuration")
        assert next(item["value"] for item in page["items"] if item["label"] == label) == expected
        assert expected not in json.dumps(projection, ensure_ascii=False)
    for name in ("x" * (inspection.FLOW_DETAIL_MAX_BYTES + 1), "界" * (inspection.FLOW_DETAIL_MAX_BYTES // 5)):
        workflow["name"] = name
        with pytest.raises(WorkflowFlowDetailTooLarge):
            details(workflow, "root", "configuration")
        workflow["name"] = "Workflow"
        workflow["tasks"][0]["name"] = name
        with pytest.raises(WorkflowFlowDetailTooLarge):
            details(workflow, "report-node", "configuration")
    workflow["tasks"][0]["name"] = {"private": "not a name"}
    with pytest.raises(WorkflowDefinitionError):
        details(workflow, "report-node", "configuration")


def test_sections_bind_cursors_to_source_revision_node_and_section():
    workflow = definition()
    workflow["tasks"][0]["inputs"] = [binding("joined", f"input{index}", "answer") for index in range(70)]
    first = details(workflow, "report-node", "inputs")
    assert len(first["items"]) == 50 and first["total_count"] == 70 and first["next_cursor"]
    second = details(workflow, "report-node", "inputs", cursor=first["next_cursor"])
    assert len(second["items"]) == 20 and second["next_cursor"] is None
    for node, section in (("report-node", "outputs"), ("choice", "inputs")):
        with pytest.raises(ValueError):
            details(workflow, node, section, cursor=first["next_cursor"])
    other_scope = {**workflow, "user_id": "other"}
    with pytest.raises(ValueError):
        details(other_scope, "report-node", "inputs", cursor=first["next_cursor"])
    value = json.loads(base64.urlsafe_b64decode(first["next_cursor"]))
    for offset in (-1, True, 70, 71, 0.5):
        cursor = base64.urlsafe_b64encode(json.dumps({**value, "offset": offset}).encode()).decode()
        with pytest.raises(ValueError):
            details(workflow, "report-node", "inputs", cursor=cursor)
    for limit in (0, 101, True, "50"):
        with pytest.raises(ValueError):
            details(workflow, "report-node", "inputs", limit=limit)
    with pytest.raises(WorkflowDefinitionConflict):
        workflow_flow_inspection(workflow, node_id="report-node", section="inputs")
    revision = workflow_definition_revision(workflow)
    workflow["tasks"][0]["instructions"] = "Edited after loading topology."
    with pytest.raises(WorkflowDefinitionConflict):
        workflow_flow_inspection(workflow, node_id="report-node", section="inputs", revision=revision)


def test_selection_and_detail_bytes_are_bounded_without_shortened_items(monkeypatch):
    workflow = loop_definition()
    loop = workflow["flow"]["nodes"][1]
    loop["iterable"] = {"kind": "documents", "documents": [
        {"scope_type": "personal", "document_id": f"document-{index}"} for index in range(120)
    ]}
    loop["inputs"] = []
    first = details(workflow, "each", "selection", limit=50)
    assert first["total_count"] == 121 and len(first["items"]) == 50
    assert first["items"][1]["value"] == {"scope_type": "personal", "document_id": "document-0"}
    monkeypatch.setattr(inspection, "FLOW_DETAIL_MAX_BYTES", 4000)
    page = details(workflow, "each", "selection", limit=100)
    assert 0 < len(page["items"]) < 100 and page["next_cursor"]
    assert len(json.dumps(page, ensure_ascii=True).encode("ascii")) < 4000
    workflow["tasks"][0]["instructions"] = "x" * 12000
    with pytest.raises(WorkflowFlowDetailTooLarge):
        details(workflow, "source-node", "configuration", limit=50)


def test_preview_is_pure_scope_bound_and_does_not_replace_editor_cas(monkeypatch):
    workflow = definition()
    workflow.update(id="foreign-stored-id", user_id="foreign", group_id="foreign-group", definition_revision="original-cas")
    original = copy.deepcopy(workflow)
    monkeypatch.setattr(inspection, "workflow_runtime_store", forbidden)
    monkeypatch.setattr(inspection, "authorize_workflow_flow_sources", forbidden)
    monkeypatch.setattr("functions_workflow_runtime.queue_durable_workflow_run", forbidden)
    monkeypatch.setattr("functions_workflow_loop_inputs.iter_workflow_loop_documents", forbidden)
    monkeypatch.setattr("functions_workflow_iterations.freeze_workflow_loop", forbidden)
    monkeypatch.setattr(WorkflowResultStore, "save", forbidden)
    result = preview_workflow_flow(workflow, user_id="owner")
    assert result["source"]["scope_type"] == "personal" and result["source"]["scope_id"] == "owner"
    assert result["source"]["definition_revision"].startswith("DRAFT:")
    assert workflow == original and workflow["definition_revision"] == "original-cas"
    page = preview_workflow_flow(
        workflow, user_id="owner", node_id="report-node", section="configuration",
        revision=result["source"]["definition_revision"],
    )
    assert page["source"] == result["source"]
    workflow["tasks"][0]["instructions"] = "Unsaved edit"
    with pytest.raises(WorkflowDefinitionConflict):
        preview_workflow_flow(
            workflow, user_id="owner", node_id="report-node", section="configuration",
            revision=result["source"]["definition_revision"],
        )
    workflow["flow"]["nodes"][0].pop("id")
    with pytest.raises(WorkflowDefinitionError):
        preview_workflow_flow(workflow, user_id="owner")


def test_declared_query_sources_are_authorized_without_enumeration(monkeypatch):
    workflow = loop_definition()
    loop = workflow["flow"]["nodes"][1]
    loop["inputs"] = []
    loop["iterable"] = {
        "kind": "workspace_query", "scopes": [{"scope_type": "group", "scope_id": "fictional-group"}],
        "filters": {"tags": ["fictional"]}, "selection": {"mode": "all_matches"},
    }
    checked = []
    allowed = {"value": True}

    def authorize_scope(scope, *, actor_user_id):
        checked.append((scope, actor_user_id))
        return allowed["value"]

    monkeypatch.setattr(inspection, "_default_authorize_scope", authorize_scope)
    monkeypatch.setattr("functions_workflow_loop_inputs.iter_workflow_loop_documents", forbidden)
    monkeypatch.setattr("functions_workflow_iterations.freeze_workflow_loop", forbidden)
    inspection.authorize_workflow_flow_sources(workflow, reader_user_id="owner")
    assert checked == [({"scope_type": "group", "scope_id": "fictional-group"}, "owner")]
    allowed["value"] = False
    with pytest.raises(AnalysisResultUnavailable):
        inspection.authorize_workflow_flow_sources(workflow, reader_user_id="owner")


def test_preview_keeps_known_list_metadata_without_relaxing_executable_validation(monkeypatch):
    workflow = definition()
    workflow["definition_revision"] = "original-editor-cas"
    baseline = preview_workflow_flow(workflow, user_id="owner")
    for field in ("metadata", "alerts", "alert_settings", "document_actions", "publication", "publication_options"):
        workflow[field] = {"legacy": {"retained": False, "provider_url": "PRIVATE_METADATA", "count": 0}}
    before = copy.deepcopy(workflow)
    monkeypatch.setattr(inspection, "workflow_runtime_store", forbidden)
    monkeypatch.setattr(inspection, "authorize_workflow_flow_sources", forbidden)
    monkeypatch.setattr(WorkflowResultStore, "save", forbidden)
    preview = preview_workflow_flow(workflow, user_id="owner")
    assert preview == baseline and workflow == before
    configuration = preview_workflow_flow(
        workflow, user_id="owner", node_id="root", section="configuration",
        revision=preview["source"]["definition_revision"],
    )
    assert "PRIVATE_METADATA" not in json.dumps(configuration)
    assert workflow["definition_revision"] == "original-editor-cas"
    workflow["parallel_execution"] = True
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        preview_workflow_flow(workflow, user_id="owner")
    workflow.pop("parallel_execution")
    workflow["tasks"][0]["metadata"] = {"parallel_execution": True}
    with pytest.raises(WorkflowDefinitionError, match="unsupported"):
        preview_workflow_flow(workflow, user_id="owner")


@pytest.mark.parametrize("version", [1, 2, 4, True, "3"])
def test_unsupported_definitions_do_not_convert_or_mutate(version):
    workflow = definition()
    workflow["definition_version"] = version
    original = copy.deepcopy(workflow)
    with pytest.raises(WorkflowFlowUnsupported):
        workflow_flow_inspection(workflow)
    with pytest.raises(WorkflowFlowUnsupported):
        preview_workflow_flow(workflow, user_id="owner")
    assert workflow == original


def test_frozen_run_uses_validated_snapshot_not_current_definition_or_limits(monkeypatch):
    workflow, store, container, _, _ = repeat_runtime(monkeypatch, maximum=1000, policy=1000)
    monkeypatch.setattr(inspection, "workflow_runtime_store", lambda *args: store)
    monkeypatch.setattr(container, "query_items", forbidden)
    before = copy.deepcopy(container.items)
    live = copy.deepcopy(workflow)
    live["flow"]["nodes"][1]["max_iterations"] = 1
    live["tasks"][1]["instructions"] = "Changed live instructions."
    frozen = workflow_run_flow_inspection(live, "run", reader_user_id="owner")
    assert frozen["source"]["definition_revision"] == workflow_definition_revision(workflow)
    assert frozen["source"]["definition_revision"] != workflow_definition_revision(live)
    assert frozen["source"]["snapshot_sha256"] == store.read()["snapshot_ref"]["sha256"]
    assert next(node for node in frozen["nodes"] if node["id"] == "repeat")["max_iterations"] == 1000
    page = workflow_run_flow_inspection(
        live, "run", reader_user_id="owner", node_id="body-node", section="configuration",
        revision=frozen["source"]["definition_revision"],
    )
    assert "Changed live" not in json.dumps(page)
    assert before == container.items
    container.items = {key: value for key, value in container.items.items() if key[1] == CONTROL_ID}
    with pytest.raises(CosmosResourceNotFoundError):
        workflow_run_flow_inspection(live, "run", reader_user_id="owner")


def test_run_schema_and_frozen_definition_version_fail_without_live_fallback(monkeypatch):
    workflow, store, container, _ = create_structured_runtime(definition(), monkeypatch)
    monkeypatch.setattr(inspection, "workflow_runtime_store", lambda *args: store)
    control = container.items["run", CONTROL_ID]
    control["schema_version"] = 1
    with pytest.raises(WorkflowFlowUnsupported):
        workflow_run_flow_inspection(workflow, "run", reader_user_id="owner")
    control["schema_version"] = 2
    snapshot = {**workflow, "definition_version": 4}
    control["snapshot_ref"] = WorkflowResultStore(container).save(
        workflow, "run", None, snapshot, node_id="root",
        execution_id=workflow_execution_id(workflow, "run", "root"), attempt=1, iteration_path=[],
    )
    control["definition_revision"] = workflow_definition_revision(snapshot)
    with pytest.raises(WorkflowFlowUnsupported):
        workflow_run_flow_inspection(workflow, "run", reader_user_id="owner")


def test_corrupt_snapshot_digest_and_reference_fail_without_live_fallback(monkeypatch):
    workflow, store, container, _ = create_structured_runtime(definition(), monkeypatch)
    monkeypatch.setattr(inspection, "workflow_runtime_store", lambda *args: store)
    control = container.items["run", CONTROL_ID]
    control["definition_revision"] = "f" * 64
    with pytest.raises(WorkflowRuntimeConflict):
        workflow_run_flow_inspection(workflow, "run", reader_user_id="owner")
    control["definition_revision"] = workflow_definition_revision(workflow)
    control["snapshot_ref"] = {}
    with pytest.raises(ValueError):
        workflow_run_flow_inspection(workflow, "run", reader_user_id="owner")


def test_exact_execution_is_frozen_point_read_and_keeps_attempt_identity(monkeypatch):
    workflow, store, container, _ = create_structured_runtime(definition(), monkeypatch)
    run_flow(workflow, store)
    monkeypatch.setattr("functions_workflow_execution_history.workflow_runtime_store", lambda *args: store)
    monkeypatch.setattr(container, "query_items", forbidden)
    live = copy.deepcopy(workflow)
    live["tasks"][0]["instructions"] = "A different live revision."
    page = workflow_execution_history(live, "run", reader_user_id="owner", node_id="report-node", iteration_path=[])
    execution = page["executions"][0]
    assert page["total_count"] == 1 and page["next_cursor"] is None
    assert execution["execution_id"] == workflow_execution_id(workflow, "run", "report-node", [])
    assert execution["execution_id"] != workflow_execution_id(live, "run", "report-node", [])
    assert execution["workflow_result"]["producer"]["attempt"] == execution["attempt"] == 1
    later = workflow_node_identity(workflow, "run", "report-node", execution["execution_id"], 2, task_id="report")
    assert later["execution_id"] == execution["execution_id"] and later["attempt"] == 2
    with pytest.raises(LookupError):
        workflow_execution_result_page(live, "run", execution["execution_id"], 2, reader_user_id="owner")
    for options in (
        {"node_id": "report-node"}, {"iteration_path": []}, {"node_id": "positive", "iteration_path": []},
        {"node_id": "missing", "iteration_path": []}, {"node_id": "report-node", "iteration_path": [], "cursor": ""},
        {"node_id": "report-node", "iteration_path": [], "kind": "attempt"},
        {"node_id": "report-node", "iteration_path": [{"loop_id": "foreign", "iteration": 0}]},
    ):
        with pytest.raises(ValueError):
            workflow_execution_history(workflow, "run", reader_user_id="owner", **options)


@pytest.mark.parametrize("node_id", ["root", "report-node"])
def test_unrecorded_valid_execution_is_only_zero_record_metadata(monkeypatch, node_id):
    workflow, store, container, _ = create_structured_runtime(definition(), monkeypatch)
    monkeypatch.setattr("functions_workflow_execution_history.workflow_runtime_store", lambda *args: store)
    monkeypatch.setattr(container, "query_items", forbidden)
    before = copy.deepcopy(container.items)
    live = copy.deepcopy(workflow)
    live["tasks"][0]["instructions"] = "A different live revision."
    response = workflow_execution_history(live, "run", reader_user_id="owner", node_id=node_id, iteration_path=[])
    assert response == {"executions": [], "next_cursor": None, "total_count": 0}
    assert container.items == before
    with pytest.raises(LookupError):
        workflow_execution_result_page(
            live, "run", workflow_execution_id(workflow, "run", node_id), 1, reader_user_id="owner",
        )


def test_exact_for_each_lookup_validates_frozen_membership_without_history_scan(monkeypatch):
    workflow, store, container, _ = loop_runtime(monkeypatch)
    _, calls = execute_loop(workflow, store, [{"value": 1}, {"value": 2}])
    path = next(call[1] for call in calls if call[0] == "body")
    monkeypatch.setattr(container, "query_items", forbidden)
    result = workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="body-node", iteration_path=path)
    assert result["executions"][0]["iteration_path"] == path
    with pytest.raises(ValueError):
        workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="body-node", iteration_path=[])
    wrong = [{**path[0], "item_id": "f" * 64}]
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="body-node", iteration_path=wrong)
    row = store.journal_read("execution", result["executions"][0]["execution_id"])
    container.items.pop(("run", row["id"]))
    assert workflow_execution_history(
        workflow, "run", reader_user_id="owner", node_id="body-node", iteration_path=path,
    ) == {"executions": [], "next_cursor": None, "total_count": 0}
    container.items["run", row["id"]] = row
    container.items["run", row["id"]]["payload"]["iteration_inputs"] = []
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="body-node", iteration_path=path)
    container.items["run", row["id"]]["scope_id"] = "foreign"
    with pytest.raises(WorkflowRuntimeConflict):
        workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="body-node", iteration_path=path)


def test_unrecorded_repeat_node_still_requires_a_sealed_admission(monkeypatch):
    workflow, store, container, _, _ = repeat_runtime(monkeypatch)
    execute_repeat(workflow, store, target=1)
    path = [{"loop_id": "repeat", "iteration": 0}]
    execution_id = workflow_execution_id(workflow, "run", "body-node", path)
    container.items.pop(("run", journal_record_id("execution", execution_id)))
    monkeypatch.setattr(container, "query_items", forbidden)
    live = copy.deepcopy(workflow)
    live["flow"]["nodes"][1]["max_iterations"] = 1
    assert workflow_execution_history(
        live, "run", reader_user_id="owner", node_id="body-node", iteration_path=path,
    ) == {"executions": [], "next_cursor": None, "total_count": 0}
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(
            live, "run", reader_user_id="owner", node_id="body-node",
            iteration_path=[{"loop_id": "repeat", "iteration": 1}],
        )
    loop_id = workflow_execution_id(workflow, "run", "repeat", [])
    container.items.pop(("run", journal_record_id("admission", ["repeat-iteration", loop_id, 0])))
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(live, "run", reader_user_id="owner", node_id="body-node", iteration_path=path)


def test_unrecorded_mixed_path_requires_both_repeat_admission_and_frozen_item(monkeypatch):
    draft = repeat_definition(1)
    contract = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
    draft["tasks"].extend([
        task("rows-source", contract=contract),
        task("leaf", inputs=[{
            "name": "item", "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"},
        }], contract=contract),
    ])
    draft["flow"]["nodes"].insert(1, {"id": "rows-source-node", "kind": "task", "task_id": "rows-source"})
    draft["flow"]["nodes"][2]["body"]["nodes"].append({
        "id": "each", "kind": "for_each", "max_items": 2, "item_key": "source_identity",
        "inputs": [binding("rows-source-node", "rows", "records")],
        "iterable": {"kind": "input", "name": "rows"},
        "body": {"id": "each-body", "nodes": [{"id": "leaf-node", "kind": "task", "task_id": "leaf"}], "outputs": []},
    })
    workflow, store, container, _, _ = repeat_runtime(monkeypatch, definition=draft)

    def produce(current, resolved, execution):
        if current["id"] == "rows-source":
            kind, value = "records", [{"row": 1}]
        elif current["id"] == "leaf":
            kind, value = "records", [resolved["values"]["item"]["value"]]
        else:
            kind = "json"
            value = {"count": int(current["id"] != "source"), "ready": current["id"] != "source"}
        return {"reply": "", "authoritative_result": {"kind": kind, "value": value}}

    _, calls = execute_repeat(workflow, store, result_for_task=produce)
    _, path, execution_id = next(call for call in calls if call[0] == "leaf")
    assert [frame["loop_id"] for frame in path] == ["repeat", "each"]
    container.items.pop(("run", journal_record_id("execution", execution_id)))
    monkeypatch.setattr(container, "query_items", forbidden)
    assert workflow_execution_history(
        workflow, "run", reader_user_id="owner", node_id="leaf-node", iteration_path=path,
    ) == {"executions": [], "next_cursor": None, "total_count": 0}
    for wrong in (
        [path[0], {**path[1], "item_id": "f" * 64}],
        [{**path[0], "iteration": 1}, path[1]],
    ):
        with pytest.raises(AnalysisResultUnavailable):
            workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="leaf-node", iteration_path=wrong)


def test_exact_repeat_round_1001_is_lifetime_not_current_batch_or_live_revision(monkeypatch):
    workflow, store, container, _, _ = repeat_runtime(monkeypatch, maximum=1000, policy=1000)
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=1001)
    continue_repeat(store)
    execute_repeat(workflow, store, target=1001)
    monkeypatch.setattr(container, "query_items", forbidden)
    live = copy.deepcopy(workflow)
    live["flow"]["nodes"][1]["max_iterations"] = 1
    live["tasks"][1]["instructions"] = "Changed after admission."
    path = [{"loop_id": "repeat", "iteration": 1000}]
    page = workflow_execution_history(live, "run", reader_user_id="owner", node_id="body-node", iteration_path=path)
    assert page["executions"][0]["iteration_path"] == path
    assert page["executions"][0]["execution_id"] == workflow_execution_id(workflow, "run", "body-node", path)
    assert page["executions"][0]["attempt"] == 1
    container.items.pop(("run", journal_record_id("execution", page["executions"][0]["execution_id"])))
    assert workflow_execution_history(
        live, "run", reader_user_id="owner", node_id="body-node", iteration_path=path,
    ) == {"executions": [], "next_cursor": None, "total_count": 0}


def test_exact_payload_reuses_source_authorization_and_private_projection(monkeypatch):
    workflow, store, container, _ = create_structured_runtime(definition(), monkeypatch)
    run_flow(workflow, store)
    monkeypatch.setattr("functions_workflow_execution_history.workflow_runtime_store", lambda *args: store)
    identifier = workflow_execution_id(workflow, "run", "classify-node")
    row = store.journal_read("execution", identifier)
    payload = container.items["run", row["id"]]["payload"]
    payload["reference_sources"] = [{"document_id": "source", "scope": "personal", "scope_id": "owner"}]
    payload["lease"] = {"token": "PRIVATE"}
    access = {"allowed": True}

    def authorize(user, sources):
        assert user == "owner" and sources[0]["document_id"] == "source"
        if not access["allowed"]:
            raise AnalysisResultUnavailable()

    monkeypatch.setattr("functions_workflow_execution_history.authorize_analysis_sources", authorize)
    result = workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="classify-node", iteration_path=[])
    assert "PRIVATE" not in json.dumps(result) and "reference_sources" not in json.dumps(result)
    access["allowed"] = False
    with pytest.raises(AnalysisResultUnavailable):
        workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="classify-node", iteration_path=[])
    payload["node_id"] = "foreign-node"
    with pytest.raises(ValueError):
        workflow_execution_history(workflow, "run", reader_user_id="owner", node_id="classify-node", iteration_path=[])
