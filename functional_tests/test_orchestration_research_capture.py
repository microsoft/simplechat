# test_orchestration_research_capture.py
"""Bounded research acquisition through actual construction, engines and readers.

Version: 0.261.127
Implemented in: 0.261.127

Only external storage, metadata/provider transport and page I/O are doubled.
The real planner constructor, attestor, current reader and result facade run.
"""

from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_orchestration_external_configuration_capture import (
    _private_digest, capture_runtime, gather_modules, run_gather,
)
from test_orchestration_external_metadata import metadata_world
from test_orchestration_external_sources import ExternalSourceWorld


@pytest.fixture
def research(capture_runtime, metadata_world, monkeypatch):
    runtime = capture_runtime
    metadata = metadata_world
    settings = metadata.settings
    settings.update({
        key: deepcopy(value) for key, value in runtime.settings.items() if key != "web_search_agent"
    })
    settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]["agent_id"] = "original-agent"
    metadata.definition = runtime.state.definition
    seeds = deepcopy(metadata.run_store.items["run"]["seeds"])
    binding = metadata.modules.models.resolve_orchestration_model(
        settings, user_id="owner", seeds=seeds, planner=True,
    )
    planner_calls = Mock(side_effect=AssertionError("Unattested planner controls must not invoke a model."))
    monkeypatch.setattr(binding.client.chat.completions, "create", planner_calls)
    try:
        with ExternalSourceWorld("deep_research") as world:
            world.settings = settings
            runtime.settings = settings
            step = {
                "step_id": "gather", "capability_id": "deep_research", "enabled": True,
                "arguments": {"query": "Current source facts"},
            }
            fingerprint = metadata.modules.contracts.canonical_digest({"step": step, "inputs": []})
            context = runtime.modules.runtime.RunContext(
                user_id="owner", conversation_id="conversation-1", run_id=world.fixture.producer.run_id,
                attempt_index=1, plan_contract_version=2, user_roles=list(world.roles),
                user_message="Review https://example.com/source",
                allowed_user_urls=["https://example.com/source"],
                planner_client=binding.as_planner_client(), planner_deployment=binding.deployment,
                model_context={"model_deployment": "not-the-research-model"},
                result_guard_token_for_step=lambda _step_id: "server-attempt-token",
                result_input_fingerprint_for_step=lambda _step_id: fingerprint,
            )
            runtime.context = context
            world.fixture.producer = context.result_producer(step)
            world.run["plan"]["steps"] = [deepcopy(step)]
            world.run["seeds"] = seeds
            world.run["user_message"] = context.user_message
            world.run["memory_audience"] = {
                "kind": "personal", "owner_id": "owner", "collaboration_id": "",
            }
            metadata.conversation = deepcopy(world.fixture.conversation)
            metadata.run_store.items[context.run_id] = deepcopy(world.run)
            current_reader = metadata.modules.metadata.build_external_metadata_reader(
                "owner", "conversation-1", read_conversation=metadata.read_conversation,
            )

            def make_attestor():
                return metadata.modules.configuration.OrchestrationExternalConfigurationAttestor(
                    user_id="owner", conversation_id="conversation-1",
                    private_digest=_private_digest, read_current_source=current_reader,
                )

            attestor = make_attestor()
            provider = world.provider(
                read_configuration=attestor.current, configuration_admitter=attestor.for_admission,
                acquisition_validator=attestor.validate_acquisition,
            )
            service = world.service(provider)
            context.result_service = service
            context.external_source_preflight = provider.preflight_gather_invocation
            events = []
            admissions = []

            def capture(source_type, **kwargs):
                provider.preflight_gather_acquisition(source_type, **kwargs)
                attestor.capture(source_type, **kwargs)
                events.append((source_type, deepcopy(kwargs["source"])))

            def admit(*, producer, prepared):
                aliases = provider.admit_gather_result(
                    producer=producer, prepared=prepared, selector=attestor.selector_for(producer),
                )
                admissions.append((deepcopy(prepared), aliases))
                return aliases

            context.capture_external_source_configuration = capture
            context.external_source_admission = admit
            captures = []
            create_capture = runtime.modules.adapters._external_invocation_capture

            def observe_capture(*args, **kwargs):
                value = create_capture(*args, **kwargs)
                captures.append(value)
                return value

            monkeypatch.setattr(runtime.modules.adapters, "_external_invocation_capture", observe_capture)
            yield SimpleNamespace(
                runtime=runtime, metadata=metadata, world=world, binding=binding, context=context,
                step=step, fingerprint=fingerprint, planner_calls=planner_calls,
                service=service, attestor=attestor, make_attestor=make_attestor, provider=provider,
                events=events, admissions=admissions, captures=captures,
                retention=importlib.import_module("functions_orchestration_result_runtime"),
            )
    finally:
        binding.close()


def test_research_consumes_the_canonical_descriptor_without_the_old_wrapper(research, monkeypatch):
    state = research
    models = state.metadata.modules.models
    client = state.context.planner_client
    expected = models.get_planner_acquisition_configuration(client)
    descriptor = Mock(wraps=models.get_planner_acquisition_configuration)
    old_wrapper = Mock(side_effect=AssertionError("Research must use the canonical private descriptor."))
    monkeypatch.setattr(models, "get_planner_acquisition_configuration", descriptor)
    monkeypatch.setattr(models, "planner_client_construction_source", old_wrapper)
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed", result
    assert descriptor.call_count > 0
    assert all(call.args == (client,) and call.kwargs == {} for call in descriptor.call_args_list)
    old_wrapper.assert_not_called()
    sources = [source for _, source in state.events if source and source["kind"] == "planner"]
    assert sources
    assert all(source == {
        "version": "orchestration-external-acquisition-v1", "kind": "planner", "phase": "resolved",
        "model": expected,
    } for source in sources)
    assert state.context.planner_client is client
    assert state.context.planner_deployment == expected["deployment"]
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("deployment", [None, False, 123, "", "other-deployment"])
def test_descriptor_requires_the_exact_pinned_deployment_before_capture(research, deployment):
    state = research
    errors = importlib.import_module("functions_orchestration_invocation_capture")
    callback = Mock()
    capture = errors.OrchestrationInvocationCapture(callback)
    with pytest.raises(errors.OrchestrationInvocationCaptureError):
        state.runtime.modules.review.capture_research_planner_configuration(
            settings=state.runtime.settings, planner_client=state.context.planner_client,
            planner_model=deployment, invocation_capture=capture,
        )
    with pytest.raises(errors.OrchestrationInvocationCaptureError):
        capture.require_valid(captured=True)
    callback.assert_not_called()
    assert state.runtime.state.web == state.runtime.state.pages == state.runtime.state.invocations == []
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("web_enabled", [False, True])
@pytest.mark.parametrize("queries", [1, 3])
def test_real_research_constructor_and_search_events_survive_current_only_restart(research, web_enabled, queries):
    state = research
    runtime = state.runtime
    runtime.settings["enable_web_search"] = web_enabled
    runtime.settings["deep_research_max_search_queries_per_turn"] = queries
    _, result = run_gather(runtime, "deep_research")
    assert result["status"] == "completed", result
    assert state.events[0] == ("deep_research", None)
    assert all(source_type == "deep_research" for source_type, _ in state.events)
    planner_sources = [source for _, source in state.events if source and source["kind"] == "planner"]
    assert planner_sources
    assert all(source["model"]["deployment"] == state.binding.deployment for source in planner_sources)
    foundry = [source for _, source in state.events if source and source["kind"] == "foundry"]
    query_count = queries if web_enabled else 0
    assert [source["phase"] for source in foundry] == ["definition", "run"] * query_count
    assert len(runtime.state.web) == query_count
    assert runtime.state.pages
    state.planner_calls.assert_not_called()
    assert result["artifacts"] == []

    task = state.retention.retain_gather_result(
        state.step, state.context, result, source_manifest=[],
    )
    fresh = state.make_attestor()
    provider = state.world.provider(read_configuration=fresh.current, configuration_admitter=None)
    service = state.world.service(provider)
    recovered = service.recover_task_result(
        producer=state.context.result_producer(state.step), input_fingerprint=state.fingerprint,
    )
    assert recovered == task
    reader = service.open_result(recovered.output("prepared"), require_current_sources=True)
    retained = reader.read_value()
    assert retained == state.admissions[0][0]
    assert fresh._captures == {} and service.access.external_source_catalog == {}
    assert len(runtime.state.web) == query_count
    wire = json.dumps(task.to_dict())
    assert state.binding.deployment not in wire
    assert runtime.settings["azure_openai_gpt_endpoint"] not in wire
    assert runtime.settings["azure_openai_gpt_key"] not in wire
    assert all(client.closed for client in runtime.state.clients)
    assert all(credential.closed for credential in runtime.state.credentials)
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("settings", [
    {"deep_research_enable_query_planning": True, "deep_research_max_search_queries_per_turn": 2},
    {"enable_deep_source_review": True, "source_review_enable_llm_planning": True},
])
def test_unattested_research_planner_request_profiles_stop_before_effects(research, settings):
    state = research
    state.runtime.settings.update(settings)
    errors = importlib.import_module("functions_orchestration_invocation_capture")
    capture = state.runtime.modules.adapters._external_invocation_capture(
        state.step, state.context, state.runtime.settings, user_id="owner", capability_id="deep_research",
    )
    with pytest.raises(errors.OrchestrationInvocationCaptureError):
        state.runtime.modules.review.capture_research_planner_configuration(
            settings=state.runtime.settings, planner_client=state.context.planner_client,
            planner_model=state.context.planner_deployment, invocation_capture=capture,
        )
    assert state.events == []
    with pytest.raises(PermissionError) as refused:
        run_gather(state.runtime, "deep_research")
    assert refused.value.code == "result_unavailable" and refused.value.retryable is False
    assert state.runtime.state.web == state.runtime.state.pages == []
    assert state.admissions == []
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("mutation", ["foreign-client", "deployment", "closed", "completions", "model-binding"])
def test_missing_or_changed_actual_construction_cannot_use_answer_model_context(research, mutation):
    state = research
    if mutation == "foreign-client":
        state.context.planner_client = object()
    elif mutation == "deployment":
        state.context.planner_deployment = "other-model"
    elif mutation == "closed":
        state.binding.close()
    elif mutation == "completions":
        state.context.planner_client.chat.completions = SimpleNamespace(create=Mock())
    else:
        state.binding.deployment = "other-model"
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "failed"
    assert state.runtime.state.web == state.runtime.state.pages == []
    assert state.admissions == []
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("phase", ["preparation", "planner", "run", "page"])
def test_replaced_context_binding_stops_at_the_next_real_boundary(research, monkeypatch, phase):
    state = research
    state.runtime.settings["deep_research_max_search_queries_per_turn"] = 3
    capture = state.context.capture_external_source_configuration

    def replace_after_capture(source_type, **kwargs):
        capture(source_type, **kwargs)
        source = kwargs["source"]
        if (
            phase == "preparation" and source is None
            or phase == "planner" and source is not None and source["kind"] == "planner"
            or phase == "run" and source is not None and source["phase"] == "run"
        ):
            state.context.planner_client = object()

    page_io = state.runtime.modules.review._fetch_source_page

    async def replace_after_page(**kwargs):
        result = await page_io(**kwargs)
        state.context.planner_client = object()
        return result

    state.context.capture_external_source_configuration = replace_after_capture
    if phase == "page":
        monkeypatch.setattr(state.runtime.modules.review, "_fetch_source_page", replace_after_page)
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "failed"
    assert len(state.runtime.state.web) == (3 if phase == "page" else int(phase == "run"))
    assert len(state.runtime.state.pages) == int(phase == "page")
    assert state.admissions == []
    state.planner_calls.assert_not_called()


def arm_metadata_fault(state, fault):
    metadata = state.metadata
    if fault == "unavailable":
        metadata.failure = OSError("PRIVATE_RESEARCH_METADATA")
    elif fault == "timeout":
        metadata.failure = TimeoutError("PRIVATE_RESEARCH_METADATA")
    elif fault == "throttled":
        metadata.status = 429
    elif fault == "cancelled":
        metadata.failure = metadata.modules.configuration.ExternalConfigurationCancelledError()
    elif fault == "interrupted":
        metadata.failure = InterruptedError("PRIVATE_RESEARCH_METADATA")
    else:
        instructions = 17 if fault == "invalid" else "x" * (
            metadata.modules.configuration.MAX_CONFIGURATION_BYTES + 64
        )
        metadata.definition = type(metadata.definition)({
            **metadata.definition.as_dict(), "instructions": instructions,
        })


@pytest.mark.parametrize("phase", ["preflight", "planner", "definition", "run", "page"])
@pytest.mark.parametrize("fault,code,retryable", [
    ("unavailable", "external_configuration_service_unavailable", True),
    ("timeout", "external_configuration_timeout", True),
    ("throttled", "external_configuration_throttled", True),
    ("invalid", "external_configuration_metadata_invalid", False),
    ("limit", "external_configuration_limit_exceeded", False),
    ("cancelled", "external_configuration_cancelled", False),
    ("interrupted", None, False),
])
def test_real_current_metadata_errors_keep_types_through_research_and_sticky_checks(
    research, monkeypatch, phase, fault, code, retryable,
):
    state = research
    capture = state.context.capture_external_source_configuration
    fault_read_start = None

    def arm():
        nonlocal fault_read_start
        fault_read_start = len(state.metadata.requests)
        arm_metadata_fault(state, fault)

    def fail_at_capture(source_type, **kwargs):
        source = kwargs["source"]
        if (
            phase == "preflight" and source is None
            or phase == "planner" and source is not None and source["kind"] == "planner"
            or source is not None and source["phase"] == phase
        ):
            arm()
        capture(source_type, **kwargs)

    state.context.capture_external_source_configuration = fail_at_capture
    page_io = state.runtime.modules.review._fetch_source_page

    async def fail_after_page(**kwargs):
        result = await page_io(**kwargs)
        arm()
        return result

    if phase == "page":
        monkeypatch.setattr(state.runtime.modules.review, "_fetch_source_page", fail_after_page)
    configuration = state.metadata.modules.configuration
    if fault == "interrupted":
        error_type = importlib.import_module(
            "functions_orchestration_invocation_capture",
        ).OrchestrationInvocationCancelledError
    else:
        error_type = (
            configuration.ExternalConfigurationCancelledError if fault == "cancelled"
            else configuration.ExternalConfigurationServiceError
        )
    if fault in ("cancelled", "interrupted"):
        _, result = run_gather(state.runtime, "deep_research")
        assert result["status"] == "cancelled"
    else:
        with pytest.raises(error_type) as raised:
            run_gather(state.runtime, "deep_research")
        assert raised.value.code == code and raised.value.retryable is retryable
        assert raised.value.__context__ is None and raised.value.__cause__ is None
    for check in (
        lambda: state.captures[0].require_valid(captured=True),
        state.captures[0].refuse,
        lambda: state.captures[0].fail(RuntimeError("Competing failure")),
    ):
        with pytest.raises(error_type) as raised:
            check()
        assert type(raised.value) is error_type
        assert getattr(raised.value, "code", None) == code
        assert getattr(raised.value, "retryable", False) is retryable
        assert "PRIVATE_RESEARCH_METADATA" not in str(raised.value)
        assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert fault_read_start is not None and len(state.metadata.requests) == fault_read_start + 1
    assert len(state.runtime.state.web) == int(phase in ("run", "page"))
    assert len(state.runtime.state.pages) == int(phase == "page")
    assert state.admissions == []
    assert all(client.closed for client in state.runtime.state.clients)
    assert all(credential.closed for credential in state.runtime.state.credentials)
    assert all(transport.closed for transport in state.metadata.transports)
    state.planner_calls.assert_not_called()


def test_planner_proof_cannot_replace_missing_actual_search_run(research):
    state = research
    state.runtime.state.skip_run = True
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "failed"
    assert any(source and source["kind"] == "planner" for _, source in state.events)
    assert any(source and source["phase"] == "definition" for _, source in state.events)
    assert not any(source and source["phase"] == "run" for _, source in state.events)
    assert state.runtime.state.web == state.runtime.state.pages == []
    assert state.admissions == []
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("unsupported", ["apim", "resource-tool", "revoked"])
def test_current_support_and_authority_refuse_research_before_effects(research, unsupported):
    state = research
    if unsupported == "apim":
        state.runtime.settings["enable_gpt_apim"] = True
    elif unsupported == "resource-tool":
        state.metadata.definition = type(state.metadata.definition)({
            **state.metadata.definition.as_dict(), "tools": [{"type": "azure_ai_search"}],
        })
    else:
        state.world.roles = ()
    with pytest.raises(PermissionError):
        run_gather(state.runtime, "deep_research")
    assert state.runtime.state.web == state.runtime.state.pages == []
    assert state.admissions == []
    state.planner_calls.assert_not_called()


def test_single_query_profile_does_not_call_an_enabled_query_planner(research):
    state = research
    state.runtime.settings["deep_research_enable_query_planning"] = True
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed"
    assert len(state.runtime.state.web) == 1
    state.planner_calls.assert_not_called()


@pytest.mark.parametrize("phase", ["run", "page"])
def test_revocation_during_research_cannot_reach_a_later_effect_or_admission(research, monkeypatch, phase):
    state = research
    state.runtime.settings["deep_research_max_search_queries_per_turn"] = 3

    def revoke(_run):
        state.world.roles = ()

    page_io = state.runtime.modules.review._fetch_source_page

    async def revoke_after_page(**kwargs):
        result = await page_io(**kwargs)
        revoke(None)
        return result

    if phase == "run":
        state.runtime.state.run_mutation = revoke
    else:
        monkeypatch.setattr(state.runtime.modules.review, "_fetch_source_page", revoke_after_page)
    with pytest.raises(PermissionError) as refused:
        run_gather(state.runtime, "deep_research")
    assert refused.value.code == "result_unavailable"
    assert len(state.runtime.state.web) == (1 if phase == "run" else 3)
    assert len(state.runtime.state.pages) == int(phase == "page")
    assert state.admissions == []
    state.planner_calls.assert_not_called()


def test_research_retains_last_complete_engine_excerpt_beyond_a_preview(research, monkeypatch):
    state = research
    state.runtime.settings["enable_web_search"] = False
    state.context.allowed_user_urls.append("https://example.com/last")
    state.context.user_message += " and https://example.com/last"
    state.world.run["user_message"] = state.context.user_message
    page_io = state.runtime.modules.review._fetch_source_page
    excerpts = []

    async def full_excerpt(**kwargs):
        result = await page_io(**kwargs)
        excerpt = "x" * 2400 + f" LAST-RETAINED-EXCERPT-{len(excerpts)}"
        excerpts.append(excerpt)
        return {**result, "excerpts": [excerpt], "text_char_count": len(excerpt)}

    monkeypatch.setattr(state.runtime.modules.review, "_fetch_source_page", full_excerpt)
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed" and len(excerpts) == 2
    task = state.retention.retain_gather_result(state.step, state.context, result, source_manifest=[])
    current = state.make_attestor()
    service = state.world.service(state.world.provider(
        read_configuration=current.current, configuration_admitter=None,
    ))
    reader = service.open_result(task.output("prepared"), require_current_sources=True)
    retained = reader.read_value()
    notes = "\n".join(retained["notes"])
    assert len(notes) > 4096
    assert all(excerpt in notes for excerpt in excerpts)
    assert notes == "\n".join(result["notes"])
    assert current._captures == {}
    assert result["artifacts"] == []
    state.planner_calls.assert_not_called()


def test_legacy_research_does_not_require_construction_or_capture(research):
    state = research
    state.context.plan_contract_version = 1
    state.context.planner_client = object()
    state.context.capture_external_source_configuration = Mock(
        side_effect=AssertionError("Legacy research must not capture configuration."),
    )
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed", result
    assert len(state.runtime.state.web) == len(state.runtime.state.pages) == 1
    assert state.events == state.captures == state.admissions == []
    state.context.capture_external_source_configuration.assert_not_called()
    state.planner_calls.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
