# test_task_completeness_runtime.py
"""Real-module verification, correction, result eligibility and durable storage.

Version: 0.261.380
Implemented in: 0.261.380
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_orchestration_reason_render_pipeline import narrative_io  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding, render_step


def report(status, quote="Evaluation", refs=None):
    return json.dumps({"requirements": [{
        "id": "details", "requirement": "Include status, proposal deadline and response days.",
        "status": status, "reason": "Requested facts omitted." if status == "missing" else "",
        "evidence_refs": refs or [], "answer_quote": quote if status == "satisfied" else "",
    }]})


def stored_steps(harness):
    return harness.run_store.list_run_steps(harness.run_id, "owner", "conversation-1")


def test_default_on_composition_corrects_twice_with_persisted_final_assessment(harness):
    harness.settings.pop("enable_chat_orchestration_completeness_check")
    harness.create([compose_step()], replies=[
        "Evaluation", report("missing"), "Evaluation, 15 days", report("missing"),
        "Evaluation, 15 days, due 2027-02-15", report("satisfied"),
    ], final_response=input_binding("prepare", "answer"))
    execution = harness.prepare()
    execution.execute()
    saved = harness.read()
    assert saved["status"] == "completed", saved.get("failure")
    rows = stored_steps(harness)
    assert rows[0]["task_completeness"]["corrections"] == 2
    assert rows[0]["task_completeness"]["checks"] == 3
    assert len(harness.model_calls) == 6
    read_store = harness.recovery.checkpoint_store(
        saved, lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
    )
    checkpoint = read_store.load_completeness(
        "prepare", binding=execution.context.completeness_binding,
    )
    assert checkpoint["status"] == "complete"
    assert checkpoint["candidate"] == "Evaluation, 15 days, due 2027-02-15"
    assert checkpoint["original"] == "Evaluation"
    count = len(harness.model_calls)
    harness.read()
    stored_steps(harness)
    assert len(harness.model_calls) == count


def test_exhaustion_blocks_rendering_and_reports_a_safe_failure(harness):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    harness.create([compose_step(), render_step("save", "md")], replies=[
        "Evaluation", report("missing"), "Evaluation", report("missing"), "Evaluation", report("missing"),
    ], final_response=input_binding("prepare", "answer"))
    harness.prepare().execute()
    saved = harness.read()
    assert saved["status"] == "failed"
    rows = stored_steps(harness)
    assert rows[0]["failure"]["code"] == "completeness_incomplete"
    assert rows[0]["task_completeness"]["corrections"] == 2
    assert rows[1]["status"] == "skipped"
    assert len(harness.model_calls) == 6


def test_unavailable_checker_never_publishes_success(harness):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    harness.create([compose_step()], replies=["Evaluation", '{"requirements":[]}'])
    harness.prepare().execute()
    assert harness.read()["status"] == "failed"
    assert stored_steps(harness)[0]["failure"]["code"] == "completeness_unavailable"
    assert len(harness.model_calls) == 2


@pytest.mark.parametrize("initial", ['{"status":"Evaluation"}', "Not JSON"])
def test_workflow_repairs_authoritative_open_json_without_reinvoking_agent(initialized_application, monkeypatch, initial):
    runner = importlib.import_module("functions_workflow_runner")
    results = importlib.import_module("functions_workflow_results")
    calls = []
    corrected = {"status": "Evaluation", "proposal_due": "2027-02-15", "response_days": 15}
    scripted = [json.dumps(corrected), report("satisfied", refs=["tool:0"])]
    if initial.startswith("{"):
        scripted.insert(0, report("missing", refs=["tool:0"]))
    replies = iter(scripted)

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    monkeypatch.setattr(runner, "_resolve_model_workflow_client", lambda *args: (client, "gpt-4o", "aoai"))
    monkeypatch.setattr(runner, "_raise_if_workflow_run_cancelled", lambda *args: None)
    workflow = {"id": "wf", "user_id": "owner", "definition_version": 2}
    task = {
        "id": "task", "type": "instructions",
        "instructions": "Include status, proposal deadline and response days.",
        "output_contract": {"kind": "json", "schema": {
            "type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"],
        }},
    }
    result = {"reply": initial, "agent_citations": [{
        "function_result": corrected, "_verification_evidence": corrected,
        "evidence_truncated": False, "success": True,
    }]}
    envelope = results.build_workflow_task_result(result, workflow=workflow, run_id="run", task=task)
    progress = []
    updated, checked = runner._check_workflow_completeness(
        result, envelope, workflow=workflow, task=task, settings={}, run_id="run", durable=None, unit_key="task",
        progress=progress.append,
    )
    assert checked["outputs"]["json"]["value"] == corrected
    assert checked["task_completeness"]["status"] == "complete"
    assert json.loads(updated["reply"]) == corrected
    assert len(calls) == len(scripted) and all("tools" not in call for call in calls)
    assert calls[-1]["messages"][0]["content"].startswith("Independently check")
    assert progress[-1]["status"] == "complete"
    assert all("candidate" not in item and "original" not in item for item in progress)


@pytest.mark.parametrize("structured", [False, True])
def test_workflow_checkpoint_reentry_reuses_assessment_without_model_or_tool_calls(initialized_application, monkeypatch, structured):
    from test_workflow_durable_execution import RuntimeContainer, Clock
    from functions_workflow_runtime_store import WorkflowRuntimeStore, WorkflowRuntimeLease
    from functions_workflow_execution import DurableWorkflowExecution, workflow_execution_scope
    from functions_workflow_structured_execution import StructuredWorkflowExecution
    from test_workflow_structured_flow import task as structured_task

    runner = importlib.import_module("functions_workflow_runner")
    results = importlib.import_module("functions_workflow_results")
    workflow = {"id": "wf", "user_id": "owner", "durable_execution": True, "definition_version": 3 if structured else 2}
    task = structured_task("task")
    task["instructions"] = "Include the status."
    if structured:
        workflow.update(
            runner_type="model", chat_capabilities_enabled=False, tasks=[task],
            flow={"id": "root", "nodes": [{"id": "task-node", "kind": "task", "task_id": "task"}], "outputs": []},
        )
    result = {"reply": "Evaluation"}
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=report("satisfied")))], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    monkeypatch.setattr(runner, "_resolve_model_workflow_client", lambda *args: (client, "gpt-4o", "aoai"))
    monkeypatch.setattr(runner, "_raise_if_workflow_run_cancelled", lambda *args: None)
    payloads = []

    def save(*args, **kwargs):
        payloads.append(json.loads(json.dumps(args[3])))
        return {"index": len(payloads) - 1}

    def load(*args, **kwargs):
        return json.loads(json.dumps(payloads[args[3]["index"]]))

    store = WorkflowRuntimeStore(RuntimeContainer(), workflow, "run", clock=Clock())
    store.initialize(
        snapshot_ref={"storage": "cosmos", "schema_version": 1, "sha256": "a" * 64, "size_bytes": 100, "chunk_count": 1},
        definition_revision="b" * 64, actor_user_id="owner", request_id="request",
    )
    with WorkflowRuntimeLease(store, owner_id="worker") as lease:
        controller = StructuredWorkflowExecution if structured else DurableWorkflowExecution
        execution = controller(store, lease, workflow, "run", save_result=save, load_result=load)
        if structured:
            execution.set_node(workflow["flow"]["nodes"][0], "root")
        with workflow_execution_scope(execution):
            envelope = results.build_workflow_task_result(result, workflow=workflow, run_id="run", task=task)
            _, checked = runner._check_workflow_completeness(
                dict(result), envelope, workflow=workflow, task=task, settings={},
                run_id="run", durable=execution, unit_key="task:task",
            )
        recreated = controller(store, lease, workflow, "run", save_result=save, load_result=load)
        if structured:
            recreated.set_node(workflow["flow"]["nodes"][0], "root")
        with workflow_execution_scope(recreated):
            _, resumed = runner._check_workflow_completeness(
                dict(result), envelope, workflow=workflow, task=task,
                settings={"enable_workflow_completeness_check": False},
                run_id="run", durable=recreated, unit_key="task:task",
            )
    assert resumed["task_completeness"] == checked["task_completeness"]
    assert resumed["task_completeness"]["status"] == "complete"
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["failed", "pending"])
def test_workflow_execution_failures_are_not_repaired(initialized_application, monkeypatch, failure):
    runner = importlib.import_module("functions_workflow_runner")

    def forbidden(*args):
        raise AssertionError("Failed/pending execution must not call a model.")

    monkeypatch.setattr(runner, "_resolve_model_workflow_client", forbidden)
    result = {"reply": "Evaluation"}
    envelope = {"execution": {"status": failure}}
    updated, checked = runner._check_workflow_completeness(
        result, envelope, workflow={}, task={}, settings={}, run_id="run", durable=None, unit_key="task",
    )
    assert updated is result and checked is envelope


@pytest.mark.parametrize("verdict", ["satisfied", "missing"])
def test_immutable_document_results_are_checked_without_rewriting_source_outputs(initialized_application, monkeypatch, verdict):
    runner = importlib.import_module("functions_workflow_runner")
    results = importlib.import_module("functions_workflow_results")
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=report(verdict)))], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    monkeypatch.setattr(runner, "_resolve_model_workflow_client", lambda *args: (client, "gpt-4o", "aoai"))
    monkeypatch.setattr(runner, "_raise_if_workflow_run_cancelled", lambda *args: None)
    workflow = {"id": "wf", "user_id": "owner", "definition_version": 2}
    task = {"id": "task", "type": "instructions", "instructions": "Include the status."}
    result = {"reply": "Evaluated one document.", "analysis_result": {
        "per_document": True, "document_results": [{
            "document_id": "document-1", "full_result": {"text": "Evaluation"},
        }],
    }}
    envelope = results.build_workflow_task_result(result, workflow=workflow, run_id="run", task=task)
    updated, checked = runner._check_workflow_completeness(
        result, envelope, workflow=workflow, task=task, settings={},
        run_id="run", durable=None, unit_key="task",
    )
    assert checked["authoritative_output"] == "documents"
    assert checked["outputs"]["documents"] == envelope["outputs"]["documents"]
    assert checked["task_completeness"]["corrections"] == 0
    assert checked["task_completeness"]["status"] == ("complete" if verdict == "satisfied" else "incomplete")
    assert updated["reply"] == "Evaluated one document."
    assert "authoritative_result" not in updated and len(calls) == 1


@pytest.mark.parametrize("verdict", ["satisfied", "missing"])
def test_retained_final_report_is_check_only_and_does_not_repeat_producer(harness, narrative_io, verdict):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    stages = []

    def model_reply():
        if harness.model_calls[-1]["messages"][0]["content"].startswith("Independently check"):
            stages.append("checker")
            judgment = json.loads(report(verdict, "Complete finding 006.", ["records"]))
            judgment["requirements"][0]["requirement"] = "Retain every original finding, including the last item."
            return json.dumps(judgment)
        stages.append("producer")
        return narrative_io["reply"]()

    harness.create([{
        "step_id": "analyze", "capability_id": "document_analyze",
        "arguments": {
            "document_ids": ["document-1"], "doc_scope": "personal",
            "analysis_prompt": "Retain every original finding, including the last item.",
        },
        "outputs": [
            {"name": "findings", "kind": "records-v1"},
            {"name": "coverage", "kind": "structured-v1"},
            {"name": "records", "kind": "records-v1"},
            {"name": "report", "kind": "markdown-v1"},
        ],
    }], replies=[model_reply] * 20, final_response=input_binding("analyze", "report"),
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"})
    execution = harness.prepare()
    execution.execute()
    assert harness.read()["status"] == ("completed" if verdict == "satisfied" else "failed")
    row = stored_steps(harness)[0]
    assert row["task_completeness"]["status"] == ("complete" if verdict == "satisfied" else "incomplete")
    assert row["task_completeness"]["corrections"] == 0
    assert stages[-1] == "checker" and stages.count("checker") == 1
    assert stages.count("producer") > 0
    if verdict == "missing":
        assert row["failure"]["code"] == "completeness_incomplete"
        assert "analyze" not in execution.context.task_results
    else:
        task = execution.context.task_results["analyze"]
        retained = harness.services().results.open_result(task.output("report")).read_text()
        assert "Complete finding 006." in retained
    count = len(harness.model_calls)
    harness.read()
    stored_steps(harness)
    assert len(harness.model_calls) == count
