# openai_style_agent_harness.py
"""
Run a local Semantic Kernel chat agent against a model endpoint using an
OpenAI-style client.

The script reads `me.json` and `agent.json` from the same directory and uses
their endpoint and agent configuration to create a `ChatCompletionAgent` backed
by `OpenAIChatCompletion` with a custom `AsyncOpenAI` client. This is intended
for isolated Grok and Phi experiments before changing the main app runtime.
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from azure.identity import ClientSecretCredential, DefaultAzureCredential
from openai import AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.utils.author_role import AuthorRole
from semantic_kernel.functions import KernelArguments, kernel_function


SCRIPT_DIR = Path(__file__).resolve().parent
MODEL_ENDPOINT_PATH = SCRIPT_DIR / "me.json"
AGENT_CONFIG_PATH = SCRIPT_DIR / "agent.json"
DEFAULT_MESSAGE = "What time is it in UTC? Use the harness tool if it helps."
DEFAULT_SERVICE_ID = "openai-style-harness"


class HarnessToolsPlugin:
    """Small local tool set for function-choice experiments."""

    @kernel_function(name="utc_now", description="Return the current UTC date and time in ISO 8601 format.")
    def utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @kernel_function(name="echo_text", description="Echo the supplied text exactly.")
    def echo_text(self, text: str) -> str:
        return text


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local SK agent against a model endpoint with an OpenAI-style client.",
    )
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="User message to send to the agent.")
    parser.add_argument(
        "--function-choice",
        default="auto",
        choices=("auto", "required", "none", "off"),
        help="Function choice mode for prompt execution settings.",
    )
    parser.add_argument(
        "--max-auto-invoke-attempts",
        type=int,
        default=10,
        help="Maximum auto invoke attempts for auto or required function choice modes.",
    )
    parser.add_argument(
        "--endpoint-id",
        default="",
        help="Optional endpoint id override when me.json contains multiple endpoints.",
    )
    parser.add_argument(
        "--model-id",
        default="",
        help="Optional model id override when the endpoint exposes multiple models.",
    )
    parser.add_argument(
        "--deployment",
        default="",
        help="Optional deployment name override when the endpoint exposes multiple models.",
    )
    parser.add_argument(
        "--no-plugin",
        action="store_true",
        help="Disable the built-in harness tools plugin.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()


def load_json_document(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path.name}. Create it in {path.parent} before running the harness."
        )

    with path.open("r", encoding="utf-8") as file_handle:
        payload = json.load(file_handle)

    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")

    return payload


def unwrap_agent_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("agent", "selected_agent", "payload"):
        nested_value = payload.get(key)
        if isinstance(nested_value, dict):
            return nested_value
    return payload


def looks_like_endpoint_config(payload: Dict[str, Any]) -> bool:
    return isinstance(payload.get("connection"), dict) and isinstance(payload.get("auth"), dict)


def first_enabled_item(items: list[Dict[str, Any]]) -> Dict[str, Any]:
    for item in items:
        if item.get("enabled", True):
            return item
    if not items:
        raise ValueError("Expected at least one item to choose from.")
    return items[0]


def resolve_endpoint_config(
    payload: Dict[str, Any],
    agent_config: Dict[str, Any],
    endpoint_id_override: str,
) -> Dict[str, Any]:
    if looks_like_endpoint_config(payload):
        return dict(payload)

    for key in ("model_endpoint", "endpoint", "selected_endpoint"):
        nested_value = payload.get(key)
        if isinstance(nested_value, dict) and looks_like_endpoint_config(nested_value):
            return dict(nested_value)

    endpoint_lists = (
        payload.get("model_endpoints"),
        payload.get("personal_model_endpoints"),
        payload.get("endpoints"),
    )
    endpoints = next((value for value in endpoint_lists if isinstance(value, list) and value), None)
    if not endpoints:
        raise ValueError(
            "me.json must be a model endpoint object or contain a non-empty model_endpoints list."
        )

    selected_endpoint_id = (
        endpoint_id_override.strip()
        or str(agent_config.get("model_endpoint_id") or "").strip()
        or str((payload.get("default_model_selection") or {}).get("endpoint_id") or "").strip()
    )

    if selected_endpoint_id:
        endpoint_config = next(
            (endpoint for endpoint in endpoints if str(endpoint.get("id") or "").strip() == selected_endpoint_id),
            None,
        )
        if endpoint_config is None:
            raise LookupError(f"Could not find endpoint_id={selected_endpoint_id!r} in me.json.")
        return dict(endpoint_config)

    return dict(first_enabled_item(endpoints))


def resolve_model_config(
    endpoint_config: Dict[str, Any],
    agent_config: Dict[str, Any],
    model_id_override: str,
    deployment_override: str,
) -> Dict[str, Any]:
    models = endpoint_config.get("models")
    selected_model_id = model_id_override.strip() or str(agent_config.get("model_id") or "").strip()
    selected_deployment = (
        deployment_override.strip()
        or str(agent_config.get("azure_openai_gpt_deployment") or "").strip()
        or str(agent_config.get("deployment") or "").strip()
    )

    if not isinstance(models, list) or not models:
        inferred_name = selected_deployment or selected_model_id
        if not inferred_name:
            raise ValueError("The selected endpoint does not define models and no model override was provided.")
        return {
            "id": selected_model_id or inferred_name,
            "deploymentName": selected_deployment or inferred_name,
            "enabled": True,
        }

    if selected_model_id:
        match = next((model for model in models if str(model.get("id") or "").strip() == selected_model_id), None)
        if match is None:
            raise LookupError(f"Could not find model_id={selected_model_id!r} in me.json.")
        return dict(match)

    if selected_deployment:
        match = next(
            (
                model for model in models
                if str(model.get("deploymentName") or model.get("deployment") or "").strip() == selected_deployment
            ),
            None,
        )
        if match is None:
            raise LookupError(f"Could not find deployment={selected_deployment!r} in me.json.")
        return dict(match)

    return dict(first_enabled_item(models))


def normalize_openai_style_base_url(raw_endpoint: str) -> str:
    endpoint = raw_endpoint.strip().rstrip("/")
    if not endpoint:
        raise ValueError("A Foundry endpoint is required to create the OpenAI-style client.")

    lowered_endpoint = endpoint.lower()
    if "/openai/v1" in lowered_endpoint:
        return endpoint + "/"
    if "/models" in lowered_endpoint:
        prefix = endpoint[: lowered_endpoint.index("/models")]
        return prefix.rstrip("/") + "/openai/v1/"
    if "/openai" in lowered_endpoint:
        prefix = endpoint[: lowered_endpoint.index("/openai")]
        return prefix.rstrip("/") + "/openai/v1/"
    return endpoint + "/openai/v1/"


def resolve_authority(auth_settings: Dict[str, Any]) -> str | None:
    management_cloud = str(auth_settings.get("management_cloud") or "public").lower()
    if management_cloud in ("government", "usgovernment", "usgov"):
        return "https://login.microsoftonline.us"
    if management_cloud == "custom":
        custom_authority = str(auth_settings.get("custom_authority") or "").strip()
        return custom_authority or None
    return None


def infer_foundry_scope_from_endpoint(base_url: str) -> str:
    host_name = (urlparse(base_url).hostname or base_url).lower()
    if "azure.us" in host_name:
        return "https://ai.azure.us/.default"
    if "azure.cn" in host_name:
        return "https://ai.azure.cn/.default"
    if "azure.de" in host_name:
        return "https://ai.azure.de/.default"
    return "https://ai.azure.com/.default"


def resolve_foundry_scope_for_auth(auth_settings: Dict[str, Any], base_url: str) -> str:
    custom_scope = str(auth_settings.get("foundry_scope") or "").strip()
    if custom_scope:
        return custom_scope

    management_cloud = str(auth_settings.get("management_cloud") or "public").lower()
    if management_cloud in ("government", "usgovernment", "usgov"):
        return "https://ai.azure.us/.default"
    if management_cloud == "china":
        return "https://ai.azure.cn/.default"
    if management_cloud == "germany":
        return "https://ai.azure.de/.default"
    return infer_foundry_scope_from_endpoint(base_url)


def resolve_openai_style_api_key(auth_settings: Dict[str, Any], base_url: str) -> str:
    auth_type = str(auth_settings.get("type") or "api_key").lower()
    if auth_type in ("api_key", "key"):
        api_key = str(auth_settings.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("The selected endpoint requires auth.api_key in me.json.")
        return api_key

    scope = resolve_foundry_scope_for_auth(auth_settings, base_url)
    if auth_type == "service_principal":
        credential = ClientSecretCredential(
            tenant_id=auth_settings.get("tenant_id"),
            client_id=auth_settings.get("client_id"),
            client_secret=auth_settings.get("client_secret"),
            authority=resolve_authority(auth_settings),
        )
    else:
        credential = DefaultAzureCredential(
            managed_identity_client_id=auth_settings.get("managed_identity_client_id") or None
        )

    return credential.get_token(scope).token


def resolve_openai_style_request_api_version(raw_api_version: str) -> str:
    normalized_api_version = str(raw_api_version or "").strip().lower()
    if normalized_api_version in ("", "v1"):
        return ""
    if normalized_api_version in ("preview", "latest"):
        return normalized_api_version

    logging.info(
        "Ignoring legacy Azure API version for OpenAI-style /openai/v1/ requests: %s",
        raw_api_version,
    )
    return ""


def build_function_choice_behavior(choice_mode: str, max_attempts: int) -> FunctionChoiceBehavior | None:
    normalized_mode = choice_mode.strip().lower()
    if normalized_mode == "off":
        return None
    if normalized_mode == "required":
        return FunctionChoiceBehavior.Required(maximum_auto_invoke_attempts=max_attempts)
    if normalized_mode == "none":
        return FunctionChoiceBehavior.NoneInvoke()
    return FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=max_attempts)


def maybe_set_prompt_setting(settings: Any, field_name: str, value: Any) -> None:
    if value in (None, "", [], {}):
        return

    model_fields = getattr(type(settings), "model_fields", {}) or {}
    if field_name in model_fields or hasattr(settings, field_name):
        setattr(settings, field_name, value)


def coerce_int(value: Any) -> int | None:
    if value in (None, "", " "):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> float | None:
    if value in (None, "", " "):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_stop_sequences(agent_config: Dict[str, Any]) -> Any:
    stop_sequences = agent_config.get("stop_sequences")
    if isinstance(stop_sequences, list) and stop_sequences:
        return stop_sequences
    stop_value = agent_config.get("stop")
    if isinstance(stop_value, list) and stop_value:
        return stop_value
    if isinstance(stop_value, str) and stop_value.strip():
        return [stop_value.strip()]
    return None


def build_prompt_execution_settings(
    service: OpenAIChatCompletion,
    service_id: str,
    agent_config: Dict[str, Any],
    function_choice_behavior: FunctionChoiceBehavior | None,
) -> Any:
    settings_class = service.get_prompt_execution_settings_class()
    settings = settings_class(service_id=service_id)
    maybe_set_prompt_setting(settings, "function_choice_behavior", function_choice_behavior)
    maybe_set_prompt_setting(settings, "service_id", service_id)

    desired_tokens = coerce_int(
        agent_config.get("max_completion_tokens")
        if agent_config.get("max_completion_tokens") not in (None, -1)
        else agent_config.get("max_tokens")
    )
    if desired_tokens and desired_tokens > 0:
        maybe_set_prompt_setting(settings, "max_completion_tokens", desired_tokens)
        maybe_set_prompt_setting(settings, "max_tokens", desired_tokens)

    maybe_set_prompt_setting(settings, "temperature", coerce_float(agent_config.get("temperature")))
    maybe_set_prompt_setting(settings, "top_p", coerce_float(agent_config.get("top_p")))
    maybe_set_prompt_setting(settings, "frequency_penalty", coerce_float(agent_config.get("frequency_penalty")))
    maybe_set_prompt_setting(settings, "presence_penalty", coerce_float(agent_config.get("presence_penalty")))
    maybe_set_prompt_setting(settings, "stop", resolve_stop_sequences(agent_config))

    reasoning_effort = str(agent_config.get("reasoning_effort") or "").strip()
    if reasoning_effort and reasoning_effort.lower() != "none":
        maybe_set_prompt_setting(settings, "reasoning_effort", reasoning_effort)

    return settings


def mask_secret(value: str, visible_chars: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible_chars:
        return "*" * len(value)
    return f"{value[:visible_chars]}***{value[-visible_chars:]}"


def format_function_choice_summary(function_choice_behavior: FunctionChoiceBehavior | None) -> str:
    if function_choice_behavior is None:
        return "off"
    behavior_type = getattr(function_choice_behavior, "type_", None)
    if behavior_type is None:
        return str(function_choice_behavior)
    return str(getattr(behavior_type, "value", behavior_type))


def resolve_harness_inputs(
    args: argparse.Namespace,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str, str, str, str, str]:
    model_endpoint_payload = load_json_document(MODEL_ENDPOINT_PATH)
    agent_payload = load_json_document(AGENT_CONFIG_PATH)
    agent_config = unwrap_agent_config(agent_payload)
    endpoint_config = resolve_endpoint_config(model_endpoint_payload, agent_config, args.endpoint_id)
    model_config = resolve_model_config(endpoint_config, agent_config, args.model_id, args.deployment)

    connection = endpoint_config.get("connection", {}) or {}
    auth_settings = endpoint_config.get("auth", {}) or {}
    provider = str(endpoint_config.get("provider") or agent_config.get("model_provider") or "new_foundry").lower()
    raw_endpoint = str(
        connection.get("base_url")
        or connection.get("openai_base_url")
        or connection.get("endpoint")
        or agent_config.get("azure_openai_gpt_endpoint")
        or ""
    ).strip()
    if not raw_endpoint:
        raise ValueError("Unable to determine an endpoint URL from me.json or agent.json.")

    base_url = normalize_openai_style_base_url(raw_endpoint)
    api_version = str(connection.get("openai_api_version") or connection.get("api_version") or "").strip()
    deployment_name = str(
        model_config.get("deploymentName")
        or model_config.get("deployment")
        or agent_config.get("azure_openai_gpt_deployment")
        or model_config.get("id")
        or ""
    ).strip()
    if not deployment_name:
        raise ValueError("Unable to determine the deployment/model name from me.json or agent.json.")

    model_id = str(model_config.get("id") or deployment_name).strip()
    return agent_config, endpoint_config, auth_settings, provider, base_url, api_version, model_id, deployment_name


def build_openai_style_service(
    auth_settings: Dict[str, Any],
    base_url: str,
    request_api_version: str,
    request_model_name: str,
) -> OpenAIChatCompletion:
    token_or_key = resolve_openai_style_api_key(auth_settings, base_url)
    client_kwargs: Dict[str, Any] = {
        "api_key": token_or_key,
        "base_url": base_url,
    }
    if request_api_version:
        client_kwargs["default_query"] = {"api-version": request_api_version}

    async_client = AsyncOpenAI(**client_kwargs)
    return OpenAIChatCompletion(
        ai_model_id=request_model_name,
        service_id=DEFAULT_SERVICE_ID,
        async_client=async_client,
    )


async def run_harness(args: argparse.Namespace) -> int:
    agent_config, endpoint_config, auth_settings, provider, base_url, api_version, model_id, deployment_name = resolve_harness_inputs(args)
    request_api_version = resolve_openai_style_request_api_version(api_version)

    request_model_name = deployment_name
    service = build_openai_style_service(auth_settings, base_url, request_api_version, request_model_name)
    function_choice_behavior = build_function_choice_behavior(
        args.function_choice,
        args.max_auto_invoke_attempts,
    )
    prompt_execution_settings = build_prompt_execution_settings(
        service,
        DEFAULT_SERVICE_ID,
        agent_config,
        function_choice_behavior,
    )

    kernel = Kernel()
    kernel.add_service(service)
    if not args.no_plugin:
        kernel.add_plugin(HarnessToolsPlugin(), plugin_name="harness_tools")

    agent_arguments = KernelArguments(settings=prompt_execution_settings)
    agent = ChatCompletionAgent(
        name=str(agent_config.get("name") or "openai-style-harness-agent"),
        description=str(agent_config.get("description") or "OpenAI-style harness agent."),
        instructions=str(
            agent_config.get("instructions")
            or "You are a test harness agent. Use tools when they help answer the user."
        ),
        kernel=kernel,
        service=service,
        arguments=agent_arguments,
        function_choice_behavior=function_choice_behavior,
    )

    logging.info("Loaded me.json from %s", MODEL_ENDPOINT_PATH)
    logging.info("Loaded agent.json from %s", AGENT_CONFIG_PATH)
    logging.info("Provider: %s", provider or "unknown")
    logging.info("Base URL: %s", base_url)
    logging.info("Catalog model id: %s", model_id or "(none)")
    logging.info("Request deployment/model: %s", request_model_name)
    logging.info("Saved API version: %s", api_version or "(none)")
    logging.info("Request API version: %s", request_api_version or "endpoint default (v1)")
    logging.info("Auth type: %s", str(auth_settings.get("type") or "api_key").lower())
    logging.info("Masked credential preview: %s", mask_secret(resolve_openai_style_api_key(auth_settings, base_url)))
    logging.info("Function choice mode: %s", format_function_choice_summary(function_choice_behavior))
    logging.info(
        "Prompt execution settings: %s",
        json.dumps(prompt_execution_settings.model_dump(exclude_none=True), default=str),
    )
    if args.no_plugin:
        logging.info("Harness plugin disabled.")
    else:
        logging.info("Harness plugin enabled with functions: utc_now, echo_text")
    if agent_config.get("actions_to_load"):
        logging.info(
            "actions_to_load from agent.json are not loaded by this standalone harness: %s",
            ", ".join(str(action) for action in agent_config.get("actions_to_load") or []),
        )

    message_history = [
        ChatMessageContent(role=AuthorRole.USER, content=args.message)
    ]

    accumulated_output = []
    last_usage = None
    last_model = None

    logging.info("Starting agent stream...")
    agent_stream = agent.invoke_stream(messages=message_history)
    async for response in agent_stream:
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            if metadata.get("usage"):
                last_usage = metadata["usage"]
            if metadata.get("model"):
                last_model = metadata["model"]

        chunk_text = None
        if hasattr(response, "content") and response.content:
            chunk_text = str(response.content)
        elif isinstance(response, str) and response:
            chunk_text = response

        if chunk_text:
            accumulated_output.append(chunk_text)
            print(chunk_text, end="", flush=True)

    print()
    logging.info("Completed agent stream.")
    logging.info("Final model reported by metadata: %s", last_model or request_model_name)
    if last_usage is not None:
        logging.info("Usage: %s", last_usage)

    if not accumulated_output:
        logging.warning("The harness completed without returning any content.")
    return 0


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    try:
        return asyncio.run(run_harness(args))
    except Exception as exc:
        logging.exception("Harness failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())