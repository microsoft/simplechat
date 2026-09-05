# test_agent_delegation_runtime.py
"""Executable delegation runtime regression tests.

Version: 0.261.093
Implemented in: 0.261.093

Real execution contexts, runtime, plugin and activity logger run against mock
providers. No Azure credentials or live model requests are used.
"""

import asyncio
import importlib
import inspect
import json
import logging
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from flask import Flask, g, session

from test_support.app_stubs import stubbed_app_imports
from test_support.agent_delegation import delegation_environment, reference


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


@pytest.fixture
def runtime(monkeypatch):
    with stubbed_app_imports():
        sys.modules["functions_appinsights"].get_appinsights_logger = lambda: logging.getLogger("delegation-test")
        monkeypatch.setitem(sys.modules, "functions_authentication", module(
            "functions_authentication", get_current_user_id=lambda: None,
        ))
        monkeypatch.setitem(sys.modules, "functions_debug", module("functions_debug", debug_print=lambda *args, **kwargs: None))
        monkeypatch.setitem(sys.modules, "functions_assigned_knowledge", module(
            "functions_assigned_knowledge", build_assigned_knowledge_runtime_filters=lambda agent: None,
        ))
        for name in (
            "agent_delegation_runtime", "semantic_kernel_plugins.plugin_invocation_logger",
            "semantic_kernel_plugins.agent_plugin",
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
        service = importlib.import_module("agent_delegation_runtime")
        contexts = importlib.import_module("agent_execution_context")
        logger = importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger")
        logger.get_plugin_logger().clear_history()
        service.contexts = contexts
        service.logger = logger
        yield service


def agent(name, user_id="user-1", **values):
    return {"id": name, "name": name, "display_name": f"Agent {name}", "scope_type": "personal",
            "scope_id": user_id, "user_id": user_id, "agent_type": "local", **values}


def frame(runtime, root=None, budget=None, cancel=None):
    root = root or agent("A")
    return runtime.contexts.AgentExecutionFrame(
        runtime.contexts.ExecutionIdentity(root["user_id"], "conversation"),
        root, budget or runtime.contexts.DelegationBudget(), cancel_requested=cancel,
    )


def authorize_graph(runtime, monkeypatch, graph):
    calls = []

    def resolve(action_id, *, caller_agent, user_id):
        calls.append((caller_agent["id"], action_id, user_id))
        target_name = graph[(caller_agent["id"], action_id)]
        return caller_agent, {"id": action_id}, agent(target_name, user_id)

    monkeypatch.setattr(runtime, "resolve_delegation_call", resolve)
    return calls


def test_discovery_and_tool_surface_have_no_provider_calls(runtime):
    plugin_class = importlib.import_module("semantic_kernel_plugins.agent_plugin").AgentPlugin
    assert plugin_class({}).display_name == "Call agent"
    assert plugin_class({}).metadata["type"] == "agent"
    assert list(inspect.signature(plugin_class.call_agent).parameters) == ["self", "task", "context"]
    from semantic_kernel.functions.kernel_plugin import KernelPlugin

    plugin = KernelPlugin.from_object("delegate", plugin_class({}))
    assert list(plugin.functions) == ["call_agent"]
    assert [parameter.name for parameter in plugin.functions["call_agent"].metadata.parameters] == ["task", "context"]
    assert runtime.logger.get_plugin_logger().invocations == []


def test_real_plugin_uses_fresh_binding_not_cached_manifest_target(runtime, monkeypatch):
    plugin_class = importlib.import_module("semantic_kernel_plugins.agent_plugin").AgentPlugin
    plugin = plugin_class({
        "id": "action-id", "name": "renamed action", "type": "agent",
        "endpoint": "internal://agent", "auth": {"type": "user"},
        "additionalFields": {"target_agent": {"id": "stale-C", "scope_type": "personal", "scope_id": "user-1"}},
    })
    authorize_graph(runtime, monkeypatch, {("A", "action-id"): "B"})
    seen = []

    async def execute(target, task, context, child):
        seen.append(target["id"])
        return {"response": "B answer", "citations": [], "usage": None}

    monkeypatch.setattr(runtime, "execute_target", execute)
    root = frame(runtime)

    async def run():
        with runtime.contexts.agent_execution(root):
            return await plugin.call_agent("task", "explicit")

    assert json.loads(asyncio.run(run()))["response"] == "B answer"
    assert seen == ["B"]
    assert len(runtime.logger.get_plugin_logger().invocations) == 1


def test_nested_chain_returns_to_parent_and_records_usage_once(runtime, monkeypatch):
    calls = authorize_graph(runtime, monkeypatch, {("A", "ab"): "B", ("B", "bc"): "C", ("C", "cd"): "D"})
    root = frame(runtime)
    received = []

    async def execute(target, task, context, child):
        received.append((target["id"], task, context, child.depth))
        if target["id"] in {"B", "C"}:
            next_action = {"B": "bc", "C": "cd"}[target["id"]]
            response = json.loads(await runtime.call_agent(next_action, "child task", "explicit"))
            assert response["response"]
        return {"response": f'{target["id"]} finished', "model": target["id"],
                "citations": [{"citation_id": target["id"], "url": "https://example.com/source"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}

    monkeypatch.setattr(runtime, "execute_target", execute)

    async def run():
        with runtime.contexts.agent_execution(root):
            output = json.loads(await runtime.call_agent("ab", "task", "context"))
            assert runtime.contexts.current_agent_execution() is root
            return output

    result = asyncio.run(run())
    assert result["response"] == "B finished"
    assert [item[3] for item in received] == [1, 2, 3]
    assert len(calls) == 3
    assert root.budget.attempts == 3
    assert runtime.delegation_usage(root.budget)["total_tokens"] == 15
    assert len(runtime.delegation_citations(root.budget)) == 3
    invocations = runtime.logger.get_plugin_logger().invocations
    assert len(invocations) == 3 and all(item.success for item in invocations)
    assert all(item.user_id == "user-1" and item.conversation_id == "conversation" for item in invocations)
    assert runtime.contexts.current_agent_execution() is None


@pytest.mark.parametrize("target,depth,ancestors", [("A", 0, ()), ("B", 3, ()), ("B", 1, (("personal", "user-1", "B"),))])
def test_self_cycle_and_fourth_level_fail_before_provider(runtime, monkeypatch, target, depth, ancestors):
    from dataclasses import replace

    authorize_graph(runtime, monkeypatch, {("A", "call"): target})
    root = replace(frame(runtime), depth=depth, ancestors=ancestors)
    invoked = []

    async def execute(*args):
        invoked.append(args)

    monkeypatch.setattr(runtime, "execute_target", execute)

    async def run():
        with runtime.contexts.agent_execution(root):
            with pytest.raises(runtime.AgentDelegationError):
                await runtime.call_agent("call", "task")

    asyncio.run(run())
    assert not invoked and root.budget.attempts == 1
    assert runtime.logger.get_plugin_logger().invocations[-1].success is False


def test_fresh_authorization_counts_denials_and_never_uses_manifest(runtime, monkeypatch):
    calls = []

    def denied(action_id, *, caller_agent, user_id):
        calls.append((action_id, user_id))
        raise PermissionError("private database secret")

    monkeypatch.setattr(runtime, "resolve_delegation_call", denied)
    root = frame(runtime)

    async def run():
        with runtime.contexts.agent_execution(root):
            for _ in range(2):
                with pytest.raises(runtime.AgentDelegationError) as error:
                    await runtime.call_agent("detached-action", "task")
                assert "secret" not in str(error.value)

    asyncio.run(run())
    assert calls == [("detached-action", "user-1")] * 2
    assert root.budget.attempts == 2
    assert all(not item.success for item in runtime.logger.get_plugin_logger().invocations)


def test_parallel_siblings_share_atomic_ten_attempt_limit(runtime, monkeypatch):
    calls = authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    root = frame(runtime)

    async def execute(*args):
        await asyncio.sleep(0)
        return {"response": "done", "citations": [], "usage": None}

    monkeypatch.setattr(runtime, "execute_target", execute)

    async def run():
        with runtime.contexts.agent_execution(root):
            return await asyncio.gather(*(runtime.call_agent("call", "task") for _ in range(14)), return_exceptions=True)

    results = asyncio.run(run())
    assert sum(isinstance(value, str) for value in results) == 10
    assert len(calls) == 10
    assert runtime.delegation_usage(root.budget) is None
    assert len(root.budget.records) == 14


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_blocked_child_is_interrupted_and_finally_runs(runtime, monkeypatch, reason):
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    stopped = False
    cleaned = []
    root = frame(runtime, cancel=lambda: stopped)
    monkeypatch.setattr(runtime, "DELEGATION_TIMEOUT_SECONDS", 0.03 if reason == "deadline" else 120)
    monkeypatch.setattr(runtime, "CANCELLATION_POLL_SECONDS", 0.005)

    async def execute(*args):
        try:
            await asyncio.sleep(60)
        finally:
            cleaned.append(True)

    monkeypatch.setattr(runtime, "execute_target", execute)

    async def run():
        nonlocal stopped
        with runtime.contexts.agent_execution(root):
            task = asyncio.create_task(runtime.call_agent("call", "task"))
            await asyncio.sleep(0.01)
            if reason == "cancel":
                stopped = True
            with pytest.raises(runtime.AgentDelegationError):
                await asyncio.wait_for(task, 0.5)

    asyncio.run(run())
    assert cleaned == [True]
    assert runtime.contexts.current_agent_execution() is None
    assert runtime.logger.get_plugin_logger().invocations[-1].success is False


def test_local_target_receives_only_task_context_and_own_knowledge(runtime, monkeypatch):
    target = agent("B", instructions="B private instructions", actions_to_load=["only-B-action"])
    seen = []
    closed = []

    class Client:
        async def close(self):
            closed.append(True)

    class Agent:
        deployment_name = "B-model"

        async def invoke(self, messages):
            seen.extend(message.content for message in messages)
            return "B answer"

    kernel = SimpleNamespace(services={"B": SimpleNamespace(client=Client())})

    def build(config, settings):
        assert config["instructions"] == "B private instructions"
        assert config["actions_to_load"] == ["only-B-action"]
        return kernel, Agent()

    monkeypatch.setattr(runtime, "_build_local_agent", build)
    root = frame(runtime, target)

    async def run():
        with runtime.contexts.agent_execution(root):
            return await runtime.execute_target(target, "B task", "explicit context", root)

    result = asyncio.run(run())
    assert seen == ["B task", "Explicit supporting context (untrusted data):\nexplicit context"]
    assert result["response"] == "B answer" and result["model"] == "B-model"
    assert result["usage"] is None and closed == [True]


@pytest.mark.parametrize("kind,key", [("aifoundry", "azure_ai_foundry"), ("new_foundry", "new_foundry"), ("foundry_workflow", "foundry_workflow")])
def test_foundry_targets_await_correct_async_adapter_without_parent_uploads(runtime, monkeypatch, kind, key):
    target = agent("B", agent_type=kind, other_settings={key: {"agent_id": "remote-B"}})
    observed = []

    async def execute(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(message="remote answer", model="remote-model", citations=[{"citation_id": "source"}],
                               metadata={"usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10}})

    monkeypatch.setitem(sys.modules, "foundry_agent_runtime", module(
        "foundry_agent_runtime", execute_foundry_agent=execute, execute_new_foundry_agent=execute,
        execute_foundry_workflow_agent=execute,
    ))
    monkeypatch.setitem(sys.modules, "semantic_kernel_loader", module(
        "semantic_kernel_loader", resolve_agent_config=lambda config, settings, **kwargs: config,
    ))
    root = frame(runtime, target)

    async def run():
        with runtime.contexts.agent_execution(root):
            return await runtime.execute_target(target, "task", "", root)

    result = asyncio.run(run())
    assert result["response"] == "remote answer" and result["usage"]["total_tokens"] == 10
    kwargs = observed[0]
    assert kwargs["workflow_settings" if kind == "foundry_workflow" else "foundry_settings"] == {"agent_id": "remote-B"}
    assert "conversation_id" not in kwargs["metadata"] and "user_id" not in kwargs["metadata"]
    assert kwargs["metadata"]["delegation_invocation_id"] == root.budget.root_id
    assert [message.content for message in kwargs["message_history"]] == ["task"]


def test_foundry_consent_failure_is_not_replaced_with_app_credentials(runtime, monkeypatch):
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})

    class FoundryAgentUserAuthenticationRequired(RuntimeError):
        pass

    async def execute(*args):
        raise FoundryAgentUserAuthenticationRequired("Sign in to Foundry.")

    monkeypatch.setattr(runtime, "execute_target", execute)
    root = frame(runtime)

    async def run():
        with runtime.contexts.agent_execution(root):
            with pytest.raises(FoundryAgentUserAuthenticationRequired):
                await runtime.call_agent("call", "task")

    asyncio.run(run())
    assert root.budget.attempts == 1
    assert runtime.logger.get_plugin_logger().invocations[-1].success is False


def test_ancestor_deadline_is_not_reset_by_descendant(runtime, monkeypatch):
    authorize_graph(runtime, monkeypatch, {("A", "ab"): "B", ("B", "bc"): "C"})
    monkeypatch.setattr(runtime, "DELEGATION_TIMEOUT_SECONDS", 0.04)
    deadlines = []
    cleaned = []
    root = frame(runtime)

    async def execute(target, task, context, child):
        deadlines.append(child.deadline)
        if target["id"] == "B":
            await asyncio.sleep(0.01)
            return await runtime.call_agent("bc", "child task")
        try:
            await asyncio.sleep(60)
        finally:
            cleaned.append(True)

    monkeypatch.setattr(runtime, "execute_target", execute)

    async def run():
        with runtime.contexts.agent_execution(root):
            with pytest.raises(runtime.AgentDelegationError):
                await asyncio.wait_for(runtime.call_agent("ab", "task"), 0.5)

    asyncio.run(run())
    assert len(deadlines) == 2 and deadlines[0] == deadlines[1]
    assert cleaned == [True]


def test_parallel_users_keep_separate_identity_history_and_budget(runtime, monkeypatch):
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    roots = [frame(runtime, agent("A", user_id)) for user_id in ("user-1", "user-2")]

    async def execute(target, task, context, child):
        await asyncio.sleep(0)
        assert runtime.contexts.current_agent_execution().identity.user_id == target["user_id"]
        return {"response": target["user_id"], "citations": [], "usage": None}

    monkeypatch.setattr(runtime, "execute_target", execute)

    async def run_root(root):
        with runtime.contexts.agent_execution(root):
            return json.loads(await runtime.call_agent("call", "task"))["response"]

    async def run():
        return await asyncio.gather(*(run_root(root) for root in roots))

    assert asyncio.run(run()) == ["user-1", "user-2"]
    assert [root.budget.attempts for root in roots] == [1, 1]
    assert roots[0].budget.root_id != roots[1].budget.root_id
    runtime.logger.get_plugin_logger().clear_history()
    assert [root.budget.invocations()[0].user_id for root in roots] == ["user-1", "user-2"]


@pytest.mark.parametrize("cancel", [True, False])
def test_real_foundry_workflow_adapter_uses_cancellable_async_io(runtime, monkeypatch, cancel):
    sys.modules["functions_authentication"].get_valid_access_token_for_plugins = lambda **kwargs: {"access_token": "test"}
    monkeypatch.setitem(sys.modules, "functions_keyvault", module(
        "functions_keyvault", retrieve_secret_from_key_vault_by_full_name=lambda value: value,
        validate_secret_name_dynamic=lambda value: False,
    ))
    monkeypatch.delitem(sys.modules, "foundry_agent_runtime", raising=False)
    foundry = importlib.import_module("foundry_agent_runtime")
    closed = []

    class Credential:
        async def close(self):
            closed.append("credential")

    class Response:
        status = 200
        headers = {"Content-Type": "text/event-stream"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append("response")

        async def json(self, **kwargs):
            return {"id": "remote-conversation"}

        @property
        def content(self):
            async def stream():
                if cancel:
                    await asyncio.sleep(60)
                yield b'data: {"type":"response.output_text.delta","delta":"Answer"}\n'
                yield b'\n'
                yield b"data: [DONE]\n\n"
            return stream()

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append("client")

        def post(self, *args, **kwargs):
            return Response()

        def delete(self, *args, **kwargs):
            closed.append("delete")
            return Response()

    async def headers(*args):
        return {}

    monkeypatch.setattr(foundry.aiohttp, "ClientSession", Client)
    monkeypatch.setattr(foundry, "_build_async_credential", lambda *args: Credential())
    monkeypatch.setattr(foundry, "_build_foundry_rest_headers", headers)
    monkeypatch.setattr(foundry, "_resolve_endpoint", lambda *args: "https://example.com")
    monkeypatch.setattr(foundry, "_build_foundry_workflow_endpoint_candidates", lambda *args, **kwargs: [
        {"responses_url": "https://example.com/responses", "conversations_url": "https://example.com/conversations"},
    ])
    monkeypatch.setattr(foundry.requests, "post", lambda *args, **kwargs: pytest.fail("Blocking requests must not run in delegated workflows"))

    async def run():
        operation = asyncio.create_task(foundry.execute_foundry_workflow_agent(
            workflow_settings={"workflow_name": "Test", "responses_api_version": "2025-11-15-preview"},
            global_settings={}, message_history=[SimpleNamespace(content="task", role="user")],
            metadata={"delegation_invocation_id": "call-id"},
        ))
        await asyncio.sleep(0.01)
        if cancel:
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(operation, 0.5)
        else:
            result = await asyncio.wait_for(operation, 0.5)
            assert result.message == "Answer"

    asyncio.run(run())
    assert "delete" in closed and "client" in closed and "credential" in closed


def test_call_agent_activity_and_citation_label_keep_target_provenance(runtime, monkeypatch):
    monkeypatch.setitem(sys.modules, "functions_azure_maps", module(
        "functions_azure_maps", refresh_azure_maps_citation_payload=lambda value, **kwargs: value,
    ))
    artifacts = importlib.import_module("functions_message_artifacts")
    thoughts = importlib.import_module("semantic_kernel_plugins.plugin_invocation_thoughts")
    provenance = {"root_id": "root", "target_label": "Finance specialist", "depth": 1}
    invocation = runtime.logger.PluginInvocation(
        "AgentPlugin", "call_agent", {}, {"response": "answer", "provenance": provenance},
        1, 2, 1000, "user", "2026-09-05", True, provenance=provenance,
    )
    assert artifacts.build_agent_citation_tool_label("AgentPlugin", "call_agent", {}, invocation.result) == "Call agent: Finance specialist"
    thought = thoughts.format_plugin_invocation_thought(invocation)
    assert thought["activity"]["title"] == "Call agent: Finance specialist"
    assert thought["activity"]["status"] == "completed"
    invocation.success = False
    assert thoughts.format_plugin_invocation_thought(invocation)["activity"]["status"] == "failed"


def test_classic_foundry_cancellation_deletes_owned_thread_and_closes_clients(runtime, monkeypatch):
    sys.modules["functions_authentication"].get_valid_access_token_for_plugins = lambda **kwargs: {"access_token": "test"}
    monkeypatch.setitem(sys.modules, "functions_keyvault", module(
        "functions_keyvault", retrieve_secret_from_key_vault_by_full_name=lambda value: value,
        validate_secret_name_dynamic=lambda value: False,
    ))
    monkeypatch.delitem(sys.modules, "foundry_agent_runtime", raising=False)
    foundry = importlib.import_module("foundry_agent_runtime")
    agents = importlib.import_module("semantic_kernel.agents")
    deleted = []
    client = SimpleNamespace(agents=SimpleNamespace(get_agent=AsyncMock(return_value=SimpleNamespace())), close=AsyncMock())
    credential = SimpleNamespace(close=AsyncMock())

    class Thread:
        def __init__(self, **kwargs):
            self.id = "owned-thread"

        async def delete(self):
            deleted.append(self.id)

    class FoundryAgent:
        create_client = staticmethod(lambda **kwargs: client)

        def __init__(self, **kwargs):
            pass

        async def invoke(self, **kwargs):
            assert isinstance(kwargs["thread"], Thread)
            await asyncio.sleep(60)
            yield None

    monkeypatch.setattr(agents, "AzureAIAgentThread", Thread)
    monkeypatch.setattr(foundry, "AzureAIAgent", FoundryAgent)
    monkeypatch.setattr(foundry, "_build_async_credential", lambda *args: credential)
    monkeypatch.setattr(foundry, "_resolve_endpoint", lambda *args: "https://example.com")

    async def run():
        operation = asyncio.create_task(foundry.execute_foundry_agent(
            foundry_settings={"agent_id": "remote-agent"}, global_settings={},
            message_history=[SimpleNamespace(content="task", role="user")],
            metadata={"delegation_invocation_id": "call-id"},
        ))
        await asyncio.sleep(0.01)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 0.5)

    asyncio.run(run())
    assert deleted == ["owned-thread"]
    client.close.assert_awaited_once()
    credential.close.assert_awaited_once()


@pytest.mark.parametrize("revocation", ["governance", "settings"])
def test_each_attempt_reauthorizes_without_parent_or_sibling_request_cache(runtime, monkeypatch, revocation):
    with delegation_environment() as (helper, services):
        services.add_agent("A", actions_to_load=["action-id"])
        services.add_agent("B")
        services.add_action(target=reference("B"))
        seen_contexts = []
        revoked = False

        def cached_governance(feature, actor, **kwargs):
            assert actor == "actor"
            cache = getattr(g, "simplechat_governance_request_cache", None)
            if cache is None:
                cache = {}
                g.simplechat_governance_request_cache = cache
            if feature not in cache:
                cache[feature] = not revoked
                seen_contexts.append(g._get_current_object())
            if not cache[feature]:
                raise PermissionError("Policy revoked.")

        services.governance.ensure_governance_access.side_effect = cached_governance
        monkeypatch.setattr(runtime, "resolve_delegation_call", helper.resolve_delegation_call)
        provider_calls = []

        async def execute(*args):
            provider_calls.append(True)
            return {"response": "answer", "citations": [], "usage": None}

        monkeypatch.setattr(runtime, "execute_target", execute)
        app = Flask("fresh-delegation-authorization")
        app.secret_key = "test"
        with app.test_request_context("/chat"):
            session["user"] = {"oid": "actor", "roles": ["User"]}
            g.simplechat_governance_request_cache = {"governance_user_agents": True}
            parent_cache = g.simplechat_governance_request_cache
            identity = runtime.capture_execution_identity("actor", "conversation")
            root = runtime.contexts.AgentExecutionFrame(identity, agent("A", "actor"), runtime.contexts.DelegationBudget())

            async def run():
                nonlocal revoked
                with runtime.contexts.agent_execution(root):
                    await runtime.call_agent("action-id", "first task")
                    if revocation == "settings":
                        services.settings["allow_user_agents"] = False
                    else:
                        revoked = True
                    with pytest.raises(runtime.AgentDelegationError):
                        await runtime.call_agent("action-id", "second task")

            asyncio.run(run())
            assert provider_calls == [True] and root.budget.attempts == 2
            assert g.simplechat_governance_request_cache is parent_cache
            assert services.settings_module.get_settings.call_count >= 2
            assert all(context is not g._get_current_object() for context in seen_contexts)


@pytest.mark.parametrize("prompt,completion,total", [(3, 4, 7), (0, 0, 0), (3, None, None), (None, None, None)])
def test_sdk_usage_derives_total_only_when_both_counts_are_observed(runtime, prompt, completion, total):
    from semantic_kernel.connectors.ai.completion_usage import CompletionUsage

    result = SimpleNamespace(metadata={"usage": CompletionUsage(prompt_tokens=prompt, completion_tokens=completion)})
    usage = runtime._observed_usage(result)
    if prompt is None and completion is None:
        assert usage is None
        return
    assert usage.get("total_tokens") == total
    if total is None:
        assert "total_tokens" not in usage
    budget = runtime.contexts.DelegationBudget()
    budget.record({"invocation_id": "observed", "usage": usage})
    assert runtime.delegation_usage(budget).get("total_tokens") == total
    kernel = SimpleNamespace(services={"model": SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)})
    assert runtime._observed_usage(kernel=kernel) == usage


@pytest.mark.parametrize("streaming", [False, True])
def test_foundry_auth_requirement_survives_real_sdk_tool_exception_boundary(runtime, monkeypatch, streaming):
    from semantic_kernel import Kernel
    from semantic_kernel.contents import ChatHistory, FunctionCallContent

    sys.modules["functions_authentication"].get_valid_access_token_for_plugins = lambda **kwargs: {"access_token": "test"}
    monkeypatch.setitem(sys.modules, "functions_keyvault", module(
        "functions_keyvault", retrieve_secret_from_key_vault_by_full_name=lambda value: value,
        validate_secret_name_dynamic=lambda value: False,
    ))
    monkeypatch.delitem(sys.modules, "foundry_agent_runtime", raising=False)
    foundry = importlib.import_module("foundry_agent_runtime")
    error = foundry.FoundryAgentUserAuthenticationRequired(
        foundry.FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE,
        auth_response={"scopes": ["https://ai.azure.com/.default"], "consent_url": "https://login.example.test/consent"},
    )
    plugin_class = importlib.import_module("semantic_kernel_plugins.agent_plugin").AgentPlugin
    plugin = plugin_class({
        "type": "agent", "id": "call", "endpoint": "internal://agent", "auth": {"type": "user"},
        "additionalFields": {"target_agent": {"id": "B", "scope_type": "personal", "scope_id": "user-1"}},
    })
    kernel = Kernel()
    kernel.add_plugin(plugin, plugin_name="delegate")
    sdk_returned = []

    class Parent:
        async def invoke(self, messages):
            history = ChatHistory()
            await kernel.invoke_function_call(
                FunctionCallContent(name="delegate-call_agent", arguments='{"task":"task"}', id="sdk-call"),
                history,
            )
            sdk_returned.append(history)
            return "incorrect success after swallowed consent"

        async def invoke_stream(self, messages):
            yield await self.invoke(messages)

    parent = Parent()
    parent.kernel = kernel
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda ref, **kwargs: agent("A"))
    monkeypatch.setattr(runtime, "_build_local_agent", lambda *args: (kernel, parent))

    async def execute(target, task, context, child):
        with child.identity.bridge(target):
            session["requested_oauth_scopes"] = error.auth_response["scopes"]
            session["child_only"] = True
            raise error

    monkeypatch.setattr(runtime, "execute_target", execute)
    app = Flask("sdk-auth-boundary")
    app.secret_key = "test"
    with app.test_request_context("/chat"):
        session["user"] = {"oid": "user-1", "roles": ["User"]}
        session["requested_oauth_scopes"] = ["original"]
        wrapped = runtime.prepare_agent_execution(parent, agent("A"), user_id="user-1", settings={})

        async def run():
            with pytest.raises(foundry.FoundryAgentUserAuthenticationRequired) as caught:
                if streaming:
                    async for _ in wrapped.invoke_stream([]):
                        pytest.fail("The root must not yield a success after a consent failure.")
                else:
                    await wrapped.invoke([])
            assert caught.value is error

        asyncio.run(run())
        assert sdk_returned, "The regression must exercise SDK handling, not direct exception propagation."
        assert session["requested_oauth_scopes"] == error.auth_response["scopes"]
        assert "child_only" not in session
        assert wrapped.budget.attempts == 1
