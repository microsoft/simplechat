# test_orchestration_native_adapter.py
"""
Functional tests for server-owned v2 native adapter dispatch.
Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139

The real adapter delegates to the real native bridge, producer and result store.
External I/O is doubled; legacy publication paths must never run for v2 work.
Infrastructure failures remain exceptions rather than terminal failed results.
"""

from copy import deepcopy
import importlib
import json
from unittest.mock import Mock

import pytest

from test_orchestration_native_results import (
    USER, OrchestrationResults, WorkflowResultStore, bridge_runtime, commits,
    finish_native, transformation_spec, use_production_builder,
)
from test_orchestration_native_infrastructure_failures import authorization_wrapper, infrastructure_error
from functions_orchestration_execution_policy import require_generated_file_publication_allowed
from functions_orchestration_output_store import OutputStorageError


@pytest.fixture
def adapters(monkeypatch):
    module = importlib.import_module("functions_orchestration_adapters")
    legacy = Mock(side_effect=AssertionError("V2 must not enter the legacy tabular path."))
    monkeypatch.setattr(module, "_resolve_step_document_ids", legacy)
    monkeypatch.setattr(module, "_prepare_step_analysis_checkpoints", legacy)
    monkeypatch.setattr(module, "resolve_context_source_manifest", legacy)
    monkeypatch.setattr(module, "log_event", Mock())
    return module, legacy


def bind_adapter(runtime, **arguments):
    runtime.step["capability_id"] = "tabular_analyze"
    use_production_builder(runtime, **arguments)
    factory = Mock(return_value=runtime.bound)
    runtime.context.native_bridge_for_step = factory
    return factory


def execute_adapter(adapters, runtime, **kwargs):
    return adapters[0].run_tabular_analyze(
        runtime.step, runtime.context, settings=runtime.native.settings,
        user_id=USER, emit=None, cancel_requested=kwargs.get("cancel_requested"),
    )


@pytest.mark.parametrize("operation,task_type,names", [
    ("query", None, {"records", "coverage"}),
    ("transform", None, {"records", "coverage"}),
    ("analysis", None, {"analysis", "coverage"}),
    ("transform", "combined", {"records", "analysis", "coverage"}),
])
def test_adapter_retains_actual_native_mode_outputs_and_last_record(
    adapters, monkeypatch, operation, task_type, names,
):
    with bridge_runtime(monkeypatch, operation=operation, task_type=task_type) as runtime:
        arguments = {}
        if operation == "query":
            arguments.update(columns=["Item_ID", "amount"], query_expression="amount >= 36")
        elif operation == "transform":
            arguments.update(columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        if task_type:
            arguments["task_type"] = task_type
        factory = bind_adapter(runtime, **arguments)
        result = execute_adapter(adapters, runtime)
        if result["status"] == "waiting":
            finish_native(runtime, result)
            result = runtime.bound.resume(
                runtime.step, runtime.context, result, settings=runtime.native.settings, user_id=USER,
            )
        assert result["status"] == "completed", result
        task = result["task_result"]
        expected_producer = runtime.context.result_producer(runtime.step)
        assert task.producer == expected_producer
        assert task.producer.contract_version == "native-tabular-result-v1"
        assert {reference.output_name for reference in task.outputs} == names
        restarted = OrchestrationResults(
            WorkflowResultStore(runtime.container, runtime.blobs, "private-results", max_size_bytes=32 * 1024 * 1024),
            runtime.service.access,
        )
        if "records" in names:
            rows = list(restarted.open_result(task.output("records")).iter_records())
            assert len(rows) == (2 if operation == "query" else 37)
            assert rows[-1]["Item_ID"] == "item-000037"
        if "analysis" in names:
            analysis = restarted.open_result(task.output("analysis")).read_value()
            assert analysis["counts"]["sum"] == 703
        factory.assert_called_once_with(runtime.step, runtime.context)
        adapters[1].assert_not_called()
        assert runtime.native.publications == [] and result["artifacts"] == []


def test_adapter_preserves_actual_wait_result_without_resubmission(adapters, monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.native.settings["tabular_generated_output_inline_max_rows"] = 1
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        observed = []
        execute = runtime.module.NativeOrchestrationBridge.execute

        def track_execute(binding, *args, **kwargs):
            result = execute(binding, *args, **kwargs)
            observed.append(result)
            return result

        monkeypatch.setattr(runtime.module.NativeOrchestrationBridge, "execute", track_execute)
        result = execute_adapter(adapters, runtime)
        assert result is observed[0]
        assert result["status"] == "waiting"
        assert result["task_result"].status == "pending" and result["task_result"].outputs == ()
        assert set(result["wait"]) == {"kind", "handle"}
        assert result["wait"]["kind"] == "native_tabular_compute"
        assert set(result["wait"]["handle"]) == {"version", "job_id", "request_fingerprint"}
        assert runtime.native.jobs.created == 1
        factory.assert_called_once_with(runtime.step, runtime.context)
        adapters[1].assert_not_called()
        assert runtime.native.publications == []


@pytest.mark.parametrize("fault", ["missing", "noncallable", "invalid_bridge", "raises"])
def test_unbound_native_adapter_fails_before_any_legacy_or_native_work(adapters, monkeypatch, fault):
    with bridge_runtime(monkeypatch) as runtime:
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        if fault == "missing":
            del runtime.context.native_bridge_for_step
        elif fault == "noncallable":
            runtime.context.native_bridge_for_step = True
        elif fault == "invalid_bridge":
            factory.return_value = {"execute": "not-a-server-bridge"}
        else:
            factory.side_effect = RuntimeError("PRIVATE_BINDING_FAILURE")
        result = execute_adapter(adapters, runtime)
        assert result["status"] == "failed"
        assert "PRIVATE_BINDING_FAILURE" not in json.dumps(result)
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []
        assert runtime.provider.calls == [] and runtime.native.publications == []
        adapters[1].assert_not_called()


@pytest.mark.parametrize("kind", ["timeout", "storage", "result_storage", "screening", "authority"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_native_factory_infrastructure_failure_is_not_a_terminal_result(adapters, monkeypatch, kind, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        before = deepcopy(runtime.container.items)
        cause = infrastructure_error(kind)
        factory.side_effect = authorization_wrapper(cause) if wrapped else cause
        expected_type = type(cause) if kind in {"screening", "authority"} else OutputStorageError
        with pytest.raises(expected_type) as caught:
            execute_adapter(adapters, runtime)
        if kind in {"screening", "authority"}:
            assert caught.value is cause
        else:
            assert caught.value.retryable is True and "PRIVATE" not in str(caught.value)
        factory.assert_called_once_with(runtime.step, runtime.context)
        adapters[1].assert_not_called()
        assert runtime.container.items == before
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []
        assert runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("kind", ["timeout", "result_storage"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_native_adapter_foreground_retention_failure_remains_operational(adapters, monkeypatch, kind, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        cause = infrastructure_error(kind)
        runtime.blobs.upload_error = authorization_wrapper(cause) if wrapped else cause
        with pytest.raises(OutputStorageError) as caught:
            execute_adapter(adapters, runtime)
        retained = commits(runtime)
        native_runs = list(runtime.native.jobs.items.values())
        assert caught.value.retryable is True and "PRIVATE" not in str(caught.value)
        assert retained == [] and runtime.blobs.uploads
        assert runtime.native.jobs.created == len(native_runs) == 1
        assert native_runs[0]["status"] == "completed" and native_runs[0]["computation_state"] == "complete"
        assert native_runs[0]["execution_policy"] == "data_only" and "artifact_set_manifest" not in native_runs[0]
        factory.assert_called_once_with(runtime.step, runtime.context)
        adapters[1].assert_not_called()
        assert runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("error_type", [ValueError, PermissionError])
@pytest.mark.parametrize("wrapped", [False, True])
def test_native_factory_validation_and_denial_keep_safe_terminal_results(adapters, monkeypatch, error_type, wrapped):
    with bridge_runtime(monkeypatch) as runtime:
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        cause = error_type("PRIVATE native binding details")
        factory.side_effect = authorization_wrapper(cause) if wrapped else cause
        result = execute_adapter(adapters, runtime)
        assert result["status"] == "failed" and "PRIVATE" not in json.dumps(result)
        factory.assert_called_once_with(runtime.step, runtime.context)
        adapters[1].assert_not_called()
        assert runtime.native.jobs.created == 0 and runtime.native.publications == []
        assert runtime.provider.calls == [] and runtime.native.blobs.reads == []


def test_cancelled_native_adapter_does_not_resolve_a_bridge(adapters, monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        result = execute_adapter(adapters, runtime, cancel_requested=lambda: True)
        assert result["status"] == "cancelled"
        factory.assert_not_called()
        adapters[1].assert_not_called()
        assert runtime.native.jobs.created == 0 and runtime.native.publications == []


def test_native_binding_factory_cannot_publish_files(adapters, monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        factory = bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())

        def attempt_publication(step, context):
            require_generated_file_publication_allowed()
            pytest.fail("The binding factory escaped the data-only publication guard.")

        factory.side_effect = attempt_publication
        result = execute_adapter(adapters, runtime)
        assert result["status"] == "failed"
        factory.assert_called_once_with(runtime.step, runtime.context)
        adapters[1].assert_not_called()
        assert runtime.native.jobs.created == 0 and runtime.native.publications == []


@pytest.mark.parametrize("fault", ["multiple", "mixed", "named_input"])
def test_unsupported_native_selection_keeps_safe_failure_diagnostics(adapters, monkeypatch, fault):
    with bridge_runtime(monkeypatch) as runtime:
        bind_adapter(runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        if fault == "named_input":
            runtime.step["inputs"] = {"records": {"step_id": "unadmitted", "output_name": "records"}}
        else:
            extra = deepcopy(runtime.context.execution_manifest[0])
            extra.update(document_id="second-source", source_kind="narrative" if fault == "mixed" else "tabular")
            runtime.context.execution_manifest.append(extra)
            runtime.context.source_manifest.append(deepcopy(extra))
        result = execute_adapter(adapters, runtime)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"]
        assert result["failure"]["retryable"] is False
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []
        assert runtime.provider.calls == [] and runtime.native.publications == []
        adapters[1].assert_not_called()
