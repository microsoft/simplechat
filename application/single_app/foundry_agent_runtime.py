# foundry_agent_runtime.py
"""Azure AI Foundry agent execution helpers."""

import asyncio
import base64
from binascii import Error as BinasciiError
import json
import logging
import mimetypes
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests
from azure.core.credentials import AccessToken
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
from functions_authentication import get_valid_access_token_for_plugins
from functions_debug import debug_print
from functions_keyvault import (
    retrieve_secret_from_key_vault_by_full_name,
    validate_secret_name_dynamic,
)

_logger = logging.getLogger("foundry_agent_runtime")

FOUNDRY_METADATA_VALUE_MAX_LENGTH = 512
FOUNDRY_INTERNAL_METADATA_KEYS = {
    "active_group_ids",
    "active_public_workspace_ids",
    "selected_document_ids",
}
FOUNDRY_FILE_SEARCHABLE_CONTEXT_MAX_CHARS = 6000
FOUNDRY_FILE_SEARCHABLE_CONTEXT_HEADER = "Attached file searchable summary"
FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE = (
    "Foundry agents and workflows require delegated access to Azure AI Foundry. "
    "Sign in or grant Foundry access, then try again."
)


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


class FoundryAgentUserAuthenticationRequired(FoundryAgentInvocationError):
    """Raised when delegated Foundry access needs user consent or sign-in."""

    def __init__(self, message: str, auth_response: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.auth_response = auth_response or {}


class DelegatedUserAccessTokenCredential:
    """Async credential adapter for a delegated user bearer token."""

    def __init__(self, token: str):
        self._token = token
        self._expires_on = _resolve_jwt_expires_on(token)

    async def get_token(self, *scopes, **kwargs):
        return AccessToken(self._token, self._expires_on)

    async def close(self):
        return None


def _resolve_jwt_expires_on(token: str) -> int:
    token_parts = str(token or "").split(".")
    if len(token_parts) >= 2:
        try:
            payload = token_parts[1]
            payload += "=" * (-len(payload) % 4)
            decoded_payload = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
            expires_on = int(decoded_payload.get("exp", 0))
            if expires_on > int(time.time()):
                return expires_on
        except (BinasciiError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            pass
    return int(time.time()) + 300


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
        self.last_run_metadata: Dict[str, Any] = {}
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
        self.last_run_metadata = result.metadata
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
        self.last_run_metadata = result.metadata
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
        self.last_run_metadata: Dict[str, Any] = {}
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
        self.last_run_metadata = result.metadata
        return result.message

    async def invoke_stream(
        self,
        messages: Iterable[ChatMessageContent],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[FoundryAgentStreamMessage]:
        """Yield incremental content for the new Foundry application runtime."""

        async for stream_message in execute_new_foundry_agent_stream(
            foundry_settings=self._new_foundry_settings,
            global_settings=self._global_settings,
            message_history=list(messages),
            metadata=metadata or {},
            max_completion_tokens=self.max_completion_tokens,
        ):
            if stream_message.metadata:
                self.last_run_metadata = stream_message.metadata
                citations = stream_message.metadata.get("citations")
                if isinstance(citations, list):
                    self.last_run_citations = citations
                model_value = stream_message.metadata.get("model")
                if isinstance(model_value, str) and model_value.strip():
                    self.last_run_model = model_value.strip()
            yield stream_message


class AzureAIFoundryWorkflowAgent:
    """Wrapper for Foundry workflow agents invoked through agent_reference."""

    agent_type = "foundry_workflow"

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
        self.last_run_metadata: Dict[str, Any] = {}
        self._workflow_settings = (
            (agent_config.get("other_settings") or {}).get("foundry_workflow") or {}
        )
        self._global_settings = settings or {}

    def _workflow_name(self) -> str:
        return _resolve_foundry_workflow_name(self._workflow_settings, self.name)

    def invoke(
        self,
        agent_message_history: Iterable[ChatMessageContent],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Synchronously invoke the workflow by aggregating the streaming response."""

        metadata = metadata or {}
        history = list(agent_message_history)
        workflow_name = self._workflow_name()
        debug_print(
            f"[FoundryWorkflowAgent] Invoking workflow '{workflow_name}' with {len(history)} messages"
        )

        result = asyncio.run(
            execute_foundry_workflow_agent(
                workflow_settings=self._workflow_settings,
                global_settings=self._global_settings,
                message_history=history,
                metadata=metadata,
                workflow_name=workflow_name,
                max_completion_tokens=self.max_completion_tokens,
            )
        )
        self.last_run_citations = result.citations
        self.last_run_model = result.model
        self.last_run_metadata = result.metadata
        return result.message

    async def invoke_stream(
        self,
        messages: Iterable[ChatMessageContent],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[FoundryAgentStreamMessage]:
        """Yield incremental content from a Foundry workflow Responses stream."""

        workflow_name = self._workflow_name()
        async for stream_message in execute_foundry_workflow_agent_stream(
            workflow_settings=self._workflow_settings,
            global_settings=self._global_settings,
            message_history=list(messages),
            metadata=metadata or {},
            workflow_name=workflow_name,
            max_completion_tokens=self.max_completion_tokens,
        ):
            if stream_message.metadata:
                self.last_run_metadata = stream_message.metadata
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
    url = (
        f"{endpoint.rstrip('/')}/applications/{quote(application_name, safe='')}/"
        "protocols/openai/responses"
    )
    file_inputs, file_input_metadata = _collect_foundry_response_file_inputs(
        foundry_settings,
        metadata,
    )
    payload = _build_new_foundry_request_payload(
        message_history,
        metadata,
        stream=False,
        max_output_tokens=_normalize_max_completion_tokens(max_completion_tokens),
        file_inputs=file_inputs,
    )
    if file_input_metadata:
        payload.setdefault("metadata", {})["attached_file_count"] = str(len(file_input_metadata))
    headers = await _build_foundry_rest_headers(
        foundry_settings,
        global_settings,
        credential,
    )

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
    url = (
        f"{endpoint.rstrip('/')}/applications/{quote(application_name, safe='')}/"
        "protocols/openai/responses"
    )
    debug_print(f"Invoking new Foundry application '{application_name}' at {endpoint} with streaming to url {url} with api-version {responses_api_version}")
    file_inputs, file_input_metadata = _collect_foundry_response_file_inputs(
        foundry_settings,
        metadata,
    )
    payload = _build_new_foundry_request_payload(
        message_history,
        metadata,
        stream=True,
        max_output_tokens=_normalize_max_completion_tokens(max_completion_tokens),
        file_inputs=file_inputs,
    )
    if file_input_metadata:
        payload.setdefault("metadata", {})["attached_file_count"] = str(len(file_input_metadata))
    headers = await _build_foundry_rest_headers(
        foundry_settings,
        global_settings,
        credential,
    )
    response_params: Dict[str, str] = {}
    conversation_params: Dict[str, str] = {}
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


async def execute_foundry_workflow_agent(
    *,
    workflow_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    workflow_name: Optional[str] = None,
    max_completion_tokens: Optional[int] = None,
) -> FoundryAgentInvocationResult:
    """Invoke a Foundry workflow by consuming its streaming response."""

    resolved_workflow_name = _resolve_foundry_workflow_name(
        workflow_settings,
        workflow_name,
    )
    text_parts: List[str] = []
    final_metadata: Dict[str, Any] = {}

    async for stream_message in execute_foundry_workflow_agent_stream(
        workflow_settings=workflow_settings,
        global_settings=global_settings,
        message_history=message_history,
        metadata=metadata,
        workflow_name=resolved_workflow_name,
        max_completion_tokens=max_completion_tokens,
    ):
        if stream_message.content:
            text_parts.append(stream_message.content)
        if stream_message.metadata:
            final_metadata = stream_message.metadata

    text = "".join(text_parts).strip()
    if not text:
        text = str(final_metadata.get("output_text") or "").strip()
    if not text:
        raise FoundryAgentInvocationError("Foundry workflow returned no assistant content.")

    citations = final_metadata.get("citations")
    return FoundryAgentInvocationResult(
        message=text,
        model=str(final_metadata.get("model") or resolved_workflow_name),
        citations=citations if isinstance(citations, list) else [],
        metadata=final_metadata,
    )


async def execute_foundry_workflow_agent_stream(
    *,
    workflow_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    workflow_name: Optional[str] = None,
    max_completion_tokens: Optional[int] = None,
) -> AsyncIterator[FoundryAgentStreamMessage]:
    """Stream a Foundry workflow response through project-level OpenAI Responses."""

    resolved_workflow_name = _resolve_foundry_workflow_name(
        workflow_settings,
        workflow_name,
    )
    endpoint = _resolve_endpoint(workflow_settings, global_settings)
    responses_api_version = (
        workflow_settings.get("responses_api_version")
        or workflow_settings.get("api_version")
        or global_settings.get("azure_ai_foundry_api_version")
    )
    if not responses_api_version:
        raise FoundryAgentInvocationError(
            "Foundry workflow agents require a responses_api_version or api_version setting."
        )

    credential = _build_async_credential(workflow_settings, global_settings)
    configured_responses_api_version = str(responses_api_version).strip()
    responses_api_version = _normalize_foundry_workflow_rest_protocol(
        configured_responses_api_version
    )
    if responses_api_version != configured_responses_api_version:
        debug_print(
            f"[FoundryWorkflowAgent] Using OpenAI-compatible workflow REST protocol '{responses_api_version}' for configured value '{configured_responses_api_version}'"
        )
    endpoint_candidates = _build_foundry_workflow_endpoint_candidates(
        endpoint,
        workflow_settings,
        responses_api_version=responses_api_version,
    )
    file_inputs, file_input_metadata = _collect_foundry_response_file_inputs(
        workflow_settings,
        metadata,
    )
    payload = _build_foundry_workflow_request_payload(
        message_history,
        metadata,
        workflow_settings=workflow_settings,
        workflow_name=resolved_workflow_name,
        stream=True,
        max_output_tokens=_normalize_max_completion_tokens(max_completion_tokens),
        max_context_chars=_normalize_max_context_chars(
            workflow_settings.get("max_context_chars")
        ),
        include_document_context=workflow_settings.get("include_document_context", True),
        file_inputs=file_inputs,
    )
    if file_input_metadata:
        payload.setdefault("metadata", {})["attached_file_count"] = str(len(file_input_metadata))
    headers = await _build_foundry_rest_headers(
        workflow_settings,
        global_settings,
        credential,
    )
    response: Optional[requests.Response] = None
    foundry_conversation_id: Optional[str] = None
    foundry_conversation_url: Optional[str] = None
    state = NewFoundryStreamState()

    try:
        response_params = _build_foundry_workflow_request_params(responses_api_version)
        conversation_params = _build_foundry_workflow_conversation_params(responses_api_version)
        for index, candidate in enumerate(endpoint_candidates):
            url = candidate["responses_url"]
            foundry_conversation_url = candidate["conversations_url"]
            foundry_conversation_id = _create_foundry_workflow_conversation(
                foundry_conversation_url,
                params=conversation_params,
                headers=headers,
            )
            payload["conversation"] = foundry_conversation_id
            debug_print(
                f"[FoundryWorkflowAgent] Invoking workflow '{resolved_workflow_name}' at {url} with Foundry conversation {foundry_conversation_id}"
            )
            response = requests.post(
                url,
                params=response_params,
                headers=headers,
                json=payload,
                timeout=(30, 120),
                stream=True,
            )
            should_try_next_path = (
                not _has_explicit_workflow_responses_path(workflow_settings)
                and response.status_code in {404, 405}
                and index < len(endpoint_candidates) - 1
            )
            if should_try_next_path:
                response.close()
                response = None
                _delete_foundry_workflow_conversation(
                    foundry_conversation_url,
                    foundry_conversation_id,
                    params=conversation_params,
                    headers=headers,
                )
                foundry_conversation_id = None
                foundry_conversation_url = None
                payload.pop("conversation", None)
                continue
            break

        if response is None:
            raise FoundryAgentInvocationError(
                "Unable to open a Foundry workflow Responses stream."
            )

        if response.status_code >= 400:
            response_payload = _try_parse_json_response(response) or {}
            raise FoundryAgentInvocationError(
                _build_http_error_message("Foundry workflow stream", response, response_payload)
            )

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/event-stream" not in content_type:
            response_payload = _parse_json_response(response)
            result = _build_foundry_workflow_invocation_result(
                response_payload=response_payload,
                workflow_name=resolved_workflow_name,
            )
            result.metadata["foundry_conversation_id"] = foundry_conversation_id
            if result.message:
                yield FoundryAgentStreamMessage(content=result.message)
            yield FoundryAgentStreamMessage(
                metadata={
                    **result.metadata,
                    "citations": result.citations,
                    "model": result.model,
                    "workflow_name": resolved_workflow_name,
                    "foundry_conversation_id": foundry_conversation_id,
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

            _update_new_foundry_stream_state(
                state=state,
                event_payload=event_payload,
                application_name=resolved_workflow_name,
            )
            _record_foundry_workflow_event(state, event_type, event_payload)

        final_text = _extract_new_foundry_stream_text(state)
        if final_text:
            state.text_parts = [final_text]
            yield FoundryAgentStreamMessage(content=final_text)

        yield FoundryAgentStreamMessage(
            metadata=_build_foundry_workflow_stream_metadata(
                state,
                resolved_workflow_name,
                payload,
                foundry_conversation_id=foundry_conversation_id,
            )
        )
    finally:
        if response is not None:
            response.close()
        if foundry_conversation_url and foundry_conversation_id:
            _delete_foundry_workflow_conversation(
                foundry_conversation_url,
                foundry_conversation_id,
                params=conversation_params,
                headers=headers,
            )
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


def _resolve_foundry_workflow_name(
    workflow_settings: Dict[str, Any],
    fallback_name: Optional[str] = None,
) -> str:
    workflow_name = str(
        workflow_settings.get("workflow_name")
        or workflow_settings.get("agent_name")
        or fallback_name
        or ""
    ).strip()
    if not workflow_name:
        raise FoundryAgentInvocationError(
            "Foundry workflow agents require workflow_name in other_settings.foundry_workflow."
        )
    return workflow_name


def _build_foundry_workflow_agent_reference(
    workflow_settings: Dict[str, Any],
    workflow_name: str,
) -> Dict[str, Any]:
    allowed_reference_fields = {
        "type",
        "name",
        "id",
        "application_id",
        "application_version",
    }
    configured_reference = workflow_settings.get("agent_reference")
    if isinstance(configured_reference, dict):
        reference = {
            key: value
            for key, value in configured_reference.items()
            if key in allowed_reference_fields and value not in (None, "")
        }
    else:
        reference = {}

    reference["type"] = str(reference.get("type") or "agent_reference").strip() or "agent_reference"
    reference.setdefault("name", workflow_name)

    agent_id = str(
        workflow_settings.get("workflow_agent_id")
        or workflow_settings.get("agent_id")
        or reference.get("id")
        or ""
    ).strip()
    if agent_id:
        reference["id"] = agent_id

    application_id = str(
        workflow_settings.get("application_id")
        or reference.get("application_id")
        or ""
    ).strip()
    if application_id:
        reference["application_id"] = application_id

    application_version = str(
        workflow_settings.get("application_version")
        or reference.get("application_version")
        or ""
    ).strip()
    if application_version:
        reference["application_version"] = application_version

    return reference


def _normalize_max_context_chars(value: Any) -> Optional[int]:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _has_explicit_workflow_responses_path(workflow_settings: Dict[str, Any]) -> bool:
    return bool(
        str(
            workflow_settings.get("responses_path")
            or workflow_settings.get("openai_responses_path")
            or ""
        ).strip()
    )


def _build_foundry_workflow_response_urls(
    endpoint: str,
    workflow_settings: Dict[str, Any],
    responses_api_version: str = "",
) -> List[str]:
    explicit_path = str(
        workflow_settings.get("responses_path")
        or workflow_settings.get("openai_responses_path")
        or ""
    ).strip()
    if explicit_path:
        if explicit_path.startswith(("https://", "http://")):
            return [explicit_path]
        return [f"{endpoint.rstrip('/')}/{explicit_path.lstrip('/')}"]

    endpoint_base = endpoint.rstrip("/")
    protocol_version = _normalize_foundry_responses_protocol_version(responses_api_version)
    if protocol_version:
        return [
            f"{endpoint_base}/openai/{protocol_version}/responses",
            f"{endpoint_base}/openai/responses",
            f"{endpoint_base}/responses",
        ]

    return [
        f"{endpoint_base}/openai/responses",
        f"{endpoint_base}/openai/v1/responses",
        f"{endpoint_base}/responses",
    ]


def _derive_foundry_conversation_url(response_url: str) -> str:
    normalized_url = str(response_url or "").rstrip("/")
    if normalized_url.endswith("/responses"):
        return f"{normalized_url[:-len('/responses')]}/conversations"
    return f"{normalized_url}/conversations"


def _build_foundry_workflow_endpoint_candidates(
    endpoint: str,
    workflow_settings: Dict[str, Any],
    responses_api_version: str = "",
) -> List[Dict[str, str]]:
    conversation_path = str(
        workflow_settings.get("conversations_path")
        or workflow_settings.get("openai_conversations_path")
        or ""
    ).strip()
    response_urls = _build_foundry_workflow_response_urls(
        endpoint,
        workflow_settings,
        responses_api_version=responses_api_version,
    )

    candidates: List[Dict[str, str]] = []
    for response_url in response_urls:
        if conversation_path:
            if conversation_path.startswith(("https://", "http://")):
                conversation_url = conversation_path
            else:
                conversation_url = f"{endpoint.rstrip('/')}/{conversation_path.lstrip('/')}"
        else:
            conversation_url = _derive_foundry_conversation_url(response_url)
        candidates.append(
            {
                "responses_url": response_url,
                "conversations_url": conversation_url,
            }
        )
    return candidates


def _normalize_foundry_responses_protocol_version(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"v1", "v2"}:
        return normalized
    return ""


def _normalize_foundry_workflow_rest_protocol(value: Any) -> str:
    version_value = str(value or "").strip()
    if not version_value:
        return "v1"
    protocol_version = _normalize_foundry_responses_protocol_version(version_value)
    if protocol_version in {"v1", "v2"}:
        return "v1"
    return version_value


def _build_foundry_workflow_request_params(responses_api_version: Any) -> Dict[str, str]:
    version_value = str(responses_api_version or "").strip()
    if not version_value or _normalize_foundry_responses_protocol_version(version_value):
        return {}
    return {"api-version": version_value}


def _build_foundry_workflow_conversation_params(responses_api_version: Any) -> Dict[str, str]:
    version_value = str(responses_api_version or "").strip()
    if not version_value or _normalize_foundry_responses_protocol_version(version_value):
        return {}
    return {"api-version": version_value}


def _create_foundry_workflow_conversation(
    conversations_url: str,
    *,
    params: Dict[str, str],
    headers: Dict[str, str],
) -> str:
    debug_print(
        f"[FoundryWorkflowAgent] Creating Foundry conversation at {conversations_url} with params {params}"
    )
    response = requests.post(
        conversations_url,
        params=params,
        headers=headers,
        json={},
        timeout=30,
    )
    payload = _parse_json_response(response)
    if response.status_code >= 400:
        raise FoundryAgentInvocationError(
            f"{_build_http_error_message('Foundry workflow conversation create', response, payload)} at {conversations_url} with params {params}"
        )
    conversation_id = str(payload.get("id") or "").strip()
    if not conversation_id:
        raise FoundryAgentInvocationError(
            "Foundry workflow conversation create returned no conversation id."
        )
    return conversation_id


def _delete_foundry_workflow_conversation(
    conversations_url: str,
    conversation_id: str,
    *,
    params: Dict[str, str],
    headers: Dict[str, str],
) -> None:
    if not conversations_url or not conversation_id:
        return
    try:
        response = requests.delete(
            f"{conversations_url.rstrip('/')}/{quote(conversation_id, safe='')}",
            params=params,
            headers=headers,
            timeout=30,
        )
        if response.status_code >= 400:
            _logger.warning(
                "Failed to delete Foundry workflow conversation %s: HTTP %s %s",
                conversation_id,
                response.status_code,
                response.text[:300],
            )
    except Exception as cleanup_error:  # pragma: no cover - best effort cleanup
        _logger.warning(
            "Failed to delete Foundry workflow conversation %s: %s",
            conversation_id,
            cleanup_error,
        )


def _looks_like_document_context_message(text: str) -> bool:
    normalized = str(text or "").lower()
    markers = (
        "retrieved document excerpts",
        "(source:",
        "document keywords",
        "document abstract",
        "ai vision analysis",
        "chat-uploaded file",
        "selected document",
        "tabular analysis",
    )
    return any(marker in normalized for marker in markers)


def _build_foundry_workflow_input_text(
    message_history: List[ChatMessageContent],
    max_context_chars: Optional[int] = None,
    include_document_context: bool = True,
) -> str:
    parts: List[str] = []
    for message in message_history:
        text = _extract_message_text(message).strip()
        if not text:
            continue
        if not include_document_context and _looks_like_document_context_message(text):
            continue
        role_value = getattr(message, "role", "user")
        role = str(role_value).strip().lower() or "user"
        if role.startswith("authorrole."):
            role = role.split(".", 1)[1]
        if role not in {"system", "developer", "user", "assistant"}:
            role = "user"
        parts.append(f"{role.upper()}:\n{text}")

    if not parts:
        raise FoundryAgentInvocationError(
            "Foundry workflow invocation requires at least one message."
        )

    packed_text = "\n\n".join(parts).strip()
    if max_context_chars and len(packed_text) > max_context_chars:
        truncation_notice = "[Earlier SimpleChat context was truncated to fit the workflow context limit.]\n\n"
        keep_chars = max(1, max_context_chars - len(truncation_notice))
        packed_text = f"{truncation_notice}{packed_text[-keep_chars:]}"
    return packed_text


def _truncate_foundry_metadata_value(value: str) -> str:
    if len(value) <= FOUNDRY_METADATA_VALUE_MAX_LENGTH:
        return value
    return f"{value[:FOUNDRY_METADATA_VALUE_MAX_LENGTH - 3]}..."


def _build_foundry_response_metadata(
    metadata: Dict[str, Any],
    additional_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    normalized_metadata: Dict[str, str] = {}
    for key, value in {**(metadata or {}), **(additional_metadata or {})}.items():
        key_text = str(key or "").strip()
        if not key_text or key_text in FOUNDRY_INTERNAL_METADATA_KEYS or value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        normalized_metadata[key_text] = _truncate_foundry_metadata_value(str(value))
    return normalized_metadata


def _extract_foundry_file_searchable_context(text: str) -> str:
    if not text:
        return ""

    patterns = [
        (
            "image",
            r"\[User uploaded an image named[^\n]*\.\].*?Use this image information to answer questions about the uploaded image\.",
        ),
        (
            "file",
            r"\[User uploaded a file named[^\n]*Content preview:\n.*?\]\nUse this file context if relevant\.",
        ),
        (
            "tabular",
            r"\[User uploaded a tabular data file named[^\n]*\. This is CSV format data for analysis:\n.*?\]\nThis is complete tabular data in CSV format\. You can perform calculations, analysis, and data operations on this dataset\.",
        ),
    ]
    blocks: List[str] = []
    for context_type, pattern in patterns:
        blocks.extend(
            _compact_foundry_upload_context_block(context_type, match.group(0))
            for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        )

    deduped_blocks: List[str] = []
    seen_blocks = set()
    for block in blocks:
        normalized_block = re.sub(r"\s+", " ", block).strip().lower()
        if normalized_block in seen_blocks:
            continue
        deduped_blocks.append(block)
        seen_blocks.add(normalized_block)

    searchable_context = "\n\n".join(deduped_blocks).strip()
    if len(searchable_context) > FOUNDRY_FILE_SEARCHABLE_CONTEXT_MAX_CHARS:
        searchable_context = searchable_context[-FOUNDRY_FILE_SEARCHABLE_CONTEXT_MAX_CHARS:]
    return searchable_context


def _compact_foundry_upload_context_block(context_type: str, block: str) -> str:
    if context_type == "image":
        filename_match = re.search(r"\[User uploaded an image named '([^']+)'\.\]", block)
        description_match = re.search(
            r"Description:\s*(.*?)(?=\nObjects detected:|\nText visible in image:|\nContextual analysis:|\n\n|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        objects_match = re.search(
            r"Objects detected:\s*(.*?)(?=\nText visible in image:|\nContextual analysis:|\n\n|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        visible_text_match = re.search(
            r"Text visible in image:\s*(.*?)(?=\nContextual analysis:|\n\n|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        ocr_match = re.search(
            r"Extracted Text \(OCR\):\s*(.*?)(?=\n\nAI Vision Analysis:|\n\n=== AI Vision Analysis ===|$)",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        filename = filename_match.group(1).strip() if filename_match else "uploaded image"
        parts = [f"Uploaded image {filename} searchable summary:"]
        if description_match:
            parts.append(_normalize_foundry_context_snippet(description_match.group(1), 1400))
        if objects_match:
            parts.append(f"Detected objects: {_normalize_foundry_context_snippet(objects_match.group(1), 800)}")
        if visible_text_match:
            parts.append(f"Visible text: {_normalize_foundry_context_snippet(visible_text_match.group(1), 500)}")
        if ocr_match:
            parts.append(f"OCR excerpt: {_normalize_foundry_context_snippet(ocr_match.group(1), 500)}")
        return " ".join(part for part in parts if part).strip()

    if context_type == "file":
        file_match = re.search(
            r"\[User uploaded a file named '([^']+)'\. Content preview:\n(.*?)\]\nUse this file context if relevant\.",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if file_match:
            filename = file_match.group(1).strip()
            preview = _normalize_foundry_context_snippet(file_match.group(2), 1800)
            return f"Uploaded file {filename} searchable content preview: {preview}"

    if context_type == "tabular":
        table_match = re.search(
            r"\[User uploaded a tabular data file named '([^']+)'\. This is CSV format data for analysis:\n(.*?)\]",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if table_match:
            filename = table_match.group(1).strip()
            preview = _normalize_foundry_context_snippet(table_match.group(2), 1800)
            return f"Uploaded tabular file {filename} searchable CSV preview: {preview}"

    return _normalize_foundry_context_snippet(block, 1800)


def _normalize_foundry_context_snippet(value: str, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars - 3]}..."


def _append_foundry_file_searchable_context_to_text(text: str, searchable_context: str) -> str:
    if not text or not searchable_context or FOUNDRY_FILE_SEARCHABLE_CONTEXT_HEADER in text:
        return text
    summary = f"{FOUNDRY_FILE_SEARCHABLE_CONTEXT_HEADER}:\n{searchable_context}\n\nOriginal user request:\n"
    user_marker = "\n\nUSER:\n"
    user_marker_index = text.rfind(user_marker)
    if user_marker_index >= 0:
        user_text_index = user_marker_index + len(user_marker)
        return f"{text[:user_text_index]}{summary}{text[user_text_index:]}"
    return f"{summary}{text}"


def _build_foundry_file_attached_workflow_text(
    message_history: List[ChatMessageContent],
    searchable_context: str,
) -> str:
    latest_user_text = _extract_latest_user_message_text(message_history)
    if not latest_user_text:
        return f"{FOUNDRY_FILE_SEARCHABLE_CONTEXT_HEADER}:\n{searchable_context}"
    return (
        f"{FOUNDRY_FILE_SEARCHABLE_CONTEXT_HEADER}:\n{searchable_context}\n\n"
        f"User request:\n{_clean_foundry_file_reference_text(latest_user_text)}"
    )


def _extract_latest_user_message_text(message_history: List[ChatMessageContent]) -> str:
    for message in reversed(message_history or []):
        role_value = getattr(message, "role", "user")
        role = str(role_value).strip().lower() or "user"
        if role.startswith("authorrole."):
            role = role.split(".", 1)[1]
        if role != "user":
            continue
        text = _extract_message_text(message).strip()
        if text:
            return text
    return ""


def _clean_foundry_file_reference_text(text: str) -> str:
    cleaned_text = str(text or "")
    replacements = [
        (r"\b(the\s+)?file\s+(i('|’)ve|ive|have)\s+uploaded\b", "the attached file summary"),
        (r"\b(the\s+)?image\s+(i('|’)ve|ive|have)\s+uploaded\b", "the attached image summary"),
        (r"\b(the\s+)?document\s+(i('|’)ve|ive|have)\s+uploaded\b", "the attached document summary"),
        (r"\buploaded\s+file\b", "attached file summary"),
        (r"\buploaded\s+image\b", "attached image summary"),
        (r"\buploaded\s+document\b", "attached document summary"),
    ]
    for pattern, replacement in replacements:
        cleaned_text = re.sub(pattern, replacement, cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(
        r"^\s*(okay,?\s*)?(let'?s|lets)\s+work\s+on\s+([A-Za-z0-9_-]+),?\s*evaluate\s+the\s+attached\s+(file|image|document)\s+summary\s+for\s+prior\s+art[,.]?\s*",
        r"Run the prior art search for \3. ",
        cleaned_text,
        flags=re.IGNORECASE,
    )
    cleaned_text = re.sub(
        r"\bevaluate\s+the\s+attached\s+(file|image|document)\s+summary\s+for\s+prior\s+art\b",
        r"run the prior art search using the attached \1 summary",
        cleaned_text,
        flags=re.IGNORECASE,
    )
    return cleaned_text.strip()


def _build_foundry_workflow_request_payload(
    message_history: List[ChatMessageContent],
    metadata: Dict[str, Any],
    *,
    workflow_settings: Optional[Dict[str, Any]] = None,
    workflow_name: str,
    stream: bool = True,
    max_output_tokens: Optional[int] = None,
    max_context_chars: Optional[int] = None,
    include_document_context: bool = True,
    file_inputs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    normalized_metadata = _build_foundry_response_metadata(
        metadata,
        additional_metadata={"workflow_name": workflow_name},
    )

    input_text = _build_foundry_workflow_input_text(
        message_history,
        max_context_chars=max_context_chars,
        include_document_context=include_document_context,
    )
    normalized_file_inputs = [item for item in (file_inputs or []) if isinstance(item, dict)]
    if normalized_file_inputs:
        searchable_context = _extract_foundry_file_searchable_context(input_text)
        if searchable_context:
            input_text = _build_foundry_file_attached_workflow_text(
                message_history,
                searchable_context,
            )
        input_payload: Any = [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": input_text,
                    },
                    *normalized_file_inputs,
                ],
            }
        ]
    else:
        input_payload = input_text

    payload: Dict[str, Any] = {
        "input": input_payload,
        "stream": stream,
        "agent_reference": _build_foundry_workflow_agent_reference(
            workflow_settings or {},
            workflow_name,
        ),
        "metadata": normalized_metadata,
    }

    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    return payload


def _build_foundry_workflow_invocation_result(
    *,
    response_payload: Dict[str, Any],
    workflow_name: str,
) -> FoundryAgentInvocationResult:
    result = _build_new_foundry_invocation_result(
        response_payload=response_payload,
        application_name=workflow_name,
    )
    result.metadata["workflow_name"] = workflow_name
    result.metadata["runtime_type"] = "foundry_workflow"
    return result


def _coerce_bool(value: Any, default_value: bool = True) -> bool:
    if value is None:
        return default_value
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default_value


def _coerce_positive_int(value: Any, default_value: int, max_value: Optional[int] = None) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default_value
    if normalized <= 0:
        normalized = default_value
    if max_value is not None:
        normalized = min(normalized, max_value)
    return normalized


def _coerce_string_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        candidates = str(value).replace(";", ",").split(",")
    normalized: List[str] = []
    seen = set()
    for item in candidates:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _download_foundry_source_blob(blob_container: str, blob_path: str) -> bytes:
    from functions_simplechat_operations import download_blob_content

    return download_blob_content(blob_container, blob_path)


def _build_foundry_file_input_part(
    *,
    file_name: str,
    file_bytes: bytes,
    content_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
        return None
    normalized_file_name = str(file_name or "uploaded-file").strip() or "uploaded-file"
    normalized_content_type = str(
        content_type
        or mimetypes.guess_type(normalized_file_name)[0]
        or "application/octet-stream"
    ).split(";", 1)[0].strip() or "application/octet-stream"
    data_uri = f"data:{normalized_content_type};base64,{base64.b64encode(bytes(file_bytes)).decode('ascii')}"

    return {
        "type": "input_file",
        "filename": normalized_file_name,
        "file_data": data_uri,
    }


def _append_foundry_file_input(
    file_inputs: List[Dict[str, Any]],
    file_metadata: List[Dict[str, Any]],
    seen_sources: set,
    *,
    source_key: str,
    file_name: str,
    blob_container: str,
    blob_path: str,
    content_type: Optional[str],
    max_file_bytes: int,
    source_type: str,
) -> None:
    if not blob_container or not blob_path or source_key in seen_sources:
        return
    seen_sources.add(source_key)

    try:
        file_bytes = _download_foundry_source_blob(blob_container, blob_path)
    except Exception as exc:
        log_event(
            "[FoundryWorkflowAgent] Failed to load file input blob",
            extra={
                "source_type": source_type,
                "blob_container": blob_container,
                "blob_path": blob_path,
                "error": str(exc),
            },
            level=logging.WARNING,
        )
        return

    if len(file_bytes) > max_file_bytes:
        log_event(
            "[FoundryWorkflowAgent] Skipping oversized file input",
            extra={
                "source_type": source_type,
                "file_name": file_name,
                "file_size": len(file_bytes),
                "max_file_bytes": max_file_bytes,
            },
            debug_only=True,
        )
        return

    file_part = _build_foundry_file_input_part(
        file_name=file_name,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    if not file_part:
        return

    file_inputs.append(file_part)
    file_metadata.append(
        {
            "source_type": source_type,
            "file_name": file_name,
            "content_type": content_type or mimetypes.guess_type(file_name or "")[0] or "application/octet-stream",
            "file_size": len(file_bytes),
        }
    )


def _collect_recent_chat_upload_file_inputs(
    *,
    conversation_id: str,
    file_inputs: List[Dict[str, Any]],
    file_metadata: List[Dict[str, Any]],
    seen_sources: set,
    max_files: int,
    max_file_bytes: int,
) -> None:
    if not conversation_id or len(file_inputs) >= max_files:
        return
    from config import cosmos_messages_container

    try:
        rows = list(
            cosmos_messages_container.query_items(
                query=(
                    "SELECT * FROM c WHERE c.conversation_id = @conversation_id "
                    "AND (c.role = 'file' OR c.role = 'image') ORDER BY c.timestamp DESC"
                ),
                parameters=[{"name": "@conversation_id", "value": conversation_id}],
                partition_key=conversation_id,
                enable_cross_partition_query=True,
            )
        )
    except Exception as exc:
        log_event(
            "[FoundryWorkflowAgent] Failed to query chat upload file inputs",
            extra={"conversation_id": conversation_id, "error": str(exc)},
            level=logging.WARNING,
        )
        return

    for message in rows:
        if len(file_inputs) >= max_files:
            break
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if metadata.get("is_user_upload") is not True and str(message.get("file_content_source") or "").strip().lower() != "blob":
            continue
        file_name = str(message.get("filename") or message.get("title") or message.get("id") or "chat-upload").strip()
        content_type = message.get("mime_type") or metadata.get("content_type") or metadata.get("mime_type")
        blob_container = str(message.get("blob_container") or "").strip()
        blob_path = str(message.get("blob_path") or "").strip()
        _append_foundry_file_input(
            file_inputs,
            file_metadata,
            seen_sources,
            source_key=f"chat:{message.get('id')}",
            file_name=file_name,
            blob_container=blob_container,
            blob_path=blob_path,
            content_type=content_type,
            max_file_bytes=max_file_bytes,
            source_type="chat_upload",
        )


def _collect_selected_document_file_inputs(
    *,
    metadata: Dict[str, Any],
    file_inputs: List[Dict[str, Any]],
    file_metadata: List[Dict[str, Any]],
    seen_sources: set,
    max_files: int,
    max_file_bytes: int,
) -> None:
    if len(file_inputs) >= max_files:
        return
    selected_document_ids = _coerce_string_list(metadata.get("selected_document_ids"))
    selected_document_id = str(metadata.get("selected_document_id") or "").strip()
    if selected_document_id and selected_document_id not in selected_document_ids:
        selected_document_ids.append(selected_document_id)
    if not selected_document_ids:
        return

    user_id = str(metadata.get("user_id") or "").strip()
    document_scope = str(metadata.get("document_scope") or "all").strip() or "all"
    conversation_id = str(metadata.get("conversation_id") or "").strip()
    active_group_ids = _coerce_string_list(metadata.get("active_group_ids"))
    active_public_workspace_ids = _coerce_string_list(metadata.get("active_public_workspace_ids"))

    if not user_id:
        return

    from functions_documents import get_document_blob_storage_info
    from functions_search_service import resolve_document_context

    for document_id in selected_document_ids:
        if len(file_inputs) >= max_files:
            break
        try:
            context = resolve_document_context(
                document_id=document_id,
                user_id=user_id,
                doc_scope=document_scope,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_ids,
                conversation_id=conversation_id,
            )
        except Exception as exc:
            log_event(
                "[FoundryWorkflowAgent] Failed to resolve selected document file input",
                extra={"document_id": document_id, "error": str(exc)},
                level=logging.WARNING,
            )
            continue
        if not context:
            continue
        if context.get("scope") == "chat":
            continue
        document = context.get("document") if isinstance(context.get("document"), dict) else {}
        try:
            blob_container, blob_path = get_document_blob_storage_info(document)
        except Exception:
            blob_container = document.get("blob_container")
            blob_path = document.get("blob_path")
        file_name = str(document.get("file_name") or document.get("title") or document_id).strip()
        content_type = document.get("mime_type") or document.get("content_type")
        _append_foundry_file_input(
            file_inputs,
            file_metadata,
            seen_sources,
            source_key=f"document:{document_id}",
            file_name=file_name,
            blob_container=str(blob_container or "").strip(),
            blob_path=str(blob_path or "").strip(),
            content_type=content_type,
            max_file_bytes=max_file_bytes,
            source_type=f"workspace_{context.get('scope') or 'document'}",
        )


def _collect_foundry_response_file_inputs(
    foundry_settings: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not _coerce_bool(foundry_settings.get("include_file_inputs"), True):
        return [], []

    max_files = _coerce_positive_int(foundry_settings.get("max_file_inputs"), 5, max_value=20)
    max_file_bytes = _coerce_positive_int(
        foundry_settings.get("max_file_input_bytes"),
        8 * 1024 * 1024,
        max_value=25 * 1024 * 1024,
    )
    file_inputs: List[Dict[str, Any]] = []
    file_metadata: List[Dict[str, Any]] = []
    seen_sources = set()

    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    _collect_selected_document_file_inputs(
        metadata=normalized_metadata,
        file_inputs=file_inputs,
        file_metadata=file_metadata,
        seen_sources=seen_sources,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
    )
    _collect_recent_chat_upload_file_inputs(
        conversation_id=str(normalized_metadata.get("conversation_id") or "").strip(),
        file_inputs=file_inputs,
        file_metadata=file_metadata,
        seen_sources=seen_sources,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
    )

    return file_inputs[:max_files], file_metadata[:max_files]


def _build_async_credential(
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
):
    auth_type = _resolve_foundry_authentication_type(foundry_settings, global_settings)
    if auth_type == "api_key":
        raise FoundryAgentInvocationError(
            "Foundry agent and workflow invocation requires Microsoft Entra ID/RBAC. API keys are only supported for model endpoint inference."
        )
    if auth_type == "delegated_user":
        scope = _resolve_foundry_scope(foundry_settings, global_settings)
        token = _get_delegated_foundry_user_token(scope)
        return DelegatedUserAccessTokenCredential(token)

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

    if auth_type == "managed_identity":
        if managed_identity_type == "user_assigned" and managed_identity_client_id:
            return AsyncDefaultAzureCredential(
                authority=authority,
                managed_identity_client_id=managed_identity_client_id,
            )
        return AsyncDefaultAzureCredential(authority=authority)

    raise FoundryAgentInvocationError(
        f"Unsupported Foundry authentication type '{auth_type}'."
    )


def _resolve_foundry_authentication_type(
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
) -> str:
    auth_type = (
        foundry_settings.get("authentication_type")
        or foundry_settings.get("auth_type")
        or global_settings.get("azure_ai_foundry_authentication_type")
    )
    auth_type = str(auth_type or "delegated_user").strip().lower()
    if auth_type in {"user", "delegated", "user_delegated", "signed_in_user"}:
        return "delegated_user"
    if auth_type in {"key", "api_key", "apikey"}:
        return "api_key"
    if auth_type in {"managed_identity", "service_principal"}:
        return auth_type
    return "delegated_user"


async def _build_foundry_rest_headers(
    foundry_settings: Dict[str, Any],
    global_settings: Dict[str, Any],
    credential,
) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    scope = _resolve_foundry_scope(foundry_settings, global_settings)
    token = await credential.get_token(scope)
    headers["Authorization"] = f"Bearer {token.token}"
    return headers


def _get_delegated_foundry_user_token(scope: str) -> str:
    token_result = get_valid_access_token_for_plugins(scopes=[scope])
    if isinstance(token_result, dict) and token_result.get("access_token"):
        return token_result["access_token"]
    if isinstance(token_result, str) and token_result:
        return token_result

    auth_response = token_result if isinstance(token_result, dict) else {}
    error_message = FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE
    if isinstance(auth_response, dict):
        auth_response["message"] = error_message
    raise FoundryAgentUserAuthenticationRequired(error_message, auth_response=auth_response)


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
    file_inputs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    input_items: List[Dict[str, Any]] = []
    last_user_input_index: Optional[int] = None
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
        if role == "user":
            last_user_input_index = len(input_items) - 1

    if not input_items:
        raise FoundryAgentInvocationError(
            "New Foundry invocation requires at least one message."
        )

    normalized_file_inputs = [item for item in (file_inputs or []) if isinstance(item, dict)]
    if normalized_file_inputs:
        attachment_index = last_user_input_index if last_user_input_index is not None else len(input_items) - 1
        searchable_context = _extract_foundry_file_searchable_context(
            "\n\n".join(_extract_message_text(message) for message in message_history)
        )
        input_items[attachment_index]["content"][0]["text"] = _append_foundry_file_searchable_context_to_text(
            input_items[attachment_index]["content"][0]["text"],
            searchable_context,
        )
        input_items[attachment_index].setdefault("content", []).extend(normalized_file_inputs)

    payload: Dict[str, Any] = {
        "input": input_items,
        "stream": stream,
    }
    normalized_metadata = _build_foundry_response_metadata(metadata)
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
        return f"Foundry stream failed: {message}"
    if isinstance(error_payload, str) and error_payload.strip():
        return f"Foundry stream failed: {error_payload.strip()}"

    response_payload = event_payload.get("response")
    if isinstance(response_payload, dict):
        response_error = response_payload.get("error")
        if isinstance(response_error, dict):
            message = response_error.get("message") or json.dumps(response_error, default=str)
            code = response_error.get("code")
            if code:
                return f"Foundry stream failed: {code}: {message}"
            return f"Foundry stream failed: {message}"
        if isinstance(response_error, str) and response_error.strip():
            return f"Foundry stream failed: {response_error.strip()}"
        status = str(response_payload.get("status") or "").strip()
        response_id = str(response_payload.get("id") or "").strip()
        if status:
            id_suffix = f" (response {response_id})" if response_id else ""
            return f"Foundry stream failed: response status {status}{id_suffix}"

    return f"Foundry stream failed: {json.dumps(event_payload, default=str)[:500]}"


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
    if event_type == "response.output_text.done":
        text = event_payload.get("text")
        if isinstance(text, str) and text.strip():
            state.metadata["output_text"] = text
            current_text = "".join(state.text_parts).strip()
            if not current_text or len(text.strip()) >= len(current_text):
                state.text_parts = [text]
        return

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
    metadata_text = state.metadata.get("output_text")
    if isinstance(metadata_text, str) and metadata_text.strip():
        normalized_metadata_text = metadata_text.strip()
        if not text or len(normalized_metadata_text) >= len(text):
            return normalized_metadata_text
    return text


def _build_new_foundry_stream_metadata(
    state: NewFoundryStreamState,
    application_name: str,
) -> Dict[str, Any]:
    metadata = dict(state.metadata)
    metadata["citations"] = state.citations
    metadata["model"] = state.model or application_name
    return metadata


def _record_foundry_workflow_event(
    state: NewFoundryStreamState,
    event_type: str,
    event_payload: Dict[str, Any],
) -> None:
    if event_type in {"response.output_text.delta", "response.completed"}:
        return

    item = event_payload.get("item") if isinstance(event_payload.get("item"), dict) else {}
    event_name = (
        item.get("name")
        or item.get("tool_name")
        or event_payload.get("name")
        or event_payload.get("tool_name")
        or ""
    )
    item_type = item.get("type") or event_payload.get("item_type") or event_payload.get("type")
    event_summary = {
        "type": event_type,
        "item_type": item_type,
        "name": event_name,
        "status": item.get("status") or event_payload.get("status"),
        "id": item.get("id") or event_payload.get("id"),
    }
    compact_summary = {
        key: value
        for key, value in event_summary.items()
        if value not in (None, "", [], {})
    }
    if not compact_summary:
        return

    workflow_events = state.metadata.setdefault("workflow_action_events", [])
    if isinstance(workflow_events, list) and len(workflow_events) < 50:
        workflow_events.append(compact_summary)


def _build_foundry_workflow_stream_metadata(
    state: NewFoundryStreamState,
    workflow_name: str,
    request_payload: Dict[str, Any],
    foundry_conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    metadata = _build_new_foundry_stream_metadata(state, workflow_name)
    metadata["workflow_name"] = workflow_name
    metadata["runtime_type"] = "foundry_workflow"
    metadata["foundry_conversation_id"] = foundry_conversation_id
    metadata["source_document_count"] = str(
        (request_payload.get("metadata") or {}).get("selected_document_count")
        or ""
    ).strip()
    metadata = {
        key: value
        for key, value in metadata.items()
        if value not in (None, "", [], {})
    }
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
    url = f"{endpoint.rstrip('/')}/agents"
    headers = await _build_foundry_rest_headers(
        foundry_settings,
        global_settings,
        credential,
    )

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

            agent_id = str(item.get("id") or properties.get("id") or "").strip()
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
                    "agent_id": agent_id,
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


def list_foundry_workflows_from_endpoint(foundry_settings: Dict[str, Any], global_settings: Dict[str, Any]):
    """Synchronously list workflow-capable Foundry project entries."""
    workflows = list_new_foundry_agents_from_endpoint(foundry_settings, global_settings)
    normalized = []
    for item in workflows:
        if not isinstance(item, dict):
            continue
        workflow_item = dict(item)
        agent_id = str(
            workflow_item.get("workflow_agent_id")
            or workflow_item.get("agent_id")
            or workflow_item.get("id")
            or ""
        ).strip()
        application_id = str(workflow_item.get("application_id") or agent_id).strip()
        application_name = str(workflow_item.get("application_name") or workflow_item.get("name") or "").strip()
        application_version = str(workflow_item.get("application_version") or "").strip()
        workflow_name = str(
            workflow_item.get("workflow_name")
            or application_name
            or agent_id
        ).strip()
        workflow_item["resource_type"] = workflow_item.get("resource_type") or "workflow"
        workflow_item["workflow_name"] = workflow_name
        workflow_item["workflow_agent_id"] = workflow_item.get("workflow_agent_id") or agent_id
        workflow_item["agent_reference"] = {
            key: value
            for key, value in {
                "type": "agent_reference",
                "name": workflow_name,
                "id": agent_id,
                "application_id": application_id,
                "application_version": application_version,
            }.items()
            if value
        }
        normalized.append(workflow_item)
    return normalized

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
