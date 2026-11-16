# test_orchestration_native_infrastructure_failures.py
"""
Native bridge infrastructure failures remain exceptions, never terminal denial.
Version: 0.261.127
Implemented in: 0.261.127

The production request builder, native job/reader, retained store and bridge run
for real. Only external I/O fails; no provider or generated-file work is allowed.
"""

from copy import deepcopy
from dataclasses import replace
import importlib
import json
from pathlib import Path
import subprocess
import sys

from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

# Application imports follow the standalone path bootstrap.
from content_screening.contracts import (
    DocumentHeldError, ScreeningConfigurationError, ScreeningError,
    SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError,
)
from functions_analysis_access import AnalysisResultUnavailable
from functions_orchestration_checkpoints import CheckpointError
from functions_orchestration_output_store import OutputError, OutputStorageError
from functions_orchestration_results import ResultUnavailableError
from functions_workflow_result_store import (
    AnalysisWorkUnitConflictError, WorkflowResultIntegrityError,
    WorkflowResultStorageUnavailableError, WorkflowResultTooLargeError,
)
from test_orchestration_native_results import (
    USER, bind_checkpoint_fingerprint, bridge_runtime, commits, execute,
    finish_native, resume, transformation_spec, use_production_builder,
)


def infrastructure_error(kind):
    constructors = {
        "timeout": lambda: TimeoutError("PRIVATE native storage endpoint"),
        "connection": lambda: ConnectionError("PRIVATE native connection"),
        "azure": lambda: ServiceRequestError("PRIVATE Azure request"),
        "cosmos": lambda: CosmosHttpResponseError(status_code=503, message="PRIVATE Cosmos service"),
        "storage": OutputStorageError,
        "checkpoint_storage": lambda: CheckpointError("checkpoint_storage_unavailable"),
        "result_storage": lambda: WorkflowResultStorageUnavailableError("PRIVATE required result backend"),
        "screening": lambda: ScreeningError("PRIVATE screening service"),
        "configuration": lambda: ScreeningConfigurationError("PRIVATE screening configuration"),
        "authority": SourceAuthorityUnavailableError,
        "unverified": SourceAuthorityUnverifiedError,
        "source_reader": lambda: ResultUnavailableError("result_source_reader_required"),
        "output_configuration": lambda: OutputError("output_source_configuration_invalid"),
    }
    return constructors[kind]()


def authorization_wrapper(error):
    wrapper = AnalysisResultUnavailable("native_compute_producer_unavailable")
    wrapper.__cause__ = error
    return wrapper


def prepare_wait(runtime):
    runtime.native.settings["tabular_generated_output_inline_max_rows"] = 1
    use_production_builder(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
    bind_checkpoint_fingerprint(runtime)
    pending = execute(runtime)
    if pending["status"] != "waiting":
        raise AssertionError("The real native job must be waiting before fault injection.")
    runtime.context.task_results = {"compute": pending["task_result"]}
    runtime.context.pending_results = {"compute": deepcopy(pending["wait"])}
    runtime.context.execution_deadline_at = "2099-01-01T00:00:00+00:00"

    def forbidden(*args, **kwargs):
        raise AssertionError("Native continuation must not plan, select a model or submit work.")

    runtime.bound = replace(runtime.bound, request_builder=forbidden, model_resolver=forbidden)
    runtime.native.patcher.setattr(runtime.native.service, "build_native_tabular_compute_callback", forbidden)
    return pending


def continuation_state(runtime, pending):
    return deepcopy({
        "pending": pending,
        "tasks": runtime.context.task_results,
        "waits": runtime.context.pending_results,
        "guard": runtime.state["guard"],
        "deadline": runtime.context.execution_deadline_at,
        "jobs": runtime.native.jobs.items,
        "parent": runtime.native.parents.items,
    })


def read_complete_rows(runtime, result):
    reader = runtime.context.result_service.open_result(result["task_result"].output("records"))
    return list(reader.iter_records())


@pytest.mark.parametrize("kind", ["timeout", "azure", "cosmos", "result_storage"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_actual_pending_poll_transport_failure_preserves_original_wait(monkeypatch, kind, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        pending = prepare_wait(runtime)
        before = continuation_state(runtime, pending)
        private_before = deepcopy(runtime.container.items)
        cause = infrastructure_error(kind)
        failure = authorization_wrapper(cause) if wrapped else cause
        polls = []

        def unavailable(item, partition_key):
            polls.append((item, partition_key))
            raise failure

        with monkeypatch.context() as fault:
            fault.setattr(runtime.native.jobs, "read_item", unavailable)
            with pytest.raises(OutputStorageError) as raised:
                resume(runtime, pending)
        after = continuation_state(runtime, pending)
        retained = commits(runtime)
        refreshed = resume(runtime, pending)
        assert after == before and runtime.container.items == private_before and retained == []
        assert polls == [(pending["wait"]["handle"]["job_id"], USER)]
        assert refreshed["status"] == "waiting" and refreshed["wait"] == pending["wait"]
        assert refreshed["task_result"] == pending["task_result"]
        assert raised.value.retryable is True and "PRIVATE" not in str(raised.value)
        assert runtime.native.jobs.created == 1 and runtime.native.publications == []
        assert runtime.provider.calls == []


@pytest.mark.parametrize("kind", ["connection", "azure", "storage", "result_storage"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_actual_retention_transport_failure_can_retain_original_job_after_recovery(monkeypatch, kind, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        pending = prepare_wait(runtime)
        finish_native(runtime, pending)
        before = continuation_state(runtime, pending)
        cause = infrastructure_error(kind)
        failure = authorization_wrapper(cause) if wrapped else cause
        with monkeypatch.context() as fault:
            fault.setattr(runtime.blobs, "upload_error", failure)
            with pytest.raises(OutputStorageError):
                resume(runtime, pending)
        after = continuation_state(runtime, pending)
        retained = commits(runtime)
        assert after == before and retained == [] and runtime.blobs.uploads
        assert runtime.native.jobs.created == 1 and runtime.native.publications == []

        completed = resume(runtime, pending)
        rows = read_complete_rows(runtime, completed)
        assert completed["status"] == "completed" and completed["task_result"].producer == pending["task_result"].producer
        assert rows == [{"Item_ID": f"item-{index:06}", "doubled": index * 2} for index in range(1, 38)]
        assert runtime.native.jobs.created == 1 and runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("kind", ["timeout", "result_storage"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_foreground_retention_preserves_transport_failure_instead_of_failed_dto(monkeypatch, kind, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        use_production_builder(
            runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec(),
        )
        cause = infrastructure_error(kind)
        runtime.blobs.upload_error = authorization_wrapper(cause) if wrapped else cause
        with pytest.raises(OutputStorageError):
            execute(runtime)
        retained = commits(runtime)
        native_runs = list(runtime.native.jobs.items.values())
        assert retained == [] and runtime.blobs.uploads
        assert runtime.native.jobs.created == len(native_runs) == 1
        assert native_runs[0]["status"] == "completed" and native_runs[0]["computation_state"] == "complete"
        assert native_runs[0]["execution_policy"] == "data_only" and "artifact_set_manifest" not in native_runs[0]
        assert runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("kind", ["screening", "configuration", "authority", "unverified"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_current_authority_error_preserves_identity_public_contract_and_pending_state(monkeypatch, kind, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        pending = prepare_wait(runtime)
        before = continuation_state(runtime, pending)
        cause = infrastructure_error(kind)
        failure = authorization_wrapper(cause) if wrapped else cause
        calls = []

        def unavailable(**kwargs):
            calls.append(kwargs["document_id"])
            raise failure

        with monkeypatch.context() as fault:
            fault.setattr(runtime.service.access, "source_metadata_reader", unavailable)
            with pytest.raises(type(cause)) as raised:
                resume(runtime, pending)
        after = continuation_state(runtime, pending)
        assert raised.value is cause and after == before and calls == ["source-1"]
        public = {"code": raised.value.code, "message": raised.value.public_message, "retryable": raised.value.retryable}
        assert "PRIVATE" not in json.dumps(public) and runtime.native.publications == []


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("wrapped", [False, True])
def test_receipt_transport_uncertainty_is_not_absence_or_replacement(monkeypatch, committed, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        pending = prepare_wait(runtime)
        finish_native(runtime, pending)
        if committed:
            original = resume(runtime, pending)
        before = continuation_state(runtime, pending)
        stored = deepcopy(runtime.container.items), deepcopy(runtime.blobs.records)
        cause = TimeoutError("PRIVATE receipt backing store")
        failure = authorization_wrapper(cause) if wrapped else cause
        reads = []

        def unavailable(*, item, partition_key):
            reads.append((partition_key, item))
            raise failure

        with monkeypatch.context() as fault:
            fault.setattr(runtime.container, "read_item", unavailable)
            with pytest.raises(OutputStorageError):
                resume(runtime, pending)
        after = continuation_state(runtime, pending)
        assert reads and after == before and (runtime.container.items, runtime.blobs.records) == stored
        completed = resume(runtime, pending)
        if committed:
            assert completed["task_result"] == original["task_result"]
        rows = read_complete_rows(runtime, completed)
        assert len(rows) == 37 and rows[-1]["doubled"] == 74
        assert runtime.native.jobs.created == 1 and runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("kind", [
    "timeout", "connection", "azure", "cosmos", "storage", "checkpoint_storage",
    "result_storage", "screening", "configuration", "authority", "unverified",
    "source_reader", "output_configuration",
])
@pytest.mark.parametrize("wrapped", [False, True])
def test_shared_native_error_seam_accepts_only_recognized_infrastructure(kind, wrapped):
    bridge = importlib.import_module("functions_orchestration_native_results")
    cause = infrastructure_error(kind)
    failure = authorization_wrapper(cause) if wrapped else cause
    expected = OutputStorageError if kind in {
        "timeout", "connection", "azure", "cosmos", "storage", "checkpoint_storage", "result_storage",
    } else type(cause)
    with pytest.raises(expected) as raised:
        bridge.raise_native_orchestration_infrastructure_failure(failure)
    if expected is not OutputStorageError or kind == "storage":
        assert raised.value is cause


@pytest.mark.parametrize("family", ["identity", "configuration"])
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("wrapped", [False, True])
def test_external_authority_services_and_control_signals_retain_their_real_types(family, cancelled, wrapped):
    bridge = importlib.import_module("functions_orchestration_native_results")
    authority = importlib.import_module(f"functions_orchestration_external_{family}")
    error_name = f"External{family.title()}{'Cancelled' if cancelled else 'Service'}Error"
    cause = getattr(authority, error_name)()
    failure = authorization_wrapper(cause) if wrapped else cause
    with pytest.raises(type(cause)) as raised:
        bridge.raise_native_orchestration_infrastructure_failure(failure)
    assert raised.value is cause and raised.value.code == cause.code
    if not cancelled:
        assert raised.value.retryable is cause.retryable


@pytest.mark.parametrize("kind", [
    "permission", "held", "missing", "azure_missing", "cosmos_missing",
    "validation", "type", "integrity", "size", "ownership", "unknown",
])
@pytest.mark.parametrize("wrapped", [False, True])
def test_true_denial_validation_and_unknown_causes_keep_safe_failed_diagnostics(monkeypatch, kind, wrapped):
    constructors = {
        "permission": lambda: PermissionError("PRIVATE genuine denial"),
        "held": DocumentHeldError,
        "missing": lambda: LookupError("PRIVATE missing source"),
        "azure_missing": lambda: ResourceNotFoundError("PRIVATE missing blob"),
        "cosmos_missing": lambda: CosmosResourceNotFoundError(status_code=404, message="PRIVATE missing job"),
        "validation": lambda: ValueError("PRIVATE invalid calculation"),
        "type": lambda: TypeError("PRIVATE invalid field"),
        "integrity": lambda: WorkflowResultIntegrityError("PRIVATE corrupt result"),
        "size": lambda: WorkflowResultTooLargeError("PRIVATE size limit"),
        "ownership": AnalysisWorkUnitConflictError,
        "unknown": lambda: RuntimeError("PRIVATE unknown engine failure"),
    }
    with bridge_runtime(monkeypatch) as runtime:
        cause = constructors[kind]()
        failure = authorization_wrapper(cause) if wrapped else cause

        def invalid(*args, **kwargs):
            raise failure

        runtime.bound = replace(runtime.bound, request_builder=invalid)
        result = execute(runtime)
        assert result["status"] == "failed" and result["failure"]["retryable"] is False
        assert "task_result" not in result and "wait" not in result and "PRIVATE" not in json.dumps(result)
        assert runtime.native.jobs.created == 0 and runtime.native.publications == []


def test_unknown_validation_wrapper_cannot_hide_known_inner_storage_failure():
    bridge = importlib.import_module("functions_orchestration_native_results")
    failure = authorization_wrapper(ValueError("PRIVATE outer validation"))
    failure.__cause__.__cause__ = TimeoutError("PRIVATE actual backing-store failure")
    with pytest.raises(OutputStorageError):
        bridge.raise_native_orchestration_infrastructure_failure(failure)


def test_cyclic_ordinary_cause_chain_is_not_infrastructure():
    bridge = importlib.import_module("functions_orchestration_native_results")
    failure = authorization_wrapper(ValueError("PRIVATE cyclic validation"))
    failure.__cause__.__cause__ = failure
    result = bridge.raise_native_orchestration_infrastructure_failure(failure)
    assert result is None


@pytest.mark.parametrize("optimized", [False, True])
def test_native_error_classifier_is_lazy_and_preserves_explicit_optimized_operations(optimized):
    script = """
import builtins, importlib, socket, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
def blocked(*args, **kwargs):
    raise RuntimeError('Network is forbidden in native error tests.')
socket.socket.connect = blocked
socket.create_connection = blocked
real_import = builtins.__import__
def metadata_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name == 'functions_orchestration_rendering':
        raise RuntimeError('Native metadata eagerly imported the renderer.')
    return real_import(name, globals, locals, fromlist, level)
with patch.object(builtins, '__import__', metadata_import):
    bridge = importlib.import_module('functions_orchestration_native_results')
    bridge.native_orchestration_arguments_schema()
    bridge.native_orchestration_output_specs('transform')
from functions_orchestration_output_store import OutputStorageError
failure = PermissionError('Private outer authorization wrapper')
failure.__cause__ = TimeoutError('Private backing store')
try:
    bridge.raise_native_orchestration_infrastructure_failure(failure)
except OutputStorageError as error:
    if error.retryable is not True or 'Private' in str(error):
        raise RuntimeError('Storage failure contract changed.')
else:
    raise RuntimeError('Native infrastructure was flattened.')
for family in ('identity', 'configuration'):
    authority = importlib.import_module('functions_orchestration_external_' + family)
    for suffix in ('Service', 'Cancelled'):
        error_type = getattr(authority, 'External' + family.title() + suffix + 'Error')
        cause = error_type()
        wrapper = PermissionError('Private authorization wrapper')
        wrapper.__cause__ = cause
        try:
            bridge.raise_native_orchestration_infrastructure_failure(wrapper)
        except error_type as error:
            if error is not cause:
                raise RuntimeError('Authority or control identity changed.')
        else:
            raise RuntimeError('An external authority or control error was flattened.')
ordinary = PermissionError('Denied')
ordinary.__cause__ = ValueError('Invalid')
bridge.raise_native_orchestration_infrastructure_failure(ordinary)
if 'config' in sys.modules or 'route_backend_chats' in sys.modules:
    raise RuntimeError('Native error handling initialized application owners.')
"""
    completed = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", script, str(APP)],
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
