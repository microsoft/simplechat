# test_orchestration_m365_actions.py
#!/usr/bin/env python3
"""
Functional test for Microsoft 365 actions in chat orchestration.
Version: 0.261.321
Implemented in: 0.261.238
Shared conversations read for their real audience, with the request as consent, in: 0.261.270
Policy-governed operation intent and recovery added in: 0.261.321

An orchestration "Use an action" step runs in its own request context, the execution
identity's bridge. Before 0.261.238 no Microsoft 365 execution context existed there, so
every Microsoft 365 function refused the call with ``m365_context_required`` before reaching
Microsoft Graph, and the step still reported completed. Before 0.261.270 a step in a shared
conversation was refused outright (microsoft/simplechat#1659).

These tests run the real action runner, step scope, Microsoft 365 runtime, execution
boundary, approval service and email plugin through a real Flask bridge. Storage, tokens,
Microsoft Graph and the model are doubled, and network access is blocked.
"""

import asyncio
import importlib
import json
import logging
import socket
import sys
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from flask import Flask, g, session
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

from test_support.m365 import CosmosContainer  # noqa: E402 - the test path is set above

USER, TENANT, CONVERSATION = "user-1", "tenant-1", "conversation-1"
ACTION_REF = "action:v1:personal:user-1:mail"
ROOT_RUN, STEP = "run-root", "retrieve_latest_emails"
REQUEST_KEY = f"{ROOT_RUN}\x00{STEP}"
MESSAGES = {"value": [{
    "id": "message-1", "subject": "Quarterly review", "isRead": False,
    "from": {"emailAddress": {"name": "Ada", "address": "ada@example.test"}},
    "receivedDateTime": "2026-10-05T16:00:00Z", "bodyPreview": "Agenda attached.",
}]}


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


def is_app_module(value):
    path = getattr(value, "__file__", None)
    try:
        return bool(path) and Path(path).resolve().is_relative_to(APP)
    except (OSError, ValueError):
        return False


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.body = json.dumps(payload).encode()
        self.headers = {"Content-Type": "application/json"}

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


def mail_action(**capabilities):
    return {
        "id": "mail", "name": "m365_email", "display_name": "Mail", "type": "m365_email",
        "description": "Read recent mail.", "action_ref": ACTION_REF,
        "scope_type": "personal", "scope_id": USER, "user_id": USER, "is_enabled": True,
        "additionalFields": {"m365_capabilities": {"get_my_messages": True, **capabilities}},
    }


def stub_modules(state):
    def read_conversation(item, partition_key):
        if item != CONVERSATION or partition_key != CONVERSATION:
            raise AssertionError("Only the step's own conversation may be read")
        return deepcopy(state.conversation)

    def participation(user_id, conversation):
        return dict(state.participation)

    return {
        "config": module(
            "config", TENANT_ID=TENANT,
            cosmos_conversations_container=SimpleNamespace(read_item=read_conversation),
            cosmos_m365_execution_runs_container=state.jobs,
            cosmos_msgraph_pending_actions_container=None,
        ),
        "functions_appinsights": module(
            "functions_appinsights",
            log_event=lambda message, *args, **kwargs: state.logs.append((message, kwargs.get("extra") or {})),
            debug_print=lambda *args, **kwargs: None, is_debug_enabled=lambda *args, **kwargs: False,
            get_appinsights_logger=lambda: logging.getLogger("test_orchestration_m365"),
            workflow_log_context=lambda **kwargs: {},
        ),
        "functions_activity_logging": module("functions_activity_logging"),
        "functions_settings": module(
            "functions_settings", get_settings=lambda: deepcopy(state.settings),
            get_user_settings=lambda user_id: {"id": user_id, "settings": {}},
            update_settings=lambda payload: True, sanitize_settings_for_user=lambda values: dict(values),
        ),
        "functions_authentication": module(
            "functions_authentication", AZURE_ENVIRONMENT="public", CUSTOM_GRAPH_URL_VALUE="",
            get_graph_base_url=lambda: "https://graph.microsoft.com/v1.0",
            get_graph_authority=lambda: f"https://login.microsoftonline.com/{TENANT}",
            get_current_user_info=lambda: {"userId": USER}, get_current_user_id=lambda: USER,
        ),
        "functions_group": module(
            "functions_group", assert_group_role=lambda *args, **kwargs: None,
            find_group_by_id=lambda *args: None, require_active_group=lambda *args: None,
            get_user_groups=lambda user_id: [],
        ),
        "functions_collaboration": module(
            "functions_collaboration", build_conversation_participation_context=participation,
            get_collaboration_conversation=lambda shared_id: {"id": shared_id, "participants": [USER]},
            assert_user_can_participate_in_collaboration_conversation=lambda *args: None,
        ),
        "functions_action_catalog": module(
            "functions_action_catalog",
            resolve_action_manifest=lambda user_id, action_ref, **kwargs: state.resolve(user_id, action_ref),
            build_action_planner_projection=lambda actions: [],
        ),
        "functions_personal_actions": module(
            "functions_personal_actions", get_personal_actions=lambda user_id, **kwargs: [deepcopy(state.action)],
        ),
        "functions_global_actions": module("functions_global_actions", get_global_actions=lambda **kwargs: []),
        "functions_group_actions": module(
            "functions_group_actions", get_governed_group_actions=lambda *args, **kwargs: [],
            get_group_actions=lambda *args, **kwargs: [],
        ),
        "functions_personal_agents": module(
            "functions_personal_agents",
            get_personal_agents=lambda user_id: deepcopy(getattr(state, "agents", [])) if user_id == USER else [],
        ),
        "functions_global_agents": module("functions_global_agents", get_global_agents=lambda: []),
        "functions_group_agents": module("functions_group_agents", get_group_agents=lambda group_id: []),
        "functions_governance": module(
            "functions_governance",
            filter_actions_by_action_type_access=lambda user_id, actions, *args: actions,
            filter_governed_global_actions_for_user=lambda user_id, actions: actions,
        ),
        "functions_keyvault": module("functions_keyvault", SecretReturnType=SimpleNamespace(NAME="name")),
        "semantic_kernel_loader": module(
            "semantic_kernel_loader",
            get_max_auto_invoke_attempts=lambda settings: 5,
            prepare_action_plugin_manifest=lambda manifest, settings: state.prepare(manifest),
        ),
        "semantic_kernel_plugins.logged_plugin_loader": module(
            "semantic_kernel_plugins.logged_plugin_loader",
            create_logged_plugin_loader=lambda kernel: state.loader(kernel),
        ),
    }


@pytest.fixture(scope="module")
def env():
    """Fresh copies of the real modules, bound to the doubles and discarded afterward."""
    state = SimpleNamespace(jobs=CosmosContainer("user_id"), logs=[], settings={})
    with patch.dict(sys.modules):
        for name in [name for name, value in list(sys.modules.items()) if is_app_module(value)]:
            sys.modules.pop(name)
        sys.modules.update(stub_modules(state))
        modules = SimpleNamespace(
            state=state,
            actions=importlib.import_module("functions_orchestration_actions"),
            adapters=importlib.import_module("functions_orchestration_adapters"),
            orchestration=importlib.import_module("functions_orchestration_m365"),
            runtime=importlib.import_module("functions_m365_runtime"),
            execution=importlib.import_module("functions_m365_execution"),
            connections=importlib.import_module("functions_m365_connections"),
            approvals=importlib.import_module("functions_m365_approvals"),
            contexts=importlib.import_module("agent_execution_context"),
            capture=importlib.import_module("functions_orchestration_invocation_capture"),
            schema=importlib.import_module("functions_orchestration_schema"),
            history=importlib.import_module("functions_m365_history"),
            email=importlib.import_module("semantic_kernel_plugins.m365_email_plugin"),
        )
        modules.execution.configure_m365_execution(
            action_config_resolver=modules.runtime.resolve_m365_action_config,
            action_selection_resolver=modules.runtime.resolve_m365_action_selection,
        )
        yield modules


@pytest.fixture
def world(env, monkeypatch):
    real_connect = socket.socket.connect

    def local_only(sock, address, *args, **kwargs):
        # The Windows asyncio loop wakes itself through a loopback socket pair.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return real_connect(sock, address, *args, **kwargs)
        raise AssertionError("Tests must not contact external services")

    monkeypatch.setattr(socket.socket, "connect", local_only)
    state = env.state
    state.__dict__.clear()
    state.__dict__.update(
        jobs=CosmosContainer("user_id"), logs=[], requests=[], replies=[], graph_calls=[],
        token_requests=[], loaded_functions=[], token_error=None, graph_error=None,
        graph_response=(200, MESSAGES), participation={}, action=mail_action(send_mail=True),
        conversation={"id": CONVERSATION, "user_id": USER},
        settings={
            "enable_chat_orchestration": True, "enable_chat_orchestration_actions": True,
            "enable_semantic_kernel": True, "max_auto_invoke_attempts": 5,
        },
    )
    env.runtime.cosmos_m365_execution_runs_container = state.jobs
    sys.modules["config"].cosmos_m365_execution_runs_container = state.jobs

    def resolve(user_id, action_ref):
        if user_id != USER or action_ref != ACTION_REF:
            raise PermissionError("The action is unavailable.")
        return deepcopy(state.action)

    def prepare(manifest):
        # The loader's own Microsoft 365 preflight, which narrows the action to the selection.
        manifests = [deepcopy(manifest)]
        if env.execution.get_m365_execution_context() is not None:
            manifests = env.execution.preflight_m365_manifests(manifests)
        if len(manifests) != 1:
            raise PermissionError("The selected action is not available for this execution.")
        return manifests[0]

    class Loader:
        def __init__(self, kernel):
            self.kernel = kernel
            self.plugin_instances = []

        def load_plugin_from_manifest(self, manifest, user_id):
            plugin = env.email.M365EmailPlugin(deepcopy(manifest))
            state.loaded_functions.append(sorted(plugin.get_functions()))
            self.plugin_instances.append(plugin)
            self.kernel.add_plugin(plugin.get_kernel_plugin("m365_email"))
            return True

    def token(scopes, context=None, *, include_auth_url=True):
        context = context or env.connections.get_m365_execution_context()
        state.token_requests.append({
            "scopes": list(scopes), "request_id": context.request_id,
            "actor": context.actor_user_id, "data": context.data_user_id,
            "conversation": context.conversation_id, "shared": context.shared,
            "session_user": (session.get("user") or {}).get("oid"),
        })
        if state.token_error:
            return {"error": state.token_error, "message": "Sign in again.", "scopes": list(scopes)}
        return {"access_token": "delegated-token"}

    def graph(method, url, **kwargs):
        state.graph_calls.append({"method": method, "url": url, "authorization": kwargs["headers"]["Authorization"]})
        if state.graph_error is not None:
            raise state.graph_error
        status, payload = state.graph_response
        return FakeResponse(payload, status)

    async def reply(service, history, settings):
        state.requests.append(str(history))
        if state.replies:
            return [state.replies.pop(0)]
        return [ChatMessageContent(role=AuthorRole.ASSISTANT, content="Ada sent Quarterly review.")]

    state.resolve, state.prepare, state.loader = resolve, prepare, Loader
    monkeypatch.setattr(env.connections, "get_m365_access_token", token)
    monkeypatch.setattr(requests, "request", graph)
    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", reply)
    state.service = AzureChatCompletion(
        service_id="orchestration-action", deployment_name="test-model",
        endpoint="https://example.invalid", api_key="not-a-real-key", api_version="2024-10-21",
    )
    monkeypatch.setattr(env.actions, "_build_action_model", lambda *args, capture_configuration=False: (
        (state.service, {"provider": "aoai", "parameters": {}}) if capture_configuration else state.service
    ))
    app = Flask(__name__)
    app.secret_key = "test-secret-key-for-orchestration-m365-tests"
    state.app = app
    yield state
    if not state.service.client.is_closed():
        asyncio.run(state.service.client.close())


def tool_call(function="m365_email-get_my_messages", **arguments):
    return ChatMessageContent(
        role=AuthorRole.ASSISTANT,
        items=[FunctionCallContent(id="call-1", name=function, arguments=json.dumps(arguments or {"top": 2}))],
    )


def run_step(
    env, world, *, request_key=REQUEST_KEY, captured=None, execution_intent='gather', journal=None, named_inputs=None,
):
    """Run the action step the way orchestration does: inside the signed-in request."""
    with world.app.test_request_context("/api/v2/orchestration/run", base_url="https://simplechat.example"):
        session["user"] = {"oid": USER, "tid": TENANT, "roles": ["User"], "preferred_username": "user@example.test"}
        identity = env.contexts.capture_execution_identity(USER, CONVERSATION)
    context = SimpleNamespace(
        action_catalog=[{key: world.action[key] for key in (
            "action_ref", "id", "name", "display_name", "description", "type", "scope_type", "scope_id",
        )}],
        active_group_ids=[], token_usage={}, notes=[], user_id=USER, conversation_id=CONVERSATION,
        agent_execution_identity=identity, delegation_budget=env.contexts.DelegationBudget(),
    )

    def capture(source_type, *, settings, source=None, selector=None):
        if captured is not None:
            captured.append((source_type, selector))
        return None if source is None else {"captured": True}

    invocation_capture = env.capture.OrchestrationInvocationCapture(capture)
    from functions_orchestration_operations import operation_journal_scope

    with operation_journal_scope(journal, complete_inputs=bool(named_inputs)):
        result = asyncio.run(env.actions.invoke_action(
            ACTION_REF, "Complete the requested mail task.", context, settings=deepcopy(world.settings),
            user_id=USER, cancel_requested=lambda: False, invocation_capture=invocation_capture,
            m365_request_key=request_key, execution_intent=execution_intent,
            named_inputs=named_inputs,
            m365_origin={"run_id": "run-2", "attempt_index": 2, "step_id": STEP},
        ))
    return result, context


def stopped(env, world, **kwargs):
    with pytest.raises(env.orchestration.OrchestrationM365Error) as caught:
        run_step(env, world, **kwargs)
    return caught.value


def request_record(env, world, request_key=REQUEST_KEY):
    return world.jobs.read_item(env.orchestration.step_request_id(request_key), partition_key=USER)


def test_email_action_step_reads_mail_through_its_own_step_context(env, world):
    world.replies = [tool_call()]
    captured = []
    result, context = run_step(env, world, captured=captured)

    request_id = env.orchestration.step_request_id(REQUEST_KEY)
    assert result["calls"] == 1
    assert "Quarterly review" in result["findings"]
    assert [call["url"] for call in world.graph_calls] == [
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
    ]
    assert world.graph_calls[0]["authorization"].endswith("delegated-token")
    # The sign-in check runs before the model; the Graph call reuses the same step request.
    assert len(world.token_requests) == 2
    assert all(request == {
        "scopes": request["scopes"], "request_id": request_id, "actor": USER, "data": USER,
        "conversation": CONVERSATION, "shared": False, "session_user": USER,
    } for request in world.token_requests)
    assert request_id.startswith("orch-") and request_id == env.orchestration.step_request_id(REQUEST_KEY)
    record = request_record(env, world)
    assert record["status"] == "completed"
    assert record["conversation_id"] == CONVERSATION and record["actor_user_id"] == USER
    assert record["workflow_id"] is None and "approval_id" not in record
    assert record["orchestration"] == {
        "run_id": "run-2", "attempt_index": 2, "step_id": STEP, "capability_id": "action_invoke",
    }
    assert captured and all(item == ("action", ACTION_REF) for item in captured)
    invocation = result["invocations"][0]
    assert invocation.function_name == "get_my_messages"
    assert invocation.result["source"] == "email"
    assert not any("m365_context_required" in json.dumps(extra, default=str) for _message, extra in world.logs)


def test_plans_never_see_send_or_read_state_functions(env, world):
    world.action = mail_action(send_mail=True, mark_message_as_read=True)
    world.replies = [tool_call()]
    run_step(env, world)
    assert world.loaded_functions == [["get_my_messages"]]


def test_missing_sign_in_stops_the_step_before_the_model_or_graph(env, world):
    world.token_error = "interactive_auth_required"
    error = stopped(env, world)

    assert error.orchestration_failure_code == "m365_sign_in_required"
    assert error.m365_code == "interactive_auth_required"
    assert error.m365_sources == ("email",)
    assert world.requests == [] and world.graph_calls == [] and world.loaded_functions == []
    assert request_record(env, world)["status"] == "failed"
    failure = env.schema.failure_from_exception(error)
    assert failure == {
        "code": "m365_sign_in_required",
        "message": env.schema.FAILURE_MESSAGES["m365_sign_in_required"],
        "m365_sources": ["email"],
    }
    stop_logs = [extra for message, extra in world.logs if "A Microsoft 365 step stopped" in message]
    assert stop_logs == [{
        "failure_code": "m365_sign_in_required", "authority_reason": "interactive_auth_required",
        "capability_id": "action_invoke", "source_count": 1,
    }]


def test_rejected_graph_sign_in_fails_the_step_instead_of_becoming_findings(env, world):
    world.graph_response = (401, {"error": {"code": "InvalidAuthenticationToken"}})
    world.replies = [tool_call()]
    error = stopped(env, world)

    assert error.orchestration_failure_code == "m365_sign_in_required"
    assert error.m365_code == "authentication_required"
    assert error.m365_sources == ("email",)
    assert len(world.graph_calls) == 1
    assert request_record(env, world)["status"] == "failed"


def test_ordinary_graph_outcomes_stay_findings(env, world):
    world.graph_response = (404, {"error": {"code": "ErrorItemNotFound"}})
    world.replies = [tool_call()]
    result, _context = run_step(env, world)
    assert result["calls"] == 1
    assert request_record(env, world)["status"] == "completed"


def test_shared_conversation_step_reads_mail_with_the_requests_own_consent(env, world, monkeypatch):
    """A shared conversation's step reads for its real audience; asking for the mail is the consent."""
    approvals = CosmosContainer()
    monkeypatch.setattr(env.approvals, "_service", env.approvals.M365ApprovalService(
        container_factory=lambda: approvals, notification_sender=lambda approval: None,
    ))
    world.participation = {"collaboration_conversation_id": "shared-1"}
    world.replies = [tool_call()]
    result, _context = run_step(env, world)

    request_id = env.orchestration.step_request_id(REQUEST_KEY)
    assert result["calls"] == 1 and "Quarterly review" in result["findings"]
    assert len(world.graph_calls) == 1
    assert world.token_requests and all(request["shared"] is True for request in world.token_requests)
    records = list(approvals.items.values())
    # One audit event says the requester shared their mail by asking; no approval is waiting.
    assert [(record["event_type"], record["source"]) for record in records] == [("shared_by_request", "email")]
    assert records[0]["context"]["request_id"] == request_id and records[0]["context"]["shared"] is True
    assert request_record(env, world)["status"] == "completed"


def test_shared_conversation_step_still_needs_a_current_participant(env, world):
    world.participation = {"collaboration_conversation_id": "shared-1"}

    def removed(*args):
        raise PermissionError("You are no longer a participant in this conversation.")

    with patch.object(env.runtime, "assert_user_can_participate_in_collaboration_conversation", removed):
        with pytest.raises(PermissionError):
            run_step(env, world)
    assert world.token_requests == [] and world.requests == [] and world.graph_calls == []


def test_send_only_action_is_refused_as_read_only(env, world):
    world.action = {**mail_action(send_mail=True), "additionalFields": {
        "m365_capabilities": {"get_my_messages": False, "send_mail": True},
    }}
    error = stopped(env, world)
    assert error.orchestration_failure_code == "m365_read_only"
    assert world.token_requests == [] and world.requests == [] and world.jobs.items == {}


def test_approval_stop_is_recorded_and_a_retry_reuses_the_request(env, world, monkeypatch):
    approval = {
        "id": "m365-approval-1", "request_type": env.approvals.TYPE_EXTENDED_ANALYSIS,
        "subject_user_id": USER, "resume_key": "resume", "execution_status": None,
    }
    service = env.runtime.get_m365_approval_service()
    reported = []

    class ReportingApprovals:
        def __getattr__(self, name):
            return getattr(service, name)

        def record_execution_status(self, *arguments):
            reported.append(arguments)

    monkeypatch.setattr(env.runtime, "get_m365_approval_service", ReportingApprovals)
    world.graph_error = env.approvals.M365ApprovalRequired(approval)
    world.replies = [tool_call()]
    error = stopped(env, world)

    assert error.orchestration_failure_code == "m365_approval_required"
    assert error.approval_id == "m365-approval-1"
    record = request_record(env, world)
    # A decision on this approval sees a stopped step, so it never resumes a chat request.
    assert record["status"] == "failed" and record["approval_id"] == "m365-approval-1"
    # The approval is still waiting for its decision, so the stop is not reported on it.
    assert reported == []

    # A retry that stops for another approval reports nothing either, as a paused chat doesn't.
    world.graph_error = env.approvals.M365ApprovalRequired({**approval, "id": "m365-approval-2"})
    world.replies = [tool_call()]
    assert stopped(env, world).approval_id == "m365-approval-2"
    assert request_record(env, world)["approval_id"] == "m365-approval-2"
    assert reported == []

    world.graph_error = None
    world.replies = [tool_call()]
    result, _context = run_step(env, world)
    retried = request_record(env, world)
    assert result["calls"] == 1
    assert len(world.jobs.items) == 1
    assert retried["status"] == "completed" and retried["approval_id"] == "m365-approval-2"
    assert {request["request_id"] for request in world.token_requests} == {
        env.orchestration.step_request_id(REQUEST_KEY),
    }
    # Approvals then shows the retried step's outcome, as it does for a resumed chat.
    assert reported == [("m365-approval-2", USER, env.orchestration.step_request_id(REQUEST_KEY), "completed")]


def test_each_plan_step_has_its_own_stable_request(env, world):
    first = env.orchestration.step_request_id(REQUEST_KEY)
    assert first == env.orchestration.step_request_id(REQUEST_KEY)
    assert first != env.orchestration.step_request_id(f"{ROOT_RUN}\x00another_step")
    assert first != env.orchestration.step_request_id(f"another-run\x00{STEP}")
    assert env.orchestration.step_request_id(None) != env.orchestration.step_request_id(None)


def test_step_scope_isolates_and_restores_request_state(env, world):
    selection = {"kind": "action", "action_ref": ACTION_REF, "user_groups": []}
    with world.app.test_request_context("/internal/agent-execution"):
        session["user"] = {"oid": USER, "tid": TENANT}
        g.m365_selected_agent_ref = {"id": "chat-agent"}
        with env.runtime.step_m365_context(
            user_id=USER, conversation_id=CONVERSATION, request_id="orch-scope", selection=selection,
        ) as context:
            assert context.request_id == "orch-scope" and context.workflow_id is None
            assert not hasattr(g, "m365_selected_agent_ref")
            assert getattr(g, env.runtime.M365_STEP_SELECTION_KEY) == selection
            assert env.runtime.resolve_m365_action_selection(context) == ["mail"]
        assert g.m365_selected_agent_ref == {"id": "chat-agent"}
        assert not hasattr(g, env.runtime.M365_STEP_SELECTION_KEY)
        assert env.runtime.get_m365_execution_context() is None


def test_a_step_without_a_signed_in_session_is_refused(env, world):
    scope = env.orchestration.action_step_scope(
        ACTION_REF, user_id=USER, conversation_id=CONVERSATION, request_key=REQUEST_KEY,
    )
    with world.app.test_request_context("/internal/agent-execution"):
        with pytest.raises(env.orchestration.OrchestrationM365Error) as caught:
            with scope:
                pass
    assert caught.value.orchestration_failure_code == "external_session_required"
    assert world.jobs.items == {}


def mail_agent(**changes):
    """A personal agent that loads the mail action, as the agent catalog serializes it."""
    return {
        "id": "mail-agent", "name": "mail_agent", "display_name": "Mail agent",
        "is_global": False, "is_group": False, "group_id": None,
        "actions_to_load": ["mail"], "other_settings": {}, **changes,
    }


def agent_scope(env, world, agent):
    scope = env.orchestration.agent_step_scope(
        agent, user_id=USER, conversation_id=CONVERSATION, request_key=REQUEST_KEY,
        origin={"run_id": "run-2", "attempt_index": 1, "step_id": "ask_mail_agent"},
    )
    request = world.app.test_request_context("/internal/agent-execution")
    return scope, request


def test_agent_step_scope_selects_only_the_agents_microsoft_365_actions(env, world):
    world.agents = [mail_agent()]
    assert env.orchestration.agent_loads_actions(mail_agent())
    assert not env.orchestration.agent_loads_actions(mail_agent(actions_to_load=[]))
    scope, request = agent_scope(env, world, mail_agent())
    with request:
        session["user"] = {"oid": USER, "tid": TENANT}
        with scope as context:
            assert context.request_id == env.orchestration.step_request_id(REQUEST_KEY)
            assert context.shared is False and context.workflow_id is None
            assert getattr(g, env.runtime.M365_STEP_SELECTION_KEY)["kind"] == "agent"
            assert env.runtime.resolve_m365_action_selection(context) == ["mail"]
        assert env.runtime.get_m365_execution_context() is None
    record = request_record(env, world)
    assert record["orchestration"] == {
        "run_id": "run-2", "attempt_index": 1, "step_id": "ask_mail_agent", "capability_id": "agent_invoke",
    }


def test_an_agent_without_microsoft_365_actions_gets_no_step_context(env, world):
    world.action = {**mail_action(), "id": "weather", "name": "weather", "type": "openapi"}
    world.agents = [mail_agent(actions_to_load=["weather"])]
    scope, request = agent_scope(env, world, mail_agent(actions_to_load=["weather"]))
    with request:
        session["user"] = {"oid": USER, "tid": TENANT}
        with scope as context:
            assert context is None and env.runtime.get_m365_execution_context() is None
    assert world.jobs.items == {} and world.token_requests == []


def test_a_removed_agent_stops_its_step_before_microsoft_365_work(env, world):
    world.agents = []
    scope, request = agent_scope(env, world, mail_agent())
    with request:
        session["user"] = {"oid": USER, "tid": TENANT}
        with pytest.raises(env.orchestration.OrchestrationM365Error) as caught:
            with scope:
                pass
    assert caught.value.orchestration_failure_code == "m365_unavailable"
    assert caught.value.m365_code == "m365_agent_unavailable"
    assert world.jobs.items == {} and world.token_requests == []


def test_refusal_codes_map_to_step_failures(env, world):
    refusal = env.orchestration.result_refusal
    for value in (
        None, "not json", [], {"value": []}, {"error": "throttled"}, {"error": "not_found"},
        {"error": "access_denied"}, {"error": "function_not_enabled"}, {"error": "source_not_allowed"},
    ):
        assert refusal(value) is None
    assert refusal({"error": "consent_required", "source": "email"}).orchestration_failure_code == "m365_sign_in_required"
    assert refusal(json.dumps({"error": "authentication_required", "sources": ["calendar"]})).m365_sources == ("calendar",)
    assert refusal({"error": {"code": "m365_action_not_selected"}}).orchestration_failure_code == "m365_unavailable"
    assert refusal({"error": "m365_context_required", "source": "email"}).orchestration_failure_code == "m365_unavailable"
    assert refusal({"error": "source_not_authorized"}).orchestration_failure_code == "m365_unavailable"
    assert refusal({"error": "m365_approval_pending"}).orchestration_failure_code == "m365_approval_required"


def test_failures_keep_only_known_microsoft_365_sources(env, world):
    schema = env.schema
    failure = schema.build_failure("m365_sign_in_required", m365_sources=["spo", "email", "email", "evil"])
    assert failure["m365_sources"] == ["email", "spo"]
    assert "m365_sources" not in schema.build_failure("step_failed", m365_sources=["email"])
    assert "m365_sources" not in schema.build_failure("m365_unavailable", m365_sources="email")
    assert schema.safe_failure(failure) == failure
    wrapped = RuntimeError("An action function could not complete.")
    wrapped.__cause__ = env.orchestration.OrchestrationM365Error("m365_unavailable", m365_code="m365_context_required")
    assert schema.failure_from_exception(wrapped)["code"] == "m365_unavailable"
    unknown = env.orchestration.OrchestrationM365Error("not_a_failure_code")
    assert schema.failure_from_exception(unknown)["code"] == "step_failed"


def test_orchestration_answers_keep_microsoft_365_sharing_provenance(env, world):
    world.replies = [tool_call()]
    result, context = run_step(env, world)
    citations = env.adapters._agent_citations(
        None, USER, CONVERSATION, set(),
        root_id=context.delegation_budget.root_id, scoped_invocations=result["invocations"],
    )
    message = {"role": "assistant", "metadata": {"orchestration": {}}, "agent_citations": citations}
    # Sharing a conversation then needs the owner's Microsoft 365 approval for this answer.
    assert env.history.history_sources([message]) == {"email": "request"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
