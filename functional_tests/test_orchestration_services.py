# test_orchestration_services.py
"""
Initialized service and owning-guard wiring for retained orchestration results.
Version: 0.261.127
Implemented in: 0.261.127

Uses real services, result persistence, runtime contexts and checkpoint adapters
with external storage/access doubled. No route, provider or model is substituted
for the service boundary under test.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from content_screening.contracts import ScreeningConfigurationError, ScreeningError
from functions_document_analysis_checkpoints import analysis_checkpoints_for_orchestration
from functions_orchestration_artifacts import OrchestrationArtifactTransport
from functions_orchestration_executor import RunContext
from functions_orchestration_output_store import OutputError
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_orchestration_services import (
    OrchestrationServices,
    admitted_result_aliases,
    composition_profiles,
    discover_result_aliases,
    validate_composition_profile,
)
from test_support.orchestration_results import ResultFixture, complete
from test_support.orchestration_revisions import AtomicMemoryContainer


def _unexpected_io(*args, **kwargs):
    raise AssertionError("Service binding must not publish or fetch artifact bytes.")


def services(fixture, **options):
    return OrchestrationServices(
        user_id="owner", conversation_id="conversation-1",
        result_store=fixture.service.store,
        run_container=AtomicMemoryContainer("conversation_id"),
        read_conversation=lambda conversation_id: deepcopy(fixture.conversation),
        read_run=lambda run_id: deepcopy(fixture.runs.get(run_id)),
        source_resolver=fixture.resolve, source_metadata_reader=fixture.metadata,
        transport=OrchestrationArtifactTransport(
            upload=_unexpected_io, read_message=_unexpected_io,
            open_stream=_unexpected_io, delete=_unexpected_io, blob_container="private-results",
        ),
        authorize_execution=lambda record, operation: True,
        max_output_bytes=32 * 1024 * 1024,
        **options,
    )


def runtime(fixture):
    record = fixture.runs[fixture.producer.run_id]
    record["plan"]["planner_contract_version"] = 2
    context = RunContext(
        run_id=record["id"], conversation_id=record["conversation_id"],
        user_id=record["user_id"], attempt_index=record["attempt_index"],
        plan_contract_version=2,
    )
    return record, context


def checkpoint_factory(fixture, *, token="owning-lease-token", store=None):
    return lambda step_id: analysis_checkpoints_for_orchestration(
        "owner", "conversation-1", "run-1", step_id,
        authorize=lambda: True, attempt_token=token,
        store=fixture.service.store if store is None else store,
    )


def test_binding_reuses_exact_initialized_store_and_real_checkpoint_guard():
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    configured = bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    guard = context.result_guard_token_for_step("analyze")
    first = context.analysis_checkpoint_factory("analyze")
    second = context.analysis_checkpoint_factory("analyze")
    prepared = first.prepare()
    saved_guard = first.store._analysis_guard(first.binding, required=True, token=guard)
    task = context.result_service.persist_task_result(
        producer=context.result_producer(record["plan"]["steps"][0]),
        role="reason", status="complete",
        outputs=[NamedOutput("report", "text-v1", "All retained content.", complete(1))],
        sources=[], origin="generated", guard_token=guard,
    )
    reader = bound.results.open_result(task.output("report"))
    text = reader.read_text()
    assert configured is context
    assert first is second
    assert first.store is bound.results.store
    assert guard == "owning-lease-token"
    assert prepared["binding"] == first.binding
    assert saved_guard["token"] == guard
    assert text == "All retained content."
    assert context.rendering_service.results is context.result_service
    assert context.approved_work_id == "run-1"


def test_external_admission_is_explicit_and_has_no_binding_time_effects():
    fixture = ResultFixture()
    bound = services(
        fixture, external_source_catalog={},
        external_source_authorizer=_unexpected_io,
        external_source_admission=_unexpected_io,
        external_source_preflight=_unexpected_io,
        capture_external_source_configuration=_unexpected_io,
    )
    record, context = runtime(fixture)
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    assert context.external_source_admission is _unexpected_io
    assert context.external_source_preflight is _unexpected_io
    assert context.capture_external_source_configuration is _unexpected_io
    request_bindings = bound.capability_request_bindings()
    assert request_bindings["external_source_preflight"] is _unexpected_io
    assert request_bindings["external_source_admission"] is _unexpected_io
    assert request_bindings["external_source_authorizer"] is _unexpected_io
    assert request_bindings["capture_external_source_configuration"] is _unexpected_io
    assert request_bindings["rendering_service"] is bound.rendering
    with pytest.raises(ResultContractError):
        services(fixture, external_source_admission=_unexpected_io)


@pytest.mark.parametrize("formats", [None, (), ("csv",)])
def test_binding_uses_current_server_catalog_not_stale_context_or_saved_permissions(monkeypatch, formats):
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    canonical = bound.export_catalog()
    admitted = canonical if formats is None else [
        entry for entry in canonical if entry["format_id"] in formats
    ]
    stale = [{"format_id": "untrusted-saved-format"}]
    context.export_catalog = deepcopy(stale)
    record["export_catalog"] = deepcopy(stale)
    original = deepcopy(record)
    monkeypatch.setattr(bound, "export_catalog", lambda: deepcopy(admitted))
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    assert context.export_catalog == admitted
    assert record == original
    assert not fixture.container.items


def test_read_only_external_access_never_inherits_an_old_admission_hook():
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    context.external_source_admission = _unexpected_io
    context.external_source_preflight = _unexpected_io
    context.capture_external_source_configuration = _unexpected_io
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    assert context.external_source_admission is None
    assert context.external_source_preflight is None
    assert context.capture_external_source_configuration is None


@pytest.mark.parametrize("capture", [True, False, "capture", {}])
def test_external_capture_requires_a_real_server_callback(capture):
    fixture = ResultFixture()
    with pytest.raises(ResultContractError):
        services(
            fixture, external_source_catalog={},
            external_source_authorizer=_unexpected_io,
            external_source_admission=_unexpected_io,
            capture_external_source_configuration=capture,
        )


def test_external_capture_requires_the_matching_admission_and_authorization_boundaries():
    fixture = ResultFixture()
    with pytest.raises(ResultContractError):
        services(fixture, capture_external_source_configuration=_unexpected_io)


@pytest.mark.parametrize("preflight", [True, False, "preflight", {}])
def test_external_preflight_requires_a_real_server_callback(preflight):
    fixture = ResultFixture()
    with pytest.raises(ResultContractError):
        services(fixture, external_source_preflight=preflight)


def test_external_acquisition_without_entry_authorization_is_not_advertised():
    fixture = ResultFixture()
    bound = services(
        fixture, external_source_authorizer=_unexpected_io,
        external_source_admission=_unexpected_io, capture_external_source_configuration=_unexpected_io,
    )
    bindings = bound.capability_request_bindings()
    assert set(bindings) == {"native_bridge_for_step", "rendering_service"}


@pytest.mark.parametrize("admission", [None, _unexpected_io])
def test_read_only_or_uncaptured_external_services_are_not_advertised_for_execution(admission):
    fixture = ResultFixture()
    bound = services(
        fixture, external_source_authorizer=_unexpected_io,
        external_source_admission=admission,
    )
    bindings = bound.capability_request_bindings()
    assert set(bindings) == {"native_bridge_for_step", "rendering_service"}
    assert bound.results.access.external_source_authorizer is _unexpected_io


@pytest.mark.parametrize("factory", [None, _unexpected_io])
def test_native_binding_is_explicit_and_never_invoked_by_context_binding(factory):
    fixture = ResultFixture()
    bound = services(fixture, native_bridge_for_step=factory)
    record, context = runtime(fixture)
    context.native_bridge_for_step = _unexpected_io
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    assert context.native_bridge_for_step is factory
    assert not fixture.container.items


@pytest.mark.parametrize("factory", [True, False, "native", {}])
def test_native_readiness_cannot_be_a_flag_or_serialized_selector(factory):
    fixture = ResultFixture()
    with pytest.raises(ResultContractError):
        services(fixture, native_bridge_for_step=factory)


@pytest.mark.parametrize("mismatch", ["token", "store", "binding"])
def test_other_guard_or_store_is_not_silently_used(mismatch):
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    factory = checkpoint_factory(
        fixture,
        token="foreign-token" if mismatch == "token" else "owning-lease-token",
        store=fixture.restart().store if mismatch == "store" else None,
    )
    if mismatch == "binding":
        original = factory

        def factory(step_id):
            value = original(step_id)
            value.binding["run_id"] = "another-run"
            return value

    bound.bind_context(
        context, record, checkpoint_factory=factory,
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    with pytest.raises(ResultContractError):
        context.result_guard_token_for_step("analyze")
    assert not fixture.container.items


@pytest.mark.parametrize("change", ["owner", "conversation", "attempt", "version"])
def test_foreign_or_legacy_runtime_cannot_bind_new_services(change):
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    if change == "owner":
        context.user_id = "other-user"
    elif change == "conversation":
        context.conversation_id = "other-conversation"
    elif change == "attempt":
        context.attempt_index = 2
    else:
        context.plan_contract_version = 1
    with pytest.raises(ResultContractError):
        bound.bind_context(
            context, record, checkpoint_factory=checkpoint_factory(fixture),
            guard_token="owning-lease-token", execution_check=lambda: True,
        )


def test_guard_rechecks_current_cancellation_and_enabled_step():
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    with pytest.raises(ResultContractError):
        context.result_guard_token_for_step("unapproved")
    record["cancellation_requested_at"] = "2026-01-01T00:00:00+00:00"
    with pytest.raises(ResultUnavailableError):
        context.result_guard_token_for_step("analyze")
    assert not fixture.container.items


def test_lost_execution_lease_cannot_prepare_new_guard():
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: False,
    )
    with pytest.raises(ResultContractError):
        context.analysis_checkpoint_factory("analyze")
    assert not fixture.container.items


def test_admitted_aliases_reopen_real_refs_and_recheck_current_sources():
    fixture = ResultFixture()
    saved = fixture.save()
    reference = saved.output("findings")
    record = {"result_aliases": {"prior_findings": reference.to_dict()}}
    aliases = admitted_result_aliases(record, fixture.restart())
    assert aliases == {"prior_findings": reference}
    fixture.denied.add("document-1")
    with pytest.raises(PermissionError):
        admitted_result_aliases(record, fixture.restart())


def test_alias_admission_rejects_foreign_producer_and_preview():
    fixture = ResultFixture()
    saved = fixture.save()
    reference = saved.output("findings")
    foreign = replace(
        reference, producer=replace(reference.producer, user_id="other-user"),
    )
    with pytest.raises(ResultUnavailableError):
        admitted_result_aliases({"result_aliases": {"foreign": foreign.to_dict()}}, fixture.service)
    with pytest.raises(ResultContractError):
        admitted_result_aliases({"result_aliases": {"preview": {"preview": True}}}, fixture.service)


def test_discovery_is_bounded_and_reports_current_access_omissions():
    fixture = ResultFixture()
    saved = fixture.save()
    record = fixture.runs["run-1"]
    record["plan"]["planner_contract_version"] = 2
    record["task_results"] = {"analyze": saved.to_dict()}
    available = discover_result_aliases([deepcopy(record)], fixture.restart())
    fixture.held.add("document-1")
    unavailable = discover_result_aliases([deepcopy(record)], fixture.restart())
    assert list(available["aliases"].values()) == list(saved.outputs)
    assert available["unavailable_count"] == 0
    assert unavailable == {"aliases": {}, "unavailable_count": 1}
    with pytest.raises(ResultContractError):
        discover_result_aliases([deepcopy(record)] * 11, fixture.service)


@pytest.mark.parametrize("failure_type", [ScreeningError, ScreeningConfigurationError])
def test_discovery_does_not_omit_results_when_current_screening_cannot_be_checked(monkeypatch, failure_type):
    fixture = ResultFixture()
    saved = fixture.save()
    record = fixture.runs["run-1"]
    record["plan"]["planner_contract_version"] = 2
    record["task_results"] = {"analyze": saved.to_dict()}

    def failed_metadata(*args, **kwargs):
        raise failure_type("Private screening backend details.")

    monkeypatch.setattr(fixture, "metadata", failed_metadata)
    reopened = fixture.restart()
    with pytest.raises(failure_type):
        discover_result_aliases([deepcopy(record)], reopened)


def test_discovery_never_admits_a_foreign_run_record():
    fixture = ResultFixture()
    record = deepcopy(fixture.runs["run-1"])
    record["user_id"] = "someone-else"
    with pytest.raises(ResultContractError):
        discover_result_aliases([record], fixture.service)


def test_composition_profiles_are_copied_from_the_shared_registry():
    profiles = composition_profiles()
    deck = {
        "schema_version": "prepared_slide_deck_v1", "slide_count": 1,
        "slides": [{"layout": "blank", "title": "", "shapes": []}],
    }
    valid = validate_composition_profile("prepared_slide_deck_v1", deck)
    profiles["prepared_slide_deck_v1"].clear()
    fresh = composition_profiles()
    assert valid is True
    assert fresh["prepared_slide_deck_v1"]
    with pytest.raises(ResultContractError):
        validate_composition_profile("undeclared-layout", deck)


def test_render_factory_rejects_a_context_bound_to_another_service():
    fixture = ResultFixture()
    bound = services(fixture)
    record, context = runtime(fixture)
    bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    rendering = bound.rendering_for_context(context, settings={}, user_id="owner")
    assert rendering is bound.rendering
    with pytest.raises(OutputError):
        bound.rendering_for_context(context, settings={}, user_id="someone-else")
