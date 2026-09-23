# test_orchestration_local_agent_capture.py
"""Actual local-agent loader bindings through the private acquisition contract.

Version: 0.261.127
Implemented in: 0.261.127

Uses the real resolver, SDK construction, prepared manifests and strict attestor.
External storage/model I/O is doubled; no live model or user artifact is created.
"""

import asyncio
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from semantic_kernel import Kernel
from semantic_kernel.contents import ChatMessageContent

from test_orchestration_external_configuration_capture import _private_digest, gather_modules
from test_orchestration_external_sources import ExternalSourceWorld


@pytest.fixture
def local_capture(gather_modules, monkeypatch):
    loader = importlib.import_module("semantic_kernel_loader")
    capture_types = importlib.import_module("functions_orchestration_invocation_capture")
    configuration = gather_modules.configuration
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    manifests = importlib.import_module("functions_action_manifest")
    state = SimpleNamespace(
        loader=loader, modules=gather_modules, capture_types=capture_types,
        events=[], sources=[], services=[], prompts=[], plugins=[], refusal=None,
    )
    state.settings = {
        "per_user_semantic_kernel": False,
        "azure_openai_gpt_endpoint": "https://example.invalid/",
        "azure_openai_gpt_key": "PRIVATE_AGENT_KEY",
        "azure_openai_gpt_api_version": "2024-10-21",
        "gpt_model": {"selected": [{"deploymentName": "gpt-4o", "modelName": "gpt-4o"}]},
        "max_auto_invoke_attempts": 4,
    }
    state.agent = {
        "id": "agent-1", "name": "Lookup", "display_name": "Lookup",
        "scope_type": "global", "scope_id": "global", "is_global": True, "is_group": False,
        "agent_type": "local", "instructions": "Return the requested facts.",
        "max_completion_tokens": 96, "actions_to_load": [],
    }
    state.producer = contracts.ProducerIdentity(
        "owner", "conversation-1", "run-1", 1, "gather", "agent_invoke", "external-test-v2",
    )
    state.selector = "global:global:agent-1"
    state.kernel = Kernel()
    state.manifest = manifests.bind_action_origin({
        "id": "lookup", "name": "facts", "type": "openapi",
        "description": "Read a fact.", "endpoint": "https://api.example.invalid",
        "openapi_spec_content": {
            "openapi": "3.0.0", "info": {"title": "Facts", "version": "1"},
            "servers": [{"url": "https://api.example.invalid"}],
            "paths": {"/fact": {"get": {
                "operationId": "lookup", "summary": "Read the current fact.",
                "responses": {"200": {"description": "A fact"}},
            }}},
        },
    }, "global", "global")
    state.resolve = Mock(wraps=loader.resolve_agent_config)
    monkeypatch.setattr(loader, "resolve_agent_config", state.resolve)
    monkeypatch.setattr(
        loader, "_get_governed_global_plugin_manifests",
        lambda *args, **kwargs: [deepcopy(state.manifest)],
    )
    constructor = loader.create_model_endpoint_chat_completion_service

    def construct(*args, **kwargs):
        state.events.append("construct-model")
        service = constructor(*args, **kwargs)
        state.services.append(service)
        return service

    monkeypatch.setattr(loader, "create_model_endpoint_chat_completion_service", construct)
    prepare = loader.prepare_action_plugin_manifest

    def prepare_manifest(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        state.events.append("prepare-plugin")
        state.plugins.append(deepcopy(prepared))
        return prepared

    monkeypatch.setattr(loader, "prepare_action_plugin_manifest", prepare_manifest)

    async def complete(service, chat_history, settings):
        state.events.append("model")
        state.prompts.append(settings.prepare_settings_dict())
        return [ChatMessageContent(role="assistant", content="Full local findings.\nLAST-LOCAL-RECORD")]

    monkeypatch.setattr(loader.AzureChatCompletion, "_inner_get_chat_message_contents", complete)

    def current_metadata(source_type, **kwargs):
        source = kwargs["source"]
        settings = kwargs["settings"]
        config = loader.resolve_agent_config(
            deepcopy(source), deepcopy(settings), execution_user_id="owner",
        )
        config["reasoning_effort"] = source.get("reasoning_effort", config.get("reasoning_effort"))
        model_capture = importlib.import_module("functions_orchestration_model_capture")
        prepared = []
        if source["actions_to_load"]:
            prepared = [prepare(deepcopy(state.manifest), settings)]
        return {
            "version": "orchestration-external-acquisition-v1", "kind": "agent", "phase": "current",
            "reference": {"id": "agent-1", "scope_type": "global", "scope_id": "global"},
            "resolved_config": model_capture.local_agent_configuration(
                config, instructions=config["instructions"],
                maximum_auto_invoke_attempts=loader.get_max_auto_invoke_attempts(settings),
            ),
            "prepared_plugins": prepared,
            "model": {
                "provider": "aoai", "protocol": "azure_openai", "endpoint": config["endpoint"],
                "api_version": config["api_version"], "deployment": config["deployment"],
                "endpoint_id": None, "model_id": None,
                "parameters": {
                    "max_tokens": config["max_completion_tokens"],
                    **({"tool_choice": "auto"} if prepared else {}),
                },
            },
        }

    state.current_metadata = current_metadata
    state.attestor = configuration.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation-1",
        private_digest=_private_digest, read_current_source=current_metadata,
    )

    def capture(source_type, **kwargs):
        source = kwargs["source"]
        state.events.append("preflight" if source is None else "capture")
        if state.refusal == ("preflight" if source is None else "resolved"):
            return False
        if source is None:
            return
        state.attestor.capture(source_type, producer=state.producer, **kwargs)
        state.sources.append(deepcopy(source))

    state.capture = capture_types.OrchestrationInvocationCapture(capture)
    try:
        yield state
    finally:
        for service in state.services:
            asyncio.run(service.client.close())


def load(state, *, capture=True):
    return state.loader.load_single_agent_for_kernel(
        state.kernel, deepcopy(state.agent), state.settings, SimpleNamespace(),
        execution_user_id="owner",
        **({"invocation_capture": state.capture} if capture else {}),
    )


@pytest.mark.parametrize("plugins", [False, True])
def test_real_loader_emits_only_actual_configuration_and_prepared_bindings(local_capture, plugins):
    state = local_capture
    if plugins:
        state.agent["actions_to_load"] = ["lookup"]
    kernel, agents = load(state)
    state.capture.require_valid(captured=True)
    assert kernel is state.kernel
    assert state.resolve.call_count == 1
    assert state.events[0] == "preflight"
    assert state.sources
    source = state.sources[-1]
    assert source["version"] == "orchestration-external-acquisition-v1"
    assert source["kind"] == "agent" and source["phase"] == "resolved"
    assert source["resolved_config"]["instructions"] == agents["Lookup"].instructions
    assert source["resolved_config"]["max_auto_invoke_attempts"] == 4
    assert "token_provider" not in source["resolved_config"]
    assert source["prepared_plugins"] == state.plugins
    assert bool(kernel.plugins) is plugins
    assert source["model"]["parameters"] == {
        "max_tokens": 96, **({"tool_choice": "auto"} if plugins else {}),
    }
    assert source["model"]["deployment"] == state.services[0].ai_model_id
    assert source["model"]["endpoint"] == str(state.services[0].client._azure_endpoint)
    json.dumps(source, allow_nan=False)

    response = asyncio.run(agents["Lookup"].get_response(messages="Read the requested fact."))
    assert "LAST-LOCAL-RECORD" in str(response)
    assert state.events.index("capture") < state.events.index("model")
    assert state.prompts[-1]["max_tokens"] == 96
    actual_parameters = {
        key: value for key, value in state.prompts[-1].items() if key not in ("stream", "tools")
    }
    assert source["model"]["parameters"] == actual_parameters
    captured = state.attestor.for_admission(
        "agent", producer=state.producer, settings=state.settings,
        source=state.agent, selector=state.selector,
    )
    restarted = state.modules.configuration.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation-1",
        private_digest=_private_digest, read_current_source=state.current_metadata,
    )
    current = restarted.current(
        "agent", producer=state.producer, settings=state.settings, source=state.agent,
    )
    assert captured == current
    assert restarted._captures == {}


def test_preflight_refusal_precedes_configuration_and_model_construction(local_capture):
    state = local_capture
    state.refusal = "preflight"
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    state.resolve.assert_not_called()
    assert state.services == state.prompts == []


@pytest.mark.parametrize("plugins", [False, True])
def test_real_loader_provider_and_complete_result_survive_restart_without_capture_map(local_capture, plugins):
    state = local_capture
    if plugins:
        state.agent["actions_to_load"] = ["lookup"]
    with ExternalSourceWorld("agent_invoke") as world:
        world.services.records["agents", "group"].clear()
        record = world.services.add(
            "agents", "global", "global", {**deepcopy(state.agent), "is_enabled": True},
        )
        world.agent_selector = state.selector
        world.settings.update(state.settings)
        state.settings = world.settings
        state.producer = world.fixture.producer
        provider = world.provider(
            read_configuration=state.attestor.current, configuration_admitter=state.attestor.for_admission,
        )

        def capture(source_type, **kwargs):
            provider.preflight_gather_invocation(producer=state.producer, selector=kwargs["selector"])
            if kwargs["source"] is not None:
                state.attestor.capture(source_type, producer=state.producer, **kwargs)

        state.capture = state.capture_types.OrchestrationInvocationCapture(capture)
        _, agents = load(state)
        response = asyncio.run(agents["Lookup"].get_response(messages="Return all the requested facts."))
        world.prepared["notes"] = [str(response)]
        admitted = world.admit(provider)
        service = world.service(provider, admitted)
        fingerprint = "f" * 64
        task = world.persist(service, admitted, input_fingerprint=fingerprint)
        calls_before_restart = (len(state.services), len(state.prompts))

        restarted = state.modules.configuration.OrchestrationExternalConfigurationAttestor(
            user_id="owner", conversation_id="conversation-1",
            private_digest=_private_digest, read_current_source=state.current_metadata,
        )
        fresh_provider = world.provider(read_configuration=restarted.current, configuration_admitter=None)
        fresh_service = world.service(fresh_provider)
        recovered = fresh_service.recover_task_result(
            producer=state.producer, input_fingerprint=fingerprint,
        )
        assert recovered == task
        reader = fresh_service.open_result(recovered.output("prepared"), require_current_sources=True)
        restored = reader.read_value()
        assert restored == world.prepared
        assert "LAST-LOCAL-RECORD" in restored["notes"][0]
        assert restarted._captures == {} and fresh_service.access.external_source_catalog == {}
        assert calls_before_restart == (len(state.services), len(state.prompts))
        assert "PRIVATE_AGENT_KEY" not in json.dumps(task.to_dict())

        record["instructions"] = "Changed current configuration."
        with pytest.raises(state.modules.configuration.ResultUnavailableError):
            reader.read_value()
        assert calls_before_restart == (len(state.services), len(state.prompts))


def test_configuration_refusal_precedes_actual_model_invocation(local_capture):
    state = local_capture
    state.refusal = "resolved"
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    assert state.prompts == []
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        state.capture.require_valid()


@pytest.mark.parametrize("plugin_type", ["agent", "sql_schema", "cosmos_query", "mcp"])
def test_unproven_plugin_modes_never_reach_loading_or_model(local_capture, plugin_type, monkeypatch):
    state = local_capture
    state.agent["actions_to_load"] = ["lookup"]
    state.manifest["type"] = plugin_type
    fallback = Mock(side_effect=AssertionError("Captured failures must not retry through legacy loading."))
    monkeypatch.setattr(state.loader, "_load_agent_plugins_original_method", fallback)
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    fallback.assert_not_called()
    assert state.kernel.plugins == {}
    assert state.prompts == []
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        state.capture.require_valid()


@pytest.mark.parametrize("failure", ["load_failed", "service", "cancelled", "private"])
def test_prepared_plugin_failure_is_sticky_and_never_retries_loading(local_capture, monkeypatch, failure):
    state = local_capture
    state.agent["actions_to_load"] = ["lookup"]
    configuration = state.modules.configuration
    errors = {
        "service": configuration.ExternalConfigurationServiceError("external_configuration_timeout"),
        "cancelled": configuration.ExternalConfigurationCancelledError(),
        "private": RuntimeError("PRIVATE_PLUGIN_FAILURE"),
    }
    plugin_loader = SimpleNamespace(load_multiple_plugins=Mock(return_value={"facts": False}))
    if failure != "load_failed":
        plugin_loader.load_multiple_plugins.side_effect = errors[failure]
    monkeypatch.setattr(state.loader, "create_logged_plugin_loader", lambda kernel: plugin_loader)
    fallback = Mock(side_effect=AssertionError("Captured execution must not enter a fallback loader."))
    monkeypatch.setattr(state.loader, "_load_agent_plugins_original_method", fallback)
    expected = (
        type(errors[failure]) if failure in ("service", "cancelled")
        else state.capture_types.OrchestrationInvocationCaptureError
    )
    with pytest.raises(expected) as caught:
        load(state)
    assert state.sources and state.prompts == []
    assert "PRIVATE_PLUGIN_FAILURE" not in str(caught.value)
    fallback.assert_not_called()
    with pytest.raises(expected) as sticky:
        state.capture.require_valid(captured=True)
    if failure == "service":
        assert sticky.value.code == "external_configuration_timeout" and sticky.value.retryable


def test_remote_schema_dependencies_are_refused_before_plugin_loading(local_capture):
    state = local_capture
    state.agent["actions_to_load"] = ["lookup"]
    state.manifest["openapi_spec_content"]["components"] = {
        "schemas": {"External": {"$ref": "https://schema.example.invalid/remote"}},
    }
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    assert state.plugins == [] and state.kernel.plugins == {} and state.prompts == []


def test_unparsed_inline_json_is_withheld_before_plugin_loading(local_capture):
    state = local_capture
    state.agent["actions_to_load"] = ["lookup"]
    state.manifest["openapi_spec_content"] = json.dumps(state.manifest["openapi_spec_content"])
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    assert state.plugins == [] and state.kernel.plugins == {} and state.prompts == []


def test_runtime_credentials_are_not_serialized_or_invoked_for_capture(local_capture, monkeypatch):
    state = local_capture
    resolver = state.resolve
    token_provider = Mock(side_effect=AssertionError("Unproven credential binding must remain unused."))

    def resolve(*args, **kwargs):
        config = resolver(*args, **kwargs)
        config["token_provider"] = token_provider
        return config

    monkeypatch.setattr(state.loader, "resolve_agent_config", resolve)
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    token_provider.assert_not_called()
    assert state.services == state.sources == state.prompts == []


@pytest.mark.parametrize("change", ["instructions", "api_version", "plugins", "arguments", "unknown_control"])
def test_changed_actual_bindings_stop_before_model_and_remain_poisoned(local_capture, change, monkeypatch):
    state = local_capture
    _, agents = load(state)
    agent = agents["Lookup"]
    service = state.services[0]
    with monkeypatch.context() as changes:
        if change == "instructions":
            changes.setattr(agent, "instructions", "Changed bound instructions.")
        elif change == "api_version":
            changes.setattr(service.client, "_api_version", "changed")
        elif change == "plugins":
            state.loader.load_time_plugin(state.kernel)
        else:
            settings = agent.arguments.execution_settings[service.service_id]
            changes.setattr(settings, "max_tokens" if change == "arguments" else "stop", 95 if change == "arguments" else ["stop"])
        with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
            asyncio.run(agent.get_response(messages="This must not execute."))
    assert state.prompts == []
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        state.capture.require_valid(captured=True)


def test_existing_model_budget_guard_keeps_its_own_typed_failure(local_capture, monkeypatch):
    state = local_capture
    _, agents = load(state)
    budgets = importlib.import_module("functions_model_capabilities")
    monkeypatch.setattr(state.services[0], "ai_model_id", "different-deployment")
    with pytest.raises(budgets.ModelTokenBudgetError) as caught:
        asyncio.run(agents["Lookup"].get_response(messages="This must not execute."))
    assert caught.value.code == "model_context_invalid"
    assert state.prompts == []


def test_invalid_model_budget_fails_before_constructing_a_client(local_capture):
    state = local_capture
    state.agent["max_completion_tokens"] = "not-a-token-limit"
    budgets = importlib.import_module("functions_model_capabilities")
    with pytest.raises(budgets.ModelTokenBudgetError):
        load(state)
    assert state.services == state.prompts == []


def test_model_guard_repeats_real_authority_capture_before_each_request(local_capture):
    state = local_capture
    _, agents = load(state)
    captured_before = len(state.sources)
    response = asyncio.run(agents["Lookup"].get_response(messages="First request."))
    assert "LAST-LOCAL-RECORD" in str(response)
    assert len(state.sources) > captured_before
    state.refusal = "resolved"
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        asyncio.run(agents["Lookup"].get_response(messages="Denied request."))
    assert len(state.prompts) == 1


def test_function_guard_refusal_survives_sdk_containment_without_tool_transport(local_capture):
    state = local_capture
    state.agent["actions_to_load"] = ["lookup"]
    kernel, _ = load(state)
    state.refusal = "resolved"
    try:
        asyncio.run(kernel.invoke(plugin_name="facts", function_name="lookup"))
    except Exception:
        # SK versions may wrap or contain a function-filter error; refusal must survive either.
        pass
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        state.capture.require_valid(captured=True)
    assert state.prompts == []


@pytest.mark.parametrize("entry", ["core", "loader"])
def test_implicit_core_tools_and_omitted_hook_cannot_escape_an_active_capture(local_capture, entry):
    state = local_capture
    contexts = importlib.import_module("agent_execution_context")
    frame = contexts.AgentExecutionFrame(
        contexts.ExecutionIdentity("owner", "conversation-1"), state.agent, contexts.DelegationBudget(),
        invocation_capture=state.capture, invocation_settings=state.settings,
    )
    with contexts.agent_execution(frame):
        with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
            if entry == "core":
                state.loader.load_agent_core_plugins(state.kernel, state.settings)
            else:
                load(state, capture=False)
    state.resolve.assert_not_called()
    assert state.kernel.plugins == {} and state.services == []


def test_prepopulated_kernel_cannot_claim_an_empty_prepared_plugin_set(local_capture):
    state = local_capture
    state.loader.load_time_plugin(state.kernel)
    with pytest.raises(state.capture_types.OrchestrationInvocationCaptureError):
        load(state)
    state.resolve.assert_not_called()
    assert state.sources == []


def test_ordinary_loader_still_accepts_existing_core_plugins(local_capture):
    state = local_capture
    state.loader.load_time_plugin(state.kernel)
    kernel, agents = load(state, capture=False)
    assert kernel.plugins
    assert "Lookup" in agents
    assert state.sources == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
