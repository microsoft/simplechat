# test_orchestration_external_preflight_adapter.py
"""Strict invocation authorization and acquisition support for all five v2 adapters.

Version: 0.261.129
Implemented in: 0.261.127
Early acquisition-support regressions implemented in: 0.261.129

The auth-only runtime hook invokes the real provider before capture or engine
setup. Capture separately invokes the real combined acquisition guard. The
current-resource cases use the real metadata reader and attestor with only
external/storage I/O doubled; neither authorization nor preparation is proof.
"""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import builtins
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_orchestration_external_configuration_capture import capture_runtime, gather_modules, run_gather
from test_orchestration_external_metadata import metadata_world
from test_orchestration_external_pre_effect import pre_effect_world
from test_orchestration_external_sources import ExternalSourceWorld


CAPABILITIES = ("web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke")
SOURCE_TYPES = {
    "web_search": "web", "url_fetch": "url", "deep_research": "deep_research",
    "agent_invoke": "agent", "action_invoke": "action",
}


@pytest.fixture(params=CAPABILITIES)
def authorized_runtime(request, capture_runtime):
    runtime = capture_runtime
    capability = request.param
    contexts = importlib.import_module("agent_execution_context")
    with ExternalSourceWorld(capability) as world:
        world.settings.update(deepcopy(runtime.settings))
        runtime.settings = deepcopy(world.settings)
        arguments = {
            "web_search": {"query": "Current source facts"},
            "url_fetch": {"urls": ["https://example.com/source"]},
            "deep_research": {"query": "Current source facts"},
            "agent_invoke": {"agent_name": "Lookup", "task": "Gather current facts"},
            "action_invoke": {"action_ref": world.action_selector, "task": "Gather current facts"},
        }[capability]
        step = {"step_id": "gather", "capability_id": capability, "arguments": arguments, "enabled": True}
        catalog = world.catalog("owner", settings=world.settings) if capability in (
            "agent_invoke", "action_invoke",
        ) else []
        runtime.context = runtime.modules.runtime.RunContext(
            user_id="owner", conversation_id="conversation-1", run_id=world.fixture.producer.run_id,
            attempt_index=1, plan_contract_version=2, user_roles=list(world.roles),
            user_message="Review https://example.com/source", allowed_user_urls=["https://example.com/source"],
            planner_client=object(), planner_deployment="not-executed",
            agent_catalog=catalog if capability == "agent_invoke" else [],
            action_catalog=catalog if capability == "action_invoke" else [],
            agent_execution_identity=contexts.ExecutionIdentity(
                "owner", "conversation-1", bridge=lambda _reference: nullcontext(),
            ),
        )
        world.fixture.producer = runtime.context.result_producer(step)
        world.run["plan"]["steps"] = [deepcopy(step)]
        world.run["user_message"] = runtime.context.user_message
        world.run["memory_audience"] = {
            "kind": "personal", "owner_id": "owner", "collaboration_id": "",
        }
        validator = Mock(side_effect=runtime.modules.configuration.ExternalConfigurationServiceError(
            "external_configuration_metadata_invalid",
        ))
        provider = world.provider(acquisition_validator=validator)
        preflight = Mock(wraps=provider.preflight_gather_invocation)
        acquisition = Mock(wraps=provider.preflight_gather_acquisition)
        capture = Mock()

        def root_capture(source_type, *, producer, settings, source=None, selector=None):
            acquisition(source_type, producer=producer, settings=settings, source=source, selector=selector)
            if source is None and source_type in ("agent", "action"):
                return
            capture(source_type, producer=producer, settings=settings, source=source, selector=selector)

        runtime.context.external_source_preflight = preflight
        runtime.context.capture_external_source_configuration = root_capture
        yield SimpleNamespace(
            runtime=runtime, world=world, provider=provider, preflight=preflight, capture=capture,
            acquisition=acquisition, validator=validator, step=step, capability=capability,
            selector=world.selected_integration(),
        )


@pytest.fixture(params=CAPABILITIES)
def current_acquisition_runtime(request, pre_effect_world):
    world = pre_effect_world
    capability = request.param
    world.configure(capability)
    runtime = world.runtime
    context = runtime.context
    step = world.run_store.items["run"]["plan"]["steps"][0]
    selector = None
    if capability == "agent_invoke":
        context.agent_catalog = world.provider.agent_catalog_reader("owner", settings=runtime.settings)
        selector = "personal:owner:agent-one"
    elif capability == "action_invoke":
        context.action_catalog = world.provider.action_catalog_reader("owner", settings=runtime.settings)
        selector = step["arguments"]["action_ref"]
    contexts = importlib.import_module("agent_execution_context")
    context.agent_execution_identity = contexts.ExecutionIdentity(
        "owner", "conversation", bridge=lambda _reference: nullcontext(),
    )
    binding = None
    if capability == "deep_research":
        binding = world.modules.models.resolve_orchestration_model(
            runtime.settings, user_id="owner",
            seeds=deepcopy(world.run_store.items["run"]["seeds"]), planner=True,
        )
        context.planner_client = binding.as_planner_client()
        context.planner_deployment = binding.deployment
    state = SimpleNamespace(
        runtime=runtime, world=world, step=step, capability=capability, selector=selector,
        prepared=[], stop_after_preparation=True,
    )

    def root_capture(source_type, *, producer, settings, source=None, selector=None):
        world.capture(source_type, producer=producer, settings=settings, source=source, selector=selector)
        state.prepared.append((source_type, producer, source, selector))
        if state.stop_after_preparation:
            raise world.modules.configuration.ExternalConfigurationServiceError(
                "external_configuration_metadata_invalid",
            )

    context.external_source_preflight = world.provider.preflight_gather_invocation
    context.capture_external_source_configuration = root_capture
    try:
        yield state
    finally:
        if binding is not None:
            binding.close()


def execute(state):
    return run_gather(state.runtime, state.capability, arguments=state.step["arguments"])[1]


def assert_no_effects(state):
    assert state.runtime.state.web == state.runtime.state.pages == state.runtime.state.invocations == []
    assert state.runtime.state.clients == state.runtime.state.credentials == []
    assert state.world.configuration_reads == []
    assert state.provider.access.external_source_catalog == {}
    assert state.runtime.state.private == {}
    assert state.runtime.context.task_results == {}
    assert state.runtime.context.result_aliases == {}


def test_combined_guard_authorizes_before_configuration_verification(authorized_runtime):
    state = authorized_runtime
    expected = state.runtime.context.result_producer(state.step)
    with pytest.raises(state.runtime.modules.configuration.ExternalConfigurationServiceError) as caught:
        execute(state)
    assert caught.value.code == "external_configuration_metadata_invalid"
    state.preflight.assert_called_once_with(producer=expected, selector=state.selector)
    state.acquisition.assert_called_once_with(
        SOURCE_TYPES[state.capability], producer=expected, settings=state.runtime.settings,
        source=None, selector=state.selector,
    )
    state.validator.assert_called_once()
    state.capture.assert_not_called()
    assert state.world.identity_reads == 2
    assert_no_effects(state)


def test_preflight_authorization_does_not_create_acquisition_proof(authorized_runtime):
    state = authorized_runtime
    capture = state.runtime.modules.adapters._external_invocation_capture(
        state.step, state.runtime.context, state.runtime.settings, user_id="owner",
        capability_id=state.capability, selector=state.selector,
    )
    errors = importlib.import_module("functions_orchestration_invocation_capture")
    with pytest.raises(errors.OrchestrationInvocationCaptureError):
        capture.require_valid(captured=True)
    assert state.world.identity_reads == 1
    producer = state.runtime.context.result_producer(state.step)
    state.preflight.assert_called_once_with(producer=producer, selector=state.selector)
    state.acquisition.assert_not_called()
    state.validator.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("fault", [
    "missing", "noncallable", "true", "false", "payload", "zero",
    "async_function", "async_callable", "awaitable",
])
def test_preflight_requires_a_synchronous_none_before_capture(authorized_runtime, fault):
    state = authorized_runtime

    async def asynchronous(*_args, **_kwargs):
        pytest.fail("An asynchronous authorization callback must not execute")

    class AsynchronousGuard:
        async def __call__(self, **_kwargs):
            pytest.fail("An asynchronous authorization object must not execute")

    callbacks = {
        "missing": None, "noncallable": True,
        "true": lambda **_kwargs: True, "false": lambda **_kwargs: False,
        "payload": lambda **_kwargs: {"authorized": True}, "zero": lambda **_kwargs: 0,
        "async_function": asynchronous, "async_callable": AsynchronousGuard(),
        "awaitable": lambda **_kwargs: asynchronous(),
    }
    state.runtime.context.external_source_preflight = callbacks[fault]
    result = execute(state)
    assert result["status"] == "failed"
    assert result["artifacts"] == []
    assert state.world.identity_reads == 0
    state.acquisition.assert_not_called()
    state.validator.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("fault", [
    "missing", "noncallable", "refused", "async_function", "awaitable",
])
def test_absent_or_refused_capture_never_starts_an_engine(authorized_runtime, fault):
    state = authorized_runtime

    async def asynchronous(*_args, **_kwargs):
        pytest.fail("An asynchronous authorization callback must not execute")

    callbacks = {
        "missing": None, "noncallable": True,
        "refused": lambda *_args, **_kwargs: False,
        "async_function": asynchronous, "awaitable": lambda *_args, **_kwargs: asynchronous(),
    }
    state.runtime.context.capture_external_source_configuration = callbacks[fault]
    result = execute(state)
    assert result["status"] == "failed"
    assert result["artifacts"] == []
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("returned", [True, False, {"authorized": True}])
def test_combined_guard_requires_none_from_its_validator(authorized_runtime, returned):
    state = authorized_runtime
    state.provider.acquisition_validator = Mock(return_value=returned)
    result = execute(state)
    assert result["status"] == "failed"
    assert state.world.identity_reads == 2
    state.provider.acquisition_validator.assert_called_once()
    state.capture.assert_not_called()
    assert_no_effects(state)


def test_auth_only_preflight_does_not_replace_acquisition_validation(authorized_runtime):
    state = authorized_runtime
    with pytest.raises(state.runtime.modules.configuration.ExternalConfigurationServiceError):
        execute(state)
    assert state.world.identity_reads == 2
    state.preflight.assert_called_once()
    state.acquisition.assert_called_once()
    state.validator.assert_called_once()
    assert_no_effects(state)


@pytest.mark.parametrize("fault", ["revoked_roles", "identity_unverified", "disabled_capability", "disabled_step"])
def test_real_current_authority_overrides_stale_context_before_effects(authorized_runtime, fault):
    state = authorized_runtime
    if fault == "revoked_roles":
        state.world.roles = ()
    elif fault == "identity_unverified":
        state.provider.read_identity = Mock(return_value=None)
    elif fault == "disabled_step":
        state.world.run["plan"]["steps"][0]["enabled"] = False
    else:
        setting = {
            "web_search": "enable_web_search", "url_fetch": "enable_url_access",
            "deep_research": "enable_source_review", "agent_invoke": "enable_semantic_kernel",
            "action_invoke": "enable_chat_orchestration_actions",
        }[state.capability]
        state.world.settings[setting] = False
        assert state.runtime.settings[setting] is True
    with pytest.raises(PermissionError) as caught:
        execute(state)
    assert caught.value.code == "result_unavailable" and caught.value.retryable is False
    state.preflight.assert_called_once()
    state.acquisition.assert_not_called()
    state.validator.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("authorized_runtime", ["agent_invoke", "action_invoke"], indirect=True)
@pytest.mark.parametrize("fault", [
    "membership_revoked", "source_removed", "saved_selection_changed", "current_selection_changed",
])
def test_current_scoped_selection_is_authorized_before_acquisition(authorized_runtime, fault):
    state = authorized_runtime
    if fault == "membership_revoked":
        state.world.services.roles.clear()
    elif fault == "source_removed":
        kind = "agents" if state.capability == "agent_invoke" else "actions"
        state.world.services.records[(kind, "group")].clear()
    elif fault == "saved_selection_changed":
        key = "agent_name" if state.capability == "agent_invoke" else "action_ref"
        state.world.run["plan"]["steps"][0]["arguments"][key] = "other-selection"
    else:
        state.world.catalog_override = state.world.catalog("owner", settings=state.world.settings)
        key = "catalog_key" if state.capability == "agent_invoke" else "action_ref"
        state.world.catalog_override[0][key] = "other-selection"
    with pytest.raises(PermissionError) as caught:
        execute(state)
    assert caught.value.code == "result_unavailable"
    expected = state.runtime.context.result_producer(state.step)
    state.preflight.assert_called_once_with(producer=expected, selector=state.selector)
    state.acquisition.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("authorized_runtime", ["agent_invoke"], indirect=True)
@pytest.mark.parametrize("catalog_key", [None, "other-selection"])
def test_agent_requires_its_original_catalog_key_before_preflight(authorized_runtime, catalog_key):
    state = authorized_runtime
    state.runtime.context.agent_catalog[0]["catalog_key"] = catalog_key
    result = execute(state)
    assert result["status"] == "failed"
    state.preflight.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


def test_denial_precedes_engine_and_logger_setup(authorized_runtime, monkeypatch):
    state = authorized_runtime
    state.world.roles = ()
    imports = []
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        if name in (
            "functions_orchestration_actions", "agent_delegation_runtime", "route_backend_chats",
            "semantic_kernel_plugins.plugin_invocation_logger",
        ):
            imports.append(name)
            raise AssertionError("Engine setup preceded fresh authority")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    with pytest.raises(PermissionError) as caught:
        execute(state)
    assert caught.value.code == "result_unavailable"
    assert imports == []
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("owner,cancelled", [
    ("identity", False), ("configuration", False), ("identity", True), ("configuration", True),
])
def test_preflight_preserves_typed_uncertainty_and_cancellation(authorized_runtime, owner, cancelled):
    state = authorized_runtime
    errors = importlib.import_module(f"functions_orchestration_external_{owner}")
    prefix = "ExternalIdentity" if owner == "identity" else "ExternalConfiguration"
    error_type = getattr(errors, prefix + ("CancelledError" if cancelled else "ServiceError"))
    failure = error_type() if cancelled else error_type(f"external_{owner}_timeout")
    failure.private_detail = "PRIVATE_AUTHORITY_ERROR"
    state.provider.read_identity = Mock(side_effect=failure)
    if cancelled:
        result = execute(state)
        assert result["status"] == "cancelled"
        assert result["artifacts"] == []
    else:
        with pytest.raises(error_type) as caught:
            execute(state)
        assert caught.value.code == failure.code and caught.value.retryable is True
        assert caught.value is not failure and not hasattr(caught.value, "private_detail")
        assert caught.value.__context__ is None and caught.value.__cause__ is None
    state.capture.assert_not_called()
    assert_no_effects(state)


def test_preflight_preserves_owning_checkpoint_control(authorized_runtime):
    state = authorized_runtime
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    failure = checkpoints.CheckpointError("ownership_lost")
    failure.private_detail = "PRIVATE_CLAIM_DETAILS"
    state.provider.read_identity = Mock(side_effect=failure)
    with pytest.raises(checkpoints.CheckpointError) as caught:
        execute(state)
    assert caught.value.code == "ownership_lost"
    assert caught.value is not failure and not hasattr(caught.value, "private_detail")
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    state.acquisition.assert_not_called()
    state.validator.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("field,value", [
    ("user_id", "other-owner"), ("conversation_id", "other-conversation"),
    ("run_id", "other-run"), ("attempt_index", 2), ("step_id", "other-step"),
    ("capability_id", "document_search"), ("contract_version", "untrusted"),
])
def test_producer_validation_precedes_preflight(authorized_runtime, field, value):
    state = authorized_runtime
    original = state.runtime.context.result_producer
    state.runtime.context.result_producer = lambda step: replace(original(step), **{field: value})
    result = execute(state)
    assert result["status"] == "failed"
    state.preflight.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


def test_selector_validation_precedes_preflight(authorized_runtime):
    state = authorized_runtime
    selector = None if state.capability in ("agent_invoke", "action_invoke") else "unexpected-selection"
    with pytest.raises(state.runtime.modules.configuration.ResultContractError):
        state.runtime.modules.adapters._external_invocation_capture(
            state.step, state.runtime.context, state.runtime.settings, user_id="owner",
            capability_id=state.capability, selector=selector,
        )
    state.preflight.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


def test_cancellation_precedes_preflight(authorized_runtime):
    state = authorized_runtime
    _, result = run_gather(
        state.runtime, state.capability, arguments=state.step["arguments"], cancel_requested=lambda: True,
    )
    assert result["status"] == "cancelled"
    state.preflight.assert_not_called()
    state.capture.assert_not_called()
    assert_no_effects(state)


def assert_no_current_effects(state):
    runtime = state.runtime
    assert runtime.state.web == runtime.state.pages == runtime.state.invocations == []
    assert runtime.state.clients == runtime.state.credentials == []
    assert runtime.context.task_results == runtime.context.result_aliases == {}
    assert state.world.provider.access.external_source_catalog == {}


def test_real_root_authorization_and_support_precede_engine_setup(current_acquisition_runtime):
    state = current_acquisition_runtime
    owner = state.runtime.context.result_producer(state.step)
    with pytest.raises(state.world.modules.configuration.ExternalConfigurationServiceError) as caught:
        execute(state)
    assert caught.value.code == "external_configuration_metadata_invalid"
    assert state.prepared == [(SOURCE_TYPES[state.capability], owner, None, state.selector)]
    assert state.world.identity_reads == [("owner", "conversation")] * 2
    assert state.world.guard_returns == [None]
    assert_no_current_effects(state)


def test_real_preparation_keeps_model_and_run_proof_incomplete(current_acquisition_runtime):
    state = current_acquisition_runtime
    state.stop_after_preparation = False
    capture = state.runtime.modules.adapters._external_invocation_capture(
        state.step, state.runtime.context, state.runtime.settings, user_id="owner",
        capability_id=state.capability, selector=state.selector,
    )
    capture(SOURCE_TYPES[state.capability], settings=state.runtime.settings, selector=state.selector)
    errors = importlib.import_module("functions_orchestration_invocation_capture")
    if state.capability == "url_fetch":
        capture.require_valid(captured=True)
    else:
        with pytest.raises(errors.OrchestrationInvocationCaptureError):
            capture.require_valid(captured=True)
        owner = state.runtime.context.result_producer(state.step)
        with pytest.raises(state.world.modules.configuration.ResultUnavailableError):
            state.world.attestor.selector_for(owner)
    if state.capability in ("agent_invoke", "action_invoke"):
        assert state.world.attestor._captures == {}
    assert_no_current_effects(state)


def test_real_current_or_actual_unsupported_configuration_stops_before_effects(current_acquisition_runtime):
    state = current_acquisition_runtime
    world = state.world
    if state.capability == "web_search":
        world.definition = type(world.definition)({
            **world.definition.as_dict(), "tools": [{"type": "file_search"}],
        })
    elif state.capability == "url_fetch":
        state.runtime.settings["source_review_timeout_seconds"] = 3
    elif state.capability == "deep_research":
        world.settings.update(deep_research_enable_query_planning=True,
                              deep_research_max_search_queries_per_turn=2)
    elif state.capability == "agent_invoke":
        world.agent_store.items["agent-one"]["agent_type"] = "local"
    else:
        world.action_store.items["action-one"]["type"] = "mcp"
    with pytest.raises(PermissionError) as caught:
        execute(state)
    assert caught.value.code == "result_unavailable"
    assert state.prepared == []
    assert world.attestor._captures == {}
    assert_no_current_effects(state)


@pytest.mark.parametrize("current_acquisition_runtime", ["agent_invoke", "action_invoke"], indirect=True)
def test_preparation_only_engine_result_cannot_be_accepted(current_acquisition_runtime, monkeypatch):
    state = current_acquisition_runtime
    state.stop_after_preparation = False
    engine_name = (
        "agent_delegation_runtime" if state.capability == "agent_invoke" else "functions_orchestration_actions"
    )
    engine = importlib.import_module(engine_name)

    async def unobserved_engine(*_args, **_kwargs):
        return {"findings": "Unattested content", "calls": 0, "invocations": [], "artifacts": []}

    invocation = Mock(side_effect=unobserved_engine)
    monkeypatch.setattr(
        engine, "invoke_scoped_agent" if state.capability == "agent_invoke" else "invoke_action", invocation,
    )
    result = execute(state)
    invocation.assert_called_once()
    assert result["status"] == "failed"
    assert result["notes"] == result["artifacts"] == []
    assert len(state.prepared) == 1
    assert state.world.attestor._captures == {}
    assert_no_current_effects(state)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
