# test_orchestration_document_action_end_to_end.py
"""
Authenticated native-document orchestration from HTTP submission to saved answer.
Version: 0.261.425
Implemented in: 0.261.419
Production plugin discovery coverage added in: 0.261.421

Real routes, plugin discovery, approval/leases, native action filters,
report/citation projection, retention, composition, completeness and publication
run with external storage, configuration and model I/O isolated. No production
service or data is touched.
"""

import asyncio
import importlib
import json
import logging
import traceback
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent

from functions_task_completeness import NARRATIVE_OBLIGATIONS
from functions_native_audit import render_native_audit
from test_orchestration_harness_routes import modules, real_http_harness
from test_orchestration_planner_contract_recovery import ACTION, action_proposal
from test_orchestration_source_kind_planning import LEFT, source_runtime
from test_support.orchestration_revisions import AtomicMemoryContainer


__all__ = ["modules", "real_http_harness", "source_runtime"]
TURN = "native-http-turn"
MESSAGE = "Inspect native metadata in only the selected source and disclose its limits."
PRIVATE = "PRIVATE_NATIVE_METADATA_SENTINEL"
TRACE_MESSAGES = {
    "[ORCHESTRATION_ADAPTERS] Document action binding verified.",
    "[ORCHESTRATION_ADAPTERS] Document action binding rechecked.",
    "[ORCHESTRATION_ADAPTERS] Document action read checkpoint.",
    "[ORCHESTRATION_EXECUTOR] Gather retention started.",
    "[ORCHESTRATION_EXECUTOR] Gather source handoff verified.",
    "[ORCHESTRATION_EXECUTOR] Gather result retained.",
    "[ORCHESTRATION_EXECUTOR] Retained document citation projection verified.",
    "[ORCHESTRATION_EXECUTOR] Composition input contract verified.",
    "[ORCHESTRATION_EXECUTOR] Prepared content retained.",
}


@pytest.fixture
def native_http(source_runtime, modules, monkeypatch):
    runtime = source_runtime
    harness = runtime.harness
    catalog = importlib.import_module("functions_action_catalog")
    settings_owner = importlib.import_module("functions_settings")
    governance = importlib.import_module("functions_governance")
    runner = importlib.import_module("functions_orchestration_actions")
    search = importlib.import_module("functions_search_service")
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.orchestration.native.http")
    harness.settings.update({
        "enable_semantic_kernel": True, "enable_chat_orchestration_actions": True,
        "enable_user_workspace": True, "allow_user_plugins": True,
        "per_user_semantic_kernel": True, "allow_group_plugins": False,
        "max_auto_invoke_attempts": 4,
        "enable_chat_orchestration_completeness_check": True,
    })
    action = {
        **ACTION, "id": "native-action", "user_id": "owner", "name": "document_search",
        "action_ref": catalog._action_ref("personal", "owner", "native-action"), "is_enabled": True,
    }
    actions = AtomicMemoryContainer("user_id")
    actions.create_item({key: value for key, value in action.items() if key != "action_ref"})
    users = AtomicMemoryContainer("id")
    users.create_item({"id": "owner", "settings": {"enable_agents": True}})
    monkeypatch.setattr(harness.config, "cosmos_personal_actions_container", actions)
    monkeypatch.setattr(harness.config, "cosmos_user_settings_container", users)
    monkeypatch.setattr(settings_owner, "get_settings", lambda: deepcopy(harness.settings))
    monkeypatch.setattr(governance, "get_settings", lambda: deepcopy(harness.settings))
    monkeypatch.setattr(
        importlib.import_module("functions_group"), "get_user_groups", lambda user_id: [],
    )
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {
        "enable_debug_logging": harness.settings.get("enable_debug_logging", False),
    })
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    state = SimpleNamespace(
        runtime=runtime, modules=modules, action=action, actions=actions, users=users,
        logger=logger, native_calls=[], report_reads=[], fail_report=False, failures=[],
    )
    log_failure = harness.execution._log_failure

    def capture_failure(message, record, error, **kwargs):
        state.failures.append("".join(traceback.format_exception(error)))
        return log_failure(message, record, error, **kwargs)

    monkeypatch.setattr(harness.execution, "_log_failure", capture_failure)
    executor = importlib.import_module("functions_orchestration_executor")
    step_failure = executor._raise_dependency_service_failure

    def capture_step_failure(step, error):
        state.failures.append("".join(traceback.format_exception(error)))
        return step_failure(step, error)

    monkeypatch.setattr(executor, "_raise_dependency_service_failure", capture_step_failure)

    def read_personal(document_id, user_id):
        state.report_reads.append((document_id, user_id))
        if state.fail_report:
            raise PermissionError(PRIVATE)
        document = harness.config.cosmos_user_documents_container.read_item(document_id, document_id)
        if document.get("user_id") != user_id:
            return None
        return {"document": document, "scope": "personal", "group_id": None, "public_workspace_id": None}

    monkeypatch.setattr(search, "_resolve_personal_document_context", read_personal)
    service = AzureChatCompletion(
        service_id="orchestration-action", deployment_name="gpt-4o",
        endpoint="https://offline.invalid", api_key="offline-fixture-not-a-credential", api_version="2024-10-21",
    )
    configuration = {
        "provider": "aoai", "protocol": "azure_openai", "endpoint": "https://offline.invalid",
        "api_version": "2024-10-21", "deployment": "gpt-4o", "parameters": {},
    }
    monkeypatch.setattr(runner, "_build_action_model", lambda *args, capture_configuration=False: (
        (service, deepcopy(configuration)) if capture_configuration else service
    ))

    async def native_reply(self, history, settings):
        state.native_calls.append(deepcopy([message.to_dict() for message in history.messages]))
        if len(state.native_calls) == 1:
            return [ChatMessageContent(role=AuthorRole.ASSISTANT, items=[FunctionCallContent(
                id="read-native", name="document_search-get_document_accessibility_report",
                arguments=json.dumps({"document_id": LEFT, "doc_scope": "personal"}),
            )])]
        results = [
            item.result for message in history.messages for item in message.items
            if hasattr(item, "result")
        ]
        value = results[-1]
        value = json.loads(value) if isinstance(value, str) else value
        return [ChatMessageContent(role=AuthorRole.ASSISTANT, content=json.dumps({
            "native_metadata": value["accessibility_metadata"], "citation": value["citation"],
        }))]

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", native_reply)
    # The offline Windows loop is created before network blocking; never permit a new socket pair.
    monkeypatch.setattr(asyncio, "run", modules.execution_loop.run_until_complete)
    yield state
    if not service.client.is_closed():
        modules.execution_loop.run_until_complete(service.client.close())


def frames(response):
    return [
        json.loads(frame.partition("data:")[2])
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]


def test_sdk_transport_options_preserve_partition_etag_and_failure_semantics():
    container = AtomicMemoryContainer("scope")
    created = container.create_item({"id": "record", "scope": "owner", "value": 1})
    record = container.read_item(
        "record", "owner", connection_timeout=10.0, read_timeout=10.0, retry_total=0,
    )
    assert type(record) is CosmosDict and record["_etag"] == created["_etag"]
    with pytest.raises(exceptions.CosmosResourceNotFoundError):
        container.read_item("record", "other", read_timeout=10.0)
    updated = container.replace_item(
        "record", {**record, "value": 2}, etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    assert type(updated) is CosmosDict and updated["_etag"] != record["_etag"]
    with pytest.raises(exceptions.CosmosAccessConditionFailedError):
        container.replace_item(
            "record", {**record, "value": 3}, etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    container.fail_reads = True
    with pytest.raises(AzureError):
        container.read_item("record", "owner", connection_timeout=10.0, read_timeout=10.0, retry_total=0)


@pytest.mark.parametrize("extension", ["pdf", "docx"])
@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("report_fails", [False, True])
def test_native_auto_turn_reaches_a_saved_cited_answer(native_http, caplog, extension, debug, report_fails):
    state = native_http
    runtime, harness = state.runtime, state.runtime.harness
    harness.settings["enable_debug_logging"] = debug
    state.fail_report = report_fails
    documents = harness.config.cosmos_user_documents_container
    document = documents.read_item(LEFT, LEFT)
    document["file_name"] = f"selected.{extension}"
    document["accessibility_metadata"] = {
        "format": extension, "schema_version": "1.0", "title": PRIVATE,
        "inspection_limits": ["Formal conformance is not determined."],
        **({"is_tagged": False} if extension == "pdf" else {
            "comments": [{"id": "comment-1", "text": "Review this date."}],
        }),
    }
    if extension == "pdf":
        # This control deliberately represents an old stored-only snapshot, not PDF bytes.
        for field in ("blob_path", "archived_blob_path", "source_file_available", "enhanced_citations"):
            document.pop(field, None)
    documents.upsert_item(document)
    citations = importlib.import_module("functions_agent_document_citations")
    marker = citations.annotate_document_search_payload({
        "document": {"id": LEFT, "file_name": document["file_name"], "version": document["version"]},
        "scope": "personal",
    }, "get_document_accessibility_report")["citation"]
    finding = "The stored PDF tag flag is false." if extension == "pdf" else "Native comment: Review this date."
    answer = f"{finding} Formal conformance is not determined. {marker}"
    proposal = action_proposal((LEFT,), action=state.action)
    proposal["steps"][0]["arguments"]["task"] = MESSAGE
    proposal["steps"][1]["arguments"]["instruction"] = (
        "Report the native facts, source citations, and explicit inspection limits."
    )

    rendered_answer = [answer]

    def compose_reply():
        payload = json.loads(harness.model_calls[-1]["messages"][-1]["content"])
        contract = payload.get("native_audit_contract")
        if contract is None:
            return answer
        rendered_answer[0] = f"{answer}\n\n{render_native_audit(contract)}"
        return json.dumps({"native_claims": [fact["id"] for fact in contract["facts"]], "answer": answer})

    def completeness_reply():
        return json.dumps({"requirements": [{
            "id": identifier, "requirement": requirement, "status": "satisfied",
            "reason": "", "evidence_refs": [], "answer_quote": rendered_answer[0],
        } for identifier, requirement in NARRATIVE_OBLIGATIONS]})

    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": MESSAGE, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal),
        compose_reply,
        completeness_reply,
    ]
    with caplog.at_level(logging.INFO, logger=state.logger.name):
        response = runtime.client.post("/api/v2/orchestration/plan", json={
            "conversation_id": "conversation-1", "turn_id": TURN, "message": MESSAGE,
            "planning_submission_id": "native-submit", "approval_mode": "auto",
            "selected_document_ids": [LEFT],
        }, buffered=True)
    events = frames(response)
    plan = next(event["plan"] for event in events if event.get("type") == "orchestration_plan")
    saved = harness.runs.read_item(plan["run_id"], "conversation-1")
    turn_response = runtime.client.get(
        f"/api/v2/orchestration/turns/{TURN}", query_string={"conversation_id": "conversation-1"},
    )
    turn = turn_response.get_json()["turn"]
    assert turn_response.status_code == 200 and turn["status"] == saved["status"]
    assert turn["run_id"] == plan["run_id"]
    questions = [
        message for message in harness.messages.items.values()
        if (message.get("metadata") or {}).get("orchestration_turn_id") == TURN and message.get("role") == "user"
    ]
    assert len(questions) == 1 and questions[0]["content"] == MESSAGE
    records = [
        record for record in caplog.records if getattr(record, "sc_message", None) in TRACE_MESSAGES
    ]
    assert bool(records) is debug
    if debug:
        serialized = json.dumps([
            {name: value for name, value in record.__dict__.items() if name.startswith("sc_")}
            for record in records
        ])
        assert PRIVATE not in serialized and LEFT not in serialized
        assert document["file_name"] not in serialized
    if report_fails:
        assert response.status_code == 200 and saved["status"] == "failed"
        assert saved.get("task_results") == {}
        assert len(state.native_calls) == 1 and state.report_reads == [(LEFT, "owner")]
        assert len(harness.model_calls) == 2 and len(harness.replies) == 2
        assert PRIVATE not in response.get_data(as_text=True)
        if debug:
            reads = [record for record in records if record.sc_stage == "document_action_read"]
            assert [record.sc_outcome for record in reads] == ["started", "failed"]
            assert not any(record.sc_stage in ("gather_retained", "compose_retained") for record in records)
        return
    assert response.status_code == 200 and saved["status"] == "completed", "\n".join(state.failures)
    assert [step["capability_id"] for step in plan["steps"]] == ["action_invoke", "compose"]
    assert plan["steps"][0]["arguments"]["document_ids"] == [LEFT]
    answers = harness.assistant_messages()
    assert len(answers) == 1 and marker in answers[0]["content"]
    if extension == "pdf":
        assert "inaccessible" in answers[0]["content"] and "Stored legacy snapshot" in answers[0]["content"]
    else:
        assert finding in answers[0]["content"]
        assert "Formal conformance is not determined." in answers[0]["content"]
    assert len(state.native_calls) == 2 and state.report_reads == [(LEFT, "owner")]
    assert len(harness.model_calls) == 4 and harness.replies == []
    compose_call = next(
        call for call in harness.model_calls if call["messages"][0]["content"].startswith("Prepare only")
    )
    prepared = json.loads(compose_call["messages"][-1]["content"])["inputs"]["native_findings"]
    native = json.loads(prepared["value"]["notes"][0].partition("\n")[2])
    assert native["native_metadata"] == document["accessibility_metadata"]
    assert native["citation"] == prepared["document_citations"][0]["citation"] == marker
    if debug:
        stages = {record.sc_stage for record in records}
        assert {
            "document_action_binding", "document_action_recheck", "document_action_read",
            "gather_retention", "gather_retained", "retained_citation_projection",
            "gather_source_handoff", "compose_inputs", "compose_retained",
        } <= stages
