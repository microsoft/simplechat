# test_orchestration_external_preflight_adapter.py
"""Fresh authorization before all five v2 acquisition adapter boundaries.

Version: 0.261.127
Implemented in: 0.261.127

Real adapters, producer validation, current source authorization and scoped
resolvers run against isolated storage/directory I/O. Configuration capture
deliberately stops execution so authorization cannot hide later engine effects.
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
from test_orchestration_external_sources import ExternalSourceWorld


CAPABILITIES = ("web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke")


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
        provider = world.provider()
        preflight = Mock(wraps=provider.preflight_gather_invocation)
        capture = Mock(side_effect=runtime.modules.configuration.ExternalConfigurationServiceError(
            "external_configuration_metadata_invalid",
        ))
        runtime.context.external_source_preflight = preflight
        runtime.context.capture_external_source_configuration = capture
        yield SimpleNamespace(
            runtime=runtime, world=world, provider=provider, preflight=preflight, capture=capture,
            step=step, capability=capability, selector=world.selected_integration(),
        )


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


def test_real_preflight_is_required_before_the_first_capture(authorized_runtime):
    state = authorized_runtime
    expected = state.runtime.context.result_producer(state.step)
    with pytest.raises(state.runtime.modules.configuration.ExternalConfigurationServiceError) as caught:
        execute(state)
    assert caught.value.code == "external_configuration_metadata_invalid"
    state.preflight.assert_called_once_with(producer=expected, selector=state.selector)
    state.capture.assert_called_once()
    assert state.world.identity_reads == 1
    assert_no_effects(state)


def test_authorization_does_not_create_acquisition_proof(authorized_runtime):
    state = authorized_runtime
    capture = state.runtime.modules.adapters._external_invocation_capture(
        state.step, state.runtime.context, state.runtime.settings, user_id="owner",
        capability_id=state.capability, selector=state.selector,
    )
    errors = importlib.import_module("functions_orchestration_invocation_capture")
    with pytest.raises(errors.OrchestrationInvocationCaptureError):
        capture.require_valid(captured=True)
    assert state.world.identity_reads == 1
    state.capture.assert_not_called()
    assert_no_effects(state)


@pytest.mark.parametrize("fault", [
    "missing", "noncallable", "true", "false", "mapping", "async_function", "awaitable",
])
def test_absent_or_invalid_preflight_never_issues_capture_or_starts_an_engine(authorized_runtime, fault):
    state = authorized_runtime

    async def asynchronous():
        pytest.fail("An asynchronous authorization callback must not execute")

    callbacks = {
        "missing": None, "noncallable": True,
        "true": lambda **_kwargs: True, "false": lambda **_kwargs: False,
        "mapping": lambda **_kwargs: {"authorized": True},
        "async_function": asynchronous, "awaitable": lambda **_kwargs: asynchronous(),
    }
    state.runtime.context.external_source_preflight = callbacks[fault]
    result = execute(state)
    assert result["status"] == "failed"
    assert result["artifacts"] == []
    state.capture.assert_not_called()
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
