# test_action_credentials_sk_continuation.py
"""Real SK direct-action credential suspension and exact tool-boundary resume.

Version: 0.261.337
Implemented in: 0.261.333
No model/provider network is used; the existing real SK scripted-provider harness
proves completed tools are retained rather than replayed.
"""

import asyncio
import importlib
import json
import sys
from dataclasses import replace
from unittest.mock import patch

import pytest
from flask import Blueprint, Flask
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.contents import ChatMessageContent, FunctionCallContent
from semantic_kernel.functions import kernel_function

from test_orchestration_action_runtime import runtime, execute, tool_message
from test_action_personal_credentials import CredentialContainer, manifest, module


@pytest.fixture(autouse=True)
def continuation_services(runtime, monkeypatch):
    continuation = importlib.import_module("functions_action_credential_continuation")
    screening = importlib.import_module("content_screening.access")
    agents = importlib.import_module("functions_agent_delegation")
    settings = importlib.import_module("functions_settings")
    monkeypatch.setattr(continuation, "_services", continuation.CredentialContinuationServices(
        collect_sources=lambda: screening.current_request_source_provenance(),
        authorize_source=lambda *args, **kwargs: screening.assert_document_available(*args, **kwargs),
        resolve_agent=lambda reference, **kwargs: agents.resolve_delegation_agent(
            reference, settings=settings.get_settings(), **kwargs,
        ),
    ))


def continue_classic_route(runtime, monkeypatch, agent, descriptor):
    with monkeypatch.context() as scoped, patch.dict(sys.modules):
        _continue_classic_route(runtime, scoped, agent, descriptor)


def _continue_classic_route(runtime, monkeypatch, agent, descriptor):
    """Exercise the actual credential POST consumer with a real retained SK thread."""
    state = importlib.import_module("functions_action_credential_state")
    credentials = importlib.import_module("functions_action_credentials")
    contracts = importlib.import_module("action_credential_contracts")
    monkeypatch.setitem(sys.modules, "functions_authentication", module(
        "functions_authentication", get_current_user_id=lambda: "actor",
        login_required=lambda function: function, user_required=lambda function: function,
    ))
    monkeypatch.setitem(sys.modules, "functions_settings", module("functions_settings", get_settings=lambda: {}))
    monkeypatch.setitem(sys.modules, "swagger_wrapper", module(
        "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function, get_auth_security=lambda: [],
    ))

    async def close_resources(kernel):
        return None

    monkeypatch.setitem(sys.modules, "agent_delegation_runtime", module(
        "agent_delegation_runtime", _build_local_agent=lambda *args: (agent.kernel, agent),
        close_agent_resources=close_resources,
    ))
    monkeypatch.setitem(sys.modules, "functions_agent_delegation", module(
        "functions_agent_delegation", resolve_delegation_agent=lambda *args, **kwargs: {"id": "parent"},
    ))
    routes = importlib.import_module("route_backend_action_credentials")
    descriptor["agent_reference"] = {"id": "parent"}
    raw = manifest()
    monkeypatch.setattr(credentials, "authorize_conversation", lambda user_id, conversation_id: {"id": conversation_id})
    monkeypatch.setattr(routes, "authorize_conversation", credentials.authorize_conversation)
    monkeypatch.setattr(credentials, "authorized_manifest", lambda user_id, reference: raw)
    monkeypatch.setattr(credentials, "safe_identities", lambda user_id, requirements: [])
    monkeypatch.setattr(routes, "get_current_user_id", lambda: "actor")
    monkeypatch.setattr(routes, "login_required", lambda function: function)
    monkeypatch.setattr(routes, "user_required", lambda function: function)
    monkeypatch.setattr(importlib.import_module("agent_execution_context"), "capture_execution_identity",
                        lambda user_id, conversation_id: runtime.context.agent_execution_identity)
    persisted = []

    def persist(message, user_id, **kwargs):
        persisted.append(message)
        return message

    # Assistant persistence itself is exercised with real SDK responses by the
    # fresh-process bootstrap suite; this test retains the real route/SK owners.
    monkeypatch.setitem(sys.modules, "route_backend_chats", module(
        "route_backend_chats", _persist_screened_assistant=persist,
    ))
    item = state.request_for(
        "actor", "conversation", credentials.manifest_reference(raw), contracts.credential_fingerprint(raw),
        {"service": "api_key"}, reason="setup_required", continuation=descriptor,
    )
    ready = state.replace("actor", item, {"status": "ready"}, item["_etag"])
    app = Flask("credential-classic")
    app.secret_key = "local-test-only"
    bp = Blueprint("credential-classic", __name__)
    routes.register_route_backend_action_credentials(bp)
    app.register_blueprint(bp)
    client = app.test_client()
    path = f"/api/action-credentials/{item['id']}"
    info = client.get(path)
    assert info.status_code == 200
    response = client.post(
        path + "/continue", json={"expected_etag": ready["_etag"]},
        headers={"X-CSRFToken": info.json["csrf_token"]},
    )
    assert response.status_code == 200 and response.mimetype == "text/event-stream"
    events = response.get_data(as_text=True)
    assert '"done": true' in events and '"content":' in events
    assert len(persisted) == 1
    assert state.read("actor", item["id"])["status"] == "completed"
    repeated = client.post(
        path + "/continue", json={"expected_etag": ready["_etag"]},
        headers={"X-CSRFToken": info.json["csrf_token"]},
    )
    assert repeated.status_code == 409
    assert len(persisted) == 1


def test_real_sk_pause_preserves_completed_tool_results_and_resumes_only_blocked_call(runtime, monkeypatch):
    contracts = importlib.import_module("action_credential_contracts")
    state = importlib.import_module("functions_action_credential_state")
    credentials = importlib.import_module("functions_action_credentials")
    store = CredentialContainer("user_id")
    monkeypatch.setattr(state, "_container", store)
    descriptor = {
        "mode": "orchestration", "checkpoint_id": "checkpoint_tools", "run_id": "run", "step_id": "step",
    }
    effects, available = [], [False]

    def lookup(ticket):
        if ticket == "43" and not available[0]:
            raise contracts.ActionCredentialsRequired({
                "id": "request", "status": "pending", "conversation_id": "conversation",
                "requirements": [{"slot": "service", "auth_type": "api_key"}],
            })
        effects.append(ticket)
        return {"ticket": ticket, "status": "open"}

    runtime.lookup_value = lookup
    runtime.replies = [tool_message("42"), tool_message("43")]
    with credentials.credential_continuation(descriptor), pytest.raises(contracts.ActionCredentialsRequired):
        asyncio.run(execute(runtime))
    assert effects == ["42"]
    checkpoint = state.read("actor", "checkpoint_tools")
    assert "simplechat_action_credentials_waiting" in checkpoint["value"]["action"]["history"]
    assert "42" in checkpoint["value"]["action"]["history"]
    descriptor["resume"] = True
    available[0] = True
    # The first invocation closes its model client; the scripted local provider remains usable.
    with credentials.credential_continuation(descriptor):
        result = asyncio.run(execute(runtime))
    assert effects == ["42", "43"]
    assert result["calls"] == 1
    assert "42" in runtime.requests[-1]
    assert "PRIVATE_CONFIG" not in checkpoint["value"]["action"]["history"]


def test_shared_actions_and_unused_personal_tools_do_not_depend_on_private_storage(runtime, monkeypatch):
    state = importlib.import_module("functions_action_credential_state")
    credentials = importlib.import_module("functions_action_credentials")
    continuation = importlib.import_module("functions_action_credential_continuation")
    container = CredentialContainer("user_id")
    monkeypatch.setattr(state, "_container", container)

    def unavailable(*args, **kwargs):
        raise AssertionError("Unused personal credentials caused a private-state read.")

    monkeypatch.setattr(state, "read", unavailable)
    runtime.replies = [tool_message("42")]
    with credentials.credential_continuation({"mode": "orchestration", "checkpoint_id": "new-shared-step"}):
        shared_result = asyncio.run(execute(runtime))
    assert shared_result["calls"] == 1
    assert not container.items

    class UnusedPersonalAction:
        manifest = manifest()

        @kernel_function
        async def lookup(self, ticket: str) -> str:
            raise AssertionError("An attached-but-unused action was invoked.")

    kernel = Kernel()
    kernel.add_service(runtime.service)
    kernel.add_plugin(UnusedPersonalAction(), plugin_name="unused")
    agent = ChatCompletionAgent(name="Reader", kernel=kernel, instructions="Answer without using a tool.")
    frame = runtime.contexts.AgentExecutionFrame(
        runtime.context.agent_execution_identity, {"id": "reader"}, runtime.contexts.DelegationBudget(),
    )

    async def invoke():
        with runtime.contexts.agent_execution(frame), credentials.credential_continuation({
            "mode": "chat", "checkpoint_id": "new-unused-turn",
        }):
            return await continuation.invoke_credential_agent(
                agent, [ChatMessageContent(role="user", content="Give a short answer.")],
            )

    result = asyncio.run(invoke())
    assert result is not None
    assert not container.items


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
def test_real_sk_classic_and_nested_threads_retain_completed_tools(runtime, monkeypatch, nested, streaming):
    contracts = importlib.import_module("action_credential_contracts")
    state = importlib.import_module("functions_action_credential_state")
    credentials = importlib.import_module("functions_action_credentials")
    continuation = importlib.import_module("functions_action_credential_continuation")
    screening = importlib.import_module("content_screening.access")
    revoked = [False]
    monkeypatch.setattr(screening, "current_request_source_provenance",
                        lambda: [{"document_id": "consumed-document", "scope": "personal", "scope_id": "actor"}])

    def source_access(source, *, user_id, purpose):
        assert user_id == "actor" and purpose == "model"
        if revoked[0]:
            raise PermissionError("Document access was revoked.")

    monkeypatch.setattr(screening, "assert_document_available", source_access)
    monkeypatch.setattr(state, "_container", CredentialContainer("user_id"))
    descriptor = {"mode": "chat", "checkpoint_id": "checkpoint_agents"}
    frame = runtime.contexts.AgentExecutionFrame(
        runtime.context.agent_execution_identity, {"id": "parent"}, runtime.contexts.DelegationBudget(),
    )
    effects, connected = [], [False]

    class Tickets:
        manifest = manifest()

        @kernel_function
        async def lookup(self, ticket: str) -> str:
            if ticket == "43" and not connected[0]:
                raise contracts.ActionCredentialsRequired({"id": "request", "status": "pending"})
            effects.append(ticket)
            return json.dumps({"ticket": ticket})

    child_kernel = Kernel()
    child_kernel.add_service(runtime.service)
    tickets = Tickets()
    child_kernel.add_plugin(tickets, plugin_name="tickets")
    child = ChatCompletionAgent(
        name="Child", kernel=child_kernel, instructions="Read the requested tickets.",
        function_choice_behavior=FunctionChoiceBehavior.Auto(),
    )
    parent = child
    if nested:
        class Delegate:
            @kernel_function
            async def call(self, task: str) -> str:
                with runtime.contexts.agent_execution(replace(frame, depth=1)):
                    result = await continuation.invoke_credential_agent(
                        child, [ChatMessageContent(role="user", content=task)],
                    )
                    return str(result)

        parent_kernel = Kernel()
        parent_kernel.add_service(runtime.service)
        parent_kernel.add_plugin(Delegate(), plugin_name="delegate")
        parent = ChatCompletionAgent(
            name="Parent", kernel=parent_kernel, instructions="Ask the child to read tickets.",
            function_choice_behavior=FunctionChoiceBehavior.Auto(),
        )
        runtime.replies = [ChatMessageContent(role="assistant", items=[
            FunctionCallContent(id="child-call", name="delegate-call", arguments='{"task":"Read tickets 42 and 43"}'),
        ])]
    runtime.replies.extend([tool_message("42"), tool_message("43")])

    if streaming:
        async def local_stream(self, **kwargs):
            async for result in self.invoke(**kwargs):
                yield result

        monkeypatch.setattr(ChatCompletionAgent, "invoke_stream", local_stream)

    async def run(messages):
        with runtime.contexts.agent_execution(frame), credentials.credential_continuation(descriptor):
            if streaming:
                return [item async for item in continuation.stream_credential_agent(parent, messages)]
            return await continuation.invoke_credential_agent(parent, messages)

    with pytest.raises(contracts.ActionCredentialsRequired):
        asyncio.run(run([ChatMessageContent(role="user", content="Read tickets 42 and 43")]))
    assert effects == ["42"]
    saved = state.read("actor", descriptor["checkpoint_id"])["value"]
    assert "root" in saved
    assert len(saved) == (2 if nested else 1)
    assert saved["root"]["sources"]
    descriptor["resume"] = True
    before = len(runtime.requests)
    instructions = child.instructions
    child.instructions += " Configuration changed."
    with pytest.raises(contracts.ActionCredentialError) as changed:
        asyncio.run(run(None))
    assert changed.value.code == "credential_execution_changed"
    assert len(runtime.requests) == before
    assert effects == ["42"]
    child.instructions = instructions
    from functions_action_manifest import bind_action_origin

    original_manifest = tickets.manifest
    tickets.manifest = bind_action_origin(dict(original_manifest), "group", "other-team")
    with pytest.raises(contracts.ActionCredentialError):
        asyncio.run(run(None))
    assert len(runtime.requests) == before
    tickets.manifest = original_manifest
    model = runtime.service.ai_model_id
    runtime.service.ai_model_id = "different-model"
    with pytest.raises(contracts.ActionCredentialError):
        asyncio.run(run(None))
    assert len(runtime.requests) == before
    runtime.service.ai_model_id = model
    revoked[0] = True
    with pytest.raises(PermissionError):
        asyncio.run(run(None))
    assert len(runtime.requests) == before
    assert effects == ["42"]
    revoked[0] = False
    connected[0] = True
    if not nested and not streaming:
        continue_classic_route(runtime, monkeypatch, parent, descriptor)
    else:
        asyncio.run(run(None))
    assert effects == ["42", "43"]
    completed = state.read("actor", descriptor["checkpoint_id"])["value"]
    assert completed["root"]["completed"] is True
    before = len(runtime.requests)
    repeated = asyncio.run(run(None))
    assert repeated
    assert len(runtime.requests) == before
    assert effects == ["42", "43"]
