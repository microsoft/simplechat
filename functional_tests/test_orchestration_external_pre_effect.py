# test_orchestration_external_pre_effect.py
"""
Functional tests for current and actual configuration support before acquisition.
Version: 0.261.127
Implemented in: 0.261.127

Real provider authorization, scoped resolvers, metadata reconstruction, attestor
projections and acquisition hooks run with only external/storage I/O doubled.
Unsupported or different actual configurations never reach a paid run/tool.
Preparation and definition validation create no synthetic completion proof.
Refs microsoft/simplechat#1509.
"""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

from azure.ai.agents.models import Agent
from azure.core.exceptions import ServiceRequestError
import pytest
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from test_orchestration_external_configuration_capture import capture_runtime, gather_modules, run_gather
from test_orchestration_external_metadata import (
    action_source, agent_source, foundry_capture, metadata_world, new_attestor, producer,
)


@pytest.fixture
def pre_effect_world(metadata_world, capture_runtime):
    world = metadata_world
    runtime = capture_runtime
    source_module = importlib.import_module("functions_orchestration_external_sources")
    world.settings.update(
        enable_url_access=True, enable_source_review=True, enable_deep_source_review=False,
        require_member_of_url_access_user=True, require_member_of_deep_research_user=True,
        per_user_semantic_kernel=True, chat_orchestration_enabled_capabilities=[],
        max_auto_invoke_attempts=5, deep_research_enable_query_planning=False,
    )
    world.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]["agent_id"] = "original-agent"
    world.agent_store.items["agent-one"]["other_settings"] = deepcopy(
        world.settings["web_search_agent"]["other_settings"]
    )
    world.definition = deepcopy(runtime.state.definition)
    world.run_store.items["run"].update(
        status="running", user_message="Review https://example.com/source",
    )
    world.roles = ("User", "UrlAccessUser", "DeepResearchUser")
    world.identity_reads = []
    world.identity_failure = None
    world.catalog_reads = []
    world.after_preparation = None
    world.captured = []
    world.guard_returns = []
    world.attestor = new_attestor(world)

    def read_identity(*, user_id, conversation_id):
        world.identity_reads.append((user_id, conversation_id))
        if world.identity_failure is not None:
            raise world.identity_failure
        return source_module.CurrentExternalSourceIdentity(user_id, world.roles, True)

    def catalog(user_id, *, settings):
        world.catalog_reads.append(user_id)
        action = world.action_store.items["action-one"]
        agent = world.agent_store.items["agent-one"]
        return [
            {
                "id": "action-one", "name": action["name"], "type": action["type"],
                "scope_type": "personal", "scope_id": "owner",
                "action_ref": world.modules.catalog._action_ref("personal", "owner", "action-one"),
            },
            {
                "id": "agent-one", "name": agent["name"], "scope_type": "personal", "scope_id": "owner",
                "catalog_key": "personal:owner:agent-one",
            },
        ]

    def make_provider(attestor=None, **overrides):
        attestor = attestor or world.attestor
        options = {
            "user_id": "owner", "conversation_id": "conversation",
            "read_identity": read_identity, "read_settings": lambda: deepcopy(world.settings),
            "read_conversation": world.read_conversation,
            "read_run": lambda run_id: deepcopy(world.run_store.items.get(run_id)),
            "read_configuration": attestor.current, "configuration_admitter": attestor.for_admission,
            "acquisition_validator": attestor.validate_acquisition,
            "action_catalog_reader": catalog, "agent_catalog_reader": catalog,
        }
        options.update(overrides)
        return source_module.OrchestrationExternalSourceProvider(**options)

    world.make_provider = make_provider
    world.provider = make_provider()

    def configure(capability="web_search"):
        arguments = {
            "web_search": {"query": "Current source facts"},
            "url_fetch": {"urls": ["https://example.com/source"]},
            "deep_research": {"query": "Current source facts"},
            "agent_invoke": {"agent_name": "Research", "task": "Gather facts"},
            "action_invoke": {
                "action_ref": world.modules.catalog._action_ref("personal", "owner", "action-one"),
                "task": "Gather facts",
            },
        }[capability]
        world.run_store.items["run"]["plan"]["steps"] = [{
            "step_id": "gather", "capability_id": capability, "arguments": arguments, "enabled": True,
        }]
        runtime.context = runtime.modules.runtime.RunContext(
            user_id="owner", conversation_id="conversation", run_id="run", attempt_index=1,
            plan_contract_version=2, user_message="Review https://example.com/source",
            user_roles=list(world.roles), allowed_user_urls=["https://example.com/source"],
            external_source_preflight=world.provider.preflight_gather_invocation,
        )
        runtime.settings = deepcopy(world.settings)
        return producer(world, capability)

    world.configure = configure
    world.configure()

    def capture(source_type, *, producer, settings, source=None, selector=None):
        checked = world.provider.preflight_gather_acquisition(
            source_type, producer=producer, settings=settings, source=source, selector=selector,
        )
        world.guard_returns.append(checked)
        if source is None and (source_type, producer.capability_id) in (
            ("agent", "agent_invoke"), ("action", "action_invoke"),
        ):
            return
        world.attestor.capture(
            source_type, producer=producer, settings=settings, source=source, selector=selector,
        )
        world.captured.append(deepcopy(source))
        if source is None and world.after_preparation is not None:
            world.after_preparation()

    world.capture = capture
    runtime.context.capture_external_source_configuration = capture
    world.runtime = runtime
    return world


def assert_no_effects(world):
    assert world.runtime.state.web == []
    assert world.runtime.state.pages == []
    assert world.runtime.state.invocations == []
    assert all(client.closed for client in world.runtime.state.clients)
    assert all(credential.closed for credential in world.runtime.state.credentials)


def test_supported_definition_still_requires_actual_observed_run_and_restarts(pre_effect_world):
    world = pre_effect_world
    step, result = run_gather(world.runtime)
    owner = world.runtime.context.result_producer(step)
    assert result["status"] == "completed"
    assert len(world.runtime.state.web) == len(world.runtime.state.invocations) == 1
    assert [item["phase"] if item is not None else None for item in world.captured] == [None, "definition", "run"]
    assert world.guard_returns == [None, None, None]
    assert len(world.requests) == 3
    assert len(world.identity_reads) == 4
    assert all(method == "GET" and "/assistants/" in url for method, url, _ in world.requests)
    admitted = world.attestor.for_admission("web", producer=owner, settings=world.settings)
    restarted = new_attestor(world)
    restored = restarted.current("web", producer=owner, settings=world.settings)
    assert restored == admitted
    assert restarted._captures == {}


def test_support_and_definition_checks_create_no_completion_proof(pre_effect_world):
    world = pre_effect_world
    evidence = foundry_capture(world)
    evidence.pop("run")
    evidence["phase"] = "definition"
    checked = world.provider.preflight_gather_acquisition(
        "web", producer=producer(world), settings=world.settings, source=evidence,
    )
    assert checked is None
    assert world.attestor._captures == {}
    world.attestor.capture("web", producer=producer(world), settings=world.settings, source=evidence)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.attestor.selector_for(producer(world))
    assert_no_effects(world)


@pytest.mark.parametrize("definition", [
    {"tools": [{"type": "azure_ai_search", "azure_ai_search": {"indexes": []}}]},
    {"tools": [{"type": "file_search"}]},
    {"tool_resources": {"file_search": {"vector_store_ids": ["resource"]}}},
    {"instructions": "Use {{unbound_variable}}"},
])
def test_unsupported_current_definition_refuses_before_actual_engine_work(pre_effect_world, definition):
    world = pre_effect_world
    world.definition = Agent({**world.definition.as_dict(), **definition})
    with pytest.raises(PermissionError):
        run_gather(world.runtime)
    assert world.captured == []
    assert world.attestor._captures == {}
    assert world.runtime.state.clients == world.runtime.state.credentials == []
    assert_no_effects(world)


@pytest.mark.parametrize("changes", [
    {"model": "different-model"},
    {"instructions": "Different actual instructions."},
    {"tools": [{"type": "bing_grounding", "bing_grounding": {
        "search_configurations": [{"connection_id": "different-connection"}],
    }}]},
    {"temperature": 0.8},
])
def test_supported_current_read_does_not_authorize_different_actual_definition(pre_effect_world, changes):
    world = pre_effect_world
    world.runtime.state.definition = Agent({**world.runtime.state.definition.as_dict(), **changes})
    with pytest.raises(PermissionError):
        run_gather(world.runtime)
    assert world.captured == [None]
    assert len(world.requests) == 2
    assert_no_effects(world)


@pytest.mark.parametrize("changes", [
    {"tools": [{"type": "azure_ai_search", "azure_ai_search": {"indexes": []}}]},
    {"tool_resources": {"file_search": {"vector_store_ids": ["actual-resource"]}}},
])
def test_unsupported_actual_definition_is_rejected_by_guard_and_earlier_engine_check(
    pre_effect_world, changes,
):
    world = pre_effect_world
    world.runtime.state.definition = Agent({**world.runtime.state.definition.as_dict(), **changes})
    actual = foundry_capture(world)
    actual.pop("run")
    actual.update(
        phase="definition",
        definition=world.modules.configuration.foundry_definition_snapshot(world.runtime.state.definition),
    )
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.provider.preflight_gather_acquisition(
            "web", producer=producer(world), settings=world.settings, source=actual,
        )
    assert world.attestor._captures == {}
    with pytest.raises(PermissionError) as raised:
        run_gather(world.runtime)
    assert raised.value.code == "result_unavailable"
    assert raised.value.retryable is False
    assert world.captured == [None]
    assert len(world.requests) == 2
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.attestor.selector_for(producer(world))
    assert_no_effects(world)


def test_current_definition_change_after_preparation_refuses_before_run(pre_effect_world):
    world = pre_effect_world

    def change_current():
        world.definition = Agent({**world.definition.as_dict(), "instructions": "Changed current policy."})

    world.after_preparation = change_current
    with pytest.raises(PermissionError):
        run_gather(world.runtime)
    assert world.captured == [None]
    assert_no_effects(world)


@pytest.mark.parametrize("change", ["endpoint", "api-version", "agent"])
def test_changed_actual_settings_fail_before_engine_configuration_work(pre_effect_world, change):
    world = pre_effect_world
    local = world.runtime.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]
    key, value = {
        "endpoint": ("endpoint", "https://different.services.ai.azure.com/api/projects/project"),
        "api-version": ("api_version", "different-version"),
        "agent": ("agent_id", "different-agent"),
    }[change]
    local[key] = value
    with pytest.raises(PermissionError):
        run_gather(world.runtime)
    assert world.captured == []
    assert world.runtime.state.clients == world.runtime.state.credentials == []
    assert_no_effects(world)


@pytest.mark.parametrize("failure", ["identity", "network", "throttled", "malformed", "cancelled"])
def test_pre_effect_verification_preserves_typed_failure_without_effects(pre_effect_world, failure):
    world = pre_effect_world
    identity_module = importlib.import_module("functions_orchestration_external_identity")
    error_type = world.modules.configuration.ExternalConfigurationServiceError
    code = "external_configuration_service_unavailable"
    retryable = True
    if failure == "identity":
        error_type = identity_module.ExternalIdentityServiceError
        code = "external_identity_timeout"
        world.identity_failure = error_type(code)
    elif failure == "network":
        world.failure = ServiceRequestError("PRIVATE_METADATA_OUTAGE")
    elif failure == "throttled":
        world.status = 429
        code = "external_configuration_throttled"
    elif failure == "malformed":
        world.definition = Agent({**world.definition.as_dict(), "model": ""})
        code = "external_configuration_metadata_invalid"
        retryable = False
    else:
        world.attestor.execution_check = lambda: False
        _, result = run_gather(world.runtime)
        assert result["status"] == "cancelled"
        assert world.requests == []
        assert_no_effects(world)
        return
    with pytest.raises(error_type) as raised:
        run_gather(world.runtime)
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert "PRIVATE" not in str(raised.value)
    assert world.captured == []
    assert_no_effects(world)


def test_revoked_authority_never_reaches_support_metadata(pre_effect_world):
    world = pre_effect_world
    world.roles = ()
    with pytest.raises(PermissionError):
        run_gather(world.runtime)
    assert world.requests == world.clients == []
    assert world.captured == []
    assert_no_effects(world)


def test_original_auth_only_default_does_not_read_configuration(pre_effect_world):
    world = pre_effect_world
    forbidden = Mock(side_effect=AssertionError("Auth-only preflight cannot validate metadata"))
    provider = world.make_provider(
        read_configuration=forbidden, configuration_admitter=forbidden, acquisition_validator=forbidden,
    )
    value = provider.preflight_gather_invocation(producer=producer(world))
    assert value is None
    assert forbidden.call_count == 0
    assert world.requests == []


def test_acquisition_preflight_requires_a_real_validator_and_no_success_shaped_return(pre_effect_world):
    world = pre_effect_world
    provider = world.make_provider(acquisition_validator=None)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        provider.preflight_gather_acquisition("web", producer=producer(world), settings=world.settings)
    invalid = world.make_provider(acquisition_validator=lambda *_args, **_kwargs: False)
    with pytest.raises(world.modules.contracts.ResultContractError):
        invalid.preflight_gather_acquisition("web", producer=producer(world), settings=world.settings)
    assert world.requests == []
    assert_no_effects(world)


@pytest.mark.parametrize("field,value", [
    ("user_id", "different-owner"), ("conversation_id", "different-conversation"),
    ("capability_id", "action_invoke"),
])
def test_foreign_producer_never_reaches_current_metadata(pre_effect_world, field, value):
    world = pre_effect_world
    foreign = replace(producer(world), **{field: value})
    with pytest.raises((PermissionError, world.modules.contracts.ResultContractError)):
        world.provider.preflight_gather_acquisition("web", producer=foreign, settings=world.settings)
    assert world.identity_reads == world.requests == []


@pytest.mark.parametrize("capability,source_type", [
    ("action_invoke", "action"), ("agent_invoke", "agent"),
])
def test_integration_preparation_uses_exact_fresh_origin_without_creating_capture(
    pre_effect_world, capability, source_type,
):
    world = pre_effect_world
    owner = world.configure(capability)
    source, selector = action_source(world) if source_type == "action" else agent_source(world)
    checked = world.provider.preflight_gather_acquisition(
        source_type, producer=owner, settings=world.settings, source=None, selector=selector,
    )
    assert checked is None
    assert world.identity_reads == [("owner", "conversation")]
    assert world.catalog_reads == ["owner"]
    assert world.attestor._captures == {}
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.attestor.selector_for(owner)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.provider.preflight_gather_acquisition(
            source_type, producer=owner, settings=world.settings, source=None, selector="wrong-selector",
        )
    assert source["id"] in ("action-one", "agent-one")
    assert_no_effects(world)


@pytest.mark.parametrize("mode", ["local", "assigned", "indirect", "mcp", "implicit-model"])
def test_unsupported_integration_modes_cannot_reach_paid_work(pre_effect_world, mode):
    world = pre_effect_world
    if mode in ("local", "assigned"):
        owner = world.configure("agent_invoke")
        source_type = "agent"
        selector = "personal:owner:agent-one"
        if mode == "local":
            world.agent_store.items["agent-one"]["agent_type"] = "local"
        else:
            world.agent_store.items["agent-one"]["actions_to_load"] = [{"id": "unattested-child"}]
    else:
        owner = world.configure("action_invoke")
        source_type = "action"
        selector = world.modules.catalog._action_ref("personal", "owner", "action-one")
        if mode == "indirect":
            world.action_store.items["action-one"]["identity_id"] = "unresolved-identity"
        elif mode == "mcp":
            world.action_store.items["action-one"]["type"] = "mcp"
        else:
            world.run_store.items["run"]["seeds"]["model"] = {}
    paid_work = Mock()
    with pytest.raises(PermissionError):
        world.provider.preflight_gather_acquisition(
            source_type, producer=owner, settings=world.settings, source=None, selector=selector,
        )
        paid_work()
    assert paid_work.call_count == 0
    assert world.attestor._captures == {}
    assert_no_effects(world)


@pytest.mark.parametrize("changed", ["model-endpoint", "prepared-manifest"])
def test_actual_action_constructor_and_preparation_drift_stop_model_and_plugin_loading(
    pre_effect_world, monkeypatch, changed,
):
    world = pre_effect_world
    owner = world.configure("action_invoke")
    manifest, selector = action_source(world)
    contexts = importlib.import_module("agent_execution_context")
    capture_module = importlib.import_module("functions_orchestration_invocation_capture")
    loader_module = importlib.import_module("semantic_kernel_plugins.logged_plugin_loader")
    actual_settings = deepcopy(world.settings)
    if changed == "model-endpoint":
        actual_settings["azure_openai_gpt_endpoint"] = "https://actual-different.openai.azure.com"
    monkeypatch.setattr(world.modules.settings, "get_settings", lambda *_args, **_kwargs: deepcopy(actual_settings))
    context = SimpleNamespace(
        user_id="owner", conversation_id="conversation", action_catalog=[manifest], active_group_ids=[],
        model_context={"provider": "aoai", "model_deployment": "gpt-4o"}, gpt_model="gpt-4o",
        token_usage={}, notes=[],
        agent_execution_identity=contexts.ExecutionIdentity("owner", "conversation", bridge=lambda _ref: nullcontext()),
        delegation_budget=contexts.DelegationBudget(),
    )
    prepared = []
    real_prepare = world.modules.loader.prepare_action_plugin_manifest

    def prepare(*args, **kwargs):
        value = real_prepare(*args, **kwargs)
        prepared.append(value)
        if changed == "prepared-manifest" and len(prepared) == 2:
            value["endpoint"] = "https://actual-different-action.invalid"
        return value

    monkeypatch.setattr(world.modules.loader, "prepare_action_plugin_manifest", prepare)
    services = []
    real_model = world.modules.actions._build_action_model

    def build_model(*args, **kwargs):
        value = real_model(*args, **kwargs)
        services.append(value[0])
        return value

    monkeypatch.setattr(world.modules.actions, "_build_action_model", build_model)
    loaders = []
    real_loader = loader_module.create_logged_plugin_loader

    def create_loader(kernel):
        value = real_loader(kernel)
        value.load_plugin_from_manifest = Mock(wraps=value.load_plugin_from_manifest)
        loaders.append(value)
        return value

    monkeypatch.setattr(loader_module, "create_logged_plugin_loader", create_loader)
    model_calls = []

    async def model_io(*_args, **_kwargs):
        model_calls.append(True)
        raise AssertionError("Unsupported actual configuration reached a model request")

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", model_io)

    def bound_capture(source_type, **kwargs):
        world.capture(source_type, producer=owner, **kwargs)

    capture = capture_module.OrchestrationInvocationCapture(bound_capture)
    with pytest.raises(PermissionError):
        asyncio.run(world.modules.actions.invoke_action(
            selector, "Gather facts", context, settings=actual_settings, user_id="owner",
            cancel_requested=lambda: False, invocation_capture=capture,
        ))
    assert model_calls == []
    assert len(services) == len(loaders) == 1
    assert all(loader.load_plugin_from_manifest.call_count == 0 for loader in loaders)
    closed = [service.client.is_closed() for service in services]
    assert closed == [True]
    assert world.attestor._captures == {}
    assert len(prepared) == 3


def test_prior_actual_agent_component_cannot_be_replaced_by_new_current_configuration(pre_effect_world):
    world = pre_effect_world
    owner = world.configure("agent_invoke")
    source, selector = agent_source(world)
    config = world.modules.loader.resolve_agent_config(source, world.settings, execution_user_id="owner")
    reference = world.modules.agents.agent_reference(source, "owner")
    event = {
        "version": world.modules.configuration.EXTERNAL_ACQUISITION_VERSION,
        "kind": "agent", "phase": "resolved", "reference": reference, "resolved_config": config,
    }
    world.capture("agent", producer=owner, settings=world.settings, source=event, selector=selector)
    world.agent_store.items["agent-one"]["description"] = "A changed configuration for this remote agent."
    definition = foundry_capture(world, max_completion_tokens=3072)
    definition.pop("run")
    definition["phase"] = "definition"
    paid_work = Mock()
    with pytest.raises(PermissionError):
        world.capture("agent", producer=owner, settings=world.settings, source=definition, selector=selector)
        paid_work()
    assert paid_work.call_count == 0
    assert owner in world.attestor._conflicts
    assert_no_effects(world)


def test_forged_acquisition_envelope_cannot_replace_current_source_authorization(pre_effect_world):
    world = pre_effect_world
    owner = world.configure("action_invoke")
    manifest, selector = action_source(world)
    plausible_model = world.modules.metadata._current_model(
        world.modules.metadata._MetadataRead("owner", "conversation", world.read_conversation, None),
        owner, world.settings, planner=False,
    )
    event = {
        "version": world.modules.configuration.EXTERNAL_ACQUISITION_VERSION,
        "kind": "action", "phase": "resolved",
        "reference": {"id": "action-one", "scope_type": "personal", "scope_id": "owner"},
        "manifest": manifest, "prepared_manifest": deepcopy(manifest), "model": plausible_model,
    }
    world.action_store.items["action-one"]["is_enabled"] = False
    validator = Mock(wraps=world.attestor.validate_acquisition)
    provider = world.make_provider(acquisition_validator=validator)
    with pytest.raises(PermissionError):
        provider.preflight_gather_acquisition(
            "action", producer=owner, settings=world.settings, source=event, selector=selector,
        )
    assert validator.call_count == 0
    assert world.attestor._captures == {}


@pytest.mark.parametrize("change", [None, "endpoint", "deployment", "response-budget"])
def test_actual_planner_construction_is_checked_before_a_request(pre_effect_world, change):
    world = pre_effect_world
    owner = world.configure("deep_research")
    actual_settings = deepcopy(world.settings)
    if change == "endpoint":
        actual_settings["azure_openai_gpt_endpoint"] = "https://actual-planner.openai.azure.com"
    elif change == "deployment":
        actual_settings["chat_orchestration_planner_deployment"] = "gpt-4o-mini"
    elif change == "response-budget":
        actual_settings["gpt_model"]["selected"][0]["responseLength"] = 4096
    binding = world.modules.models.resolve_orchestration_model(
        actual_settings, user_id="owner", seeds=deepcopy(world.run_store.items["run"]["seeds"]), planner=True,
    )
    try:
        client = binding.as_planner_client()
        actual = world.modules.models.planner_client_construction_source(client, binding.deployment)
        request = Mock()
        if change is not None:
            with pytest.raises(PermissionError):
                world.capture("deep_research", producer=owner, settings=actual_settings, source=actual)
                request()
        else:
            world.capture("deep_research", producer=owner, settings=actual_settings, source=actual)
            with pytest.raises(world.modules.configuration.ResultUnavailableError):
                world.attestor.selector_for(owner)
        assert request.call_count == 0
        assert_no_effects(world)
    finally:
        binding.close()


def test_acquisition_check_rejects_current_metadata_as_execution_proof(pre_effect_world):
    world = pre_effect_world
    current = world.reader(
        "web", producer=producer(world), settings=world.settings, source=None, selector=None,
    )
    with pytest.raises(PermissionError):
        world.provider.preflight_gather_acquisition(
            "web", producer=producer(world), settings=world.settings, source=current,
        )
    assert world.attestor._captures == {}
    assert_no_effects(world)


def test_current_lookup_does_not_depend_on_or_get_replaced_by_existing_capture(pre_effect_world):
    world = pre_effect_world
    evidence = foundry_capture(world)
    evidence.pop("run")
    evidence["phase"] = "definition"
    world.capture("web", producer=producer(world), settings=world.settings, source=evidence)
    world.definition = Agent({**world.definition.as_dict(), "model": "changed-current-model"})
    with pytest.raises(PermissionError):
        world.provider.preflight_gather_acquisition(
            "web", producer=producer(world), settings=world.settings, source=evidence,
        )
    assert len(world.requests) == 2
    assert_no_effects(world)
