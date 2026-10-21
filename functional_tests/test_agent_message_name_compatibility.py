# test_agent_message_name_compatibility.py
"""
Functional regressions for request-only agent message author aliases.
Version: 0.261.365
Implemented in: 0.261.365

Real SimpleChat agents and Semantic Kernel serialize requests through the pinned
Azure/OpenAI clients to an offline HTTP transport. Agent identities, shared
histories, tool routing, streaming, workflow and delegation entrypoints remain
unchanged. Socket/DNS access is blocked; no live model or Azure state is used.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

from flask import Flask, session
import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI
import pytest
from semantic_kernel.agents import ChatHistoryAgentThread
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion
from semantic_kernel.contents import ChatHistory, ChatMessageContent, FunctionCallContent, FunctionResultContent
from semantic_kernel.exceptions.service_exceptions import ServiceResponseException
from semantic_kernel.functions import KernelArguments, kernel_function


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))

# Application imports follow the worktree module-path setup.
from agent_logging_chat_completion import LoggingChatCompletionAgent
from agent_execution_context import ExecutionIdentity
from content_screening.access import guard_chat_service
from functions_model_capabilities import resolve_model_token_budget
from functions_model_message_names import model_message_author_name, wrap_agent_message_names
from functions_workflow_context import invoke_workflow_agent, wrap_workflow_chat_service
from test_m365_agent_streaming import delegation
from test_workflow_policy_failures import prepare, run_once
from test_workflow_runtime_integration import integration


LONG_NAME = "FED-failed-only-20261020T214915Z-FED-26-recovery-controlled-agent"
INSTRUCTIONS = "Read the authorized acquisition record. Preserve all evidence."
TOOL_NAME = "evidence-load"
TOOL_CALL_ID = "opaque-call-01"


@pytest.fixture
def offline_loop(monkeypatch):
    # Windows creates a loopback socket pair when constructing an event loop.
    loop = asyncio.new_event_loop()

    def blocked(*args, **kwargs):
        raise AssertionError("Message-name regressions must not access the network.")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    try:
        yield loop
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


class ProviderCapture:
    def __init__(self, *, tool=False, reject=False):
        self.requests = []
        self.tool = tool
        self.reject = reject

    def __call__(self, request):
        payload = json.loads(request.content)
        self.requests.append(payload)
        invalid = [
            message["name"] for message in payload["messages"] if "name" in message
            and (len(message["name"]) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", message["name"]))
        ]
        if invalid or self.reject:
            return httpx.Response(400, json={"error": {
                "message": "Offline provider rejected request metadata.",
                "type": "invalid_request_error", "code": "invalid_value", "param": "messages[0].name",
            }})
        call_tool = self.tool and not any(message["role"] == "tool" for message in payload["messages"])
        message = {"role": "assistant"}
        if call_tool:
            message["tool_calls"] = [{
                "id": TOOL_CALL_ID, "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            }]
        else:
            message["content"] = "Verified acquisition record."
        common = {"id": "offline-completion", "created": 1, "model": "offline-model"}
        finish_reason = "tool_calls" if call_tool else "stop"
        if payload.get("stream"):
            if call_tool:
                message["tool_calls"][0]["index"] = 0
            chunks = [
                {**common, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": message, "finish_reason": None},
                ]},
                {**common, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish_reason},
                ]},
            ]
            text = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            **common, "object": "chat.completion",
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        })


@asynccontextmanager
async def offline_agent(protocol, name, *, capture=None):
    capture = capture if capture is not None else ProviderCapture()
    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as http_client:
        if protocol == "azure":
            client = AsyncAzureOpenAI(
                azure_endpoint="https://offline.invalid", api_version="2024-05-01-preview",
                api_key="offline-only", max_retries=0, http_client=http_client,
            )
            service = AzureChatCompletion(deployment_name="offline-model", async_client=client)
        else:
            client = AsyncOpenAI(api_key="offline-only", max_retries=0, http_client=http_client)
            service = OpenAIChatCompletion(ai_model_id="offline-model", async_client=client)
        agent = LoggingChatCompletionAgent(
            id="saved-agent-id", name=name, display_name="Unchanged visible agent",
            instructions=INSTRUCTIONS, service=service,
            function_choice_behavior=FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=3),
        )
        yield agent, capture


async def invoke(agent, *, streaming=False, **kwargs):
    if streaming:
        return [response async for response in agent.invoke_stream(**kwargs)]
    response = await agent.invoke(**kwargs)
    return [response]


@pytest.mark.parametrize("name", ["a" * 63, "a" * 64, LONG_NAME, "a" * 300, "", "Agent with spaces", "Agent.\u00e9", "\ud800"])
def test_author_alias_is_valid_deterministic_and_idempotent(name):
    alias = model_message_author_name(name)
    again = model_message_author_name(name)
    repeated = model_message_author_name(alias)
    assert 1 <= len(alias) <= 64
    assert re.fullmatch(r"[A-Za-z0-9_-]+", alias)
    assert alias == again == repeated
    if name and len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", name):
        assert alias == name


def test_long_names_with_common_prefix_have_distinct_aliases():
    first = model_message_author_name("agent_" + "a" * 200 + "one")
    second = model_message_author_name("agent_" + "a" * 200 + "two")
    assert first != second


@pytest.mark.parametrize("optimized", [False, True])
def test_name_boundary_import_and_identity_checks_need_no_cloud_bootstrap(optimized):
    probe = """
import socket, sys
def blocked(*args, **kwargs):
    raise RuntimeError("Name compatibility import attempted network access.")
socket.getaddrinfo = blocked
socket.socket.connect = blocked
from functions_model_message_names import model_message_author_name, wrap_agent_message_names
name = "agent_" + "a" * 200
alias = model_message_author_name(name)
again = model_message_author_name(alias)
if not (len(alias) == 64 and again == alias and name == "agent_" + "a" * 200):
    raise RuntimeError("Author alias or original identity changed.")
if "config" in sys.modules or "functions_settings" in sys.modules:
    raise RuntimeError("Name compatibility imported cloud configuration.")
"""
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", probe],
        env={**os.environ, "PYTHONPATH": str(ROOT / "application" / "single_app")},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("protocol", ["azure", "openai"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("length", [63, 64, 65, 300])
def test_real_agent_serializes_compatible_authors_without_renaming_identity(offline_loop, protocol, streaming, length):
    name = LONG_NAME if length == 65 else "a" * length

    async def exercise():
        async with offline_agent(protocol, name) as (agent, capture):
            responses = await invoke(agent, streaming=streaming, messages="Read one record.")
            stored = [message async for message in responses[-1].thread.get_messages()]
            assert all(response.message.name == name for response in responses)
            assert stored[-1].name == name
            assert agent.name == name and agent.id == "saved-agent-id"
            assert agent.display_name == "Unchanged visible agent" and agent.instructions == INSTRUCTIONS
            assert len(capture.requests) == 1
            instruction = capture.requests[0]["messages"][0]
            assert instruction == {"role": "system", "name": model_message_author_name(name), "content": INSTRUCTIONS}
            assert "name" not in capture.requests[0]["messages"][1]
            wrapped, _settings = await agent._get_chat_completion_service_and_settings(agent.kernel, KernelArguments())
            same = wrap_agent_message_names(wrapped)
            assert same is wrapped

    offline_loop.run_until_complete(exercise())


@pytest.mark.parametrize("streaming", [False, True])
def test_name_boundary_retains_verified_model_settings_and_instruction_role(offline_loop, streaming):
    budget = resolve_model_token_budget({"modelName": "gpt-4o"}, provider="azure", request_output_limit=128)

    async def exercise():
        async with offline_agent("azure", LONG_NAME) as (agent, capture):
            original_service = agent.service
            original_service.instruction_role = "developer"
            agent.model_token_budget = budget
            agent.deployment_name = "offline-model"
            responses = await invoke(agent, streaming=streaming, messages="Read one record.")
            assert agent.service is original_service and agent.model_token_budget == budget
            assert responses[-1].message.name == LONG_NAME
            assert capture.requests[0]["max_tokens"] == 128
            assert capture.requests[0]["messages"][0] == {
                "role": "developer", "name": model_message_author_name(LONG_NAME), "content": INSTRUCTIONS,
            }

    offline_loop.run_until_complete(exercise())


@pytest.mark.parametrize("streaming", [False, True])
def test_shared_history_and_followup_keep_saved_authors_and_content(offline_loop, streaming):
    history = ChatHistory(messages=[
        ChatMessageContent(role="developer", name="Policy author / original", content="Keep original policy."),
        ChatMessageContent(role="user", name="Original user \u00e9", content="Read the authorized source.", metadata={"source": "one"}),
        ChatMessageContent(role="assistant", name=LONG_NAME + "_previous", content="Earlier evidence."),
    ])
    before = history.model_dump()

    async def exercise():
        async with offline_agent("azure", LONG_NAME) as (first, first_capture):
            async with offline_agent("openai", LONG_NAME + "_second") as (second, second_capture):
                thread = ChatHistoryAgentThread(chat_history=history)
                first_responses = await invoke(first, streaming=streaming, thread=thread)
                stored_first = [message async for message in thread.get_messages()]
                first_author = stored_first[-1].name
                snapshot = [message.model_dump() for message in stored_first]
                second_responses = await invoke(second, streaming=streaming, thread=thread, messages="Continue.")
                stored_second = [message async for message in thread.get_messages()]
                assert first_author == LONG_NAME
                assert stored_second[-1].name == second.name
                assert first_responses[-1].message.name == first.name
                assert second_responses[-1].message.name == second.name
                assert [message.model_dump() for message in stored_first] == snapshot
                for capture in (first_capture, second_capture):
                    outgoing = capture.requests[0]["messages"]
                    for original, copied in zip(history.messages[:3], outgoing[1:4]):
                        assert copied["name"] == model_message_author_name(original.name)
                        assert copied["content"] == original.content
                assert second_capture.requests[0]["messages"][-2]["name"] == model_message_author_name(first.name)

    offline_loop.run_until_complete(exercise())
    assert [message.model_dump() for message in history.messages[:3]] == before["messages"]


def test_request_copy_preserves_tool_routing_and_input_metadata(offline_loop):
    history = ChatHistory(messages=[
        ChatMessageContent(role="assistant", name=LONG_NAME, items=[
            FunctionCallContent(id=TOOL_CALL_ID, name=TOOL_NAME, arguments='{"original":true}'),
        ], metadata={"evidence": {"id": "unchanged"}}),
        ChatMessageContent(role="tool", name="Original_tool_route", items=[
            FunctionResultContent(id=TOOL_CALL_ID, name=TOOL_NAME, result={"record": "original"}),
        ]),
    ])
    before = history.model_dump()

    async def exercise():
        async with offline_agent("azure", LONG_NAME) as (agent, _capture):
            service, _settings = await agent._get_chat_completion_service_and_settings(agent.kernel, KernelArguments())
            outgoing = service._prepare_chat_history_for_request(history)
            original = agent.service._prepare_chat_history_for_request(history)
            assert service.delegate is agent.service
            assert outgoing[0] == {**original[0], "name": model_message_author_name(LONG_NAME)}
            assert outgoing[1] == original[1]

    offline_loop.run_until_complete(exercise())
    assert history.model_dump() == before


@pytest.mark.parametrize("protocol", ["azure", "openai"])
@pytest.mark.parametrize("streaming", [False, True])
def test_real_tool_rounds_preserve_function_names_and_call_ids(offline_loop, protocol, streaming):
    effects = []

    @kernel_function(name="load", description="Read the authorized acquisition record.")
    def load() -> str:
        effects.append("read")
        return "Known acquisition result."

    async def exercise():
        async with offline_agent(protocol, LONG_NAME, capture=ProviderCapture(tool=True)) as (agent, capture):
            agent.kernel.add_function(plugin_name="evidence", function=load)
            responses = await invoke(agent, streaming=streaming, messages="Read the acquisition record.")
            assert responses[-1].message.name == LONG_NAME
            assert len(capture.requests) == 2
            assert all(request["tools"][0]["function"]["name"] == TOOL_NAME for request in capture.requests)
            second = capture.requests[-1]["messages"]
            call = next(message for message in second if message.get("tool_calls"))
            result = next(message for message in second if message["role"] == "tool")
            assert call["tool_calls"][0]["function"]["name"] == TOOL_NAME
            assert call["tool_calls"][0]["id"] == result["tool_call_id"] == TOOL_CALL_ID
            assert "Known acquisition result." in result["content"]

    offline_loop.run_until_complete(exercise())
    assert effects == ["read"]


def test_unrelated_provider_failure_is_not_hidden_or_retried(offline_loop):
    capture = ProviderCapture(reject=True)

    async def exercise():
        async with offline_agent("azure", LONG_NAME, capture=capture) as (agent, _capture):
            with pytest.raises(ServiceResponseException):
                await agent.invoke(messages="Read one record.")
            assert agent.name == LONG_NAME

    offline_loop.run_until_complete(exercise())
    assert len(capture.requests) == 1


@pytest.mark.parametrize("streaming", [False, True])
def test_per_round_source_guard_still_stops_after_an_external_read(offline_loop, streaming):
    effects = []
    capture = ProviderCapture(tool=True)

    @kernel_function(name="load", description="Read the authorized record.")
    def load() -> str:
        effects.append("read")
        return "Read before access changed."

    def validate():
        if effects:
            raise PermissionError("Source access changed before the next model request.")

    async def exercise():
        async with offline_agent("azure", LONG_NAME, capture=capture) as (agent, _capture):
            agent.kernel.add_function(plugin_name="evidence", function=load)
            guard_chat_service(agent.service, source_validator=validate)
            with pytest.raises(PermissionError, match="Source access changed"):
                await invoke(agent, streaming=streaming, messages="Read one record.")

    offline_loop.run_until_complete(exercise())
    assert effects == ["read"] and len(capture.requests) == 1


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("group", [False, True])
def test_durable_workflow_invokes_real_named_agent_without_recovery(integration, monkeypatch, offline_loop, structured, group):
    workflow, runner, services, make_store = prepare(integration, monkeypatch, structured=structured, group=group)
    capture = ProviderCapture()
    failures = []

    def dispatch(attempt_workflow, *args, **kwargs):
        async def exercise():
            async with offline_agent("azure", LONG_NAME, capture=capture) as (agent, _capture):
                agent.service = wrap_workflow_chat_service(
                    agent.service, {"modelName": "gpt-4o", "deploymentName": "offline-model"}, provider="aoai",
                )
                agent.kernel.add_service(agent.service, overwrite=True)
                response = await invoke_workflow_agent(agent, [
                    ChatMessageContent(role="user", content=attempt_workflow["task_prompt"]),
                ])
                assert response.message.name == LONG_NAME
                return {"reply": str(response)}

        try:
            return offline_loop.run_until_complete(exercise())
        except Exception as error:
            failures.append(error)
            raise

    runner["_execute_workflow_dispatch"] = dispatch
    run_id, record = run_once(workflow, services)
    control = make_store(workflow, run_id).read()
    assert record["status"] == control["state"] == "completed", failures
    assert len(capture.requests) == 1
    assert capture.requests[0]["messages"][0]["name"] == model_message_author_name(LONG_NAME)


@pytest.mark.parametrize("streaming", [False, True])
def test_delegated_entrypoint_keeps_reference_and_visible_agent_identity(delegation, offline_loop, streaming):
    reference = {
        "id": "saved-agent-id", "name": LONG_NAME, "scope_type": "personal",
        "scope_id": "owner", "user_id": "owner", "agent_type": "local",
    }
    before = dict(reference)
    app = Flask(__name__)
    app.secret_key = "offline-test-only"

    async def exercise():
        async with offline_agent("azure", LONG_NAME) as (agent, capture):
            with app.test_request_context("/api/chat/stream"):
                session["user"] = {"oid": "owner", "roles": ["User"]}
                execution = delegation.prepare_agent_execution(
                    agent, reference, user_id="owner", settings={}, conversation_id="conversation",
                )
                responses = await invoke(execution, streaming=streaming, messages="Read one record.")
                assert responses[-1].message.name == LONG_NAME
                assert execution.name == LONG_NAME and execution.reference == before
                assert execution.display_name == "Unchanged visible agent"
            assert len(capture.requests) == 1
            assert capture.requests[0]["messages"][0]["name"] == model_message_author_name(LONG_NAME)

    offline_loop.run_until_complete(exercise())
    assert reference == before


def test_scoped_orchestration_uses_real_agent_without_renaming_reference(delegation, monkeypatch, offline_loop):
    reference = {
        "id": "saved-agent-id", "name": LONG_NAME, "scope_type": "personal",
        "scope_id": "owner", "user_id": "owner", "agent_type": "local",
    }
    resolved = []

    def resolve(selected, **kwargs):
        resolved.append(dict(selected))
        return dict(reference)

    monkeypatch.setattr(delegation, "resolve_delegation_agent", resolve)

    async def exercise():
        async with offline_agent("azure", LONG_NAME) as (agent, capture):
            monkeypatch.setattr(delegation, "_build_local_agent", lambda *args: (agent.kernel, agent))
            identity = ExecutionIdentity("owner", "conversation")
            result = await delegation.invoke_scoped_agent(
                reference, "Read the acquisition record.", identity=identity, budget=delegation.DelegationBudget(),
            )
            assert result["response"] == "Verified acquisition record."
            assert agent.name == LONG_NAME and agent.id == reference["id"]
            assert capture.requests[0]["messages"][0]["name"] == model_message_author_name(LONG_NAME)

    offline_loop.run_until_complete(exercise())
    assert resolved == [reference]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
