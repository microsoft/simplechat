# functions_workflow_context.py
"""Request-scoped workflow budgets at direct and Semantic Kernel model boundaries."""

import json
import math
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import requests
import tiktoken
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase

from functions_model_capabilities import (
    ModelTokenBudget,
    normalize_token_limit,
    resolve_model_token_budget,
)
from model_endpoint_clients import ModelEndpointBehavior
from functions_workflow_execution import assert_workflow_execution_owned


# This is a disclosed compatibility policy, not an invented model capability.
UNKNOWN_MODEL_INPUT_TOKENS = 8192
_active_workflow = ContextVar("workflow_context_budget", default=None)


class WorkflowContextBudgetError(ValueError):
    """Required input remains durable but cannot fit the selected request."""

    def __init__(self, audit):
        self.audit = audit
        budget_name = (
            "the compatibility input budget (model limits are unverified)"
            if audit.get("limit_source") == "compatibility_policy"
            else "the selected model's input budget"
        )
        super().__init__(
            f"The complete workflow input exceeds {budget_name} "
            f"({audit['input_tokens']} estimated tokens; {audit['input_budget_tokens']} available). "
            "The upstream result is retained without truncation. Configure verified model limits, "
            "select a larger context window, or process the input in explicit batches."
        )


def _count_request_tokens(messages, tools, tokenizer, *, bounded_model=False):
    payload = json.dumps(
        {"messages": messages, "tools": tools or []},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    if not tokenizer and bounded_model:
        return len(payload.encode("utf-8")), "utf8_upper_bound"
    encoding_name = tokenizer or "cl100k_base"
    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except (OSError, requests.RequestException):
        # No input is sent to the tokenizer host. If vocabulary download is
        # unavailable, byte counting is a conservative, explicitly labeled bound.
        return len(payload.encode("utf-8")), "utf8_upper_bound"
    count = len(encoding.encode(payload, disallowed_special=()))
    return count, encoding_name if tokenizer else "cl100k_base_estimate"


def calculate_workflow_context_budget(messages, model, *, provider=None, tools=None, output_tokens=None):
    budget = resolve_model_token_budget(model, provider=provider)
    context_limit = budget.context_window
    input_limit = budget.input_limit
    output_limit = budget.output_limit
    requested_output = normalize_token_limit(
        budget.request_output_limit if output_tokens is None else output_tokens,
        "Workflow response length",
    )
    if requested_output and output_limit and requested_output > output_limit:
        raise ValueError("The requested workflow response length exceeds the model's output limit.")
    try:
        tokenizer = tiktoken.encoding_name_for_model(budget.model_id)
    except KeyError:
        tokenizer = None
    windows = [value for value in (context_limit, budget.effective_context_window) if value is not None]
    bounded_model = bool(windows or input_limit)
    token_count, estimator = _count_request_tokens(
        messages, tools, tokenizer, bounded_model=bounded_model,
    )
    token_count += 16 * len(messages) + (256 if tools else 0)
    output_reserve = requested_output or output_limit
    input_bounds = [*windows, *([input_limit] if input_limit is not None else [])]
    input_ceiling = min(input_bounds) if input_bounds else UNKNOWN_MODEL_INPUT_TOKENS
    safety_tokens = max(256, math.ceil(input_ceiling * 0.02))
    if windows and output_limit and not requested_output:
        # With model-default response length, use the remaining context rather
        # than reserving an impossible full window for both input and output.
        output_reserve = min(
            output_limit,
            max(min(output_limit, 256), min(windows) - safety_tokens - token_count),
        )
    if bounded_model or budget.applicability != "text":
        # The shared contract also rejects visible-only/unknown generation
        # accounting; a numeric response cap alone does not bound reasoning.
        available = budget.with_request_limit(output_reserve).remaining_input()
        sources = {origin for _field, origin in budget.provenance}
        configured = bool(sources & {"model", "endpoint"})
        source = "catalog+configured" if configured and "catalog" in sources else (
            "configured" if configured else "catalog"
        )
    else:
        available = UNKNOWN_MODEL_INPUT_TOKENS
        source = "compatibility_policy"

    input_budget = max(0, available - safety_tokens)
    audit = {
        "model_id": budget.model_id or None,
        "model_provider": budget.provider,
        "model_protocol": budget.protocol,
        "model_version": budget.model_version,
        "limit_status": "known" if bounded_model and output_limit else (
            "partial" if bounded_model or output_limit else "unknown"
        ),
        "limit_source": source,
        "context_window_tokens": context_limit,
        "effective_context_window_tokens": budget.effective_context_window,
        "max_input_tokens": input_limit,
        "max_output_tokens": output_limit,
        "output_token_accounting": budget.output_accounting,
        "output_reserve_tokens": output_reserve,
        "output_reservation": "requested" if requested_output else "automatic",
        "safety_tokens": safety_tokens,
        "input_tokens": token_count,
        "input_budget_tokens": input_budget,
        "token_estimator": estimator,
        "decision": "full_input" if token_count <= input_budget else "blocked",
        "truncated": False,
    }
    return audit


@contextmanager
def workflow_context_budget_scope(workflow):
    previous_settings = workflow.get("_context_output_settings")
    workflow["_context_output_settings"] = {}
    token = _active_workflow.set(workflow)
    try:
        yield
    finally:
        if previous_settings is None:
            workflow.pop("_context_output_settings", None)
        else:
            workflow["_context_output_settings"] = previous_settings
        _active_workflow.reset(token)


def _check_request(messages, model, *, provider=None, tools=None, output_tokens=None):
    assert_workflow_execution_owned()
    workflow = _active_workflow.get()
    if workflow is None:
        return
    audit = calculate_workflow_context_budget(
        messages, model, provider=provider, tools=tools, output_tokens=output_tokens,
    )
    previous = workflow.get("context_budget") or {}
    audit["request_count"] = int(previous.get("request_count") or 0) + 1
    audit["peak_input_tokens"] = max(int(previous.get("peak_input_tokens") or 0), audit["input_tokens"])
    blocked = audit["decision"] == "blocked"
    audit["blocked_request_count"] = int(previous.get("blocked_request_count") or 0) + int(blocked)
    blocked_request = dict(audit) if blocked else previous.get("blocked_request")
    if blocked_request:
        audit["blocked_request"] = blocked_request
    workflow["context_budget"] = audit
    if blocked:
        raise WorkflowContextBudgetError(audit)
    return audit


def _configured_response_tokens(model):
    if isinstance(model, ModelTokenBudget):
        return model.request_output_limit
    value = model.get("responseLength") if isinstance(model, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _response_parameter(audit, model, provider):
    name = audit.get("model_id")
    if not name:
        name = model.get("modelName") or model.get("deploymentName") if isinstance(model, Mapping) else model
    return ModelEndpointBehavior(provider, name).response_length_parameter


def raise_if_workflow_context_blocked(workflow):
    audit = (workflow.get("context_budget") or {}).get("blocked_request")
    if audit:
        raise WorkflowContextBudgetError(audit)


async def invoke_workflow_agent(agent, messages):
    """Local services guard every round; hosted agents expose only submitted input."""
    if _active_workflow.get() is not None and getattr(agent, "agent_type", "local") != "local":
        serialized = [message.to_dict() for message in messages]
        _check_request(serialized, getattr(agent, "model_metadata", None) or "", provider="managed_agent")
        _active_workflow.get()["context_budget"]["budget_scope"] = "submitted_messages"
    return await agent.invoke(messages)


class _BudgetedCompletions:
    def __init__(self, delegate, model, provider):
        self._delegate = delegate
        self._model = model
        self._provider = provider

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def create(self, **kwargs):
        requested_output = kwargs.get("max_completion_tokens")
        if requested_output is None:
            requested_output = kwargs.get("max_tokens")
        audit = _check_request(
            kwargs.get("messages") or [],
            self._model,
            provider=self._provider,
            tools=kwargs.get("tools"),
            output_tokens=_configured_response_tokens(self._model) if requested_output is None else requested_output,
        )
        if audit and audit["output_reserve_tokens"] and not requested_output:
            kwargs[_response_parameter(audit, self._model, self._provider)] = audit["output_reserve_tokens"]
        return self._delegate.create(**kwargs)


class _BudgetedChat:
    def __init__(self, delegate, model, provider):
        self._delegate = delegate
        self.completions = _BudgetedCompletions(delegate.completions, model, provider)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


class WorkflowModelClient:
    """Preserve the client interface and its authoritative, non-secret model record."""

    def __init__(self, delegate, model, provider):
        self._delegate = delegate
        self.model_metadata = model
        self.chat = _BudgetedChat(delegate.chat, model, provider)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def wrap_workflow_model_client(client, model, provider, *, endpoint_metadata=None, api_type=None):
    if _active_workflow.get() is None:
        return client
    budget = resolve_model_token_budget(
        model,
        endpoint_metadata,
        provider="azure" if api_type == "azure_openai" else provider,
        protocol="messages" if api_type == "anthropic" or provider == "claude" else "chat_completions",
        request_output_limit=_configured_response_tokens(model),
    )
    return WorkflowModelClient(client, budget, provider)


class WorkflowBudgetChatCompletion(ChatCompletionClientBase):
    """Guard every provider request, including accumulated tool-result rounds."""

    delegate: ChatCompletionClientBase
    model_metadata: Any
    provider: str = ""

    def __getattr__(self, name):
        try:
            return super().__getattr__(name)
        except AttributeError:
            delegate = self.__dict__.get("delegate")
            if delegate is None:
                raise
            return getattr(delegate, name)

    def get_prompt_execution_settings_class(self):
        return self.delegate.get_prompt_execution_settings_class()

    def _verify_function_choice_settings(self, settings):
        return self.delegate._verify_function_choice_settings(settings)

    def _update_function_choice_settings_callback(self):
        return self.delegate._update_function_choice_settings_callback()

    def _reset_function_choice_settings(self, settings):
        return self.delegate._reset_function_choice_settings(settings)

    def _check(self, chat_history, settings):
        messages = self.delegate._prepare_chat_history_for_request(chat_history)
        requested_output = getattr(settings, "max_completion_tokens", None)
        if requested_output is None:
            requested_output = getattr(settings, "max_tokens", None)
        if requested_output is None:
            requested_output = _configured_response_tokens(self.model_metadata)
        workflow = _active_workflow.get()
        if workflow is not None:
            # A previous automatic allowance must not become a user-specified
            # reservation on the next tool round. Keep this request-only.
            cache = workflow["_context_output_settings"]
            key = id(settings)
            if key not in cache:
                cache[key] = (settings, requested_output)
            requested_output = cache[key][1]
        audit = _check_request(
            messages,
            self.model_metadata,
            provider=self.provider,
            tools=getattr(settings, "tools", None),
            output_tokens=requested_output,
        )
        if audit and audit["output_reserve_tokens"]:
            parameter = _response_parameter(audit, self.model_metadata, self.provider)
            if hasattr(settings, parameter):
                setattr(settings, parameter, audit["output_reserve_tokens"])

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        self._check(chat_history, settings)
        return await self.delegate._inner_get_chat_message_contents(chat_history, settings)

    async def _inner_get_streaming_chat_message_contents(self, chat_history, settings, function_invoke_attempt=0):
        self._check(chat_history, settings)
        async for messages in self.delegate._inner_get_streaming_chat_message_contents(
            chat_history, settings, function_invoke_attempt,
        ):
            yield messages


class _WorkflowFunctionCallingBudget(WorkflowBudgetChatCompletion):
    SUPPORTS_FUNCTION_CALLING = True


def wrap_workflow_chat_service(service, model=None, *, provider=""):
    if _active_workflow.get() is None or service is None or isinstance(service, WorkflowBudgetChatCompletion):
        return service
    wrapper = _WorkflowFunctionCallingBudget if service.SUPPORTS_FUNCTION_CALLING else WorkflowBudgetChatCompletion
    return wrapper(
        ai_model_id=service.ai_model_id,
        service_id=service.service_id,
        instruction_role=service.instruction_role,
        delegate=service,
        model_metadata=model or {"modelName": service.ai_model_id},
        provider=provider,
    )
