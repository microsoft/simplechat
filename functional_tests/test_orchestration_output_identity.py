# test_orchestration_output_identity.py
"""
Current directory authority failures through real output lifecycle boundaries.
Version: 0.261.127
Implemented in: 0.261.127

The current identity I/O boundary raises the real typed authority exceptions.
Rendering, durable attempt admission, publication reads and history use production
modules with the existing external-storage doubles, without model/provider calls.
"""

import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from content_screening.contracts import DocumentHeldError, ScreeningConfigurationError, ScreeningError
from functions_orchestration_artifacts import binding_for_intent, load_orchestration_artifact_binding
from functions_orchestration_external_identity import ExternalIdentityCancelledError, ExternalIdentityServiceError
from functions_orchestration_output_store import OutputUnavailableError
from functions_orchestration_rendering import execute_render_file
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_output_lifecycle import lifecycle, production_modules


IDENTITY_FAILURES = (
    ("external_identity_service_unavailable", True),
    ("external_identity_timeout", True),
    ("external_identity_throttled", True),
    ("external_identity_incomplete", True),
    ("external_identity_response_invalid", False),
    ("external_identity_pagination_invalid", False),
    ("external_identity_limit_exceeded", False),
    ("external_identity_callback_invalid", False),
)


@pytest.mark.parametrize("code,retryable", IDENTITY_FAILURES)
@pytest.mark.parametrize("phase", ["render", "commit"])
def test_identity_failure_keeps_exact_bounded_attempt_budget(lifecycle, code, retryable, phase):
    output = lifecycle.prepare()
    original_authorizer = lifecycle.service.authorize_execution
    producer_writes = lifecycle.results.container.sequence
    failing = False

    def authorize(record, *, operation):
        nonlocal failing
        failing = failing or operation == phase
        if failing:
            raise ExternalIdentityServiceError(code)
        return original_authorizer(record, operation=operation)

    lifecycle.service.authorize_execution = authorize
    attempts = 3 if retryable else 1
    for attempt in range(1, attempts + 1):
        result = lifecycle.run(output)
        assert result["error_code"] == code and result["artifact_message_id"] is None
        assert result["row_count"] is None and result["character_count"] is None and result["size_bytes"] is None
        if attempt < attempts:
            assert result["state"] == "retry_scheduled"
            assert result["automatic_attempts"] == attempt + 1
            lifecycle.advance_due(output)
        else:
            assert result["state"] == "failed" and result["can_retry"] is retryable
    before = lifecycle.raw(output)
    with pytest.raises(ExternalIdentityServiceError) as unavailable:
        lifecycle.run(output)
    after = lifecycle.raw(output)
    assert unavailable.value.code == code and unavailable.value.retryable is retryable
    assert before == after and after["attempt_count"] == after["automatic_attempts"] == attempts
    assert after["committed_intent"] is None
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == (1 if phase == "commit" else 0)
    if retryable:
        with pytest.raises(ExternalIdentityServiceError):
            lifecycle.service.manual_retry(output["output_id"], "identity-restored")
        unchanged = lifecycle.raw(output)
        assert unchanged == after
        lifecycle.service.authorize_execution = original_authorizer
        manual = lifecycle.service.manual_retry(output["output_id"], "identity-restored")
        repeated = lifecycle.service.manual_retry(output["output_id"], "identity-restored")
        completed = lifecycle.run(manual)
        assert repeated == manual and manual["attempt_count"] == 4 and manual["automatic_attempts"] == 3
        assert completed["state"] == "completed" and completed["automatic_attempts"] == 3
        assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1
    assert lifecycle.results.container.sequence == producer_writes


@pytest.mark.parametrize("code,retryable", IDENTITY_FAILURES)
@pytest.mark.parametrize("surface", ["read", "outputs", "cards", "binding", "history", "file", "cached_file"])
def test_identity_uncertainty_never_returns_stale_output_or_finalization_facts(lifecycle, code, retryable, surface):
    completed = lifecycle.run(lifecycle.prepare())
    record = lifecycle.raw(completed)
    binding = binding_for_intent(record, record["committed_intent"])
    message = lifecycle.output_history(with_cards=False)
    if surface in {"file", "cached_file"}:
        message = lifecycle.service.transport.message(record, committed=True)
        if surface == "cached_file":
            with lifecycle.app.test_request_context():
                message = lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    original_message = deepcopy(message)

    def unavailable(*args, **kwargs):
        raise ExternalIdentityServiceError(code)

    lifecycle.service.authorize_execution = unavailable
    with pytest.raises(ExternalIdentityServiceError) as failure:
        if surface == "read":
            lifecycle.service.read(completed["output_id"])
        elif surface == "outputs":
            lifecycle.service.list_public_outputs("run-1")
        elif surface == "cards":
            lifecycle.service.committed_artifacts("run-1")
        elif surface == "binding":
            load_orchestration_artifact_binding("owner", binding)
        else:
            with lifecycle.app.test_request_context():
                lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    after = lifecycle.raw(completed)
    assert failure.value.code == code and failure.value.retryable is retryable
    assert record == after and message == original_message
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1


@pytest.mark.parametrize("code,retryable", IDENTITY_FAILURES)
@pytest.mark.parametrize("surface", ["binding", "history", "file"])
def test_identity_failure_in_service_factory_remains_an_operational_failure(lifecycle, monkeypatch, code, retryable, surface):
    completed = lifecycle.run(lifecycle.prepare())
    record = lifecycle.raw(completed)
    binding = binding_for_intent(record, record["committed_intent"])
    message = (
        lifecycle.service.transport.message(record, committed=True)
        if surface == "file" else lifecycle.output_history(with_cards=False)
    )
    original_message = deepcopy(message)

    def unavailable(*args, **kwargs):
        raise ExternalIdentityServiceError(code)

    monkeypatch.setattr(importlib.import_module("functions_orchestration_artifacts"), "_service_factory", unavailable)
    with pytest.raises(ExternalIdentityServiceError) as failure:
        if surface == "binding":
            load_orchestration_artifact_binding("owner", binding)
        else:
            with lifecycle.app.test_request_context():
                lifecycle.modules.sources.sanitize_generated_artifact_history(message, "owner")
    after = lifecycle.raw(completed)
    assert failure.value.code == code and failure.value.retryable is retryable
    assert record == after and message == original_message
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1


@pytest.mark.parametrize("wrapper", [
    PermissionError, ResultUnavailableError, OutputUnavailableError, DocumentHeldError, ScreeningConfigurationError,
])
def test_explicit_wrapped_identity_outage_is_not_denial_or_hold(lifecycle, wrapper):
    output = lifecycle.prepare()

    def unavailable(*args, **kwargs):
        raise wrapper("private wrapper details") from ExternalIdentityServiceError("external_identity_throttled")

    lifecycle.service.authorize_execution = unavailable
    result = lifecycle.run(output)
    assert result["state"] == "retry_scheduled" and result["automatic_attempts"] == 2
    assert result["error_code"] == "external_identity_throttled"
    assert "private wrapper" not in json.dumps(result) and not lifecycle.render_calls
    with pytest.raises(ExternalIdentityServiceError):
        lifecycle.service.committed_artifacts("run-1")


@pytest.mark.parametrize("wrapper", [PermissionError, OutputUnavailableError, ScreeningError, TimeoutError])
def test_factory_wrapper_does_not_convert_malformed_identity_to_denial_or_retry(lifecycle, monkeypatch, wrapper):
    completed = lifecycle.run(lifecycle.prepare())
    record = lifecycle.raw(completed)
    binding = binding_for_intent(record, record["committed_intent"])

    def malformed(*args, **kwargs):
        raise wrapper("private wrapper details") from ExternalIdentityServiceError("external_identity_response_invalid")

    monkeypatch.setattr(importlib.import_module("functions_orchestration_artifacts"), "_service_factory", malformed)
    with pytest.raises(ExternalIdentityServiceError) as failure:
        load_orchestration_artifact_binding("owner", binding)
    after = lifecycle.raw(completed)
    assert failure.value.code == "external_identity_response_invalid" and failure.value.retryable is False
    assert record == after and len(lifecycle.render_calls) == 1


@pytest.mark.parametrize("failure_type,code", [
    (ResultUnavailableError, "output_access_denied"),
    (DocumentHeldError, "output_screening_hold"),
    (ExternalIdentityCancelledError, "output_cancelled"),
])
def test_actual_denial_hold_and_cancel_never_retry(lifecycle, failure_type, code):
    output = lifecycle.prepare()

    def denied(*args, **kwargs):
        raise failure_type()

    lifecycle.service.authorize_execution = denied
    result = lifecycle.run(output)
    assert result["state"] == ("cancelled" if failure_type is ExternalIdentityCancelledError else "failed")
    assert result["error_code"] == code and result["automatic_attempts"] == 1
    assert result["can_retry"] is False and result["artifact_message_id"] is None
    assert not lifecycle.render_calls and not lifecycle.blobs.data


def test_implicit_earlier_identity_error_does_not_reclassify_a_fresh_denial(lifecycle):
    output = lifecycle.prepare()

    def denied(*args, **kwargs):
        try:
            raise ExternalIdentityServiceError()
        except ExternalIdentityServiceError:
            raise ResultUnavailableError("external_identity_access_denied")

    lifecycle.service.authorize_execution = denied
    result = lifecycle.run(output)
    assert result["state"] == "failed" and result["error_code"] == "output_access_denied"
    assert result["automatic_attempts"] == 1 and not result["can_retry"]
    assert not lifecycle.render_calls and not lifecycle.blobs.data


@pytest.mark.parametrize("state", ["retry_scheduled", "rendering"])
def test_identity_error_during_observation_cannot_spend_another_attempt(lifecycle, state):
    output = lifecycle.prepare()
    if state == "retry_scheduled":
        lifecycle.failures["json"] = [TimeoutError("A transient renderer failure.")]
        scheduled = lifecycle.run(output)
        assert scheduled["state"] == "retry_scheduled"
    else:
        claim = lifecycle.service.claim_due(output["output_id"], worker_id="current-worker")
        assert claim is not None
    before = lifecycle.raw(output)

    def unavailable(*args, **kwargs):
        raise ExternalIdentityServiceError("external_identity_throttled")

    lifecycle.service.authorize_execution = unavailable
    with pytest.raises(ExternalIdentityServiceError):
        lifecycle.run(output)
    after = lifecycle.raw(output)
    assert before == after and after["state"] == state


@pytest.mark.parametrize("code,retryable", IDENTITY_FAILURES)
def test_render_adapter_never_echoes_cached_completion_after_identity_failure(lifecycle, monkeypatch, code, retryable):
    completed = lifecycle.run(lifecycle.prepare())
    before = lifecycle.raw(completed)
    producer = lifecycle.add_render_step("json_file")
    reader = lifecycle.service.results.open_result(lifecycle.saved.output("findings"))
    context = SimpleNamespace(
        plan_contract_version=2, execution_deadline_at=lifecycle.deadline.isoformat(),
        result_producer=lambda step: producer,
    )
    step = {
        "step_id": "json_file", "capability_id": "render_file",
        "arguments": {"file_name": "json_file.json", "output_format": "json", "profile": "exact_records_v1"},
    }
    original_ensure = lifecycle.service.ensure_output

    def unavailable(*args, **kwargs):
        raise ExternalIdentityServiceError(code)

    def ensure_then_fail_identity(**kwargs):
        saved = original_ensure(**kwargs)
        lifecycle.service.authorize_execution = unavailable
        return saved

    monkeypatch.setattr(lifecycle.service, "ensure_output", ensure_then_fail_identity)
    result = execute_render_file(
        step, context, service_factory=lambda *args, **kwargs: lifecycle.service,
        resolve_inputs=lambda step, context: {"source": reader},
        build_step_result=lifecycle.modules.schema.build_step_result,
        build_failure=lifecycle.modules.schema.build_failure, settings={}, user_id="owner",
    )
    after = lifecycle.raw(completed)
    assert result["status"] == ("waiting" if retryable else "failed")
    assert result["output_error"] == {"code": code, "retryable": retryable}
    assert not result.get("outputs") and not result["artifacts"]
    assert completed["artifact_message_id"] not in json.dumps(result)
    assert before == after and len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1


def test_late_worker_cannot_report_another_workers_success_during_identity_outage(lifecycle):
    output = lifecycle.prepare()
    original_service = lifecycle.service
    entered, release = threading.Event(), threading.Event()

    def pause():
        entered.set()
        if not release.wait(30):
            raise AssertionError("The stale-writer test was not released.")

    def unavailable(*args, **kwargs):
        raise ExternalIdentityServiceError("external_identity_throttled")

    lifecycle.messages.after_create = pause
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(lifecycle.run, output)
        try:
            if not entered.wait(30):
                raise AssertionError("The real uploader did not create its staged message.")
            lifecycle.now += timedelta(seconds=11)
            lifecycle.restart()
            recovered = lifecycle.service.reconcile(output["output_id"])
            lifecycle.advance_due(output)
            completed = lifecycle.run(output)
            before = lifecycle.raw(completed)
            lifecycle.service.authorize_execution = unavailable
            original_service.authorize_execution = unavailable
        finally:
            release.set()
        with pytest.raises(ExternalIdentityServiceError) as failure:
            future.result(timeout=30)
    after = lifecycle.raw(completed)
    assert recovered["state"] == "retry_scheduled" and completed["state"] == "completed"
    assert failure.value.code == "external_identity_throttled" and before == after
    assert len(lifecycle.render_calls) == lifecycle.blobs.uploads == 1
