# test_agent_delegation_entrypoints.py
"""Executable root/worker/stream context and cancellation coverage.

Version: 0.261.093
Implemented in: 0.261.093
"""

import asyncio
import ast
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime
import importlib
import json
import logging
import threading
from types import CodeType, SimpleNamespace

import pytest
from flask import Flask, g, has_request_context, session

from test_agent_delegation_runtime import agent, authorize_graph, module, runtime
from test_support.app_stubs import APP_ROOT
from test_support.agent_delegation import execute_functions


def test_identity_bridge_isolates_parallel_children_and_preserves_parent(runtime):
    app = Flask("delegation-test")
    app.secret_key = "test-only"
    with app.test_request_context("/chat"):
        session["user"] = {"oid": "user-1", "roles": ["User"], "name": "Real user"}
        g.parent_upload = "must not pass"
        g.request_agent_name = "parent"
        identity = runtime.capture_execution_identity("user-1", "conversation")

        async def child(name):
            with identity.bridge(agent(name)):
                assert not hasattr(g, "parent_upload")
                assert session["user"]["roles"] == ["User"]
                g.unique_child = name
                await asyncio.sleep(0)
                assert g.unique_child == name and g.request_agent_name == name
                return g.unique_child

        async def run():
            return await asyncio.gather(child("B"), child("C"))

        assert asyncio.run(run()) == ["B", "C"]
        assert g.parent_upload == "must not pass" and g.request_agent_name == "parent"
        assert not hasattr(g, "unique_child")


def test_root_stream_survives_separate_next_tasks_without_context_leak(runtime):
    class Root:
        name = "A"
        kernel = SimpleNamespace(plugins={})

        async def invoke_stream(self, messages):
            for text in ["first", "second"]:
                assert runtime.contexts.current_agent_execution().identity.user_id == "user-1"
                await asyncio.sleep(0)
                yield text

    wrapped = runtime.prepare_agent_execution(
        Root(), agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1", "conversation"),
    )
    loop = asyncio.new_event_loop()
    stream = wrapped.invoke_stream([])
    try:
        assert loop.run_until_complete(stream.__anext__()) == "first"
        assert runtime.contexts.current_agent_execution() is None
        assert loop.run_until_complete(stream.__anext__()) == "second"
        with pytest.raises(StopAsyncIteration):
            loop.run_until_complete(stream.__anext__())
        assert runtime.contexts.current_agent_execution() is None
    finally:
        loop.run_until_complete(stream.aclose())
        loop.close()


def test_stream_stop_interrupts_waiting_parent(runtime, monkeypatch):
    stopped = False
    cleaned = []
    monkeypatch.setattr(runtime, "CANCELLATION_POLL_SECONDS", 0.005)

    class Root:
        kernel = SimpleNamespace(plugins={})

        async def invoke_stream(self, messages):
            try:
                await asyncio.sleep(60)
                yield "never"
            finally:
                cleaned.append(True)

    wrapped = runtime.prepare_agent_execution(
        Root(), agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1"),
        cancel_requested=lambda: stopped,
    )

    async def run():
        nonlocal stopped
        stream = wrapped.invoke_stream([])
        task = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0.01)
        stopped = True
        with pytest.raises(runtime.AgentExecutionCancelled):
            await asyncio.wait_for(task, 0.5)
        await stream.aclose()

    asyncio.run(run())
    assert cleaned == [True]


def test_root_rebuilds_shared_kernel_without_mutating_cached_agent(runtime, monkeypatch):
    original = SimpleNamespace(kernel=SimpleNamespace(plugins={"Call": SimpleNamespace(functions={"call_agent": object()})}))
    built = []

    class Fresh:
        async def invoke(self, messages):
            assert runtime.contexts.current_agent_execution().caller["id"] == "A"
            return "root reply"

    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda ref, **kwargs: agent("A"))
    monkeypatch.setattr(runtime, "_build_local_agent", lambda target, settings: (built.append(target) or SimpleNamespace(services={}), Fresh()))
    wrapper = runtime.prepare_agent_execution(
        original, agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1"),
    )
    assert asyncio.run(wrapper.invoke([])) == "root reply"
    assert len(built) == 1
    assert wrapper.agent is original
    assert list(original.kernel.plugins) == ["Call"]


def test_chat_retry_cannot_replay_delegated_side_effects(runtime, monkeypatch):
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    effects = []

    class Parent:
        kernel = SimpleNamespace(plugins={})

        async def invoke(self, messages):
            return await runtime.call_agent("call", "write task")

    async def execute(*args):
        effects.append("committed")
        return {"response": "done", "citations": [], "usage": None}

    monkeypatch.setattr(runtime, "execute_target", execute)
    wrapped = runtime.prepare_agent_execution(
        Parent(), agent("A"), user_id="user-1", settings={}, prevent_replay=True,
        identity=runtime.contexts.ExecutionIdentity("user-1"),
    )
    assert json.loads(asyncio.run(wrapped.invoke([])))["response"] == "done"
    with pytest.raises(runtime.AgentDelegationError):
        asyncio.run(wrapped.invoke([]))
    assert effects == ["committed"] and wrapped.budget.attempts == 1


def test_real_loader_filters_delegation_by_id_and_isolation_in_both_paths(runtime):
    source = ast.parse((APP_ROOT / "semantic_kernel_loader.py").read_text(encoding="utf-8"))
    names = {"load_agent_specific_plugins", "_load_plugins_original_method", "_apply_agent_plugin_runtime_overlays"}
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    loaded = []
    fallback = []
    fail_loader = False
    manifest = {
        "type": "agent", "id": "action-id", "name": "action-name",
        "endpoint": "internal://agent", "auth": {"type": "user"},
        "additionalFields": {"target_agent": {"id": "global-agent", "scope_type": "global", "scope_id": "global"}},
    }

    class Loader:
        def load_multiple_plugins(self, manifests, user_id):
            if fail_loader:
                raise RuntimeError("test loader failure")
            loaded.extend(manifests)
            return {item["id"]: True for item in manifests}

    namespace = {
        "logging": __import__("logging"), "log_event": lambda *args, **kwargs: None,
        "debug_print": lambda *args, **kwargs: None,
        "create_logged_plugin_loader": lambda kernel: Loader(),
        "_get_governed_global_plugin_manifests": lambda *args, **kwargs: [manifest],
        "_apply_agent_plugin_runtime_overlays": lambda values, **kwargs: values,
        "hydrate_workspace_identity_in_plugin": lambda value: value,
        "SecretReturnType": SimpleNamespace(NAME="name"),
        "SIMPLECHAT_PLUGIN_TYPE": "simplechat", "CHART_PLUGIN_TYPE": "chart",
        "MSGRAPH_PLUGIN_TYPE": "msgraph", "BLOB_STORAGE_PLUGIN_TYPE": "blob_storage",
        "_load_agent_plugins_original_method": lambda kernel, manifests, mode: fallback.extend(manifests),
        "discover_plugins": lambda: pytest.fail("blanket discovery must not instantiate an agent action"),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "loader_agent_hooks", "exec"), namespace)
    overlaid = namespace["_apply_agent_plugin_runtime_overlays"]([manifest], group_id="group-1")
    assert "default_group_id" not in overlaid[0]
    validator = importlib.import_module("functions_agent_delegation").validate_agent_action_manifest
    assert validator(overlaid[0])["additionalFields"] == manifest["additionalFields"]
    assert namespace["_apply_agent_plugin_runtime_overlays"]([{"type": "http"}], group_id="group-1")[0]["default_group_id"] == "group-1"
    load = namespace["load_agent_specific_plugins"]
    load(object(), ["action-name"], {}, user_id="user-1", allow_agent_actions=True)
    assert not loaded
    load(object(), ["action-id"], {}, user_id="user-1")
    assert not loaded
    load(object(), ["action-id"], {}, user_id="user-1", allow_agent_actions=True)
    assert loaded == [manifest]
    fail_loader = True
    load(object(), ["action-name"], {}, user_id="user-1", allow_agent_actions=True)
    assert not fallback
    load(object(), ["action-id"], {}, user_id="user-1", allow_agent_actions=True)
    assert fallback == [manifest]
    namespace["discover_plugins"] = lambda: {"AgentPlugin": SimpleNamespace()}
    namespace["_load_plugins_original_method"](object(), [manifest], {})


def test_worker_roots_share_budget_across_steps_and_new_workflow_resets(runtime, monkeypatch):
    budget = runtime.contexts.DelegationBudget()
    identity = runtime.contexts.ExecutionIdentity("user-1")
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda ref, **kwargs: ref)

    async def execute(target, task, context, child):
        if target["id"] == "A":
            for _ in range(5):
                await runtime.call_agent("call", "task")
        return {"response": "answer", "citations": [], "usage": None}

    monkeypatch.setattr(runtime, "execute_target", execute)
    for _ in range(2):
        asyncio.run(runtime.invoke_scoped_agent(agent("A"), "task", identity=identity, budget=budget))
    assert budget.attempts == 10
    with pytest.raises(runtime.AgentDelegationError):
        asyncio.run(runtime.invoke_scoped_agent(agent("A"), "task", identity=identity, budget=budget))
    new_budget = runtime.contexts.DelegationBudget()
    assert asyncio.run(runtime.invoke_scoped_agent(agent("A"), "task", identity=identity, budget=new_budget))["response"] == "answer"
    assert new_budget.attempts == 5


def test_real_orchestration_adapter_enters_runtime_and_merges_usage_once(runtime, monkeypatch):
    adapters = importlib.import_module("functions_orchestration_adapters")
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda ref, **kwargs: ref)

    async def execute(target, task, context, child):
        if target["id"] == "A":
            await runtime.call_agent("call", "explicit child task")
        return {"response": f'{target["id"]} answer', "citations": [],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}

    monkeypatch.setattr(runtime, "execute_target", execute)
    context = SimpleNamespace(
        user_message="root task", agent_catalog=[agent("A")], user_enable_agents=True,
        agent_execution_identity=runtime.contexts.ExecutionIdentity("user-1", "conversation"),
        delegation_budget=runtime.contexts.DelegationBudget(), token_usage={}, conversation_id="conversation",
    )
    step = {"step_id": "agent-step", "arguments": {"agent_name": "A", "task": "root task"}}
    for _ in range(2):
        result = adapters.run_agent_invoke(
            step, context, settings={"enable_semantic_kernel": True, "allow_user_agents": True},
            user_id="user-1", emit=None, cancel_requested=lambda: False,
        )
        assert result["status"] == "completed"
        assert any("A answer" in note for note in result["notes"])
    assert context.delegation_budget.attempts == 2
    assert context.token_usage["total_tokens"] == 20
    assert len(context.token_usage["agent_breakdown"]) == 2


@pytest.mark.parametrize("cancel", [False, True])
def test_workflow_agent_hook_executes_parent_and_child_and_preserves_cancellation(runtime, monkeypatch, cancel):
    """Execute the actual workflow entry function with only its Azure services replaced."""
    source = ast.parse((APP_ROOT / "functions_workflow_runner.py").read_text(encoding="utf-8"))
    names = {
        "_execute_agent_workflow", "_execute_cancelable_workflow_step",
        "_create_token_usage_aggregate", "_accumulate_token_usage_summary", "_finalize_token_usage",
        "_workflow_agent_execution_context",
    }
    nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    stopped = threading.Event()
    authorize_graph(runtime, monkeypatch, {("A", "call"): "B"})
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda ref, **kwargs: agent("A"))

    class Parent:
        name = "A"
        display_name = "Agent A"
        deployment_name = "parent-model"
        kernel = SimpleNamespace(plugins={"delegate": SimpleNamespace(functions={"call_agent": object()})})

        async def invoke(self, messages):
            delegated = json.loads(await runtime.call_agent("call", "delegated task"))
            return f'Parent answer with {delegated["response"]}'

    async def execute(target, task, context, child):
        if cancel:
            asyncio.get_running_loop().call_later(0.01, stopped.set)
            await asyncio.sleep(60)
        return {"response": "child answer", "citations": [],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}

    parent = Parent()
    kernel = SimpleNamespace(services={"model": SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5)})
    monkeypatch.setattr(runtime, "execute_target", execute)
    monkeypatch.setattr(runtime, "_build_local_agent", lambda *args: (kernel, parent))
    monkeypatch.setattr(runtime, "CANCELLATION_POLL_SECONDS", 0.005)

    class WorkflowCancelled(RuntimeError):
        pass

    namespace = {
        "asyncio": asyncio, "g": g, "DelegationBudget": runtime.contexts.DelegationBudget,
        "AgentExecutionCancelled": runtime.AgentExecutionCancelled, "WorkflowRunCancelledError": WorkflowCancelled,
        "WORKFLOW_RUN_CANCELLED_MESSAGE": "Workflow cancelled.",
        "_workflow_delegation_budget": ContextVar("test_workflow_budget", default=None),
        "_workflow_execution_identity": ContextVar("test_workflow_identity", default=None),
        "contextmanager": contextmanager, "nullcontext": nullcontext,
        "has_request_context": has_request_context, "session": session,
        "capture_execution_identity": runtime.capture_execution_identity,
        "_raise_if_workflow_run_cancelled": lambda *args: None,
        "_is_workflow_run_cancellation_requested": lambda *args: stopped.is_set(),
        "_ensure_execution_context": lambda *args: nullcontext(),
        "get_plugin_logger": runtime.logger.get_plugin_logger,
        "prepare_agent_execution": runtime.prepare_agent_execution,
        "delegation_citations": runtime.delegation_citations, "delegation_usage": runtime.delegation_usage,
        "_get_workflow_group_id": lambda *args: None, "Kernel": lambda: kernel,
        "load_user_semantic_kernel": lambda *args: (kernel, {"A": parent}),
        "get_workflow_kernel_settings": lambda settings: settings,
        "_resolve_workflow_conversation_context": lambda *args, **kwargs: None,
        "_build_workflow_agent_messages": lambda prompt, **kwargs: [SimpleNamespace(content=prompt)],
        "_build_agent_citations_from_invocations": lambda *args, **kwargs: [],
        "_collect_agent_alert_targets": lambda *args: [],
        "_accumulate_token_usage": lambda *args: None,
        "_coerce_token_count": lambda value: int(value) if value is not None else None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "workflow_agent_hooks", "exec"), namespace)
    app = Flask("workflow-test")
    app.secret_key = "test-only"
    with app.test_request_context("/workflow"):
        session["user"] = {"oid": "user-1", "roles": ["User"]}
        workflow = {"user_id": "user-1", "id": "workflow", "selected_agent": agent("A"), "task_prompt": "task"}
        if cancel:
            with pytest.raises(WorkflowCancelled):
                namespace["_execute_agent_workflow"](workflow, {}, conversation_id="conversation", run_id="run")
        else:
            result = namespace["_execute_agent_workflow"](workflow, {}, conversation_id="conversation", run_id="run")
            assert result["reply"] == "Parent answer with child answer"
            assert result["agent_name"] == "A"
            assert result["token_usage"]["total_tokens"] == 10
        assert not hasattr(g, "request_agent_name")
        assert session["user"]["roles"] == ["User"]


@pytest.mark.parametrize("enabled", [False, True])
def test_isolated_runtime_preserves_normal_enabled_agent_core_tools(runtime, monkeypatch, enabled):
    class Kernel:
        def __init__(self):
            self.plugins = {}
            self.services = {}

    loaded_actions = []
    namespace = {
        "Kernel": Kernel, "logging": logging,
        "log_event": lambda *args, **kwargs: None, "debug_print": lambda *args: None,
        "create_logged_plugin_loader": lambda kernel: SimpleNamespace(
            load_multiple_plugins=lambda manifests, user: loaded_actions.extend(manifests),
        ),
        "is_tabular_processing_enabled": lambda settings: settings.get("enable_tabular_processing", False),
    }
    for name in ("time", "http", "wait", "math", "text", "fact_memory", "document_search", "tabular_processing", "chart", "embedding_model"):
        namespace[f"load_{name}_plugin"] = lambda kernel, *args, tool=name: kernel.plugins.setdefault(tool, tool)
    execute_functions("semantic_kernel_loader.py", {
        "load_plugins_for_kernel", "load_agent_core_plugins",
    }, namespace)
    settings = {
        "enable_http_plugin": enabled, "enable_wait_plugin": enabled,
        "enable_default_embedding_model_plugin": enabled, "enable_fact_memory_plugin": enabled,
    }
    normal = Kernel()
    namespace["load_plugins_for_kernel"](normal, [], settings)
    isolated = Kernel()
    namespace["load_agent_core_plugins"](isolated, settings)
    assert isolated.plugins == normal.plugins
    for tool in ("http", "wait", "embedding_model", "fact_memory"):
        assert (tool in isolated.plugins) is enabled
    assert loaded_actions == []

    monkeypatch.setitem(__import__("sys").modules, "semantic_kernel_loader", module(
        "semantic_kernel_loader", load_agent_core_plugins=namespace["load_agent_core_plugins"],
        load_single_agent_for_kernel=lambda kernel, target, *args, **kwargs: (kernel, {target["name"]: SimpleNamespace()}),
    ))
    real_kernel_module = importlib.import_module("semantic_kernel")
    monkeypatch.setattr(real_kernel_module, "Kernel", Kernel)
    root = runtime.contexts.AgentExecutionFrame(
        runtime.contexts.ExecutionIdentity("user-1"), agent("B"), runtime.contexts.DelegationBudget(),
    )
    with runtime.contexts.agent_execution(root):
        built, _ = runtime._build_local_agent(agent("B"), settings)
    assert built.plugins == normal.plugins


@pytest.mark.parametrize("isolated", [False, True])
def test_real_retry_helpers_apply_and_restore_actual_invocation_agent(runtime, monkeypatch, isolated):
    namespace = {}
    execute_functions("route_backend_chats.py", {
        "apply_agent_stream_retry_mode", "restore_agent_stream_retry_state",
    }, namespace)
    actual_agents = []
    invocations = []

    class Parent:
        def __init__(self):
            self.function_choice_behavior = "Auto"
            self.arguments = SimpleNamespace(execution_settings={"model": SimpleNamespace(function_choice_behavior="Auto")})
            self.service = SimpleNamespace(prompt_execution_settings=SimpleNamespace(function_choice_behavior="Auto"))
            self.kernel = SimpleNamespace(plugins={"delegate": SimpleNamespace(functions={"call_agent": object()})} if isolated else {})
            actual_agents.append(self)

        async def invoke_stream(self, messages):
            settings = self.arguments.execution_settings["model"]
            observed = (self.function_choice_behavior, settings.function_choice_behavior, self.service.prompt_execution_settings.function_choice_behavior)
            invocations.append(observed)
            if observed != (None, None, None):
                raise RuntimeError("auto tool choice requires a tool-call-parser")
            yield "retried answer"

    parent = Parent()
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda ref, **kwargs: agent("A"))
    monkeypatch.setattr(runtime, "_build_local_agent", lambda *args: (SimpleNamespace(services={}), Parent()))
    wrapped = runtime.prepare_agent_execution(
        parent, agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1"),
    )

    async def run():
        with pytest.raises(RuntimeError, match="tool-call-parser"):
            async for _ in wrapped.invoke_stream([]):
                pass
        state = namespace["apply_agent_stream_retry_mode"](wrapped, "disable_tools")
        try:
            assert [item async for item in wrapped.invoke_stream([])] == ["retried answer"]
        finally:
            namespace["restore_agent_stream_retry_state"](wrapped, state)

    asyncio.run(run())
    assert invocations == [("Auto", "Auto", "Auto"), (None, None, None)]
    assert all(value.function_choice_behavior == "Auto" for value in actual_agents)
    assert all(value.arguments.execution_settings["model"].function_choice_behavior == "Auto" for value in actual_agents)
    assert all(value.service.prompt_execution_settings.function_choice_behavior == "Auto" for value in actual_agents)
    assert wrapped._stream_retry_override is None


def test_completed_delegation_records_are_drained_once_with_original_citations(runtime):
    namespace = {"AgentExecution": runtime.AgentExecution}
    execute_functions("route_backend_chats.py", {
        "_merge_chat_token_usage", "_drain_agent_delegation_results",
    }, namespace)
    wrapped = runtime.prepare_agent_execution(
        SimpleNamespace(), agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1"),
    )
    wrapped.budget.record({
        "invocation_id": "finished", "success": True, "provenance": {"invocation_id": "finished"},
        "citations": [{"citation_id": "original", "file_name": "Assigned knowledge", "url": "https://example.test/source"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
    })
    wrapped.budget.record({"invocation_id": "unfinished", "success": False, "usage": None})
    citations = []
    usage = namespace["_drain_agent_delegation_results"](wrapped, None, citations)
    assert usage["total_tokens"] == 9 and usage["request_count"] == 1
    assert citations[0]["citation_id"] == "original" and len(citations) == 1
    assert namespace["_drain_agent_delegation_results"](wrapped, usage, citations) is usage
    assert len(citations) == 1 and wrapped.completed_delegation_count == 1


@pytest.mark.parametrize("partial_content,mixed_sources", [("", False), ("partial answer", False), ("rolled-back root answer", True)])
def test_actual_stream_stop_finalizer_persists_completed_child_sources_and_usage(runtime, partial_content, mixed_sources):
    """Execute the route's real cancellation finalizer against in-memory persistence."""
    namespace = {"AgentExecution": runtime.AgentExecution}
    execute_functions("route_backend_chats.py", {
        "_merge_chat_token_usage", "_drain_agent_delegation_results",
    }, namespace)
    source = ast.parse((APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8"))
    finalizer = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "finalize_cancelled_stream_response")
    code_objects = [compile(source, "route_backend_chats.py", "exec")]
    while code_objects:
        code = code_objects.pop()
        if code.co_name == "finalize_cancelled_stream_response":
            assert "log_token_usage" not in code.co_freevars
        code_objects.extend(value for value in code.co_consts if isinstance(value, CodeType))
    finalizer.body = [
        ast.copy_location(ast.Global(names=node.names), node) if isinstance(node, ast.Nonlocal) else node
        for node in finalizer.body
    ]
    wrapped = runtime.prepare_agent_execution(
        SimpleNamespace(), agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1"),
    )
    wrapped.budget.record({
        "invocation_id": "finished", "success": True, "provenance": {"invocation_id": "finished"},
        "citations": [{"citation_id": "child-source", "file_name": "Assigned knowledge", "url": "https://example.test/source"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
    })
    wrapped.budget.record({"invocation_id": "unfinished", "success": False, "usage": None})
    documents, usage_events, rollbacks = [], [], []
    namespace.update({
        "selected_agent": wrapped, "token_usage_data": None, "cancelled_stream_response": None,
        "stream_session": SimpleNamespace(get_cancel_reason=lambda: "user_requested"),
        "accumulated_content": partial_content, "mixed_source_manifest": {"id": "mixed"} if mixed_sources else None,
        "hybrid_citations_list": [{"citation_id": "root-evidence"}], "web_search_citations_list": [], "agent_citations_list": [],
        "generated_analysis_artifacts_list": [], "generated_tabular_outputs_list": [], "system_messages_for_augmentation": [],
        "user_id": "user-1", "conversation_id": "conversation", "user_message_id": "user-message",
        "assistant_message_id": "assistant-message", "user_info_for_assistant": {},
        "datetime": datetime, "logging": logging,
        "search_query": None, "hybrid_search_enabled": False, "search_results": [],
        "final_model_used": "model", "use_agent_streaming": True, "gpt_model": "model", "gpt_model_icon": None,
        "agent_display_name_used": "Parent", "agent_name_used": "A", "agent_icon_used": None, "agent_tags_used": [],
        "reasoning_effort": None, "frontend_gpt_model": None, "gpt_endpoint_id": None, "gpt_model_id": None,
        "gpt_provider": None, "gpt_response_length": None, "history_debug_info": {}, "source_review_result": None,
        "deep_research_result": None, "response_message_context": {}, "assistant_thread_attempt": 1,
        "thought_tracker": SimpleNamespace(enabled=False), "conversation_item": {"id": "conversation"},
        "effective_active_group_id": None, "effective_active_public_workspace_id": None,
        "apply_agent_document_citations": lambda *args, **kwargs: None,
        "_build_hybrid_citation_sort_key": lambda value: value,
        "_get_current_message_plugin_invocations": lambda *args: [],
        "build_cited_source_subsets": lambda *args, **kwargs: {"cited_hybrid_citations": [], "cited_web_search_citations": []},
        "persist_agent_citation_artifacts": lambda **kwargs: kwargs["agent_citations"],
        "_build_generated_analysis_metadata": lambda **kwargs: {},
        "make_json_serializable": lambda value: value,
        "cosmos_messages_container": SimpleNamespace(upsert_item=lambda document: documents.append(deepcopy(document))),
        "cosmos_conversations_container": SimpleNamespace(upsert_item=lambda document: None),
        "initialize_conversation_used_document_tracking": lambda *args: None,
        "collect_stream_response_conversation_metadata": lambda: None,
        "merge_cited_documents_into_conversation": lambda *args: None,
        "invalidate_conversation_cache_for_item": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None, "log_token_usage": lambda **kwargs: usage_events.append(kwargs),
        "_build_stream_cancel_event": lambda conversation_id, **kwargs: {"conversation_id": conversation_id, **kwargs},
        "_rollback_mixed_source_chat_publication": lambda *args: rollbacks.append(True),
        "compact_source_review_result_for_metadata": lambda result: None,
        "build_streaming_capability_usage": lambda: {},
        "delegation_citations": runtime.delegation_citations,
    })
    exec(compile(ast.Module(body=[finalizer], type_ignores=[]), "stream_stop_finalizer", "exec"), namespace)
    first = namespace["finalize_cancelled_stream_response"]()
    second = namespace["finalize_cancelled_stream_response"]()
    assert first is second and len(documents) == 1 and len(usage_events) == 1
    document = documents[0]
    assert document["content"] == ("" if mixed_sources else partial_content)
    assert document["metadata"]["token_usage"]["total_tokens"] == 9
    assert document["metadata"]["token_usage"]["request_count"] == 1
    assert document["agent_name"] == "A"
    assert [citation["citation_id"] for citation in document["agent_citations"]] == ["child-source"]
    assert first["extra_payload"]["metadata"]["token_usage"]["total_tokens"] == 9
    if mixed_sources:
        assert document["hybrid_citations"] == [] and rollbacks == [True]


def test_nonstream_fallback_rethrows_authentication_instead_of_generic_failure(runtime):
    source = ast.parse((APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "try_fallback_chain")

    class FoundryAgentUserAuthenticationRequired(RuntimeError):
        auth_response = {"scopes": ["foundry"], "consent_url": "https://login.example.test"}

    error = FoundryAgentUserAuthenticationRequired("Sign in.")
    namespace = {
        "FoundryAgentUserAuthenticationRequired": FoundryAgentUserAuthenticationRequired,
        "delegation_budget": SimpleNamespace(attempts=1), "log_event": lambda *args, **kwargs: None,
        "gpt_model": "model",
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "chat_fallback", "exec"), namespace)
    execute_functions("route_backend_chats.py", {"_agent_authentication_required_payload"}, namespace)

    def invoke():
        raise error

    with pytest.raises(FoundryAgentUserAuthenticationRequired) as caught:
        namespace["try_fallback_chain"]([{"name": "agent", "func": invoke, "on_success": lambda result: result}])
    assert caught.value is error
    payload = namespace["_agent_authentication_required_payload"](error)
    assert payload["auth_required"] and payload["scopes"] == ["foundry"]
    assert payload["consent_url"] == error.auth_response["consent_url"]
