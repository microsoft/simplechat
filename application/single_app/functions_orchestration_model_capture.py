# functions_orchestration_model_capture.py
"""Private observations of already constructed Semantic Kernel model bindings.

Version: 0.261.127
"""

from copy import deepcopy
import json

from functions_orchestration_invocation_capture import OrchestrationInvocationCaptureError


_MODEL_PARAMETERS = frozenset({
    "temperature", "top_p", "max_tokens", "max_completion_tokens", "max_output_tokens", "max_prompt_tokens",
    "response_length", "reasoning_effort", "response_format", "parallel_tool_calls",
    "presence_penalty", "frequency_penalty", "seed", "tool_choice",
})


def local_agent_configuration(config, *, instructions, maximum_auto_invoke_attempts):
    """Project the actual binding inputs without the resolver's runtime token hook."""
    result = deepcopy({key: value for key, value in config.items() if key != "token_provider"})
    result["instructions"] = instructions
    result["max_auto_invoke_attempts"] = maximum_auto_invoke_attempts
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError):
        raise OrchestrationInvocationCaptureError() from None
    return result


def local_agent_model_parameters(arguments, service_id):
    """Read the exact argument settings supplied to the constructed local agent."""
    execution_settings = arguments.execution_settings
    if set(execution_settings) != {service_id}:
        raise OrchestrationInvocationCaptureError()
    parameters = execution_settings[service_id].prepare_settings_dict()
    if parameters.pop("stream", False) is not False:
        raise OrchestrationInvocationCaptureError()
    extra_body = parameters.pop("extra_body", {})
    if type(extra_body) is not dict:
        raise OrchestrationInvocationCaptureError()
    parameters.update(extra_body)
    if not set(parameters) <= _MODEL_PARAMETERS:
        raise OrchestrationInvocationCaptureError()
    try:
        json.dumps(parameters, allow_nan=False)
    except (TypeError, ValueError):
        raise OrchestrationInvocationCaptureError() from None
    return deepcopy(parameters)


def azure_chat_construction_metadata(
    service, *, protocol, provider, configured_endpoint, configured_api_version,
    endpoint_id=None, model_id=None, use_responses_api=None, url_mode="",
):
    # These SDK types belong to an executing model boundary, not app bootstrap.
    from openai import AsyncAzureOpenAI, AsyncOpenAI
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion
    from functions_model_endpoint_providers import MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI, MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE
    from functions_model_endpoint_validation import model_endpoint_inference_api
    from functions_model_endpoint_urls import resolve_custom_openai_base_url, resolve_model_inference_endpoint
    from model_endpoint_clients import normalize_openai_style_base_url

    client = getattr(service, "client", None)
    if protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        if (
            not isinstance(service, OpenAIChatCompletion) or not isinstance(client, AsyncOpenAI)
            or isinstance(client, AsyncAzureOpenAI) or not isinstance(configured_endpoint, str)
            or not configured_endpoint or not service.ai_model_id
        ):
            return None
        selected_api = model_endpoint_inference_api(configured_endpoint, use_responses_api)
        effective_endpoint = resolve_model_inference_endpoint(
            configured_endpoint, use_responses_api=use_responses_api, provider=provider,
            api_type="openai" if provider == "custom" else "", url_mode=url_mode,
        )
        expected = (
            resolve_custom_openai_base_url(configured_endpoint, "openai", url_mode)
            if provider == "custom" and selected_api != "responses"
            else normalize_openai_style_base_url(effective_endpoint)
        )
        mode = getattr(service, "inference_api", "chat_completions")
        if (
            str(client.base_url).rstrip("/") != expected.rstrip("/")
            or bool(client.default_query)
            or mode != selected_api
        ):
            return None
        return {
            "provider": provider, "protocol": "responses" if mode == "responses" else protocol,
            "endpoint": str(client.base_url), "api_version": "", "deployment": service.ai_model_id,
            "endpoint_id": endpoint_id, "model_id": model_id, "parameters": {},
        }
    actual_endpoint = getattr(client, "_azure_endpoint", None)
    actual_version = getattr(client, "_api_version", None)
    if (
        not isinstance(service, AzureChatCompletion) or not isinstance(client, AsyncAzureOpenAI)
        or protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
        or type(configured_endpoint) is not str or not configured_endpoint
        or type(configured_api_version) is not str or not configured_api_version
        or actual_endpoint is None or actual_version != configured_api_version
        or str(actual_endpoint).rstrip("/") != configured_endpoint.rstrip("/")
        or not service.ai_model_id
    ):
        return None
    return {
        "provider": provider, "protocol": protocol, "endpoint": str(actual_endpoint),
        "api_version": actual_version, "deployment": service.ai_model_id,
        "endpoint_id": endpoint_id, "model_id": model_id, "parameters": {},
    }
