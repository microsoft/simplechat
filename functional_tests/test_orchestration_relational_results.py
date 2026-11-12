# test_orchestration_relational_results.py
"""
Functional tests for authorized, retained multi-file calculation results.
Version: 0.261.432
Implemented in: 0.261.432

Real source authorization, bounded computation and retained records run offline.
Only documents, blobs and model I/O are doubled by the existing native harness.
"""

from copy import deepcopy
import csv
import importlib
import io
import sys

import pytest
from azure.core.exceptions import ServiceRequestError

from test_orchestration_native_results import USER, bridge_runtime, commits, execute
from test_orchestration_dependency_runtime import execute as execute_compiled, runtime  # noqa: F401
from test_tabular_relational_calculations import join_spec
from test_support.orchestration_research import document_action_policy_module


def prepare(runtime):
    native = runtime.native
    # Share the real pure policy definitions without the unrelated search bootstrap.
    native.patcher.setitem(sys.modules, "functions_document_actions", document_action_policy_module())
    documents = {
        "source-1": {
            **native.document, "file_name": "orders.csv", "blob_path": f"{USER}/orders.csv",
        },
        "source-2": {
            **native.document, "id": "source-2", "file_name": "prices.csv", "blob_path": f"{USER}/prices.csv",
        },
    }
    data = {
        "source-1": b"code,quantity\n007,3\n008,2\n",
        "source-2": b"sku,price\n008,0.20\n007,0.10\n",
    }
    for identifier, document in documents.items():
        native.blobs.values[("user-documents", document["blob_path"])] = {
            "bytes": data[identifier], "etag": "relational-source-1", "metadata": {},
        }

    def read_document(document_id, user_id, **kwargs):
        if not native.state["allowed"] or user_id != USER or document_id not in documents:
            raise PermissionError("The selected source is unavailable.")
        return deepcopy(documents[document_id])

    mixed = importlib.import_module("functions_mixed_source_orchestration")
    native.patcher.setattr(native.screening, "_read_authorized_document", read_document)
    runtime.service.access.source_metadata_reader = read_document

    def read_blob_document(container, blob, user_id):
        matching = [document for document in documents.values()
                    if document["blob_container"] == container and document["blob_path"] == blob]
        if len(matching) != 1:
            raise PermissionError("The selected source location is unavailable.")
        return read_document(matching[0]["id"], user_id)

    native.patcher.setattr(native.screening, "_resolve_blob_document", read_blob_document)
    native.patcher.setattr(mixed, "_default_document_context_batch_resolver", lambda **kwargs: [
        {"document": read_document(identifier, kwargs["user_id"]), "scope": "personal",
         "group_id": None, "public_workspace_id": None}
        for identifier in kwargs["document_ids"]
    ])
    manifest = mixed.resolve_authorized_source_manifest(["source-1", "source-2"], USER, doc_scope="personal")
    runtime.context.source_manifest = deepcopy(manifest)
    runtime.context.execution_manifest = deepcopy(manifest)
    spec = join_spec()
    spec["datasets"][0]["document_id"] = "source-1"
    spec["datasets"][1]["document_id"] = "source-2"
    runtime.bound = runtime.module.build_native_orchestration_bridge(native_operation="relate")
    runtime.step["arguments"] = {
        "question": "Calculate exact order amounts from the selected orders and prices.",
        "native_operation": "relate", "document_ids": ["source-1", "source-2"], "relational_spec": spec,
    }
    runtime.step["outputs"] = [
        {"name": output.name, "kind": output.kind} for output in runtime.bound.output_specs
    ]
    parent = native.parents.read_item("parent-run", runtime.context.conversation_id)
    parent["plan"]["steps"] = [deepcopy(runtime.step)]
    native.parents.replace_item(parent["id"], parent)
    return documents, data


def test_cross_file_result_retains_exact_records_coverage_and_original_row_lineage(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        prepare(runtime)
        result = execute(runtime)
        assert result["status"] == "completed", result
        task = result["task_result"]
        rows = list(runtime.service.open_result(task.output("records")).iter_records())
        lineage = list(runtime.service.open_result(task.output("lineage")).iter_records())
        coverage = runtime.service.open_result(task.output("coverage")).read_value()
        assert rows == [{"code": "007", "amount": "0.30"}, {"code": "008", "amount": "0.40"}]
        assert [entry["document_id"] for entry in coverage["sources"]] == ["source-1", "source-2"]
        assert coverage["input_rows"] == 4 and coverage["complete"] is True
        assert coverage["source_snapshots"] == [
            {"document_id": source["document_id"], "scope": source["scope"], "scope_id": source["scope_id"],
             "source_version": source["source_version"], "source_revision": source["source_revision"]}
            for source in runtime.context.source_manifest
        ]
        assert coverage["operation_spec"] == runtime.step["arguments"]["relational_spec"]
        assert lineage[0]["sources"][0]["document_id"] == "source-2"
        assert lineage[0]["sources"][0]["row_ranges"] == [[3, 3]]
        assert len(commits(runtime)) == 1
        assert runtime.native.jobs.created == 0
        assert runtime.provider.calls == [] and runtime.native.publications == []


@pytest.mark.parametrize("fault", ["revoked", "stale", "ambiguous", "cancelled", "attempt", "retention"])
def test_cross_file_failure_controls_publish_no_complete_result(monkeypatch, fault):
    with bridge_runtime(monkeypatch) as runtime:
        documents, data = prepare(runtime)
        if fault == "revoked":
            runtime.native.state["allowed"] = False
        elif fault == "stale":
            documents["source-2"]["_etag"] = "a-later-source-revision"
        elif fault == "ambiguous":
            key = ("user-documents", documents["source-2"]["blob_path"])
            runtime.native.blobs.values[key]["bytes"] += b"007,0.20\n"
        elif fault == "attempt":
            parent = runtime.native.parents.read_item("parent-run", runtime.context.conversation_id)
            parent["attempt_index"] = 2
            runtime.native.parents.replace_item(parent["id"], parent)
        elif fault == "retention":
            runtime.blobs.upload_error = ServiceRequestError("PRIVATE_STORAGE_ERROR")
            output = importlib.import_module("functions_orchestration_output_store")
            with pytest.raises(output.OutputStorageError):
                execute(runtime)
            assert commits(runtime) == []
            assert runtime.native.jobs.created == 0 and runtime.provider.calls == []
            return
        result = execute(runtime, cancel_requested=lambda: fault == "cancelled")
        assert result["status"] in {"failed", "cancelled"}, result
        expected_code = {
            "revoked": "native_access_unavailable", "stale": "native_access_unavailable",
            "attempt": "native_access_unavailable", "ambiguous": "native_relational_ambiguous",
            "cancelled": "native_cancelled",
        }[fault]
        assert result["failure"]["native_code"] == expected_code, result
        assert "task_result" not in result or result["task_result"] is None
        assert commits(runtime) == []
        assert runtime.native.jobs.created == 0 and runtime.provider.calls == []


def test_authority_is_rechecked_after_source_bytes_are_read(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        documents, data = prepare(runtime)

        def read(source, user_id, group_id, public_workspace_id, *, purpose):
            content = data[source["document_id"]]
            if source["document_id"] == "source-2":
                documents["source-2"]["_etag"] = "changed-during-read"
            return documents[source["document_id"]], content

        runtime.context.merge_source_reader = read
        result = execute(runtime)
        assert result["status"] == "failed"
        assert result["failure"]["native_code"] == "native_access_unavailable"
        assert commits(runtime) == []
        assert runtime.provider.calls == []


def test_relational_arguments_and_legacy_single_source_contracts_are_distinct():
    module = importlib.import_module("functions_orchestration_native_results")
    spec = join_spec()
    arguments = {
        "question": "Calculate from both sources.", "native_operation": "relate",
        "document_ids": ["sales", "catalog"], "relational_spec": spec,
    }
    normalized = module.validate_native_orchestration_arguments(arguments)
    again = module.validate_native_orchestration_arguments(normalized)
    assert again == normalized
    with pytest.raises(module.NativeOrchestrationBridgeError):
        module.validate_native_orchestration_arguments({
            "question": "Read both.", "native_operation": "query", "document_ids": ["sales", "catalog"],
            "query_expression": "index == index", "columns": ["code"],
        })


def test_real_compiler_executor_and_export_consume_computed_not_model_generated_rows(runtime):
    module = importlib.import_module("functions_orchestration_native_results")
    spec = join_spec()
    step = {
        "step_id": "calculate", "capability_id": "tabular_analyze",
        "arguments": {
            "question": "Calculate exact order amounts across the selected files.",
            "native_operation": "relate", "document_ids": ["sales", "catalog"], "relational_spec": spec,
        },
    }
    case = runtime.make([step], available=["tabular_analyze"])
    data = {"sales": b"code,quantity\n007,3\n008,2\n", "catalog": b"sku,price\n008,0.20\n007,0.10\n"}
    for identifier in data:
        case.fixture.sources[identifier] = {
            "document_id": identifier, "scope": "personal", "scope_id": "owner",
            "source_version": 1, "source_revision": f"{identifier}-revision",
            "source_kind": "tabular", "file_name": f"{identifier}.csv",
            "storage_locator": {"container": "private", "blob_path": f"owner/{identifier}.csv"},
        }
    case.context.native_bridge_for_step = lambda step, context: module.build_native_orchestration_bridge(
        native_operation=step["arguments"]["native_operation"],
    )
    case.context.merge_source_reader = lambda source, user_id, group_id, public_workspace_id, purpose: (
        {"id": source["document_id"]}, data[source["document_id"]],
    )
    result = execute_compiled(runtime, case)
    assert result["status"] == "completed", result
    task = runtime.contracts.TaskResult.from_dict(result["task_results"]["calculate"])
    assert {output.output_name for output in task.outputs} == {"records", "lineage", "coverage"}
    assert case.model.calls == []
    exports = importlib.import_module("functions_generated_file_exports")
    sources = importlib.import_module("functions_orchestration_export_sources")
    source = sources.open_orchestration_export_source(case.fixture.restart(), task.output("records"))
    with exports.build_generated_file_export(
        source=source,
        export_request=exports.GeneratedFileExportRequest("csv", "exact_tabular_records_v1"),
        max_output_bytes=1024 * 1024,
    ) as output:
        rows = list(csv.reader(io.StringIO(output.file_content.read().decode("utf-8-sig"))))
        source.require_complete_consumption()
        assert output.record_count == 2
    assert rows == [["code", "amount"], ["007", "0.30"], ["008", "0.40"]]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
