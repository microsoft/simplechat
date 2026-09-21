# functions_model_budget_runtime.py
"""Translate a safe model budget into the actual SDK generation settings."""

from copy import deepcopy

from semantic_kernel.functions import KernelArguments

from functions_model_capabilities import (
    ModelTokenBudgetError,
    is_reasoning_model,
    normalize_token_limit,
)


OUTPUT_SETTING_FIELDS = ("max_completion_tokens", "max_output_tokens", "max_tokens")


def _setting(settings, field):
    extra_body = getattr(settings, "extra_body", None) or {}
    if field in extra_body:
        return extra_body[field]
    value = getattr(settings, field, None)
    if value is not None:
        return value
    return (getattr(settings, "extension_data", None) or {}).get(field)


def request_output_limit(settings, budget):
    fields = ("max_tokens", "max_completion_tokens") if budget.protocol == "messages" else OUTPUT_SETTING_FIELDS
    for field in fields:
        value = _setting(settings, field)
        if value is not None:
            return normalize_token_limit(value, "Response Length")
    return budget.request_output_limit


def set_generation_limit(settings, budget, value):
    """Send one protocol-appropriate ceiling, including overrides in extra_body."""
    value = normalize_token_limit(value, "Response Length")
    for field in OUTPUT_SETTING_FIELDS:
        if field in type(settings).model_fields:
            setattr(settings, field, None)
        settings.extension_data.pop(field, None)
        if getattr(settings, "extra_body", None):
            settings.extra_body.pop(field, None)
    if value is None:
        return
    field = "max_tokens"
    if budget.protocol == "responses":
        field = "max_output_tokens"
    elif budget.protocol == "chat_completions" and (
        budget.provider in ("openai", "azure") and is_reasoning_model(budget.model_id)
        or budget.provider == "xai"
    ):
        field = "max_completion_tokens"
    if field in type(settings).model_fields:
        setattr(settings, field, value)
    else:
        settings.extension_data[field] = value


def _set_reasoning_effort(settings, budget, effort):
    if effort is None or budget.protocol != "chat_completions":
        return
    if effort not in ("none", "minimal", "low", "medium", "high", "xhigh"):
        raise ModelTokenBudgetError("model_context_invalid", "Select a supported reasoning effort.")
    # The pinned SK enum predates 'none'; OpenAI's supported extra_body carries it unchanged.
    if "extra_body" in type(settings).model_fields:
        if "reasoning_effort" in type(settings).model_fields:
            settings.reasoning_effort = None
        settings.extension_data.pop("reasoning_effort", None)
        settings.extra_body = {**(settings.extra_body or {}), "reasoning_effort": effort}
    else:
        settings.extension_data["reasoning_effort"] = effort


def prepare_model_execution_settings(
    settings, budget, *, output_limit=None, reasoning_effort=None, tools_enabled=False,
):
    """Return isolated wire settings and their matching budget, without mutating defaults."""
    prepared = deepcopy(settings)
    requested = request_output_limit(prepared, budget)
    if output_limit is not None:
        requested = min(
            value for value in (normalize_token_limit(output_limit), requested, budget.output_limit)
            if value is not None
        )
    if requested is not None:
        if budget.output_limit is not None and requested > budget.output_limit:
            raise ModelTokenBudgetError(
                "model_context_invalid", "Response Length exceeds this model's documented output limit."
            )
        set_generation_limit(prepared, budget, requested)
    effort = _setting(prepared, "reasoning_effort")
    if effort is None:
        effort = reasoning_effort
    if tools_enabled and budget.tool_reasoning_efforts:
        if effort is None and budget.tool_reasoning_efforts == ("none",):
            effort = "none"
        if effort not in budget.tool_reasoning_efforts:
            raise ModelTokenBudgetError(
                "model_tool_configuration_invalid",
                "This model's Chat Completions tools require Reasoning Effort None. Choose a supported model or reasoning setting.",
            )
    _set_reasoning_effort(prepared, budget, effort)
    return prepared, budget.with_request_limit(requested)


def build_model_budget_arguments(service, budget, *, reasoning_effort=None):
    settings_class = service.get_prompt_execution_settings_class()
    existing = getattr(service, "prompt_execution_settings", None)
    settings = (
        settings_class.from_prompt_execution_settings(deepcopy(existing))
        if existing is not None else settings_class()
    )
    settings.service_id = service.service_id
    requested = request_output_limit(settings, budget)
    if requested is not None:
        set_generation_limit(settings, budget, requested)
    effort = _setting(settings, "reasoning_effort")
    _set_reasoning_effort(settings, budget, effort if effort is not None else reasoning_effort)
    return KernelArguments(settings=settings)
