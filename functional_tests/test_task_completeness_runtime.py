# test_task_completeness_runtime.py
"""Real-module verification, correction, result eligibility and durable storage.

Version: 0.261.417
Implemented in: 0.261.382; 0.261.384; 0.261.416; 0.261.417
"""

import importlib
import json
import sys
from copy import copy, deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from azure.core import MatchConditions
from openai import (
    APIConnectionError, AuthenticationError, BadRequestError, PermissionDeniedError, RateLimitError,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_orchestration_reason_render_pipeline import narrative_io  # noqa: F401
from functions_task_completeness import NARRATIVE_OBLIGATIONS
from test_support.orchestration_harness_execution import (
    CompletionClient, compose_step, decoded_frames, input_binding, render_step,
)


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
        "Evaluation", report("missing"), "Evaluation first", report("missing"), "Evaluation final", report("missing"),
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
    harness.create([compose_step()], replies=["Evaluation", '{"requirements":[]}', '{"requirements":[]}'])
    harness.prepare().execute()
    assert harness.read()["status"] == "failed"
    assert stored_steps(harness)[0]["failure"]["code"] == "completeness_unavailable"
    assert len(harness.model_calls) == 3


SOURCE_MESSAGE = (
    "Please rewrite this as a polished note: Our project demonstration went really well. "
    "Alex asked whether the service was already deployed. It is deployed, and the team "
    "was pleased with the reception."
)
PREPARED_DRAFT = (
    "Our project demonstration went exceptionally well. Alex asked whether the service "
    "was already deployed, and we confirmed that it is. The team was delighted with the reception."
)


def draft_assessment():
    return json.dumps({"requirements": {
        identifier: {"status": "satisfied", "reason": "", "evidence_refs": ["user_provided_content"],
                     "answer_quote": PREPARED_DRAFT}
        for identifier, _ in NARRATIVE_OBLIGATIONS
    }})


def create_context_draft(harness, replies, *, review="auto", intent="transform_supplied_text"):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    harness.turn["content"] = SOURCE_MESSAGE
    current = harness.messages.read_item(harness.turn["id"], harness.turn["conversation_id"])
    harness.messages.replace_item(
        harness.turn["id"], harness.turn, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    step = compose_step()
    step["arguments"].update(
        instruction="Rewrite the user's account as a polished note without adding facts.",
        response_policy="available_information", semantic_review=review,
    )
    if intent is not None:
        step["arguments"]["content_intent"] = intent
    harness.create([step], replies=replies, final_response=input_binding("prepare", "answer"))
    return step


@pytest.mark.parametrize("checker_reply", [
    "Not JSON", '{"requirements":{"personalized_check":{}}}', "",
    APIConnectionError(request=httpx.Request("POST", "https://offline.invalid")),
    RateLimitError("Unavailable", response=httpx.Response(
        429, request=httpx.Request("POST", "https://offline.invalid"),
    ), body=None),
])
def test_real_context_only_auto_delivers_retained_draft_after_checker_error(harness, checker_reply):
    create_context_draft(harness, [PREPARED_DRAFT, checker_reply])
    execution = harness.prepare()
    frames = execution.execute()
    saved = harness.read()
    rows = stored_steps(harness)
    messages = harness.assistant_messages()
    assert saved["status"] == "completed", saved.get("failure")
    final = decoded_frames(frames)[-1]
    assert final["full_content"] == messages[-1]["content"] == PREPARED_DRAFT
    assert len(harness.model_calls) == 2 and harness.replies == []
    checked = rows[0]["task_completeness"]
    assert checked["status"] == "complete" and checked["deterministic_status"] == "passed"
    assert checked["semantic_enabled"] is True and checked["stages"][-1]["status"] == "skipped"
    assert checked["evidence_basis"] == "user_message" and checked["corrections"] == 0
    assert checked["semantic_skip_reason"].startswith("completeness_")
    payload = json.loads(harness.model_calls[1]["messages"][-1]["content"])
    assert payload["evidence"]["user_provided_content"] == SOURCE_MESSAGE
    assert payload["instruction"]["approved_request"] == SOURCE_MESSAGE
    response_format = harness.model_calls[1]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"]["properties"]["requirements"]["required"] == [
        identifier for identifier, _ in NARRATIVE_OBLIGATIONS
    ]
    read_store = harness.recovery.checkpoint_store(
        saved, lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
    )
    checkpoint = read_store.load_completeness("prepare", binding=execution.context.completeness_binding)
    assert checkpoint["candidate"] == PREPARED_DRAFT and checkpoint["original"] == PREPARED_DRAFT
    assert checkpoint["semantic_status"] == "skipped"
    calls = len(harness.model_calls)
    reloaded = harness.read()
    rows_after_reload = stored_steps(harness)
    assert reloaded["status"] == "completed" and rows_after_reload[0]["task_completeness"] == checked
    assert len(harness.model_calls) == calls


@pytest.mark.parametrize("review,intent", [
    ("on", "transform_supplied_text"), ("auto", None), ("auto", "substantive"),
])
def test_on_or_unproven_context_tasks_keep_the_review_failure_gate(harness, review, intent):
    create_context_draft(harness, [PREPARED_DRAFT, "Not JSON", "Not JSON"], review=review, intent=intent)
    harness.prepare().execute()
    saved = harness.read()
    rows = stored_steps(harness)
    assert saved["status"] == "failed" and len(harness.model_calls) == 3
    assert rows[0]["failure"]["code"] == "completeness_unavailable"
    assert "semantic_skip_reason" not in rows[0]["task_completeness"]


def response_format_rejected():
    return BadRequestError("Unsupported response format.", response=httpx.Response(
        400, request=httpx.Request("POST", "https://offline.invalid"),
    ), body={"error": {"param": "response_format", "code": "unsupported_parameter"}})


def test_schema_rejection_uses_same_closed_review_in_json_compatibility_mode(harness):
    create_context_draft(harness, [PREPARED_DRAFT, response_format_rejected(), draft_assessment()])
    harness.prepare().execute()
    saved = harness.read()
    rows = stored_steps(harness)
    assert saved["status"] == "completed" and len(harness.model_calls) == 3
    assert harness.model_calls[1]["response_format"]["type"] == "json_schema"
    assert harness.model_calls[2]["response_format"] == {"type": "json_object"}
    assert harness.model_calls[1]["messages"] == harness.model_calls[2]["messages"]
    assert rows[0]["task_completeness"]["stages"][-1]["status"] == "completed"
    assert "semantic_skip_reason" not in rows[0]["task_completeness"]


def test_two_format_rejections_use_bounded_prompt_only_compatibility(harness):
    create_context_draft(harness, [
        PREPARED_DRAFT, response_format_rejected(), response_format_rejected(), draft_assessment(),
    ])
    harness.prepare().execute()
    saved = harness.read()
    assert saved["status"] == "completed" and len(harness.model_calls) == 4
    assert "response_format" not in harness.model_calls[-1]
    assert harness.model_calls[-1]["messages"] == harness.model_calls[1]["messages"]


@pytest.mark.parametrize("error_type,status", [
    (BadRequestError, 400), (AuthenticationError, 401), (PermissionDeniedError, 403),
])
def test_unrelated_provider_rejections_neither_downgrade_format_nor_skip_review(harness, error_type, status):
    failure = error_type("Request rejected.", response=httpx.Response(
        status, request=httpx.Request("POST", "https://offline.invalid"),
    ), body={"error": {"param": "messages", "code": "invalid_request"}})
    create_context_draft(harness, [PREPARED_DRAFT, failure])
    harness.prepare().execute()
    saved = harness.read()
    rows = stored_steps(harness)
    assert saved["status"] == "failed" and len(harness.model_calls) == 2
    assert "semantic_skip_reason" not in rows[0]["task_completeness"]


@pytest.mark.parametrize("filtered", [True, False])
def test_checker_refusal_and_content_filter_are_not_optional_outages(harness, monkeypatch, filtered):
    original = CompletionClient.create

    def create(client, **kwargs):
        if kwargs["messages"][0]["content"].startswith("Independently check"):
            client.environment.model_calls.append(deepcopy(kwargs))
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                finish_reason="content_filter" if filtered else "stop",
                message=SimpleNamespace(content="", refusal=None if filtered else "Refused"),
            )])
        return original(client, **kwargs)

    monkeypatch.setattr(CompletionClient, "create", create)
    create_context_draft(harness, [PREPARED_DRAFT])
    harness.prepare().execute()
    saved = harness.read()
    rows = stored_steps(harness)
    assert saved["status"] == "failed" and len(harness.model_calls) == 2
    assert "semantic_skip_reason" not in rows[0]["task_completeness"]


def test_source_authority_loss_during_checker_outage_still_blocks_delivery(harness):
    def unavailable_after_access_loss():
        current = harness.conversations.read_item(harness.conversation["id"], harness.conversation["id"])
        harness.conversations.replace_item(
            harness.conversation["id"], {**harness.conversation, "user_id": "another-owner"},
            etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
        )
        return APIConnectionError(request=httpx.Request("POST", "https://offline.invalid"))

    create_context_draft(harness, [PREPARED_DRAFT, unavailable_after_access_loss])
    execution = harness.prepare()
    execution.execute()
    saved = harness.read()
    messages = harness.assistant_messages()
    assert saved["status"] != "completed" and messages == [] and len(harness.model_calls) == 2
    assert execution.lease.stopped.is_set()


@pytest.mark.parametrize("masked", [False, True])
def test_user_message_changed_during_checker_outage_cannot_complete_optional_recovery(harness, masked):
    def unavailable_after_source_change():
        current = harness.messages.read_item(harness.turn["id"], harness.turn["conversation_id"])
        changed = (
            {**current, "metadata": {**(current.get("metadata") or {}), "masked": True}}
            if masked else {**current, "content": "A different request replaced the original message."}
        )
        harness.messages.replace_item(
            harness.turn["id"], changed, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
        )
        return APIConnectionError(request=httpx.Request("POST", "https://offline.invalid"))

    create_context_draft(harness, [PREPARED_DRAFT, unavailable_after_source_change])
    execution = harness.prepare()
    execution.execute()
    saved = harness.read()
    rows = stored_steps(harness)
    messages = harness.assistant_messages()
    assert saved["status"] != "completed" and len(harness.model_calls) == 2
    assert all(message.get("content") != PREPARED_DRAFT for message in messages)
    assert all(row.get("task_completeness", {}).get("status") != "complete" for row in rows)
    assert execution.lease.stopped.is_set()


def test_context_intent_cannot_bypass_required_structured_output(harness):
    harness.settings["chat_orchestration_completeness_max_corrections"] = 0
    step = compose_step()
    step["arguments"].update(
        response_policy="available_information", content_intent="draft_supplied_text",
    )
    step["outputs"] = [{
        "name": "answer", "kind": "structured-v1",
        "schema": {"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]},
    }]
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    with pytest.raises(harness.schema.PlanValidationError, match="require narrative outputs"):
        harness.create([step])
    step["arguments"]["response_policy"] = "complete_inputs"
    harness.create([step], replies=['{"answer":{"total":"12"}}'])
    harness.prepare().execute()
    saved = harness.read()
    rows = stored_steps(harness)
    assert saved["status"] == "failed" and len(harness.model_calls) == 1
    assert rows[0]["failure"]["code"] == "completeness_incomplete"
    assert rows[0]["task_completeness"]["deterministic_status"] == "failed"


@pytest.mark.parametrize("intent", ["unknown", True, None])
def test_content_intent_is_a_validated_plan_argument(harness, intent):
    step = compose_step()
    step["arguments"]["content_intent"] = intent
    with pytest.raises(harness.schema.PlanValidationError):
        harness.create([step])


@pytest.mark.parametrize("with_corrections", [False, True])
@pytest.mark.parametrize("checkpoint_missing", [False, True])
def test_explicit_retry_rechecks_retained_candidate_without_regeneration(harness, with_corrections, checkpoint_missing):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    replies = (
        ["Evaluation", report("missing"), "Evaluation first", report("missing"), "Evaluation final", report("missing")]
        if with_corrections else ["Evaluation", '{"requirements":[]}', '{"requirements":[]}']
    )
    harness.create([compose_step()], replies=replies)
    execution = harness.prepare()
    execution.execute()
    original = harness.read()
    assert harness.recovery.recovery_projection(original)["retry_scope"] == "check"
    authorize = lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1")

    def validate(source):
        probe = copy(execution.context)
        probe.result_service = harness.services().results
        return harness.recovery.validate_resume(
            source, probe, harness.settings, authorize, source_run_id=source["id"],
        )

    child = harness.recovery.prepare_retry(
        original["id"], "owner", {
            "conversation_id": "conversation-1", "expected_version": original["recovery_version"],
            "submission_id": "explicit-check-retry",
        }, authorize=authorize, validate=validate, message_container=harness.messages,
    )
    harness.run_id = child["id"]
    assert child["retry_scope"] == "check"
    harness.replies = [report("satisfied")]
    if checkpoint_missing:
        harness.monkeypatch.setattr(type(execution.context.completeness_store), "load_completeness", lambda *args, **kwargs: None)
    harness.prepare().execute()
    if checkpoint_missing:
        assert harness.read()["status"] == "failed"
        assert len(harness.model_calls) == len(replies)
        return
    assert harness.read()["status"] == "completed", harness.read().get("failure")
    assert len(harness.model_calls) == len(replies) + 1
    assert harness.model_calls[-1]["messages"][0]["content"].startswith("Independently check")
    checked_payload = json.loads(harness.model_calls[-1]["messages"][-1]["content"])
    assert checked_payload["candidate"] == ("Evaluation final" if with_corrections else "Evaluation")
    assert stored_steps(harness)[0]["task_completeness"]["corrections"] == (2 if with_corrections else 0)


def test_semantic_review_off_preserves_mandatory_schema_correction(harness):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    step = compose_step()
    step["arguments"]["semantic_review"] = "off"
    step["outputs"] = [{
        "name": "answer", "kind": "structured-v1",
        "schema": {"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]},
    }]
    harness.create([step], replies=['{"answer":{"total":"12"}}', '{"answer":{"total":12}}'])
    execution = harness.prepare()
    execution.execute()
    assert harness.read()["status"] == "completed", harness.read().get("failure")
    assert len(harness.model_calls) == 2
    feedback = json.loads(harness.model_calls[1]["messages"][-1]["content"])
    assert '"path": ["total"]' in feedback["deficiencies"][0]
    assert '"expected": "number"' in feedback["deficiencies"][0]
    report_value = stored_steps(harness)[0]["task_completeness"]
    assert report_value["deterministic_status"] == "passed" and report_value["semantic_enabled"] is False
    assert report_value["stages"][-1]["status"] == "skipped"


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


def test_compose_completeness_receives_saved_memory_and_conversation_history(harness):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    memory_messages = [
        {
            "role": "system",
            "content": (
                "<Instruction Memory>\n"
                "- For my Civic Bridge review CB-27-983413, start each brief with "
                "'Civic Bridge desk brief (CB-27-983413)' on its own line. Use these three "
                "section headings, in order: Decision, Evidence, Next step.\n"
                "</Instruction Memory>"
            ),
        },
        {
            "role": "system",
            "content": (
                "<Fact Memory>\n"
                "- For Civic Bridge review CB-27-983413, please address me as Avery; "
                "I'm the readiness reviewer. Rowan owns the mission.\n"
                "</Fact Memory>"
            ),
        },
    ]
    candidate = (
        "Civic Bridge desk brief (CB-27-983413)\n\n"
        "## Decision\n"
        "Avery, readiness reviewer: maintain amber readiness for Civic Bridge review CB-27-983413.\n\n"
        "## Evidence\n"
        "Training brief FED-PROGRAM-027 has a $200,000 budget, amber readiness, and Rowan as mission owner.\n\n"
        "## Next step\n"
        "Review readiness dependencies with Rowan."
    )
    checker_reply = json.dumps({
        "requirements": [
            {
                "id": "prefix",
                "requirement": "Start with Civic Bridge desk brief (CB-27-983413) on its own line.",
                "status": "satisfied",
                "reason": "Starts with the saved instruction prefix.",
                "evidence_refs": ["saved_memory"],
                "answer_quote": "Civic Bridge desk brief (CB-27-983413)",
            },
            {
                "id": "headings",
                "requirement": "Use Markdown headings ## Decision, ## Evidence, ## Next step in order.",
                "status": "satisfied",
                "reason": "Uses the three required headings in order.",
                "evidence_refs": ["saved_memory"],
                "answer_quote": "## Decision ... ## Evidence ... ## Next step",
            },
            {
                "id": "persona_and_history",
                "requirement": "Address Avery, readiness reviewer, and preserve prior baseline facts.",
                "status": "satisfied",
                "reason": "Addresses Avery and preserves baseline facts.",
                "evidence_refs": ["saved_memory", "conversation_history"],
                "answer_quote": "Avery, readiness reviewer",
            },
            {
                "id": "no_em_dash",
                "requirement": "Do not use em dashes.",
                "status": "satisfied",
                "reason": "No em dashes are used.",
                "evidence_refs": [],
                "answer_quote": "",
            },
        ]
    })
    harness.create([compose_step()], replies=[candidate, checker_reply], final_response=input_binding("prepare", "answer"))
    execution = harness.prepare()
    execution.context.memory_context = {
        **execution.context.memory_context,
        "status": "available",
        "context_messages": memory_messages,
        "notices": [],
    }
    execution.context.reload_memory_context = lambda: execution.context.memory_context
    history_messages = [
        {"id": "m1", "role": "user", "content": "Civic Bridge review CB-27-983413 baseline is $200,000."},
        {"id": "m2", "role": "assistant", "content": "Noted the $200,000 baseline for CB-27-983413."},
    ]
    execution.context.read_conversation_messages = lambda: history_messages
    execution.execute()

    saved = harness.read()
    assert saved["status"] == "completed", saved.get("failure")
    checker_call = harness.model_calls[-1]
    checker_payload = json.loads(checker_call["messages"][1]["content"])
    assert "saved_memory" in checker_payload["evidence"]
    assert "conversation_history" in checker_payload["evidence"]
    assert "Current saved Instruction Memory and Fact Memory supersede" in checker_payload["contract"]["generation_policy"]


def test_scoped_memory_candidates_do_not_leak_into_unmatched_conversations():
    memory_module = importlib.import_module("functions_fact_memory_context")
    items = [
        {
            "id": "cb-1",
            "memory_type": "instruction",
            "value": (
                "For my Civic Bridge review CB-27-983413, start each brief with "
                "'Civic Bridge desk brief (CB-27-983413)' on its own line. "
                "These preferences apply to Civic Bridge review CB-27-983413."
            ),
            "updated_at": "2026-10-23T19:43:34+00:00",
        },
        {
            "id": "cb-2",
            "memory_type": "instruction",
            "value": (
                "For my Civic Bridge review CB-27-9672AB, start each brief with "
                "'Civic Bridge desk brief (CB-27-9672AB)' on its own line. "
                "These preferences apply to Civic Bridge review CB-27-9672AB."
            ),
            "updated_at": "2026-10-23T12:37:22+00:00",
        },
        {
            "id": "fed-1",
            "memory_type": "instruction",
            "value": (
                "For this synthetic exercise only, when the user message contains "
                "FED-repair2-20261017-FED-38, start your answer with the exact line "
                "BRIEF-42ffe3e63b-R1. Do not apply this format to messages without that exercise label."
            ),
            "updated_at": "2026-10-17T23:03:58+00:00",
        },
        {
            "id": "global-1",
            "memory_type": "instruction",
            "value": "Do not use em dashes.",
            "updated_at": "2026-08-04T20:01:20+00:00",
        },
    ]

    unscoped_query = "Which program is 10 seconds on and 10 seconds off? https://manuals.plus/m/424434ca_optim.pdf"
    selected_unscoped = memory_module._select_scoped_memory_candidates(items, query_text=unscoped_query)
    assert [item["id"] for item in selected_unscoped] == ["global-1"]

    other_review_query = "I'm working on Civic Bridge review CB-27-7D616B. Give me a baseline summary."
    selected_other = memory_module._select_scoped_memory_candidates(items, query_text=other_review_query)
    assert [item["id"] for item in selected_other] == ["global-1"]

    matching_query = "I'm working on Civic Bridge review CB-27-983413. Give me a baseline summary."
    selected_matching = memory_module._select_scoped_memory_candidates(items, query_text=matching_query)
    assert [item["id"] for item in selected_matching] == ["cb-1", "global-1"]


def test_pdf_source_review_extracts_page_coverage_and_unfound_source_completes(harness):
    import fitz

    source_review = importlib.import_module("functions_source_review")
    adapters = importlib.import_module("functions_orchestration_adapters")
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Manual Title: Timer Controller\nProgram 1 runs 30 seconds on and 30 seconds off.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Program 2 runs continuous mode for 5 minutes.")
    pdf_bytes = doc.tobytes()
    doc.close()

    extracted = source_review.extract_source_review_evidence_from_pdf(
        pdf_bytes=pdf_bytes,
        url="https://manuals.example/timer_manual.pdf",
        user_message="Which program runs 10 seconds on and 10 seconds off?",
    )
    assert extracted["status"] == "reviewed"
    assert extracted["content_type"] == "application/pdf"
    assert extracted["pdf_page_count"] == 2
    assert extracted["pdf_pages_reviewed"] == 2
    assert any("2 total page(s); 2 page(s) inspected" in excerpt for excerpt in extracted["excerpts"])

    compacted = source_review._compact_page_for_evidence(extracted)
    assert compacted["pdf_page_count"] == 2
    assert compacted["pdf_pages_reviewed"] == 2
    notes = adapters._notes_from_source_review({"pages": [compacted]})
    assert any("2 of 2 PDF page(s) inspected" in note for note in notes)
