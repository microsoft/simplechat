# test_orchestration_native_results.py
"""
Native computation, retained results and authorized export-source integration.
Version: 0.261.141
Implemented in: 0.261.127
Replay-location identity failure mapping added in: 0.261.141

Only external storage, document metadata, model and telemetry I/O are doubled.
The native engine, RunContext, bridge, result store, readers and export bridge
execute for real. No Flask route, paid provider or user publication is invoked.
"""

from contextlib import contextmanager
from copy import deepcopy
import csv
from dataclasses import replace
from decimal import Decimal
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

# Import real application modules only after the standalone test path bootstrap.
from functions_orchestration_checkpoints import step_input_fingerprint
from functions_orchestration_executor import RunContext
from functions_orchestration_result_contracts import RESULT_RECEIPT_VERSION, ResultContractError, TaskResult
from functions_orchestration_results import OrchestrationResultAccess, OrchestrationResults
from functions_workflow_result_store import WorkflowResultStore
from test_native_tabular_compute_service import (
    CONVERSATION, USER, NativeModelFixture, compute_plan, native_runtime, transformation_spec,
)
from test_support.orchestration_results import ResultContainer
from test_workflow_result_store import FakeBlobService


@contextmanager
def bridge_runtime(monkeypatch, count=37, *, operation="transform", task_type=None, durable=False):
    with native_runtime(monkeypatch, count) as native:
        bridge = importlib.import_module("functions_orchestration_native_results")
        mixed = importlib.import_module("functions_mixed_source_orchestration")
        container = ResultContainer()
        blobs = FakeBlobService()
        store = WorkflowResultStore(container, blobs, "private-results", max_size_bytes=32 * 1024 * 1024)
        access = OrchestrationResultAccess(
            user_id=USER, conversation_id=CONVERSATION,
            read_conversation=lambda identifier: native.conversations.read_item(identifier, identifier),
            read_run=lambda identifier: native.parents.read_item(identifier, CONVERSATION),
            source_resolver=mixed.resolve_authorized_source_manifest,
            source_metadata_reader=native.screening._read_authorized_document,
        )
        service = OrchestrationResults(store, access)
        calls = {"plan": 0, "model": 0, "guard": 0}
        state = {"guard": "native-bridge-server-token"}

        def guard(step_id):
            calls["guard"] += 1
            if step_id != "compute":
                raise ResultContractError("result_guard_required")
            return state["guard"]

        def request_builder(step, context, *, settings, user_id, source_manifest, native_operation, task_type, cancel_requested):
            calls["plan"] += 1
            plan = compute_plan(native, durable=durable)
            plan["requested_output_hints"]["native_operation"] = native_operation
            question = "Compute doubled amounts."
            if task_type in ("hierarchical_analysis", "combined"):
                plan.update({"execution_contract": task_type, "durable_task_type": task_type, "reason_code": "durable_intent"})
                plan["deliverable_contract"]["transformation_spec"] = {}
                plan["requested_output_hints"].pop("transformation_spec")
                question = "Summarize the amounts." if task_type == "hierarchical_analysis" else "Double amounts and summarize."
            if native_operation == "query":
                plan["deliverable_contract"]["transformation_spec"] = {}
                plan["requested_output_hints"].pop("transformation_spec")
                plan["deliverable_contract"]["public_output_schema"] = ["Item_ID", "amount"]
                plan["deliverable_contract"]["internal_checkpoint_schema"] = ["source_row_number", "source_row_identity", "Item_ID", "amount"]
                plan["requested_output_hints"]["query_expression"] = "amount <= 2"
                question = "Return the first two matching rows."
            return bridge.NativeOrchestrationRequest(plan, question)

        def model_resolver(step, context, *, settings, user_id):
            calls["model"] += 1
            return {"gpt_model": context.gpt_model, "model_context": context.model_context}

        bound = bridge.build_native_orchestration_bridge(
            native_operation=operation, task_type=task_type,
            request_builder=request_builder, model_resolver=model_resolver,
        )
        step = {
            "step_id": "compute", "capability_id": "document_analyze", "role": "reason", "enabled": True,
            "arguments": {"document_ids": ["source-1"]},
            "inputs": {}, "depends_on": [],
            "outputs": [{"name": spec.name, "kind": spec.kind} for spec in bound.output_specs],
        }
        parent = native.parents.read_item("parent-run", CONVERSATION)
        parent["plan"]["steps"] = [deepcopy(step)]
        native.parents.replace_item(parent["id"], parent)
        context = RunContext(
            user_id=USER, conversation_id=CONVERSATION, run_id="parent-run", attempt_index=1,
            plan_contract_version=2, result_service=service, gpt_model="gpt-4o",
            result_guard_token_for_step=guard,
        )
        context.source_manifest = deepcopy(native.source_manifest)
        context.execution_manifest = deepcopy(native.source_manifest)
        provider = NativeModelFixture()
        native.patcher.setattr(native.engine, "_build_chat_service", lambda *args, **kwargs: provider)
        yield SimpleNamespace(
            native=native, module=bridge, bound=bound, step=step, context=context,
            service=service, container=container, blobs=blobs, calls=calls, state=state, provider=provider,
        )


def execute(runtime, **kwargs):
    return runtime.bound.execute(
        runtime.step, runtime.context, settings=runtime.native.settings, user_id=USER, **kwargs,
    )


def resume(runtime, pending, **kwargs):
    return runtime.bound.resume(
        runtime.step, runtime.context, pending, settings=runtime.native.settings, user_id=USER, **kwargs,
    )


def finish_native(runtime, pending):
    return runtime.native.engine.process_tabular_generated_output_run(pending["wait"]["handle"]["job_id"], USER)


def commits(runtime):
    return [value for value in runtime.container.items.values() if value.get("record_kind") == "final"]


def bind_checkpoint_fingerprint(runtime):
    def owned_fingerprint(step, context):
        return step_input_fingerprint(step, context, None, settings=runtime.native.settings)

    runtime.bound = replace(runtime.bound, input_fingerprint_for_step=owned_fingerprint)
    return owned_fingerprint(runtime.step, runtime.context)


def use_production_builder(runtime, **arguments):
    runtime.step["arguments"] = {
        "document_ids": ["source-1"], "native_operation": runtime.bound.native_operation,
        "question": "Compute doubled amounts.", **arguments,
    }
    runtime.bound = runtime.module.build_native_orchestration_bridge(
        native_operation=runtime.bound.native_operation, task_type=runtime.bound.task_type,
    )
    parent = runtime.native.parents.read_item("parent-run", CONVERSATION)
    parent["plan"]["steps"] = [deepcopy(runtime.step)]
    runtime.native.parents.replace_item(parent["id"], parent)


@pytest.mark.parametrize("count", [0, 37, 30000])
def test_production_builder_executes_exact_deterministic_transforms(monkeypatch, count):
    with bridge_runtime(monkeypatch, count) as runtime:
        use_production_builder(
            runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec(),
        )
        result = execute(runtime)
        if result["status"] == "waiting":
            finish_native(runtime, result)
            result = resume(runtime, result)
        assert result["status"] == "completed", result
        reference = result["task_result"].output("records")
        rows = list(runtime.service.open_result(reference).iter_records())
        assert [column.name for column in reference.columns] == ["Item_ID", "doubled"]
        assert len(rows) == count
        assert rows == [
            {"Item_ID": f"item-{index:06}", "doubled": index * 2} for index in range(1, count + 1)
        ]
        assert runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("query, expected", [("amount < 0", 0), ("amount >= 36", 2), ("index == index", 37)])
def test_production_query_filters_and_counts_the_complete_result(monkeypatch, query, expected):
    with bridge_runtime(monkeypatch, operation="query") as runtime:
        use_production_builder(
            runtime, question="Return matching rows and their complete count.",
            columns=["Item_ID", "amount"], query_expression=query,
        )
        result = execute(runtime)
        assert result["status"] == "completed", result
        rows = list(runtime.service.open_result(result["task_result"].output("records")).iter_records())
        coverage = runtime.service.open_result(result["task_result"].output("coverage")).read_value()
        assert len(rows) == expected
        assert coverage["outputs"]["records"]["actual_count"] == expected
        assert coverage["outputs"]["records"]["expected_count"] == expected
        assert coverage["outputs"]["records"]["preview"] is False
        if query == "amount >= 36":
            assert rows == [{"Item_ID": "item-000036", "amount": 36}, {"Item_ID": "item-000037", "amount": 37}]
        assert runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("mode", ["semantic", "analysis", "combined", "hybrid"])
def test_production_model_supported_modes_execute_without_files(monkeypatch, mode):
    operation = "analysis" if mode == "analysis" else "transform"
    task_type = "combined" if mode == "combined" else None
    with bridge_runtime(monkeypatch, operation=operation, task_type=task_type) as runtime:
        arguments = {"question": "Double amounts and summarize their total."}
        if mode == "analysis":
            arguments["question"] = "Summarize all amounts and their total."
        else:
            arguments["columns"] = ["Item_ID", "doubled"]
        if mode == "combined":
            arguments.update(task_type="combined", transformation_spec=transformation_spec())
        elif mode == "hybrid":
            spec = transformation_spec()
            spec["fields"][1] = {"name": "doubled", "mode": "semantic", "type": "number", "nullable": False}
            arguments["transformation_spec"] = spec
        use_production_builder(runtime, **arguments)
        result = execute(runtime)
        if result["status"] == "waiting":
            finish_native(runtime, result)
            result = resume(runtime, result)
        assert result["status"] == "completed", result
        task = result["task_result"]
        if mode != "analysis":
            rows = list(runtime.service.open_result(task.output("records")).iter_records())
            assert len(rows) == 37 and rows[0]["doubled"] == 2 and rows[-1]["doubled"] == 74
        if mode in {"analysis", "combined"}:
            value = runtime.service.open_result(task.output("analysis")).read_value()
            assert value["counts"]["sum"] == 703
        assert {reference.output_name for reference in task.outputs} == {
            spec.name for spec in runtime.bound.output_specs
        }
        assert runtime.provider.calls and runtime.native.publications == []


def test_production_plan_uses_exact_schema_not_file_intent_or_heuristic_row_fields(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        use_production_builder(
            runtime, question="Generate a CSV with an answer for every row.",
            columns=["Item_ID", "doubled"], transformation_spec=transformation_spec(),
        )
        request = runtime.module.build_native_orchestration_request(
            runtime.step, runtime.context, settings=runtime.native.settings, user_id=USER,
            source_manifest=runtime.context.source_manifest,
            native_operation="transform", task_type="structured_export",
        )
        contract = request.plan["deliverable_contract"]
        assert contract["public_output_schema"] == ["Item_ID", "doubled"]
        assert contract["row_cardinality"] == "one_per_source_row" and contract["ordering"] == "source_order"
        assert contract["validation_profile"] == "exact_rows_schema_and_rules"
        assert contract["requested_artifacts"] == [] and request.plan["requested_output_formats"] == []
        assert request.plan["row_analysis_questions"] == []
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []
        result = execute(runtime)
        if result["status"] == "waiting":
            finish_native(runtime, result)
            result = resume(runtime, result)
        assert result["status"] == "completed", result
        assert runtime.native.publications == []


@pytest.mark.parametrize("schema, fields", [
    (None, None), ([], None), (["source_row_number", "source_row_identity"], []),
    (["source_row_number", "source_row_identity", "doubled"], ["doubled"]),
])
def test_combined_prompt_distinguishes_no_model_fields_from_schema_discovery(monkeypatch, schema, fields):
    with bridge_runtime(monkeypatch) as runtime:
        prompt = runtime.native.engine._build_combined_chunk_prompt(
            {"user_question": "Compute and summarize."}, [], 1, 1, output_schema=schema,
        )
        prefix = "Use exactly these structured row fields for every object, in this order: "
        assert (prefix in prompt) == (fields is not None)
        if fields is not None:
            assert f"{prefix}{json.dumps(fields)}." in prompt


@pytest.mark.parametrize("fault", [
    "question_only", "missing_columns", "duplicate_columns", "wrong_spec_fields", "wrong_nullable",
    "aggregate_expression", "unsafe_expression", "analysis_columns", "query_transform", "wrong_task_type", "delivery",
    "csv_sheet",
])
def test_production_arguments_fail_before_any_model_query_or_job_work(monkeypatch, fault):
    with bridge_runtime(monkeypatch, operation="query" if fault in {
        "aggregate_expression", "unsafe_expression", "query_transform",
    } else "analysis" if fault == "analysis_columns" else "transform") as runtime:
        arguments = {"columns": ["Item_ID", "doubled"], "transformation_spec": transformation_spec()}
        if runtime.bound.native_operation == "query":
            arguments = {"columns": ["amount"], "query_expression": "amount.sum()"}
        elif runtime.bound.native_operation == "analysis":
            arguments = {"columns": ["amount"]}
        if fault == "missing_columns":
            arguments.pop("columns")
        elif fault == "duplicate_columns":
            arguments["columns"] = ["Item_ID", "Item_ID"]
        elif fault == "wrong_spec_fields":
            arguments["columns"] = ["not_the_transformation_output"]
        elif fault == "wrong_nullable":
            arguments["transformation_spec"]["fields"][0]["nullable"] = "false"
        elif fault == "unsafe_expression":
            arguments["query_expression"] = "__import__('os').getcwd()"
        elif fault == "query_transform":
            arguments.update(query_expression="index == index", transformation_spec=transformation_spec())
        elif fault == "wrong_task_type":
            arguments["task_type"] = "hierarchical_analysis"
        elif fault == "delivery":
            arguments["output_format"] = "csv"
        elif fault == "csv_sheet":
            arguments["selected_sheet"] = "Ignored sheet"
        use_production_builder(runtime, **arguments)
        if fault == "question_only":
            runtime.step["arguments"] = {"document_ids": ["source-1"], "question": "What is the average?"}
        result = execute(runtime)
        assert result["status"] == "failed", result
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []
        assert runtime.provider.calls == [] and runtime.native.publications == []


def test_production_resume_never_calls_request_builder_or_model_resolver(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.native.settings["tabular_generated_output_inline_max_rows"] = 1
        use_production_builder(
            runtime, columns=["Item_ID", "doubled"], transformation_spec=transformation_spec(),
        )
        pending = execute(runtime)
        assert pending["status"] == "waiting", pending
        finish_native(runtime, pending)

        def forbidden(*args, **kwargs):
            raise AssertionError("A resume may not generate a request or resolve a model.")

        runtime.bound = replace(runtime.bound, request_builder=forbidden, model_resolver=forbidden)
        result = resume(runtime, pending)
        assert result["status"] == "completed", result
        assert runtime.native.jobs.created == 1


@pytest.mark.parametrize("operation", ["query", "transform", "analysis"])
def test_production_argument_validation_is_idempotent_and_wire_safe(monkeypatch, operation):
    with bridge_runtime(monkeypatch, operation=operation) as runtime:
        arguments = {
            "document_ids": ["source-1"], "question": "Compute the approved operation.", "native_operation": operation,
        }
        if operation == "query":
            arguments.update(columns=["amount"], query_expression="amount > 0")
        elif operation == "transform":
            arguments.update(columns=["Item_ID", "doubled"], transformation_spec=transformation_spec())
        original = deepcopy(arguments)
        first = runtime.module.validate_native_orchestration_arguments(arguments)
        second = runtime.module.validate_native_orchestration_arguments(json.loads(json.dumps(first)))
        errors = list(runtime.module.Draft202012Validator(runtime.module.native_orchestration_arguments_schema()).iter_errors(first))
        assert first == second and arguments == original and errors == []


@pytest.mark.parametrize("count", [0, 37, 30000])
def test_real_native_compute_retention_and_export_preserve_every_derived_row(monkeypatch, count):
    with bridge_runtime(monkeypatch, count) as runtime:
        result = execute(runtime)
        if result["status"] == "waiting":
            finished = finish_native(runtime, result)
            assert finished["status"] == "completed"
            result = resume(runtime, result)
        assert result["status"] == "completed", result
        task = result["task_result"]
        assert type(task) is TaskResult and task.producer == runtime.context.result_producer(runtime.step)
        assert {item.output_name for item in task.outputs} == {"records", "coverage"}
        assert task.output("records").item_count == count
        assert [column.name for column in task.output("records").columns] == ["Item_ID", "doubled"]

        exports = importlib.import_module("functions_orchestration_export_sources")
        files = importlib.import_module("functions_generated_file_exports")
        restarted = OrchestrationResults(
            WorkflowResultStore(runtime.container, runtime.blobs, "private-results", max_size_bytes=32 * 1024 * 1024),
            runtime.service.access,
        )
        source = exports.open_orchestration_export_source(
            restarted, task.output("records"), columns=["doubled", "Item_ID"],
        )
        with files.build_generated_file_export(
            source=source,
            export_request=files.GeneratedFileExportRequest("csv", "tabular_records_v1", columns=source.columns),
            max_output_bytes=32 * 1024 * 1024,
        ) as output:
            stream = io.TextIOWrapper(output.file_content, encoding="utf-8", newline="")
            try:
                rows = csv.reader(stream)
                header = next(rows)
                first, last, actual = None, None, 0
                for row in rows:
                    actual += 1
                    first = row if first is None else first
                    last = row
                    assert Decimal(row[0]) == actual * 2
            finally:
                stream.detach()
            source.require_complete_consumption()
            assert output.record_count == count and actual == count
            assert header == ["doubled", "Item_ID"]
            if count:
                assert first[1] == "item-000001" and last[1] == f"item-{count:06}"
        assert runtime.native.publications == []
        assert result["artifacts"] == []
        assert runtime.native.jobs.created == 1


@pytest.mark.parametrize(
    ("operation", "task_type", "names"),
    [("analysis", None, {"analysis", "coverage"}), ("transform", "combined", {"records", "analysis", "coverage"})],
)
def test_analysis_and_combined_declarations_match_full_native_outputs(monkeypatch, operation, task_type, names):
    with bridge_runtime(monkeypatch, 83, operation=operation, task_type=task_type) as runtime:
        pending = execute(runtime)
        assert pending["status"] == "waiting"
        finished = finish_native(runtime, pending)
        assert finished["status"] == "completed"
        result = resume(runtime, pending)
        assert result["status"] == "completed", result
        task = result["task_result"]
        value = runtime.service.open_result(task.output("analysis")).read_value()
        coverage = runtime.service.open_result(task.output("coverage")).read_value()
        assert {item.output_name for item in task.outputs} == names
        assert value["row_count"] == 83 and value["counts"]["sum"] == sum(range(1, 84))
        assert set(coverage["outputs"]) == names - {"coverage"}
        assert runtime.native.publications == []


def test_wait_restart_and_duplicate_resume_never_plan_or_submit_again(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        assert pending["status"] == "waiting"
        assert pending["task_result"].outputs == ()
        assert set(pending["wait"]) == {"kind", "handle"}
        assert set(pending["wait"]["handle"]) == {"version", "job_id", "request_fingerprint"}
        pending["wait"] = json.loads(json.dumps(pending["wait"]))
        pending["task_result"] = TaskResult.from_dict(pending["task_result"].to_dict())
        parent = runtime.native.parents.read_item("parent-run", CONVERSATION)
        parent["status"] = "waiting"
        runtime.native.parents.replace_item(parent["id"], parent)
        opened = []
        open_native = runtime.native.results.open_native_tabular_result

        def open_once(**kwargs):
            opened.append(kwargs["handle"])
            return open_native(**kwargs)

        def no_submission(*args, **kwargs):
            raise AssertionError("Resume must never submit or build another native callback.")

        runtime.native.patcher.setattr(runtime.native.results, "open_native_tabular_result", open_once)
        runtime.native.patcher.setattr(runtime.native.service, "build_native_tabular_compute_callback", no_submission)
        runtime.native.patcher.setattr(runtime.native.engine, "queue_tabular_generated_output_run", no_submission)
        planned = dict(runtime.calls)
        source_reads = len(runtime.native.blobs.reads)
        writes = len(runtime.native.blobs.writes)
        first = resume(runtime, pending)
        second = resume(runtime, pending)
        assert first["status"] == second["status"] == "waiting"
        assert runtime.calls == planned
        assert len(runtime.native.blobs.reads) == source_reads
        assert len(runtime.native.blobs.writes) == writes
        assert len(opened) == 2
        finish_native(runtime, pending)
        parent = runtime.native.parents.read_item("parent-run", CONVERSATION)
        parent["status"] = "running"
        runtime.native.parents.replace_item(parent["id"], parent)
        ready = resume(runtime, pending)
        assert ready["status"] == "completed", ready
        runtime.context.task_results["compute"] = ready["task_result"]
        stored = len(runtime.blobs.uploads)
        again = resume(runtime, pending)
        assert again["task_result"] == ready["task_result"]
        assert len(runtime.blobs.uploads) == stored
        assert runtime.calls["plan"] == runtime.calls["model"] == 1
        assert runtime.native.jobs.created == 1
        assert len(opened) == 4


def test_query_uses_real_native_filter_and_declared_schema(monkeypatch):
    with bridge_runtime(monkeypatch, operation="query") as runtime:
        result = execute(runtime)
        assert result["status"] == "completed", result
        rows = list(runtime.service.open_result(result["task_result"].output("records")).iter_records())
        assert rows == [
            {"Item_ID": "item-000001", "amount": 1}, {"Item_ID": "item-000002", "amount": 2},
        ]
        assert runtime.provider.calls == []


def test_snapshot_policy_is_explicit_and_retains_original_values(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        finish_native(runtime, pending)
        runtime.native.document.update({"version": 2, "_etag": "source-revision-2"})
        source_blob = runtime.native.blobs.values[("user-documents", f"{USER}/source.csv")]
        source_blob.update({"etag": "source-blob-2", "bytes": b"Item_ID,amount\nreplacement,999\n"})
        refused = resume(runtime, pending)
        assert refused["status"] == "failed"
        snapshot = runtime.module.build_native_orchestration_bridge(
            native_operation="transform", request_builder=runtime.bound.request_builder,
            source_policy="snapshot",
        )
        result = snapshot.resume(
            runtime.step, runtime.context, pending, settings=runtime.native.settings, user_id=USER,
        )
        assert result["status"] == "completed", result
        rows = list(runtime.service.open_result(result["task_result"].output("records")).iter_records())
        assert len(rows) == 37 and rows[-1]["doubled"] == 74
        coverage = runtime.service.open_result(result["task_result"].output("coverage")).read_value()
        assert coverage["sources"][0]["source_version"] == 1
        runtime.native.state["allowed"] = False
        with pytest.raises(PermissionError):
            runtime.service.open_result(result["task_result"].output("records"))


@pytest.mark.parametrize("fault", [
    "missing", "extra", "kind", "unavailable_model", "missing_locator", "named_inputs",
    "multiple_declared", "mismatched_declared",
])
def test_invalid_admission_does_not_invoke_the_request_builder(monkeypatch, fault):
    with bridge_runtime(monkeypatch) as runtime:
        if fault == "missing":
            runtime.step["outputs"].pop()
        elif fault == "extra":
            runtime.step["outputs"].append({"name": "preview", "kind": "records-v1"})
        elif fault == "kind":
            runtime.step["outputs"][0]["kind"] = "structured-v1"
        elif fault == "unavailable_model":
            runtime.context.gpt_model = None
        elif fault == "named_inputs":
            runtime.step["inputs"] = {"source": {"binding": {"step_id": "earlier", "output_name": "records"}}}
        elif fault == "multiple_declared":
            runtime.step["arguments"]["document_ids"].append("other-source")
        elif fault == "mismatched_declared":
            runtime.step["arguments"]["document_ids"] = ["other-source"]
        else:
            runtime.context.source_manifest[0].pop("storage_locator")
        result = execute(runtime)
        assert result["status"] == "failed"
        assert runtime.calls["plan"] == 0 and runtime.native.jobs.created == 0
        assert result["failure"]["retryable"] is False and runtime.native.publications == []


def test_declared_mode_and_bare_aggregate_cannot_be_replaced_with_source_rows(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        def bare_request(step, context, **kwargs):
            plan = runtime.native.planner.plan_tabular_request(
                "What is the average?", [{"file_name": "source.csv", "document_id": "source-1"}],
            )
            return runtime.module.NativeOrchestrationRequest(plan, "What is the average?")

        bound = runtime.module.build_native_orchestration_bridge(
            native_operation="transform", request_builder=bare_request,
        )
        result = bound.execute(runtime.step, runtime.context, settings=runtime.native.settings, user_id=USER)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"] == "native_request_invalid"
        assert runtime.native.blobs.reads == [] and runtime.native.jobs.created == 0


def test_same_attempt_is_required_when_resuming(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        parent = runtime.native.parents.read_item("parent-run", CONVERSATION)
        parent["attempt_index"] = 2
        runtime.native.parents.replace_item(parent["id"], parent)
        runtime.context.attempt_index = 2
        result = resume(runtime, pending)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"] == "native_wait_invalid"
        assert runtime.calls["plan"] == 1 and runtime.native.jobs.created == 1


def test_checkpoint_fingerprint_supports_committed_resume_after_restart(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        fingerprint = bind_checkpoint_fingerprint(runtime)
        pending = execute(runtime)
        finish_native(runtime, pending)
        result = resume(runtime, pending)
        assert result["status"] == "completed", result
        reference = result["task_result"].output("records")
        metadata = runtime.service.open_result(reference).metadata()
        assert metadata["input_fingerprint"] == fingerprint
        private_writes = len(runtime.blobs.uploads), deepcopy(runtime.container.items)
        runtime.context.result_service = OrchestrationResults(
            WorkflowResultStore(runtime.container, runtime.blobs, "private-results", max_size_bytes=32 * 1024 * 1024),
            runtime.service.access,
        )
        runtime.context.task_results = {}
        repeated = resume(runtime, pending)
        assert repeated["status"] == "completed", repeated
        assert repeated["task_result"] == result["task_result"]
        assert (len(runtime.blobs.uploads), runtime.container.items) == private_writes
        assert runtime.calls["plan"] == runtime.calls["model"] == 1 and runtime.native.jobs.created == 1


def test_omitted_checkpoint_fingerprint_preserves_receipt_free_retention(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        result = execute(runtime)
        assert result["status"] == "completed", result
        metadata = runtime.service.open_result(result["task_result"].output("records")).metadata()
        fingerprint = step_input_fingerprint(runtime.step, runtime.context, None, settings=runtime.native.settings)
        recovered = runtime.service.recover_task_result(
            producer=runtime.context.result_producer(runtime.step), input_fingerprint=fingerprint,
        )
        assert "input_fingerprint" not in metadata
        assert recovered is None


def test_pending_native_step_has_no_committed_input_receipt(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        fingerprint = bind_checkpoint_fingerprint(runtime)
        pending = execute(runtime)
        recovered = runtime.service.recover_task_result(
            producer=runtime.context.result_producer(runtime.step), input_fingerprint=fingerprint,
        )
        retained = commits(runtime)
        assert pending["status"] == "waiting" and pending["task_result"].status == "pending"
        assert recovered is None and retained == []
        assert set(pending["wait"]) == {"kind", "handle"}


def test_receipt_read_failure_never_replays_or_replaces_committed_output(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        bind_checkpoint_fingerprint(runtime)
        pending = execute(runtime)
        finish_native(runtime, pending)
        result = resume(runtime, pending)
        assert result["status"] == "completed", result
        final_keys = [
            key for key, value in runtime.container.items.items()
            if value.get("record_kind") == "final" and not value.get("key", "").startswith(RESULT_RECEIPT_VERSION)
        ]
        assert len(final_keys) == 1
        runtime.container.items.pop(final_keys[0])
        private_state = len(runtime.blobs.uploads), deepcopy(runtime.container.items)
        failed = resume(runtime, pending)
        after = len(runtime.blobs.uploads), runtime.container.items
        assert failed["status"] == "failed"
        assert after == private_state
        assert runtime.calls["plan"] == runtime.calls["model"] == 1 and runtime.native.jobs.created == 1


def test_invalid_checkpoint_fingerprint_stops_before_planning(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.bound = replace(runtime.bound, input_fingerprint_for_step=lambda step, context: "not-a-checkpoint-hash")
        result = execute(runtime)
        assert result["status"] == "failed"
        assert runtime.calls["plan"] == runtime.calls["model"] == 0 and runtime.native.jobs.created == 0


@pytest.mark.parametrize("fault", ["acl", "cancellation", "parent_deletion", "store_guard"])
def test_late_revocation_during_full_retention_never_commits(monkeypatch, fault):
    with bridge_runtime(monkeypatch) as runtime:
        state = {"cancel": False, "changed": False}
        original = runtime.native.results.NativeTabularResultReader.iter_records

        def changing_records(reader):
            for index, row in enumerate(original(reader)):
                if index == 3:
                    if fault == "acl":
                        runtime.native.state["allowed"] = False
                    elif fault == "cancellation":
                        state["cancel"] = True
                    elif fault == "parent_deletion":
                        parent = runtime.native.parents.read_item("parent-run", CONVERSATION)
                        parent["deleted_at"] = "2026-05-01T00:00:00Z"
                        runtime.native.parents.replace_item(parent["id"], parent)
                    else:
                        runtime.service.store.delete_orchestration_results(USER, CONVERSATION, "parent-run")
                    state["changed"] = True
                yield row

        runtime.native.patcher.setattr(runtime.native.results.NativeTabularResultReader, "iter_records", changing_records)
        result = execute(runtime, cancel_requested=lambda: state["cancel"])
        complete = commits(runtime)
        assert state["changed"]
        assert result["status"] == ("cancelled" if fault == "cancellation" else "failed")
        assert complete == [] and runtime.native.publications == []


@pytest.mark.parametrize("state", ["failed", "cancelled", "invalid-state", "incomplete"])
def test_terminal_or_invalid_native_state_is_not_endless_waiting(monkeypatch, state):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        if state == "incomplete":
            finish_native(runtime, pending)
        job = runtime.native.jobs.read_item(pending["wait"]["handle"]["job_id"], USER)
        if state == "incomplete":
            job["computation_state"] = "incomplete"
        else:
            job["status"] = state
        runtime.native.jobs.replace_item(job["id"], job)
        result = resume(runtime, pending)
        complete = commits(runtime)
        assert result["status"] in {"failed", "cancelled"}, result
        assert result.get("wait") is None and complete == [] and runtime.native.jobs.created == 1


def test_analysis_value_limit_does_not_create_a_partial_success(monkeypatch):
    with bridge_runtime(monkeypatch, operation="analysis", durable=True) as runtime:
        runtime.bound = replace(runtime.bound, max_analysis_bytes=1)
        pending = execute(runtime)
        finished = finish_native(runtime, pending)
        assert finished["status"] == "completed"
        result = resume(runtime, pending)
        complete = commits(runtime)
        assert result["status"] == "failed" and complete == []


def test_foreground_and_durable_retention_are_equivalent(monkeypatch):
    outputs = []
    for durable in (False, True):
        with bridge_runtime(monkeypatch, durable=durable) as runtime:
            result = execute(runtime)
            if durable:
                assert result["status"] == "waiting"
                finish_native(runtime, result)
                result = resume(runtime, result)
            assert result["status"] == "completed"
            reference = result["task_result"].output("records")
            rows = list(runtime.service.open_result(reference).iter_records())
            outputs.append((reference.columns, reference.completeness, rows))
    assert outputs[0] == outputs[1]
    assert outputs[0][2][-1]["doubled"] == 74


def test_replay_location_of_another_revision_is_a_clean_access_failure(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        archived = {**deepcopy(runtime.native.document), "id": "source-archived", "_etag": "source-revision-0"}
        logged = []
        runtime.native.patcher.setattr(
            runtime.native.screening, "_resolve_blob_document", lambda container, blob, user_id: deepcopy(archived),
        )
        runtime.native.patcher.setattr(
            runtime.module, "log_event", lambda message, extra=None, **kwargs: logged.append(dict(extra or {})),
        )
        runtime.native.patcher.setattr(
            runtime.module, "workflow_log_context",
            lambda step_id=None, run_id=None, conversation_id=None: {
                "step_id_hash": f"hash:{step_id}", "run_id_hash": f"hash:{run_id}",
                "conversation_id_hash": f"hash:{conversation_id}",
            },
        )
        result = execute(runtime)
        complete = commits(runtime)
        assert result["status"] == "failed"
        assert result["failure"]["code"] == "context_unavailable"
        assert result["failure"]["native_code"] == "native_access_unavailable"
        assert result["failure"]["retryable"] is False
        assert complete == [] and runtime.native.jobs.created == 0
        assert runtime.native.publications == []
        assert len(logged) == 1
        assert logged[0]["failure_code"] == "context_unavailable"
        assert logged[0]["execution_code"] == "native_compute_source_identity_mismatch"
        assert logged[0]["step_id_hash"] == "hash:compute" and "step_id" not in logged[0]
        assert logged[0]["run_id_hash"] == "hash:parent-run"
        assert logged[0]["conversation_id_hash"] == f"hash:{CONVERSATION}" and CONVERSATION
        assert "run_id" not in logged[0] and "conversation_id" not in logged[0]


@pytest.mark.parametrize("source_kind", ["narrative", "tabular"])
def test_multi_or_mixed_selection_is_refused_before_plan_model_or_native_work(monkeypatch, source_kind):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.context.source_manifest.append({**runtime.context.source_manifest[0], "source_kind": source_kind})
        result = execute(runtime)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"] == "native_selection_unsupported"
        assert result["failure"]["retryable"] is False
        assert runtime.calls == {"plan": 0, "model": 0, "guard": 0}
        assert runtime.native.jobs.created == 0
        assert runtime.native.blobs.reads == [] and runtime.native.publications == []


@pytest.mark.parametrize("mutation", ["version", "job_id", "request_fingerprint", "extra"])
def test_invalid_wait_handle_fails_closed_without_submission(monkeypatch, mutation):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        if mutation == "extra":
            pending["wait"]["handle"]["blob_path"] = "untrusted/private/path"
        else:
            pending["wait"]["handle"][mutation] = "invalid"
        result = resume(runtime, pending)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"] == "native_wait_invalid"
        assert runtime.calls["plan"] == 1 and runtime.native.jobs.created == 1
        assert runtime.native.publications == []


@pytest.mark.parametrize("revocation", ["acl", "screening", "conversation", "parent", "attempt", "job", "cancel"])
def test_resume_stops_on_revoked_deleted_or_canceled_state(monkeypatch, revocation):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        finish_native(runtime, pending)
        if revocation == "acl":
            runtime.native.state["allowed"] = False
        elif revocation == "screening":
            runtime.native.document["content_screening"] = {"state": "pending_review"}
        elif revocation == "conversation":
            runtime.native.conversations.items.clear()
        elif revocation == "parent":
            runtime.native.parents.items.clear()
        elif revocation == "job":
            runtime.native.jobs.items.clear()
        else:
            parent = runtime.native.parents.read_item("parent-run", CONVERSATION)
            if revocation == "attempt":
                parent["attempt_index"] = 2
            else:
                parent["cancellation_requested_at"] = "cancelled"
            runtime.native.parents.replace_item(parent["id"], parent)
        result = resume(runtime, pending)
        retained = commits(runtime)
        assert result["status"] in ("failed", "cancelled")
        assert "task_result" not in result and retained == []
        assert runtime.native.publications == [] and runtime.calls["plan"] == 1


def test_corrupt_native_output_cannot_commit_a_partial_generic_result(monkeypatch):
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        finish_native(runtime, pending)
        path = runtime.native.engine._output_blob_path(USER, CONVERSATION, pending["wait"]["handle"]["job_id"], 1)
        blob = runtime.native.blobs.values[("personal-chat", path)]
        rows = json.loads(blob["bytes"])
        rows[0]["doubled"] = -999
        blob["bytes"] = json.dumps(rows).encode("utf-8")
        result = resume(runtime, pending)
        retained = commits(runtime)
        assert result["status"] == "failed" and retained == []
        assert "task_result" not in result
        assert runtime.native.publications == []


def test_actual_guard_is_required_and_cancellation_is_not_pending(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.state["guard"] = None
        result = execute(runtime)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"] == "native_guard_unavailable"
        assert runtime.calls["plan"] == 0 and runtime.native.jobs.created == 0
        cancelled = execute(runtime, cancel_requested=lambda: True)
        assert cancelled["status"] == "cancelled"
        assert "wait" not in cancelled
    with bridge_runtime(monkeypatch, durable=True) as runtime:
        pending = execute(runtime)
        finish_native(runtime, pending)
        runtime.state["guard"] = "different-server-token"
        result = resume(runtime, pending)
        retained = commits(runtime)
        assert result["status"] == "failed" and retained == []
        assert runtime.native.publications == []


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("first", ["functions_orchestration_registry", "functions_orchestration_native_results"])
def test_cold_imports_are_real_route_free_and_network_blocked(optimized, first):
    script = """
import importlib, socket, sys
def blocked(*args, **kwargs):
    raise RuntimeError('Network is forbidden in a cold import.')
socket.socket.connect = blocked
socket.create_connection = blocked
sys.path.insert(0, sys.argv[1])
importlib.import_module(sys.argv[2])
bridge = importlib.import_module('functions_orchestration_native_results')
importlib.import_module('functions_orchestration_executor')
from jsonschema import Draft202012Validator
Draft202012Validator.check_schema(bridge.native_orchestration_arguments_schema())
specs = bridge.native_orchestration_output_specs('analysis')
if [spec.name for spec in specs] != ['analysis', 'coverage']:
    raise RuntimeError('Invalid native output declaration.')
if 'config' in sys.modules or 'route_backend_chats' in sys.modules:
    raise RuntimeError('Native bridge crossed the bootstrap/route boundary.')
"""
    completed = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", script, str(APP), first],
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
