# functions_orchestration_model_capture.py
"""Private observations of already constructed Semantic Kernel model bindings.

Version: 0.261.127
"""

from copy import deepcopy
import json

from functions_orchestration_invocation_capture import OrchestrationInvocationCaptureError


_MODEL_PARAMETERS = frozenset({
    "temperature", "top_p", "max_tokens", "max_completion_tokens", "max_prompt_tokens",
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
    endpoint_id=None, model_id=None,
):
    # These SDK types belong to an executing model boundary, not app bootstrap.
    from openai import AsyncAzureOpenAI
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
    from functions_model_endpoint_providers import MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI

    client = getattr(service, "client", None)
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
