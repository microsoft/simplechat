# foundry_agent_runtime.py
"""Azure AI Foundry agent execution helpers."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional
from urllib.parse import quote

import requests
from azure.identity import (
    AzureAuthorityHosts,
    ClientSecretCredential as SyncClientSecretCredential,
    DefaultAzureCredential as SyncDefaultAzureCredential,
)
from azure.identity.aio import (  # type: ignore
    ClientSecretCredential as AsyncClientSecretCredential,
    DefaultAzureCredential as AsyncDefaultAzureCredential,
)
from semantic_kernel.agents import AzureAIAgent
from semantic_kernel.contents.chat_message_content import ChatMessageContent

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_keyvault import (
    retrieve_secret_from_key_vault_by_full_name,
    validate_secret_name_dynamic,
)

_logger = logging.getLogger("foundry_agent_runtime")


@dataclass
class FoundryAgentInvocationResult:
    """Represents the outcome from a Foundry agent run."""

    message: str
    model: Optional[str]
    citations: List[Dict[str, Any]]
    metadata: Dict[str, Any]


@dataclass
class FoundryAgentStreamMessage:
    """Represents a streaming content or metadata event from a Foundry runtime."""

    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NewFoundryStreamState:
    """Tracks new Foundry response state while processing an event stream."""

    text_parts: List[str] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class FoundryAgentInvocationError(RuntimeError):
    """Raised when the Foundry agent invocation cannot be completed."""


def _normalize_max_completion_tokens(value: Any) -> Optional[int]:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


class AzureAIFoundryChatCompletionAgent:
    """Lightweight wrapper so Foundry agents behave like SK chat agents."""

    agent_type = "aifoundry"

    def __init__(self, agent_config: Dict[str, Any], settings: Dict[str, Any]):
        self.name = agent_config.get("name")
        self.display_name = agent_config.get("display_name") or self.name
        self.description = agent_config.get("description", "")
        self.id = agent_config.get("id")
        self.default_agent = agent_config.get("default_agent", False)
        self.is_global = agent_config.get("is_global", False)
        self.is_group = agent_config.get("is_group", False)
        self.group_id = agent_config.get("group_id")
        self.group_name = agent_config.get("group_name")
        self.max_completion_tokens = agent_config.get("max_completion_tokens", -1)
        self.last_run_citations: List[Dict[str, Any]] = []
        self.last_run_model: Optional[str] = None
        self._foundry_settings = (
            (agent_config.get("other_settings") or {}).get("azure_ai_foundry") or {}
        )
        self._global_settings = settings or {}

    def invoke(
        self,
        agent_message_history: Iterable[ChatMessageContent],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Synchronously invoke the Foundry agent and return the final message text."""

        metadata = metadata or {}
        history = list(agent_message_history)
        debug_print(
            f"[FoundryAgent] Invoking agent '{self.name}' with {len(history)} messages"
        )

        try:
            result = asyncio.run(
                execute_foundry_agent(
                    foundry_settings=self._foundry_settings,
                    global_settings=self._global_settings,
                    message_history=history,
                    metadata=metadata,
                    max_completion_tokens=self.max_completion_tokens,
                )
            )
        except RuntimeError:
            log_event(
                "[FoundryAgent] Invocation runtime error",
                extra={
                    "agent_id": self.id,
                    "agent_name": self.name,
                },
                level=logging.ERROR,
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            log_event(
                "[FoundryAgent] Invocation error",
                extra={
                    "agent_id": self.id,
                    "agent_name": self.name,
                },
                level=logging.ERROR,
            )
            raise

        self.last_run_citations = result.citations
        self.last_run_model = result.model
        return result.message

    async def invoke_stream(
        self,
        messages: Iterable[ChatMessageContent],
    ) -> AsyncIterator[str]:
        """Yield a single final chunk so Foundry agents can participate in stream mode."""

        result = await execute_foundry_agent(
            foundry_settings=self._foundry_settings,
            global_settings=self._global_settings,
            message_history=list(messages),
            metadata={},
            max_completion_tokens=self.max_completion_tokens,
        )
        self.last_run_citations = result.citations
        self.last_run_model = result.model
        if result.message:
            yield result.message


class AzureAIFoundryNewChatCompletionAgent:
    """Wrapper for the new Foundry application-based runtime."""

    agent_type = "new_foundry"

    def __init__(self, agent_config: Dict[str, Any], settings: Dict[str, Any]):
        self.name = agent_config.get("name")
        self.display_name = agent_config.get("display_name") or self.name
        self.description = agent_config.get("description", "")
        self.id = agent_config.get("id")
        self.default_agent = agent_config.get("default_agent", False)
        self.is_global = agent_config.get("is_global", False)
        self.is_group = agent_config.get("is_group", False)
        self.group_id = agent_config.get("group_id")
        self.group_name = agent_config.get("group_name")
        self.max_completion_tokens = agent_config.get("max_completion_tokens", -1)
        self.last_run_citations: List[Dict[str, Any]] = []
        self.last_run_model: Optional[str] = None
        self._new_foundry_settings = (
            (agent_config.get("other_settings") or {}).get("new_foundry") or {}
        )
        self._global_settings = settings or {}

    def invoke(
        self,
        agent_message_history: Iterable[ChatMessageContent],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Synchronously invoke the new Foundry application runtime."""

        metadata = metadata or {}
        history = list(agent_message_history)
        debug_print(
            f"[NewFoundryAgent] Invoking application '{self.name}' with {len(history)} messages"
        )

        result = asyncio.run(
            execute_new_foundry_agent(
                foundry_settings=self._new_foundry_settings,
                global_settings=self._global_settings,
                message_history=history,
                metadata=metadata,
                max_completion_tokens=self.max_completion_tokens,
            )
        )
        self.last_run_citations = result.citations
        self.last_run_model = result.model
        return result.message

    async def invoke_stream(
        self,
        messages: Iterable[ChatMessageContent],
    ) -> AsyncIterator[FoundryAgentStreamMessage]:
        """Yield incremental content for the new Foundry application runtime."""

        async for stream_message in execute_new_foundry_agent_stream(
            foundry_settings=self._new_foundry_settings,
            global_settings=self._global_settings,
            message_history=list(messages),
            metadata={},
            max_completion_tokens=self.max_completion_tokens,
        ):
            if stream_message.metadata:
                citations = stream_message.metadata.get("citations")
                if isinstance(citations, list):
                    self.last_run_citations = citations
                model_value = stream_message.metadata.get("model")
                if isinstance(model_value, str) and model_value.strip():
                    self.last_run_model = model_value.strip()
            yield stream_message


async def execute_foundry_agent(
    *,
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    max_completion_tokens: Optional[int] = None,
) -> FoundryAgentInvocationResult:
    """Invoke a Foundry agent using Semantic Kernel's AzureAIAgent abstraction."""

    agent_id = (foundry_settings.get("agent_id") or "").strip()
    if not agent_id:
        raise FoundryAgentInvocationError(
            "Azure AI Foundry agents require an agent_id in other_settings.azure_ai_foundry."
        )

    endpoint = _resolve_endpoint(foundry_settings, global_settings)
    api_version = foundry_settings.get("api_version") or global_settings.get(
        "azure_ai_foundry_api_version"
    )

    credential = _build_async_credential(foundry_settings, global_settings)
    client = AzureAIAgent.create_client(
        credential=credential,
        endpoint=endpoint,
        api_version=api_version,
    )
    resolved_max_completion_tokens = _normalize_max_completion_tokens(max_completion_tokens)

    try:
        definition = await client.agents.get_agent(agent_id)
        azure_agent = AzureAIAgent(client=client, definition=definition)
        responses = []
        invoke_kwargs = {
            "messages": message_history,
            "metadata": {k: str(v) for k, v in metadata.items() if v is not None},
        }
        if resolved_max_completion_tokens is not None:
            invoke_kwargs["max_completion_tokens"] = resolved_max_completion_tokens

        async for response in azure_agent.invoke(**invoke_kwargs):
            responses.append(response)

        if not responses:
            raise FoundryAgentInvocationError("Foundry agent returned no messages.")

        last_response = responses[-1]

        thread_id = None
        if last_response.thread is not None:
            thread_id = getattr(last_response.thread, "id", None)

        message_obj = last_response.message

        if not thread_id:
            metadata_thread_id = None
            if isinstance(message_obj.metadata, dict):
                metadata_thread_id = message_obj.metadata.get("thread_id")
            thread_id = metadata_thread_id or metadata.get("thread_id")

        if thread_id:
            try:
                if last_response.thread is not None and hasattr(last_response.thread, "delete"):
                    await last_response.thread.delete()
                elif hasattr(client, "agents") and hasattr(client.agents, "delete_thread"):
                    await client.agents.delete_thread(thread_id)
            except Exception as cleanup_error:  # pragma: no cover - best effort cleanup
                _logger.warning("Failed to delete Foundry thread: %s", cleanup_error)
        text = _extract_message_text(message_obj)
        citations = _extract_citations(message_obj)
        model_name = getattr(definition, "model", None)
        if isinstance(model_name, dict):
            model_value = model_name.get("id")
        else:
            model_value = getattr(model_name, "id", None)

        log_event(
            "[FoundryAgent] Invocation complete",
            extra={
                "agent_id": agent_id,
                "endpoint": endpoint,
                "model": model_value,
                "message_length": len(text or ""),
                "max_completion_tokens": resolved_max_completion_tokens,
            },
        )

        return FoundryAgentInvocationResult(
            message=text,
            model=model_value,
            citations=citations,
            metadata=message_obj.metadata or {},
        )
    finally:
        try:
            await client.close()
        finally:
            await credential.close()


async def execute_new_foundry_agent(
    *,
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    max_completion_tokens: Optional[int] = None,
) -> FoundryAgentInvocationResult:
    """Invoke the new Foundry application runtime through its Responses protocol endpoint."""

    application_name = _resolve_new_foundry_application_name(foundry_settings)
    endpoint = _resolve_endpoint(foundry_settings, global_settings)
    responses_api_version = (
        foundry_settings.get("responses_api_version")
        or foundry_settings.get("api_version")
        or global_settings.get("azure_ai_foundry_api_version")
    )
    if not responses_api_version:
        raise FoundryAgentInvocationError(
            "New Foundry agents require a responses_api_version setting."
        )

    credential = _build_async_credential(foundry_settings, global_settings)
    scope = _resolve_foundry_scope(foundry_settings, global_settings)
    token = await credential.get_token(scope)
    url = (
        f"{endpoint.rstrip('/')}/applications/{quote(application_name, safe='')}/"
        "protocols/openai/responses"
    )
    payload = _build_new_foundry_request_payload(
        message_history,
        metadata,
        stream=False,
        max_output_tokens=_normalize_max_completion_tokens(max_completion_tokens),
    )
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }

    try:
        response = await asyncio.to_thread(
            requests.post,
            url,
            params={"api-version": responses_api_version},
            headers=headers,
            json=payload,
            timeout=90,
        )
        response_payload = _parse_json_response(response)
        if response.status_code >= 400:
            raise FoundryAgentInvocationError(
                _build_http_error_message("new Foundry response", response, response_payload)
            )

        result = _build_new_foundry_invocation_result(
            response_payload=response_payload,
            application_name=application_name,
        )

        log_event(
            "[NewFoundryAgent] Invocation complete",
            extra={
                "application_name": application_name,
                "endpoint": endpoint,
                "model": result.model,
                "message_length": len(result.message),
                "max_output_tokens": payload.get("max_output_tokens"),
            },
        )

        return result
    finally:
        await credential.close()


async def execute_new_foundry_agent_stream(
    *,
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    max_completion_tokens: Optional[int] = None,
) -> AsyncIterator[FoundryAgentStreamMessage]:
    """Stream a new Foundry application response through the Responses API."""

    application_name = _resolve_new_foundry_application_name(foundry_settings)
    endpoint = _resolve_endpoint(foundry_settings, global_settings)
    responses_api_version = (
        foundry_settings.get("responses_api_version")
        or foundry_settings.get("api_version")
        or global_settings.get("azure_ai_foundry_api_version")
    )
    if not responses_api_version:
        raise FoundryAgentInvocationError(
            "New Foundry agents require a responses_api_version setting."
        )

    credential = _build_async_credential(foundry_settings, global_settings)
    scope = _resolve_foundry_scope(foundry_settings, global_settings)
    token = await credential.get_token(scope)
    url = (
        f"{endpoint.rstrip('/')}/applications/{quote(application_name, safe='')}/"
        "protocols/openai/responses"
    )
    debug_print(f"Invoking new Foundry application '{application_name}' at {endpoint} with streaming to url {url} with api-version {responses_api_version}")
    payload = _build_new_foundry_request_payload(
        message_history,
        metadata,
        stream=True,
        max_output_tokens=_normalize_max_completion_tokens(max_completion_tokens),
    )
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }
    response: Optional[requests.Response] = None
    state = NewFoundryStreamState()

    try:
        response = requests.post(
            url,
            params={"api-version": responses_api_version},
            headers=headers,
            json=payload,
            timeout=(30, 90),
            stream=True,
        )
        if response.status_code >= 400:
            response_payload = _try_parse_json_response(response)
            raise FoundryAgentInvocationError(
                _build_http_error_message(
                    "new Foundry stream",
                    response,
                    response_payload or {},
                )
            )

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/event-stream" not in content_type:
            response_payload = _parse_json_response(response)
            result = _build_new_foundry_invocation_result(
                response_payload=response_payload,
                application_name=application_name,
            )
            if result.message:
                yield FoundryAgentStreamMessage(content=result.message)
            yield FoundryAgentStreamMessage(
                metadata={
                    **result.metadata,
                    "citations": result.citations,
                    "model": result.model,
                }
            )
            return

        for event_name, event_data in _iter_sse_events(response):
            if event_data == "[DONE]":
                break

            event_payload = _parse_sse_json_payload(event_name, event_data)
            event_type = str(event_payload.get("type") or event_name or "").strip()
            if not event_type:
                continue

            if event_type in {"error", "response.error", "response.failed"}:
                raise FoundryAgentInvocationError(
                    _extract_new_foundry_event_error(event_payload)
                )

            delta_text = _extract_new_foundry_stream_delta(event_payload)
            if delta_text:
                state.text_parts.append(delta_text)
                yield FoundryAgentStreamMessage(content=delta_text)

            _update_new_foundry_stream_state(
                state=state,
                event_payload=event_payload,
                application_name=application_name,
            )

        full_text = "".join(state.text_parts).strip()
        if not full_text:
            fallback_text = _extract_new_foundry_stream_text(state)
            if fallback_text:
                state.text_parts = [fallback_text]
                yield FoundryAgentStreamMessage(content=fallback_text)

        yield FoundryAgentStreamMessage(metadata=_build_new_foundry_stream_metadata(state, application_name))
    finally:
        if response is not None:
            response.close()
        await credential.close()


def _resolve_endpoint(foundry_settings: Dict[str, Any], global_settings: Dict[str, Any]) -> str:
    endpoint = (
        foundry_settings.get("endpoint")
        or global_settings.get("azure_ai_foundry_endpoint")
        or os.getenv("AZURE_AI_AGENT_ENDPOINT")
    )
    project_name = (foundry_settings.get("project_name") or "").strip()
    if endpoint:
        endpoint = endpoint.rstrip("/")
        if "/api/projects/" not in endpoint and project_name:
            endpoint = f"{endpoint}/api/projects/{project_name}"
        return endpoint

    raise FoundryAgentInvocationError(
        "Azure AI Foundry endpoint is not configured. Provide an endpoint in the agent's other_settings.azure_ai_foundry or global settings."
    )


def _resolve_new_foundry_application_name(foundry_settings: Dict[str, Any]) -> str:
    application_name = str(foundry_settings.get("application_name") or "").strip()
    application_id = str(foundry_settings.get("application_id") or "").strip()
    if not application_name and application_id:
        application_name = application_id.split(":", 1)[0].strip()
    if not application_name:
        raise FoundryAgentInvocationError(
            "New Foundry agents require application_name or application_id in other_settings.new_foundry."
        )
    return application_name


def _build_async_credential(
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
):
    auth_type = (
        foundry_settings.get("authentication_type")
        or foundry_settings.get("auth_type")
        or global_settings.get("azure_ai_foundry_authentication_type")
    )
    managed_identity_type = (
        foundry_settings.get("managed_identity_type")
        or global_settings.get("azure_ai_foundry_managed_identity_type")
    )
    managed_identity_client_id = (
        foundry_settings.get("managed_identity_client_id")
        or global_settings.get("azure_ai_foundry_managed_identity_client_id")
    )

    authority = (
        foundry_settings.get("authority")
        or global_settings.get("azure_ai_foundry_authority")
        or _authority_from_cloud(foundry_settings.get("cloud") or global_settings.get("azure_ai_foundry_cloud"))
    )

    tenant_id = foundry_settings.get("tenant_id") or global_settings.get(
        "azure_ai_foundry_tenant_id"
    )
    client_id = foundry_settings.get("client_id") or global_settings.get(
        "azure_ai_foundry_client_id"
    )
    client_secret = foundry_settings.get("client_secret") or global_settings.get(
        "azure_ai_foundry_client_secret"
    )

    if auth_type == "service_principal":
        if not client_secret:
            raise FoundryAgentInvocationError(
                "Foundry service principals require client_secret value."
            )
        resolved_secret = _resolve_secret_value(client_secret)
        if not tenant_id or not client_id:
            raise FoundryAgentInvocationError(
                "Foundry service principals require tenant_id and client_id values."
            )
        return AsyncClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=resolved_secret,
            authority=authority,
        )

    if client_secret and auth_type != "managed_identity":
        resolved_secret = _resolve_secret_value(client_secret)
        if not tenant_id or not client_id:
            raise FoundryAgentInvocationError(
                "Foundry service principals require tenant_id and client_id values."
            )
        return AsyncClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=resolved_secret,
            authority=authority,
        )

    if auth_type == "managed_identity":
        if managed_identity_type == "user_assigned" and managed_identity_client_id:
            return AsyncDefaultAzureCredential(
                authority=authority,
                managed_identity_client_id=managed_identity_client_id,
            )
        return AsyncDefaultAzureCredential(authority=authority)

    # Fall back to default chained credentials (managed identity, CLI, etc.)
    return AsyncDefaultAzureCredential(authority=authority)


def _resolve_foundry_scope(
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
) -> str:
    scope = str(
        foundry_settings.get("foundry_scope")
        or global_settings.get("azure_ai_foundry_scope")
        or ""
    ).strip()
    if scope:
        return scope

    cloud_value = (
        foundry_settings.get("cloud")
        or global_settings.get("azure_ai_foundry_cloud")
        or ""
    )
    normalized = str(cloud_value).strip().lower()
    if normalized in ("usgov", "usgovernment", "gcc"):
        return "https://ai.azure.us/.default"
    return "https://ai.azure.com/.default"


def _resolve_secret_value(value: str) -> str:
    if validate_secret_name_dynamic(value):
        resolved = retrieve_secret_from_key_vault_by_full_name(value)
        if not resolved:
            raise FoundryAgentInvocationError(
                f"Unable to resolve Key Vault secret '{value}' for Foundry credentials."
            )
        return resolved
    return value


def _authority_from_cloud(cloud_value: Optional[str]) -> str:
    if not cloud_value:
        return AzureAuthorityHosts.AZURE_PUBLIC_CLOUD

    normalized = cloud_value.lower()
    if normalized in ("usgov", "usgovernment", "gcc"):
        return AzureAuthorityHosts.AZURE_GOVERNMENT
    return AzureAuthorityHosts.AZURE_PUBLIC_CLOUD


def _extract_message_text(message: ChatMessageContent) -> str:
    if message.content:
        if isinstance(message.content, str):
            return message.content
        try:
            return "".join(str(chunk) for chunk in message.content)
        except TypeError:
            return str(message.content)
    return ""


def _extract_citations(message: ChatMessageContent) -> List[Dict[str, Any]]:
    metadata = message.metadata or {}
    citations = metadata.get("citations")
    if isinstance(citations, list):
        return [c for c in citations if isinstance(c, dict)]
    items = getattr(message, "items", None)
    if isinstance(items, list):
        extracted: List[Dict[str, Any]] = []
        for item in items:
            content_type = getattr(item, "content_type", None)
            if content_type != "annotation":
                continue
            url = getattr(item, "url", None)
            title = getattr(item, "title", None)
            quote = getattr(item, "quote", None)
            if not url:
                continue
            extracted.append(
                {
                    "url": url,
                    "title": title,
                    "quote": quote,
                    "citation_type": getattr(item, "citation_type", None),
                }
            )
        if extracted:
            return extracted
    return []


def _build_new_foundry_request_payload(
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    stream: bool = False,
    max_output_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    input_items: List[Dict[str, Any]] = []
    for message in message_history:
        role_value = getattr(message, "role", "user")
        role = str(role_value).strip().lower() or "user"
        if role not in {"system", "user", "assistant", "developer"}:
            role = "user"

        text = _extract_message_text(message).strip()
        if not text:
            continue

        input_items.append(
            {
                "type": "message",
                "role": role,
                "content": [
                    {
                        "type": "input_text",
                        "text": text,
                    }
                ],
            }
        )

    if not input_items:
        raise FoundryAgentInvocationError(
            "New Foundry invocation requires at least one message."
        )

    payload: Dict[str, Any] = {
        "input": input_items,
        "stream": stream,
    }
    normalized_metadata = {
        key: str(value)
        for key, value in (metadata or {}).items()
        if value is not None
    }
    if normalized_metadata:
        payload["metadata"] = normalized_metadata
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    return payload


def _parse_json_response(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise FoundryAgentInvocationError(
            f"Foundry endpoint returned non-JSON response: {response.text[:500]}"
        ) from exc
    if not isinstance(payload, dict):
        raise FoundryAgentInvocationError("Foundry endpoint returned an unexpected payload.")
    return payload


def _try_parse_json_response(response: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _build_http_error_message(
    operation: str,
    response: requests.Response,
    payload: Dict[str, Any],
) -> str:
    details = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(details, dict):
        detail_text = details.get("message") or json.dumps(details)
    else:
        detail_text = details or response.text[:500]
    return f"Failed {operation}: HTTP {response.status_code} {detail_text}"


def _extract_new_foundry_response_text(payload: Dict[str, Any]) -> str:
    texts: List[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for content_item in item.get("content") or []:
            if not isinstance(content_item, dict):
                continue
            block_type = content_item.get("type")
            if block_type in {"output_text", "text", "input_text"}:
                text = content_item.get("text") or content_item.get("value")
                if isinstance(text, str) and text:
                    texts.append(text)
    if texts:
        return "\n".join(texts).strip()

    fallback = payload.get("output_text") or payload.get("text")
    if isinstance(fallback, str):
        return fallback.strip()
    return ""


def _extract_new_foundry_response_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    result_metadata = payload.get("metadata") or {}
    if not isinstance(result_metadata, dict):
        result_metadata = {}
    else:
        result_metadata = dict(result_metadata)

    usage = _normalize_usage_payload(payload.get("usage"))
    if usage:
        result_metadata["usage"] = usage

    conversation = payload.get("conversation")
    if isinstance(conversation, dict):
        result_metadata["conversation"] = conversation

    response_id = payload.get("id")
    if response_id:
        result_metadata["response_id"] = response_id

    return result_metadata


def _build_new_foundry_invocation_result(
    *,
    response_payload: Dict[str, Any],
    application_name: str,
) -> FoundryAgentInvocationResult:
    text = _extract_new_foundry_response_text(response_payload)
    if not text:
        raise FoundryAgentInvocationError(
            "New Foundry application returned no assistant content."
        )

    citations = _extract_new_foundry_citations(response_payload)
    model_value = str(response_payload.get("model") or application_name)
    result_metadata = _extract_new_foundry_response_metadata(response_payload)
    return FoundryAgentInvocationResult(
        message=text,
        model=model_value,
        citations=citations,
        metadata=result_metadata,
    )


def _extract_new_foundry_citations(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content") or []:
            if not isinstance(content_item, dict):
                continue
            for annotation in content_item.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                url = annotation.get("url") or annotation.get("uri")
                title = annotation.get("title") or annotation.get("name")
                quote_text = annotation.get("quote") or annotation.get("text")
                if url or title or quote_text:
                    citations.append(
                        {
                            "url": url,
                            "title": title,
                            "quote": quote_text,
                            "citation_type": annotation.get("type") or annotation.get("annotation_type"),
                        }
                    )
    return citations


def _extract_nested_version_value(version_source: Any) -> str:
    if isinstance(version_source, dict):
        latest = version_source.get("latest")
        if isinstance(latest, dict):
            latest_version = str(latest.get("version") or "").strip()
            if latest_version:
                return latest_version

        direct_version = str(version_source.get("version") or "").strip()
        if direct_version:
            return direct_version

        items = version_source.get("items") or version_source.get("data") or version_source.get("value")
        if isinstance(items, list) and items:
            for item in items:
                item_version = _extract_nested_version_value(item)
                if item_version:
                    return item_version
    elif isinstance(version_source, list):
        for item in version_source:
            item_version = _extract_nested_version_value(item)
            if item_version:
                return item_version
    return ""


def _extract_new_foundry_api_version(item: Dict[str, Any], properties: Dict[str, Any]) -> str:
    return str(
        item.get("responses_api_version")
        or item.get("response_api_version")
        or item.get("openai_api_version")
        or item.get("api_version")
        or properties.get("responses_api_version")
        or properties.get("response_api_version")
        or properties.get("openai_api_version")
        or properties.get("api_version")
        or ""
    ).strip()


def _normalize_usage_payload(usage_payload: Any) -> Optional[Dict[str, int]]:
    if isinstance(usage_payload, dict):
        prompt_tokens = int(usage_payload.get("input_tokens") or usage_payload.get("prompt_tokens") or 0)
        completion_tokens = int(usage_payload.get("output_tokens") or usage_payload.get("completion_tokens") or 0)
        total_tokens = int(usage_payload.get("total_tokens") or (prompt_tokens + completion_tokens))
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    return None


def _iter_sse_events(response: requests.Response):
    event_name: Optional[str] = None
    data_lines: List[str] = []

    for raw_line in response.iter_lines(decode_unicode=True):
        line = raw_line if isinstance(raw_line, str) else ""
        if line == "":
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        yield event_name, "\n".join(data_lines)


def _parse_sse_json_payload(event_name: Optional[str], event_data: str) -> Dict[str, Any]:
    try:
        payload = json.loads(event_data)
    except ValueError as exc:
        raise FoundryAgentInvocationError(
            f"New Foundry stream returned invalid JSON payload: {event_data[:500]}"
        ) from exc

    if not isinstance(payload, dict):
        raise FoundryAgentInvocationError("New Foundry stream returned an unexpected payload.")
    if event_name and not payload.get("type"):
        payload["type"] = event_name
    return payload


def _extract_new_foundry_event_error(event_payload: Dict[str, Any]) -> str:
    error_payload = event_payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message") or json.dumps(error_payload)
        return f"New Foundry stream failed: {message}"
    if isinstance(error_payload, str) and error_payload.strip():
        return f"New Foundry stream failed: {error_payload.strip()}"
    return f"New Foundry stream failed: {json.dumps(event_payload, default=str)[:500]}"


def _extract_new_foundry_stream_delta(event_payload: Dict[str, Any]) -> str:
    event_type = str(event_payload.get("type") or "").strip()
    if event_type != "response.output_text.delta":
        return ""
    delta_text = event_payload.get("delta")
    return delta_text if isinstance(delta_text, str) else ""


def _extract_response_payload_from_stream_event(event_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    response_payload = event_payload.get("response")
    if isinstance(response_payload, dict):
        return response_payload
    if isinstance(event_payload.get("output"), list):
        return event_payload
    return None


def _extract_new_foundry_annotation(annotation: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(annotation, dict):
        return None
    url = annotation.get("url") or annotation.get("uri")
    title = annotation.get("title") or annotation.get("name")
    quote_text = annotation.get("quote") or annotation.get("text")
    if not (url or title or quote_text):
        return None
    return {
        "url": url,
        "title": title,
        "quote": quote_text,
        "citation_type": annotation.get("type") or annotation.get("annotation_type"),
    }


def _merge_citations(existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = list(existing)
    seen = {json.dumps(item, sort_keys=True, default=str) for item in existing}
    for item in incoming:
        key = json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged


def _update_new_foundry_stream_state(
    *,
    state: NewFoundryStreamState,
    event_payload: Dict[str, Any],
    application_name: str,
) -> None:
    response_payload = _extract_response_payload_from_stream_event(event_payload)
    if response_payload:
        state.model = str(response_payload.get("model") or state.model or application_name)
        state.metadata.update(_extract_new_foundry_response_metadata(response_payload))
        citations = _extract_new_foundry_citations(response_payload)
        if citations:
            state.citations = _merge_citations(state.citations, citations)
        fallback_text = _extract_new_foundry_response_text(response_payload)
        if fallback_text and not state.text_parts:
            state.text_parts = [fallback_text]
        return

    event_type = str(event_payload.get("type") or "").strip()
    if event_type == "response.output_text.annotation.added":
        annotation = _extract_new_foundry_annotation(event_payload.get("annotation"))
        if annotation:
            state.citations = _merge_citations(state.citations, [annotation])
        return

    if event_type in {"response.output_item.added", "response.output_item.done"}:
        item = event_payload.get("item")
        if isinstance(item, dict):
            item_citations = _extract_new_foundry_citations({"output": [item]})
            if item_citations:
                state.citations = _merge_citations(state.citations, item_citations)


def _extract_new_foundry_stream_text(state: NewFoundryStreamState) -> str:
    text = "".join(state.text_parts).strip()
    if text:
        return text
    metadata_text = state.metadata.get("output_text")
    return metadata_text.strip() if isinstance(metadata_text, str) else ""


def _build_new_foundry_stream_metadata(
    state: NewFoundryStreamState,
    application_name: str,
) -> Dict[str, Any]:
    metadata = dict(state.metadata)
    metadata["citations"] = state.citations
    metadata["model"] = state.model or application_name
    return metadata


async def _list_foundry_agents_async(
    *,
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any]
) -> List[Dict[str, Any]]:
    endpoint = _resolve_endpoint(foundry_settings, global_settings)
    api_version = foundry_settings.get("api_version") or global_settings.get(
        "azure_ai_foundry_api_version"
    )
    credential = _build_async_credential(foundry_settings, global_settings)
    client = AzureAIAgent.create_client(
        credential=credential,
        endpoint=endpoint,
        api_version=api_version,
    )

    async def resolve_agent_list():
        agents_client = getattr(client, "agents", None)
        if not agents_client:
            raise FoundryAgentInvocationError("Foundry agents client not available.")
        if hasattr(agents_client, "list_agents"):
            return agents_client.list_agents()
        if hasattr(agents_client, "list"):
            return agents_client.list()
        raise FoundryAgentInvocationError("Foundry agent list API not available.")

    try:
        result = await resolve_agent_list()
        if hasattr(result, "__aiter__"):
            items = []
            async for item in result:
                items.append(item)
        elif isinstance(result, dict):
            items = result.get("value") or result.get("data") or []
        elif isinstance(result, list):
            items = result
        else:
            items = getattr(result, "value", None) or getattr(result, "data", None) or []

        normalized: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict):
                normalized.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "display_name": item.get("display_name") or item.get("name"),
                    "description": item.get("description") or "",
                })
                continue
            normalized.append({
                "id": getattr(item, "id", None),
                "name": getattr(item, "name", None),
                "display_name": getattr(item, "display_name", None) or getattr(item, "name", None),
                "description": getattr(item, "description", None) or "",
            })
        return normalized
    finally:
        try:
            await client.close()
        finally:
            await credential.close()


def list_foundry_agents_from_endpoint(foundry_settings: Dict[str, Any], global_settings: Dict[str, Any]):
    """Synchronously list Foundry agents using the provided endpoint configuration."""
    return asyncio.run(
        _list_foundry_agents_async(
            foundry_settings=foundry_settings,
            global_settings=global_settings,
        )
    )


async def _list_new_foundry_agents_async(
    *,
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """List the latest new Foundry project agents/applications via the project REST API."""

    endpoint = _resolve_endpoint(foundry_settings, global_settings)
    api_version = (
        foundry_settings.get("activity_api_version")
        or foundry_settings.get("api_version")
        or foundry_settings.get("responses_api_version")
        or global_settings.get("azure_ai_foundry_api_version")
        or "2025-11-15-preview"
    )
    credential = _build_async_credential(foundry_settings, global_settings)
    scope = _resolve_foundry_scope(foundry_settings, global_settings)
    token = await credential.get_token(scope)
    url = f"{endpoint.rstrip('/')}/agents"
    headers = {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }

    try:
        response = await asyncio.to_thread(
            requests.get,
            url,
            params={"api-version": api_version},
            headers=headers,
            timeout=30,
        )
        payload = _parse_json_response(response)
        if response.status_code >= 400:
            raise FoundryAgentInvocationError(
                _build_http_error_message("new Foundry agent list", response, payload)
            )

        items = payload.get("value") or payload.get("data") or payload.get("items") or []
        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            version = str(
                item.get("version")
                or item.get("latest_version")
                or item.get("latestVersion")
                or item.get("agent_version")
                or item.get("agentVersion")
                or properties.get("version")
                or properties.get("latest_version")
                or properties.get("latestVersion")
                or properties.get("agent_version")
                or properties.get("agentVersion")
                or _extract_nested_version_value(item.get("versions"))
                or _extract_nested_version_value(properties.get("versions"))
                or ""
            ).strip()
            name = str(
                item.get("name")
                or item.get("agent_name")
                or item.get("agentName")
                or properties.get("name")
                or properties.get("agent_name")
                or properties.get("agentName")
                or ""
            ).strip()
            if not name:
                continue

            application_id = f"{name}:{version}" if version else name
            display_name = str(
                item.get("display_name")
                or item.get("displayName")
                or properties.get("display_name")
                or properties.get("displayName")
                or name
            ).strip() or name
            description = str(
                item.get("description")
                or properties.get("description")
                or ""
            ).strip()
            responses_api_version = _extract_new_foundry_api_version(item, properties)

            normalized.append(
                {
                    "id": application_id,
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                    "application_id": application_id,
                    "application_name": name,
                    "application_version": version,
                    "responses_api_version": responses_api_version,
                }
            )

        return normalized
    finally:
        await credential.close()


def list_new_foundry_agents_from_endpoint(foundry_settings: Dict[str, Any], global_settings: Dict[str, Any]):
    """Synchronously list new Foundry agents/applications using the project REST API."""
    return asyncio.run(
        _list_new_foundry_agents_async(
            foundry_settings=foundry_settings,
            global_settings=global_settings,
        )
    )

def resolve_foundry_project_base(endpoint, project_name):
    if not endpoint:
        raise ValueError("Missing Foundry endpoint")
    base = endpoint.rstrip("/")
    if "/api/projects/" in base:
        return base
    if project_name:
        return f"{base}/api/projects/{project_name}"
    raise ValueError("Foundry project name is required when endpoint does not include /api/projects/.")

def resolve_foundry_project_api_version(api_version):
    version = (api_version or "").strip()
    if version and version.startswith("v"):
        return version
    return "v1"

def resolve_authority(auth_settings):
    management_cloud = (auth_settings.get("management_cloud") or "public").lower()
    if management_cloud == "government":
        return "https://login.microsoftonline.us"
    if management_cloud == "custom":
        custom_authority = auth_settings.get("custom_authority") or ""
        return custom_authority.strip() or None
    return None

def build_project_credential(auth_settings):
    """Build a synchronous credential for sync discovery routes and SDK clients."""

    auth_type = (auth_settings.get("type") or "managed_identity").lower()
    if auth_type == "service_principal":
        authority_override = resolve_authority(auth_settings)
        return SyncClientSecretCredential(
            tenant_id=auth_settings.get("tenant_id"),
            client_id=auth_settings.get("client_id"),
            client_secret=auth_settings.get("client_secret"),
            authority=authority_override,
        )
    if auth_type == "api_key":
        raise ValueError("API key auth is not supported for Foundry project discovery.")
    managed_identity_client_id = auth_settings.get("managed_identity_client_id") or None
    return SyncDefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)

def list_new_foundry_agents_from_project(endpoint_cfg):
    connection = endpoint_cfg.get("connection", {}) or {}
    auth = endpoint_cfg.get("auth", {}) or {}
    foundry_settings = {
        "endpoint": connection.get("endpoint"),
        "project_name": connection.get("project_name") or "",
        "activity_api_version": resolve_foundry_project_api_version(
            connection.get("project_api_version") or connection.get("api_version") or "v1"
        ),
        "authentication_type": auth.get("type") or "managed_identity",
        "managed_identity_type": auth.get("managed_identity_type") or "system_assigned",
        "managed_identity_client_id": auth.get("managed_identity_client_id") or "",
        "tenant_id": auth.get("tenant_id") or "",
        "client_id": auth.get("client_id") or "",
        "client_secret": auth.get("client_secret") or "",
        "cloud": auth.get("management_cloud") or "",
        "authority": auth.get("custom_authority") or "",
    }
    return list_new_foundry_agents_from_endpoint(foundry_settings, {})
