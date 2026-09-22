# test_orchestration_capture_metadata_errors.py
"""Current-metadata failures and pre-effect gates through actual acquisition.

Version: 0.261.127
Implemented in: 0.261.127

Real provider preflight, attestor current reads, adapters and owned SDK observers
run with metadata/provider transport doubled. No grants or live model calls.
"""

from copy import deepcopy
import importlib

import pytest
from azure.ai.agents.models import Agent
from requests import Response
from requests.exceptions import HTTPError

from test_orchestration_external_capture_integration import bound_acquisition
from test_orchestration_external_configuration_capture import (
    _current_web_configuration, capture_runtime, gather_modules, run_gather,
)
from test_orchestration_external_metadata import metadata_world
from test_orchestration_external_pre_effect import pre_effect_world


@pytest.fixture
def capture_states(capture_runtime, monkeypatch):
    captures = []
    adapters = capture_runtime.modules.adapters
    create_capture = adapters._external_invocation_capture

    def observe_capture(*args, **kwargs):
        value = create_capture(*args, **kwargs)
        captures.append(value)
        return value

    monkeypatch.setattr(adapters, "_external_invocation_capture", observe_capture)
    return captures


def _bing_tool():
    return {
        "type": "bing_grounding",
        "bing_grounding": {"search_configurations": [{"connection_id": "owned-bing-connection"}]},
    }


@pytest.mark.parametrize("changes", [
    {"tools": [{"type": "azure_ai_search", "azure_ai_search": {"indexes": []}}]},
    {"tool_resources": {"file_search": {"vector_store_ids": ["actual-resource"]}}},
])
def test_actual_unsupported_definition_preserves_early_policy_denial(
    pre_effect_world, capture_states, changes,
):
    world = pre_effect_world
    runtime = world.runtime
    runtime.context.external_source_preflight = world.provider.preflight_gather_invocation
    world.definition = Agent({**world.definition.as_dict(), "tools": [_bing_tool()]})
    runtime.state.definition = Agent({**world.definition.as_dict(), **changes})
    with pytest.raises(PermissionError) as refused:
        run_gather(runtime)
    assert refused.value.code == "result_unavailable" and refused.value.retryable is False
    assert refused.value.__context__ is None and refused.value.__cause__ is None
    with pytest.raises(type(refused.value)) as sticky:
        capture_states[-1].require_valid(captured=True)
    assert sticky.value.code == refused.value.code
    assert sticky.value is not refused.value
    assert world.captured == [None]
    assert len(world.requests) == 1
    assert runtime.state.calls == ["definition"]
    assert runtime.state.web == runtime.state.pages == runtime.state.invocations == []
    owner = runtime.context.result_producer(world.run_store.items["run"]["plan"]["steps"][0])
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.attestor.selector_for(owner)
    assert world.provider.access.external_source_catalog == {}
    assert runtime.context.task_results == {}
    assert all(client.closed for client in runtime.state.clients)
    assert all(credential.closed for credential in runtime.state.credentials)


@pytest.mark.parametrize("tools,expected", [
    ([{"type": "azure_ai_search", "azure_ai_search": {}}], "denied"),
    ([{"type": "file_search"}], "denied"),
    ([{"type": "function", "function": {}}], "denied"),
    ([{"type": "code_interpreter"}], "denied"),
    ([{"type": "mcp"}], "denied"),
    ([{"type": "bing_grounding"}], "denied"),
    ([{"type": "bing_grounding", "bing_grounding": {"search_configurations": []}}], "denied"),
    ([{
        "type": "bing_grounding",
        "bing_grounding": {"search_configurations": [{"connection_id": "connection", "count": True}]},
    }], "invalid"),
    ([_bing_tool() for _ in range(65)], "denied"),
])
def test_unsupported_foundry_tools_stop_before_run_and_admission(
    capture_runtime, capture_states, tools, expected,
):
    runtime = capture_runtime
    runtime.state.definition = type(runtime.state.definition)(
        {**runtime.state.definition.as_dict(), "tools": deepcopy(tools)},
    )
    with bound_acquisition(runtime, "web_search") as bound:
        bound.context.external_source_preflight = bound.provider.preflight_gather_invocation
        error_type = (
            PermissionError if expected == "denied"
            else runtime.modules.configuration.ExternalConfigurationServiceError
        )
        with pytest.raises(error_type) as refused:
            run_gather(runtime)
        expected_code = "result_unavailable" if expected == "denied" else "external_configuration_metadata_invalid"
        assert refused.value.code == expected_code
        assert refused.value.retryable is False
        with pytest.raises(error_type):
            capture_states[-1].require_valid(captured=True)
        assert runtime.state.calls.count("definition") == 1
        assert runtime.state.invocations == runtime.state.web == []
        assert bound.captured == [None]
        assert bound.admissions == []
        assert bound.service.access.external_source_catalog == {}
        assert all(client.closed for client in runtime.state.clients)
        assert all(credential.closed for credential in runtime.state.credentials)


@pytest.mark.parametrize("count", [0, 1, 64])
def test_supported_foundry_tools_keep_observed_run_binding_and_retention(capture_runtime, count):
    runtime = capture_runtime
    tools = [_bing_tool() for _ in range(count)]
    runtime.state.definition = type(runtime.state.definition)(
        {**runtime.state.definition.as_dict(), "tools": tools},
    )
    with bound_acquisition(runtime, "web_search") as bound:
        bound.context.external_source_preflight = bound.provider.preflight_gather_invocation
        _, result = run_gather(runtime)
        assert result["status"] == "completed", result
        assert len(runtime.state.web) == 1
        assert [source["phase"] for source in bound.captured if source] == ["definition", "run"]
        assert all(source["binding"] == "observed-run-v1" for source in bound.captured if source)
        assert bound.captured[-1]["run"]["tools"] == tools
        task = bound.retention.retain_gather_result(bound.step, bound.context, result, source_manifest=[])
        reader = bound.service.open_result(task.output("prepared"), require_current_sources=True)
        retained = reader.read_value()
        assert retained == bound.admissions[0][0]
        assert len(runtime.state.web) == 1
        assert all(client.closed for client in runtime.state.clients)


def test_legacy_foundry_tools_are_not_restricted_by_capture_policy(capture_runtime):
    runtime = capture_runtime
    runtime.context.plan_contract_version = 1
    runtime.state.definition = type(runtime.state.definition)({
        **runtime.state.definition.as_dict(),
        "tools": [{"type": "azure_ai_search", "azure_ai_search": {}}],
    })
    _, result = run_gather(runtime)
    assert result["status"] == "completed", result
    assert len(runtime.state.web) == 1
    assert runtime.state.sources == []
    assert all(client.closed for client in runtime.state.clients)


@pytest.mark.parametrize("phase", ["preflight", "definition", "run", "poll"])
@pytest.mark.parametrize("fault,code,retryable", [
    ("unavailable", "external_configuration_service_unavailable", True),
    ("timeout", "external_configuration_timeout", True),
    ("throttled", "external_configuration_throttled", True),
    ("invalid", "external_configuration_metadata_invalid", False),
    ("limit", "external_configuration_limit_exceeded", False),
    ("cancelled", "external_configuration_cancelled", False),
    ("denied", "result_unavailable", False),
    ("held", "document_under_review", False),
])
def test_current_metadata_taxonomy_survives_initial_and_sticky_sdk_failure(
    capture_runtime, capture_states, phase, fault, code, retryable,
):
    runtime = capture_runtime
    runtime.state.poll_run = phase == "poll"
    configuration = runtime.modules.configuration
    held_error = importlib.import_module("content_screening.contracts").DocumentHeldError
    with bound_acquisition(runtime, "web_search") as bound:
        bound.context.external_source_preflight = bound.provider.preflight_gather_invocation
        fault_reads = []
        run_observations = []
        fault_enabled = phase == "preflight"

        def read_current(*args, **kwargs):
            if not fault_enabled:
                return _current_web_configuration(runtime)
            fault_reads.append(True)
            if fault == "unavailable":
                raise OSError("PRIVATE_METADATA_TRANSPORT")
            if fault == "timeout":
                raise TimeoutError("PRIVATE_METADATA_TIMEOUT")
            if fault == "throttled":
                response = Response()
                response.status_code = 429
                raise HTTPError("PRIVATE_METADATA_THROTTLE", response=response)
            if fault == "invalid":
                return None
            if fault == "cancelled":
                raise configuration.ExternalConfigurationCancelledError()
            if fault == "denied":
                raise configuration.ResultUnavailableError("external_source_revoked")
            if fault == "held":
                raise held_error("PRIVATE_HELD_DETAILS")
            source = deepcopy(_current_web_configuration(runtime))
            source["definition"]["instructions"] = "x" * (configuration.MAX_CONFIGURATION_BYTES + 64)
            source["overrides"]["instructions"] = source["definition"]["instructions"]
            return source

        bound.attestor.read_current_source = read_current
        original_capture = bound.context.capture_external_source_configuration

        def capture(source_type, **kwargs):
            nonlocal fault_enabled
            original_capture(source_type, **kwargs)
            observed_phase = (kwargs["source"] or {}).get("phase")
            if observed_phase == "run":
                run_observations.append(True)
            if observed_phase == phase or (
                phase == "poll" and observed_phase == "run" and len(run_observations) == 2
            ):
                fault_enabled = True
                bound.attestor.current(
                    source_type, producer=kwargs["producer"], settings=kwargs["settings"],
                )

        bound.context.capture_external_source_configuration = capture
        if fault == "cancelled":
            _, result = run_gather(runtime)
            assert result["status"] == "cancelled"
            expected = configuration.ExternalConfigurationCancelledError
        elif fault in ("denied", "held"):
            expected = held_error if fault == "held" else PermissionError
            with pytest.raises(expected) as caught:
                run_gather(runtime)
            assert caught.value.__context__ is None and caught.value.__cause__ is None
        else:
            expected = configuration.ExternalConfigurationServiceError
            with pytest.raises(expected) as caught:
                run_gather(runtime)
            assert caught.value.code == code and caught.value.retryable is retryable
            assert caught.value.__context__ is None and caught.value.__cause__ is None

        for operation in (capture_states[-1].require_valid, capture_states[-1].refuse):
            with pytest.raises(expected) as sticky:
                operation()
            assert "PRIVATE_" not in str(sticky.value)
            assert sticky.value.code == code
            assert sticky.value.__context__ is None and sticky.value.__cause__ is None
            if fault != "cancelled":
                assert sticky.value.retryable is retryable
        assert fault_reads == [True]
        assert runtime.state.calls.count("definition") == (0 if phase == "preflight" else 1)
        assert len(runtime.state.web) == (0 if phase in ("preflight", "definition") else 1)
        assert runtime.state.calls.count("poll") == (1 if phase == "poll" else 0)
        assert len(run_observations) == {"preflight": 0, "definition": 0, "run": 1, "poll": 2}[phase]
        assert bound.admissions == []
        assert bound.service.access.external_source_catalog == {}
        if phase == "preflight":
            assert runtime.state.clients == runtime.state.credentials == []
        assert all(client.closed for client in runtime.state.clients)
        assert all(credential.closed for credential in runtime.state.credentials)


@pytest.mark.parametrize("field,value", [("temperature", -1), ("instructions", 42)])
@pytest.mark.parametrize("phase", ["definition", "run"])
def test_sdk_snapshot_failure_before_callback_preserves_verification_error(
    capture_runtime, capture_states, phase, field, value,
):
    runtime = capture_runtime
    if phase == "definition":
        runtime.state.definition = type(runtime.state.definition)(
            {**runtime.state.definition.as_dict(), field: value},
        )
    else:
        runtime.state.run_mutation = lambda run: run.update({field: value})
    error_type = runtime.modules.configuration.ExternalConfigurationServiceError
    with bound_acquisition(runtime, "web_search") as bound:
        bound.context.external_source_preflight = bound.provider.preflight_gather_invocation
        with pytest.raises(error_type) as immediate:
            run_gather(runtime)
        assert immediate.value.code == "external_configuration_metadata_invalid"
        assert immediate.value.retryable is False
        assert immediate.value.__context__ is None and immediate.value.__cause__ is None
        with pytest.raises(error_type) as sticky:
            capture_states[-1].require_valid()
        assert sticky.value.code == immediate.value.code
        assert sticky.value.retryable is False
        assert sticky.value.__context__ is None and sticky.value.__cause__ is None
        assert bound.admissions == []
        assert not any(source and source["phase"] == "run" for source in bound.captured)
        assert len(runtime.state.web) == (1 if phase == "run" else 0)
        assert all(client.closed for client in runtime.state.clients)
        assert all(credential.closed for credential in runtime.state.credentials)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
