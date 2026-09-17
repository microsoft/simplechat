# test_workflow_structured_flow.py
"""
Isolated regression coverage for the structured v3 compiler, exact results and journal.
Version: 0.261.116
Implemented in: 0.261.116

Uses production compiler, controller, flow traversal, result transport and readers
with JSON-copying transactional Cosmos fakes. No model, Azure or workflow is invoked.
"""

import copy
import ast
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the worktree path setup.
from functions_workflow_definitions import WorkflowDefinitionError, workflow_definition_revision
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution import WorkflowSuspended, workflow_execution_scope
from functions_workflow_execution import current_workflow_execution
from functions_workflow_results import WorkflowResultNotReadyError
from functions_workflow_flow import MISSING, compile_workflow_flow, evaluate_predicate, normalize_predicate
from functions_workflow_flow_runner import WorkflowFlowRunner
from functions_workflow_identity import workflow_execution_id, workflow_node_identity
from functions_workflow_node_results import authorize_workflow_node_result_read, load_workflow_node_input
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_results import build_workflow_task_result, persist_workflow_task_result, workflow_result_summary
from functions_workflow_results import authorize_workflow_task_result_read
from functions_workflow_results import _build_task_result
from functions_document_analysis_checkpoints import analysis_checkpoints_for_workflow
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeLease, WorkflowRuntimeStore
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_validation import validate_workflow_task_output
from test_workflow_durable_execution import Clock, RuntimeContainer


def binding(node_id, name="input", output="authoritative", required=True):
    return {"name": name, "source": {"kind": "node_output", "node_id": node_id, "output": output},
            "required": required}


def task(identifier, *, inputs=None, contract=None):
    return {
        "id": identifier, "type": "instructions", "name": identifier, "instructions": "Use only declared inputs.",
        "runner": {"type": "inherit"}, "document_action": {"type": "none"},
        "inputs": [] if inputs is None else inputs, "output_contract": contract or {"kind": "text"},
    }


def condition(name="flag"):
    return {"op": "eq", "left": {"input": name, "path": "/pass"}, "right": {"literal": True}}


def definition():
    return {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "tasks": [
            task("report", inputs=[binding("joined", output="answer")]),
            task("no"), task("yes"),
            task("classify", contract={"kind": "json", "schema": {
                "type": "object", "required": ["pass"], "properties": {"pass": {"type": "boolean"}},
            }}),
        ],
        "flow": {"id": "root", "nodes": [
            {"id": "classify-node", "kind": "task", "task_id": "classify"},
            {"id": "choice", "kind": "if", "inputs": [binding("classify-node", "flag")],
             "condition": condition(),
             "then": {"id": "positive", "nodes": [{"id": "yes-node", "kind": "task", "task_id": "yes"}]},
             "else": {"id": "negative", "nodes": [{"id": "no-node", "kind": "task", "task_id": "no"}]},
             "join": {"id": "joined", "exports": [{
                 "name": "answer", "expected_kind": "text", "required": True,
                 "then": {"node_id": "yes-node"}, "else": {"node_id": "no-node"},
             }]}},
            {"id": "report-node", "kind": "task", "task_id": "report"},
        ], "outputs": [binding("report-node", "report")]},
    }


class JournalContainer(RuntimeContainer):
    def query_items(self, *, query, parameters, partition_key=None, max_item_count=None, **kwargs):
        values = {item["name"][1:]: item["value"] for item in parameters}
        rows = [copy.deepcopy(row) for (partition, _), row in self.items.items()
                if partition_key is None or partition == partition_key]
        for field in ("run_id", "workflow_id", "scope_type", "scope_id", "execution_id"):
            if field in values:
                rows = [row for row in rows if row.get(field) == values[field]]
        if "record_type" in values:
            rows = [row for row in rows if row.get("type") == values["record_type"]]
        if "kind" in values:
            rows = [row for row in rows if row.get("record_kind") == values["kind"]]
        if "after" in values:
            rows = [row for row in rows if row.get("sequence", 0) > values["after"]]
            rows.sort(key=lambda row: row["sequence"])
        if "through" in values:
            rows = [row for row in rows if row.get("sequence", 0) <= values["through"]]
        top = re.search(r"SELECT TOP (\d+)", query)
        return rows[:int(top[1])] if top else rows

    def delete_item(self, item, partition_key):
        del self.items[(partition_key, item)]


@pytest.fixture
def runtime(monkeypatch):
    return create_structured_runtime(definition(), monkeypatch)


def create_structured_runtime(workflow, monkeypatch):
    compiled = compile_workflow_flow(workflow)
    workflow.update({key: compiled[key] for key in ("flow", "tasks", "limits")})
    workflow["definition_revision"] = workflow_definition_revision(workflow)
    container, clock = JournalContainer(), Clock()
    store = WorkflowRuntimeStore(container, workflow, "run", clock=clock)
    results = WorkflowResultStore(container)
    snapshot = results.save(
        workflow, "run", None, workflow, node_id="root",
        execution_id=workflow_execution_id(workflow, "run", "root"), attempt=1, iteration_path=[],
    )
    store.initialize(snapshot_ref=snapshot, definition_revision=workflow["definition_revision"],
                     actor_user_id="owner", request_id="request")

    def configured(*args, **kwargs):
        return WorkflowResultStore(container)

    monkeypatch.setattr("functions_workflow_result_store._configured_store", configured)
    monkeypatch.setattr("functions_workflow_result_store._configured_result_store", configured)
    return workflow, store, container, clock


def test_catalogue_order_is_not_executable_and_defaults_are_explicit():
    compiled = compile_workflow_flow(definition())
    assert compiled["flow"]["nodes"][0]["task_id"] == "classify"
    assert compiled["tasks"][0]["id"] == "report"
    source = compiled["tasks"][0]["inputs"][0]
    assert source["allow_partial"] is False and source["source"]["scope"] == "current"
    assert compiled["limits"] == {"max_executions": 5000, "deadline_seconds": 86400}


@pytest.mark.parametrize("mutation", [
    lambda wf: wf["flow"]["nodes"][1]["then"]["nodes"].append({"id": "other", "kind": "repeat"}),
    lambda wf: wf["tasks"][0].update(inputs=None),
    lambda wf: wf["flow"]["nodes"][1]["join"]["exports"][0]["then"].update(node_id="missing"),
    lambda wf: wf["flow"]["nodes"][1]["then"]["nodes"][0].update(run_when={"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}}),
    lambda wf: wf["flow"]["nodes"][1]["else"].update(id="positive"),
    lambda wf: wf["tasks"].append(copy.deepcopy(wf["tasks"][0])),
    lambda wf: wf.update(limits={"max_executions": True}),
    lambda wf: wf["flow"].pop("outputs"),
    lambda wf: wf["flow"]["nodes"][1].update(target={"node_id": "report-node"}),
])
def test_compiler_rejects_invalid_or_lossy_shapes(mutation):
    workflow = definition()
    mutation(workflow)
    with pytest.raises(WorkflowDefinitionError):
        compile_workflow_flow(workflow)


def test_branch_outputs_cannot_escape_without_a_join():
    workflow = definition()
    workflow["tasks"][0]["inputs"] = [binding("yes-node")]
    with pytest.raises(WorkflowDefinitionError, match="region"):
        compile_workflow_flow(workflow)


def test_forward_route_checks_every_reachable_required_dependency():
    workflow = definition()
    workflow["flow"]["nodes"].insert(0, {
        "id": "route", "kind": "route", "inputs": [], "condition": {
            "op": "eq", "left": {"literal": 1}, "right": {"literal": 2},
        }, "target": {"node_id": "choice"},
    })
    with pytest.raises(WorkflowDefinitionError, match="required producer"):
        compile_workflow_flow(workflow)
    workflow["flow"]["nodes"][0]["target"] = {"node_id": "route"}
    with pytest.raises(WorkflowDefinitionError, match="later sibling"):
        compile_workflow_flow(workflow)


def test_predicate_missing_null_boolean_numeric_and_short_circuit_rules():
    bindings = [{"name": "input"}]
    exists = normalize_predicate({"op": "exists", "value": {"input": "input", "path": "/x"}}, bindings)
    assert evaluate_predicate(exists, {"input": {"x": None}}) is True
    assert evaluate_predicate(exists, {"input": {}}) is False
    comparison = normalize_predicate({
        "op": "eq", "left": {"input": "input", "path": "/x"}, "right": {"literal": None},
    }, bindings)
    with pytest.raises(WorkflowDefinitionError, match="missing"):
        evaluate_predicate(comparison, {"input": {}})
    guarded = normalize_predicate({"op": "all", "conditions": [exists, comparison]}, bindings)
    assert evaluate_predicate(guarded, {"input": {}}) is False
    for operator in ("eq", "ne", "lt"):
        expr = normalize_predicate({"op": operator, "left": {"literal": True}, "right": {"literal": 1}}, [])
        if operator == "lt":
            with pytest.raises(WorkflowDefinitionError):
                evaluate_predicate(expr, {})
        else:
            assert evaluate_predicate(expr, {}) is (operator == "ne")
    assert evaluate_predicate(normalize_predicate({
        "op": "eq", "left": {"literal": 1}, "right": {"literal": 1.0},
    }, []), {})
    with pytest.raises(WorkflowDefinitionError):
        normalize_predicate({"op": "exists", "value": {"input": "input", "path": "/bad~2path"}}, bindings)


def run_flow(workflow, store, *, yes=True, crash_after_choice=False):
    calls, outcomes = [], []
    with WorkflowRuntimeLease(store, owner_id="worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        with workflow_execution_scope(execution):
            flow = WorkflowFlowRunner(workflow, "run", execution, outcomes, actor_user_id="owner")
            for current in flow.tasks():
                if crash_after_choice and current["id"] in {"yes", "no"}:
                    raise SystemExit("Restart after durable branch decision.")
                resolved = flow.resolve(current["inputs"])
                raw = execution.run_unit(
                    f"task:{current['id']}",
                    lambda: calls.append(current["id"]) or (
                        {"reply": json.dumps({"pass": yes}), "authoritative_result": {"kind": "json", "value": {"pass": yes}}}
                        if current["id"] == "classify" else {"reply": current["id"] + "x" * 13000 + "FINAL-SENTINEL"}
                    ), inputs={"task": current, "receipts": resolved["consumed_inputs"]}, replay_safe=True,
                )
                envelope = build_workflow_task_result(raw, workflow=workflow, run_id="run", task=current)
                envelope["consumed_inputs"] = resolved["consumed_inputs"]
                envelope["workflow_validation"] = validate_workflow_task_output(envelope, current["output_contract"])
                manifest, reference = persist_workflow_task_result(
                    envelope, workflow=workflow, run_id="run", task_id=current["id"], settings={"max_file_size_mb": 10},
                )
                outcomes.append({
                    "task": current, "status": "succeeded",
                    "consumed_inputs": resolved["consumed_inputs"],
                    "result": {**raw, "workflow_result": workflow_result_summary(manifest, reference),
                               "workflow_validation": envelope["workflow_validation"]},
                })
            return flow, calls


@pytest.mark.parametrize("yes", [True, False])
def test_exact_selected_join_and_long_final_output_survive_reload(runtime, yes):
    workflow, store, container, _ = runtime
    flow, calls = run_flow(workflow, store, yes=yes)
    assert calls == ["classify", "yes" if yes else "no", "report"]
    assert flow.finished and not flow.failed
    receipt = flow.final_outputs[0]
    prompt, _ = load_workflow_node_input(workflow, "run", receipt["producer"], receipt["result_ref"])
    assert json.loads(prompt)["value"].endswith("FINAL-SENTINEL")
    report = flow.completed["report-node"]["summary"]
    join_receipt = report["consumed_inputs"][0]
    assert join_receipt["producer"]["node_id"] == "joined"
    assert "task_id" not in join_receipt["producer"]
    join, _ = authorize_workflow_node_result_read(
        workflow, "run", join_receipt["producer"], join_receipt["result_ref"],
    )
    assert {item["producer"]["node_id"] for item in join["consumed_inputs"]} == {"choice", "yes-node" if yes else "no-node"}
    assert join["outputs"]["answer"]["selected_producer"]["producer"]["node_id"] == ("yes-node" if yes else "no-node")
    assert store.read()["units"] == {} and store.read()["memory"] == {}


def test_restart_follows_persisted_choice_and_does_not_reinvoke_classifier(runtime):
    workflow, store, _, _ = runtime
    with pytest.raises(SystemExit):
        run_flow(workflow, store, crash_after_choice=True)
    flow, calls = run_flow(workflow, store, yes=False)
    assert calls == ["yes", "report"]
    assert flow.completed["no-node"]["state"] == "skipped"


def test_exact_identity_rejects_forged_attempt_execution_task_and_scope(runtime):
    workflow, store, _, _ = runtime
    flow, _ = run_flow(workflow, store)
    receipt = flow.final_outputs[0]
    for changed in (
        {"attempt": 2}, {"execution_id": "f" * 64}, {"task_id": "classify"}, {"node_id": "classify-node"},
    ):
        with pytest.raises((ValueError, CosmosResourceNotFoundError)):
            load_workflow_node_input(workflow, "run", {**receipt["producer"], **changed}, receipt["result_ref"])
    with pytest.raises(ValueError):
        workflow_node_identity({**workflow, "user_id": "stranger"}, "run", "report-node",
                               receipt["producer"]["execution_id"], 1, task_id="report")


def test_schema2_pages_more_than_1000_records_without_growing_control(runtime):
    workflow, store, container, _ = runtime
    with WorkflowRuntimeLease(store, owner_id="seed-worker") as lease:
        for index in range(1010):
            store.journal_commit(lease.token, "execution", f"seed-{index}", {
                "execution_id": f"seed-{index}", "node_id": "node", "node_kind": "task",
                "iteration_path": [], "state": "completed", "attempt": 1,
            })
    cursor, items = None, []
    while True:
        page = store.journal_page("execution", cursor=cursor, limit=73)
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(items) == 1010 and len({item["sequence"] for item in items}) == 1010
    control = store.read()
    assert len(json.dumps(control)) < 5000 and control["units"] == {} and control["memory"] == {}
    assert control["admitted_count"] == 0
    with pytest.raises(ValueError):
        store.journal_page("attempt", cursor=store.journal_page("execution", limit=1)["next_cursor"])


def test_approval_is_bound_to_exact_attempt_and_old_gate_cannot_approve_retry(runtime):
    workflow, store, _, _ = runtime
    node = workflow["flow"]["nodes"][0]
    def execute():
        with WorkflowRuntimeLease(store, owner_id="worker") as lease:
            controller = StructuredWorkflowExecution(store, lease, workflow, "run")
            controller.set_node(node, "root")
            with workflow_execution_scope(controller):
                return controller.run_unit("task:classify", lambda: {"reply": "saved"},
                                           inputs={"request": 1}, approval={"required": True}, replay_safe=True)
    with pytest.raises(WorkflowSuspended):
        execute()
    waiting = store.read()
    first_gate = waiting["gate"]
    assert first_gate["node_id"] == node["id"] and first_gate["attempt"] == 1
    store.decide(expected_version=waiting["version"], gate_id=first_gate["id"], choice="approve",
                 actor_user_id="owner", request_id="approve-1")
    execute()
    with WorkflowRuntimeLease(store, owner_id="invalidate") as lease:
        controller = StructuredWorkflowExecution(store, lease, workflow, "run")
        controller.set_node(node, "root")
        controller.invalidate_task("task:classify")
    with pytest.raises(WorkflowSuspended):
        execute()
    second = store.read()
    assert second["gate"]["attempt"] == 2 and second["gate"]["id"] != first_gate["id"]
    with pytest.raises(WorkflowRuntimeConflict):
        store.decide(expected_version=second["version"], gate_id=first_gate["id"], choice="approve",
                     actor_user_id="owner", request_id="stale-approval")


def test_production_task_sequence_reuses_dispatcher_and_exact_results(runtime):
    from test_workflow_task_result_handoff import build_inventory_run

    workflow, store, _, _ = runtime
    runner, _, _, _, _, items = build_inventory_run(1)
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        response = '{"pass": true}' if len(requests) == 1 else "x" * 13000 + "DISPATCH-SENTINEL"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    runner.update({
        "get_workflow_alert_signals": lambda: [],
        "_resolve_model_workflow_client": lambda *args, **kwargs: (
            runner["WorkflowModelClient"](client, "gpt-4.1", "aoai"), "gpt-4.1", "aoai",
        ),
        "persist_workflow_task_result": lambda envelope, **kwargs: persist_workflow_task_result(
            envelope, **{**kwargs, "settings": {"max_file_size_mb": 10}},
        ),
        "authorize_workflow_task_result_read": authorize_workflow_task_result_read,
    })
    with WorkflowRuntimeLease(store, owner_id="dispatcher-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        with workflow_execution_scope(execution):
            result = runner["_execute_workflow_task_sequence"](
                workflow, {}, "conversation", "run", None, {}, actor_user_id="owner",
            )
    assert len(requests) == 3
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert result["reply"].endswith("DISPATCH-SENTINEL")
    assert [entry["task_id"] for entry in result["task_results"]] == ["classify", "yes", "report"]
    assert result["workflow_outputs"][0]["producer"]["node_id"] == "report-node"


def test_run_when_false_precedes_approval_and_produces_only_skip_evidence(runtime):
    workflow, store, _, _ = runtime
    workflow["flow"]["nodes"][0]["run_when"] = {
        "op": "eq", "left": {"literal": 1}, "right": {"literal": 2},
    }
    workflow["tasks"] = [task("classify")]
    workflow["tasks"][0]["approval"] = {"required": True}
    workflow["flow"]["nodes"] = [workflow["flow"]["nodes"][0]]
    workflow["flow"]["outputs"] = []
    with WorkflowRuntimeLease(store, owner_id="skip-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        flow = WorkflowFlowRunner(workflow, "run", execution, [], actor_user_id="owner")
        assert list(flow.tasks()) == []
    row = store.journal_page("execution")["items"][0]
    assert row["state"] == "skipped" and row["reason_code"] == "run_when_false"
    assert "workflow_result" not in row and store.read()["gate"] is None
    assert store.read()["admitted_count"] == 1


def test_control_budget_and_deadline_include_waits_without_counting_payload_writes(runtime):
    workflow, store, container, clock = runtime
    control = store.read()
    control["max_executions"] = 1
    container._store(("run", control["id"]), control)
    with WorkflowRuntimeLease(store, owner_id="budget-worker") as lease:
        store.journal_commit(lease.token, "decision", "first", {"choice": "then"}, admission=True)
        for index in range(3):
            store.journal_commit(lease.token, "unit", f"checkpoint-{index}", {"state": "completed"})
        store.wait(lease.token, state="waiting_approval", gate={"id": "gate", "kind": "approval", "choices": ["approve", "reject"]})
    waiting = store.read()
    store.decide(expected_version=waiting["version"], gate_id="gate", choice="approve", actor_user_id="owner", request_id="allow")
    with WorkflowRuntimeLease(store, owner_id="limit-worker") as lease:
        with pytest.raises(WorkflowSuspended, match="paused"):
            store.journal_commit(lease.token, "decision", "second", {"choice": "else"}, admission=True)
    limited = store.read()
    assert limited["admitted_count"] == 1 and limited["gate"]["choices"] == ["cancel"]
    with pytest.raises(WorkflowRuntimeConflict):
        store.resume(expected_version=limited["version"], actor_user_id="owner", request_id="reset-budget")
    # Independently exercise expiration while a run is genuinely waiting.
    limited.update(state="waiting_approval", phase="", gate={"id": "later-gate", "kind": "approval", "choices": ["approve", "reject"]})
    container._store(("run", limited["id"]), limited)
    clock.now = clock.now.replace(year=clock.now.year + 1)
    assert store.expire_deadline()["state"] == "paused"
    assert store.read()["phase"] == "deadline_exceeded"


@pytest.mark.parametrize("race", ["before_guard", "checkpoint", "cancelled_worker"])
def test_v3_analyze_writes_retain_workflow_and_native_guard_fences(runtime, monkeypatch, race):
    workflow, store, container, _ = runtime
    node = workflow["flow"]["nodes"][0]
    with WorkflowRuntimeLease(store, owner_id="analyze-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        execution.set_node(node, "root")
        with workflow_execution_scope(execution):
            checkpoints = analysis_checkpoints_for_workflow(
                workflow, "run", "classify", user_id="owner", authorize=lambda: execution.check(),
                source_authorizer=lambda *args, **kwargs: True, store=WorkflowResultStore(container), **execution.selectors(),
            )
            assert all(not isinstance(value, list) for value in checkpoints.binding.values())
            if race != "before_guard":
                checkpoints.prepare()
                checkpoints.initialize({"instructions": "Extract"}, [
                    {"document_id": "source", "scope": "personal", "scope_id": "owner", "source_version": 1},
                ])
            operation = checkpoints.prepare if race == "before_guard" else lambda: checkpoints.store.write_analysis_checkpoint(
                checkpoints.binding, "source", "source", {"source": "verified"}, token=checkpoints.token,
            )
            if race == "cancelled_worker":
                store.request_cancel(actor_user_id="owner", request_id="cancel")
                before = copy.deepcopy(container.items)
            else:
                original = container.execute_item_batch
                before = []

                def race_write(batch_operations, partition_key):
                    if not before:
                        store.tombstone()
                        before.append(copy.deepcopy(container.items))
                    return original(batch_operations, partition_key)

                monkeypatch.setattr(container, "execute_item_batch", race_write)
            with pytest.raises(WorkflowRuntimeConflict):
                operation()
            assert container.items == (before if race == "cancelled_worker" else before[0])


def test_paged_consumption_lineage_is_not_limited_to_256_ancestors(runtime):
    workflow, store, _, _ = runtime
    receipts = []
    source_execution = workflow_execution_id(workflow, "run", "yes-node")
    for attempt in range(1, 302):
        identity = workflow_node_identity(workflow, "run", "yes-node", source_execution, attempt, task_id="yes")
        envelope = _build_task_result({"reply": f"result {attempt}"}, identity, "workflow-result-v2")
        envelope["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True}
        manifest, reference = persist_workflow_task_result(envelope, workflow=workflow, run_id="run", task_id="yes", settings={})
        receipts.append({"producer": identity, "result_ref": reference, "output_name": "text",
                         "output_ref": manifest["outputs"]["text"]["result_ref"]})
    identity = workflow_node_identity(workflow, "run", "report-node", workflow_execution_id(workflow, "run", "report-node"), 1, task_id="report")
    aggregate = _build_task_result({"reply": "Complete lineage"}, identity, "workflow-result-v2")
    aggregate["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True}
    aggregate["consumed_inputs"] = receipts
    manifest, reference = persist_workflow_task_result(aggregate, workflow=workflow, run_id="run", task_id="report", settings={})
    assert "consumed_inputs" not in manifest
    assert manifest["consumed_inputs_index"]["record_count"] == 301
    loaded, _ = authorize_workflow_node_result_read(workflow, "run", identity, reference)
    assert loaded["consumed_inputs_index"]["record_count"] == 301


def test_publication_uses_explicit_producer_and_stable_execution_receipt_across_retry(runtime, monkeypatch):
    from test_analyze_backend_saved_integration import load_functions

    workflow, store, _, _ = runtime
    identity = workflow_node_identity(workflow, "run", "yes-node", workflow_execution_id(workflow, "run", "yes-node"), 2, task_id="yes")
    envelope = _build_task_result({"reply": "Native saved analysis"}, identity, "workflow-result-v2")
    envelope.update(analysis_origin=True, validation={"status": "valid"}, workflow_validation={
        "version": 1, "status": "valid", "eligible": True,
    }, artifacts=[{"output_format": "md", "artifact_message_id": "artifact", "conversation_id": "conversation", "capability": "analyze"}])
    manifest, reference = persist_workflow_task_result(envelope, workflow=workflow, run_id="run", task_id="yes", settings={})
    receipt = {"producer": identity, "result_ref": reference, "output_name": "text", "output_ref": manifest["outputs"]["text"]["result_ref"]}
    published, requests = {}, []

    def publish(actor, *, request_id, publication, artifact_reference):
        requests.append((request_id, artifact_reference["producer"]))
        published.setdefault(request_id, {"publication": {"state": "queued", "document_id": "one-document"}})
        return copy.deepcopy(published[request_id])

    monkeypatch.setitem(sys.modules, "functions_artifact_publication", SimpleNamespace(publish_workflow_analysis_artifact=publish))
    monkeypatch.setitem(sys.modules, "functions_personal_workflows", SimpleNamespace(normalize_workflow_publication=lambda value: value))
    namespace = {"WorkflowResultNotReadyError": WorkflowResultNotReadyError,
                 "authorize_workflow_task_result_read": authorize_workflow_task_result_read,
                 "current_workflow_execution": current_workflow_execution}
    load_functions("functions_workflow_runner.py", {"_execute_workflow_analysis_publication"}, namespace)
    task_config = {**workflow["tasks"][0], "publication": {"artifact_format": "md", "workspace_scope": "personal"}}
    with WorkflowRuntimeLease(store, owner_id="publication") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        execution.set_node(workflow["flow"]["nodes"][-1], "root")
        with workflow_execution_scope(execution):
            for attempt in (1, 2):
                store.journal_commit(lease.token, "unit", execution._key("task:report"), {"state": "running", "attempt": attempt})
                result, consumed = namespace["_execute_workflow_analysis_publication"](
                    workflow, "run", task_config, "wrong-predecessor", {"sha256": "wrong"},
                    explicit_inputs=[receipt], actor_user_id="owner", publish=publish,
                )
                assert result["publication"]["state"] == "queued"
                assert consumed[0]["producer"] == identity
    assert len(requests) == 2 and requests[0] == requests[1] and len(published) == 1
    assert requests[0][1]["attempt"] == 2


def test_branch_exit_route_skips_remaining_children_and_reaches_only_its_join(runtime):
    workflow, store, _, _ = runtime
    branch = workflow["flow"]["nodes"][1]["then"]
    workflow["tasks"].append(task("never"))
    branch["nodes"].extend([
        {"id": "exit", "kind": "route", "inputs": [], "condition": {
            "op": "eq", "left": {"literal": 1}, "right": {"literal": 1},
        }, "target": {"exit_region_id": branch["id"]}},
        {"id": "never-node", "kind": "task", "task_id": "never"},
    ])
    flow, calls = run_flow(workflow, store)
    assert "never" not in calls and flow.completed["never-node"]["state"] == "skipped"
    assert flow.completed["joined"]["state"] == "completed" and flow.finished


def test_lost_decision_acknowledgement_does_not_double_admit_or_change_choice(runtime, monkeypatch):
    workflow, store, container, _ = runtime
    original = container.execute_item_batch
    lost = []

    def commit_then_disconnect(batch_operations, partition_key):
        value = original(batch_operations, partition_key)
        if not lost:
            lost.append(True)
            raise CosmosHttpResponseError(status_code=503)
        return value

    with WorkflowRuntimeLease(store, owner_id="worker") as lease:
        monkeypatch.setattr(container, "execute_item_batch", commit_then_disconnect)
        row = store.journal_commit(lease.token, "decision", "decision", {"decision": {"choice": "then"}},
                                   admission=True, immutable=True, updates={"cursor": {"node_id": "choice"}})
        version = store.read()["version"]
        repeated = store.journal_commit(lease.token, "decision", "decision", {"decision": {"choice": "then"}},
                                        admission=True, immutable=True)
        assert repeated == row and store.read()["admitted_count"] == 1 and store.read()["version"] == version


def test_deletion_sweeps_v3_journal_and_genuine_node_sections_but_keeps_tombstone(runtime):
    workflow, store, container, _ = runtime
    run_flow(workflow, store)
    store.tombstone()
    WorkflowResultStore(container).delete_run_results(workflow, "run")
    remaining = list(container.items.values())
    assert len(remaining) == 1 and remaining[0]["type"] == "workflow_runtime_control"
    assert remaining[0]["deleted"] is True


def test_private_journal_records_never_enter_ordinary_run_items():
    path = Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_personal_workflows.py"
    function = next(node for node in ast.parse(path.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "is_public_workflow_run_item")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    for field in ("type", "item_type"):
        assert namespace["is_public_workflow_run_item"]({field: "workflow_runtime_journal"}) is False
    assert namespace["is_public_workflow_run_item"]({"item_type": "task"}) is True


def test_blob_transport_keeps_attempt_namespaces_distinct_and_cleans_genuine_node_results(runtime):
    from test_workflow_result_store import FakeBlobService

    workflow, store, container, _ = runtime
    blobs = FakeBlobService()
    results = WorkflowResultStore(container, blobs, "private-results")
    execution_id = workflow_execution_id(workflow, "run", "yes-node")
    references = []
    for attempt in (1, 2):
        reference = results.save(
            workflow, "run", "yes", {"complete": "same payload"},
            node_id="yes-node", execution_id=execution_id, attempt=attempt, iteration_path=[],
        )
        references.append(reference)
        assert results.load(workflow, "run", "yes", reference, node_id="yes-node",
                            execution_id=execution_id, attempt=attempt, iteration_path=[]) == {"complete": "same payload"}
    assert len(blobs.records) == 2 and references[0] == references[1]
    store.tombstone()
    results.delete_run_results(workflow, "run")
    assert blobs.records == {}
    assert len(container.items) == 1


def test_control_provenance_cannot_bypass_source_authorization_or_claim_analyze_origin(runtime):
    workflow, _, _, _ = runtime
    source = {"document_id": "source", "scope": "personal", "scope_id": "owner", "source_version": 1}
    receipts = []
    for node_id, task_id in (("classify-node", "classify"), ("choice", None), ("report-node", "report")):
        identity = workflow_node_identity(workflow, "run", node_id, workflow_execution_id(workflow, "run", node_id), 1, task_id=task_id)
        envelope = _build_task_result({"reply": "Selected result"}, identity, "workflow-result-v2")
        envelope["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True}
        envelope["consumed_inputs"] = receipts[-1:]
        if not receipts:
            envelope["analysis_access"] = {"version": "analysis-source-access-v1", "sources": [source]}
        manifest, reference = persist_workflow_task_result(envelope, workflow=workflow, run_id="run", task_id=task_id, settings={})
        receipts.append({"producer": identity, "result_ref": reference, "output_name": "text",
                         "output_ref": manifest["outputs"]["text"]["result_ref"], "control": task_id is None})
    authorized = True

    def resolver(ids, **kwargs):
        return [{**source, "authorization_status": "authorized" if authorized else "unresolved"}]

    root, access = authorize_workflow_node_result_read(workflow, "run", identity, reference, source_resolver=resolver)
    assert access["source_count"] == 1 and root.get("analysis_origin") is not True
    authorized = False
    with pytest.raises(AnalysisResultUnavailable):
        authorize_workflow_node_result_read(workflow, "run", identity, reference, source_resolver=resolver)


def test_history_sanitizer_preserves_exact_task_and_control_result_bindings(runtime):
    from functions_saved_analysis import sanitize_workflow_analysis_history

    workflow, store, _, _ = runtime
    flow, _ = run_flow(workflow, store)
    record = {"id": "run", "task_results": [{
        "task_id": item["task"]["id"], "workflow_result": item["result"]["workflow_result"],
        "consumed_inputs": item["consumed_inputs"], "response_preview": "Saved output",
    } for item in flow.task_results]}
    reads = []

    def reader(*args, **kwargs):
        reads.append((args[2], kwargs))
        return authorize_workflow_task_result_read(*args, **kwargs)

    safe, _, available = sanitize_workflow_analysis_history(workflow, record, "owner", result_reader=reader)
    assert available and safe == record
    assert reads and all(item[1]["execution_id"] for item in reads)
    assert any(task_id is None for task_id, _ in reads)
