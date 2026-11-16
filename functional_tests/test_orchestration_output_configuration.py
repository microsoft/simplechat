# test_orchestration_output_configuration.py
"""
Preserve typed current-configuration failures through retained file boundaries.
Version: 0.261.127
Implemented in: 0.261.127

Real metadata attestation, rendering, transport, publication, history and
read-only resumption use external-I/O doubles. No configuration proof, source
content, model invocation or extra retry admission may replace failed authority.
"""

import importlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import AzureError, HttpResponseError, ResourceNotFoundError

from content_screening.contracts import DocumentHeldError, ScreeningConfigurationError
from functions_orchestration_artifacts import binding_for_intent, load_orchestration_artifact_binding
from functions_orchestration_output_store import OutputUnavailableError
from functions_orchestration_rendering import execute_render_file, output_failure
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_output_lifecycle import APP, ROOT, TESTS, lifecycle, production_modules  # noqa: F401
from test_orchestration_render_resume import (
    completed_result, forbid_execution, pending_result, persistence_snapshot, resume, resumption,
)


CONFIGURATION_FAILURES = (
    ("external_configuration_service_unavailable", True),
    ("external_configuration_timeout", True),
    ("external_configuration_throttled", True),
    ("external_configuration_metadata_invalid", False),
    ("external_configuration_limit_exceeded", False),
)
ALL_FAILURES = (*CONFIGURATION_FAILURES, ("output_cancelled", False))


_CONFIGURATION_CLASSIFIER_PROBE = r"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

app = Path(sys.argv[1]).resolve()
with offline_app_imports():
    modules = {}
    for name in sys.argv[3:]:
        modules[name] = importlib.import_module(name)
    configuration = modules["functions_orchestration_external_configuration"]
    rendering = modules["functions_orchestration_rendering"]
    artifacts = importlib.import_module("functions_orchestration_artifacts")
    results = importlib.import_module("functions_orchestration_results")
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    for module in (configuration, rendering, artifacts, results, checkpoints):
        if Path(module.__file__).resolve().parent != app:
            raise AssertionError("The probe imported a different application tree.")
    failures = (
        ("external_configuration_service_unavailable", True),
        ("external_configuration_timeout", True),
        ("external_configuration_throttled", True),
        ("external_configuration_metadata_invalid", False),
        ("external_configuration_limit_exceeded", False),
        ("output_cancelled", False),
    )
    checked = 0
    for code, retryable in failures:
        original = (
            configuration.ExternalConfigurationCancelledError()
            if code == "output_cancelled"
            else configuration.ExternalConfigurationServiceError(code)
        )
        result_error = results.ResultUnavailableError("external_configuration_unavailable")
        result_error.__cause__ = original
        checkpoint_error = checkpoints.CheckpointError("checkpoint_storage_unavailable")
        checkpoint_error.__cause__ = result_error
        nested_error = RuntimeError("A private wrapper.")
        nested_error.__cause__ = checkpoint_error
        for candidate in (original, result_error, checkpoint_error, nested_error):
            classified = rendering.output_failure(candidate)
            if classified != (code, retryable):
                raise AssertionError((type(candidate).__name__, code, classified))
            authority = artifacts.external_authority_failure(candidate)
            if authority is None or authority[0] is not original or authority[1:] != (code, retryable):
                raise AssertionError("The shared authority classifier lost the original failure.")
            try:
                rendering.raise_output_read_infrastructure_failure(candidate)
            except type(original) as raised:
                if raised is not original:
                    raise AssertionError("The read boundary substituted another failure.")
            else:
                raise AssertionError("The read boundary swallowed an authority failure.")
            checked += 1
        denial = results.ResultUnavailableError("external_configuration_unavailable")
        denial.__context__ = original
        classified = rendering.output_failure(denial)
        if classified != ("output_access_denied", False):
            raise AssertionError("An implicit context changed a genuine denial.")
    fingerprints = {
        Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (artifacts, rendering)
    }
print("PASS: actual configuration classifier boundaries", checked, json.dumps(fingerprints, sort_keys=True))
"""


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("configuration_first", [False, True])
def test_actual_configuration_classifiers_in_a_fresh_offline_process(optimized, configuration_first):
    modules = [
        "functions_orchestration_rendering", "functions_orchestration_external_configuration",
    ]
    if configuration_first:
        modules.reverse()
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    completed = subprocess.run(
        command + ["-c", _CONFIGURATION_CLASSIFIER_PROBE, str(APP), str(TESTS), *modules],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout[-6000:] + completed.stderr[-6000:]
    assert "PASS: actual configuration classifier boundaries 24" in completed.stdout


@pytest.fixture
def configuration(lifecycle):
    return importlib.import_module("functions_orchestration_external_configuration")


def current_metadata_failure(world, module, code):
    if code == "external_configuration_service_unavailable":
        error = AzureError("PRIVATE metadata transport failure")
    elif code == "external_configuration_timeout":
        error = TimeoutError("PRIVATE metadata timeout")
    elif code == "external_configuration_throttled":
        error = HttpResponseError("PRIVATE metadata throttling")
        error.status_code = 429
    elif code == "external_configuration_metadata_invalid":
        error = ValueError("PRIVATE malformed metadata")
    elif code == "output_cancelled":
        error = module.ExternalConfigurationCancelledError()
    else:
        error = module.ExternalConfigurationServiceError(code)
    provider = Mock(side_effect=error)
    digest = Mock(side_effect=AssertionError("Failed metadata must not mint a configuration proof."))
    attestor = module.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation-1",
        read_current_source=provider, private_digest=digest,
    )
    producer = replace(world.results.producer, capability_id="web_search")
    raised = []

    def fail(*args, **kwargs):
        try:
            return attestor.current("web", producer=producer, settings={})
        except (module.ExternalConfigurationServiceError, module.ExternalConfigurationCancelledError) as exc:
            raised.append(exc)
            raise

    return SimpleNamespace(call=fail, provider=provider, digest=digest, raised=raised)


@pytest.mark.parametrize("code,retryable", CONFIGURATION_FAILURES)
@pytest.mark.parametrize("phase", ["render", "commit"])
def test_configuration_failures_keep_the_existing_file_budget(lifecycle, configuration, code, retryable, phase):
    world = lifecycle
    output = world.prepare()
    original = world.service.authorize_execution
    failure = current_metadata_failure(world, configuration, code)
    failing = False

    def authorize(record, *, operation):
        nonlocal failing
        failing = failing or operation == phase
        return failure.call() if failing else original(record, operation=operation)

    world.service.authorize_execution = authorize
    count = 3 if retryable else 1
    for attempt in range(1, count + 1):
        outcome = world.run(output)
        assert outcome["error_code"] == code
        assert outcome["artifact_message_id"] is outcome["row_count"] is outcome["size_bytes"] is None
        assert "PRIVATE" not in json.dumps(outcome)
        if attempt < count:
            assert outcome["state"] == "retry_scheduled" and outcome["automatic_attempts"] == attempt + 1
            world.advance_due(outcome)
        else:
            assert outcome["state"] == "failed" and outcome["can_retry"] is retryable
    before = persistence_snapshot(world)
    with pytest.raises(configuration.ExternalConfigurationServiceError) as caught:
        world.run(output)
    after = persistence_snapshot(world)
    assert caught.value.code == code and caught.value.retryable is retryable and before == after
    assert outcome["attempt_count"] == outcome["automatic_attempts"] == count
    if retryable:
        with pytest.raises(configuration.ExternalConfigurationServiceError):
            world.service.manual_retry(output["output_id"], "configuration-restored")
        unchanged = persistence_snapshot(world)
        assert unchanged == after
        world.service.authorize_execution = original
        manual = world.service.manual_retry(output["output_id"], "configuration-restored")
        duplicate = world.service.manual_retry(output["output_id"], "configuration-restored")
        restored = world.run(manual)
        assert manual == duplicate and manual["attempt_count"] == 4 and manual["automatic_attempts"] == 3
        assert restored["state"] == "completed" and len(world.render_calls) == world.blobs.uploads == 1
    assert world.results.container.sequence == world.producer_writes
    assert failure.provider.call_count and not failure.digest.call_count


@pytest.mark.parametrize("code,retryable", ALL_FAILURES)
@pytest.mark.parametrize("surface", [
    "read", "outputs", "cards", "binding", "publication", "visibility",
    "history", "file", "cached_file", "download", "factory",
])
def test_configuration_uncertainty_never_returns_cached_public_facts(
    lifecycle, configuration, monkeypatch, code, retryable, surface,
):
    world = lifecycle
    completed = world.run(world.prepare())
    record = world.raw(completed)
    binding = binding_for_intent(record, record["committed_intent"])
    artifact = world.service.transport.message(record, committed=True)
    message = artifact if surface in {"file", "cached_file"} else world.output_history(with_cards=False)
    if surface == "cached_file":
        with world.app.test_request_context():
            message = world.modules.sources.sanitize_generated_artifact_history(message, "owner")
    failure = current_metadata_failure(world, configuration, code)
    if surface == "factory":
        monkeypatch.setattr(importlib.import_module("functions_orchestration_artifacts"), "_service_factory", failure.call)
    else:
        world.service.authorize_execution = failure.call
    before = persistence_snapshot(world)
    original_message = deepcopy(message)
    error_type = (
        configuration.ExternalConfigurationCancelledError
        if code == "output_cancelled" else configuration.ExternalConfigurationServiceError
    )
    with pytest.raises(error_type) as caught:
        if surface == "read":
            world.service.read(completed["output_id"])
        elif surface == "outputs":
            world.service.list_public_outputs("run-1")
        elif surface == "cards":
            world.service.committed_artifacts("run-1")
        elif surface in {"binding", "publication", "factory"}:
            load_orchestration_artifact_binding("owner", binding, for_publication=surface == "publication")
        elif surface == "visibility":
            world.modules.operations.assert_generated_chat_artifact_is_published_for_user("owner", artifact)
        elif surface == "download":
            with world.service.open_download(completed["output_id"]) as stream:
                raise AssertionError("Unverified metadata exposed a download stream.")
        else:
            with world.app.test_request_context():
                world.modules.sources.sanitize_generated_artifact_history(message, "owner")
    after = persistence_snapshot(world)
    assert caught.value is failure.raised[-1]
    assert before == after and message == original_message and not failure.digest.call_count
    assert "PRIVATE" not in str(caught.value)
    if code != "output_cancelled":
        assert caught.value.code == code and caught.value.retryable is retryable


@pytest.mark.parametrize("wrapper", [
    PermissionError, ResultUnavailableError, OutputUnavailableError, DocumentHeldError,
    ScreeningConfigurationError, LookupError, ResultContractError, ResourceNotFoundError, TimeoutError,
    RuntimeError, ValueError, TypeError, AttributeError, OSError,
])
@pytest.mark.parametrize("code,retryable", [
    ("external_configuration_throttled", True),
    ("external_configuration_metadata_invalid", False), ("output_cancelled", False),
])
def test_explicit_configuration_causes_remain_typed(lifecycle, configuration, wrapper, code, retryable):
    world = lifecycle
    completed = world.run(world.prepare())
    failure = current_metadata_failure(world, configuration, code)

    def wrapped(*args, **kwargs):
        try:
            failure.call()
        except (configuration.ExternalConfigurationServiceError, configuration.ExternalConfigurationCancelledError) as exc:
            raise wrapper("private_wrapper") from exc

    world.service.authorize_execution = wrapped
    expected = (
        configuration.ExternalConfigurationCancelledError
        if code == "output_cancelled" else configuration.ExternalConfigurationServiceError
    )
    before = persistence_snapshot(world)
    with pytest.raises(expected) as caught:
        world.service.read(completed["output_id"])
    classification = output_failure(caught.value)
    assert classification == (code, retryable) and caught.value is failure.raised[-1]
    assert before == persistence_snapshot(world)


@pytest.mark.parametrize("code,retryable", ALL_FAILURES)
@pytest.mark.parametrize("boundary", ["factory", "inputs", "authority"])
@pytest.mark.parametrize("saved_kind", ["waiting", "completed"])
def test_configuration_failure_during_resumption_never_mutates_or_echoes_success(
    resumption, configuration, monkeypatch, code, retryable, boundary, saved_kind,
):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    failure = current_metadata_failure(world, configuration, code)
    if boundary == "factory":
        case.service_factory = failure.call
    elif boundary == "inputs":
        case.resolve_inputs = failure.call
    else:
        world.service.authorize_execution = failure.call
    saved = pending_result(case, completed) if saved_kind == "waiting" else completed_result(case, completed)
    forbid_execution(case, monkeypatch)
    original_saved = deepcopy(saved)
    if code == "output_cancelled":
        result = resume(case, saved)
        assert result["status"] == "cancelled" and result["output_error"] == {"code": code, "retryable": False}
        assert result["outputs"] == result["artifacts"] == []
        assert "PRIVATE" not in json.dumps(result)
    else:
        with pytest.raises(configuration.ExternalConfigurationServiceError) as caught:
            resume(case, saved)
        assert caught.value is failure.raised[-1]
        assert caught.value.code == code and caught.value.retryable is retryable
    assert saved == original_saved


@pytest.mark.parametrize("boundary", ["factory", "inputs"])
def test_configuration_cancellation_before_admission_remains_cancelled(resumption, configuration, monkeypatch, boundary):
    case, world = resumption, resumption.world
    failure = current_metadata_failure(world, configuration, "output_cancelled")
    if boundary == "factory":
        case.service_factory = failure.call
    else:
        case.resolve_inputs = failure.call
    forbid_execution(case, monkeypatch)
    result = execute_render_file(
        case.step, case.context, service_factory=case.service_factory, resolve_inputs=case.resolve_inputs,
        build_step_result=world.modules.schema.build_step_result,
        build_failure=world.modules.schema.build_failure, settings={}, user_id="owner",
    )
    assert result["status"] == "cancelled" and result["outputs"] == result["artifacts"] == []
    assert result["output_error"] == {"code": "output_cancelled", "retryable": False}


@pytest.mark.parametrize("code,retryable", ALL_FAILURES)
def test_execute_adapter_withholds_completed_facts_after_configuration_failure(
    resumption, configuration, monkeypatch, code, retryable,
):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    failure = current_metadata_failure(world, configuration, code)
    ensure = world.service.ensure_output

    def admitted_then_unverifiable(**kwargs):
        output = ensure(**kwargs)
        world.service.authorize_execution = failure.call
        return output

    monkeypatch.setattr(world.service, "ensure_output", admitted_then_unverifiable)
    before = persistence_snapshot(world)
    result = execute_render_file(
        case.step, case.context, service_factory=case.service_factory, resolve_inputs=case.resolve_inputs,
        build_step_result=world.modules.schema.build_step_result,
        build_failure=world.modules.schema.build_failure, settings={}, user_id="owner",
    )
    expected = "cancelled" if code == "output_cancelled" else "waiting" if retryable else "failed"
    assert result["status"] == expected and result["output_error"] == {"code": code, "retryable": retryable}
    assert not result.get("outputs") and not result["artifacts"]
    assert completed["artifact_message_id"] not in json.dumps(result) and "PRIVATE" not in json.dumps(result)
    assert before == persistence_snapshot(world)


@pytest.mark.parametrize("state", ["retry_scheduled", "rendering"])
@pytest.mark.parametrize("code", [
    "external_configuration_throttled", "external_configuration_metadata_invalid", "output_cancelled",
])
def test_configuration_failure_during_observation_cannot_spend_an_admission(lifecycle, configuration, state, code):
    world = lifecycle
    output = world.prepare()
    if state == "retry_scheduled":
        world.failures["json"] = [TimeoutError("A transient renderer interruption.")]
        world.run(output)
    else:
        world.service.claim_due(output["output_id"])
    failure = current_metadata_failure(world, configuration, code)
    world.service.authorize_execution = failure.call
    before = persistence_snapshot(world)
    expected = (
        configuration.ExternalConfigurationCancelledError
        if code == "output_cancelled" else configuration.ExternalConfigurationServiceError
    )
    with pytest.raises(expected) as caught:
        world.run(output)
    assert caught.value is failure.raised[-1] and before == persistence_snapshot(world)


@pytest.mark.parametrize("code", [
    "external_configuration_throttled", "external_configuration_metadata_invalid", "output_cancelled",
])
def test_history_factory_preserves_explicit_configuration_failure_causes(lifecycle, configuration, monkeypatch, code):
    world = lifecycle
    world.run(world.prepare())
    message = world.output_history(with_cards=False)
    failure = current_metadata_failure(world, configuration, code)

    def unavailable_factory(*args, **kwargs):
        try:
            failure.call()
        except (configuration.ExternalConfigurationServiceError, configuration.ExternalConfigurationCancelledError) as exc:
            raise TimeoutError("PRIVATE factory wrapper") from exc

    monkeypatch.setattr(
        importlib.import_module("functions_orchestration_artifacts"), "_service_factory", unavailable_factory,
    )
    before = persistence_snapshot(world)
    expected = (
        configuration.ExternalConfigurationCancelledError
        if code == "output_cancelled" else configuration.ExternalConfigurationServiceError
    )
    with world.app.test_request_context(), pytest.raises(expected) as caught:
        world.modules.sources.sanitize_generated_artifact_history(message, "owner")
    assert caught.value is failure.raised[-1] and before == persistence_snapshot(world)


@pytest.mark.parametrize("phase", ["render", "prepare", "commit"])
def test_configuration_cancellation_never_queues_retry(lifecycle, configuration, phase):
    world = lifecycle
    output = world.prepare()
    original = world.service.authorize_execution
    failure = current_metadata_failure(world, configuration, "output_cancelled")
    world.service.authorize_execution = lambda record, *, operation: (
        failure.call() if operation == phase else original(record, operation=operation)
    )
    outcome = world.run(output)
    assert outcome["state"] == "cancelled" and outcome["error_code"] == "output_cancelled"
    assert outcome["automatic_attempts"] == outcome["attempt_count"] == 1 and not outcome["can_retry"]
    assert outcome["artifact_message_id"] is None


@pytest.mark.parametrize("held", [False, True])
def test_genuine_denials_do_not_inherit_implicit_configuration_errors(lifecycle, configuration, held):
    world = lifecycle
    output = world.prepare()

    def denied(*args, **kwargs):
        try:
            raise configuration.ExternalConfigurationServiceError("external_configuration_timeout")
        except configuration.ExternalConfigurationServiceError:
            if held:
                raise DocumentHeldError()
            raise ResultUnavailableError("external_configuration_unavailable")

    world.service.authorize_execution = denied
    outcome = world.run(output)
    assert outcome["state"] == "failed" and outcome["automatic_attempts"] == 1 and not outcome["can_retry"]
    assert outcome["error_code"] == ("output_screening_hold" if held else "output_access_denied")
    assert not world.render_calls and not world.blobs.data


def test_untyped_error_cannot_claim_configuration_retryability():
    error = RuntimeError("An unrelated failure.")
    error.code = "external_configuration_timeout"
    error.retryable = True
    classified = output_failure(error)
    assert classified == ("output_failed", False)
