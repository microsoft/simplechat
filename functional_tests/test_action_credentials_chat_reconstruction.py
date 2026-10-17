# test_action_credentials_chat_reconstruction.py
"""Fresh-agent save/continue integration through real application owners.

Version: 0.261.345
Implemented in: 0.261.345

Cold subprocesses keep bootstrap, loaders, authorization, identities, journals,
routes and screened response persistence real. Only external I/O is doubled.
"""

import json

import pytest

from test_orchestration_result_imports import run_probe


PROBE = r'''
import asyncio
import base64
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from functools import wraps
import json
import requests
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from test_action_personal_credentials import CredentialContainer
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import (
    ChatMessageContent, FunctionCallContent, FinishReason,
    StreamingChatMessageContent,
)

scenario = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

def check(value, message):
    if not value:
        raise AssertionError(message)

with globals().get("credential_ui_context", nullcontext)() as transport, offline_app_imports() as environment:
    import app as web
    import config
    import app_settings_cache
    import functions_settings
    import functions_workspace_identities as identities
    import functions_action_credential_state as state
    import semantic_kernel_loader as loader
    import agent_delegation_runtime as runtime
    import route_backend_chats as chats
    import functions_authentication as authentication
    import route_backend_action_credentials as credential_routes
    import functions_appinsights as telemetry
    from action_credential_contracts import ActionCredentialsRequired
    from flask import g, session
    from semantic_kernel import Kernel
    from semantic_kernel.core_plugins import MathPlugin
    from yamcs.protobuf.instances.instances_service_pb2 import ListInstancesResponse

    settings = {
        **functions_settings.get_settings(), "enable_semantic_kernel": True,
        "allow_user_agents": True, "allow_user_plugins": True,
        "allow_group_agents": True, "allow_group_plugins": True, "enable_group_workspaces": True,
        "enable_user_workspace": True, "per_user_semantic_kernel": True,
        "merge_global_semantic_kernel_with_workspace": True,
        "enable_key_vault_secret_storage": False, "enable_content_safety": False,
        "enable_default_embedding_model_plugin": False, "enable_tabular_processing": False,
        "azure_openai_gpt_endpoint": "https://model.example.invalid",
        "azure_openai_gpt_key": "local-model-key", "azure_openai_gpt_deployment": "test-model",
        "azure_openai_gpt_api_version": "2024-10-21", "max_auto_invoke_attempts": 5,
    }
    target = {
        "id": "telemetry", "name": "telemetry", "display_name": "Telemetry",
        "agent_type": "local", "is_enabled": True, "is_global": True,
        "instructions": "List the available telemetry instances.", "actions_to_load": ["mission"],
    }
    scope = scenario.get("scope", "global")
    if scope != "global":
        target.update(is_global=False, is_group=scope == "group")
        target["group_id" if scope == "group" else "user_id"] = "team" if scope == "group" else "owner"
    profile = scenario.get("profile", "per-user")
    if "fact_memory" in scenario:
        settings["enable_fact_memory_plugin"] = scenario["fact_memory"]
    else:
        settings.pop("enable_fact_memory_plugin", None)
    settings["global_selected_agent"] = target
    action = {
        "id": "mission", "name": "mission", "type": "yamcs", "is_enabled": True,
        "endpoint": "https://mission.example.invalid", "metadata": {},
        "auth": {"type": "NoAuth"},
        "additionalFields": {"instance": "sim", "auth_method": "none", "enable_basic_auth": True},
        "credential_requirements": {"version": 1, "slots": {
            "proxy": {"source": "personal", "auth_type": "username_password"},
        }},
    }
    agent_container = getattr(config, "cosmos_" + scope + "_agents_container")
    action_container = getattr(config, "cosmos_" + scope + "_actions_container")
    if scope != "global":
        action["group_id" if scope == "group" else "user_id"] = "team" if scope == "group" else "owner"
    agent_container.upsert_item(target)
    action_container.upsert_item(action)
    config.cosmos_groups_container.upsert_item({
        "id": "team", "name": "Telemetry Team", "owner": {"id": "owner"}, "users": [{"userId": "owner"}],
    })
    user_settings = {"settings": {"enable_agents": True, "selected_agent": target}}
    if scope == "group":
        user_settings["settings"]["activeGroupOid"] = "team"
    state.configure_action_credential_state(CredentialContainer("user_id"))
    models, provider_calls, completed_calls, histories, diagnostics, responses = [], [], [], [], [], [
        ChatMessageContent(role="assistant", items=[
            FunctionCallContent(id="completed-sum", name="math-Add", arguments='{"input":2,"amount":3}'),
        ]),
        ChatMessageContent(role="assistant", items=[
            FunctionCallContent(id="blocked-instances", name="mission-list_instances", arguments="{}"),
        ]),
        ChatMessageContent(role="assistant", content="sim is RUNNING."),
    ]

    async def model_reply(service, history, execution_settings):
        histories.append(str(history))
        check(bool(responses), "Unexpected model invocation or replay.")
        if len(responses) == 1:
            check("RUNNING" in str(history) and len(provider_calls) == 1,
                  "Model did not receive the actual resumed provider result.")
        return [responses.pop(0)]

    async def stream_reply(service, history, execution_settings, function_invoke_attempt=0):
        reply = (await model_reply(service, history, execution_settings))[0]
        calls = [item for item in reply.items if isinstance(item, FunctionCallContent)]
        if calls:
            yield [StreamingChatMessageContent(role="assistant", choice_index=0,
                finish_reason=FinishReason.TOOL_CALLS,
                items=[FunctionCallContent(index=index, id=call.id, name=call.name, arguments=call.arguments)
                       for index, call in enumerate(calls)])]
        else:
            yield [StreamingChatMessageContent(role="assistant", choice_index=0, content=reply.content,
                                              finish_reason=FinishReason.STOP)]

    async def invoke_initial(execution, messages):
        if scenario.get("streaming"):
            return [item async for item in execution.invoke_stream(messages)]
        return await execution.invoke(messages)

    create_model = loader.create_model_endpoint_chat_completion_service
    def model_service(*args, **kwargs):
        service = create_model(*args, **kwargs)
        models.append(service)
        return service

    def provider_instances(session, request, **kwargs):
        header = request.headers.get("Authorization")
        expected = "Basic " + base64.b64encode(b"private-user-sentinel:private-password-sentinel").decode()
        check(header == expected, "Tool did not use the newly saved credentials.")
        check(request.method == "GET" and request.url.endswith("/api/instances"), "Unexpected provider operation.")
        provider_calls.append(True)
        response = requests.Response()
        response.status_code = scenario.get("provider_status", 200)
        response._content = ListInstancesResponse(instances=[{"name": "sim", "state": "RUNNING"}]).SerializeToString()
        return response

    add = MathPlugin.add
    @wraps(add)
    def counted_add(*args, **kwargs):
        completed_calls.append(True)
        return add(*args, **kwargs)

    log_event = credential_routes.log_event
    def capture_diagnostic(message, *args, **kwargs):
        if message == "[PLUGINS] Credential continuation stopped.":
            diagnostics.append(telemetry._build_logger_extra(message, kwargs["extra"]))
        return log_event(message, *args, **kwargs)

    with ExitStack() as mocks:
        for context in (
            patch.object(asyncio, "run", side_effect=environment.loop.run_until_complete),
            patch.object(app_settings_cache, "get_settings_cache", return_value=settings),
            patch.object(functions_settings, "get_settings", return_value=settings),
            patch.object(functions_settings, "get_user_settings", return_value=user_settings),
            patch.object(identities, "get_settings", return_value=settings),
            patch.object(loader, "get_user_settings", return_value=user_settings),
            patch.object(agent_container, "query_items", side_effect=lambda **kwargs: [deepcopy(target)]),
            patch.object(action_container, "query_items", side_effect=lambda **kwargs: [deepcopy(action)]),
            patch.object(config.cosmos_groups_container, "query_items", side_effect=lambda **kwargs: [
                deepcopy(row) for row in config.cosmos_groups_container.items.values()
                if any(user["userId"] == "owner" for user in row.get("users", []))
            ]),
            patch.object(config.cosmos_messages_container, "query_items", side_effect=lambda **kwargs: [
                deepcopy(row) for row in config.cosmos_messages_container.items.values()
                if row.get("conversation_id") == "credential-chat"
            ]),
            patch.object(loader, "create_model_endpoint_chat_completion_service", side_effect=model_service),
            patch.object(AzureChatCompletion, "_inner_get_chat_message_contents", model_reply),
            patch.object(AzureChatCompletion, "_inner_get_streaming_chat_message_contents", stream_reply),
            patch.object(MathPlugin, "add", counted_add),
            patch.object(requests.Session, "send", provider_instances),
            patch.object(credential_routes, "log_event", side_effect=capture_diagnostic),
            patch.object(authentication, "get_user_profile_image", return_value=None),
        ):
            mocks.enter_context(context)
        selected_identity = None
        if scenario.get("identity") in {"select", "rotate"}:
            identities.create_workspace_identity("personal", "owner", {
                "name": "Existing proxy", "provider": "yamcs", "usage_contexts": ["actions"],
                "supported_source_types": ["yamcs"],
                "credentials": {"auth_type": "username_password", "username": "private-user-sentinel",
                                "password": "old-password" if scenario["identity"] == "rotate" else "private-password-sentinel"},
            }, "owner", identity_id="existing-proxy")
            selected_identity = identities.get_workspace_identity("personal", "owner", "existing-proxy")
        with web.app.test_request_context("/"):
            session["user"] = {"oid": "owner", "roles": ["User"]}
            g.conversation_id = "credential-chat"
            g.request_agent_info = deepcopy(target)
            chats._create_personal_conversation("owner", "credential-chat")
            user_message = {
                "id": "original-question", "conversation_id": "credential-chat", "user_id": "owner",
                "role": "user", "content": "List the actual telemetry instances.",
                "created_at": "2026-10-17T12:00:00Z",
            }
            prior_messages = [
                ChatMessageContent(role="user", content="Remember this existing conversation."),
                ChatMessageContent(role="assistant", content="Ready for the next operation."),
            ] if scenario.get("prior_history") else []
            for index, prior in enumerate(prior_messages):
                config.cosmos_messages_container.upsert_item({
                    **user_message, "id": f"prior-{index}", "role": prior.role.value, "content": prior.content,
                })
            config.cosmos_messages_container.upsert_item(user_message)
            canonical = runtime.resolve_delegation_agent(target, user_id="owner", settings=settings)
            if profile == "global":
                original_kernel, agents = loader.load_semantic_kernel(Kernel(), settings)
            elif profile == "agent-core":
                from agent_execution_context import AgentExecutionFrame, DelegationBudget, agent_execution, capture_execution_identity
                frame = AgentExecutionFrame(capture_execution_identity("owner", "credential-chat"), canonical, DelegationBudget())
                with agent_execution(frame):
                    original_kernel, selected = runtime._build_local_agent(canonical, settings)
                agents = {"telemetry": selected}
            else:
                original_kernel, agents = loader.load_user_semantic_kernel(Kernel(), settings, "owner", None)
            check(agents is not None, "Original selected agent was not constructed.")
            original = agents["telemetry"]
            check(original.construction_profile == profile, "Initial construction profile was lost.")
            check("construction_profile" not in original.model_dump(), "Construction metadata escaped serialization.")
            check(("document_search" in original_kernel.plugins) == (profile != "per-user"),
                  "Initial Document Search capabilities changed.")
            check(("fact_memory" in original_kernel.plugins)
                  == settings.get("enable_fact_memory_plugin", profile == "per-user"),
                  "Initial Fact Memory defaults changed.")
            execution = runtime.prepare_agent_execution(
                original, canonical, user_id="owner", settings=settings, conversation_id="credential-chat",
            )
            try:
                asyncio.run(invoke_initial(execution, prior_messages + [ChatMessageContent(
                    role="user", content="List the actual telemetry instances.",
                )]))
            except ActionCredentialsRequired as error:
                pending = error.credential_request
            else:
                raise AssertionError("Tool did not pause for personal credentials.")
        check(not provider_calls and len(completed_calls) == 1, "Initial tool boundaries were not retained.")
        checkpoint = state.read("owner", execution.credential_checkpoint_id)
        check("root" in checkpoint["value"], "No retained root tool history.")
        client = web.app.test_client()
        with client.session_transaction() as browser:
            browser["user"] = {"oid": "owner", "roles": ["User"]}
        path = "/api/action-credentials/" + pending["id"]
        info = client.get(path)
        check(info.status_code == 200, "Credential request was not authorized.")
        slot = {
            "slot": "proxy", "name": "Local proxy",
            "credentials": {"auth_type": "username_password",
                            "username": "private-user-sentinel", "password": "private-password-sentinel"},
        }
        if selected_identity:
            slot.pop("name")
            slot["identity_id"] = selected_identity["id"]
            if scenario["identity"] == "select":
                slot.pop("credentials")
            else:
                slot["expected_identity_etag"] = selected_identity["_etag"]
        if transport is not None:
            continued, ready = transport(client, pending, user_message)
        else:
            submitted = client.post(path + "/submit", json={
                "expected_etag": pending["etag"], "slots": [slot],
            }, headers={"X-CSRFToken": info.json["csrf_token"]})
            check(submitted.status_code == 200, "Credential save failed: " + str(submitted.json))
            ready = submitted.json["credential_request"]
            mutation = scenario.get("mutation")
            if mutation == "instructions":
                target["instructions"] += " Changed after pause."
                agent_container.upsert_item(target)
            elif mutation == "model":
                settings["azure_openai_gpt_deployment"] = "different-model"
            elif mutation == "tools":
                settings["enable_math_plugin"] = False
            elif mutation == "destination":
                action["endpoint"] = "https://changed.example.invalid"
                action_container.upsert_item(action)
            elif mutation == "ownership":
                config.cosmos_conversations_container.items["credential-chat"]["user_id"] = "other-user"
            elif mutation == "group":
                config.cosmos_groups_container.items["team"]["owner"] = {"id": "other-user"}
                config.cosmos_groups_container.items["team"]["users"] = []
            persistence = (
                patch.object(chats, "_persist_screened_assistant", side_effect=OSError("private-password-sentinel"))
                if scenario.get("persistence_failure") else nullcontext()
            )
            with persistence:
                continued = client.post(path + "/continue", json={"expected_etag": ready["etag"]},
                                       headers={"X-CSRFToken": info.json["csrf_token"]}, buffered=True)
        frames = continued.get_data(as_text=True)
        if scenario.get("persistence_failure") or scenario.get("provider_status") == 401:
            expected_status = "failed" if scenario.get("persistence_failure") else "superseded"
            check('"done": true' not in frames and len(provider_calls) == 1, "Failure became success or replayed work.")
            check(state.read("owner", pending["id"])["status"] == expected_status, "Failure status was not truthful.")
            check(len(completed_calls) == 1, "Failure replayed prior work.")
            check("private-password-sentinel" not in frames + json.dumps(diagnostics), "Failure leaked credentials.")
            if scenario.get("provider_status") == 401:
                check('"action_credentials_required"' in frames, "Authentication rejection did not re-challenge.")
            else:
                check(diagnostics[-1]["sc_stage"] == "credential_response_persistence", "Persistence phase was lost.")
            duplicate = client.post(path + "/continue", json={"expected_etag": ready["etag"]},
                                    headers={"X-CSRFToken": info.json["csrf_token"]})
            check(duplicate.status_code == 409 and len(provider_calls) == 1, "Failed operation was automatically replayed.")
            for model in models:
                if not model.client.is_closed():
                    environment.loop.run_until_complete(model.client.close())
            print("PASS: rejected credentials or response persistence cannot report success")
            sys.exit(0)
        if scenario.get("mutation"):
            check('"done": true' not in frames and not provider_calls, "Changed execution reached the provider.")
            check(len(completed_calls) == 1, "Rejected execution replayed prior work.")
            if scenario["mutation"] in {"instructions", "model", "tools"}:
                check(diagnostics[-1]["sc_failure_code"] == "credential_execution_changed",
                      "Safe diagnostics lost the guard's stable code.")
                check(diagnostics[-1]["sc_stage"] == "credential_tool_resume",
                      "Safe diagnostics lost the failing stage.")
                check(len(diagnostics[-1]["sc_conversation_id_hash"]) == 64, "Correlation was not hashed.")
            check("private-password-sentinel" not in frames + json.dumps(diagnostics), "Failure leaked credentials.")
            for model in models:
                if not model.client.is_closed():
                    environment.loop.run_until_complete(model.client.close())
            print("PASS: genuine configuration/access changes remain blocked")
            sys.exit(0)
        check(continued.status_code == 200 and '"done": true' in frames,
              "Same-conversation continuation failed: " + frames)
        check(len(provider_calls) == 1, "Blocked provider call did not execute exactly once.")
        check(len(completed_calls) == 1, "An earlier completed tool was replayed.")
        check(len(models) == 2 and models[0] is not models[1], "Resume did not create a fresh model.")
        if prior_messages:
            check("Remember this existing conversation." in histories[-1], "Earlier conversation context was lost.")
        check(state.read("owner", pending["id"])["status"] == "completed", "Request did not complete.")
        answer = json.loads(next(line[6:] for line in frames.splitlines() if '"done": true' in line))
        saved = config.cosmos_messages_container.read_item(answer["message_id"], "credential-chat")
        check(saved["conversation_id"] == "credential-chat" and saved["content"] == "sim is RUNNING.",
              "Assistant answer was not persisted in the same conversation.")
        check(sum(row.get("role") == "user" for row in config.cosmos_messages_container.items.values())
              == 1 + bool(prior_messages),
              "Continuation reposted the question.")
        check(len(config.cosmos_personal_workspace_identities_container.items) == 1, "Identity was duplicated.")
        private_state = json.dumps(list(state.container().items.values()))
        check("private-password-sentinel" not in frames + private_state + "".join(histories),
              "Credential secret escaped its private identity boundary.")
        duplicate = client.post(path + "/continue", json={"expected_etag": ready["etag"]},
                                headers={"X-CSRFToken": info.json["csrf_token"]})
        check(duplicate.status_code == 409 and len(provider_calls) == 1, "Duplicate continuation replayed work.")
    for model in models:
        if not model.client.is_closed():
            environment.loop.run_until_complete(model.client.close())
    check(not environment.network_attempts, "Integration attempted external network I/O.")
print("PASS: fresh agent resumed the blocked tool and persisted the same-conversation answer")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_new_credential_request_resumes_fresh_agent_in_same_conversation(optimized):
    run_probe(PROBE, (), optimized)


@pytest.mark.parametrize("scenario", [
    {"scope": "personal", "identity": "select", "fact_memory": False},
    {"scope": "group", "identity": "rotate", "fact_memory": True},
    {"profile": "global", "identity": "select"},
    {"profile": "agent-core"},
    {"streaming": True},
    {"prior_history": True},
])
def test_reconstruction_preserves_profiles_and_identity_lifecycle(scenario):
    run_probe(PROBE, (json.dumps(scenario),), False)


@pytest.mark.parametrize("mutation", ["instructions", "model", "tools", "destination", "ownership", "group"])
def test_fresh_reconstruction_rejects_real_changes(mutation):
    scenario = {"mutation": mutation, "scope": "group" if mutation == "group" else "global"}
    run_probe(PROBE, (json.dumps(scenario),), False)


@pytest.mark.parametrize("scenario", [{"provider_status": 401}, {"persistence_failure": True}])
def test_resume_failure_cannot_report_success_or_replay(scenario):
    run_probe(PROBE, (json.dumps(scenario),), False)
