# test_orchestration_relational_results.py
"""
Functional tests for authorized, retained multi-file calculation results.
Version: 0.261.470
Implemented in: 0.261.437; 0.261.446
Evaluation findings returned to the authoring model added in: 0.261.470
Source-header failure classification added in: 0.261.439
Stable runtime failure codes and locations added in: 0.261.443
Complete preparation and owner-bound prepared lowering added in: 0.261.446

Real source authorization, bounded computation and retained records run offline.
Only documents, blobs and model I/O are doubled by the existing native harness.
"""

from copy import deepcopy
from dataclasses import replace
import csv
import hashlib
import importlib
import io
import json
import sys

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ServiceRequestError

from test_orchestration_native_results import USER, bridge_runtime, commits, execute
from test_orchestration_dependency_runtime import execute as execute_compiled, runtime  # noqa: F401
from test_tabular_relational_calculations import join_spec
from test_support.orchestration_research import document_action_policy_module
from test_support.orchestration_results import ResultContainer


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


def test_legacy_native_fingerprint_keeps_the_recorded_capability_projection(monkeypatch):
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    with bridge_runtime(monkeypatch) as runtime:
        prepare(runtime)
        actual = checkpoints.step_input_fingerprint(
            runtime.step, runtime.context, "coordinator-recorded-legacy-recovery",
            settings=runtime.native.settings,
        )
    assert actual == "57da84c521a234d43a83db6e230d20fccdfc9b9d3aa3af3604ab9c87166e736c"


def test_legacy_schema_projection_excludes_new_preparation_only_members():
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    registry = importlib.import_module("functions_orchestration_registry")
    native = registry.get_capability("tabular_analyze", contract_version=2)
    compose = registry.get_capability("compose", contract_version=2)
    native_inputs = checkpoints._legacy_tabular_capability_inputs(native["inputs"])
    compose_inputs = checkpoints._legacy_compose_capability_inputs(compose["inputs"])
    assert "prepare" not in native_inputs["properties"]["native_operation"]["enum"]
    assert "preparation_request" not in native_inputs["properties"]
    assert "calculation_mode" not in native_inputs["properties"]
    assert not any(
        "calculation_mode" in variant.get("required", [])
        for variant in native_inputs["oneOf"]
    )
    requirement = compose_inputs["properties"]["tabular_requirement"]["properties"]
    assert "calculation_answer" not in requirement["mode"]["enum"]
    assert "version" not in requirement


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


@pytest.mark.parametrize(
    "mutation",
    [
        None, "body", "request", "selector", "saved_unsupported",
        "saved_wrong_sources", "resume_correction",
        "two_corrections", "correction_exhausted", "authored_version",
        "evaluation_correction", "evaluation_exhausted",
    ],
)
def test_prepared_relational_owner_uses_complete_input_and_checkpoints_program(monkeypatch, mutation):
    with bridge_runtime(monkeypatch) as runtime:
        documents, data = prepare(runtime)
        module = importlib.import_module("functions_orchestration_native_results")
        checkpoints = importlib.import_module("functions_orchestration_checkpoints")
        contracts = importlib.import_module("functions_orchestration_result_contracts")
        analysis_access = importlib.import_module("functions_analysis_access")
        snapshots = analysis_access.analysis_source_snapshot(runtime.context.source_manifest)
        preparation_question = "Prepare the complete order and price context."
        preparation_request = {
            "version": "tabular-context-request-v1",
            "datasets": [
                {
                    "alias": "sales", "document_id": "source-1",
                    "context_columns": [], "key_profiles": [],
                },
                {
                    "alias": "catalog", "document_id": "source-2",
                    "context_columns": [], "key_profiles": [],
                },
            ],
        }
        prep_step = {
            "step_id": "prepare", "capability_id": "tabular_analyze", "role": "reason",
            "enabled": True, "inputs": {}, "depends_on": [],
            "arguments": {
                "question": preparation_question, "native_operation": "prepare",
                "document_ids": ["source-1", "source-2"],
                "preparation_request": preparation_request,
            },
            "outputs": [
                {"name": "context", "kind": "structured-v1"},
                {"name": "coverage", "kind": "structured-v1"},
            ],
        }
        parent = runtime.native.parents.read_item("parent-run", runtime.context.conversation_id)
        parent["plan"]["steps"] = [deepcopy(prep_step), deepcopy(runtime.step)]
        runtime.native.parents.replace_item(parent["id"], parent)
        producer = runtime.context.result_producer(prep_step)
        source_snapshots = [
            {
                **snapshot,
                "content_sha256": hashlib.sha256(data[snapshot["document_id"]]).hexdigest(),
            }
            for snapshot in snapshots
        ]
        request_digest = hashlib.sha256(contracts.canonical_bytes({
            "question": preparation_question, "request": preparation_request,
        })).hexdigest()
        datasets = [{
            "alias": "sales", "document_id": "source-1", "sheet": "",
            "content_sha256": source_snapshots[0]["content_sha256"],
            "selection": {}, "headers": ["code", "quantity"],
            "physical_row_count": 2, "context_columns": [], "key_profiles": [],
        }, {
            "alias": "catalog", "document_id": "source-2", "sheet": "",
            "content_sha256": source_snapshots[1]["content_sha256"],
            "selection": {}, "headers": ["sku", "price"],
            "physical_row_count": 2, "context_columns": [], "key_profiles": [],
        }]
        context_value = {
            "version": "tabular-calculation-context-v1", "complete": True,
            "source_snapshots": source_snapshots,
            "analytical_request_sha256": request_digest,
            "datasets": datasets,
            "limitations": [],
        }
        context_value["profile_sha256"] = hashlib.sha256(contracts.canonical_bytes({
            "datasets": datasets,
            "source_snapshots": source_snapshots,
            "analytical_request_sha256": request_digest,
        })).hexdigest()
        complete = contracts.Completeness(
            "complete", 1, 1, contracts.Coverage(2, 2, "sources"), "valid",
            ("complete_preparation",), (),
        )
        preparation = runtime.service.persist_task_result(
            producer=producer, role="reason", status="complete",
            outputs=[runtime.module.NamedOutput(
                "context", "structured-v1", context_value, complete,
            ), runtime.module.NamedOutput(
                "coverage", "structured-v1", {
                    "complete": True, "source_snapshots": source_snapshots,
                    "profile_sha256": context_value["profile_sha256"],
                    "analytical_request_sha256": context_value["analytical_request_sha256"],
                    "datasets": [
                        {"document_id": item["document_id"]} for item in context_value["datasets"]
                    ],
                }, complete,
            )],
            sources=snapshots, origin="grounded",
            source_policy="current", guard_token="preparation-token",
        )
        runtime.context.task_results = {"prepare": preparation}
        runtime.step["capability_id"] = "tabular_analyze"
        runtime.step["arguments"] = {
            "question": "Calculate exact order amounts from complete context.",
            "native_operation": "relate", "document_ids": ["source-1", "source-2"],
            "calculation_mode": "prepared-v1",
        }
        runtime.step["inputs"] = {
            "preparation": {
                "binding": {
                    "version": "orchestration-input-binding-v1", "step_id": "prepare",
                    "output_name": "context", "existing_result": None,
                },
                "allow_partial": False,
            },
        }
        runtime.step["outputs"] = [
            {"name": name, "kind": kind}
            for name, kind in (
                ("records", "records-v1"), ("lineage", "records-v1"),
                ("coverage", "structured-v1"),
            )
        ]
        runtime.context.resolved_message = preparation_question
        runtime.context.plan_steps = [deepcopy(prep_step), deepcopy(runtime.step)]
        parent["plan"]["steps"][1] = deepcopy(runtime.step)
        runtime.native.parents.replace_item(parent["id"], parent)
        spec = join_spec()
        spec["datasets"][0]["document_id"] = "source-1"
        spec["datasets"][1]["document_id"] = "source-2"
        calls = []
        prompts = []
        faulty_replies = {
            "two_corrections": 2, "correction_exhausted": 3,
            "evaluation_correction": 1, "evaluation_exhausted": 3,
        }.get(mutation, 0)

        def invoke(prompt, *, stage, metadata):
            calls.append((stage, metadata))
            prompts.append(json.loads(prompt))
            if len(calls) <= faulty_replies:
                faulty = deepcopy(spec)
                if mutation.startswith("evaluation"):
                    # Well formed, and every column exists: it fails only on the data, where
                    # the quantity cells are text and the comparison is not typed.
                    amount = faulty["steps"][1]["transform"]["fields"][0]
                    amount["expression"] = {
                        "op": "case", "else": deepcopy(amount["expression"]),
                        "branches": [{
                            "when": {"op": "gt", "left": {"source": "sales.quantity"}, "right": {"value": 1}},
                            "then": deepcopy(amount["expression"]),
                        }],
                    }
                else:
                    faulty["steps"][0]["on"][0]["right"] = "catalog.missing"
                return json.dumps(faulty)
            if mutation == "authored_version":
                # The author names the other format; the operations decide, with no correction.
                return json.dumps({**spec, "version": "tabular-relate-v2"})
            return json.dumps(spec)

        invoke.enforces_complete_generation = True
        runtime.context.invoke_prompt = invoke
        binding = "lowering-binding"
        checkpoint_container = ResultContainer()
        checkpoint_store = checkpoints.CheckpointStore(
            checkpoint_container, run_id="parent-run", user_id=USER,
            conversation_id="conversation-1", turn_id="turn-1",
            authorize=lambda: True, token="execution-token", claim_id="claim-1",
        )
        checkpoint_store.initialize()
        runtime.context.completeness_store = checkpoint_store
        runtime.context.completeness_binding = binding

        def fingerprint(step, context):
            value = checkpoints.step_input_fingerprint(
                step, context, binding, settings=runtime.native.settings,
            )
            return value

        fingerprint(runtime.step, runtime.context)
        runtime.bound = replace(
            module.build_native_orchestration_bridge(native_operation="relate"),
            input_fingerprint_for_step=fingerprint,
        )
        if mutation in {"saved_unsupported", "saved_wrong_sources"}:
            rejected = deepcopy(spec)
            if mutation == "saved_unsupported":
                rejected["version"] = "unsupported-program-contract"
            else:
                rejected["datasets"][0]["document_id"] = "outside-approved-selection"
            checkpoint_store.save_lowering_state(
                runtime.step["step_id"], {
                    "version": "tabular-program-lowering-v1",
                    "phase": "program_saved", "calls_used": 1,
                    "completion_contract_version": "harness-stop-v1",
                    "completion_confirmed": True, "program": rejected,
                    "program_sha256": hashlib.sha256(
                        contracts.canonical_bytes(rejected)
                    ).hexdigest(),
                }, binding=binding,
                input_fingerprint=fingerprint(runtime.step, runtime.context),
            )
        elif mutation == "resume_correction":
            rejected = deepcopy(spec)
            rejected["steps"][0]["on"][0]["right"] = "catalog.missing"
            checkpoint_store.save_lowering_state(
                runtime.step["step_id"], {
                    "version": "tabular-program-lowering-v1",
                    "phase": "failure_saved", "calls_used": 1,
                    "completion_contract_version": "harness-stop-v1",
                    "completion_confirmed": True, "program": rejected,
                    "program_sha256": hashlib.sha256(
                        contracts.canonical_bytes(rejected)
                    ).hexdigest(),
                    "last_failure": {
                        "category": "relational_column_missing",
                        "check": "column_missing", "step_index": 0,
                        "program": rejected,
                    },
                }, binding=binding,
                input_fingerprint=fingerprint(runtime.step, runtime.context),
            )
        failures = []
        runtime.native.patcher.setattr(
            module, "log_event", lambda _message, extra=None, **_kwargs: failures.append(extra),
        )
        initial_commits = len(commits(runtime))
        if mutation == "body":
            key = ("user-documents", documents["source-2"]["blob_path"])
            runtime.native.blobs.values[key]["bytes"] = b"sku,price\n008,0.21\n007,0.10\n"
        elif mutation == "request":
            runtime.context.resolved_message = "Calculate a different approved request."
        elif mutation == "selector":
            runtime.context.plan_steps[0]["arguments"]["preparation_request"]["datasets"][0][
                "header_row"
            ] = 2
        result = execute(runtime)
        if mutation in ("correction_exhausted", "evaluation_exhausted"):
            assert result["status"] == "failed", result
            assert len(calls) == module.LOWERING_MAX_CALLS == checkpoints.LOWERING_STATE_MAX_CALLS == 3
            assert len(commits(runtime)) == initial_commits
            assert "catalog.missing" not in json.dumps(failures, default=str)
            return
        if mutation not in (
            None, "resume_correction", "two_corrections", "authored_version", "evaluation_correction",
        ):
            assert result["status"] == "failed", result
            assert result["failure"]["native_code"] in {
                "native_inputs_unsupported", "native_access_unavailable",
                "native_source_changed", "native_execution_failed",
            }
            assert calls == [] and len(commits(runtime)) == initial_commits
            return
        assert result["status"] == "completed", json.dumps(
            {"result": result, "diagnostics": failures}, default=str, indent=2,
        )
        assert len(calls) == {"two_corrections": 3, "evaluation_correction": 2}.get(mutation, 1)
        if mutation == "evaluation_correction":
            # The evaluator's finding went back to the author with its own program: which step
            # and operand, what it expected and what it found. No cell value.
            assert "rejection" not in prompts[0]
            rejection = prompts[1]["rejection"]["location"]
            assert rejection["category"] == "comparison" and rejection["step_op"] == "derive"
            assert rejection["left_category"] == "string" and rejection["right_category"] == "number"
            assert prompts[1]["rejected_program"]["steps"][1]["transform"]["fields"][0]["expression"]["op"] == "case"
            assert "comparison_operands_have_incompatible_types" in prompts[1]["instructions"]
            returned = [item for item in failures if (item or {}).get("correction_origin") == "evaluation"]
            assert len(returned) == 1 and returned[0]["calls_used"] == 1 and returned[0]["calls_limit"] == 3
        assert calls[0][1]["require_complete_generation"] is True
        if mutation == "two_corrections":
            assert "rejection" not in prompts[0]
            for corrected in prompts[1:]:
                feedback = corrected["rejection"]["feedback"]
                assert feedback["missing_columns"] == ["catalog.missing"]
                assert "catalog.sku" in feedback["available_columns"]
                assert corrected["rejected_program"]["steps"][0]["on"][0]["right"] == "catalog.missing"
            assert "catalog.missing" not in json.dumps(failures, default=str)
        state = checkpoint_store.load_lowering_state(
            "compute", binding=binding, input_fingerprint=fingerprint(
                runtime.step, runtime.context,
            ),
        )
        assert state["phase"] == "retained"
        assert state["calls_used"] == {
            "resume_correction": 2, "two_corrections": 3, "evaluation_correction": 2,
        }.get(mutation, 1)
        assert state["completion_confirmed"] is True
        assert state["program_sha256"] == hashlib.sha256(
            contracts.canonical_bytes(spec)
        ).hexdigest()


def test_source_schema_assertion_failure_is_not_reported_as_missing_named_outputs(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        prepare(runtime)
        runtime.step["arguments"]["relational_spec"]["datasets"][0]["columns"] = ["code"]
        result = execute(runtime)
        assert result["status"] == "failed"
        assert result["failure"]["code"] == "source_schema_mismatch"
        assert result["failure"]["native_code"] == "native_source_schema_mismatch"
        assert "complete source header" in result["error"]
        assert commits(runtime) == []
        assert runtime.provider.calls == []


def test_saved_lowering_program_requires_supported_completion_and_exact_digest(monkeypatch):
    module = importlib.import_module("functions_orchestration_checkpoints")
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    container = ResultContainer()
    store = module.CheckpointStore(
        container, run_id="parent-run", user_id=USER,
        conversation_id="conversation-1", turn_id="turn-1",
        authorize=lambda: True, token="execution-token", claim_id="claim-1",
    )
    store.initialize()
    program = join_spec()
    digest = hashlib.sha256(contracts.canonical_bytes(program)).hexdigest()
    state = {
        "version": "tabular-program-lowering-v1",
        "phase": "program_saved", "calls_used": 1,
        "completion_contract_version": "harness-stop-v1",
        "completion_confirmed": True, "program": program,
        "program_sha256": digest,
    }
    store.save_lowering_state(
        "compute", state, binding="lowering-binding",
        input_fingerprint="a" * 64,
    )
    loaded = store.load_lowering_state(
        "compute", binding="lowering-binding", input_fingerprint="a" * 64,
    )
    assert loaded == state
    for change in ("digest", "contract"):
        invalid = deepcopy(state)
        if change == "digest":
            invalid["program_sha256"] = "0" * 64
        else:
            invalid["completion_contract_version"] = "unsupported-contract"
        with pytest.raises(module.CheckpointError):
            store.save_lowering_state(
                "compute", invalid, binding="lowering-binding",
                input_fingerprint="a" * 64,
            )
    correction = {
        "category": "relational_column_missing",
        "check": "column_missing", "step_index": 0, "program": program,
    }
    store.save_lowering_state(
        "resume", {
            **state, "phase": "failure_saved", "last_failure": correction,
        }, binding="lowering-binding", input_fingerprint="a" * 64,
    )
    resumed = store.load_lowering_state(
        "resume", binding="lowering-binding", input_fingerprint="a" * 64,
    )
    assert resumed["last_failure"]["program"] == program
    item_id = f"lowering:{module.fingerprint('compute')}"
    saved = container.read_item(item_id, "parent-run")
    saved["state"]["program_sha256"] = "0" * 64
    container.replace_item(
        saved["id"], saved, etag=saved["_etag"],
        match_condition=MatchConditions.IfNotModified,
    )
    with pytest.raises(module.CheckpointError):
        store.load_lowering_state(
            "compute", binding="lowering-binding",
            input_fingerprint="a" * 64,
        )


def test_program_correction_never_repairs_genuine_interval_or_numeric_faults():
    native = importlib.import_module("functions_orchestration_native_results")
    relational = importlib.import_module("functions_tabular_relational")
    # A join whose matches contradict its declared cardinality is still never returned.
    assert native._safe_program_correction(relational.TabularRelationalError(
        "relational_match_ambiguous", detail={"check": "left_reuse", "step_index": 5},
    )) is None
    transformations = importlib.import_module("functions_tabular_transformations")
    stopped = transformations.TabularTransformationEvaluationError("Numeric value is invalid")
    stopped.detail = {
        "check": "step_evaluation", "step_index": 4, "step_op": "aggregate", "role": "aggregate_measure",
        "measure_index": 2, "left_category": "string", "expected_type": "number", "value": "private cell",
    }
    returned = native._safe_program_correction(stopped)
    assert returned == {
        "category": "numeric_value_is_invalid", "check": "step_evaluation", "step_index": 4,
        "origin": "evaluation", "location": {
            "step_op": "aggregate", "role": "aggregate_measure", "measure_index": 2,
            "left_category": "string", "expected_type": "number",
        },
    }
    assert native._saved_correction_admissible(returned)
    assert not native._saved_correction_admissible({"category": "relational_match_ambiguous", "step_index": 1})
    assert native._safe_program_correction(relational.TabularRelationalError(
        "relational_match_ambiguous",
        detail={"check": "effective_interval_overlap", "step_index": 1},
    )) is None
    assert native._safe_program_correction(relational.TabularRelationalError(
        "relational_numeric_invalid",
        detail={"check": "cumulative_value", "step_index": 2},
    )) is None
    correction = native._safe_program_correction(relational.TabularRelationalError(
        "relational_column_missing",
        detail={"check": "column_missing", "step_index": 0},
    ))
    assert correction == {
        "category": "relational_column_missing",
        "check": "column_missing",
        "step_index": 0,
    }
    named = relational._missing_columns_error(
        ("catalog.sku", "catalog.price"), ["catalog.missing"], "join_right_key",
        frozenset({"catalog"}), {"step_index": 0, "step_op": "join"},
    )
    assert "catalog.missing" not in json.dumps(named.detail)
    assert "catalog.missing" not in json.dumps(relational.native_error_diagnostics(named))
    named_correction = native._safe_program_correction(named)
    assert named_correction["feedback"] == {
        "missing_columns": ["catalog.missing"],
        "available_columns": ["catalog.sku", "catalog.price"],
    }
    assert named_correction["location"]["role"] == "join_right_key"
    prompt = json.loads(native._prepared_program_prompt(
        "Approved request.", {"version": "tabular-calculation-context-v1"},
        {"type": "object"}, correction={
            **correction, "program": join_spec(),
        },
    ))
    assert prompt["rejected_program"] == join_spec()


def test_native_prepare_retains_complete_context_and_exact_profiles(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        prepare(runtime)
        runtime.bound = runtime.module.build_native_orchestration_bridge(native_operation="prepare")
        runtime.step["arguments"] = {
            "question": "Prepare the complete order and price context.",
            "native_operation": "prepare", "document_ids": ["source-1", "source-2"],
            "preparation_request": {
                "version": "tabular-context-request-v1",
                "datasets": [{
                    "alias": "orders", "document_id": "source-1",
                    "context_columns": ["code"], "key_profiles": [
                        {"name": "order_keys", "columns": ["code", "quantity"]},
                    ],
                }, {
                    "alias": "prices", "document_id": "source-2",
                    "context_columns": ["sku"], "key_profiles": [
                        {"name": "price_keys", "columns": ["sku"]},
                    ],
                }],
            },
        }
        runtime.step["outputs"] = [
            {"name": output.name, "kind": output.kind} for output in runtime.bound.output_specs
        ]
        result = execute(runtime)
        assert result["status"] == "completed", result
        task = result["task_result"]
        context = runtime.service.open_result(task.output("context")).read_value()
        coverage = runtime.service.open_result(task.output("coverage")).read_value()
        assert context["version"] == "tabular-calculation-context-v1"
        assert context["datasets"][0]["headers"] == ["code", "quantity"]
        assert context["datasets"][0]["context_columns"][0]["distinct_values"] == [
            {"value": "007", "rows": [2]}, {"value": "008", "rows": [3]},
        ]
        assert context["datasets"][0]["key_profiles"][0]["distinct_count"] == 2
        assert all(
            len(dataset["content_sha256"]) == 64 for dataset in context["datasets"]
        )
        snapshots = importlib.import_module(
            "functions_analysis_access",
        ).analysis_source_snapshot(runtime.context.source_manifest)
        assert context["source_snapshots"] == [
            {**source, "content_sha256": dataset["content_sha256"]}
            for source, dataset in zip(snapshots, context["datasets"])
        ]
        assert coverage["input_rows"] == 4 and coverage["complete"] is True
        assert runtime.provider.calls == [] and runtime.native.jobs.created == 0


def test_preparation_argument_rejects_duplicate_profile_names(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        module = runtime.module
        arguments = {
            "question": "Prepare keys.",
            "native_operation": "prepare", "document_ids": ["source-1"],
            "preparation_request": {
                "version": "tabular-context-request-v1",
                "datasets": [{
                    "alias": "source", "document_id": "source-1", "context_columns": [],
                    "key_profiles": [
                        {"name": "same", "columns": ["left"]},
                        {"name": "same", "columns": ["right"]},
                    ],
                }],
            },
        }
        with pytest.raises(module.NativeOrchestrationBridgeError) as error:
            module.validate_native_orchestration_arguments(arguments)
        assert error.value.code == "native_arguments_invalid"


@pytest.mark.parametrize("fault,native_code,logged", [
    ("column", "native_relational_invalid", {
        "execution_code": "relational_column_missing", "native_check": "column_missing",
        "native_role": "join_right_key", "native_category": "name_not_in_prefix",
        "native_step_op": "join", "native_step_index": 0, "native_missing_count": 1,
    }),
    ("evaluation", "native_execution_failed", {
        "execution_code": "division_by_zero_is_not_allowed", "native_check": "step_evaluation",
        "native_step_op": "derive", "native_step_index": 1,
    }),
])
def test_runtime_failures_log_a_stable_code_and_location_without_source_values(monkeypatch, fault, native_code, logged):
    with bridge_runtime(monkeypatch) as runtime:
        prepare(runtime)
        records = []
        runtime.native.patcher.setattr(
            runtime.module, "log_event", lambda message, extra=None, **kwargs: records.append(dict(extra or {})),
        )
        spec = runtime.step["arguments"]["relational_spec"]
        if fault == "column":
            spec["steps"][0]["on"][0]["right"] = "catalog.private_marker_typo"
        else:
            spec["steps"][1]["transform"]["fields"][0]["expression"] = {
                "op": "divide", "values": [{"source": "sales.quantity"}, 0],
            }
        result = execute(runtime)
        assert result["status"] == "failed" and result["failure"]["native_code"] == native_code
        assert len(records) == 1 and logged.items() <= records[0].items()
        assert "private_marker" not in repr(records) and "007" not in repr(records)
        assert commits(runtime) == [] and runtime.provider.calls == []


def test_real_compiler_executor_and_export_consume_trusted_legacy_manual_rows(runtime, monkeypatch):
    module = importlib.import_module("functions_orchestration_native_results")
    spec = join_spec()
    step = {
        "step_id": "calculate", "capability_id": "tabular_analyze",
        "arguments": {
            "question": "Calculate exact order amounts across the selected files.",
            "native_operation": "relate", "document_ids": ["sales", "catalog"], "relational_spec": spec,
        },
    }
    monkeypatch.setattr(
        runtime.schema, "validate_generated_plan_tabular_admission", lambda _plan: None,
    )
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
