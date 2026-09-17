# test_analyze_backend_saved_integration.py
"""
Behavioral integration tests for Analyze presentation and saved-data chat reuse.
Version: 0.261.109
Implemented in: 0.261.109

Real adapter, artifact, history, chat route and shared section-reader functions
run against serialized storage, Flask requests and deterministic model doubles.
No original document extraction, workspace upload or live Azure call is made.
"""

import ast
import asyncio
import csv
import io
import json
import logging
import random
import re
import time
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, Response, g, has_request_context, jsonify, request, session
from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.contents import ChatMessageContent, FunctionCallContent
from semantic_kernel.functions import kernel_function

from test_document_analysis_lossless_artifacts import load_module_functions
from test_saved_analysis_service import ChatSections, read_options, saved, saved_chat
from test_support.app_stubs import import_app_module


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
exports = import_app_module("functions_generated_file_exports")
access = import_app_module("functions_analysis_access")
mixed = import_app_module("functions_mixed_source_orchestration")
budget = import_app_module("functions_workflow_context")
agent_runtime = import_app_module("agent_delegation_runtime")
result_storage = import_app_module("functions_workflow_result_store")


def load_functions(filename, names, namespace):
    path = APP / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
    ]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def final_analysis(fixture):
    payload, _ = saved.load_saved_analysis_input(
        "owner", saved.saved_analysis_context(fixture["descriptor"]), **read_options(fixture),
    )
    data = json.loads(payload)
    source = fixture["source_resolver"](["document-1"])[0]
    return {
        "analysis_result_version": "analyze-final-v1",
        "analysis_reply": "## Findings\n\nSixty controls need an assigned owner.",
        "reply": "## Findings\n\nSixty controls need an assigned owner.",
        "authoritative_result": {"kind": "records", "value": data["records"]},
        "analysis_evidence": data["evidence"],
        "analysis_validation": data["validation"],
        "source_manifest": [source],
        "mixed_source_manifest": [source],
        "documents": [{"document_id": "document-1", "document_name": "controls.txt"}],
        "coverage": {"document_count": 1, "processed_windows": 1, "total_windows": 1},
        "raw_analysis_items": [{"text": "RAW-NOTES-MUST-NOT-BECOME-THE-REPORT"}],
    }


def runner_namespace(**extra):
    namespace = {
        "debug_print": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
        "has_request_context": lambda: True,
        "raise_if_mixed_source_cancelled": mixed.raise_if_mixed_source_cancelled,
        "MixedSourceCancellationError": mixed.MixedSourceCancellationError,
        "normalize_search_id_list": lambda values: list(dict.fromkeys(values or [])),
        "normalize_mixed_source_correlation_id": lambda value: value or "test-correlation",
        "partition_source_manifest": mixed.partition_source_manifest,
        "build_evidence_envelope": mixed.build_evidence_envelope,
        "EVIDENCE_ENGINE_DOCUMENT_ANALYSIS": mixed.EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
        "EVIDENCE_STATUS_COMPLETED": mixed.EVIDENCE_STATUS_COMPLETED,
        "EVIDENCE_STATUS_FAILED": mixed.EVIDENCE_STATUS_FAILED,
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "DOCUMENT_ACTION_TYPE_COMPARISON": "compare",
        "SELECTION_MODE_SELECTED": "selected",
        "time": time,
        "analysis_artifact_metadata": saved.analysis_artifact_metadata,
        "serialize_generated_xml": exports.serialize_generated_xml,
        "DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT": 3,
        "DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT": 3,
        "DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH": 220,
        "DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_COUNT": 4,
        "DOCUMENT_ANALYSIS_ARTIFACT_REPLY_CHAR_THRESHOLD": 500,
        **extra,
    }
    result = load_module_functions(str(APP / "functions_workflow_runner.py"), namespace)
    result["_maybe_execute_pure_tabular_analyze_preflight"] = lambda *args, **kwargs: None
    return result


def test_answer_markdown_csv_and_json_share_final_values(saved_chat):
    uploads = {}

    def upload(**kwargs):
        uploads[kwargs["output_format"]] = kwargs
        return {"message": {"id": f'artifact-{kwargs["output_format"]}', "file_name": kwargs["file_name"]}}

    runner = runner_namespace(upload_generated_analysis_artifact_for_current_user=upload)
    analysis = final_analysis(saved_chat)
    producer = {"kind": "chat", "conversation_id": "conversation-1", "message_id": "assistant-new"}
    result = runner["_maybe_create_document_analysis_generated_artifacts"](
        analysis, "Give me a table of all findings and a JSON artifact.",
        conversation_id="conversation-1", analysis_producer=producer,
    )
    expected = [record["values"] for record in analysis["authoritative_result"]["value"]]
    assert result["assistant_reply"] == analysis["analysis_reply"]
    assert json.loads(uploads["json"]["file_content"]) == expected
    assert list(csv.DictReader(io.StringIO(uploads["csv"]["file_content"]))) == expected
    markdown = uploads["md"]["file_content"]
    assert "## Findings\n\nSixty controls" in markdown
    assert "RAW-NOTES" not in markdown and '"analysis_reply"' not in markdown
    assert all(upload["analysis_producer"] == producer for upload in uploads.values())
    assert all(item["analysis_result_required"] for item in result["artifacts"])


def test_no_findings_does_not_export_diagnostic_rows(saved_chat):
    analysis = final_analysis(saved_chat)
    analysis["authoritative_result"]["value"] = []
    runner = runner_namespace()
    assert runner["_build_document_analysis_structured_rows"](analysis) == []
    assert "RAW-NOTES" not in runner["_build_document_analysis_markdown_artifact"](analysis)


@pytest.mark.parametrize("output_format", ["json", "xml"])
def test_mixed_analysis_exports_include_all_final_records_not_a_native_component(saved_chat, output_format):
    uploads = {}

    def upload(**kwargs):
        uploads[kwargs["output_format"]] = kwargs["file_content"]
        return {"message": {"id": f'artifact-{kwargs["output_format"]}', "file_name": kwargs["file_name"]}}

    analysis = final_analysis(saved_chat)
    analysis["analysis_reply"] = analysis["reply"] = "Both sources contribute accepted findings."
    analysis["analysis_sources"] = [
        *analysis["source_manifest"],
        {"document_id": "native-source", "source_kind": "tabular", "scope": "personal", "scope_id": "owner"},
    ]
    analysis["authoritative_result"]["value"].append({
        "record_id": "native-final", "document_id": "native-source",
        "values": {"finding": "Native final value", "amount": "12.3400"}, "evidence_refs": [],
    })
    runner = runner_namespace(upload_generated_analysis_artifact_for_current_user=upload)
    runner["_maybe_create_document_analysis_generated_artifacts"](
        analysis, f"Return a {output_format.upper()} artifact.", conversation_id="conversation-1",
        primary_generated_outputs=[{
            "capability": "tabular", "artifact_message_id": "native-component",
            "output_format": output_format, "status": "completed",
        }],
    )
    assert "Native final value" in uploads[output_format]
    assert "Control 59" in uploads[output_format]
    if output_format == "json":
        assert len(json.loads(uploads[output_format])) == 61


def test_complete_pure_native_artifact_is_not_uploaded_again(saved_chat):
    analysis = final_analysis(saved_chat)
    analysis["analysis_sources"] = [{**analysis["source_manifest"][0], "source_kind": "tabular"}]
    runner = runner_namespace(
        get_requested_generated_file_format=exports.get_requested_generated_file_format,
        get_requested_structured_artifact_format=exports.get_requested_structured_artifact_format,
        upload_generated_analysis_artifact_for_current_user=lambda **kwargs: pytest.fail("Reuse the native artifact."),
    )
    result = runner["_maybe_create_document_analysis_generated_artifacts"](
        analysis, "Return a JSON artifact.", conversation_id="conversation-1",
        primary_generated_outputs=[{
            "capability": "tabular", "artifact_message_id": "complete-native-file",
            "output_format": "json", "status": "completed",
        }],
    )
    assert result["artifacts"] == []
    assert result["assistant_reply"] == analysis["analysis_reply"]


@pytest.mark.parametrize("source_count", [1, 10, 100, 300, 500])
def test_narrative_adapter_passes_every_authorized_snapshot(source_count):
    sources = [{
        "document_id": f"document-{index}", "scope": "personal", "scope_id": "owner",
        "source_version": index, "source_revision": f"etag-{index}",
        "authorization_status": "authorized", "source_kind": "narrative",
        "file_name": f"source-{index}.txt",
    } for index in range(source_count)]
    resolutions = []
    calls = []

    def resolve(ids, **kwargs):
        resolutions.append(list(ids))
        return [deepcopy(source) for source in sources if source["document_id"] in ids]

    def produce(**kwargs):
        calls.append(kwargs)
        return {
            "analysis_result_version": "analyze-final-v1",
            "analysis_reply": "The selected sources contain findings.",
            "reply": "The selected sources contain findings.",
            "authoritative_result": {"kind": "records", "value": [
                {"record_id": source["document_id"], "document_id": source["document_id"],
                 "values": {"finding": source["file_name"]}, "evidence_refs": []}
                for source in sources
            ]},
            "analysis_validation": {"status": "valid"},
            "analysis_evidence": [],
            "analysis_metrics": {"collection_model_calls": 0},
            "coverage": {"documents": [
                {"document_id": source["document_id"], "total_windows": 1, "processed_windows": 1}
                for source in sources
            ]},
        }

    runner = runner_namespace(
        run_document_analysis=produce,
        resolve_analysis_source_manifest=lambda ids, **kwargs: access.resolve_analysis_source_manifest(
            ids, resolver=resolve, **kwargs,
        ),
    )
    result = runner["_execute_mixed_source_analyze_workflow"](
        {"user_id": "owner", "task_prompt": "Explain the risks."},
        {"type": "analyze", "document_ids": [source["document_id"] for source in sources]},
        {}, lambda *args, **kwargs: pytest.fail("A second bounded-evidence synthesis must not run."),
        max_documents=source_count,
    )
    assert len(calls) == 1
    assert calls[0]["result_version"] == "analyze-final-v1"
    assert calls[0]["source_manifest"] == sources
    assert len(resolutions) == (source_count + 99) // 100
    assert max(map(len, resolutions)) <= 100
    assert len(result["authoritative_result"]["value"]) == source_count
    assert result["analysis_metrics"]["collection_model_calls"] == 0
    assert result["analysis_validation"] == {"status": "valid"}


def test_final_collection_deduplicates_replays_without_overwriting_conflicts(saved_chat):
    runner = runner_namespace()
    analysis = final_analysis(saved_chat)
    combined = runner["_combine_final_analysis_results"](
        [analysis, deepcopy(analysis)], "Readable combined answer.", {},
    )
    assert len(combined["authoritative_result"]["value"]) == 60
    changed = deepcopy(analysis)
    changed["authoritative_result"]["value"][0]["values"]["finding"] = "Conflicting value"
    with pytest.raises(ValueError, match="conflicting identities"):
        runner["_combine_final_analysis_results"]([analysis, changed], "Answer", {})
    pending = {"reply": "Still processing", "coverage": {"progress_meta": {"status": "pending"}}}
    assert runner["_combine_final_analysis_results"]([analysis, pending], "Pending", {}) is None


class MessageStore:
    def __init__(self, original):
        self.documents = {original["id"]: deepcopy(original)}

    def read_item(self, item, partition_key):
        value = self.documents[item]
        assert value["conversation_id"] == partition_key
        return deepcopy(value)

    def upsert_item(self, document):
        self.documents[document["id"]] = deepcopy(document)
        return deepcopy(document)

    def delete_item(self, item, partition_key):
        assert self.documents[item]["conversation_id"] == partition_key
        del self.documents[item]

    def query_items(self, **kwargs):
        values = list(self.documents.values())
        return sorted(values, key=lambda item: item.get("timestamp", ""))


@pytest.fixture
def chat(saved_chat, monkeypatch):
    fixture = saved_chat
    messages = MessageStore(fixture["message"])
    source_state = fixture["state"]
    state = {
        "cancelled": False, "cancel_after_model": False, "cancel_after_analyze": False,
        "model_calls": [], "token_logs": [], "analyze_calls": [], "save_failure": False, "rollbacks": 0,
    }
    store = ChatSections(deepcopy(fixture["store"].contents))
    conversation = {"id": "conversation-1", "user_id": "owner", "title": "Saved controls"}

    def message_loader(user_id, conversation_id, message_id):
        if user_id != "owner" or conversation_id != "conversation-1" or not source_state["conversation_allowed"]:
            raise PermissionError()
        return messages.read_item(message_id, conversation_id)

    options = {
        "message_loader": message_loader, "chat_loader": store.load,
        "source_resolver": fixture["source_resolver"],
    }

    def complete(**kwargs):
        state["model_calls"].append(deepcopy(kwargs))
        data = json.loads(kwargs["messages"][-1]["content"].split("[Saved Analyze result — complete data]\n", 1)[1])
        assert data["original_sources_reanalyzed"] is False
        assert len(data["records"]) == 60
        if state["cancel_after_model"]:
            state["cancelled"] = True
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="All 60 saved controls need an owner."))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=12, total_tokens=112),
        )

    limits = {
        "context_window_tokens": 200000, "max_input_tokens": None, "max_output_tokens": 4096,
        "tokenizer": None, "source": "catalog", "model_id": "actual-selected-model", "status": "known",
    }
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda *args, **kwargs: dict(limits))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    app = Flask(__name__)
    app.secret_key = "offline-test-key"
    scope = {
        "active_group_ids": [], "active_group_id": None,
        "active_public_workspace_ids": [], "active_public_workspace_id": None,
    }
    namespace = {
        "asyncio": asyncio, "json": json, "logging": logging, "random": random, "uuid": uuid,
        "datetime": datetime, "time": time, "g": g, "has_request_context": has_request_context,
        "request": request, "session": session, "jsonify": jsonify,
        "get_current_user_id": lambda: "owner", "get_current_user_info": lambda: {"user_id": "owner"},
        "get_settings": lambda: {"conversation_history_limit": 10},
        "log_event": lambda *args, **kwargs: None, "debug_print": lambda *args, **kwargs: None,
        "make_json_serializable": lambda value: deepcopy(value),
        "cosmos_messages_container": messages,
        "cosmos_conversations_container": SimpleNamespace(upsert_item=lambda item: deepcopy(item)),
        "_load_or_create_analyze_conversation": lambda *args, **kwargs: deepcopy(conversation),
        "_get_latest_chat_thread_id": lambda *args: "previous",
        "_initialize_assistant_response_tracking": lambda **kwargs: (
            kwargs.get("assistant_message_id") or f"assistant-{uuid.uuid4().hex}", SimpleNamespace(enabled=False), 1,
            {"thread_id": kwargs["current_user_thread_id"], "previous_thread_id": "previous"},
        ),
        "build_prompt_selection_metadata": lambda *args: None,
        "saved_analysis_context": saved.saved_analysis_context,
        "SavedAnalysisInput": saved.SavedAnalysisInput,
        "explain_saved_analysis": saved.explain_saved_analysis,
        "format_saved_analysis": saved.format_saved_analysis,
        "saved_analysis_format_request": saved.saved_analysis_format_request,
        "analysis_result_contexts": saved.analysis_result_contexts,
        "bind_chat_analysis_attempt": lambda *args: None,
        "prepare_chat_analysis": lambda *args, **kwargs: SimpleNamespace(
            token="offline-attempt", cancel=lambda **kwargs: None,
            operation_request=None, operation_sources=None,
        ),
        "assert_analysis_attempt_current": lambda *args: None,
        "update_analysis_conversation": lambda user, value: value,
        "authorize_analysis_conversation": lambda *args: deepcopy(conversation),
        "AnalysisWorkUnitConflictError": result_storage.AnalysisWorkUnitConflictError,
        "AnalysisResultUnavailable": saved.AnalysisResultUnavailable,
        "load_saved_analysis_input": lambda user_id, context, **kwargs: saved.load_saved_analysis_input(
            user_id, context, **options, **kwargs,
        ),
        "load_saved_analysis": lambda user_id, context: saved.load_saved_analysis(user_id, context, **options),
        "sanitize_saved_analysis_messages": lambda values, user_id: saved.sanitize_saved_analysis_messages(
            values, user_id, result_reader=lambda actor, context: saved.load_saved_analysis(actor, context, **options),
        ),
        "raise_if_mixed_source_cancelled": mixed.raise_if_mixed_source_cancelled,
        "MixedSourceCancellationError": mixed.MixedSourceCancellationError,
        "AgentExecutionCancelled": type("Cancelled", (BaseException,), {}),
        "WorkflowContextBudgetError": budget.WorkflowContextBudgetError,
        "WorkflowResultNotReadyError": saved.WorkflowResultNotReadyError,
        "workflow_context_budget_scope": budget.workflow_context_budget_scope,
        "raise_if_workflow_context_blocked": budget.raise_if_workflow_context_blocked,
        "_resolve_canonical_chat_agent": lambda *args, **kwargs: None,
        "_resolve_model_workflow_client": lambda *args: (
            budget.WorkflowModelClient(client, {"id": "actual-selected-model"}, "aoai"),
            "actual-selected-deployment", "aoai",
        ),
        "extract_chat_completion_response_text": lambda value: value.choices[0].message.content,
        "filter_assistant_artifact_items": lambda values: list(values),
        "build_message_artifact_payload_map": lambda values: {},
        "hydrate_agent_citations_from_artifacts": lambda values, payloads: values,
        "sort_messages_by_thread": lambda values: values,
        "resolve_block_sources_in_content": lambda message, content: content,
        "build_assistant_history_content_with_citations": lambda message, content: content,
        "remove_masked_content": lambda content, ranges: content,
        "_set_initial_conversation_title": lambda *args: False,
        "invalidate_conversation_cache_for_item": lambda *args, **kwargs: None,
        "log_chat_activity": lambda **kwargs: None,
        "log_token_usage": lambda **kwargs: state["token_logs"].append(kwargs),
        "build_user_message_persisted_stream_event": lambda conv, message: (
            f'data: {json.dumps({"type": "user_message_persisted", "user_message_id": message})}\n\n'
        ),
        "_authorize_personal_conversation_access": lambda *args: conversation,
        "_get_authorized_chat_scope_context": lambda *args, **kwargs: deepcopy(scope),
        "CHAT_STREAM_REGISTRY": SimpleNamespace(start_session=lambda *args, **kwargs: SimpleNamespace(
            is_cancel_requested=lambda: state["cancelled"],
        )),
        "CLIENT_SAFE_STREAM_ERROR_MESSAGE": "Streaming failed.",
    }
    analysis = final_analysis(fixture)

    def produce(workflow, settings, **kwargs):
        state["analyze_calls"].append(deepcopy({
            key: value for key, value in workflow.items() if key != "_analysis_checkpoints"
        }))
        if state["cancel_after_analyze"]:
            state["cancelled"] = True
        return {
            "reply": "An artifact announcement is not the answer.",
            "analysis_result": deepcopy(analysis), "analysis_coverage": deepcopy(analysis["coverage"]),
            "model_deployment_name": "actual-selected-deployment", "token_usage": {},
        }

    def save_analysis(result, **kwargs):
        if state["save_failure"]:
            raise OSError("offline storage failure")
        return saved.save_chat_analysis(
            result, **kwargs, authorize_conversation=lambda *args: conversation,
            save_result=store.save, source_resolver=fixture["source_resolver"],
        )

    def rollback(*args, **kwargs):
        state["rollbacks"] += 1

    namespace.update({
        "VERSION": "0.261.106",
        "DOCUMENT_ACTION_TYPE_NONE": "none", "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "DOCUMENT_ACTION_TYPE_COMPARISON": "compare", "DOCUMENT_ACTION_CONTEXT_CHAT": "chat",
        "normalize_mixed_source_correlation_id": mixed.normalize_mixed_source_correlation_id,
        "MixedSourceFinalizationError": mixed.MixedSourceFinalizationError,
        "compare_reauthorized_source_manifests": mixed.compare_reauthorized_source_manifests,
        "emit_mixed_source_telemetry": lambda *args, **kwargs: None,
        "resolve_analysis_source_manifest": lambda ids, **kwargs: access.resolve_analysis_source_manifest(
            ids, resolver=fixture["source_resolver"], **kwargs,
        ),
        "get_document_action_max_documents_by_type": lambda *args, **kwargs: {},
        "get_enabled_document_action_types": lambda **kwargs: ["analyze"],
        "normalize_document_action_config": lambda action_payload, **kwargs: action_payload,
        "_normalize_requested_scope_ids": lambda values: list(values or []),
        "_normalize_conversation_task_document_ids": lambda values: list(values or []),
        "_build_document_action_user_metadata": lambda **kwargs: {
            "thread_info": {"thread_id": kwargs["current_thread_id"]},
            "user_info": {"user_id": kwargs["user_id"]},
        },
        "_build_document_action_prompt_with_assigned_knowledge_context": lambda prompt, *args: prompt,
        "_get_conversation_context_agent_fields": lambda value: {},
        "build_conversation_context_snapshot": lambda *args, **kwargs: {},
        "serialize_conversation_context_snapshot": lambda value: json.dumps(value),
        "build_conversation_context_system_message": lambda value: None,
        "build_conversation_context_data_message": lambda value: None,
        "_execute_document_action_workflow": produce,
        "_build_document_action_hybrid_citations": lambda result: [],
        "append_conversation_context_citation": lambda *args, **kwargs: None,
        "apply_agent_document_citations": lambda *args, **kwargs: None,
        "_build_hybrid_citation_sort_key": lambda value: "",
        "persist_agent_citation_artifacts": lambda **kwargs: [],
        "maybe_create_generated_file_output": lambda **kwargs: None,
        "maybe_create_assistant_file_generated_output": lambda **kwargs: None,
        "get_analysis_export_rows": exports.get_analysis_export_rows,
        "get_assistant_presentation_content": exports.get_assistant_presentation_content,
        "get_generated_file_export_content": exports.get_generated_file_export_content,
        "get_requested_generated_file_format": exports.get_requested_generated_file_format,
        "serialize_generated_json": exports.serialize_generated_json,
        "_rollback_mixed_source_chat_publication": rollback,
        "save_chat_analysis": save_analysis,
        "build_cited_source_subsets": lambda *args, **kwargs: {
            "cited_hybrid_citations": [], "cited_web_search_citations": [],
        },
        "_build_capability_usage_metadata": lambda **kwargs: {},
        "initialize_conversation_used_document_tracking": lambda *args: None,
        "collect_conversation_metadata": lambda **kwargs: kwargs["conversation_item"],
        "_build_agent_selection_metadata": lambda *args: {},
        "merge_cited_documents_into_conversation": lambda *args: None,
    })
    names = {
        "SavedAnalysisFollowupUnsupported", "_invoke_saved_analysis_chat_reply",
        "_sanitize_saved_analysis_history", "_analysis_history_metadata",
        "execute_saved_analysis_chat_request", "normalize_terminal_chat_payload",
        "_bounded_int", "_safe_int", "_truncate_log_text", "_build_stream_cancel_event",
        "_format_history_message_ref", "_capture_history_refs", "build_conversation_history_segments",
        "build_stream_error_event", "chat_api", "chat_stream_api",
        "execute_document_action_chat_request", "_reauthorize_document_action_finalization",
        "_validate_reauthorized_manifest_finalization", "_build_generated_analysis_metadata",
        "_normalize_generated_analysis_artifact_metadata",
    }
    load_functions("route_backend_chats.py", names, namespace)

    def background_response(factory, **kwargs):
        events = []
        for event in factory(events.append):
            events.append(event)
        return Response("".join(events), mimetype="text/event-stream")

    namespace["build_background_stream_response"] = background_response
    app.add_url_rule("/api/chat", "chat", namespace["chat_api"], methods=["POST"])
    app.add_url_rule("/api/chat/stream", "stream", namespace["chat_stream_api"], methods=["POST"])
    app.add_url_rule("/api/chat/document-action", "analyze", lambda: namespace["execute_document_action_chat_request"](
        request.get_json(), cancel_requested=lambda: state["cancelled"],
    ), methods=["POST"])
    return SimpleNamespace(
        client=app.test_client(), app=app, namespace=namespace, state=state, source_state=source_state,
        messages=messages, store=store, limits=limits, descriptor=fixture["descriptor"], options=options,
        analysis=analysis,
    )


def followup_body(chat):
    return {
        "message": "Explain every saved finding.", "conversation_id": "conversation-1",
        "analysis_result_context": saved.saved_analysis_context(chat.descriptor),
        "model_endpoint_id": "selected-endpoint", "model_id": "actual-selected-model",
        "model_deployment": "actual-selected-deployment",
        "document_action": {"type": "analyze", "document_ids": ["must-not-analyze"]},
        "selected_document_ids": ["must-not-analyze"], "hybrid_search": True,
        "web_search_enabled": True, "source_review_enabled": True, "image_generation": True,
    }


def frames(response):
    return [json.loads(line[5:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data:")]


def analyze_body():
    return {
        "message": "Explain these controls.", "conversation_id": "conversation-1",
        "model_endpoint_id": "selected-endpoint", "model_id": "actual-selected-model",
        "document_action": {"type": "analyze", "document_ids": ["document-1"], "doc_scope": "all"},
    }


def test_direct_analyze_saves_real_assistant_identity_and_reloads_all_records(chat):
    response = chat.client.post("/api/chat/document-action", json=analyze_body())
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["reply"] == chat.analysis["analysis_reply"]
    descriptor = payload["metadata"]["saved_analysis"]
    assert descriptor["message_id"] == payload["message_id"]
    assert descriptor["binding"]["kind"] == "chat"
    assert "workflow_id" not in descriptor["binding"]
    assert chat.messages.documents[payload["message_id"]]["content"] == payload["reply"]
    assert chat.messages.documents[payload["message_id"]]["metadata"] == payload["metadata"]
    assert chat.state["analyze_calls"][0]["_analysis_producer"] == {
        "kind": "chat", "conversation_id": "conversation-1", "message_id": payload["message_id"],
    }
    cold_store = ChatSections(deepcopy(chat.store.contents))
    serialized, _ = saved.load_saved_analysis_input(
        "owner", saved.saved_analysis_context(descriptor),
        **{**chat.options, "chat_loader": cold_store.load},
    )
    assert len(json.loads(serialized)["records"]) == 60
    assert "RAW-NOTES" not in serialized


def test_direct_analyze_save_failure_is_not_a_successful_assistant_message(chat):
    chat.state["save_failure"] = True
    response = chat.client.post("/api/chat/document-action", json=analyze_body())
    assert response.status_code == 503
    assert response.get_json()["warning_type"] == "analysis_save_failed"
    assert "could not be saved" in response.get_json()["error"]
    assert chat.state["rollbacks"] == 1
    assert len([item for item in chat.messages.documents.values() if item["role"] == "assistant"]) == 1


def test_direct_analyze_keeps_partial_validation_distinct_from_completion(chat):
    chat.analysis["analysis_validation"] = {"status": "partial", "limitations": ["One work unit failed."]}
    chat.analysis["coverage"]["progress_meta"] = {"status": "partial"}
    response = chat.client.post("/api/chat/document-action", json=analyze_body())
    assert response.status_code == 200, response.get_json()
    descriptor = response.get_json()["metadata"]["saved_analysis"]
    assert descriptor["validation_status"] == "partial"
    assert descriptor["execution_status"] == "incomplete"
    assert descriptor["record_count"] == 60


def test_direct_analyze_cancellation_prevents_saving_or_advertising_results(chat):
    chat.state["cancel_after_analyze"] = True
    stored_before = deepcopy(chat.store.contents)
    response = chat.client.post("/api/chat/document-action", json=analyze_body())
    assert response.status_code == 409
    assert response.get_json()["canceled"] is True
    assert chat.store.contents == stored_before
    assert len([item for item in chat.messages.documents.values() if item["role"] == "assistant"]) == 1


def test_stream_followup_uses_saved_records_before_any_source_action(chat):
    response = chat.client.post("/api/chat/stream", json=followup_body(chat))
    result = frames(response)[-1]
    assert result["done"] and result["full_content"].startswith("All 60 saved controls")
    assert "not independently rechecked" in result["full_content"]
    assert result["metadata"]["saved_analysis"] == chat.descriptor
    assert result["model_deployment_name"] == "actual-selected-deployment"
    assert result["metadata"]["context_budget"]["truncated"] is False
    stored = chat.messages.documents[result["message_id"]]
    assert stored["metadata"] == result["metadata"]
    assert len(chat.state["model_calls"]) == 1
    assert chat.state["model_calls"][0]["model"] == "actual-selected-deployment"
    prompt = chat.state["model_calls"][0]["messages"][-1]["content"]
    assert "record-59" in prompt and "RAW-NOTE-ONLY" not in prompt
    assert chat.state["token_logs"][0]["total_tokens"] == 112


def test_sync_followup_retry_keeps_result_digest_without_reextracting(chat):
    first = chat.client.post("/api/chat", json=followup_body(chat)).get_json()
    retry = followup_body(chat)
    retry["retry_user_message_id"] = first["user_message_id"]
    second_response = chat.client.post("/api/chat", json=retry)
    assert second_response.status_code == 200, second_response.get_json()
    second = second_response.get_json()
    assert second["metadata"]["saved_analysis"]["result_sha256"] == chat.descriptor["result_sha256"]
    assert len([item for item in chat.messages.documents.values() if item["role"] == "user"]) == 1
    assert len(chat.state["model_calls"]) == 2
    assert len(json.loads(saved.load_saved_analysis_input(
        "owner", saved.saved_analysis_context(chat.descriptor), **chat.options,
    )[0])["records"]) == 60


def test_saved_followup_blocks_full_input_that_exceeds_selected_model_budget(chat):
    chat.limits.update(context_window_tokens=1024, max_output_tokens=512)
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code == 400
    assert "input budget" in response.get_json()["error"]
    assert chat.state["model_calls"] == []
    assert list(chat.store.contents)
    assert not [item for item in chat.messages.documents.values() if item["id"] != "assistant-1" and item["role"] == "assistant"]


def test_revocation_blocks_saved_followup_before_model_or_assistant_persistence(chat):
    chat.source_state["source_allowed"] = False
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code == 403
    assert "source access" in response.get_json()["error"]
    assert chat.state["model_calls"] == []
    assert len(chat.messages.documents) == 1


def test_cancellation_after_model_response_does_not_publish_explanation(chat):
    chat.state["cancel_after_model"] = True
    response = chat.client.post("/api/chat/stream", json=followup_body(chat))
    result = frames(response)[-1]
    assert result["cancelled"] is True and result["message_persisted"] is False
    assert len([item for item in chat.messages.documents.values() if item["role"] == "assistant"]) == 1


class SavedReplyCompletion(OpenAIChatCompletion):
    requests: list = []

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        self.requests.append({
            "messages": chat_history.serialize(), "tools_enabled": settings.function_choice_behavior is not None,
        })
        if settings.function_choice_behavior is not None:
            return [ChatMessageContent(role="assistant", items=[
                FunctionCallContent(id="source-read", name="source-extract", arguments="{}"),
            ])]
        return [ChatMessageContent(role="assistant", content="The local agent explained the saved findings.")]


@pytest.mark.parametrize("oversized_instructions", [False, True])
def test_local_agent_saved_followup_disables_tools_and_budgets_real_instructions(chat, oversized_instructions):
    namespace = chat.namespace
    selected = {"name": "SavedAnalysisAgent", "display_name": "Saved analysis agent", "agent_type": "local"}
    original = SavedReplyCompletion(ai_model_id="actual-agent-model", service_id="saved-model", api_key="offline-only")
    tool_calls = []

    @kernel_function(name="extract", description="Extract an original source.")
    def extract() -> str:
        tool_calls.append(True)
        raise AssertionError("Saved-result explanations must never extract original sources.")

    def load_agent(kernel, settings, user_id, redis):
        kernel.add_function(plugin_name="source", function=extract)
        service = budget.wrap_workflow_chat_service(original, {"modelName": "actual-agent-model"}, provider="aoai")
        agent = ChatCompletionAgent(
            name=selected["name"], kernel=kernel, service=service,
            instructions="Explain accepted saved findings. " * (10000 if oversized_instructions else 1),
            function_choice_behavior=FunctionChoiceBehavior.Auto(),
        )
        return kernel, {selected["name"]: agent}

    namespace.update({
        "Kernel": Kernel, "ChatCompletionAgent": ChatCompletionAgent, "ChatMessageContent": ChatMessageContent,
        "AgentExecution": agent_runtime.AgentExecution,
        "prepare_agent_execution": agent_runtime.prepare_agent_execution,
        "invoke_workflow_agent": budget.invoke_workflow_agent,
        "_resolve_canonical_chat_agent": lambda *args, **kwargs: selected,
        "load_user_semantic_kernel": load_agent,
    })
    load_functions("route_backend_chats.py", {
        "apply_agent_stream_retry_mode", "restore_agent_stream_retry_state",
    }, namespace)
    with chat.client.session_transaction() as user_session:
        user_session["user"] = {"oid": "owner"}
    body = followup_body(chat)
    body["agent_info"] = selected
    response = chat.client.post("/api/chat", json=body)
    if oversized_instructions:
        assert response.status_code == 400, response.get_json()
        assert "input budget" in response.get_json()["error"]
        assert original.requests == []
    else:
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload["agent_name"] == selected["name"]
        assert "local agent explained" in payload["reply"]
        assert "record-59" in original.requests[0]["messages"]
        assert original.requests[0]["tools_enabled"] is False
        assert payload["metadata"]["context_budget"]["request_count"] == 1
    assert tool_calls == []


def test_managed_agent_followup_is_explicitly_unsupported_without_model_substitution(chat):
    chat.namespace["_resolve_canonical_chat_agent"] = lambda *args: {
        "name": "Managed", "agent_type": "azure_ai_foundry",
    }
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code == 400
    assert "cannot guarantee" in response.get_json()["error"]
    assert chat.state["model_calls"] == []


def test_direct_saved_format_request_never_invokes_the_selected_model(chat):
    uploads = []

    def upload(**kwargs):
        uploads.append(kwargs)
        return {"message": {"id": "formatted-file", "file_name": kwargs["file_name"]}}

    chat.namespace["format_saved_analysis"] = lambda inputs, output_format, **kwargs: saved.format_saved_analysis(
        inputs, output_format, upload_artifact=upload, bind_contexts=lambda *args: None, **kwargs,
    )
    body = followup_body(chat)
    body["message"] = "Export this saved result as JSON."
    response = chat.client.post("/api/chat", json=body)
    assert response.status_code == 200, response.get_json()
    assert len(json.loads(uploads[0]["file_content"])) == 60
    assert response.get_json()["metadata"]["analysis_explanation"]["consumption"]["mode"] == "format_only"
    assert chat.state["model_calls"] == chat.state["analyze_calls"] == []


def test_direct_chat_consumes_all_saved_records_in_model_sized_pages(chat):
    chat.limits.update(context_window_tokens=14000, max_output_tokens=2048)
    seen = []
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        data = json.loads(kwargs["messages"][-1]["content"].split("[Saved Analyze result — complete data]\n", 1)[1])
        if "records" in data:
            seen.extend(record["record_id"] for record in data["records"])
            answer = {"record_explanations": [{
                "record_ref": record["record_ref"], "text": record["values"]["finding"],
            } for record in data["records"]]}
        else:
            answer = {"conclusions": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))], usage=None)

    delegate = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    chat.namespace["_resolve_model_workflow_client"] = lambda *args: (
        budget.WorkflowModelClient(delegate, {"id": "actual-selected-model", "responseLength": 2048}, "aoai"),
        "actual-selected-deployment", "aoai",
    )
    response = chat.client.post("/api/chat", json=followup_body(chat))
    assert response.status_code == 200, response.get_json()
    consumption = response.get_json()["metadata"]["analysis_explanation"]["consumption"]
    assert consumption["mode"] == "record_pages"
    assert consumption["record_count"] == 60
    assert len(seen) == len(set(seen)) == 60
    assert len(calls) > 1 and chat.state["analyze_calls"] == []


def test_history_propagates_identity_and_withholds_derived_text_after_revocation(chat):
    origin = deepcopy(chat.messages.documents["assistant-1"])
    with chat.app.test_request_context():
        chat.namespace["build_conversation_history_segments"]([origin], 10)
        lineage = chat.namespace["_analysis_history_metadata"]()
    assert lineage["analysis_result_contexts"] == [saved.saved_analysis_context(chat.descriptor)]
    derived = {
        "id": "derived-message", "conversation_id": "conversation-1", "role": "assistant",
        "content": "PRIVATE-COPIED-EXPLANATION", "metadata": lineage,
        "agent_citations": [{"function_result": "PRIVATE-COPIED-EVIDENCE"}],
    }
    chat.messages.documents["derived-message"] = derived
    chat.source_state["source_allowed"] = False
    with chat.app.test_request_context():
        segments = chat.namespace["build_conversation_history_segments"]([origin, derived], 10)
        assert chat.namespace["_analysis_history_metadata"]() == {}
    assert "PRIVATE-COPIED" not in json.dumps(segments, default=list)
    assert "unavailable" in json.dumps(segments, default=list).lower()
