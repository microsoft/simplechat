# test_orchestration_output_checkpoint_storage.py
"""
Preserve operational checkpoint reads across retained-output boundaries.
Version: 0.261.127
Implemented in: 0.261.127

Actual CheckpointStore reads and safe cause-free CheckpointError values exercise
classification, current visibility, history, downloads and read-only resumption.
External storage is isolated; missing, invalid, denied and fenced proof must not
acquire retryability from arbitrary provider codes or implicit exception context.
"""

import importlib
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cosmos import exceptions

from functions_orchestration_artifacts import binding_for_intent, load_orchestration_artifact_binding
from functions_orchestration_output_store import OutputStorageError, OutputUnavailableError
from functions_orchestration_rendering import output_failure, raise_output_read_infrastructure_failure
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_output_lifecycle import APP, ROOT, TESTS, lifecycle, production_modules  # noqa: F401
from test_orchestration_render_resume import (
    completed_result, forbid_execution, pending_result, persistence_snapshot, resume, resumption,
)


def wrap_failure(module, error, wrapper):
    if wrapper == "direct":
        return error
    factories = {
        "result": ResultUnavailableError,
        "output": OutputUnavailableError,
        "permission": PermissionError,
        "checkpoint": module.CheckpointError,
        "translated": OutputStorageError,
    }
    if wrapper == "nested":
        error = wrap_failure(module, error, "result")
        error = wrap_failure(module, error, "checkpoint")
        return wrap_failure(module, error, "output")
    wrapped = factories[wrapper]()
    wrapped.__cause__ = error
    return wrapped


def checkpoint_failure(*, source="store", wrapper="direct"):
    module = importlib.import_module("functions_orchestration_checkpoints")
    provider = Mock(side_effect=exceptions.CosmosHttpResponseError(
        status_code=503, message="PRIVATE checkpoint provider response",
    ))
    store = module.CheckpointStore(
        SimpleNamespace(read_item=provider), run_id="run-1", user_id="owner",
        conversation_id="conversation-1", turn_id="turn-1", authorize=lambda: True,
        plan_contract_version=2,
    )
    originals = []

    def fail(*args, **kwargs):
        try:
            if source == "cause_free":
                raise module.CheckpointError("checkpoint_storage_unavailable")
            store._read("checkpoint:lifecycle")
        except module.CheckpointError as exc:
            originals.append(exc)
            error = wrap_failure(module, exc, wrapper)
            if error is exc:
                raise
            raise error

    return SimpleNamespace(
        call=fail, provider=provider, originals=originals, module=module, store=store,
    )


@pytest.mark.parametrize("source", ["store", "cause_free"])
@pytest.mark.parametrize("wrapper", [
    "direct", "result", "output", "permission", "checkpoint", "nested", "translated",
])
def test_actual_checkpoint_storage_classification(lifecycle, source, wrapper):
    failure = checkpoint_failure(source=source, wrapper=wrapper)
    with pytest.raises(Exception) as raised:
        failure.call()
    classified = output_failure(raised.value)
    assert classified == ("output_storage_unavailable", True)
    assert failure.originals[0].code == "checkpoint_storage_unavailable"
    with pytest.raises(OutputStorageError) as operational:
        raise_output_read_infrastructure_failure(raised.value)
    assert operational.value.retryable is True and "PRIVATE" not in str(operational.value)
    assert failure.provider.call_count == int(source == "store")


@pytest.mark.parametrize("code", [
    "checkpoint_unavailable", "checkpoint_invalid", "context_unavailable",
    "ownership_lost", "recovery_changed",
])
def test_nonstorage_checkpoint_meanings_do_not_become_retryable(lifecycle, code):
    module = importlib.import_module("functions_orchestration_checkpoints")
    error = module.CheckpointError(code)
    classified = output_failure(error)
    raise_output_read_infrastructure_failure(error)
    assert error.code == code and classified == ("output_failed", False)


@pytest.mark.parametrize("kind", ["missing", "invalid", "denied"])
def test_real_missing_invalid_and_denied_reads_are_not_storage_failures(lifecycle, kind):
    failure = checkpoint_failure()
    if kind == "missing":
        failure.provider.side_effect = exceptions.CosmosResourceNotFoundError()
    elif kind == "invalid":
        failure.provider.side_effect = None
        failure.provider.return_value = {"id": "checkpoint:lifecycle", "user_id": "another-owner"}
    else:
        failure.store.authorize = lambda: False
    with pytest.raises(failure.module.CheckpointError) as raised:
        failure.call()
    classified = output_failure(raised.value)
    raise_output_read_infrastructure_failure(raised.value)
    expected = {
        "missing": "checkpoint_unavailable", "invalid": "checkpoint_invalid", "denied": "context_unavailable",
    }
    assert raised.value.code == expected[kind] and classified[1] is False
    assert failure.provider.call_count == int(kind != "denied")


def test_untrusted_codes_context_and_cycles_do_not_create_storage_uncertainty(lifecycle):
    module = importlib.import_module("functions_orchestration_checkpoints")
    fake_type = type("CheckpointError", (RuntimeError,), {"__module__": module.__name__})
    for error in (RuntimeError("PRIVATE provider"), fake_type("PRIVATE spoofed type")):
        error.code = "checkpoint_storage_unavailable"
        error.retryable = True
        classified = output_failure(error)
        raise_output_read_infrastructure_failure(error)
        assert classified == ("output_failed", False)
    denial = ResultUnavailableError()
    denial.__context__ = module.CheckpointError("checkpoint_storage_unavailable")
    classified = output_failure(denial)
    raise_output_read_infrastructure_failure(denial)
    assert classified == ("output_access_denied", False)
    cycle = module.CheckpointError()
    cycle.__cause__ = cycle
    classified = output_failure(cycle)
    raise_output_read_infrastructure_failure(cycle)
    assert classified == ("output_failed", False)
    opaque = RuntimeError("PRIVATE unrecognized wrapper")
    opaque.__cause__ = module.CheckpointError("checkpoint_storage_unavailable")
    classified = output_failure(opaque)
    assert classified == ("output_failed", False)


@pytest.mark.parametrize("source,wrapper", [
    ("store", "direct"), ("cause_free", "direct"), ("store", "nested"), ("store", "translated"),
])
@pytest.mark.parametrize("surface", [
    "read", "outputs", "cards", "binding", "publication", "visibility", "history", "download", "factory",
])
def test_checkpoint_storage_failure_withholds_all_current_file_projections(
    lifecycle, monkeypatch, source, wrapper, surface,
):
    world = lifecycle
    completed = world.run(world.prepare())
    record = world.raw(completed)
    binding = binding_for_intent(record, record["committed_intent"])
    message = world.service.transport.message(record, committed=True)
    history = world.output_history(with_cards=True)
    failure = checkpoint_failure(source=source, wrapper=wrapper)
    original = world.service.authorize_execution
    if surface == "factory":
        monkeypatch.setattr(
            importlib.import_module("functions_orchestration_artifacts"), "_service_factory", failure.call,
        )
    else:
        world.service.authorize_execution = failure.call
    before = persistence_snapshot(world)
    with pytest.raises(OutputStorageError) as raised:
        if surface == "read":
            world.service.read(completed["output_id"])
        elif surface == "outputs":
            world.service.list_public_outputs("run-1")
        elif surface == "cards":
            world.service.committed_artifacts("run-1")
        elif surface in {"binding", "publication", "factory"}:
            load_orchestration_artifact_binding("owner", binding, for_publication=surface == "publication")
        elif surface == "visibility":
            world.modules.operations.assert_generated_chat_artifact_is_published_for_user("owner", message)
        elif surface == "download":
            with world.service.open_download(completed["output_id"]):
                raise AssertionError("An unverified checkpoint exposed a download stream.")
        else:
            with world.app.test_request_context():
                world.modules.sources.sanitize_generated_artifact_history(history, "owner")
    after = persistence_snapshot(world)
    assert raised.value.code == "output_storage_unavailable" and raised.value.retryable is True
    assert before == after and failure.originals
    assert all(error.code == "checkpoint_storage_unavailable" for error in failure.originals)
    assert "PRIVATE" not in str(raised.value)
    world.service.authorize_execution = original
    restored = world.service.list_public_outputs("run-1")
    assert restored[0]["artifact_message_id"] == completed["artifact_message_id"]
    assert len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("source,wrapper", [("cause_free", "direct"), ("store", "nested")])
@pytest.mark.parametrize("boundary", ["factory", "inputs", "authority"])
@pytest.mark.parametrize("saved_kind", ["waiting", "completed"])
def test_checkpoint_read_failure_cannot_replace_a_saved_render_result(
    resumption, monkeypatch, source, wrapper, boundary, saved_kind,
):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    saved = pending_result(case, completed) if saved_kind == "waiting" else completed_result(case, completed)
    original_saved = deepcopy(saved)
    failure = checkpoint_failure(source=source, wrapper=wrapper)
    if boundary == "factory":
        case.service_factory = failure.call
    elif boundary == "inputs":
        case.resolve_inputs = failure.call
    else:
        world.service.authorize_execution = failure.call
    forbid_execution(case, monkeypatch)
    with pytest.raises(OutputStorageError) as raised:
        resume(case, saved)
    assert saved == original_saved and raised.value.retryable is True and failure.originals


@pytest.mark.parametrize("source", ["store", "cause_free"])
@pytest.mark.parametrize("phase", ["render", "commit"])
def test_checkpoint_storage_retries_keep_the_original_persistent_budget(lifecycle, source, phase):
    world = lifecycle
    output = world.prepare()
    failure = checkpoint_failure(source=source, wrapper="nested")
    original = world.service.authorize_execution
    unavailable = False

    def authorize(record, *, operation):
        nonlocal unavailable
        unavailable = unavailable or operation == phase
        return failure.call() if unavailable else original(record, operation=operation)

    world.service.authorize_execution = authorize
    for attempt in range(1, 4):
        outcome = world.run(output)
        stored = world.raw(output)
        assert outcome["error_code"] == "output_storage_unavailable" and stored["retryable"] is True
        assert outcome["artifact_message_id"] is None
        if attempt < 3:
            assert outcome["state"] == "retry_scheduled" and outcome["automatic_attempts"] == attempt + 1
            world.advance_due(outcome)
        else:
            assert outcome["state"] == "failed" and outcome["can_retry"] is True
    before = persistence_snapshot(world)
    with pytest.raises(OutputStorageError):
        world.run(output)
    after = persistence_snapshot(world)
    assert before == after and outcome["automatic_attempts"] == outcome["attempt_count"] == 3
    assert world.results.container.sequence == world.producer_writes


_CHECKPOINT_IMPORT_PROBE = r"""
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports():
    modules = {name: importlib.import_module(name) for name in sys.argv[3:]}
    rendering = modules["functions_orchestration_rendering"]
    checkpoints = modules["functions_orchestration_checkpoints"]
    outputs = importlib.import_module("functions_orchestration_output_store")
    results = importlib.import_module("functions_orchestration_results")
    for original in (checkpoints.CheckpointError("checkpoint_storage_unavailable"), outputs.OutputStorageError()):
        wrapped = results.ResultUnavailableError()
        wrapped.__cause__ = original
        nested = checkpoints.CheckpointError()
        nested.__cause__ = wrapped
        for candidate in (original, wrapped, nested):
            classified = rendering.output_failure(candidate)
            if classified != ("output_storage_unavailable", True):
                raise AssertionError(("Incorrect storage classification", classified))
            try:
                rendering.raise_output_read_infrastructure_failure(candidate)
            except outputs.OutputStorageError as error:
                if error.retryable is not True:
                    raise AssertionError("Storage retryability was lost.")
            else:
                raise AssertionError("An operational checkpoint read was suppressed.")
print("PASS: actual checkpoint output classifiers")
"""


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("checkpoint_first", [False, True])
def test_checkpoint_classifiers_in_a_fresh_offline_process(optimized, checkpoint_first):
    modules = ["functions_orchestration_rendering", "functions_orchestration_checkpoints"]
    if checkpoint_first:
        modules.reverse()
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    completed = subprocess.run(
        command + ["-c", _CHECKPOINT_IMPORT_PROBE, str(APP), str(TESTS), *modules],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stdout[-6000:] + completed.stderr[-6000:]
    assert "PASS: actual checkpoint output classifiers" in completed.stdout
