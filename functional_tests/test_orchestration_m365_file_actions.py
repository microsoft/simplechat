# test_orchestration_m365_file_actions.py
#!/usr/bin/env python3
"""
Functional test for SharePoint and OneDrive actions in chat orchestration.
Version: 0.261.300
Implemented in: 0.261.300

An orchestration "Use an action" step calls its model without a chat agent. SharePoint and
OneDrive file functions bound the content they return by the model's token budget, which
chat binds through the selected agent's continuation journal, and deeper file analysis needs
that agent's model. A plan step had neither, so ``search_files`` returned
``model_context_unavailable``. The step still reported completed, and the answer said the
documents couldn't be searched, while the same agent in chat found them.

These tests run the real action runner, step scope, Microsoft 365 runtime, approval service,
SharePoint plugin and the production file-runtime wiring (``configure_m365_file_runtime``)
through a real Flask bridge. Microsoft Graph, blob storage, Cosmos and the model are doubled,
and network access is blocked.
"""

import ast
import importlib
import json
import re
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent, FunctionResultContent

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

# The shared harness sets the application path and doubles; its fixtures run here too.
from test_orchestration_m365_actions import (  # noqa: E402,F401
    ACTION_REF, CONVERSATION, TENANT, USER, env, module, request_record, run_step, world,
)
from test_support.m365 import CosmosContainer  # noqa: E402

FILE_TEXT = (
    "The EVA Swab Tool collects microbial samples from spacesuits and spacecraft surfaces "
    "during spacewalks, supporting planetary protection and astrobiology research."
)
WEB_URL = "https://contoso.sharepoint.com/sites/research/Documents/eva-swab-tool.txt"
SNIPPET = "The <c0>EVA Swab Tool</c0> collects microbial samples during spacewalks."
ANALYSIS = "The EVA Swab Tool samples spacesuit and spacecraft surfaces for microbes."
ENDPOINT = {
    "id": "endpoint-1", "provider": "aoai",
    "connection": {"endpoint": "https://example.invalid", "openai_api_version": "2024-10-21"},
    "models": [{"id": "model-1", "deploymentName": "test-model", "modelName": "gpt-5.6-terra"}],
}
MODEL_CONTEXT = {"endpoint_id": "endpoint-1", "model_id": "model-1", "provider": "aoai"}


def sharepoint_action():
    return {
        "id": "sharepoint", "name": "m365_sharepoint", "display_name": "SharePoint",
        "type": "m365_sharepoint", "description": "Search SharePoint document libraries.",
        "action_ref": ACTION_REF, "scope_type": "personal", "scope_id": USER, "user_id": USER,
        "is_enabled": True, "additionalFields": {"m365_capabilities": {}},
    }


class GraphResponse:
    def __init__(self, payload=None, status=200, *, body=None, headers=None):
        self.status_code = status
        self.body = json.dumps(payload).encode() if body is None else body
        self.headers = headers or {"Content-Type": "application/json"}

    def iter_content(self, chunk_size):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]

    def close(self):
        pass


def file_item():
    return {
        "id": "item-1", "name": "eva-swab-tool.txt", "size": len(FILE_TEXT.encode()),
        "file": {"mimeType": "text/plain"}, "parentReference": {"driveId": "drive-1", "siteId": "site-1"},
        "webUrl": WEB_URL, "eTag": '"version-1"', "cTag": '"content-1"',
        "lastModifiedDateTime": "2026-09-17T12:00:00Z",
    }


def graph(state):
    def request(method, url, **kwargs):
        path = urlsplit(url).path.removeprefix("/v1.0")
        state.graph_calls.append({"method": method, "path": path})
        if path == "/me":
            # No Copilot license: search uses Microsoft Graph search, as for most users.
            return GraphResponse({"id": USER, "assignedLicenses": [], "assignedPlans": []})
        if path == "/search/query":
            return GraphResponse({"value": [{"hitsContainers": [{
                "total": 1, "moreResultsAvailable": False,
                "hits": [{"resource": file_item(), "summary": SNIPPET}],
            }]}]})
        if path == "/drives/drive-1":
            return GraphResponse({
                "id": "drive-1", "driveType": "documentLibrary",
                "webUrl": "https://contoso.sharepoint.com/sites/research/Documents",
            })
        if path == "/drives/drive-1/items/item-1":
            return GraphResponse(file_item())
        if path == "/drives/drive-1/items/item-1/content":
            body = FILE_TEXT.encode()
            return GraphResponse(body=body, headers={"Content-Type": "text/plain", "Content-Length": str(len(body))})
        raise AssertionError(f"Unexpected Microsoft Graph request: {method} {path}")

    return request


class MemoryBlobs:
    """Blob storage for conversation memory, held in memory with real ETag semantics."""

    def __init__(self, storage):
        self.storage = storage
        self.records = {}
        self.generation = 0

    def read(self, container, name, *, max_bytes):
        record = self.records.get((container, name))
        if record is None:
            raise self.storage.MemoryNotFoundError("No test blob.")
        if len(record.data) > max_bytes:
            raise AssertionError("The test attempted an oversized blob read.")
        return record

    def put(self, container, name, data, *, etag=None):
        current = self.records.get((container, name))
        if etag is None and current is not None or etag is not None and (current is None or current.etag != etag):
            raise self.storage.MemoryConflictError("Test ETag conflict.")
        self.generation += 1
        record = self.storage.BlobRecord(bytes(data), f"etag-{self.generation}")
        self.records[(container, name)] = record
        return record.etag

    def delete(self, container, name, *, etag):
        current = self.records.get((container, name))
        if current is None or current.etag != etag:
            raise self.storage.MemoryConflictError("Test ETag conflict.")
        del self.records[(container, name)]


def call(function, call_id, **arguments):
    return ChatMessageContent(
        role=AuthorRole.ASSISTANT,
        items=[FunctionCallContent(id=call_id, name=f"m365_sharepoint-{function}", arguments=json.dumps(arguments))],
    )


def reply(text):
    return ChatMessageContent(role=AuthorRole.ASSISTANT, content=text)


def as_result(value):
    """A function result as the step's model received it, as a dictionary."""
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return ast.literal_eval(str(value))


def prepared_memory_id(history):
    """The memory ID the step's earlier prepare_file call returned, read from its own history."""
    for message in reversed(history.messages):
        for item in message.items:
            if isinstance(item, FunctionResultContent) and item.function_name == "prepare_file":
                return as_result(item.result)["memory_id"]
    raise AssertionError("prepare_file has not returned a memory ID")


@pytest.fixture(scope="module")
def file_env(env):
    """The production file-runtime wiring, with conversation memory supplied per test."""
    holder = SimpleNamespace(binding=None)
    sys.modules["conversation_memory_runtime"] = module(
        "conversation_memory_runtime", resolve_m365_memory=lambda context: holder.binding(context),
    )
    # Plain-text extraction defers to the config-dependent content helpers; read the file directly.
    sys.modules["functions_content"] = module(
        "functions_content", extract_text_file=lambda path: Path(path).read_text(encoding="utf-8"),
    )
    file_runtime = importlib.import_module("functions_m365_file_runtime")
    file_runtime.configure_m365_file_runtime()
    yield SimpleNamespace(
        holder=holder, file_runtime=file_runtime,
        retrieval=importlib.import_module("functions_m365_retrieval"),
        continuation=importlib.import_module("functions_m365_agent_continuation"),
        sharepoint=importlib.import_module("semantic_kernel_plugins.m365_sharepoint_plugin"),
        memory=importlib.import_module("functions_conversation_memory"),
        storage=importlib.import_module("conversation_memory_storage"),
        capabilities=importlib.import_module("functions_model_capabilities"),
        transport=importlib.import_module("functions_m365_transport"),
    )


@pytest.fixture
def file_world(env, world, file_env, monkeypatch):
    blobs = MemoryBlobs(file_env.storage)

    def authorize(context, operation):
        return (
            context.tenant_id == TENANT and context.conversation_id == CONVERSATION
            and context.principal_id == USER and context.storage_owner == USER
        )

    def publish(context, run, grant_context):
        raise AssertionError("A private conversation never publishes file evidence.")

    store = file_env.memory.ConversationMemoryStore(
        transport=blobs, authorize_access=authorize, authorize_publish=publish,
        log_event=lambda *args, **kwargs: None,
    )
    file_env.holder.binding = lambda context: (store, file_env.memory.MemoryContext(
        tenant_id=context.tenant_id, principal_id=context.data_user_id,
        conversation_id=context.conversation_id, storage_owner=USER, request_id=context.request_id,
    ))
    monkeypatch.setattr(file_env.file_runtime, "cosmos_m365_execution_runs_container", world.jobs)
    world.action = sharepoint_action()
    world.store = store
    world.script = []
    world.model_calls = []
    # Each function result, as the step's model last received it in its chat history.
    world.results = {}
    world.endpoint = deepcopy(ENDPOINT)

    class Loader:
        def __init__(self, kernel):
            self.kernel = kernel
            self.plugin_instances = []

        def load_plugin_from_manifest(self, manifest, user_id):
            plugin = file_env.sharepoint.M365SharePointPlugin(deepcopy(manifest))
            world.loaded_functions.append(sorted(plugin.get_functions()))
            self.plugin_instances.append(plugin)
            self.kernel.add_plugin(plugin.get_kernel_plugin("m365_sharepoint"))
            return True

    async def model(service, history, settings):
        world.model_calls.append({"history": str(history), "settings": settings})
        for message in history.messages:
            for item in message.items:
                if isinstance(item, FunctionResultContent):
                    world.results[item.function_name] = as_result(item.result)
        if not world.script:
            raise AssertionError("The model was called more often than the test scripted")
        return [world.script.pop(0)(history)]

    world.loader = Loader
    monkeypatch.setattr(requests, "request", graph(world))
    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", model)
    # The step's model resolves the way production does; only endpoint lookup and client
    # construction are doubled, so the budget comes from the real resolution helpers.
    monkeypatch.setattr(env.actions, "_resolve_action_model", lambda settings, context, user_id: (
        world.service, "azure_openai", deepcopy(world.endpoint), dict(MODEL_CONTEXT),
    ))
    monkeypatch.setattr(env.actions, "_action_model_configuration", lambda *args: {"provider": "aoai", "parameters": {}})
    yield world
    file_env.holder.binding = None


def stopped(env, world):
    with pytest.raises(env.orchestration.OrchestrationM365Error) as caught:
        run_step(env, world)
    return caught.value


def approvals_service(env, monkeypatch):
    approvals = CosmosContainer()
    service = env.approvals.M365ApprovalService(
        container_factory=lambda: approvals, notification_sender=lambda approval: None,
        decision_validator=lambda approval: True,
    )
    monkeypatch.setattr(env.approvals, "_service", service)
    return service


def test_sharepoint_search_step_reads_documents_with_the_step_models_budget(env, file_env, file_world):
    file_world.script = [
        lambda history: call("search_files", "call-1", query="EVA Swab Tool"),
        lambda history: reply("SharePoint: the EVA Swab Tool collects microbial samples during spacewalks."),
    ]
    result, _context = run_step(env, file_world)

    assert result["calls"] == 1
    assert "EVA Swab Tool" in result["findings"]
    found = file_world.results["search_files"]
    assert found["status"] == "ok" and found["source"] == "spo"
    assert [item["display_name"] for item in found["results"]] == ["eva-swab-tool.txt"]
    assert "EVA Swab Tool collects microbial samples" in found["results"][0]["excerpts"][0]["text"]
    assert found["coverage"]["context_tokens"] > 0
    assert [call_info["path"] for call_info in file_world.graph_calls] == [
        "/me", "/search/query", "/drives/drive-1/items/item-1", "/drives/drive-1",
    ]
    # The excerpt reached the model as data, not a refusal it could describe as findings.
    assert "EVA Swab Tool collects microbial samples" in file_world.model_calls[1]["history"]
    assert not any("model_context_unavailable" in json.dumps(extra, default=str) for _message, extra in file_world.logs)
    record = request_record(env, file_world)
    assert record["status"] == "completed" and record["memory_budget_run_id"]


def test_step_model_without_verified_limits_stops_before_the_model_or_graph(env, file_env, file_world):
    file_world.endpoint["models"][0]["modelName"] = "unlisted-model"
    error = stopped(env, file_world)

    assert error.orchestration_failure_code == "m365_model_limits_required"
    assert error.m365_code == "model_generation_unbounded"
    assert error.m365_sources == ("spo",)
    assert file_world.model_calls == [] and file_world.graph_calls == []
    assert request_record(env, file_world)["status"] == "failed"
    failure = env.schema.failure_from_exception(error)
    assert failure == {
        "code": "m365_model_limits_required",
        "message": env.schema.FAILURE_MESSAGES["m365_model_limits_required"],
        "m365_sources": ["spo"],
    }
    stop_logs = [extra for message, extra in file_world.logs if "A Microsoft 365 step stopped" in message]
    assert stop_logs == [{
        "failure_code": "m365_model_limits_required", "authority_reason": "model_generation_unbounded",
        "capability_id": "action_invoke", "source_count": 1,
    }]


def test_unavailable_conversation_evidence_fails_the_step_instead_of_becoming_findings(env, file_env, file_world):
    def unavailable(context):
        raise file_env.storage.MemoryUnavailableError("Chat storage is not configured.")

    file_env.holder.binding = unavailable
    file_world.script = [
        lambda history: call("search_files", "call-1", query="EVA Swab Tool"),
        lambda history: reply("The document-evidence service could not run."),
    ]
    error = stopped(env, file_world)

    assert error.orchestration_failure_code == "m365_evidence_unavailable"
    assert error.m365_code == "memory_unavailable"
    assert error.m365_sources == ("spo",)
    # The refusal stopped the step before the model could report it as findings.
    assert len(file_world.model_calls) == 1
    assert request_record(env, file_world)["status"] == "failed"


def test_analysis_after_approval_runs_with_the_step_model(env, file_env, file_world, monkeypatch):
    service = approvals_service(env, monkeypatch)
    question = "What is the EVA Swab Tool used for?"

    def analyze(history):
        return call("analyze_file", "call-2", memory_id=prepared_memory_id(history), question=question)

    file_world.script = [
        lambda history: call("prepare_file", "call-1", drive_id="drive-1", item_id="item-1"),
        analyze,
    ]
    error = stopped(env, file_world)

    assert error.orchestration_failure_code == "m365_approval_required"
    approval = service.get_approval(error.approval_id, USER)
    assert approval["request_type"] == env.approvals.TYPE_EXTENDED_ANALYSIS and approval["status"] == "pending"
    record = request_record(env, file_world)
    assert record["status"] == "failed" and record["approval_id"] == error.approval_id
    downloads = [item for item in file_world.graph_calls if item["path"].endswith("/content")]
    assert len(downloads) == 1

    service.decide(error.approval_id, USER, {"choice": "request"})
    file_world.model_calls.clear()
    file_world.script = [
        lambda history: call("prepare_file", "call-1", drive_id="drive-1", item_id="item-1"),
        analyze,
        lambda history: reply(ANALYSIS),
        lambda history: reply(f"SharePoint analysis: {ANALYSIS}"),
    ]
    result, _context = run_step(env, file_world)

    assert result["calls"] == 2
    analysis = file_world.results["analyze_file"]
    assert analysis["status"] == "completed" and analysis["findings"] == ANALYSIS
    assert re.fullmatch(r"[0-9a-f]{32}", analysis["analysis_id"])
    # The retry reused the captured file, and the analysis batch ran on the step's own model,
    # with its evidence, no tools and the bounded batch output.
    assert len([item for item in file_world.graph_calls if item["path"].endswith("/content")]) == 1
    batch = next(item for item in file_world.model_calls if item["settings"].function_choice_behavior is None)
    assert FILE_TEXT in batch["history"] and question in batch["history"]
    assert not getattr(batch["settings"], "tools", None)
    assert 1536 in (getattr(batch["settings"], "max_completion_tokens", None), getattr(batch["settings"], "max_tokens", None))
    retried = request_record(env, file_world)
    assert retried["status"] == "completed" and retried["approval_id"] == error.approval_id


def test_step_binding_serves_only_its_own_request_and_ends_with_the_call(env, file_env, file_world):
    context = env.execution.M365ExecutionContext(
        actor_user_id=USER, data_user_id=USER, tenant_id=TENANT,
        conversation_id=CONVERSATION, request_id="orch-request-1",
    )
    budget = file_env.capabilities.resolve_model_token_budget(
        {"modelName": "gpt-5.6-terra"}, {"provider": "aoai"}, provider="aoai",
    )
    bind = file_env.continuation.m365_step_model_binder(
        context, service=file_world.service, model_token_budget=budget, tool_schemas=[],
    )
    with pytest.raises(file_env.transport.M365ProviderError) as unbound:
        file_env.file_runtime.resolve_m365_model_room(context)
    assert unbound.value.code == "model_context_unavailable"

    with bind([ChatMessageContent(role=AuthorRole.USER, content="What is the EVA Swab Tool?")]):
        room = file_env.file_runtime.resolve_m365_model_room(context)
        assert 0 < room < budget.context_window
        model = file_env.continuation.get_m365_analysis_model(context)
        assert model.model_token_budget is budget and model.deployment_name == "test-model"
        for foreign in (
            replace(context, request_id="orch-request-2"),
            replace(context, actor_user_id="user-2", data_user_id="user-2"),
            replace(context, conversation_id="conversation-2"),
        ):
            with pytest.raises(env.approvals.M365PolicyError) as refused:
                file_env.continuation.get_m365_analysis_model(foreign)
            assert refused.value.code == "m365_analysis_unavailable"

    with pytest.raises(file_env.transport.M365ProviderError):
        file_env.file_runtime.resolve_m365_model_room(context)
    with pytest.raises(env.approvals.M365PolicyError):
        file_env.continuation.get_m365_analysis_model(context)


def test_file_refusals_and_capacity_outcomes_map_to_the_right_step_result(env, file_env, file_world):
    refusal = env.orchestration.result_refusal
    for code in ("model_context_full", "memory_hard_limit", "request_operation_limit", "search_limit", "not_found"):
        assert refusal({"error": {"code": code}, "source": "spo"}) is None
    for code in (
        "model_context_unavailable", "model_generation_unbounded", "model_input_estimate_unavailable",
        "model_context_invalid", "model_tool_configuration_invalid",
    ):
        stop = refusal({"error": {"code": code}, "source": "spo"})
        assert stop.orchestration_failure_code == "m365_model_limits_required" and stop.m365_sources == ("spo",)
    for code in (
        "memory_unavailable", "memory_access_denied", "memory_context_mismatch", "memory_busy",
        "memory_recovery_required", "request_memory_binding_required", "request_memory_mismatch",
        "request_memory_busy", "invalid_request_memory", "invalid_model_budget",
        "m365_continuation_unavailable",
    ):
        stop = refusal(json.dumps({"error": {"code": code}, "source": "onedrive"}))
        assert stop.orchestration_failure_code == "m365_evidence_unavailable" and stop.m365_sources == ("onedrive",)
    assert env.orchestration.m365_file_source({"type": "m365_sharepoint"}) == "spo"
    assert env.orchestration.m365_file_source({"type": "m365_onedrive"}) == "onedrive"
    assert env.orchestration.m365_file_source({"type": "m365_email"}) is None


def test_step_budget_comes_from_the_resolved_model_records(env, file_env, file_world):
    budget_for = env.actions._action_model_budget
    service = file_world.service
    endpoint_budget = budget_for({}, service, "azure_openai", deepcopy(ENDPOINT), dict(MODEL_CONTEXT))
    assert endpoint_budget.model_id == "gpt-5.6-terra" and endpoint_budget.provider == "azure"
    assert endpoint_budget.request_output_limit is None and endpoint_budget.remaining_input(0) > 0

    legacy = budget_for(
        {"gpt_model": {"selected": [{"deploymentName": "test-model", "modelName": "gpt-5.6-terra"}]}},
        service, "azure_openai", None, {},
    )
    assert legacy.model_id == "gpt-5.6-terra" and legacy.remaining_input(0) > 0

    messages = budget_for({}, service, "anthropic", deepcopy(ENDPOINT), dict(MODEL_CONTEXT))
    assert messages.protocol == "messages"

    unlisted = deepcopy(ENDPOINT)
    unlisted["models"][0]["modelName"] = "unlisted-model"
    unverified = budget_for({}, service, "azure_openai", unlisted, dict(MODEL_CONTEXT))
    with pytest.raises(file_env.capabilities.ModelTokenBudgetError):
        unverified.remaining_input(0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
