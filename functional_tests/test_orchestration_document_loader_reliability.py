# test_orchestration_document_loader_reliability.py
"""
Functional tests for shared document-action loading and safe failure outcomes.
Version: 0.261.421
Implemented in: 0.261.421

Real authenticated routes, discovery, source checks, SDK-shaped document stores,
chunk readers, action filters, retention, and final publication run offline.
The all-format matrix reads already indexed text; it does not claim that every
format exposes native Office/PDF metadata or that extraction is tested here.
"""

import hashlib
import importlib
import importlib.util
import json
import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent

from functions_task_completeness import NARRATIVE_OBLIGATIONS
from test_orchestration_document_action_end_to_end import (
    LEFT, PRIVATE, frames, modules, native_http, real_http_harness, source_runtime,
)
from test_orchestration_planner_contract_recovery import action_proposal


__all__ = ["modules", "native_http", "real_http_harness", "source_runtime"]
FAILURE_CASES = (
    ("loading", "action_initialization_failed", "action_initialization", 0, 0),
    ("identity", "document_reader_identity_mismatch", "action_initialization", 0, 0),
    ("read", "document_action_read_failed", "document_action_read", 1, 1),
    ("results", "action_results_missing", "action_results", 1, 0),
)


def submit_action_turn(state, message, answer, turn_id):
    proposal = action_proposal((LEFT,), action=state.action)
    proposal["steps"][0]["arguments"]["task"] = message
    proposal["steps"][1]["arguments"]["instruction"] = (
        "Use only the returned source evidence and copy its citation."
    )
    state.runtime.harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": message, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal),
        answer,
        json.dumps({"requirements": [{
            "id": identifier, "requirement": requirement, "status": "satisfied",
            "reason": "", "evidence_refs": [], "answer_quote": answer,
        } for identifier, requirement in NARRATIVE_OBLIGATIONS]}),
    ]
    response = state.runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": turn_id, "message": message,
        "planning_submission_id": f"{turn_id}-submit", "approval_mode": "auto",
        "selected_document_ids": [LEFT],
    }, buffered=True)
    events = frames(response)
    plans = [event["plan"] for event in events if event.get("type") == "orchestration_plan"]
    if len(plans) != 1:
        raise AssertionError(f"The request did not produce one approved plan: {response.get_data(as_text=True)}")
    plan = plans[0]
    saved = state.runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    return response, events, plan, saved


def test_every_supported_format_reaches_a_saved_cited_stored_chunk_answer(native_http, monkeypatch):
    state = native_http
    harness = state.runtime.harness
    documents = harness.config.cosmos_user_documents_container
    owner = importlib.import_module("functions_documents")
    citations = importlib.import_module("functions_agent_document_citations")
    extensions = sorted(harness.config.get_allowed_extensions(enable_video=True, enable_audio=True))
    categories = harness.config.get_allowed_extension_categories(
        enable_video=True, enable_audio=True, enable_xsd=True,
    )
    covered = {extension for category in categories for extension in category["extensions"]}
    assert covered == set(extensions)
    search_calls = []
    native_attempts = []
    monkeypatch.setattr(owner, "cosmos_user_documents_container", documents)
    plugin = importlib.import_module("semantic_kernel_plugins.document_search_plugin")

    def reject_native_report(**kwargs):
        native_attempts.append(deepcopy(kwargs))
        raise AssertionError("Stored-text retrieval must not request or infer a native report.")

    monkeypatch.setattr(plugin, "get_document_accessibility_payload", reject_native_report)

    def stored_chunk(document):
        return {
            "id": f"{LEFT}_1", "document_id": LEFT, "user_id": "owner",
            "file_name": document["file_name"], "version": document["version"],
            "chunk_id": "1", "chunk_sequence": 1, "page_number": 1,
            "chunk_text": "The stored source states that the review is complete.",
        }

    def search(**kwargs):
        search_calls.append(deepcopy(kwargs))
        if kwargs.get("filter") != f"document_id eq '{LEFT}'":
            raise AssertionError("The stored-chunk reader did not use the bound document filter.")
        document = documents.read_item(LEFT, LEFT)
        return [stored_chunk(document)]

    def search_client(*, group_id=None, public_workspace_id=None):
        if group_id is not None or public_workspace_id is not None:
            raise AssertionError("A personal document was routed to another search index.")
        return SimpleNamespace(search=search)

    monkeypatch.setattr(owner, "_get_search_client", search_client)

    async def stored_reply(self, history, settings):
        state.native_calls.append(deepcopy([message.to_dict() for message in history.messages]))
        results = [
            item.result for message in history.messages for item in message.items
            if hasattr(item, "result")
        ]
        if not results:
            return [ChatMessageContent(role=AuthorRole.ASSISTANT, items=[FunctionCallContent(
                id="read-stored", name="document_search-retrieve_document_chunks",
                arguments=json.dumps({"document_id": LEFT, "doc_scope": "personal"}),
            )])]
        value = json.loads(results[-1]) if isinstance(results[-1], str) else results[-1]
        return [ChatMessageContent(role=AuthorRole.ASSISTANT, content=json.dumps({
            "stored_text": value["chunks"][0]["chunk_text"], "citation": value["chunks"][0]["citation"],
        }))]

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", stored_reply)
    message = "Quote the selected file's already stored extracted text and cite it. Do not infer native properties."
    for index, extension in enumerate(extensions):
        document = documents.read_item(LEFT, LEFT)
        document.update({
            "file_name": f"selected.{extension}", "num_chunks": 1,
            "indexed_chunk_count_version": document["version"],
        })
        for field in ("archived_blob_path", "accessibility_metadata"):
            document.pop(field, None)
        documents.upsert_item(document)
        marker = citations.annotate_document_search_payload({
            "document": {"id": LEFT, "file_name": document["file_name"], "version": document["version"]},
            "scope": "personal", "chunks": [stored_chunk(document)],
        }, "retrieve_document_chunks")["chunks"][0]["citation"]
        answer = f"The stored source states that the review is complete. {marker}"
        before_calls = len(state.native_calls)
        before_search = len(search_calls)
        before_context_reads = len(state.report_reads)
        response, events, plan, saved = submit_action_turn(
            state, message, answer, f"format-{index}-{extension}",
        )
        assert response.status_code == 200 and saved["status"] == "completed", (
            extension, saved.get("failure"), state.failures,
        )
        assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
        assert len(state.native_calls) - before_calls == 2, extension
        assert len(search_calls) - before_search == 1, extension
        assert len(state.report_reads) - before_context_reads == 1, extension
        assert native_attempts == [], extension
        assert len(harness.replies) == 0, extension
        saved_answer = harness.assistant_messages()[-1]
        assert answer == saved_answer["content"], extension
        assert not any(event.get("type") == "error" for event in events), extension
    assert len(search_calls) == len(extensions)
    assert len(harness.assistant_messages()) == len(extensions)


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("mode,code,stage,model_calls,report_reads", FAILURE_CASES)
def test_owned_action_failure_survives_saved_steps_and_private_logging(
    native_http, monkeypatch, caplog, debug, mode, code, stage, model_calls, report_reads,
):
    state = native_http
    harness = state.runtime.harness
    harness.settings["enable_debug_logging"] = debug
    document = harness.config.cosmos_user_documents_container.read_item(LEFT, LEFT)
    document.update({
        "file_name": "selected.pdf",
        "accessibility_metadata": {
            "format": "pdf", "schema_version": "1.0", "title": PRIVATE, "is_tagged": False,
        },
    })
    harness.config.cosmos_user_documents_container.upsert_item(document)
    loader = importlib.import_module("semantic_kernel_plugins.logged_plugin_loader")
    if mode == "loading":
        monkeypatch.setattr(loader.LoggedPluginLoader, "load_plugin_from_manifest", lambda *args, **kwargs: False)
    elif mode == "identity":
        reader = importlib.import_module("semantic_kernel_plugins.document_search_plugin")
        spec = importlib.util.spec_from_file_location(reader.__name__, reader.__file__)
        duplicate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(duplicate)
        monkeypatch.setattr(
            loader.LoggedPluginLoader, "_create_plugin_instance",
            lambda self, manifest: duplicate.DocumentSearchPlugin(deepcopy(manifest)),
        )
    elif mode == "read":
        state.fail_report = True
    else:
        async def no_results(self, history, settings):
            state.native_calls.append(deepcopy([message.to_dict() for message in history.messages]))
            return [ChatMessageContent(role=AuthorRole.ASSISTANT, content=PRIVATE)]

        monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", no_results)
    with caplog.at_level(logging.INFO, logger=state.logger.name):
        response, events, plan, saved = submit_action_turn(
            state, "Inspect only the selected document's native properties.",
            "This draft must never be composed after a failed acquisition.", f"failure-{mode}",
        )
    assert response.status_code == 200 and saved["status"] == "failed"
    assert saved.get("task_results") == {}
    assert len(state.native_calls) == model_calls
    assert len(state.report_reads) == report_reads
    assert len(harness.model_calls) == 2 and len(harness.replies) == 2
    steps_response = state.runtime.client.get(
        f"/api/v2/orchestration/runs/{plan['run_id']}/steps",
        query_string={"conversation_id": "conversation-1"},
    )
    steps_payload = steps_response.get_json()
    assert steps_response.status_code == 200
    failed_step = next(
        step for step in steps_payload["steps"] if step["step_id"] == plan["steps"][0]["step_id"]
    )
    assert failed_step["status"] == "failed"
    assert failed_step["failure"]["code"] == code
    schema = importlib.import_module("functions_orchestration_schema")
    expected = schema.build_failure(code)
    assert failed_step["failure"]["message"] == expected["message"]
    answers = harness.assistant_messages()
    assert len(answers) == 1 and expected["message"] in answers[0]["content"]
    assert PRIVATE not in response.get_data(as_text=True) + json.dumps(steps_payload) + json.dumps(answers)
    records = [
        record for record in caplog.records
        if getattr(record, "sc_message", None) == "[ORCHESTRATION_ADAPTERS] Direct action execution failed."
    ]
    assert len(records) == 1
    record = records[0]
    assert record.sc_failure_code == code and record.sc_stage == stage
    assert record.sc_run_id_hash == hashlib.sha256(plan["run_id"].encode()).hexdigest()
    assert record.sc_step_id_hash == hashlib.sha256(plan["steps"][0]["step_id"].encode()).hexdigest()
    assert record.sc_conversation_id_hash == hashlib.sha256(b"conversation-1").hexdigest()
    if stage in ("action_initialization", "document_action_read"):
        assert record.sc_function_calls_attempted is (stage == "document_action_read")
    else:
        assert not hasattr(record, "sc_function_calls_attempted")
    serialized = json.dumps({
        name: value for name, value in record.__dict__.items() if name.startswith("sc_")
    })
    assert PRIVATE not in serialized and LEFT not in serialized
    assert document["file_name"] not in serialized


@pytest.mark.parametrize("code", [case[1] for case in FAILURE_CASES])
def test_owned_action_codes_are_safe_nontransient_and_allow_manual_recovery(modules, code):
    actions = importlib.import_module("functions_orchestration_actions")
    schema = importlib.import_module("functions_orchestration_schema")
    failure = schema.failure_from_exception(actions.ActionExecutionError(PRIVATE, failure_code=code))
    transient = schema.failure_is_transient(failure)
    repeats = schema.failure_repeats_on_retry(failure)
    assert failure == schema.build_failure(code)
    assert not transient and not repeats
    assert PRIVATE not in json.dumps(failure)


@pytest.mark.parametrize("cause,code", [(TimeoutError, "provider_timeout"), (ConnectionError, "connection_failed")])
def test_unclassified_action_errors_preserve_transient_provider_causes(modules, cause, code):
    actions = importlib.import_module("functions_orchestration_actions")
    schema = importlib.import_module("functions_orchestration_schema")
    error = actions.ActionExecutionError(PRIVATE)
    error.__cause__ = cause(PRIVATE)
    failure = schema.failure_from_exception(error)
    transient = schema.failure_is_transient(failure)
    assert failure["code"] == code and transient
    assert PRIVATE not in json.dumps(failure)


def test_arbitrary_exception_failure_codes_are_not_admitted(modules):
    actions = importlib.import_module("functions_orchestration_actions")
    schema = importlib.import_module("functions_orchestration_schema")
    failure = schema.failure_from_exception(actions.ActionExecutionError(PRIVATE, failure_code=PRIVATE))
    expected = schema.build_failure("step_failed")
    assert failure == expected
    assert PRIVATE not in json.dumps(failure)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
