# test_workflow_policy_failures.py
"""
Functional regressions for deterministic workflow policy failures.
Version: 0.261.430
Implemented in: 0.261.362

Real request budgets, durable controllers, task sequence bodies and runtime projections
exercise refusal, halt/continue, later-round effects and separate corrected runs. The
existing integration fixture replaces external services, not the failure policy.
"""

import asyncio
import copy
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
from openai import (
    AuthenticationError, BadRequestError, InternalServerError, NotFoundError,
    PermissionDeniedError, RateLimitError,
)
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import kernel_function

from test_workflow_runtime_integration import integration
from test_workflow_context_budget import ToolCallingCompletion
import functions_workflow_runtime as runtime
from functions_model_capabilities import ModelTokenBudgetError
from functions_model_endpoint_diagnostics import SanitizedModelEndpointError
from functions_workflow_context import WorkflowModelClient, wrap_workflow_chat_service, workflow_context_budget_scope
from functions_workflow_policy_errors import workflow_policy_failure
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_execution import workflow_unit
from functions_workflow_results import persist_workflow_task_result, authorize_workflow_task_result_read
from model_endpoint_profiles import GenAIMilRequestError


ROOT = Path(__file__).resolve().parents[1]
MODEL = {
    "modelName": "gpt-4o", "contextWindow": 1024, "outputTokenLimit": 128,
    "outputTokenAccounting": "total_generation",
}


def prepare(integration, monkeypatch, *, structured=False, group=False, strategy="halt", retries=0):
    workflow, runner, services, make_store, clock, requests = integration
    workflow.update(runner_type="agent", error_handling={"strategy": strategy, "retry_count": retries})
    workflow["tasks"] = [{
        "id": "check", "type": "instructions", "name": "Check records",
        "instructions": "Read the records.", "runner": {"type": "inherit"},
        "document_action": {"type": "none"}, "inputs": [], "output_contract": {"kind": "text"},
    }]
    if structured:
        workflow.update(definition_version=3, flow={
            "id": "root", "nodes": [{"id": "check-node", "kind": "task", "task_id": "check"}],
            "outputs": [{"name": "answer", "source": {"kind": "node_output", "node_id": "check-node"}}],
        })
        container = make_store(workflow, "unused").container
        monkeypatch.setattr("functions_workflow_result_store._configured_store", lambda *a, **k: WorkflowResultStore(container))
        runner.update({
            "persist_workflow_task_result": persist_workflow_task_result,
            "authorize_workflow_task_result_read": authorize_workflow_task_result_read,
        })
    if group:
        workflow.update(group_id="group", workspace_type="group")
        services["partition"] = "group"
        services["definitions"].partition_field = "group_id"
        services["runs"].partition_field = "group_id"
        services["load_workflow"] = lambda: services["definitions"].read_item(item=workflow["id"], partition_key="group")
        runner["normalize_group_workflow_task_runner"] = lambda *a, **k: {"type": "inherit"}
        runner["get_group_workflow_run"] = lambda group_id, run_id: services["runs"].read_item(item=run_id, partition_key=group_id)
        runner["get_group_workflow"] = lambda *a, **k: services["load_workflow"]()
    services["definitions"].upsert_item(workflow)
    return workflow, runner, services, make_store


def budget_dispatch(calls, *, later_round=False, configuration_error=False):
    def invoke(workflow, *args, **kwargs):
        def provider(**request):
            calls.append(request)
            return "accepted"

        model = {**MODEL, **({"outputTokenAccounting": "unknown"} if configuration_error else {})}
        client = WorkflowModelClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider))), model, "aoai")
        if later_round:
            client.chat.completions.create(messages=[{"role": "user", "content": "Read one record."}])
        client.chat.completions.create(messages=[{"role": "user", "content": "record " * 3000}])
        raise AssertionError("An oversized or unbounded request must not reach the provider.")
    return invoke


def run_once(workflow, services):
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    run_id = queued["run"]["id"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    record = services["runs"].read_item(item=run_id, partition_key=services["partition"])
    return run_id, record


@pytest.mark.parametrize("model_name", ["gpt-4o", "gpt-4o-mini", "gpt-4.1"])
def test_catalog_budget_accepts_full_request_above_compatibility_allowance(model_name):
    sent = []
    model = {"modelName": model_name, "deploymentName": model_name}
    client = WorkflowModelClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: sent.append(kwargs),
    ))), model, "aoai")
    messages = [{"role": "user", "content": "record " * 9000}]
    tools = [{"type": "function", "function": {"name": "read_record", "description": "Read a record.",
              "parameters": {"type": "object", "properties": {"id": {"type": "string"}}}}}]
    workflow = {}
    with workflow_context_budget_scope(workflow):
        client.chat.completions.create(messages=messages, tools=tools)
    assert len(sent) == 1
    assert sent[0]["messages"] == messages and sent[0]["tools"] == tools
    assert workflow["context_budget"]["input_tokens"] > 7936
    assert workflow["context_budget"]["limit_source"] == "catalog"
    assert workflow["context_budget"]["decision"] == "full_input"
    assert workflow["context_budget"]["truncated"] is False


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("retries", [0, 3])
def test_refused_first_request_is_a_terminal_diagnosable_failure(integration, monkeypatch, structured, group, retries):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, group=group, retries=retries)
    calls = []
    runner["_execute_workflow_dispatch"] = budget_dispatch(calls)
    task_items = []
    save_item = runner["_save_workflow_run_item_record"]

    def record_item(wf, item):
        task_items.append(copy.deepcopy(item))
        return save_item(wf, item)

    runner["_save_workflow_run_item_record"] = record_item
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()
    assert calls == []
    assert record["status"] == control["state"] == "failed", control
    assert record["error_code"] == "workflow_context_budget_exceeded"
    assert "input budget" in record["error"]
    assert record["completed_at"]
    current_workflow = services["load_workflow"]()
    assert current_workflow["active_run_id"] == ""
    assert current_workflow["last_run_status"] == "failed"
    item = task_items[-1]
    assert item["status"] == "failed" and item["attempt_count"] == 1
    assert item["error_code"] == record["error_code"]
    assert item["context_budget"]["decision"] == "blocked"
    assert item["context_budget"]["input_tokens"] > item["context_budget"]["input_budget_tokens"]
    if structured:
        execution_rows = [row["payload"] for row in make_store(workflow, run_id).container.items.values()
                          if row.get("record_kind") == "execution" and row.get("run_id") == run_id]
        assert len(execution_rows) == 1
        assert execution_rows[0]["state"] == "failed"
        assert execution_rows[0]["error_code"] == record["error_code"]
    else:
        unit = control["units"]["task:check"]
        assert unit["state"] == "failed" and unit["replay_safe"] is False
        assert unit["error_code"] == record["error_code"]


@pytest.mark.parametrize("structured", [False, True])
def test_later_round_failure_never_replays_prior_effects(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    calls = []
    runner["_execute_workflow_dispatch"] = budget_dispatch(calls, later_round=True)
    run_id, record = run_once(workflow, services)
    runtime.continue_durable_workflow_run(workflow, run_id)
    assert record["status"] == "failed"
    assert len(calls) == 1
    control = make_store(workflow, run_id).read()
    assert control["state"] == "failed"


@pytest.mark.parametrize("structured", [False, True])
def test_model_configuration_refusal_is_not_retried_or_exposed_raw(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    calls = []
    runner["_execute_workflow_dispatch"] = budget_dispatch(calls, configuration_error=True)
    run_id, record = run_once(workflow, services)
    assert calls == []
    assert record["status"] == "failed"
    assert record["error_code"] == "model_generation_unbounded"
    assert "total-generation" in record["error"]
    failure = workflow_policy_failure(ModelTokenBudgetError("model_context_invalid", "PRIVATE PROVIDER SECRET"))
    assert "PRIVATE" not in failure["error"]
    control = make_store(workflow, run_id).read()
    assert control["state"] == "failed"


@pytest.mark.parametrize("structured", [False, True])
def test_excessive_response_length_finishes_without_recovery(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    calls = []
    client = WorkflowModelClient(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: calls.append(kwargs),
    ))), MODEL, "aoai")
    runner["_execute_workflow_dispatch"] = lambda *a, **k: client.chat.completions.create(
        messages=[{"role": "user", "content": "Short request"}], max_tokens=129,
    )
    run_id, record = run_once(workflow, services)
    assert calls == []
    assert record["status"] == "failed"
    assert record["error_code"] == "model_context_invalid"
    control = make_store(workflow, run_id).read()
    assert control["state"] == "failed"


@pytest.mark.parametrize("structured", [False, True])
def test_corrected_explicit_run_keeps_original_failure(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured)
    runner["_execute_workflow_dispatch"] = budget_dispatch([])
    original_id, original = run_once(workflow, services)
    original_control = make_store(workflow, original_id).read()
    changed = services["load_workflow"]()
    changed["tasks"][0]["instructions"] = "Read only the accepted record."
    services["definitions"].upsert_item(changed)
    runner["_execute_workflow_dispatch"] = lambda *a, **k: {"reply": "Verified record: Evaluation."}
    new_id, succeeded = run_once(changed, services)
    assert new_id != original_id
    assert succeeded["status"] == "completed", succeeded.get("error")
    preserved = services["runs"].read_item(item=original_id, partition_key=services["partition"])
    preserved_control = make_store(workflow, original_id).read()
    assert preserved == original
    assert preserved_control == original_control


@pytest.mark.parametrize("structured", [False, True])
def test_arbitrary_operation_errors_still_require_explicit_recovery(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    calls = []

    def uncertain(*args, **kwargs):
        calls.append("effect")
        raise ValueError("PRIVATE operation failure; not proof of a policy refusal")

    runner["_execute_workflow_dispatch"] = uncertain
    run_id, record = run_once(workflow, services)
    runtime.continue_durable_workflow_run(workflow, run_id)
    control = make_store(workflow, run_id).read()
    assert record["status"] == control["state"] == "waiting_recovery"
    assert calls == ["effect"]
    assert control["gate"]["choices"] == ["retry", "cancel"]
    assert "PRIVATE" not in control["gate"]["reason"]


@pytest.mark.parametrize("structured", [False, True])
def test_http_provider_rejection_finishes_without_nonreplayable_recovery(
    integration, monkeypatch, structured,
):
    workflow, runner, services, make_store = prepare(
        integration, monkeypatch, structured=structured, retries=3,
    )
    calls = []

    def rejected(*args, **kwargs):
        calls.append("provider")
        raise SanitizedModelEndpointError(
            "Custom model request failed. (reference abc12345)",
            correlation_reference="abc12345",
            status_code=400,
            api_type="anthropic",
            protocol="messages",
        )

    runner["_execute_workflow_dispatch"] = rejected
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()

    assert calls == ["provider"]
    assert record["status"] == control["state"] == "failed", control
    assert record["error_code"] == "model_provider_request_failed"
    assert record["error"] == "Custom model request failed. (reference abc12345)"
    assert record["correlation_reference"] == "abc12345"
    assert record["effect_certainty"] == "none"
    assert (control.get("gate") or {}).get("kind") != "recovery"


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("status,error_type", [
    (400, BadRequestError), (401, AuthenticationError), (403, PermissionDeniedError),
    (404, NotFoundError), (429, RateLimitError), (503, InternalServerError),
])
def test_real_native_sdk_invocation_retains_safe_reason_and_bounded_retry(
    integration, monkeypatch, structured, status, error_type,
):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=2)
    calls = []

    def provider(**kwargs):
        calls.append(kwargs)
        if status in (429, 503) and len(calls) == 3:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Recovered."))])
        raise error_type(
            "PRIVATE provider URL and credentials must never reach task history",
            response=httpx.Response(status, request=httpx.Request("POST", "https://offline.invalid")),
            body={"error": {"message": "PRIVATE", "type": "private_provider_type"}},
        )

    def dispatch(*args, **kwargs):
        client = WorkflowModelClient(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider))), MODEL, "aoai",
        )
        completion = client.chat.completions.create(model="model", messages=[{"role": "user", "content": "Check."}])
        return {"reply": completion.choices[0].message.content}

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()
    if status in (429, 503):
        assert len(calls) == 3
        assert record["status"] == control["state"] == "completed"
    else:
        assert len(calls) == 1
        assert record["status"] == control["state"] == "failed"
        assert record["error_code"] == "model_provider_request_failed"
        assert record["provider_status"] == status
        assert record["provider_error_type"] == error_type.__name__
        assert record["effect_certainty"] == "none"
    assert "PRIVATE" not in str(record)
    assert "PRIVATE" not in str(control.get("gate"))


@pytest.mark.parametrize("structured", [False, True])
def test_later_native_rejection_does_not_erase_prior_tool_effects(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    effects = []

    def provider(**kwargs):
        raise NotFoundError(
            "PRIVATE", response=httpx.Response(404, request=httpx.Request("POST", "https://offline.invalid")),
            body={"error": {"message": "PRIVATE"}},
        )

    def dispatch(*args, **kwargs):
        effects.append("tool-effect")
        client = WorkflowModelClient(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider))), MODEL, "aoai",
        )
        client.chat.completions.create(model="model", messages=[
            {"role": "user", "content": "Use the required tool."},
            {"role": "assistant", "tool_calls": [{"id": "call", "type": "function", "function": {"name": "effect", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call", "content": "Committed external effect."},
        ])

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()
    assert effects == ["tool-effect"]
    assert record["status"] == control["state"] == "waiting_recovery"
    assert control["gate"]["effect_certainty"] == "possible"
    assert control["gate"]["provider_status"] == 404
    assert control["gate"]["error_code"] == "model_provider_request_failed"
    assert "PRIVATE" not in str(control["gate"])


@pytest.mark.parametrize("structured", [False, True])
def test_native_rejection_cannot_erase_an_earlier_journaled_effect_without_tool_history(
    integration, monkeypatch, structured,
):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    effects, requests = [], []

    def provider(**kwargs):
        requests.append("request")
        raise NotFoundError(
            "PRIVATE", response=httpx.Response(404, request=httpx.Request("POST", "https://offline.invalid")),
            body={"error": {"message": "PRIVATE"}},
        )

    def dispatch(*args, **kwargs):
        workflow_unit("external-effect", lambda: effects.append("committed"), inputs={}, replay_safe=False)
        client = WorkflowModelClient(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider))), MODEL, "aoai",
        )
        client.chat.completions.create(model="model", messages=[{"role": "user", "content": "Finish the operation."}])

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()
    assert record["status"] == control["state"] == "waiting_recovery"
    assert control["gate"]["effect_certainty"] == "possible"
    assert control["gate"]["provider_status"] == 404
    runtime.continue_durable_workflow_run(workflow, run_id)
    assert effects == ["committed"] and requests == ["request"]


@pytest.mark.parametrize("structured", [False, True])
def test_real_transport_failure_keeps_unknown_status_and_effect_certainty(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=2)
    calls = []

    def provider(**kwargs):
        calls.append(True)
        raise httpx.ReadTimeout("PRIVATE", request=httpx.Request("POST", "https://offline.invalid"))

    def dispatch(*args, **kwargs):
        client = WorkflowModelClient(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider))), MODEL, "aoai",
        )
        client.chat.completions.create(model="model", messages=[{"role": "user", "content": "Answer."}])

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()
    assert calls == [True]
    assert record["status"] == control["state"] == "waiting_recovery"
    assert control["gate"]["request_outcome"] == "unconfirmed"
    assert control["gate"]["provider_error_type"] == "ReadTimeout"
    assert control["gate"]["effect_certainty"] == "possible"
    assert "provider_status" not in control["gate"]
    assert "PRIVATE" not in str(control["gate"])


def test_programming_defects_are_not_normalized_as_provider_failures():
    def provider(**kwargs):
        raise TypeError("Programming defect")

    client = WorkflowModelClient(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider))), MODEL, "aoai",
    )
    with workflow_context_budget_scope({}), pytest.raises(TypeError) as failure:
        client.chat.completions.create(model="model", messages=[{"role": "user", "content": "Answer."}])
    assert workflow_policy_failure(failure.value) is None


@pytest.mark.parametrize("structured", [False, True])
def test_provider_failure_without_a_definitive_status_stays_recoverable(
    integration, monkeypatch, structured,
):
    workflow, runner, services, make_store = prepare(
        integration, monkeypatch, structured=structured,
    )

    def uncertain(*args, **kwargs):
        raise SanitizedModelEndpointError(
            "Custom model stream failed. (reference def67890)",
            correlation_reference="def67890",
            api_type="anthropic",
            protocol="messages",
        )

    runner["_execute_workflow_dispatch"] = uncertain
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()

    assert record["status"] == control["state"] == "waiting_recovery"
    assert control["gate"]["choices"] == ["retry", "cancel"]
    if structured:
        execution_rows = [
            row["payload"] for row in make_store(workflow, run_id).container.items.values()
            if row.get("record_kind") == "execution" and row.get("run_id") == run_id
        ]
        assert execution_rows[-1]["correlation_reference"] == "def67890"
        assert execution_rows[-1]["effect_certainty"] == "possible"
    else:
        assert control["units"]["task:check"]["correlation_reference"] == "def67890"
        assert control["units"]["task:check"]["effect_certainty"] == "possible"


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("status_code", [429, 503])
def test_transient_provider_rejection_retries_then_completes(
    integration, monkeypatch, structured, status_code,
):
    workflow, runner, services, _make_store = prepare(
        integration, monkeypatch, structured=structured, retries=2,
    )
    attempts = 0

    def transient(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise SanitizedModelEndpointError(
                f"Custom model request failed. (reference retry{attempts})",
                correlation_reference=f"retry{attempts}",
                status_code=status_code,
            )
        return {"reply": "Recovered provider response."}

    runner["_execute_workflow_dispatch"] = transient
    _run_id, record = run_once(workflow, services)

    assert attempts == 3
    assert record["status"] == "completed"
    assert not record.get("error_code")


@pytest.mark.parametrize("status_code", [401, 403, 404, 429, 502])
def test_genai_mil_failure_classifies_terminal_only_for_definitive_rejections(status_code):
    failure = workflow_policy_failure(
        GenAIMilRequestError(status_code, reference="genai-ref"),
    )

    assert failure["correlation_reference"] == "genai-ref"
    assert failure["terminal_failure"] is (status_code in {401, 403, 404})


@pytest.mark.parametrize("structured", [False, True])
def test_continue_policy_runs_independent_task_without_retry(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, strategy="continue", retries=3)
    workflow["tasks"].append({**copy.deepcopy(workflow["tasks"][0]), "id": "next", "name": "Independent task"})
    if structured:
        workflow["flow"]["nodes"].append({"id": "next-node", "kind": "task", "task_id": "next"})
        workflow["flow"]["outputs"] = [{"name": "answer", "source": {"kind": "node_output", "node_id": "next-node"}}]
    services["definitions"].upsert_item(workflow)
    attempts = []
    reject = budget_dispatch([])

    def dispatch(wf, *args, **kwargs):
        attempts.append(wf["active_task"]["id"])
        if attempts[-1] == "check":
            return reject(wf)
        return {"reply": "Independent work completed."}

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    assert attempts == ["check", "next"]
    assert record["status"] in {"failed", "completed_partial"}
    control = make_store(workflow, run_id).read()
    assert control["state"] == record["status"]


@pytest.mark.parametrize("structured", [False, True])
def test_crash_after_failure_checkpoint_does_not_replay_agent(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured)
    calls = []
    runner["_execute_workflow_dispatch"] = budget_dispatch(calls)
    save_item = runner["_save_workflow_run_item_record"]

    def interrupted(wf, item):
        saved = save_item(wf, item)
        if item["status"] == "failed":
            raise SystemExit("worker disappeared before run finalization")
        return saved

    runner["_save_workflow_run_item_record"] = interrupted
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    run_id = queued["run"]["id"]
    with pytest.raises(SystemExit):
        runtime.continue_durable_workflow_run(workflow, run_id)
    runner["_save_workflow_run_item_record"] = save_item
    runner["_execute_workflow_dispatch"] = lambda *a, **k: calls.append("replayed")
    runtime.continue_durable_workflow_run(workflow, run_id)
    assert calls == []
    control = make_store(workflow, run_id).read()
    assert control["state"] in {"failed", "waiting_recovery"}


@pytest.mark.parametrize("structured", [False, True])
def test_real_semantic_kernel_tool_round_failure_preserves_effect_uncertainty_without_replay(integration, monkeypatch, structured):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, retries=3)
    original = ToolCallingCompletion(ai_model_id="fixture-model", service_id="model", api_key="test-only")
    effects = []

    @kernel_function(name="load", description="Read the inventory.")
    def load() -> str:
        effects.append("read")
        return "inventory " * 10000

    def dispatch(*args, **kwargs):
        kernel = Kernel()
        kernel.add_function(plugin_name="evidence", function=load)
        history = ChatHistory()
        history.add_user_message("Review inventory.")
        settings = PromptExecutionSettings()
        settings.function_choice_behavior = FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=3)
        service = wrap_workflow_chat_service(original, {**MODEL, "contextWindow": 4096}, provider="aoai")
        kernel.add_service(service)
        asyncio.run(service.get_chat_message_contents(history, settings, kernel=kernel))
        raise AssertionError("The second model request should be blocked")

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    assert record["status"] == "waiting_recovery", record.get("error")
    assert effects == ["read"] and original.request_count == 1
    control = make_store(workflow, run_id).read()
    assert control["state"] == "waiting_recovery"
    assert control["gate"]["effect_certainty"] == "possible"
    assert control["gate"]["error_code"] == "workflow_context_budget_exceeded"


@pytest.mark.parametrize("structured", [False, True])
def test_failed_connector_citation_marks_task_and_run_failed_and_recovery_run_succeeds(
    integration, monkeypatch, structured,
):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured)
    workflow["tasks"][0]["output_contract"] = {
        "kind": "json",
        "require_complete_coverage": False,
        "allow_partial": False,
        "schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["Evaluation"]}},
            "required": ["status"],
        },
    }
    services["definitions"].upsert_item(workflow)
    task_items = []
    save_item = runner["_save_workflow_run_item_record"]

    def record_item(wf, item):
        task_items.append(copy.deepcopy(item))
        return save_item(wf, item)

    runner["_save_workflow_run_item_record"] = record_item
    runner["_execute_workflow_dispatch"] = lambda *a, **k: {
        "reply": '{"status":"Evaluation"}',
        "agent_citations": [
            {
                "tool_name": "OpenApiPlugin.getSyntheticAcquisition",
                "plugin_name": "OpenApiPlugin",
                "function_name": "getSyntheticAcquisition",
                "function_arguments": {"kwargs": {"acquisition_id": "DEMO-ACQ-ERROR503"}},
                "success": False,
                "error_message": "HTTP 503",
            }
        ],
    }
    failed_id, failed_record = run_once(workflow, services)
    failed_control = make_store(workflow, failed_id).read()
    assert failed_record["status"] == failed_control["state"] == "failed"
    assert failed_record["success"] is False
    assert task_items[-1]["status"] == "failed"
    assert "tool_invocation_failed" in task_items[-1]["workflow_validation"]["reason_codes"]
    current_workflow = services["load_workflow"]()
    assert current_workflow["active_run_id"] == ""
    assert current_workflow["last_run_status"] == "failed"

    current_workflow["tasks"][0]["instructions"] = "Check DEMO-ACQ-001 instead."
    services["definitions"].upsert_item(current_workflow)
    runner["_execute_workflow_dispatch"] = lambda *a, **k: {
        "reply": (
            '{"id":"DEMO-ACQ-001","status":"Evaluation",'
            '"proposal_due":"2027-02-15","award_target":"2027-04-01","response_days":15}'
        ),
        "agent_citations": [
            {
                "tool_name": "OpenApiPlugin.getSyntheticAcquisition",
                "plugin_name": "OpenApiPlugin",
                "function_name": "getSyntheticAcquisition",
                "function_arguments": {"kwargs": {"acquisition_id": "DEMO-ACQ-001"}},
                "success": True,
            }
        ],
    }
    recovered_id, recovered_record = run_once(current_workflow, services)
    assert recovered_id != failed_id
    assert recovered_record["status"] == "completed", recovered_record.get("error")
    assert recovered_record["success"] is True
    assert task_items[-1]["status"] == "succeeded"
    preserved = services["runs"].read_item(item=failed_id, partition_key=services["partition"])
    assert preserved["status"] == "failed"


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("first", ["functions_workflow_context", "functions_workflow_execution", "functions_workflow_policy_errors"])
def test_policy_contract_cold_imports_without_cloud_bootstrap(optimized, first):
    probe = f'''
import importlib, socket, sys

def blocked(*args, **kwargs):
    raise AssertionError("Cold imports must not access the network")
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
importlib.import_module({first!r})
from functions_workflow_policy_errors import WorkflowContextBudgetError, WorkflowPolicyError
from functions_workflow_context import WorkflowContextBudgetError as public_error
from functions_workflow_execution import DurableWorkflowExecution
from functions_workflow_structured_execution import StructuredWorkflowExecution
if public_error is not WorkflowContextBudgetError or not issubclass(public_error, WorkflowPolicyError):
    raise AssertionError("Error identity changed across import order")
if "config" in sys.modules or "functions_settings" in sys.modules:
    raise AssertionError("Policy imports initialized an application owner")
'''
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "application" / "single_app")}
    result = subprocess.run([sys.executable, *(["-O"] if optimized else []), "-c", probe],
                            env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
