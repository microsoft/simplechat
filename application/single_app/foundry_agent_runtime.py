# foundry_agent_runtime.py
"""Azure AI Foundry agent execution helpers."""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from azure.identity import AzureAuthorityHosts
from azure.identity.aio import (  # type: ignore
    ClientSecretCredential,
    DefaultAzureCredential,
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


def _resolve_endpoint(foundry_settings: Dict[str, Any], global_settings: Dict[str, Any]) -> str:
    endpoint = (
        foundry_settings.get("endpoint")
        or global_settings.get("azure_ai_foundry_endpoint")
        or os.getenv("AZURE_AI_AGENT_ENDPOINT")
    )
    if endpoint:
        return endpoint.rstrip("/")

    raise FoundryAgentInvocationError(
        "Azure AI Foundry endpoint is not configured. Provide an endpoint in the agent's other_settings.azure_ai_foundry or global settings."
    )


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
        return ClientSecretCredential(
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
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=resolved_secret,
            authority=authority,
        )

    if auth_type == "managed_identity":
        if managed_identity_type == "user_assigned" and managed_identity_client_id:
            return DefaultAzureCredential(
                authority=authority,
                managed_identity_client_id=managed_identity_client_id,
            )
        return DefaultAzureCredential(authority=authority)

    # Fall back to default chained credentials (managed identity, CLI, etc.)
    return DefaultAzureCredential(authority=authority)


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
