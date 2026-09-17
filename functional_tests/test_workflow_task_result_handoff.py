# test_workflow_task_result_handoff.py
"""
Functional regression for workflow result production, persistence, and handoff.
Version: 0.261.122
Implemented in: 0.261.106

Fictional inventory records pass through the production document analysis,
artifact presentation, task dispatch, and sequence implementations. Only
external services are replaced; the upstream task result is not hand-built.
"""

import ast
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ServiceRequestError

from test_document_analysis_lossless_artifacts import build_window, load_module_functions
from test_workflow_result_store import FakeBlobService, FakeCosmosContainer
from test_support.workflow_results import workflow_result_helpers
from functions_workflow_alert_safety import sanitize_workflow_alert_record
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_results import (
    build_workflow_task_result,
    load_workflow_task_input,
    persist_workflow_task_result,
    authorize_workflow_task_result_read,
)


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
RUNNER = APP_ROOT / "functions_workflow_runner.py"
ANALYSIS = APP_ROOT / "functions_document_analysis.py"


class RunItemsContainer(FakeCosmosContainer):
    def upsert_item(self, body):
        key = (body["run_id"], body["id"])
        self.records[key] = json.loads(json.dumps(body))
        return json.loads(json.dumps(self.records[key]))


def _load_production_functions(path, namespace):
    """Use real function bodies without bootstrapping live Azure clients."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    constants[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
    return load_module_functions(str(path), {**constants, **namespace})


def build_inventory_run(record_count=1, note_size=0, *, blob=True):
    records = [
        {"item_id": f"inventory-{index:04d}", "quantity": index + 1, "note": "x" * note_size}
        for index in range(record_count)
    ]
    records[len(records) // 2]["note"] = (
        "x" * (note_size // 2) + "MIDDLE-INVENTORY-RECORD-MUST-SURVIVE" + "x" * (note_size // 2)
    )
    provider_output = json.dumps(records)
    provider_requests = []
    uploaded_artifacts = {}
    container = RunItemsContainer()
    blob_service = FakeBlobService() if blob else None
    loaded_refs = []

    def result_store():
        # A new store instance on every operation rules out an in-memory handoff.
        return WorkflowResultStore(container, blob_service, "private-chat-results")

    def save_section(workflow, run_id, task_id, data, **kwargs):
        return result_store().save(workflow, run_id, task_id, data)

    def load_section(workflow, run_id, task_id, reference):
        loaded_refs.append(dict(reference))
        return result_store().load(workflow, run_id, task_id, reference)

    def completion(**kwargs):
        provider_requests.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]
        if prompt.startswith("Write only an unrelated note"):
            explanation = "An intermediate note with no inventory findings."
        elif "[Previous workflow task output]" in prompt:
            serialized = prompt.split("[Previous workflow task output]\n", 1)[1].split(
                "\n\nUse the previous task output", 1,
            )[0]
            consumed = json.loads(serialized)
            if "inputs" in consumed:
                consumed = consumed["inputs"][0]["result"]
            assert consumed["kind"] == "records"
            findings = consumed["value"]
            explanation = (
                f"Inventory contains {len(findings)} items and "
                f"{sum(row['quantity'] for row in findings)} units."
            )
        else:
            explanation = provider_output
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=explanation,
            ))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))

    def upload_artifact(**kwargs):
        artifact_id = f"artifact-{len(uploaded_artifacts) + 1}"
        uploaded_artifacts[artifact_id] = kwargs["file_content"]
        return {"message": {"id": artifact_id, "file_name": kwargs["file_name"]}}

    store_source = APP_ROOT / "functions_personal_workflows.py"
    store_nodes = [
        node for node in ast.parse(store_source.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"save_personal_workflow_run_item", "_strip_cosmos_metadata"}
    ]
    store_namespace = {
        "uuid": uuid,
        "cosmos_personal_workflow_run_items_container": container,
        "sanitize_workflow_alert_record": sanitize_workflow_alert_record,
    }
    exec(compile(ast.Module(body=store_nodes, type_ignores=[]), str(store_source), "exec"), store_namespace)

    def unexpected_workspace_write(*args, **kwargs):
        raise AssertionError("Result consumption must not upload or re-index a workspace document.")

    analysis = _load_production_functions(ANALYSIS, {
        "time": time,
        "log_event": lambda *args, **kwargs: None,
        "debug_print": lambda *args, **kwargs: None,
        "normalize_search_id_list": lambda values: list(values or []),
        "normalize_search_scope": lambda value: value or "personal",
    })
    analysis["_get_mixed_source_orchestration_helpers"] = lambda: (
        type("AnalysisCancelled", (BaseException,), {}),
        lambda *args, **kwargs: None,
    )
    analysis["_get_search_service_helpers"] = lambda: (
        lambda chunks, **kwargs: chunks,
        lambda document_id, **kwargs: {
            "document": {"id": document_id, "file_name": "fictional-inventory.txt"},
            "scope": "personal",
            "scope_id": "owner",
            "chunks": [build_window(1, 1, 1, "Fictional inventory evidence.")],
            "chunk_count": 1,
        },
    )

    runner = _load_production_functions(RUNNER, {
        **workflow_result_helpers(),
        "datetime": datetime,
        "timezone": timezone,
        "uuid": uuid,
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "debug_print": lambda *args, **kwargs: None,
        "has_request_context": lambda: True,
        "raise_if_mixed_source_cancelled": lambda *args, **kwargs: None,
        "normalize_mixed_source_correlation_id": lambda value: value,
        "MixedSourceCancellationError": type("MixedSourceCancelled", (BaseException,), {}),
        "AgentExecutionCancelled": type("AgentCancelled", (BaseException,), {}),
        "DOCUMENT_ACTION_TYPE_NONE": "none",
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "DOCUMENT_ACTION_TYPE_COMPARISON": "compare",
        "DOCUMENT_ACTION_TYPE_SEARCH": "search",
        "DOCUMENT_ACTION_CONTEXT_WORKFLOW": "workflow",
        "DOCUMENT_ACTION_ANALYSIS_MODE_PER_DOCUMENT": "per_document",
        "normalize_document_action_analysis_mode": lambda value: value or "combined",
        "get_document_action_max_documents": lambda *args, **kwargs: 10,
        "get_settings": lambda: {},
        "get_document_action_config": lambda source, **kwargs: source.get("document_action") or {"type": "none"},
        "get_document_action_max_documents_by_type": lambda *args, **kwargs: {},
        "get_enabled_document_action_types": lambda **kwargs: ["none", "analyze"],
        "build_analyze_config": lambda action: {"enabled": action.get("type") == "analyze"},
        "normalize_personal_workflow_task_runner": lambda *args, **kwargs: {"type": "inherit"},
        "upload_generated_analysis_artifact_for_current_user": upload_artifact,
        "append_proactive_chart_guidance": lambda prompt: prompt,
        "build_generated_file_output_guidance": lambda prompt: "",
        "upload_generated_document_for_current_user": unexpected_workspace_write,
        "queue_generated_document_processing": unexpected_workspace_write,
    })
    runner.update({
        "_result_reads": loaded_refs,
        "_load_result_section": load_section,
        # These fixtures deliberately exercise the legacy producer contract; modern
        # work-unit guards are covered by test_analyze_live_write_fences.py.
        "_prepare_workflow_analysis_checkpoints": lambda *args, **kwargs: None,
        "_raise_if_workflow_run_cancelled": lambda *args, **kwargs: None,
        "_resolve_model_workflow_client": lambda *args, **kwargs: (
            runner["WorkflowModelClient"](client, {
                "modelName": "inventory-fixture",
                "contextWindow": 128000,
                "outputTokenLimit": 32768,
                "outputTokenAccounting": "total_generation",
            }, "aoai"), "inventory-fixture", "aoai",
        ),
        "save_personal_workflow_run_item": store_namespace["save_personal_workflow_run_item"],
        "persist_workflow_task_result": lambda envelope, **kwargs: persist_workflow_task_result(
            envelope, **{"save_result": save_section, **kwargs},
        ),
        "load_workflow_task_input": lambda workflow, run_id, task_id, reference, **kwargs: load_workflow_task_input(
            workflow, run_id, task_id, reference, load_result=load_section, **kwargs,
        ),
        "authorize_workflow_task_result_read": lambda *args, **kwargs: authorize_workflow_task_result_read(
            *args, load_result=load_section, **kwargs,
        ),
        "_initialize_document_run_items": lambda *args, **kwargs: None,
        "_build_run_item_activity_callback": lambda *args, **kwargs: None,
        "_resolve_recent_document_action_targets": lambda workflow, action, settings: action,
        "_reauthorize_mixed_source_workflow_result": lambda *args, **kwargs: None,
        "_execute_mixed_source_analyze_workflow": lambda workflow, config, settings, invoke_prompt, **kwargs: (
            analysis["run_document_analysis"](
                user_id="owner",
                analysis_prompt=workflow["task_prompt"],
                document_ids=config["document_ids"],
                invoke_prompt=invoke_prompt,
                max_documents=10,
                include_coverage_summary=False,
            )
        ),
    })
    workflow = {
        "id": "workflow-inventory",
        "user_id": "owner",
        "runner_type": "model",
        "chat_capabilities_enabled": False,
        "tasks": [
            {
                "id": "extract",
                "name": "Extract inventory",
                "instructions": "Extract all inventory records as a JSON array in a JSON artifact.",
                "document_action": {"type": "analyze", "document_ids": ["inventory-source"]},
            },
            {
                "id": "consume",
                "name": "Consume inventory",
                "instructions": "Use every extracted inventory record.",
                "document_action": {"type": "none"},
            },
        ],
    }
    return runner, workflow, records, provider_requests, uploaded_artifacts, container.records


@pytest.mark.parametrize("record_count,note_size,blob", [
    (1, 20000, True), (10, 1500, False), (100, 160, True), (500, 32, True),
])
def test_analyze_artifact_content_reaches_next_task(record_count, note_size, blob):
    runner, workflow, records, requests, artifacts, items = build_inventory_run(record_count, note_size, blob=blob)
    result = runner["_execute_workflow_task_sequence"](
        workflow, {}, "conversation-inventory", "run-inventory", None, {},
    )

    assert artifacts, "The production Analyze path must produce an actual artifact."
    assert any("MIDDLE-INVENTORY-RECORD-MUST-SURVIVE" in str(value) for value in artifacts.values())
    first_task = result["task_results"][0]
    assert first_task["status"] == "succeeded"
    downstream_prompt = requests[-1]["messages"][-1]["content"]
    for record in records:
        assert record["item_id"] in downstream_prompt
    assert "MIDDLE-INVENTORY-RECORD-MUST-SURVIVE" in downstream_prompt
    assert "[Previous task output truncated]" not in downstream_prompt
    assert items, "The sequence must use the production task persistence path."
    assert result["reply"].endswith(
        f"Inventory contains {record_count} items and {sum(row['quantity'] for row in records)} units."
    )
    producer = result["task_results"][0]["workflow_result"]
    consumer = result["task_results"][1]["workflow_result"]
    consumed = consumer["consumed_inputs"][0]
    assert consumed["producer"]["task_id"] == "extract"
    assert consumed["producer"]["run_id"] == "run-inventory"
    assert consumed["result_ref"] == producer["result_ref"]
    assert consumed["output_name"] == producer["authoritative_output"] == "records"
    assert consumed["output_ref"] == producer["outputs"]["records"]["result_ref"]
    assert runner["_result_reads"][:2] == [producer["result_ref"], consumed["output_ref"]]
    assert runner["_result_reads"].count(consumed["output_ref"]) == 1
    assert all(reference == producer["result_ref"] for reference in runner["_result_reads"][2:])
    persisted_consumer = items[(
        "run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "consume"),
    )]
    assert persisted_consumer["workflow_result"]["consumed_inputs"] == [consumed]


def test_storage_failure_does_not_replay_the_completed_model_task():
    runner, workflow, records, requests, artifacts, items = build_inventory_run()
    workflow["error_handling"] = {"strategy": "halt", "retry_count": 3}

    def fail_persistence(*args, **kwargs):
        raise ServiceRequestError("PRIVATE-PROVIDER-DETAIL-MUST-NOT-LEAK")

    runner["persist_workflow_task_result"] = fail_persistence
    with pytest.raises(RuntimeError, match="full task result could not be saved") as caught:
        runner["_execute_workflow_task_sequence"](
            workflow, {}, "conversation-inventory", "run-inventory", None, {},
        )
    assert len(requests) == 1
    assert "PRIVATE-PROVIDER-DETAIL" not in str(caught.value)
    failed = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "extract"))]
    assert failed["status"] == "failed"
    assert not any(item.get("task_id") == "consume" for item in items.values())


@pytest.mark.parametrize("legacy_checkpoint", [False, True])
def test_m365_resume_hands_off_complete_checkpoint_without_repeating_the_producer(legacy_checkpoint):
    runner, workflow, records, requests, artifacts, items = build_inventory_run(100, 160)
    checkpoints = {}
    awaiting_sign_in = True
    dispatch = runner["_execute_workflow_dispatch"]

    def save_checkpoint(task_id, task_result):
        checkpoints[task_id] = json.loads(json.dumps(task_result))

    def dispatch_with_sign_in(attempt_workflow, *args, **kwargs):
        if attempt_workflow["active_task"]["id"] == "consume" and awaiting_sign_in:
            raise runner["M365SignInRequired"]("m365_connection_required")
        return dispatch(attempt_workflow, *args, **kwargs)

    runner.update({
        "read_m365_task_checkpoint": lambda task_id: checkpoints.get(task_id),
        "save_m365_task_checkpoint": save_checkpoint,
        "_execute_workflow_dispatch": dispatch_with_sign_in,
    })
    with pytest.raises(runner["M365SignInRequired"]):
        runner["_execute_workflow_task_sequence"](
            workflow, {}, "conversation-inventory", "run-inventory", None, {},
        )
    assert len(requests) == 1
    assert set(checkpoints) == {"extract"}
    original_artifacts = dict(artifacts)
    if legacy_checkpoint:
        checkpoints["extract"]["result"].pop("workflow_result")
        checkpoints["extract"].pop("consumed_inputs")
    awaiting_sign_in = False
    result = runner["_execute_workflow_task_sequence"](
        workflow, {}, "conversation-inventory", "run-inventory", None, {},
    )
    assert len(requests) == 2, "Resuming must not repeat the producer's external work."
    assert artifacts == original_artifacts
    assert set(checkpoints) == {"extract", "consume"}
    producer = result["task_results"][0]["workflow_result"]
    consumer = result["task_results"][1]["workflow_result"]
    assert consumer["consumed_inputs"][0]["result_ref"] == producer["result_ref"]
    assert consumer["consumed_inputs"][0]["producer"]["task_id"] == "extract"
    assert all(record["item_id"] in requests[-1]["messages"][-1]["content"] for record in records)
    stored = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "extract"))]
    assert stored["workflow_result"]["result_ref"] == producer["result_ref"]


def test_preview_only_checkpoint_is_not_used_as_a_complete_result():
    runner, workflow, records, requests, artifacts, items = build_inventory_run()
    runner["read_m365_task_checkpoint"] = lambda task_id: {
        "status": "succeeded", "output_summary": "Only a preview is available.",
    }
    with pytest.raises(runner["WorkflowResultNotReadyError"], match="no complete task result"):
        runner["_execute_workflow_task_sequence"](
            workflow, {}, "conversation-inventory", "run-inventory", None, {},
        )
    assert requests == []


def test_smaller_downstream_model_blocks_without_losing_source_records():
    runner, workflow, records, requests, artifacts, items = build_inventory_run(100, 160)
    original_resolver = runner["_resolve_model_workflow_client"]
    workflow["error_handling"] = {"strategy": "halt", "retry_count": 3}

    def resolve(workflow, settings):
        client, deployment, provider = original_resolver(workflow, settings)
        if workflow["active_task"]["id"] == "consume":
            client = runner["WorkflowModelClient"](client._delegate, {
                "modelName": "small-fixture",
                "contextWindow": 1024,
                "outputTokenLimit": 256,
                "outputTokenAccounting": "total_generation",
            }, provider)
            deployment = "small-fixture"
        return client, deployment, provider

    runner["_resolve_model_workflow_client"] = resolve
    with pytest.raises(RuntimeError, match="input budget"):
        runner["_execute_workflow_task_sequence"](
            workflow, {}, "conversation-inventory", "run-inventory", None, {},
        )
    assert len(requests) == 1
    producer = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "extract"))]
    consumer = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "consume"))]
    assert consumer["context_budget"]["decision"] == "blocked"
    assert consumer["consumed_inputs"][0]["producer"]["task_id"] == "extract"
    prompt, consumed = runner["load_workflow_task_input"](
        workflow, "run-inventory", "extract", producer["workflow_result"]["result_ref"],
    )
    assert json.loads(prompt)["value"] == records


def test_per_document_results_retain_final_values_without_raw_notes():
    runner, workflow, records, requests, artifacts, items = build_inventory_run()
    runner.update({
        "EVIDENCE_STATUS_PENDING": "pending",
        "EVIDENCE_STATUS_COMPLETED": "completed",
        "EVIDENCE_STATUS_FAILED": "failed",
        "EVIDENCE_STATUS_CANCELED": "canceled",
        "deduplicate_mixed_source_references": lambda values, **kwargs: values,
    })
    document_results = [
        {
            "document_id": f"source-{index}",
            "result": {
                "reply": f"Presentation for source {index}.",
                "analysis_result": {
                    "analysis_reply": json.dumps([{"item_id": f"item-{index}", "quantity": index}]),
                    "raw_analysis_items": [{"text": "DIAGNOSTIC-ONLY earlier estimate."}],
                },
                "analysis_coverage": {
                    "documents": [{"document_id": f"source-{index}", "file_name": f"inventory-{index}.txt"}],
                    "progress_meta": {"status": "completed"},
                },
            },
        }
        for index in (1, 2)
    ]
    combined = runner["_combine_per_document_analysis_results"](document_results)
    envelope = build_workflow_task_result(
        combined, workflow=workflow, run_id="run-inventory", task={"id": "extract"},
    )
    manifest, reference = runner["persist_workflow_task_result"](
        envelope, workflow=workflow, run_id="run-inventory", task_id="extract",
    )
    prompt, consumed = runner["load_workflow_task_input"](
        workflow, "run-inventory", "extract", reference,
    )
    assert json.loads(prompt)["value"] == [
        {"document_id": "source-1", "kind": "records", "value": [{"item_id": "item-1", "quantity": 1}]},
        {"document_id": "source-2", "kind": "records", "value": [{"item_id": "item-2", "quantity": 2}]},
    ]
    assert "DIAGNOSTIC-ONLY" not in prompt
    assert "Presentation for" not in prompt
    assert consumed["output_name"] == "documents"


def test_cancellation_keeps_completed_results_and_does_not_start_next_task():
    runner, workflow, records, requests, artifacts, items = build_inventory_run()
    cancelled = False
    original_persist = runner["persist_workflow_task_result"]

    def persist_then_cancel(*args, **kwargs):
        nonlocal cancelled
        persisted = original_persist(*args, **kwargs)
        cancelled = True
        return persisted

    nodes = [
        node for node in ast.parse(RUNNER.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in {"WorkflowRunCancelledError", "_raise_if_workflow_run_cancelled"}
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), "exec"), runner)
    runner["_is_workflow_run_cancellation_requested"] = lambda *args: cancelled
    runner["persist_workflow_task_result"] = persist_then_cancel
    with pytest.raises(runner["WorkflowRunCancelledError"]):
        runner["_execute_workflow_task_sequence"](
            workflow, {}, "conversation-inventory", "run-inventory", None, {},
        )
    assert len(requests) == 1
    assert not any(item.get("task_id") == "consume" for item in items.values())
    producer = items[("run-inventory", runner["_workflow_task_run_item_id"]("run-inventory", "extract"))]
    prompt, consumed = runner["load_workflow_task_input"](
        workflow, "run-inventory", "extract", producer["workflow_result"]["result_ref"],
    )
    assert producer["status"] == "succeeded"
    assert json.loads(prompt)["value"] == records
