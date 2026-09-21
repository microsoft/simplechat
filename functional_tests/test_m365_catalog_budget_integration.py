# test_m365_catalog_budget_integration.py
"""
Real-catalog, real-loader and real-Semantic-Kernel M365 budget integration.
Version: 0.261.035
Implemented in: 0.261.035

Fresh normal/optimized processes bootstrap real application modules with only
external Cosmos/model/Graph/storage I/O replaced. Required checks remain active
under optimized Python. The resolver and shipped catalog are never mocked.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_offline_scenarios():
    # Application modules must first import inside the external-I/O bootstrap seam.
    import asyncio
    from dataclasses import replace
    import json
    from types import SimpleNamespace
    from unittest.mock import patch
    from urllib.parse import urlsplit

    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as offline:
        import app
        from flask import Flask, session
        from semantic_kernel import Kernel
        from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
        from semantic_kernel.contents import AuthorRole, ChatHistory, ChatMessageContent, FunctionCallContent, FunctionResultContent, StreamingChatMessageContent
        from semantic_kernel.functions import KernelArguments
        from pydantic import Field
        import semantic_kernel_loader as loader
        import functions_m365_agent_continuation as continuation
        import functions_m365_file_runtime as file_runtime
        import functions_m365_retrieval as retrieval
        import functions_m365_execution as execution
        from functions_m365_transport import M365ProviderError
        from functions_m365_operations import normalize_m365_action_config
        from functions_model_capabilities import ModelTokenBudget, ModelTokenBudgetError, resolve_model_token_budget
        from semantic_kernel_plugins.m365_sharepoint_plugin import M365SharePointPlugin
        from test_m365_provider_core import FakeResponse, GraphFixture
        from test_conversation_working_memory import MemoryHarness
        from test_m365_agent_continuation import Memory
        from test_support.m365 import CosmosContainer

        class OfflineModel(OpenAIChatCompletion):
            requests: list = Field(default_factory=list)
            tool_results: list = Field(default_factory=list)

            async def _inner_get_chat_message_contents(self, chat_history, settings):
                self.requests.append(settings.prepare_settings_dict())
                has_result = any(message.role == AuthorRole.TOOL for message in chat_history.messages)
                if has_result:
                    self.tool_results.extend(
                        item.result for message in chat_history.messages if message.role == AuthorRole.TOOL
                        for item in message.items if hasattr(item, "result")
                    )
                    return [ChatMessageContent(role=AuthorRole.ASSISTANT, content="The retained SharePoint report says <safe>.")]
                return [ChatMessageContent(role=AuthorRole.ASSISTANT, items=[
                    FunctionCallContent(id="budget-call", name="m365_sharepoint-search_files", arguments='{"query":"report"}'),
                ])]

            async def _inner_get_streaming_chat_message_contents(self, chat_history, settings, function_invoke_attempt=0):
                results = await self._inner_get_chat_message_contents(chat_history, settings)
                for message in results:
                    yield [StreamingChatMessageContent(
                        role=message.role, content=message.content, items=message.items, choice_index=0,
                    )]

        class OwnerGraph(GraphFixture):
            def request(self, method, url, **kwargs):
                response = super().request(method, url, **kwargs)
                if urlsplit(url).path.endswith("/me"):
                    return FakeResponse({**json.loads(response.body), "id": "owner"})
                return response

        harness = MemoryHarness()
        journal_memory = Memory()
        jobs = CosmosContainer("user_id")
        manifest = {
            **normalize_m365_action_config("m365_sharepoint", {"id": "action-1", "name": "m365_sharepoint"}),
            "type": "m365_sharepoint", "source": "spo",
        }
        saved_actions = CosmosContainer("user_id")
        saved_actions.create_item(body={**manifest, "user_id": "owner"})
        execution.configure_m365_execution(
            action_config_resolver=lambda context, action_id, source: saved_actions.read_item(action_id, "owner"),
            action_selection_resolver=lambda context: ["action-1"],
        )
        context = execution.M365ExecutionContext(
            "owner", "owner", "tenant", request_id="request", conversation_id="conversation",
            action_configs={"action-1": manifest},
        )

        def binding(candidate):
            return harness.store, replace(harness.context, request_id=candidate.request_id)

        def request_run(candidate):
            return retrieval.create_m365_request_budget(*binding(candidate), candidate)

        retrieval.configure_m365_retrieval(
            memory_resolver=binding, request_run_resolver=request_run,
            model_budget_resolver=file_runtime.resolve_m365_model_room,
            token_counter=file_runtime.count_m365_context_tokens,
        )
        continuation.configure_m365_agent_continuation(
            memory_resolver=lambda candidate: (journal_memory, object()), jobs_factory=lambda: jobs,
            model_context_setter=file_runtime.configure_m365_model_context,
            model_context_reset=file_runtime.reset_m365_model_context,
        )
        endpoint = {
            "id": "endpoint", "provider": "aoai", "enabled": True, "contextWindow": 200000,
            "connection": {"endpoint": "https://budget.invalid", "api_version": "2025-01-01-preview"},
            "auth": {"type": "api_key", "api_key": "offline"},
            "models": [{
                "id": "row", "deploymentName": "friendly-deployment",
                "catalogModelId": "gpt-5.6-terra", "modelVersion": "2026-07-09",
                "responseLength": 2048, "outputTokenLimit": 16000,
            }],
        }
        settings = {"model_endpoints": [endpoint], "default_model_selection": {"endpoint_id": "endpoint", "model_id": "row"}}
        app.configure_application_cache(
            settings, None, redis_client_factory=app.functions_redis_client.create_redis_client,
        )
        agent_config = {
            "id": "budget-agent", "name": "budget_agent", "instructions": "Use the SharePoint search tool.",
            "is_global": True, "model_endpoint_id": "endpoint", "model_id": "row",
            "reasoning_effort": "none",
        }
        web = Flask("budget-integration")
        web.secret_key = "offline"

        def create_agent(configuration, configuration_settings):
            def model_service(resolved, service_id, app_settings=None):
                return OfflineModel(ai_model_id=resolved["deployment"], service_id=service_id, api_key="offline")

            kernel = Kernel()
            with patch.object(loader, "create_model_endpoint_chat_completion_service", model_service):
                _kernel, agents = loader.load_single_agent_for_kernel(
                    kernel, configuration, configuration_settings, SimpleNamespace(),
                )
            require(bool(agents), "Actual loader did not construct the selected agent.")
            return next(iter(agents.values()))

        with web.test_request_context():
            session["user"] = {"oid": "owner"}
            agent = create_agent(agent_config, settings)
            budget = agent.model_token_budget
            require(isinstance(budget, ModelTokenBudget), "Agent lost its typed budget.")
            require(budget.context_window == 200000, "Endpoint context override was lost.")
            require(budget.input_limit == 922000, "Partial overrides hid catalog input capacity.")
            require(budget.output_limit == 16000, "Model output override was lost.")
            require(budget.request_output_limit == 2048, "Response Length did not reach the agent.")
            require(budget.model_id == "gpt-5.6-terra", "Deployment alias lost canonical identity.")
            require("offline" not in repr(budget) and "budget.invalid" not in repr(budget), "Budget leaked endpoint credentials.")
            invalid = create_agent({**agent_config, "max_completion_tokens": 16001}, settings)
            with execution.m365_execution_context(replace(context, request_id="invalid-cap")):
                try:
                    offline.loop.run_until_complete(invalid.invoke(messages="Search for report"))
                except ModelTokenBudgetError as error:
                    require(error.code == "model_context_invalid", "Invalid cap was not a typed configuration error.")
                    require("Response Length" in error.payload["error"], "Invalid cap lacks an actionable public message.")
                    require("auth_required" not in error.payload, "Invalid cap requested reconnection.")
                else:
                    raise AssertionError("Generation beyond the provider limit reached inference.")
            require(invalid.service.requests == [], "Invalid generation cap reached the provider.")
            inherited = create_agent({**agent_config, "model_endpoint_id": "", "model_id": ""}, settings)
            require(inherited.model_token_budget == budget, "Default selection did not propagate the same budget.")

            graph = OwnerGraph("spo")
            plugin = M365SharePointPlugin(manifest)
            plugin._operations.transport = graph.transport()
            agent.kernel.add_plugin(plugin, plugin_name="m365_sharepoint")
            with execution.m365_execution_context(context):
                result = offline.loop.run_until_complete(agent.invoke(messages="Search SharePoint for report."))
            require(result is not None and graph.calls, "Real SharePoint search did not reach the Graph transport.")
            require(any("/search/query" in url for _method, url, _kwargs in graph.calls), "Graph search was not invoked.")
            require(agent.service.tool_results, "No tool result reached the model.")
            tool_result = agent.service.tool_results[-1]
            if isinstance(tool_result, str):
                tool_result = json.loads(tool_result)
            require("error" not in tool_result, f"SharePoint tool failed: {tool_result}")
            require(bool(tool_result.get("results")), "No SharePoint evidence reached the model.")
            require(bool(tool_result["results"][0].get("evidence_id")), "Source evidence was not retained.")
            require(bool(tool_result["results"][0].get("excerpts")), "Retained excerpts were not returned.")
            require(agent.service.requests[0]["max_completion_tokens"] == 2048, "Wire cap differs from the budget.")
            require("max_tokens" not in agent.service.requests[0], "Two output-limit parameters were sent.")
            require(agent.service.requests[0]["extra_body"]["reasoning_effort"] == "none", "Explicit none did not reach the provider.")
            require(file_runtime._model_context.get() is None, "Finished invocation leaked model context.")
            require(continuation._current_journal.get() is None, "Finished invocation leaked its journal.")

            stream_context = replace(context, request_id="stream-request")

            async def stream():
                return [chunk async for chunk in agent.invoke_stream(messages="Search SharePoint for report.")]

            prior_calls = len(graph.calls)
            with execution.m365_execution_context(stream_context):
                streamed = offline.loop.run_until_complete(stream())
            require(bool(streamed) and len(graph.calls) > prior_calls, "Streaming did not invoke real SharePoint search.")
            require(file_runtime._model_context.get() is None, "Streaming leaked its budget context.")

            history = ChatHistory()
            history.add_user_message("Search for report")
            history.add_message(ChatMessageContent(role=AuthorRole.ASSISTANT, items=[
                FunctionCallContent(id="completed", name="m365_sharepoint-search_files", arguments='{"query":"report"}'),
            ]))
            history.add_message(ChatMessageContent(role=AuthorRole.TOOL, items=[
                FunctionResultContent(id="completed", name="m365_sharepoint-search_files", result=tool_result),
            ]))
            resume_context = replace(context, request_id="resume-request")
            changed = create_agent({**agent_config, "max_completion_tokens": 1000}, settings)
            changed.kernel.add_plugin(plugin, plugin_name="m365_sharepoint")

            async def checkpoint_roundtrip():
                journal = continuation.AgentContinuationJournal(agent, resume_context)
                try:
                    await journal.prepare((), {"messages": "Search for report"})
                    journal._save_history(history)
                finally:
                    journal.close()
                resumed = continuation.AgentContinuationJournal(agent, resume_context)
                prior_calls = len(graph.calls)
                try:
                    _args, resumed_kwargs = await resumed.prepare((), {})
                    room = file_runtime.resolve_m365_model_room(resume_context)
                    require(room > 0 and resumed_kwargs["thread"] is not None, "Resumed history lost its model budget.")
                    require(len(graph.calls) == prior_calls, "Completed search was replayed during resume.")
                finally:
                    resumed.close()
                changed_journal = continuation.AgentContinuationJournal(changed, resume_context)
                try:
                    try:
                        await changed_journal.prepare((), {})
                    except execution.M365PolicyError as error:
                        require(error.code == "m365_agent_changed", "Budget change produced the wrong recovery error.")
                    else:
                        raise AssertionError("A paused request silently changed generation allowance.")
                finally:
                    changed_journal.close()

            offline.loop.run_until_complete(checkpoint_roundtrip())

            for field, value in (("max_completion_tokens", 512), ("max_completion_tokens", 1024)):
                override = OpenAIChatPromptExecutionSettings(service_id=agent.service.service_id, **{field: value})
                merged = agent._merge_arguments(KernelArguments(settings=override))
                _service, actual = offline.loop.run_until_complete(agent._get_chat_completion_service_and_settings(agent.kernel, merged))
                require(actual.max_completion_tokens == value, "Per-request output cap was ignored.")
            defaults = next(iter(agent.arguments.execution_settings.values()))
            require(defaults.max_completion_tokens == 2048, "Per-request settings mutated shared defaults.")
            default_override = KernelArguments(settings=OpenAIChatPromptExecutionSettings(max_completion_tokens=256))
            merged = agent._merge_arguments(default_override)
            _service, actual = offline.loop.run_until_complete(agent._get_chat_completion_service_and_settings(agent.kernel, merged))
            require(actual.max_completion_tokens == 256, "A default-key request cap lost precedence to the pinned service.")
            try:
                agent._merge_arguments(KernelArguments(settings=OpenAIChatPromptExecutionSettings(
                    service_id="unrelated-service", max_completion_tokens=10,
                )))
            except ModelTokenBudgetError as error:
                require(error.code == "model_context_invalid", "Cross-service override used the wrong failure code.")
            else:
                raise AssertionError("A request could replace the service without replacing its model budget.")
            original_service = agent.service
            replacement = OfflineModel(
                ai_model_id="different-model", service_id=original_service.service_id, api_key="offline",
            )
            agent.kernel.add_service(replacement, overwrite=True)
            try:
                try:
                    offline.loop.run_until_complete(agent._get_chat_completion_service_and_settings(
                        agent.kernel, agent._merge_arguments(None),
                    ))
                except ModelTokenBudgetError as error:
                    require(error.code == "model_context_invalid", "Replaced service did not fail as a budget mismatch.")
                else:
                    raise AssertionError("A same-ID service replacement borrowed another model's budget.")
            finally:
                agent.kernel.add_service(original_service, overwrite=True)

            async def isolated_contexts():
                ready = asyncio.Event()
                async def one(cap, expected):
                    token = file_runtime.configure_m365_model_context(
                        ModelTokenBudget(context_window=10000, request_output_limit=cap, output_accounting="total_generation"),
                        [], tool_schemas=[],
                    )
                    try:
                        ready.set()
                        await ready.wait()
                        await asyncio.sleep(0)
                        room = file_runtime.resolve_m365_model_room(context)
                        require(room == expected, "Concurrent tasks shared model-budget state.")
                    finally:
                        file_runtime.reset_m365_model_context(token)
                await asyncio.gather(one(1000, 4902), one(2000, 3902))

            offline.loop.run_until_complete(isolated_contexts())
            unknown_token = file_runtime.configure_m365_model_context("unknown-model", [])
            try:
                try:
                    file_runtime.resolve_m365_model_room(context)
                except M365ProviderError as error:
                    require(error.code in ("model_context_unavailable", "model_generation_unbounded"), "Unknown model looked like an authentication failure.")
                else:
                    raise AssertionError("Unknown model received an invented budget.")
            finally:
                file_runtime.reset_m365_model_context(unknown_token)

            terra = resolve_model_token_budget("gpt-5.6-terra")
            require((terra.context_window, terra.input_limit, terra.output_limit) == (1050000, 922000, 128000), "Shipped Terra data is incomplete.")
            require(terra.remaining_input() == 922000, "Shared/input ceilings were conflated.")
            require(budget.tool_reasoning_efforts == ("none",), "Azure tool/reasoning profile was lost.")
            unversioned = resolve_model_token_budget("gpt-5.6-terra", provider="azure")
            require(unversioned.tool_reasoning_efforts == ("none",), "Existing unversioned Terra deployments lost the tool-compatible default.")

            def model_service(resolved, service_id, app_settings=None):
                return OfflineModel(ai_model_id=resolved["deployment"], service_id=service_id, api_key="offline")

            specialists = [
                {**agent_config, "id": name, "name": name, "max_completion_tokens": cap}
                for name, cap in (("first_specialist", 512), ("second_specialist", 1024))
            ]
            with patch.object(loader, "get_global_agents", return_value=specialists), patch.object(
                loader, "get_global_actions", return_value=[],
            ), patch.object(loader, "create_model_endpoint_chat_completion_service", model_service):
                _kernel, loaded = loader.load_semantic_kernel(Kernel(), {**settings, "enable_multi_agent_orchestration": True})
            require(loaded is not None and len(loaded) == 2, "Specialist construction lost an agent.")
            for name, expected in (("first_specialist", 512), ("second_specialist", 1024)):
                specialist = loaded[name]
                actual_service, actual_settings = offline.loop.run_until_complete(
                    specialist._get_chat_completion_service_and_settings(
                        specialist.kernel, specialist._merge_arguments(None),
                    )
                )
                require(actual_service.service_id == specialist.service.service_id, "Specialists shared the first model service.")
                require(actual_settings.max_completion_tokens == expected, "Specialists shared a generation cap.")


@pytest.mark.parametrize("optimized", [False, True])
def test_real_catalog_loader_agent_and_sharepoint_runtime(optimized):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command += [
        "-c",
        "import sys; sys.path[:0] = sys.argv[1:3]; from test_m365_catalog_budget_integration import run_offline_scenarios; run_offline_scenarios()",
        str(APP), str(TESTS),
    ]
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, env=environment)
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-10000:]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
