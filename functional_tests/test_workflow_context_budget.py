# test_workflow_context_budget.py
"""
Functional tests for workflow provider-boundary context budgets.
Version: 0.261.122
Implemented in: 0.261.106

These tests cover complete requests, selected-model limits, tool-result rounds,
and isolation from ordinary chat. Model metadata and provider responses are
deterministic; Semantic Kernel's function-calling loop is real.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.contents import ChatHistory, ChatMessageContent, FunctionCallContent
from semantic_kernel.functions import kernel_function

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Import the app only after adding the worktree's module directory.
import functions_workflow_context as context
from functions_model_capabilities import ModelTokenBudgetError, resolve_model_token_budget


@pytest.fixture
def limits(monkeypatch):
    metadata = {
        "context_window_tokens": 32768,
        "max_input_tokens": None,
        "max_output_tokens": 4096,
        "tokenizer": "cl100k_base",
        "source": "catalog",
        "model_id": "fixture-model",
        "status": "known",
        "output_token_accounting": "total_generation",
    }

    def resolve(*args, **kwargs):
        return context.ModelTokenBudget(
            model_id=metadata["model_id"],
            provider="openai",
            context_window=metadata["context_window_tokens"],
            input_limit=metadata["max_input_tokens"],
            output_limit=metadata["max_output_tokens"],
            effective_context_window=metadata.get("effective_context_window_tokens"),
            output_accounting=metadata["output_token_accounting"],
            provenance=(("contextWindow", "catalog"),) if metadata["source"] == "catalog" else (),
        )

    def encoding_name(_model):
        if not metadata["tokenizer"]:
            raise KeyError(_model)
        return metadata["tokenizer"]

    monkeypatch.setattr(context, "resolve_model_token_budget", resolve)
    monkeypatch.setattr(context.tiktoken, "encoding_name_for_model", encoding_name)
    return metadata


def test_complete_input_above_old_character_cap_is_not_clipped(limits):
    text = json.dumps([{"id": index, "description": "inventory material " * 12} for index in range(100)])
    assert len(text) > 12000
    sent = []
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: sent.append(kwargs) or "done"),
    ))
    guarded = context.WorkflowModelClient(client, "fixture-model", "aoai")
    workflow = {}
    with context.workflow_context_budget_scope(workflow):
        guarded.chat.completions.create(
            model="fixture-model", messages=[{"role": "user", "content": text}],
        )
    assert sent[0]["messages"][0]["content"] == text
    assert workflow["context_budget"]["decision"] == "full_input"
    assert workflow["context_budget"]["truncated"] is False


def test_instructions_and_tools_share_the_input_budget(limits):
    limits.update(context_window_tokens=1800, max_output_tokens=500)
    messages = [
        {"role": "system", "content": "instruction " * 600},
        {"role": "user", "content": "evidence " * 600},
    ]
    audit = context.calculate_workflow_context_budget(
        messages, "fixture-model", tools=[{"description": "tool schema " * 200}], output_tokens=500,
    )
    assert audit["decision"] == "blocked"
    assert audit["output_reserve_tokens"] == 500
    assert audit["input_tokens"] > audit["input_budget_tokens"]


def test_joint_window_model_reserves_only_available_automatic_output(limits):
    limits.update(context_window_tokens=8192, max_output_tokens=8192)
    audit = context.calculate_workflow_context_budget(
        [{"role": "user", "content": "A short inventory question."}], "fixture-model",
    )
    assert audit["decision"] == "full_input"
    assert 0 < audit["output_reserve_tokens"] < 8192
    assert audit["input_tokens"] + audit["output_reserve_tokens"] + audit["safety_tokens"] <= 8192


def test_input_and_output_limits_are_separate(limits):
    limits["max_input_tokens"] = 2048
    audit = context.calculate_workflow_context_budget(
        [{"role": "user", "content": "small"}], "fixture-model", output_tokens=1024,
    )
    assert audit["input_budget_tokens"] == 2048 - audit["safety_tokens"]
    assert audit["output_reserve_tokens"] == 1024
    with pytest.raises(ValueError, match="response length"):
        context.calculate_workflow_context_budget([], "fixture-model", output_tokens=5000)


def test_unknown_model_budget_is_explicit_not_unlimited(limits):
    limits.update(
        context_window_tokens=None, max_output_tokens=None, max_input_tokens=None,
        tokenizer=None, status="unknown", source="unknown",
    )
    audit = context.calculate_workflow_context_budget([{"role": "user", "content": "small"}], "custom")
    assert audit["context_window_tokens"] is None
    assert audit["limit_source"] == "compatibility_policy"
    assert audit["token_estimator"] == "cl100k_base_estimate"
    assert audit["input_budget_tokens"] < context.UNKNOWN_MODEL_INPUT_TOKENS


def test_known_model_without_tokenizer_uses_a_conservative_bound(limits):
    limits["tokenizer"] = None
    text = "\u4e00" * 500
    audit = context.calculate_workflow_context_budget(
        [{"role": "user", "content": text}], "known-non-openai-model",
    )
    assert audit["token_estimator"] == "utf8_upper_bound"
    assert audit["input_tokens"] >= len(text.encode("utf-8"))


@pytest.mark.parametrize("accounting", ["visible_only", "unknown"])
def test_numeric_output_limit_does_not_claim_to_bound_hidden_reasoning(limits, accounting):
    limits["output_token_accounting"] = accounting
    sent = []
    client = context.WorkflowModelClient(SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: sent.append(kwargs)),
    )), "fixture-model", "aoai")
    with context.workflow_context_budget_scope({}), pytest.raises(ModelTokenBudgetError) as error:
        client.chat.completions.create(messages=[{"role": "user", "content": "small"}], max_tokens=128)
    assert error.value.code == "model_generation_unbounded"
    assert sent == []


@pytest.mark.parametrize("input_tokens, decision", [(3488, "full_input"), (3489, "blocked")])
def test_effective_protocol_window_enforces_exact_request_boundary(limits, monkeypatch, input_tokens, decision):
    limits.update(
        context_window_tokens=10000, effective_context_window_tokens=4000,
        max_input_tokens=6000, max_output_tokens=2000,
    )
    monkeypatch.setattr(
        context, "_count_request_tokens", lambda *args, **kwargs: (input_tokens - 16, "fixture"),
    )
    audit = context.calculate_workflow_context_budget(
        [{"role": "user", "content": "complete input"}], "fixture-model", output_tokens=256,
    )
    assert audit["context_window_tokens"] == 10000
    assert audit["effective_context_window_tokens"] == 4000
    assert audit["input_budget_tokens"] == 3488
    assert audit["input_tokens"] == input_tokens
    assert audit["decision"] == decision
    assert audit["truncated"] is False


def test_known_window_without_generation_allowance_does_not_fall_back_to_unknown_policy(limits):
    limits["max_output_tokens"] = None
    with pytest.raises(ModelTokenBudgetError) as error:
        context.calculate_workflow_context_budget([], "fixture-model")
    assert error.value.code == "model_context_unavailable"


@pytest.mark.parametrize("output_tokens", [False, 0, -1, 1.5])
def test_invalid_explicit_response_limits_are_not_sent_or_silently_replaced(limits, output_tokens):
    sent = []
    client = context.WorkflowModelClient(SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: sent.append(kwargs)),
    )), "fixture-model", "aoai")
    with context.workflow_context_budget_scope({}), pytest.raises(ModelTokenBudgetError):
        client.chat.completions.create(messages=[], max_tokens=output_tokens)
    assert sent == []


def test_real_audited_profile_is_preserved_through_the_workflow_boundary(monkeypatch):
    budget = resolve_model_token_budget(
        "gpt-5.5", provider="azure", protocol="responses", request_output_limit=1000,
    )
    monkeypatch.setattr(context, "_count_request_tokens", lambda *args, **kwargs: (100, "fixture"))
    audit = context.calculate_workflow_context_budget(
        [{"role": "user", "content": "complete input"}], budget,
    )
    assert audit["model_provider"] == "azure"
    assert audit["model_protocol"] == "responses"
    assert audit["context_window_tokens"] == 1050000
    assert audit["max_input_tokens"] == 922000
    assert audit["effective_context_window_tokens"] == 922000
    assert audit["max_output_tokens"] == 128000
    assert audit["output_reserve_tokens"] == 1000
    assert audit["output_reservation"] == "requested"
    assert audit["input_budget_tokens"] == budget.remaining_input() - audit["safety_tokens"]
    assert audit["decision"] == "full_input"


def test_authorized_endpoint_limits_and_protocol_follow_direct_client_into_agent_wrapper():
    sent = []
    original = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: sent.append(kwargs)),
    ))
    model = {"modelName": "private-model", "responseLength": 200}
    endpoint = {
        "provider": "custom", "tokenLimitProvider": "anthropic",
        "contextWindow": 8192, "inputTokenLimit": 7000, "outputTokenLimit": 1000,
        "outputTokenAccounting": "total_generation", "auth": {"api_key": "not-budget-metadata"},
    }
    service = RespondingCompletion(ai_model_id="private-model", api_key="test-only")
    workflow = {}
    with context.workflow_context_budget_scope(workflow):
        client = context.wrap_workflow_model_client(
            original, model, "custom", endpoint_metadata=endpoint, api_type="anthropic",
        )
        wrapped_service = context.wrap_workflow_chat_service(service, client.model_metadata, provider="custom")
        client.chat.completions.create(messages=[{"role": "user", "content": "complete input"}])
    budget = wrapped_service.model_metadata
    assert isinstance(budget, context.ModelTokenBudget)
    assert budget.provider == "anthropic"
    assert budget.protocol == "messages"
    assert budget.context_window == 8192
    assert budget.input_limit == 7000
    assert budget.output_limit == 1000
    assert budget.request_output_limit == 200
    assert "auth" not in vars(budget)
    assert sent[0]["max_tokens"] == 200
    assert workflow["context_budget"]["limit_source"] == "configured"
    assert workflow["context_budget"]["input_budget_tokens"] == 7000 - 256


class ToolCallingCompletion(OpenAIChatCompletion):
    request_count: int = 0

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        self.request_count += 1
        if self.request_count == 1:
            return [ChatMessageContent(role="assistant", items=[
                FunctionCallContent(id="read-1", name="evidence-load", arguments="{}"),
            ])]
        return [ChatMessageContent(role="assistant", content="Finished.")]


class RespondingCompletion(OpenAIChatCompletion):
    request_count: int = 0

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        self.request_count += 1
        return [ChatMessageContent(role="assistant", content="The final inventory has seven units.")]


@pytest.mark.parametrize("large_instructions", [False, True])
def test_local_agent_uses_budgeted_service_with_its_instructions(limits, large_instructions):
    limits.update(context_window_tokens=2048, max_output_tokens=512)
    original = RespondingCompletion(ai_model_id="fixture-model", service_id="agent-model", api_key="test-only")
    workflow = {}
    with context.workflow_context_budget_scope(workflow):
        service = context.wrap_workflow_chat_service(original, "fixture-model", provider="aoai")
        agent = ChatCompletionAgent(
            name="InventoryAgent",
            instructions="Trusted inventory instruction. " * (2000 if large_instructions else 1),
            service=service,
        )

        async def invoke():
            return [item async for item in agent.invoke(
                messages=[ChatMessageContent(role="user", content="Explain the final inventory.")],
            )]

        if large_instructions:
            with pytest.raises(context.WorkflowContextBudgetError):
                asyncio.run(invoke())
            assert original.request_count == 0
            assert workflow["context_budget"]["decision"] == "blocked"
        else:
            messages = asyncio.run(invoke())
            assert messages[-1].message.content == "The final inventory has seven units."
            assert original.request_count == 1
    assert "_context_output_settings" not in workflow


def test_semantic_kernel_rechecks_after_tool_results(limits):
    limits.update(context_window_tokens=4096, max_output_tokens=512)
    original = ToolCallingCompletion(ai_model_id="fixture-model", service_id="model", api_key="test-only")
    kernel = Kernel()

    @kernel_function(name="load", description="Read the full inventory.")
    def load() -> str:
        return "inventory " * 10000

    kernel.add_function(plugin_name="evidence", function=load)
    history = ChatHistory()
    history.add_system_message("Use the inventory tool.")
    history.add_user_message("Review inventory.")
    settings = PromptExecutionSettings()
    settings.function_choice_behavior = FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=3)
    workflow = {}
    with context.workflow_context_budget_scope(workflow):
        service = context.wrap_workflow_chat_service(original, "fixture-model", provider="aoai")
        kernel.add_service(service)
        with pytest.raises(context.WorkflowContextBudgetError):
            asyncio.run(service.get_chat_message_contents(history, settings, kernel=kernel))

    assert original.request_count == 1, "The over-budget second request must never reach the provider."
    assert workflow["context_budget"]["request_count"] == 2
    assert workflow["context_budget"]["decision"] == "blocked"
    assert len(history.messages) >= 4, "The real tool result must be present in the checked history."


def test_non_workflow_calls_are_unchanged(limits):
    original = ToolCallingCompletion(ai_model_id="fixture-model", api_key="test-only")
    assert context.wrap_workflow_chat_service(original) is original
    unwrapped = object()
    assert context.wrap_workflow_model_client(unwrapped, "fixture-model", "aoai") is unwrapped
    sent = []
    raw = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **kwargs: sent.append(kwargs)),
    ))
    client = context.WorkflowModelClient(raw, "fixture-model", "aoai")
    client.chat.completions.create(messages=[{"role": "user", "content": "large " * 50000}])
    assert len(sent) == 1
