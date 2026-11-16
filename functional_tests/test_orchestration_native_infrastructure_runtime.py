# test_orchestration_native_infrastructure_runtime.py
"""Native service failures must survive the dependency executor's outer catches.

Version: 0.261.127
Implemented in: 0.261.127

Real native jobs, result retention, same-attempt claims and checkpoint restoration
run with existing external-I/O doubles. Operational uncertainty never clears an
original wait or becomes permission to submit another computation.
"""

from copy import deepcopy
import importlib
import json
import sys

import pytest

from functions_orchestration_output_store import OutputStorageError
from functions_orchestration_result_contracts import TaskResult
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_dependency_native_runtime import prepare, run
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_orchestration_native_infrastructure_failures import (
    authorization_wrapper, infrastructure_error,
)
from test_orchestration_native_results import bridge_runtime, commits, transformation_spec
from test_support.orchestration_harness_execution import native_step
from test_support.orchestration_research import document_action_policy_module


def execute_claim(harness, execution):
    try:
        return harness.run_engine(execution)
    finally:
        execution.close()


def start_native_wait(harness):
    harness.settings.update({
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 1,
    })
    harness.create(
        [native_step()],
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
    )
    execution = harness.prepare()
    token = execution.lease.token
    result = execute_claim(harness, execution)
    if result["status"] != "waiting":
        raise AssertionError("The original native job must be waiting before I/O fails.")
    return harness.read(), token


def forbid_native_resubmission(native, monkeypatch):
    bridge = importlib.import_module("functions_orchestration_native_results")

    def forbidden(*args, **kwargs):
        raise AssertionError("A saved native wait must not rebuild or resubmit its computation.")

    monkeypatch.setattr(bridge.NativeOrchestrationBridge, "execute", forbidden)
    monkeypatch.setattr(bridge, "build_native_orchestration_request", forbidden)
    monkeypatch.setattr(native.native, "build_native_tabular_compute_callback", forbidden)


@pytest.mark.parametrize("kind", ["timeout", "azure", "result_storage"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_initial_native_retention_outage_escapes_dependency_failure_conversion(
    monkeypatch, kind, wrapped,
):
    monkeypatch.setitem(sys.modules, "functions_document_actions", document_action_policy_module())
    with bridge_runtime(monkeypatch) as runtime:
        prepare(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        cause = infrastructure_error(kind)
        runtime.blobs.upload_error = authorization_wrapper(cause) if wrapped else cause
        with pytest.raises(OutputStorageError) as raised:
            run(runtime)
        retained = commits(runtime)
        assert raised.value.retryable is True and "PRIVATE" not in str(raised.value)
        assert retained == [] and runtime.context.task_results == {}
        assert runtime.context.failures == [] and not runtime.context._failed_result_step_ids
        assert runtime.native.jobs.created == 1 and runtime.blobs.uploads
        assert runtime.native.publications == [] and runtime.provider.calls == []


@pytest.mark.parametrize("boundary", ["poll", "retention"])
@pytest.mark.parametrize("kind", ["timeout", "azure", "result_storage"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_native_wait_survives_transport_failure_and_finishes_the_original_job(
    harness, monkeypatch, boundary, kind, wrapped,
):
    with harness.native_io() as native:
        original, token = start_native_wait(harness)
        forbid_native_resubmission(native, monkeypatch)
        wait = original["pending_results"]["compute"]
        job_id = wait["handle"]["job_id"]
        if boundary == "retention":
            native.engine.process_tabular_generated_output_run(job_id, "owner")
        before_jobs = deepcopy(native.jobs.items)
        continuation = harness.continue_waiting("unavailable-native-io")
        claimed = continuation.lease.read()
        cause = infrastructure_error(kind)
        failure = authorization_wrapper(cause) if wrapped else cause
        polls = []

        def unavailable(*args, **kwargs):
            polls.append((args, kwargs))
            raise failure

        with monkeypatch.context() as fault:
            if boundary == "poll":
                fault.setattr(native.jobs, "read_item", unavailable)
            else:
                fault.setattr(harness.blobs, "upload_error", failure)
            with pytest.raises(OutputStorageError) as raised:
                execute_claim(harness, continuation)
        saved = harness.read()
        assert raised.value.retryable is True and "PRIVATE" not in str(raised.value)
        assert saved["pending_results"] == original["pending_results"]
        assert saved["task_results"] == original["task_results"]
        assert saved["execution_deadline_at"] == original["execution_deadline_at"]
        assert saved["attempt_index"] == original["attempt_index"]
        assert saved["status"] == claimed["status"] == "running" and not saved.get("failure")
        assert continuation.lease.token == token and continuation.lease.stopped.is_set()
        assert native.jobs.items == before_jobs and native.jobs.created == 1
        assert continuation.context.pending_results == original["pending_results"]
        assert continuation.context.task_results["compute"].status == "pending"
        if boundary == "poll":
            assert len(polls) == 1
            pending = execute_claim(harness, harness.continue_waiting("native-still-pending"))
            assert pending["status"] == "waiting" and pending["pending_results"]["compute"] == wait
            native.engine.process_tabular_generated_output_run(job_id, "owner")

        completed = execute_claim(harness, harness.continue_waiting("native-recovered"))
        service = harness.services()
        task = TaskResult.from_dict(completed["task_results"]["compute"])
        rows = list(service.results.open_result(task.output("records")).iter_records())
        messages = harness.assistant_messages()
        assert completed["status"] == "completed" and completed["pending_results"] == {}
        assert task.producer.to_dict() == original["task_results"]["compute"]["producer"]
        assert completed["execution_deadline_at"] == original["execution_deadline_at"]
        assert rows == [
            {"Item_ID": f"item-{index:06}", "doubled": index * 2} for index in range(1, 38)
        ]
        assert native.jobs.created == 1 and harness.model_calls == []
        assert harness.blobs.file_uploads == 0 and messages == []
        assert "PRIVATE" not in json.dumps([saved, completed])


@pytest.mark.parametrize("wrapped", [False, True])
def test_saved_native_source_configuration_error_is_not_terminal_denial(harness, monkeypatch, wrapped):
    with harness.native_io() as native:
        original, token = start_native_wait(harness)
        forbid_native_resubmission(native, monkeypatch)
        continuation = harness.continue_waiting("source-reader-unavailable")
        claimed = continuation.lease.read()
        cause = infrastructure_error("source_reader")
        failure = authorization_wrapper(cause) if wrapped else cause

        def unavailable(**kwargs):
            raise failure

        with monkeypatch.context() as fault:
            fault.setattr(continuation.services.results.access, "source_metadata_reader", unavailable)
            with pytest.raises(ResultUnavailableError) as raised:
                execute_claim(harness, continuation)
        saved = harness.read()
        assert raised.value is cause and raised.value.code == "result_source_reader_required"
        assert saved["pending_results"] == original["pending_results"]
        assert saved["task_results"] == original["task_results"]
        assert saved["execution_deadline_at"] == original["execution_deadline_at"]
        assert saved["status"] == claimed["status"] == "running" and not saved.get("failure")
        assert continuation.lease.token == token and native.jobs.created == 1
        assert continuation.context.task_results["compute"].status == "pending"
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("boundary", ["poll", "retention"])
def test_scheduler_preserves_native_wait_and_recovers_after_actual_transport_outage(
    harness, monkeypatch, boundary,
):
    # The scheduler fixture module imports its owners after offline application initialization.
    from test_orchestration_harness_scheduler import tick

    with harness.native_io() as native:
        original, _ = start_native_wait(harness)
        forbid_native_resubmission(native, monkeypatch)
        wait = original["pending_results"]["compute"]
        job_id = wait["handle"]["job_id"]
        if boundary == "retention":
            native.engine.process_tabular_generated_output_run(job_id, "owner")
        failure = authorization_wrapper(infrastructure_error("azure"))

        def unavailable(*args, **kwargs):
            raise failure

        with monkeypatch.context() as fault:
            if boundary == "poll":
                fault.setattr(native.jobs, "read_item", unavailable)
            else:
                fault.setattr(harness.blobs, "upload_error", failure)
            outcome, _, logs = tick(harness, max_outputs=0)
        saved = harness.read()
        messages = harness.assistant_messages()
        assert outcome["ok"] is False and len(outcome["errors"]) == 1, outcome
        assert outcome["errors"][0]["code"] == "message_not_saved"
        assert outcome["errors"][0]["retryable"] is True
        assert saved["task_results"] == original["task_results"]
        assert saved["pending_results"] == original["pending_results"]
        assert saved["execution_deadline_at"] == original["execution_deadline_at"]
        assert saved["status"] == "running" and not saved.get("failure")
        assert saved["execution_lease"] is None and messages == []
        assert native.jobs.created == 1 and harness.model_calls == []
        assert "PRIVATE" not in json.dumps([saved, outcome, logs])

        if boundary == "poll":
            native.engine.process_tabular_generated_output_run(job_id, "owner")
        recovered, _, _ = tick(harness, max_outputs=0)
        ready = harness.read()
        assert recovered["ok"] is True and recovered["errors"] == [], recovered
        assert ready["status"] == "completed" and ready["message_saved"] is True
        assert ready["pending_results"] == {}
        assert ready["task_results"]["compute"]["producer"] == original["task_results"]["compute"]["producer"]
        assert ready["attempt_index"] == original["attempt_index"]
        assert ready["execution_deadline_at"] == original["execution_deadline_at"]
        assert native.jobs.created == 1 and harness.model_calls == []
        assert harness.blobs.file_uploads == 0
