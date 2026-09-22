# test_orchestration_external_capture_integration.py
"""
Real external acquisition hooks through preflight, capture, admission and restart.
Version: 0.261.127
Implemented in: 0.261.127

Reuse the engine owner's provider/page I/O doubles, not a capture callback double.
Adapters, configuration attestation, authorization, central retention and result
readers are real. No network, credential grants or live model calls are permitted.
Refs microsoft/simplechat#1509.
"""

import asyncio
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import pytest

from test_orchestration_external_configuration_capture import (
    _current_web_configuration,
    _private_digest,
    capture_runtime,
    gather_modules,
    run_gather,
)
from test_orchestration_external_sources import ExternalSourceWorld
from test_orchestration_action_runtime import runtime, tool_message


@contextmanager
def bound_acquisition(runtime, capability):
    """Root-shaped injection over real application objects and isolated I/O."""
    configuration = runtime.modules.configuration
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    retention = importlib.import_module("functions_orchestration_result_runtime")
    with ExternalSourceWorld(capability) as world:
        world.settings.update(deepcopy(runtime.settings))
        runtime.settings = world.settings
        arguments = {
            "url_fetch": {"urls": ["https://example.com/source"]},
            "web_search": {"query": "Current source facts"},
        }[capability]
        step = {"step_id": "gather", "capability_id": capability, "arguments": arguments, "enabled": True}
        fingerprint = contracts.canonical_digest({"step": step, "inputs": []})
        context = runtime.modules.runtime.RunContext(
            user_id="owner", conversation_id="conversation-1", run_id=world.fixture.producer.run_id,
            attempt_index=1, plan_contract_version=2,
            user_message="Review https://example.com/source", user_roles=list(world.roles),
            allowed_user_urls=["https://example.com/source"],
            result_guard_token_for_step=lambda _step_id: "server-attempt-token",
            result_input_fingerprint_for_step=lambda _step_id: fingerprint,
        )
        runtime.context = context
        world.fixture.producer = context.result_producer(step)
        world.run["plan"]["steps"] = [deepcopy(step)]
        world.run["user_message"] = context.user_message
        world.run["memory_audience"] = {"kind": "personal", "owner_id": "owner", "collaboration_id": ""}
        metadata_reads = []

        def current_metadata(source_type, *, producer, settings, source, selector):
            if source_type != "web" or source is not None or selector is not None:
                raise AssertionError("Only current web metadata belongs at this boundary")
            metadata_reads.append(producer)
            return _current_web_configuration(runtime)

        def make_attestor():
            return configuration.OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1", private_digest=_private_digest,
                read_current_source=current_metadata,
            )

        attestor = make_attestor()
        provider = world.provider(
            read_configuration=attestor.current, configuration_admitter=attestor.for_admission,
            acquisition_validator=attestor.validate_acquisition,
        )
        constructor_catalog = {}
        service = world.service(provider, constructor_catalog)
        context.result_service = service
        context.external_source_preflight = provider.preflight_gather_invocation
        captured = []
        admissions = []

        def capture(source_type, *, producer, settings, source=None, selector=None):
            runtime.state.calls.append("preflight")
            provider.preflight_gather_acquisition(
                source_type, producer=producer, settings=settings, source=source, selector=selector,
            )
            if source is None and (source_type, producer.capability_id) in (
                ("agent", "agent_invoke"), ("action", "action_invoke"),
            ):
                return
            attestor.capture(source_type, producer=producer, settings=settings, source=source, selector=selector)
            captured.append(deepcopy(source))
            runtime.state.calls.append("captured")

        def admit(*, producer, prepared):
            admitted = provider.admit_gather_result(
                producer=producer, prepared=prepared, selector=attestor.selector_for(producer),
            )
            admissions.append((deepcopy(prepared), dict(admitted)))
            return admitted

        context.capture_external_source_configuration = capture
        context.external_source_admission = admit
        yield SimpleNamespace(
            world=world, context=context, step=step, provider=provider, attestor=attestor,
            make_attestor=make_attestor, service=service, retention=retention, contracts=contracts,
            captured=captured, admissions=admissions, metadata_reads=metadata_reads,
            constructor_catalog=constructor_catalog, fingerprint=fingerprint,
        )


@pytest.mark.parametrize("capability", ["url_fetch", "web_search"])
def test_actual_acquisition_preflight_capture_central_retention_and_restart(capture_runtime, capability):
    runtime = capture_runtime
    with bound_acquisition(runtime, capability) as bound:
        request_context = runtime.modules.runtime._dependency_request_context(bound.context)
        bindings = {
            name for name in request_context
            if name.startswith("external_source_") or name == "capture_external_source_configuration"
        }
        assert bindings == {
            "external_source_admission", "capture_external_source_configuration", "external_source_authorizer",
            "external_source_preflight",
        }
        registry = importlib.import_module("functions_orchestration_registry")
        available = registry.resolve_available_capability_ids(
            bound.world.settings, request_context=request_context, candidate_ids=(capability,), contract_version=2,
        )
        assert available == [capability]
        _, result = run_gather(runtime, capability)
        assert result["status"] == "completed", result
        assert runtime.state.calls[0] == "preflight"
        effect = "page" if capability == "url_fetch" else "web"
        assert runtime.state.calls.index("captured") < runtime.state.calls.index(effect)
        phases = [source["phase"] if source is not None else None for source in bound.captured]
        assert phases == ([None] if capability == "url_fetch" else [None, "definition", "run"])
        for source in bound.captured:
            if source is not None:
                assert source["version"] == "orchestration-external-acquisition-v1"
                assert source["kind"] == "foundry"
                assert source["binding"] == "observed-run-v1"

        task = bound.retention.retain_gather_result(
            bound.step, bound.context, result, source_manifest=[],
        )
        assert len(bound.admissions) == 1
        prepared, admitted = bound.admissions[0]
        expected_digest = bound.contracts.canonical_digest(prepared)
        assert len(admitted) == 1
        assert all(reference.content_sha256 == expected_digest for reference in admitted.values())
        assert bound.constructor_catalog == {}
        assert bound.service.access.external_source_catalog == admitted
        assert [reference.kind for reference in task.outputs] == ["structured-v1"]
        assert prepared["notes"] == result["notes"]
        assert prepared["citations"] == result["citations"]
        assert prepared["evidence"] == result["evidence"]

        effects_before_read = (len(runtime.state.web), len(runtime.state.pages))
        restarted = bound.make_attestor()
        provider = bound.world.provider(read_configuration=restarted.current, configuration_admitter=None)
        service = bound.world.service(provider)
        recovered = service.recover_task_result(
            producer=bound.world.fixture.producer, input_fingerprint=bound.fingerprint,
        )
        assert recovered == task
        reader = service.open_result(recovered.output("prepared"), require_current_sources=True)
        restored = reader.read_value()
        metadata = reader.metadata()
        assert restored == prepared
        assert restarted._captures == {}
        assert service.access.external_source_catalog == {}
        assert metadata["origin"] == "grounded"
        assert metadata["external_source_count"] == 1
        assert (len(runtime.state.web), len(runtime.state.pages)) == effects_before_read
        wire = json.dumps(task.to_dict())
        assert "PRIVATE_CONFIGURATION_KEY" not in wire
        assert "private-provider.invalid" not in wire
        assert "original-agent" not in wire
        assert bool(bound.metadata_reads) is (capability == "web_search")

        bound.world.roles = ()
        with pytest.raises(runtime.modules.configuration.ResultUnavailableError):
            reader.read_value()
        assert (len(runtime.state.web), len(runtime.state.pages)) == effects_before_read


@pytest.mark.parametrize("capability", ["url_fetch", "web_search"])
def test_actual_preflight_revocation_blocks_effects_despite_stale_context_roles(capture_runtime, capability):
    runtime = capture_runtime
    with bound_acquisition(runtime, capability) as bound:
        bound.world.roles = ()
        with pytest.raises(PermissionError) as raised:
            run_gather(runtime, capability)
        assert raised.value.code == "result_unavailable"
        assert raised.value.retryable is False
        assert bound.context.user_roles
        assert bound.world.identity_reads == 1
        assert runtime.state.calls == []
        assert bound.captured == []
        assert bound.admissions == []
        assert runtime.state.web == runtime.state.pages == []
        assert runtime.state.clients == runtime.state.credentials == []
        assert bound.service.access.external_source_catalog == {}


@pytest.mark.parametrize("capability", ["url_fetch", "web_search"])
def test_actual_saved_reads_reconstruct_current_policy_without_capture_or_refetch(capture_runtime, capability):
    runtime = capture_runtime
    with bound_acquisition(runtime, capability) as bound:
        _, result = run_gather(runtime, capability)
        assert result["status"] == "completed", result
        task = bound.retention.retain_gather_result(bound.step, bound.context, result, source_manifest=[])
        restarted = bound.make_attestor()
        provider = bound.world.provider(read_configuration=restarted.current, configuration_admitter=None)
        service = bound.world.service(provider)
        bound.world.settings["app_title"] = "Unrelated administrative save"
        reader = service.open_result(task.output("prepared"))
        original = reader.read_value()
        assert original == bound.admissions[0][0]
        effects = (len(runtime.state.web), len(runtime.state.pages))
        if capability == "web_search":
            runtime.state.definition["instructions"] = "Current policy changed."
        else:
            bound.world.settings["source_review_max_redirects"] = 0
        with pytest.raises(runtime.modules.configuration.ResultUnavailableError):
            service.open_result(task.output("prepared"))
        assert restarted._captures == {}
        assert (len(runtime.state.web), len(runtime.state.pages)) == effects


@pytest.mark.parametrize("missing", ["tool_resources", "model", "assistant_id"])
def test_actual_missing_sdk_run_evidence_never_admits_a_result(capture_runtime, missing):
    runtime = capture_runtime
    runtime.state.run_mutation = lambda run: run.pop(missing, None)
    with bound_acquisition(runtime, "web_search") as bound:
        with pytest.raises(PermissionError) as raised:
            run_gather(runtime)
        assert raised.value.code == "result_unavailable"
        assert raised.value.retryable is False
        with pytest.raises(runtime.modules.configuration.ResultUnavailableError):
            bound.attestor.for_admission(
                "web", producer=bound.world.fixture.producer, settings=bound.world.settings,
            )
        assert bound.admissions == []
        assert bound.service.access.external_source_catalog == {}
        assert len(runtime.state.web) == 1
        assert all(client.closed for client in runtime.state.clients)
        assert all(credential.closed for credential in runtime.state.credentials)


def test_earlier_private_envelope_is_rejected_before_a_provider_run(capture_runtime):
    runtime = capture_runtime
    with bound_acquisition(runtime, "web_search") as bound:
        current_capture = bound.context.capture_external_source_configuration

        def incompatible(source_type, *, producer, settings, source=None, selector=None):
            if source is not None:
                source = {**source, "kind": "foundry-definition-v1"}
            current_capture(source_type, producer=producer, settings=settings, source=source, selector=selector)

        bound.context.capture_external_source_configuration = incompatible
        with pytest.raises(runtime.modules.configuration.ExternalConfigurationServiceError) as raised:
            run_gather(runtime)
        assert raised.value.code == "external_configuration_metadata_invalid"
        assert raised.value.retryable is False
        assert runtime.state.web == []
        assert bound.admissions == []
        assert bound.service.access.external_source_catalog == {}
        assert all(client.closed for client in runtime.state.clients)
        assert all(credential.closed for credential in runtime.state.credentials)


def test_actual_action_reauthorization_capture_and_restart_use_one_envelope(runtime, gather_modules):
    state = runtime
    configuration = gather_modules.configuration
    capture_module = importlib.import_module("functions_orchestration_invocation_capture")
    with ExternalSourceWorld("action_invoke") as world:
        world.settings.update(max_auto_invoke_attempts=5)
        state.settings = world.settings
        selected = world.catalog("owner", settings=world.settings)[0]
        state.action = selected
        state.context.action_catalog = [selected]
        state.context.user_id = "owner"
        state.context.conversation_id = "conversation-1"
        state.context.agent_execution_identity = state.contexts.ExecutionIdentity(
            "owner", "conversation-1", bridge=lambda _reference: nullcontext(),
        )
        resolver = world.provider().action_resolver
        state.manifest = resolver("owner", world.action_selector, settings=world.settings)
        observed = []

        def current_source(source_type, *, producer, settings, source, selector):
            if source_type != "action" or selector != world.action_selector:
                raise AssertionError("Current metadata must use the exact scoped action")
            return {
                "version": configuration.EXTERNAL_ACQUISITION_VERSION,
                "kind": "action", "phase": "current",
                "reference": {"id": source["id"], "scope_type": source["scope_type"], "scope_id": source["scope_id"]},
                "manifest": source, "prepared_manifest": deepcopy(source),
                "model": {
                    **state.model_configuration, "parameters": {"parallel_tool_calls": False, "tool_choice": "auto"},
                },
            }

        def make_attestor():
            return configuration.OrchestrationExternalConfigurationAttestor(
                user_id="owner", conversation_id="conversation-1",
                read_current_source=current_source, private_digest=_private_digest,
            )

        attestor = make_attestor()
        provider = world.provider(
            read_configuration=attestor.current, configuration_admitter=attestor.for_admission,
            acquisition_validator=attestor.validate_acquisition,
        )

        def capture(source_type, *, settings, source, selector):
            provider.preflight_gather_acquisition(
                source_type, producer=world.fixture.producer, settings=settings, source=source, selector=selector,
            )
            if source_type == "action" and source is None:
                return
            attestor.capture(
                source_type, producer=world.fixture.producer, settings=settings, source=source, selector=selector,
            )
            observed.append(deepcopy(source))
            if len(observed) == 1:
                assert state.loads == state.calls == state.requests == []

        capture("action", settings=world.settings, source=None, selector=world.action_selector)
        assert observed == []
        assert attestor._captures == {}
        with pytest.raises(configuration.ResultUnavailableError):
            world.admit(provider)

        state.replies = [tool_message("42", "43")]
        result = asyncio.run(state.runtime.invoke_action(
            world.action_selector, "Look up the tickets.", state.context,
            settings=world.settings, user_id="owner", cancel_requested=lambda: False,
            invocation_capture=capture_module.OrchestrationInvocationCapture(capture),
        ))
        assert result["calls"] == 2
        assert state.calls == [("42", "owner"), ("43", "owner")]
        assert len(observed) == 3
        assert all(value["version"] == "orchestration-external-acquisition-v1" for value in observed)
        assert all(value["kind"] == "action" and value["phase"] == "resolved" for value in observed)
        assert all(value["prepared_manifest"] == state.manifest for value in observed)
        assert all(
            value["model"]["parameters"] == {"parallel_tool_calls": False, "tool_choice": "auto"}
            for value in observed
        )

        world.prepared["notes"] = [result["findings"]]
        admitted = world.admit(provider)
        task = world.persist(world.service(provider, admitted), admitted)
        restarted = make_attestor()
        reader = world.provider(read_configuration=restarted.current, configuration_admitter=None)
        restored = world.service(reader).open_result(task.output("prepared")).read_value()
        assert restored == world.prepared
        assert restarted._captures == {}
        assert result["findings"] in restored["notes"]
        world.services.roles.clear()
        with pytest.raises(configuration.ResultUnavailableError):
            world.service(reader).open_result(task.output("prepared"))
