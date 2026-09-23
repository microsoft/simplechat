# test_analyze_native_saved_integration.py
"""
Native Analyze output, adapter and saved-consumer integration regressions.
Version: 0.261.127
Implemented in: 0.261.109

Real native checkpoint serialization, adaptation and saved-section readers run
against offline run/blob/provider boundaries. No source is uploaded or re-indexed.
"""

import asyncio
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest

from test_analyze_backend_saved_integration import load_functions, mixed, runner_namespace, saved
from test_saved_analysis_service import ChatSections
from test_support.app_stubs import import_app_module
from test_support.document_analysis import (
    USER_ID, FixtureAnalysisClient, document_analysis_runtime, original_document,
)


native = import_app_module("functions_native_analysis_results")
deliverables = import_app_module("functions_analysis_deliverables")


@pytest.fixture
def native_run(monkeypatch):
    source = {
        "document_id": "native-source", "scope": "personal", "scope_id": USER_ID,
        "source_kind": "tabular", "file_name": "inventory.csv", "source_version": 1,
        "source_revision": "source-etag", "authorization_status": "authorized",
    }
    rows = [{"amount": "12.3400", "details": f"Complete output row {index}: " + "x" * 200} for index in range(150)]
    run = {
        "id": "native-run", "conversation_id": "conversation-1", "user_id": USER_ID,
        "source_file_name": source["file_name"], "source_descriptor": {"source": "workspace"},
        "status": "completed", "task_type": "combined", "row_count": len(rows),
        "processed_rows": len(rows), "batch_count": 3, "completed_batches": 3,
        "output_schema": ["source_row_number", "amount", "details"],
        "artifact_set_manifest": {"lifecycle_state": "completed"},
    }
    checkpoints = {
        f"batch-{batch}": [
            {"source_row_number": index + 1, **rows[index]} for index in range((batch - 1) * 50, batch * 50)
        ] for batch in range(1, 4)
    }
    checkpoints["final"] = {"summary": "Complete native final summary " + "y" * 16000, "row_count": len(rows)}
    reads = []
    state = {"allowed": True}

    def resolve(ids, **kwargs):
        assert ids == [source["document_id"]]
        return [{**source, "authorization_status": "authorized" if state["allowed"] else "unresolved"}]

    def load(key):
        reads.append(key)
        return deepcopy(checkpoints[key])

    namespace = {
        "json": json, "_safe_int": lambda value, default=0, **kwargs: int(value if value is not None else default),
        "_get_tabular_run_serialized_public_schema": lambda value: ["amount", "details"],
        "TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD": "source_row_number",
        "_output_blob_path": lambda user, conversation, run_id, batch: f"batch-{batch}",
        "_validate_tabular_output_checkpoint_metadata": lambda *args: None,
        "_download_json_blob": load,
        "project_structured_deliverable_row": deliverables.project_structured_deliverable_row,
    }
    load_functions(
        "functions_tabular_generated_exports.py",
        {"_write_ordered_output_stream", "iter_tabular_output_records"}, namespace,
    )
    monkeypatch.setitem(sys.modules, "functions_tabular_generated_exports", SimpleNamespace(
        _read_run=lambda *args: deepcopy(run),
        _authorize_tabular_export_run_execution=lambda value: None,
        _build_public_artifact_projection=lambda value: {
            key: item for key, item in value.items() if key not in {"blob_container", "blob_path"}
        },
        _revalidate_tabular_source_version_for_publication=lambda value: None,
        _analysis_final_blob_path=lambda *args: "final",
        _download_json_blob=load,
        _write_ordered_output_stream=namespace["_write_ordered_output_stream"],
    ))
    return SimpleNamespace(source=source, rows=rows, run=run, checkpoints=checkpoints, reads=reads, state=state, resolve=resolve)


def adapt(fixture, **kwargs):
    return native.adapt_native_analysis_result(
        user_id=USER_ID, conversation_id="conversation-1", source=fixture.source,
        generated_outputs=[{"run_id": "native-run", "status": "completed"}],
        source_resolver=fixture.resolve, **kwargs,
    )


def test_native_declared_rules_replace_reported_values_and_discard_stale_exports(native_run, monkeypatch):
    engine = sys.modules["functions_tabular_generated_exports"]
    monkeypatch.setitem(
        engine._write_ordered_output_stream.__globals__, "_get_tabular_run_serialized_public_schema",
        lambda run: ["amount", "details", "total"],
    )
    native_run.run["output_schema"].append("total")
    for key, rows in native_run.checkpoints.items():
        if key.startswith("batch-"):
            for row in rows:
                row["total"] = 93847
    native_run.run["final_artifact"] = {
        "artifact_message_id": "old-export", "output_format": "json",
    }
    rules = {
        "version": "tabular-transform-v2",
        "fields": [{
            "name": "total", "mode": "deterministic", "type": "number",
            "expression": {"op": "round", "value": {"source": "amount"}, "scale": 2, "mode": "half_up"},
        }],
    }
    result = adapt(
        native_run, analysis_options={"transformation_spec": rules, "required_fields": ["total"]},
        analysis_producer={"kind": "workflow", "workflow_id": "workflow-1", "run_id": "run-1", "task_id": "analyze"},
        bind_artifacts=lambda *args: pytest.fail("Unchecked native artifacts cannot be promoted as corrected exports."),
    )
    assert result["analysis_validation"]["status"] == "valid"
    assert all(record["values"]["total"] == 12.34 for record in result["authoritative_result"]["value"])
    assert "93847" not in result["analysis_reply"]
    assert "93847" not in json.dumps(result["analysis_validation"])
    assert result["generated_tabular_outputs"] == []
    assert result["analysis_diagnostics"]["calculations"]["issues"][0]["reported_value"] == 93847


def test_native_required_fields_cannot_silently_be_ignored(native_run):
    result = adapt(native_run, analysis_options={"required_fields": ["not_in_the_native_output"]})
    assert result["analysis_validation"]["status"] == "invalid"
    assert result["authoritative_result"]["value"] == []
    assert result["generated_tabular_outputs"] == []


def test_native_preflight_forwards_required_options_without_restoring_old_artifacts(native_run):
    old_outputs = [{"run_id": "native-run", "artifact_message_id": "old-export"}]
    runner = runner_namespace(
        resolve_analysis_source_manifest=lambda *args, **kwargs: [deepcopy(native_run.source)],
        adapt_native_analysis_result=lambda **kwargs: native.adapt_native_analysis_result(
            **kwargs, source_resolver=native_run.resolve,
        ),
    )
    runner["_maybe_execute_pure_tabular_analyze_preflight"] = lambda *args, **kwargs: {
        "generated_tabular_outputs": old_outputs,
    }
    result = runner["_execute_mixed_source_analyze_workflow"](
        {"user_id": USER_ID, "task_prompt": "Require the approval field.", "_analysis_result_version": "analyze-final-v1"},
        {
            "type": "analyze", "document_ids": ["native-source"],
            "analysis_options": {"required_fields": ["approval"]},
        },
        {}, lambda *args, **kwargs: pytest.fail("Completed native output must not be resubmitted."),
        conversation_id="conversation-1",
    )
    assert result["analysis_validation"]["status"] == "invalid"
    assert result["authoritative_result"]["value"] == []
    assert result["generated_tabular_outputs"] == []


def save_and_reload(fixture, result):
    store = ChatSections()
    descriptor = saved.save_chat_analysis(
        {"reply": result["reply"], "analysis_result": result},
        user_id=USER_ID, conversation_id="conversation-1", message_id="assistant-1",
        authorize_conversation=lambda *args: None, save_result=store.save, source_resolver=fixture.resolve,
    )
    message = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"saved_analysis": descriptor},
    }
    options = {
        "message_loader": lambda *args: message, "chat_loader": ChatSections(deepcopy(store.contents)).load,
        "source_resolver": fixture.resolve,
    }
    return descriptor, options


def test_complete_native_checkpoints_survive_saving_beyond_the_old_eight_thousand_char_limit(native_run):
    fixture = native_run
    result = adapt(fixture)
    assert fixture.reads == ["batch-1", "batch-2", "batch-3"]
    assert len(result["analysis_reply"]) > 8000
    assert [record["values"] for record in result["authoritative_result"]["value"]] == fixture.rows
    descriptor, options = save_and_reload(fixture, result)
    del result
    payload, _ = saved.load_saved_analysis_input(USER_ID, saved.saved_analysis_context(descriptor), **options)
    assert [record["values"] for record in json.loads(payload)["records"]] == fixture.rows
    assert len(fixture.reads) == 3
    fixture.state["allowed"] = False
    with pytest.raises(PermissionError):
        saved.read_saved_analysis_page(USER_ID, saved.saved_analysis_context(descriptor), **options)
    assert len(fixture.reads) == 3


@pytest.mark.parametrize("state,execution", [
    ("queued", "pending"), ("running", "pending"), ("retrying", "pending"),
    ("failed", "failed"), ("canceled", "cancelled"),
])
def test_native_nonterminal_or_failed_state_never_accepts_a_preview(native_run, state, execution):
    native_run.run["status"] = state
    result = adapt(native_run, complete_output={"status": "completed", "kind": "records", "value": [{"fake": "preview"}]})
    assert result["execution_status"] == execution
    assert result["authoritative_result"]["value"] == []
    assert native_run.reads == []
    descriptor, options = save_and_reload(native_run, result)
    assert descriptor["execution_status"] == execution
    with pytest.raises(ValueError, match="no readable accepted result"):
        saved.load_saved_analysis_input(USER_ID, saved.saved_analysis_context(descriptor), **options)


def test_native_checkpoint_gap_fails_instead_of_substituting_a_summary(native_run):
    native_run.checkpoints["batch-2"][0]["source_row_number"] = 1
    with pytest.raises(ValueError, match="gap or overlap"):
        adapt(native_run)


def test_native_final_summary_uses_the_durable_final_not_the_output_card_preview(native_run):
    native_run.run["task_type"] = "hierarchical_analysis"
    result = adapt(native_run)
    assert native_run.reads == ["final"]
    assert result["authoritative_result"]["value"][0]["values"] == native_run.checkpoints["final"]
    assert len(result["authoritative_result"]["value"][0]["values"]["summary"]) > 8000
    assert result["analysis_validation"]["checks"][-1]["status"] == "not_performed"


def test_source_denial_precedes_any_native_output_read(native_run):
    native_run.state["allowed"] = False
    with pytest.raises(PermissionError):
        adapt(native_run)
    assert native_run.reads == []


def test_foreground_output_requires_the_native_file_and_scope_proof(native_run):
    complete = {
        "status": "completed", "kind": "records", "value": [{"finding": "Final native output"}],
        "source_file_name": "a-different-file.csv", "source_authorization": {"source": "workspace"},
    }
    with pytest.raises(PermissionError):
        native.adapt_native_analysis_result(
            user_id=USER_ID, conversation_id="conversation-1", source=native_run.source,
            complete_output=complete, source_resolver=native_run.resolve,
        )
    del complete["source_file_name"]
    unsupported = native.adapt_native_analysis_result(
        user_id=USER_ID, conversation_id="conversation-1", source=native_run.source,
        complete_output=complete, source_resolver=native_run.resolve,
    )
    assert unsupported["execution_status"] == "unsupported"
    assert unsupported["authoritative_result"]["value"] == []


def test_proven_empty_native_query_is_a_valid_zero_record_result(native_run, monkeypatch):
    class ToolResult(str):
        internal_metadata = {"tabular_source_authorization": {"source": "workspace"}}

    invocation = SimpleNamespace(result=ToolResult(json.dumps({
        "filename": native_run.source["file_name"], "data": [], "returned_rows": 0, "total_matches": 0,
    })))
    monkeypatch.setitem(sys.modules, "route_backend_chats", SimpleNamespace(
        _build_tabular_generated_output_source_candidate=lambda values: None,
        get_tabular_invocation_error_message=lambda value: None,
        get_tabular_invocation_result_payload=lambda value: json.loads(value.result),
    ))
    complete = native.collect_native_foreground_output([invocation])
    result = native.adapt_native_analysis_result(
        user_id=USER_ID, conversation_id="conversation-1", source=native_run.source,
        complete_output=complete, source_resolver=native_run.resolve,
    )
    descriptor, options = save_and_reload(native_run, result)
    assert descriptor["record_count"] == 0 and descriptor["source_count"] == 1
    assert descriptor["validation_status"] == "valid"
    assert saved.read_saved_analysis_page(USER_ID, saved.saved_analysis_context(descriptor), **options)["records"] == []


def test_native_artifact_references_do_not_expose_storage_locators(native_run):
    native_run.run["final_artifact"] = {
        "artifact_message_id": "native-file", "file_name": "native.json", "output_format": "json",
        "blob_container": "private-storage-name", "blob_path": "private-storage-path",
    }
    bindings = []
    result = adapt(native_run, analysis_producer={
        "kind": "workflow", "workflow_id": "workflow", "run_id": "run", "task_id": "task",
    }, bind_artifacts=lambda *args: bindings.append(args))
    assert len(bindings) == 1
    assert "private-storage" not in json.dumps(result["generated_tabular_outputs"])


def test_foreground_adapter_captures_complete_native_values_without_reduction(native_run, monkeypatch):
    fixture = native_run

    async def foreground(**kwargs):
        return "WRONG BOUNDED HANDOFF " * 1000, False

    async def generate(**kwargs):
        kwargs["final_result_callback"]({
            "status": "completed", "kind": "records", "value": deepcopy(fixture.rows),
            "source_row_count": len(fixture.rows),
            "source_file_name": fixture.source["file_name"], "source_authorization": {"source": "workspace"},
        })
        return {"artifact_message_id": "native-file", "conversation_id": "conversation-1", "output_format": "json"}

    monkeypatch.setitem(sys.modules, "functions_tabular_analysis", SimpleNamespace(
        augment_tabular_invocations_with_related_document_evidence=lambda *args: pytest.fail("No extra source pass."),
        build_tabular_related_document_evidence_summary=lambda *args: "",
        get_new_plugin_invocations=lambda *args: [], maybe_create_tabular_generated_output=generate,
        maybe_queue_direct_tabular_generated_output=lambda **kwargs: None,
        plan_tabular_request=lambda *args, **kwargs: {}, run_tabular_analysis_with_thought_tracking=foreground,
    ))
    runner = runner_namespace(
        asyncio=asyncio, is_mixed_source_manifest_enabled=lambda settings: False,
        is_tabular_processing_enabled=lambda settings: True,
        get_plugin_logger=lambda: SimpleNamespace(get_invocations_for_conversation=lambda *args, **kwargs: []),
        classify_tabular_parity_request=lambda text: {},
        emit_tabular_parity_event=lambda *args, **kwargs: None,
        TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION="foreground",
        adapt_native_analysis_result=lambda **kwargs: native.adapt_native_analysis_result(
            **kwargs, source_resolver=fixture.resolve,
        ),
    )
    runner["_resolve_tabular_document_action_documents"] = lambda *args, **kwargs: [{
        **fixture.source, "document_name": "Inventory", "source_hint": "workspace",
    }]
    runner["_resolve_tabular_document_action_model_name"] = lambda *args: "user-selected-model"
    runner["_build_agent_citations_from_plugin_invocations"] = lambda values: []
    runner["_build_workflow_model_context"] = lambda *args: {"model_id": "user-selected-model"}
    result = runner["_maybe_execute_tabular_document_action"](
        "analyze", {
            "user_id": USER_ID, "task_prompt": "Export the full inventory as JSON.",
            "_analysis_result_version": "analyze-final-v1",
        }, {"document_ids": [fixture.source["document_id"]]}, {},
        conversation_id="conversation-1", source_manifest=[fixture.source],
        invoke_prompt=lambda *args, **kwargs: pytest.fail("No clipped foreground synthesis is allowed."),
    )
    assert result is not None
    assert [record["values"] for record in result["result"]["authoritative_result"]["value"]] == fixture.rows
    assert "WRONG BOUNDED HANDOFF" not in json.dumps(result)
    assert result["result"]["analysis_sources"] == [fixture.source]


@pytest.mark.parametrize("native_status,execution,validation", [
    ("completed", "succeeded", "valid"), ("queued", "pending", "partial"), ("failed", "incomplete", "partial"),
])
def test_modern_mixed_results_keep_native_records_and_zero_finding_sources(
    native_run, native_status, execution, validation,
):
    fixture = native_run
    fixture.run["status"] = native_status
    native_result = adapt(fixture)
    documents = {
        "narrative-source": original_document("narrative-source", ["The contract relies on a sole supplier."]),
        "no-findings": original_document("no-findings", ["No issue is identified in this passage."]),
    }
    narrative_sources = [{
        "document_id": document_id, "source_kind": "narrative",
        "file_name": item["document"]["file_name"], "scope": "personal", "scope_id": USER_ID,
        "source_version": 1, "source_revision": None, "authorization_status": "authorized",
    } for document_id, item in documents.items()]
    manifest = [fixture.source, *narrative_sources]
    client = FixtureAnalysisClient()
    native_document = original_document(fixture.source["document_id"], [])
    native_document["document"].update(file_name=fixture.source["file_name"], _etag="source-etag")
    with document_analysis_runtime({**documents, fixture.source["document_id"]: native_document}) as runtime:
        runner = runner_namespace(
            **{name: getattr(mixed, name) for name in (
                "EVIDENCE_ENGINE_TABULAR_TOOLS", "EVIDENCE_STATUS_PENDING",
                "build_mixed_source_evidence_handoff", "deduplicate_mixed_source_references",
            )},
            native_analysis_state=native.native_analysis_state,
            run_document_analysis=runtime.producer.run_document_analysis,
            resolve_analysis_source_manifest=lambda ids, **kwargs: [
                deepcopy(source) for document_id in ids for source in manifest if source["document_id"] == document_id
            ],
        )
        runner["_maybe_execute_tabular_document_action"] = lambda *args, **kwargs: {
            "result": deepcopy(native_result),
            "generated_tabular_outputs": [{
                "run_id": "native-run", "export_run_id": "native-run", "status": native_status,
            }] if native_status != "completed" else [],
        }
        runner["_build_mixed_source_deferred_composition_descriptor"] = lambda *args, **kwargs: {
            "status": "pending", "pending_tabular_runs": [{"run_id": "native-run"}],
        }
        runner["_build_mixed_source_deferred_reply"] = lambda *args: "Native output remains pending."
        result = runner["_execute_mixed_source_analyze_workflow"](
            {"user_id": USER_ID, "task_prompt": "Explain the risks.", "_analysis_result_version": "analyze-final-v1"},
            {"type": "analyze", "document_ids": [source["document_id"] for source in manifest]},
            {}, client.invoke_prompt, conversation_id="conversation-1", max_documents=3,
        )
    assert result["execution_status"] == execution
    assert result["analysis_validation"]["status"] == validation
    assert result["analysis_sources"] == manifest
    assert len(client.calls) == 2 and {call["stage"] for call in client.calls} == {"window_analysis"}
    assert len(result["authoritative_result"]["value"]) == (151 if native_status == "completed" else 1)

    def resolve(ids, **kwargs):
        return [deepcopy(source) for document_id in ids for source in manifest if source["document_id"] == document_id]

    scope = SimpleNamespace(resolve=resolve)
    descriptor, options = save_and_reload(scope, result)
    assert descriptor["source_count"] == 3
    assert descriptor["execution_status"] == execution
    page = saved.read_saved_analysis_page(USER_ID, saved.saved_analysis_context(descriptor), **options)
    assert page["validation"]["status"] == validation
    assert page["total_records"] == (151 if native_status == "completed" else 1)
