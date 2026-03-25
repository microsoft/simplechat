# foundry_agent_runtime.py
"""Azure AI Foundry agent execution helpers."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
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


class FoundryAgentInvocationError(RuntimeError):
    """Raised when the Foundry agent invocation cannot be completed."""


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
            )
        )
        self.last_run_citations = result.citations
        self.last_run_model = result.model
        return result.message

    async def invoke_stream(
        self,
        messages: Iterable[ChatMessageContent],
    ) -> AsyncIterator[str]:
        """Yield a single final chunk for stream mode compatibility."""

        result = await execute_new_foundry_agent(
            foundry_settings=self._new_foundry_settings,
            global_settings=self._global_settings,
            message_history=list(messages),
            metadata={},
        )
        self.last_run_citations = result.citations
        self.last_run_model = result.model
        if result.message:
            yield result.message


async def execute_foundry_agent(
    *,
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
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

    try:
        definition = await client.agents.get_agent(agent_id)
        azure_agent = AzureAIAgent(client=client, definition=definition)
        responses = []
        async for response in azure_agent.invoke(
            messages=message_history,
            metadata={k: str(v) for k, v in metadata.items() if v is not None},
        ):
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
    payload = _build_new_foundry_request_payload(message_history, metadata)
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

        text = _extract_new_foundry_response_text(response_payload)
        if not text:
            raise FoundryAgentInvocationError(
                "New Foundry application returned no assistant content."
            )

        citations = _extract_new_foundry_citations(response_payload)
        model_value = str(response_payload.get("model") or application_name)
        result_metadata = response_payload.get("metadata") or {}
        if isinstance(response_payload.get("conversation"), dict):
            result_metadata = dict(result_metadata)
            result_metadata["conversation"] = response_payload.get("conversation")
        if response_payload.get("id"):
            result_metadata = dict(result_metadata)
            result_metadata["response_id"] = response_payload.get("id")

        log_event(
            "[NewFoundryAgent] Invocation complete",
            extra={
                "application_name": application_name,
                "endpoint": endpoint,
                "model": model_value,
                "message_length": len(text),
            },
        )

        return FoundryAgentInvocationResult(
            message=text,
            model=model_value,
            citations=citations,
            metadata=result_metadata,
        )
    finally:
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
        "stream": False,
    }
    normalized_metadata = {
        key: str(value)
        for key, value in (metadata or {}).items()
        if value is not None
    }
    if normalized_metadata:
        payload["metadata"] = normalized_metadata
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
            name = str(
                item.get("name")
                or item.get("agent_name")
                or item.get("agentName")
                or properties.get("name")
                or properties.get("agent_name")
                or properties.get("agentName")
                or ""
            ).strip()
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

            normalized.append(
                {
                    "id": application_id,
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                    "application_id": application_id,
                    "application_name": name,
                    "application_version": version,
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
    try:
        from azure.ai.projects import AIProjectClient
    except ImportError as exc:
        raise ImportError(
            "azure-ai-projects is required for new Foundry application discovery."
        ) from exc

    connection = endpoint_cfg.get("connection", {}) or {}
    auth = endpoint_cfg.get("auth", {}) or {}
    project_endpoint = resolve_foundry_project_base(
        connection.get("endpoint"),
        connection.get("project_name"),
    )
    api_version = resolve_foundry_project_api_version(
        connection.get("project_api_version") or connection.get("api_version") or "v1"
    )
    credential = build_project_credential(auth)
    try:
        with AIProjectClient(
            endpoint=project_endpoint,
            credential=credential,
            api_version=api_version,
        ) as project_client:
            items = list(project_client.agents.list_agents())
    finally:
        credential.close()

    normalized = []
    for item in items:
        item_id = getattr(item, "id", None) or getattr(item, "agent_id", None)
        name = getattr(item, "name", None) or getattr(item, "agent_name", None)
        display_name = getattr(item, "display_name", None) or name
        description = getattr(item, "description", None) or ""
        version = str(
            getattr(item, "version", None)
            or getattr(item, "agent_version", None)
            or ""
        ).strip()
        if not name:
            continue
        application_id = f"{name}:{version}" if version else (item_id or name)
        normalized.append(
            {
                "id": application_id,
                "name": name,
                "display_name": display_name,
                "description": description,
                "application_id": application_id,
                "application_name": name,
                "application_version": version,
            }
        )
    return normalized
