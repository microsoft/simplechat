# model_endpoint_clients.py
"""Protocol-aware clients for configured model endpoints."""

import json
import asyncio
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Iterator, List
from urllib.parse import urlparse

import requests
from openai import OpenAI
from pydantic import Field
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.function_calling_utils import update_settings_from_function_call_configuration
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.open_ai_prompt_execution_settings import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.function_call_content import FunctionCallContent
from semantic_kernel.contents.function_result_content import FunctionResultContent
from semantic_kernel.contents.streaming_chat_message_content import StreamingChatMessageContent
from semantic_kernel.contents.streaming_text_content import StreamingTextContent
from semantic_kernel.contents.text_content import TextContent
from semantic_kernel.contents.utils.author_role import AuthorRole
from semantic_kernel.contents.utils.finish_reason import FinishReason
from semantic_kernel.exceptions.service_exceptions import ServiceInvalidExecutionSettingsError

from functions_debug import debug_print


MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI = "azure_openai"
MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE = "openai_style"
MODEL_ENDPOINT_PROTOCOL_ANTHROPIC = "anthropic"

ANTHROPIC_MODEL_MARKERS = ("claude",)
OPENAI_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
MODEL_CONTEXT_MODE_SYSTEM = "system"
MODEL_CONTEXT_MODE_FOLD_LATEST_USER = "fold_latest_user"


class ModelEndpointBehavior:
    """Provider/model behavior policy shared by Simple Chat model endpoint callers."""

    def __init__(self, provider: Any = "", deployment_name: Any = ""):
        self.provider = str(provider or "").strip().lower()
        self.deployment_name = str(deployment_name or "").strip()
        self.normalized_deployment_name = self.deployment_name.lower()

    @property
    def is_foundry_provider(self) -> bool:
        return self.provider in {"aifoundry", "new_foundry"}

    @property
    def is_anthropic_model(self) -> bool:
        return is_anthropic_model(self.deployment_name)

    @property
    def is_openai_reasoning_model(self) -> bool:
        return self.normalized_deployment_name.startswith(OPENAI_REASONING_MODEL_PREFIXES)

    @property
    def is_foundry_non_openai_model(self) -> bool:
        if not self.is_foundry_provider or not self.normalized_deployment_name:
            return False
        if self.normalized_deployment_name.startswith(("gpt", "o1", "o3", "o4")):
            return False
        if self.is_anthropic_model:
            return False
        return True

    @property
    def context_mode(self) -> str:
        return MODEL_CONTEXT_MODE_FOLD_LATEST_USER if self.is_foundry_non_openai_model else MODEL_CONTEXT_MODE_SYSTEM

    def resolve_reasoning_effort(self, reasoning_effort: Any) -> str:
        normalized_reasoning_effort = str(reasoning_effort or "").strip()
        if not normalized_reasoning_effort or normalized_reasoning_effort.lower() == "none":
            return ""
        return normalized_reasoning_effort if self.is_openai_reasoning_model else ""


def normalize_endpoint_text(endpoint: Any) -> str:
    """Return a trimmed endpoint URL without a trailing slash."""
    return str(endpoint or "").strip().rstrip("/")


def get_endpoint_path(endpoint: Any) -> str:
    """Return the lower-case parsed path for an endpoint string."""
    endpoint_value = normalize_endpoint_text(endpoint)
    if not endpoint_value:
        return ""
    try:
        return urlparse(endpoint_value).path.lower()
    except ValueError:
        return endpoint_value.lower()


def get_endpoint_origin(endpoint: Any) -> str:
    """Return scheme and host for an endpoint URL."""
    endpoint_value = normalize_endpoint_text(endpoint)
    parsed_url = urlparse(endpoint_value)
    if not parsed_url.scheme or not parsed_url.netloc:
        return endpoint_value
    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def is_anthropic_model(deployment_name: Any) -> bool:
    """Return whether a deployment should use the Anthropic messages protocol."""
    normalized_name = str(deployment_name or "").strip().lower()
    return any(marker in normalized_name for marker in ANTHROPIC_MODEL_MARKERS)


def endpoint_uses_openai_style_protocol(endpoint: Any) -> bool:
    """Return whether the endpoint is already an OpenAI-compatible Foundry URL."""
    endpoint_value = normalize_endpoint_text(endpoint).lower()
    endpoint_path = get_endpoint_path(endpoint_value)
    return (
        "/openai/v1" in endpoint_path
        or "/api/projects/" in endpoint_path
        or "services.ai.azure.com" in endpoint_value
    )


def infer_model_endpoint_protocol(provider: Any, endpoint: Any, deployment_name: Any = "") -> str:
    """Infer the runtime protocol from provider, endpoint path, and deployment name."""
    normalized_provider = str(provider or "aoai").strip().lower()
    endpoint_path = get_endpoint_path(endpoint)

    if normalized_provider in ("anthropic", "claude"):
        return MODEL_ENDPOINT_PROTOCOL_ANTHROPIC

    if "/anthropic/" in endpoint_path or is_anthropic_model(deployment_name):
        return MODEL_ENDPOINT_PROTOCOL_ANTHROPIC

    if normalized_provider in ("aifoundry", "new_foundry") and endpoint_uses_openai_style_protocol(endpoint):
        return MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE

    return MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI


def normalize_openai_style_base_url(raw_endpoint: Any) -> str:
    """Normalize Foundry OpenAI-compatible endpoints to a base URL."""
    endpoint = normalize_endpoint_text(raw_endpoint)
    if not endpoint:
        raise ValueError("A Foundry endpoint is required for OpenAI-compatible inference.")

    lowered_endpoint = endpoint.lower()
    for suffix in ("/chat/completions", "/responses", "/models"):
        suffix_index = lowered_endpoint.find(suffix)
        if suffix_index >= 0:
            endpoint = endpoint[:suffix_index]
            lowered_endpoint = endpoint.lower()
            break

    openai_v1_index = lowered_endpoint.find("/openai/v1")
    if openai_v1_index >= 0:
        return endpoint[: openai_v1_index + len("/openai/v1")].rstrip("/") + "/"

    openai_index = lowered_endpoint.find("/openai")
    if openai_index >= 0:
        return endpoint[:openai_index].rstrip("/") + "/openai/v1/"

    return endpoint.rstrip("/") + "/openai/v1/"


def normalize_anthropic_messages_url(raw_endpoint: Any) -> str:
    """Normalize a Foundry endpoint to the Anthropic messages URL."""
    endpoint = normalize_endpoint_text(raw_endpoint)
    if not endpoint:
        raise ValueError("A Foundry endpoint is required for Anthropic inference.")

    lowered_endpoint = endpoint.lower()
    messages_index = lowered_endpoint.find("/anthropic/v1/messages")
    if messages_index >= 0:
        return endpoint[: messages_index + len("/anthropic/v1/messages")]

    anthropic_index = lowered_endpoint.find("/anthropic/v1")
    if anthropic_index >= 0:
        return endpoint[: anthropic_index + len("/anthropic/v1")].rstrip("/") + "/messages"

    return get_endpoint_origin(endpoint).rstrip("/") + "/anthropic/v1/messages"


def resolve_openai_style_request_api_version(raw_api_version: Any) -> str:
    """Return a version query value that is valid for OpenAI-style /openai/v1 requests."""
    return ""


def normalize_chat_completion_text(content: Any) -> str:
    """Normalize text content returned by OpenAI-compatible chat responses."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
                continue
            if isinstance(part, dict):
                part_text = part.get("text") or part.get("content") or part.get("value")
                if isinstance(part_text, str):
                    text_parts.append(part_text)
                elif isinstance(part_text, dict) and isinstance(part_text.get("value"), str):
                    text_parts.append(part_text["value"])
                continue
            part_text = getattr(part, "text", None) or getattr(part, "content", None)
            if isinstance(part_text, str):
                text_parts.append(part_text)
        return "".join(text_parts)
    return str(content)


def extract_chat_completion_response_text(response: Any) -> str:
    """Extract assistant message text from a chat completion response."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return normalize_chat_completion_text(getattr(message, "content", None))


def build_openai_style_chat_client(token_or_key: str, base_url: str, api_version: Any = ""):
    """Build an OpenAI-compatible chat client for Foundry data-plane endpoints."""
    request_api_version = resolve_openai_style_request_api_version(api_version)
    client_kwargs: Dict[str, Any] = {
        "api_key": token_or_key,
        "base_url": normalize_openai_style_base_url(base_url),
    }
    if request_api_version:
        client_kwargs["default_query"] = {"api-version": request_api_version}
    return OpenAIStyleChatCompletionClient(OpenAI(**client_kwargs))


class OpenAIStyleChatCompletionClient:
    """Small wrapper that makes OpenAI-compatible Foundry calls tolerant of Azure-only options."""

    def __init__(self, client: OpenAI):
        self._client = client
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any):
        request_kwargs = dict(kwargs)
        request_kwargs.pop("stream_options", None)
        return self._client.chat.completions.create(**request_kwargs)


def build_anthropic_chat_client(
    *,
    endpoint: str,
    api_key: str = "",
    bearer_token: str = "",
    timeout: int = 90,
):
    """Build a chat-completions-shaped adapter over the Anthropic messages protocol."""
    return AnthropicChatCompletionClient(
        endpoint=endpoint,
        api_key=api_key,
        bearer_token=bearer_token,
        timeout=timeout,
    )


class AnthropicChatCompletionClient:
    """Adapter that exposes Anthropic messages through chat.completions.create."""

    def __init__(self, *, endpoint: str, api_key: str = "", bearer_token: str = "", timeout: int = 90):
        self.endpoint = normalize_anthropic_messages_url(endpoint)
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs: Any):
        payload = self._build_payload(kwargs)
        stream = bool(kwargs.get("stream"))
        response = requests.post(
            self.endpoint,
            headers=self._build_headers(stream=stream),
            json=payload,
            timeout=(30, self.timeout),
            stream=stream,
        )
        if response.status_code >= 400:
            self._raise_response_error(response)

        if stream:
            return self._iter_stream_chunks(response)

        return self._build_completion_response(response.json())

    def _build_headers(self, *, stream: bool = False) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif self.api_key:
            headers["api-key"] = self.api_key
            headers["x-api-key"] = self.api_key
        else:
            raise ValueError("Anthropic model endpoints require an API key or bearer token.")
        return headers

    def _build_payload(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        model = str(kwargs.get("model") or "").strip()
        if not model:
            raise ValueError("Anthropic model requests require a deployment name.")

        messages, system_prompt = self._convert_messages(kwargs.get("messages") or [])
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(kwargs),
        }
        if system_prompt:
            payload["system"] = system_prompt
        if kwargs.get("stream"):
            payload["stream"] = True
        for field_name in ("temperature", "top_p", "stop_sequences"):
            value = kwargs.get(field_name)
            if value not in (None, "", [], {}):
                payload[field_name] = value
        if kwargs.get("stop") not in (None, "", [], {}):
            payload["stop_sequences"] = kwargs.get("stop")

        tools = self._convert_tools(kwargs.get("tools"))
        if tools:
            payload["tools"] = tools
            tool_choice = self._convert_tool_choice(kwargs.get("tool_choice"))
            if tool_choice:
                payload["tool_choice"] = tool_choice

        return payload

    def _convert_tools(self, tools: Any) -> List[Dict[str, Any]]:
        converted_tools: List[Dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            function_payload = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            tool_name = str(function_payload.get("name") or "").strip()
            if not tool_name:
                continue
            input_schema = function_payload.get("parameters")
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}
            converted_tools.append({
                "name": tool_name,
                "description": str(function_payload.get("description") or ""),
                "input_schema": input_schema,
            })
        return converted_tools

    def _convert_tool_choice(self, tool_choice: Any) -> Dict[str, Any] | None:
        if tool_choice in (None, "", [], {}):
            return None
        if isinstance(tool_choice, dict):
            return tool_choice

        normalized_choice = str(getattr(tool_choice, "value", tool_choice) or "").strip().lower()
        if normalized_choice == "required":
            return {"type": "any"}
        if normalized_choice == "none":
            return {"type": "none"}
        if normalized_choice == "auto":
            return {"type": "auto"}
        return None

    def _resolve_max_tokens(self, kwargs: Dict[str, Any]) -> int:
        for field_name in ("max_tokens", "max_completion_tokens"):
            value = kwargs.get(field_name)
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                continue
            if normalized > 0:
                return normalized
        return 4096

    def _convert_messages(self, messages: Iterable[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], str]:
        converted: List[Dict[str, Any]] = []
        system_parts: List[str] = []

        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").lower()
            content = self._normalize_content(message.get("content"))
            if not content:
                continue
            if role == "system":
                system_parts.append(self._content_to_text(content))
                continue
            if role not in ("user", "assistant"):
                role = "user"
            converted.append({"role": role, "content": content})

        if not converted:
            raise ValueError("Anthropic model requests require at least one user or assistant message.")

        return converted, "\n\n".join(system_parts)

    def _normalize_content(self, content: Any) -> str | List[Dict[str, Any]]:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            normalized_blocks = []
            text_parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type in ("text", "tool_use", "tool_result"):
                        normalized_blocks.append(item)
                        continue
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        text_parts.append(text_value)
            if normalized_blocks:
                if text_parts:
                    normalized_blocks.insert(0, {"type": "text", "text": "\n".join(part for part in text_parts if part)})
                return normalized_blocks
            return "\n".join(part for part in text_parts if part)
        if content is None:
            return ""
        return str(content)

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict):
                    text_value = item.get("text") or item.get("content")
                    if isinstance(text_value, str):
                        text_parts.append(text_value)
            return "\n".join(part for part in text_parts if part)
        return str(content or "")

    def _build_completion_response(self, response_payload: Dict[str, Any]):
        text, tool_calls = self._extract_response_parts(response_payload)
        usage_payload = response_payload.get("usage") if isinstance(response_payload.get("usage"), dict) else {}
        prompt_tokens = int(usage_payload.get("input_tokens") or 0)
        completion_tokens = int(usage_payload.get("output_tokens") or 0)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=tool_calls),
                finish_reason=response_payload.get("stop_reason"),
            )],
            usage=SimpleNamespace(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    def _extract_response_text(self, response_payload: Dict[str, Any]) -> str:
        text, _ = self._extract_response_parts(response_payload)
        return text

    def _extract_response_parts(self, response_payload: Dict[str, Any]) -> tuple[str, List[Any]]:
        content = response_payload.get("content")
        if not isinstance(content, list):
            return "", []
        text_parts = []
        tool_calls = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
            elif item.get("type") == "tool_use":
                tool_input = item.get("input") if isinstance(item.get("input"), dict) else {}
                tool_calls.append(SimpleNamespace(
                    id=str(item.get("id") or ""),
                    type="function",
                    function=SimpleNamespace(
                        name=str(item.get("name") or ""),
                        arguments=json.dumps(tool_input),
                    ),
                ))
        return "".join(text_parts), tool_calls

    def _iter_stream_chunks(self, response: requests.Response) -> Iterator[Any]:
        prompt_tokens = 0
        completion_tokens = 0
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8", errors="replace").strip()
                else:
                    line = str(raw_line).strip()
                if not line.startswith("data:"):
                    continue
                event_data = line[5:].strip()
                if not event_data or event_data == "[DONE]":
                    continue
                try:
                    event_payload = json.loads(event_data)
                except json.JSONDecodeError:
                    debug_print(f"[ModelEndpoint] Ignoring invalid Anthropic stream payload: {event_data[:200]}")
                    continue

                event_type = event_payload.get("type")
                if event_type == "error":
                    error_payload = event_payload.get("error")
                    if isinstance(error_payload, dict):
                        error_message = error_payload.get("message") or error_payload.get("type") or str(error_payload)
                    else:
                        error_message = str(error_payload or event_payload)
                    raise RuntimeError(f"Anthropic model stream failed: {error_message}")
                if event_type == "message_start":
                    usage = event_payload.get("message", {}).get("usage", {})
                    prompt_tokens = int(usage.get("input_tokens") or prompt_tokens or 0)
                    continue
                if event_type == "content_block_delta":
                    delta = event_payload.get("delta") or {}
                    text = delta.get("text") if isinstance(delta, dict) else ""
                    if text:
                        yield SimpleNamespace(
                            choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
                            usage=None,
                        )
                    continue
                if event_type == "message_delta":
                    usage = event_payload.get("usage") if isinstance(event_payload.get("usage"), dict) else {}
                    prompt_tokens = int(usage.get("input_tokens") or prompt_tokens or 0)
                    completion_tokens = int(usage.get("output_tokens") or completion_tokens or 0)
                    continue
        finally:
            response.close()

        if prompt_tokens or completion_tokens:
            yield SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            )

    def _raise_response_error(self, response: requests.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text[:500]}

        error_payload = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error_payload, dict):
            error_message = error_payload.get("message") or error_payload.get("type") or str(error_payload)
        else:
            error_message = str(error_payload or payload)

        raise RuntimeError(
            f"Anthropic model request failed with status {response.status_code}: {error_message}"
        )


class AnthropicSemanticKernelChatCompletion(ChatCompletionClientBase):
    """Semantic Kernel chat service for Anthropic-compatible model endpoints."""

    SUPPORTS_FUNCTION_CALLING = True

    endpoint: str
    api_key: str = ""
    bearer_token: str = ""
    timeout: int = 90
    prompt_execution_settings: OpenAIChatPromptExecutionSettings | None = Field(default=None)

    def __init__(
        self,
        *,
        service_id: str,
        deployment_name: str,
        endpoint: str,
        api_key: str = "",
        bearer_token: str = "",
        timeout: int = 90,
    ):
        super().__init__(
            ai_model_id=deployment_name,
            service_id=service_id,
            endpoint=endpoint,
            api_key=api_key,
            bearer_token=bearer_token,
            timeout=timeout,
        )

    def get_prompt_execution_settings_class(self):
        return OpenAIChatPromptExecutionSettings

    def instantiate_prompt_execution_settings(self):
        return OpenAIChatPromptExecutionSettings()

    def set_prompt_execution_settings(self, prompt_execution_settings):
        self.prompt_execution_settings = OpenAIChatPromptExecutionSettings.from_prompt_execution_settings(
            prompt_execution_settings
        )

    def _verify_function_choice_settings(self, settings) -> None:
        if not isinstance(settings, OpenAIChatPromptExecutionSettings):
            raise ServiceInvalidExecutionSettingsError(
                "The settings must be an OpenAIChatPromptExecutionSettings."
            )
        if getattr(settings, "number_of_responses", None) is not None and settings.number_of_responses > 1:
            raise ServiceInvalidExecutionSettingsError(
                "Auto invocation of tool calls may only be used with a single completion."
            )

    def _update_function_choice_settings_callback(self):
        return update_settings_from_function_call_configuration

    def _reset_function_choice_settings(self, settings) -> None:
        if hasattr(settings, "tool_choice"):
            settings.tool_choice = None
        if hasattr(settings, "tools"):
            settings.tools = None

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        request_kwargs = self._build_request_kwargs(chat_history, settings, stream=False)
        client = self._build_client()
        response = await asyncio.to_thread(client.chat.completions.create, **request_kwargs)
        return self._create_chat_message_contents_from_response(response)

    def _create_chat_message_contents_from_response(self, response) -> List[ChatMessageContent]:
        choice = response.choices[0] if response.choices else None
        message = getattr(choice, "message", None) if choice else None
        items = []
        content = getattr(message, "content", "") if message else ""
        if content:
            items.append(TextContent(text=content))
        for tool_call in getattr(message, "tool_calls", None) or []:
            function_payload = getattr(tool_call, "function", None)
            tool_name = getattr(function_payload, "name", "") if function_payload else ""
            if not tool_name:
                continue
            items.append(FunctionCallContent(
                id=getattr(tool_call, "id", None),
                name=tool_name,
                arguments=getattr(function_payload, "arguments", "{}"),
            ))
        return [
            ChatMessageContent(
                role=AuthorRole.ASSISTANT,
                items=items,
                ai_model_id=self.ai_model_id,
                inner_content=response,
                finish_reason=self._normalize_finish_reason(getattr(choice, "finish_reason", None)),
                metadata=self._build_usage_metadata(response),
            )
        ]

    def _normalize_finish_reason(self, finish_reason: Any) -> FinishReason | None:
        normalized_reason = str(finish_reason or "").strip().lower()
        if not normalized_reason:
            return None
        if normalized_reason == "tool_use":
            normalized_reason = "tool_calls"
        try:
            return FinishReason(normalized_reason)
        except ValueError:
            return None

    async def _inner_get_streaming_chat_message_contents(
        self,
        chat_history,
        settings,
        function_invoke_attempt: int = 0,
    ):
        if getattr(settings, "tools", None):
            request_kwargs = self._build_request_kwargs(chat_history, settings, stream=False)
            client = self._build_client()
            response = await asyncio.to_thread(client.chat.completions.create, **request_kwargs)
            for message in self._create_chat_message_contents_from_response(response):
                yield [self._to_streaming_chat_message_content(message, function_invoke_attempt)]
            return

        request_kwargs = self._build_request_kwargs(chat_history, settings, stream=True)
        client = self._build_client()
        stream = await asyncio.to_thread(client.chat.completions.create, **request_kwargs)
        sentinel = object()
        iterator = iter(stream)

        while True:
            chunk = await asyncio.to_thread(next, iterator, sentinel)
            if chunk is sentinel:
                break

            metadata = self._build_usage_metadata(chunk)
            if not getattr(chunk, "choices", None):
                if metadata:
                    yield [
                        StreamingChatMessageContent(
                            role=AuthorRole.ASSISTANT,
                            content="",
                            choice_index=0,
                            ai_model_id=self.ai_model_id,
                            inner_content=chunk,
                            metadata=metadata,
                            function_invoke_attempt=function_invoke_attempt,
                        )
                    ]
                continue

            delta = getattr(chunk.choices[0], "delta", None)
            content = getattr(delta, "content", "") if delta else ""
            if content:
                yield [
                    StreamingChatMessageContent(
                        role=AuthorRole.ASSISTANT,
                        content=content,
                        choice_index=0,
                        ai_model_id=self.ai_model_id,
                        inner_content=chunk,
                        metadata=metadata,
                        function_invoke_attempt=function_invoke_attempt,
                    )
                ]

    def _to_streaming_chat_message_content(
        self,
        message: ChatMessageContent,
        function_invoke_attempt: int,
    ) -> StreamingChatMessageContent:
        streaming_items = []
        for item in message.items or []:
            if isinstance(item, TextContent):
                streaming_items.append(StreamingTextContent(
                    choice_index=0,
                    text=item.text,
                    ai_model_id=self.ai_model_id,
                    inner_content=item.inner_content,
                    metadata=item.metadata,
                    encoding=item.encoding,
                ))
            else:
                streaming_items.append(item)
        return StreamingChatMessageContent(
            role=message.role,
            items=streaming_items,
            choice_index=0,
            ai_model_id=self.ai_model_id,
            inner_content=message.inner_content,
            metadata=message.metadata,
            finish_reason=message.finish_reason,
            function_invoke_attempt=function_invoke_attempt,
        )

    def _build_client(self):
        return build_anthropic_chat_client(
            endpoint=self.endpoint,
            api_key=self.api_key,
            bearer_token=self.bearer_token,
            timeout=self.timeout,
        )

    def _build_request_kwargs(self, chat_history, settings, *, stream: bool) -> Dict[str, Any]:
        request_kwargs: Dict[str, Any] = {
            "model": self.ai_model_id,
            "messages": self._convert_chat_history(chat_history),
            "stream": stream,
        }

        for source_settings in (self.prompt_execution_settings, settings):
            if not source_settings:
                continue
            self._copy_setting(source_settings, request_kwargs, "temperature")
            self._copy_setting(source_settings, request_kwargs, "top_p")
            self._copy_setting(source_settings, request_kwargs, "max_tokens")
            self._copy_setting(source_settings, request_kwargs, "max_completion_tokens")
            stop_value = getattr(source_settings, "stop", None)
            if stop_value not in (None, "", [], {}):
                request_kwargs["stop"] = stop_value
            tools = getattr(source_settings, "tools", None)
            if tools not in (None, "", [], {}):
                request_kwargs["tools"] = tools
            tool_choice = getattr(source_settings, "tool_choice", None)
            if tool_choice not in (None, "", [], {}):
                request_kwargs["tool_choice"] = tool_choice

        return request_kwargs

    def _copy_setting(self, settings, request_kwargs: Dict[str, Any], field_name: str) -> None:
        value = getattr(settings, field_name, None)
        if value not in (None, "", [], {}):
            request_kwargs[field_name] = value

    def _convert_chat_history(self, chat_history) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        for message in getattr(chat_history, "messages", []) or []:
            if not isinstance(message, ChatMessageContent):
                continue
            role_value = getattr(message, "role", "user") or "user"
            role = str(getattr(role_value, "value", role_value)).lower()
            if role == "developer":
                role = "system"
            elif role == "tool":
                role = "user"
            content = self._convert_message_content(message)
            if content is None and hasattr(message, "to_dict"):
                try:
                    content = message.to_dict(role_key="role", content_key="content").get("content")
                except Exception:
                    content = ""
            if content in (None, "", [], {}):
                continue
            messages.append({"role": role, "content": content})
        return messages

    def _convert_message_content(self, message: ChatMessageContent) -> str | List[Dict[str, Any]] | None:
        items = getattr(message, "items", []) or []
        if not items:
            return getattr(message, "content", None)

        text_parts = []
        blocks = []
        for item in items:
            if isinstance(item, FunctionCallContent):
                tool_id = item.id or item.call_id or item.name or item.function_name
                blocks.append({
                    "type": "tool_use",
                    "id": str(tool_id or "tool_call"),
                    "name": str(item.name or item.function_name or ""),
                    "input": self._parse_function_arguments(item.arguments),
                })
            elif isinstance(item, FunctionResultContent):
                tool_result_id = item.id or item.call_id or item.name or item.function_name
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": str(tool_result_id or "tool_call"),
                    "content": self._stringify_tool_result(item.result),
                })
            elif isinstance(item, TextContent):
                text_parts.append(item.text)

        if blocks:
            if text_parts:
                blocks.insert(0, {"type": "text", "text": "\n".join(text_parts)})
            return blocks
        if text_parts:
            return "\n".join(text_parts)
        return getattr(message, "content", None)

    def _parse_function_arguments(self, arguments: Any) -> Dict[str, Any]:
        if isinstance(arguments, dict):
            return arguments
        if arguments in (None, "", {}):
            return {}
        try:
            parsed_arguments = json.loads(str(arguments))
            return parsed_arguments if isinstance(parsed_arguments, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _stringify_tool_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, default=str)
        except (TypeError, ValueError):
            return str(result)

    def _build_usage_metadata(self, response_or_chunk) -> Dict[str, Any]:
        usage = getattr(response_or_chunk, "usage", None)
        if not usage:
            return {}
        return {
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            }
        }