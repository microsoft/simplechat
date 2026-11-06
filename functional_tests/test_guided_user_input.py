# test_guided_user_input.py
"""Functional tests for open questions and real local-agent pause/resume.

Version: 0.261.411
Implemented in: 0.261.411
Uses the installed SK loop and SDK-default Cosmos doubles, never a provider network.
"""

import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.contents import ChatMessageContent, FunctionCallContent
from semantic_kernel.functions import kernel_function

from test_support.app_stubs import stubbed_app_imports
from test_support.versioning import assert_app_version_at_least
from test_action_personal_credentials import CredentialContainer
from test_action_credentials_sk_continuation import continuation_services, runtime  # noqa: F401


def question_spec():
    return {
        "message": "Three details are needed to continue.",
        "requested_schema": {
            "type": "object",
            "properties": {
                "audience": {"type": "string", "title": "Who is this for?"},
                "focus": {"type": "array", "items": {"type": "string"}, "title": "What matters?"},
                "format": {"type": "string", "enum": ["brief", "full"], "title": "Which format?"},
            },
            "required": ["audience", "focus", "format"],
        },
        "ui_hints": {"fields": {
            "audience": {"input": "choices", "choices": ["Team", "Leadership"], "allow_custom": True},
            "focus": {"input": "choices", "choices": ["Risks", "Timeline"], "allow_custom": True},
        }},
    }


def test_open_suggestions_do_not_weaken_closed_enums():
    assert_app_version_at_least("0.261.411")
    with stubbed_app_imports():
        schema = importlib.import_module("functions_orchestration_schema")
        question = schema.normalize_elicitation(question_spec(), "test-run")
        response, errors = schema.validate_elicitation_response(question, {
            "action": "accept", "content": {"audience": "Partners", "focus": ["Risks", "Costs"], "format": "brief"},
        })
        assert not errors
        assert response["content"]["audience"] == "Partners"
        invalid, errors = schema.validate_elicitation_response(question, {
            "action": "accept", "content": {**response["content"], "format": "invented"},
        })
        assert invalid is None and errors
        question_specification = question_spec()
        question_specification["ui_hints"]["fields"]["format"] = {
            "input": "choices", "choices": ["brief"], "allow_custom": True,
        }
        with pytest.raises(schema.PlanValidationError):
            schema.normalize_elicitation(question_specification, "test-run")


@pytest.fixture
def input_runtime(runtime, continuation_services, monkeypatch):
    schema = importlib.import_module("functions_orchestration_schema")
    owner = importlib.import_module("functions_user_input")
    state = importlib.import_module("functions_action_credential_state")
    credentials = importlib.import_module("functions_action_credentials")
    continuation = importlib.import_module("functions_action_credential_continuation")
    stops = importlib.import_module("agent_interaction_contracts")
    store = CredentialContainer("user_id")
    monkeypatch.setattr(state, "_container", store)

    def authorize(user_id, conversation_id):
        if (user_id, conversation_id) != ("actor", "conversation"):
            raise PermissionError("Not this actor's conversation.")
        return {"id": conversation_id, "user_id": user_id}

    def unused(*args, **kwargs):
        raise AssertionError("Question handling must not access credentials.")

    monkeypatch.setattr(credentials, "_services", credentials.CredentialServices(
        current_user_id=lambda: "actor", authorize_conversation=authorize,
        resolve_manifest=unused, read_identity=unused, list_identities=unused,
        identity_supports_usage=unused, read_identity_auth=unused, create_identity=unused, update_identity=unused,
    ))

    def normalize_answer(question, response, context, user_id, conversation_id):
        authorize(user_id, conversation_id)
        normalized, errors = schema.validate_elicitation_response(question, response)
        if errors:
            raise owner.UserInputError("input_invalid", 400)
        return normalized, context if normalized["action"] == "accept" else {}

    monkeypatch.setattr(owner, "_services", owner.UserInputServices(
        lambda spec, checkpoint_id: schema.normalize_elicitation(spec, checkpoint_id),
        normalize_answer,
    ))
    effects = []

    class Tickets:
        @kernel_function
        def lookup(self, ticket: str) -> str:
            effects.append(ticket)
            return "A retained result"

    def make_agent():
        kernel = Kernel()
        kernel.add_service(runtime.service)
        kernel.add_plugin(Tickets(), plugin_name="tickets")
        return kernel, ChatCompletionAgent(
            name="Reader", instructions="Use the answers to finish the task.", kernel=kernel,
            function_choice_behavior=FunctionChoiceBehavior.Auto(),
        )

    kernel, agent = make_agent()
    descriptor = {
        "mode": "chat", "checkpoint_id": "input-test-checkpoint", "user_input_enabled": True,
        "agent_reference": {"id": "reader"},
    }
    frame = runtime.contexts.AgentExecutionFrame(
        runtime.context.agent_execution_identity, {"id": "reader", "name": "Reader"},
        runtime.contexts.DelegationBudget(),
    )

    async def invoke():
        with runtime.contexts.agent_execution(frame), credentials.credential_continuation(descriptor):
            return await continuation.invoke_credential_agent(
                agent, None if descriptor.get("resume") else [ChatMessageContent(role="user", content="Prepare the brief.")],
            )

    def call(name, arguments, call_id):
        return ChatMessageContent(role="assistant", items=[
            FunctionCallContent(id=call_id, name=name, arguments=json.dumps(arguments)),
        ])

    runtime.replies = [
        call("tickets-lookup", {"ticket": "completed-before-question"}, "before"),
        call("UserInput-request_user_input", {"specification": json.dumps(question_spec())}, "question-call"),
        call("tickets-lookup", {"ticket": "after-answers"}, "after"),
    ]
    return SimpleNamespace(
        invoke=invoke, owner=owner, state=state, stop=stops.UserInputRequired, effects=effects,
        descriptor=descriptor, store=store, kernel=kernel, continuation=continuation,
        make_agent=make_agent, identity=runtime.context.agent_execution_identity, runtime=runtime,
    )


def test_real_sk_questions_resume_only_paused_calls(input_runtime):
    env = input_runtime
    with pytest.raises(env.stop) as stopped:
        asyncio.run(env.invoke())
    assert env.effects == ["completed-before-question"]
    request_id = stopped.value.input_request["id"]
    checkpoint = env.state.read("actor", env.descriptor["checkpoint_id"])
    assert "completed-before-question" in checkpoint["value"]["root"]["history"]
    body = {
        "revision": 1, "submission_id": "answers-once",
        "response": {"action": "accept", "content": {
            "audience": "Partners", "focus": ["Risks", "Costs"], "format": "brief",
        }},
        "context": {},
    }
    saved = env.owner.answer_request("actor", request_id, body)
    repeated = env.owner.answer_request("actor", request_id, body)
    assert saved["_etag"] == repeated["_etag"]
    env.descriptor["resume"] = True
    result = asyncio.run(env.invoke())
    assert result is not None
    assert env.effects == ["completed-before-question", "after-answers"]
    repeated_result = asyncio.run(env.invoke())
    assert str(repeated_result) == str(result)
    assert env.effects == ["completed-before-question", "after-answers"]
    changed = {**body, "submission_id": "different"}
    with pytest.raises(env.owner.UserInputError):
        env.owner.answer_request("actor", request_id, changed)
    with pytest.raises(LookupError):
        env.owner.read_request("someone-else", request_id)


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_refusals_do_not_forward_drafted_answers(input_runtime, action):
    env = input_runtime
    with pytest.raises(env.stop) as stopped:
        asyncio.run(env.invoke())
    request_id = stopped.value.input_request["id"]
    saved = env.owner.answer_request("actor", request_id, {
        "revision": 1, "submission_id": "refusal",
        "response": {"action": action, "content": {"audience": "DO NOT FORWARD"}},
        "context": {"audience": {"text": "DO NOT FORWARD"}},
    })
    assert saved["response"] == {"action": action, "content": {}}
    assert saved["answer_context"] == {}
    assert env.effects == ["completed-before-question"]


def test_noninteractive_agents_do_not_gain_the_tool(input_runtime):
    env = input_runtime
    env.descriptor["user_input_enabled"] = False
    asyncio.run(env.invoke())
    assert "UserInput" not in env.kernel.plugins


def test_workflow_execution_cannot_inherit_an_interactive_tool(input_runtime):
    env = input_runtime
    contexts = importlib.import_module("agent_execution_context")
    with contexts.workflow_identity_scope(env.identity):
        asyncio.run(env.invoke())
    assert "UserInput" not in env.kernel.plugins


def test_question_failure_cannot_be_interpreted_as_a_successful_tool_result(input_runtime, monkeypatch):
    env = input_runtime
    monkeypatch.setattr(env.owner, "_services", None)
    with pytest.raises(env.owner.UserInputError):
        asyncio.run(env.invoke())
    assert env.effects == ["completed-before-question"]
