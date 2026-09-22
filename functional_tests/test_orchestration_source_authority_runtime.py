# test_orchestration_source_authority_runtime.py
"""V2 runtime/recovery must not turn uncertain source authority into a denial.

Version: 0.261.127
Implemented in: 0.261.127

Real dispatch, composition, leases, checkpoints and retained-result recovery
preserve typed screening, directory and configuration errors. Caller-owned
strict scopes fence caught failures; known holds and access denials keep their
existing outcome.
"""

from copy import deepcopy
import importlib

import pytest

from content_screening.access import (
    assert_current_request_sources_available, raise_source_authority_error, strict_source_authority,
)
from content_screening.contracts import (
    DocumentHeldError, ScreeningConfigurationError, ScreeningError,
    SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError,
)
from test_orchestration_dependency_recovery import durable, fail_first
from test_orchestration_dependency_runtime import binding, compose, execute, runtime
from test_orchestration_waiting_continuation import claim, waiting


@pytest.fixture(params=[
    ScreeningError, ScreeningConfigurationError,
    SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError,
])
def authority_failure(request):
    return request.param("PRIVATE_SOURCE_AUTHORITY_DIAGNOSTIC")


@pytest.fixture(params=[
    ("identity", "ExternalIdentityServiceError", None),
    ("identity", "ExternalIdentityCancelledError", None),
    ("configuration", "ExternalConfigurationServiceError", None),
    ("configuration", "ExternalConfigurationServiceError", "external_configuration_metadata_invalid"),
    ("configuration", "ExternalConfigurationCancelledError", None),
])
def metadata_failure(runtime, request):
    # Resolve owner-defined error types after the offline application fixture is initialized.
    family, name, code = request.param
    module = importlib.import_module(f"functions_orchestration_external_{family}")
    error_type = getattr(module, name)
    return error_type() if code is None else error_type(code)


def unavailable(failure):
    def fail(*args, **kwargs):
        raise failure

    return fail


def _check_composition_service_failure(runtime, failure):
    case = runtime.make(
        [compose("source"), compose("independent")], [failure, "Must not generate."],
    )
    writes = []
    with pytest.raises(type(failure)) as raised:
        execute(
            runtime, case, persist=lambda kind, record: writes.append((kind, deepcopy(record))),
        )
    assert raised.value is failure
    assert len(case.model.calls) == 1 and case.model.replies == ["Must not generate."]
    assert case.context.task_results == {} and case.context.failures == []
    assert not case.context._failed_result_step_ids
    assert not any(
        record.get("status") in {"failed", "cancelled", "completed"} for _, record in writes
    )


def test_composition_preserves_typed_source_authority(runtime, authority_failure):
    _check_composition_service_failure(runtime, authority_failure)


def test_composition_preserves_typed_metadata_service_and_cancellation(runtime, metadata_failure):
    _check_composition_service_failure(runtime, metadata_failure)


@pytest.mark.parametrize("error_type,code", [
    (PermissionError, "result_unavailable"),
    (ValueError, "result_invalid"),
    (TimeoutError, "provider_timeout"),
    (ConnectionError, "connection_failed"),
    (RuntimeError, "model_failed"),
])
def test_composition_keeps_ordinary_model_failure_mapping(runtime, error_type, code):
    case = runtime.make([compose()], [error_type("PRIVATE_MODEL_DIAGNOSTIC")])
    result = execute(runtime, case)
    assert result["status"] == "failed"
    assert result["steps"][0]["failure"]["code"] == code
    assert "PRIVATE_MODEL_DIAGNOSTIC" not in result["message"]
    assert case.context.task_results == {} and len(case.model.calls) == 1


def test_producer_authority_failure_does_not_terminalize_or_run_independent_models(
    runtime, authority_failure,
):
    case = runtime.make([compose("source"), compose("independent")], ["Must not generate."])
    calls, writes = [], []

    def adapter(step, context, **kwargs):
        calls.append(step["step_id"])
        if step["step_id"] == "source":
            raise authority_failure
        return runtime.composition.adapter_compose(step, context, **kwargs)

    with pytest.raises(type(authority_failure)) as raised:
        execute(
            runtime, case, get_adapter=lambda capability: adapter,
            persist=lambda kind, record: writes.append((kind, deepcopy(record))),
        )
    assert raised.value is authority_failure
    assert calls == ["source"] and case.model.calls == []
    assert case.context.failures == []
    assert not any(record.get("status") == "failed" for _, record in writes)
    assert "source" not in case.context._failed_result_step_ids


def test_caught_authority_failure_is_checked_before_accepting_adapter_result(
    runtime, authority_failure,
):
    case = runtime.make([compose("source"), compose("independent")], ["Must not generate."])
    calls, writes = [], []

    def adapter(step, context, **kwargs):
        calls.append(step["step_id"])
        if step["step_id"] != "source":
            return runtime.composition.adapter_compose(step, context, **kwargs)
        try:
            raise_source_authority_error(authority_failure)
        except ScreeningError:
            pass
        return runtime.schema.build_step_result(
            status="failed", failure=runtime.schema.build_failure("result_unavailable"),
        )

    with pytest.raises(type(authority_failure)) as raised, strict_source_authority():
        execute(
            runtime, case, get_adapter=lambda capability: adapter,
            persist=lambda kind, record: writes.append((kind, deepcopy(record))),
        )
    assert_current_request_sources_available("owner")
    assert raised.value is authority_failure
    assert calls == ["source"] and case.model.calls == []
    assert case.context.failures == []
    assert not any(record.get("status") == "failed" for _, record in writes)


def test_already_fenced_authority_does_not_enter_another_adapter(runtime, authority_failure):
    case = runtime.make([compose()], ["Must not generate."])
    calls = []

    def adapter(step, context, **kwargs):
        calls.append(step["step_id"])
        return runtime.composition.adapter_compose(step, context, **kwargs)

    with pytest.raises(type(authority_failure)) as raised, strict_source_authority():
        try:
            raise_source_authority_error(authority_failure)
        except ScreeningError:
            pass
        execute(runtime, case, get_adapter=lambda capability: adapter)
    assert_current_request_sources_available("owner")
    assert raised.value is authority_failure
    assert calls == [] and case.model.calls == []


def test_caught_source_admission_failure_stops_the_adapter_before_effects(
    runtime, authority_failure,
):
    case = runtime.make([{
        "step_id": "source", "capability_id": "document_search", "arguments": {"query": "Find evidence."},
    }])
    case.context.selected_document_ids = ["document-1"]
    original = case.context.resolve_source_manifest
    calls = []

    def resolve(*args, **kwargs):
        manifest = original(*args, **kwargs)
        try:
            raise_source_authority_error(authority_failure)
        except ScreeningError:
            pass
        return manifest

    def adapter(step, context, **kwargs):
        calls.append(step["step_id"])
        return runtime.schema.build_step_result(
            status="failed", failure=runtime.schema.build_failure("step_failed"),
        )

    case.context.resolve_source_manifest = resolve
    with pytest.raises(type(authority_failure)) as raised, strict_source_authority():
        execute(runtime, case, get_adapter=lambda capability: adapter)
    assert raised.value is authority_failure
    assert calls == [] and case.model.calls == []


@pytest.mark.parametrize("receipt_found", [True, False], ids=["cached-result", "missing-result"])
def test_caught_recovered_receipt_failure_cannot_promote_cached_success_or_replay(
    runtime, monkeypatch, authority_failure, receipt_found,
):
    case = runtime.make([compose()], ["Already retained."], final_response=binding("draft"))
    initial = execute(runtime, case)
    assert initial["status"] == "completed"
    original = case.context.result_service.recover_task_result
    writes = []

    def recover(**kwargs):
        recovered = original(**kwargs)
        try:
            raise_source_authority_error(authority_failure)
        except ScreeningError:
            pass
        return recovered if receipt_found else None

    monkeypatch.setattr(case.context.result_service, "recover_task_result", recover)
    case.context.task_results.clear()
    with pytest.raises(type(authority_failure)) as raised, strict_source_authority():
        execute(
            runtime, case, persist=lambda kind, record: writes.append((kind, deepcopy(record))),
        )
    assert raised.value is authority_failure
    assert len(case.model.calls) == 1
    assert not any(record.get("status") in {"failed", "completed"} for _, record in writes)


def test_final_source_uncertainty_preserves_committed_results(
    runtime, monkeypatch, authority_failure,
):
    case = runtime.make(
        [compose()], ["Already retained complete content."], final_response=binding("draft"),
    )
    monkeypatch.setattr(
        runtime.executor, "read_result_document_citations", unavailable(authority_failure),
    )
    with pytest.raises(type(authority_failure)) as raised:
        execute(runtime, case)
    assert raised.value is authority_failure
    assert len(case.model.calls) == 1
    assert case.context.task_results["draft"].status == "complete"
    assert case.context.failures == []


def test_saved_wait_uncertainty_never_clears_pending_results(
    waiting, monkeypatch, authority_failure,
):
    before = waiting.read_run("run-1")
    acquired = claim(waiting)
    context = waiting.fresh_context(acquired["record"])
    monkeypatch.setattr(
        waiting.runtime.executor, "resume_waiting_dependency_step", unavailable(authority_failure),
    )
    with pytest.raises(type(authority_failure)) as raised:
        waiting.run(acquired["record"], context)
    current = waiting.read_run("run-1")
    assert raised.value is authority_failure
    assert current["pending_results"] == before["pending_results"]
    assert current["task_results"] == before["task_results"]
    assert current["execution_deadline_at"] == before["execution_deadline_at"]
    assert context.pending_results["failed"] == before["pending_results"]["failed"]
    assert context.task_results["failed"].status == "pending"
    assert context.failures == [] and len(waiting.case.model.calls) == 1


def test_saved_wait_metadata_failure_preserves_original_work(waiting, monkeypatch, metadata_failure):
    before = waiting.read_run("run-1")
    acquired = claim(waiting)
    context = waiting.fresh_context(acquired["record"])
    monkeypatch.setattr(
        waiting.runtime.executor, "resume_waiting_dependency_step", unavailable(metadata_failure),
    )
    with pytest.raises(type(metadata_failure)) as raised:
        waiting.run(acquired["record"], context)
    current = waiting.read_run("run-1")
    assert raised.value is metadata_failure
    assert current["pending_results"] == before["pending_results"]
    assert current["task_results"] == before["task_results"]
    assert current["execution_deadline_at"] == before["execution_deadline_at"]
    assert context.pending_results["failed"] == before["pending_results"]["failed"]
    assert context.task_results["failed"].status == "pending"
    assert context.failures == [] and len(waiting.case.model.calls) == 1


@pytest.mark.parametrize("boundary", ["reference", "receipt"])
def test_recovery_preserves_typed_authority_error_instead_of_checkpoint_denial(
    durable, monkeypatch, authority_failure, boundary,
):
    fail_first(durable)
    record = durable.read_run("run-1")
    context = durable.fresh_context(record)
    original_records = deepcopy(durable.case.fixture.container.items)
    method = "open_result" if boundary == "reference" else "recover_task_result"
    monkeypatch.setattr(context.result_service, method, unavailable(authority_failure))
    with pytest.raises(type(authority_failure)) as raised:
        if boundary == "reference":
            durable.recovery.validate_resume(
                record, context, durable.case.settings, lambda: True, source_run_id=record["id"],
            )
        else:
            durable.recovery._receipt_checkpoint(
                record, "retained", lambda: True, context.result_service,
            )
    assert raised.value is authority_failure
    assert durable.case.fixture.container.items == original_records
    assert len(durable.case.model.calls) == 1


@pytest.mark.parametrize("failure_type", [DocumentHeldError, PermissionError])
def test_known_hold_and_denial_keep_the_existing_step_failure(runtime, failure_type):
    case = runtime.make([compose()])
    result = execute(
        runtime, case, get_adapter=lambda capability: unavailable(failure_type("PRIVATE_DENIAL")),
    )
    assert result["status"] == "failed"
    assert result["steps"][0]["failure"]["code"] == "result_unavailable"
    assert case.model.calls == []
