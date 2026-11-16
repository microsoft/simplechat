# test_orchestration_document_action_binding.py
"""
Functional regressions for enforced native document action source bindings.
Version: 0.261.423
Implemented in: 0.261.419

The real action runner, Semantic Kernel filters, Document Search plugin and
citation projection run with model and source-service I/O doubled. Existing
source-authority suites cover the underlying readers' current-access checks.
"""

import asyncio
import importlib
import json
import logging
import sys
from contextlib import nullcontext
from copy import deepcopy
from types import ModuleType, SimpleNamespace

import pytest
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent

from test_orchestration_harness_routes import modules


__all__ = ["modules"]
SOURCE = "selected-source"


@pytest.fixture
def native_action(modules, monkeypatch):
    runner = importlib.import_module("functions_orchestration_actions")
    contexts = importlib.import_module("agent_execution_context")
    action = {
        "action_ref": "personal:actor:native", "id": "native", "name": "document_search",
        "display_name": "Native inspection", "type": "document_search",
        "scope_type": "personal", "scope_id": "actor",
    }
    state = SimpleNamespace(
        runtime=runner, contexts=contexts, loop=modules.execution_loop,
        action=action, manifest={**action, "additionalFields": {}},
        settings={
            "enable_chat_orchestration": True, "enable_chat_orchestration_actions": True,
            "enable_semantic_kernel": True, "max_auto_invoke_attempts": 5,
        },
        loads=[], requests=[], replies=[],
    )
    state.context = SimpleNamespace(
        action_catalog=[action], active_group_ids=[], token_usage={}, notes=[],
        user_id="actor", conversation_id="conversation",
        agent_execution_identity=contexts.ExecutionIdentity(
            "actor", "conversation", bridge=lambda reference: nullcontext(),
        ),
        delegation_budget=contexts.DelegationBudget(),
    )
    plugin_module = importlib.import_module("semantic_kernel_plugins.document_search_plugin")
    selection = importlib.import_module("functions_workflow_document_selection")
    logger = importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger")
    monkeypatch.setattr(logger, "get_current_user_id", lambda: "actor")
    state.native_reads, state.native_payloads, state.source_checks = [], [], 0
    state.allowed, state.scope, state.scope_id = True, "personal", "actor"
    state.metadata = {
        "format": "pdf", "schema_version": "1.0", "is_tagged": False,
        "inspection_limits": ["No structure tree is stored for this source."],
    }

    def authorize():
        state.source_checks += 1
        if not state.allowed:
            raise PermissionError("The source is no longer available.")

    def payload(operation, **kwargs):
        state.native_reads.append((operation, deepcopy(kwargs)))
        identifier = kwargs.get("document_id", SOURCE)
        if not selection.selected_source_matches("actor", identifier, state.scope, state.scope_id):
            raise LookupError("The source is outside the bound workspace.")
        document = {
            "id": SOURCE, "file_name": f"selected.{state.metadata['format']}",
            "user_id": "actor", "scope": state.scope, "scope_id": state.scope_id, "version": 1,
        }
        result = {
            "document": document, "scope": state.scope, "format": state.metadata["format"],
            "accessibility_metadata": deepcopy(state.metadata),
        }
        if operation == "search":
            result["results"] = [{
                "document_id": SOURCE, "file_name": document["file_name"],
                "id": f"{SOURCE}_1", "page_number": 1, "chunk_text": "Stored native evidence.",
            }]
        elif operation == "chunks":
            result["chunks"] = [{
                "document_id": SOURCE, "file_name": document["file_name"],
                "id": f"{SOURCE}_1", "page_number": 1, "chunk_text": "Stored native evidence.",
            }]
        elif operation == "summary":
            result["summary"] = "Source-grounded summary."
        state.native_payloads.append(result)
        return result

    monkeypatch.setattr(plugin_module, "get_current_user_id", lambda: "actor")
    monkeypatch.setattr(plugin_module, "get_document_accessibility_payload", lambda **kwargs: payload("native", **kwargs))
    monkeypatch.setattr(plugin_module, "get_document_chunks_payload", lambda **kwargs: payload("chunks", **kwargs))
    monkeypatch.setattr(plugin_module, "summarize_document_content", lambda **kwargs: payload("summary", **kwargs))
    monkeypatch.setattr(plugin_module, "run_document_search", lambda **kwargs: payload("search", **kwargs))

    class Loader:
        def __init__(self, kernel):
            self.kernel, self.plugin_instances = kernel, []

        def load_plugin_from_manifest(self, manifest, user_id):
            plugin = plugin_module.DocumentSearchPlugin(manifest)
            self.plugin_instances.append(plugin)
            state.loads.append((manifest["id"], user_id))
            self.kernel.add_plugin(plugin, plugin_name="document_search")
            return True

    loader_module = ModuleType("semantic_kernel_plugins.logged_plugin_loader")
    loader_module.create_logged_plugin_loader = Loader
    monkeypatch.setitem(sys.modules, "semantic_kernel_plugins.logged_plugin_loader", loader_module)
    preparation = ModuleType("semantic_kernel_loader")
    preparation.get_max_auto_invoke_attempts = lambda settings: settings["max_auto_invoke_attempts"]
    preparation.prepare_action_plugin_manifest = lambda manifest, settings: deepcopy(manifest)
    monkeypatch.setitem(sys.modules, "semantic_kernel_loader", preparation)
    monkeypatch.setattr(
        importlib.import_module("functions_settings"), "get_settings", lambda: deepcopy(state.settings),
    )
    monkeypatch.setattr(runner, "resolve_action_manifest", lambda *args, **kwargs: deepcopy(state.manifest))
    state.service = AzureChatCompletion(
        service_id="orchestration-action", deployment_name="offline-model",
        endpoint="https://offline.invalid", api_key="offline-fixture-not-a-credential", api_version="2024-10-21",
    )
    monkeypatch.setattr(runner, "_build_action_model", lambda *args, **kwargs: state.service)
    state.check_sources = authorize

    async def reply(self, history, settings):
        state.requests.append(str(history))
        if state.replies:
            return [state.replies.pop(0)]
        native = state.native_payloads[-1]
        return [ChatMessageContent(
            role=AuthorRole.ASSISTANT,
            content=json.dumps({
                "native_evidence": native["accessibility_metadata"],
                "citation": native.get("citation"),
            }),
        )]

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", reply)
    yield state
    if not state.service.client.is_closed():
        state.loop.run_until_complete(state.service.client.close())


def tool_call(function, arguments):
    return ChatMessageContent(
        role=AuthorRole.ASSISTANT,
        items=[FunctionCallContent(
            id="native-call", name=f"document_search-{function}", arguments=json.dumps(arguments),
        )],
    )


async def execute(state):
    return await state.runtime.invoke_action(
        state.action["action_ref"], "Inspect only the selected source.", state.context,
        settings=state.settings, user_id="actor", cancel_requested=lambda: False,
        document_sources=[{"document_id": SOURCE, "scope": state.scope, "scope_id": state.scope_id}],
        document_source_check=state.check_sources,
        m365_origin={"step_id": "inspect", "run_id": getattr(state.context, "run_id", None)},
    )


@pytest.mark.parametrize("scope,scope_id", [
    ("personal", "actor"), ("group", "group-1"), ("public", "workspace-1"),
])
def test_native_metadata_and_citations_survive_the_real_action_loop(native_action, scope, scope_id):
    state = native_action
    state.scope, state.scope_id = scope, scope_id
    state.manifest["additionalFields"] = {
        "allowed_scopes": [scope], "allowed_group_ids": ["group-1"],
        "allowed_public_workspace_ids": ["workspace-1"],
    }
    state.replies = [tool_call("get_document_accessibility_report", {"document_id": SOURCE})]
    result = state.loop.run_until_complete(execute(state))
    evidence = json.loads(result["findings"])
    assert result["calls"] == 1 and state.source_checks == 2
    assert len(state.native_reads) == 1 and state.native_reads[0][1]["doc_scope"] == scope
    assert evidence["native_evidence"]["is_tagged"] is False
    assert evidence["native_evidence"]["inspection_limits"] == state.metadata["inspection_limits"]
    assert evidence["citation"] and SOURCE in evidence["citation"]
    assert state.contexts.current_agent_execution() is None
    selection = importlib.import_module("functions_workflow_document_selection")
    outside_matches = selection.selected_source_matches("actor", "outside", scope, scope_id)
    assert outside_matches is True


def test_native_word_comments_are_not_replaced_with_body_text(native_action):
    state = native_action
    state.metadata = {
        "format": "docx", "schema_version": "1.0",
        "comments": [
            {"id": "comment-1", "text": "Review this date.", "author": "Reviewer", "anchor": "15 December"},
            {"id": "reply-1", "parent_id": "comment-1", "text": "Use the approved date."},
        ],
        "inspection_limits": ["Resolution state is not exposed by this stored report."],
    }
    state.replies = [tool_call("get_document_accessibility_report", {"document_id": SOURCE})]
    result = state.loop.run_until_complete(execute(state))
    evidence = json.loads(result["findings"])
    assert evidence["native_evidence"]["comments"] == state.metadata["comments"]
    assert evidence["native_evidence"]["inspection_limits"] == state.metadata["inspection_limits"]
    assert evidence["citation"] and SOURCE in evidence["citation"]


def test_search_without_a_model_filter_is_restricted_before_source_io(native_action):
    state = native_action
    state.replies = [tool_call("search_documents", {"query": "native evidence"})]
    result = state.loop.run_until_complete(execute(state))
    assert result["calls"] == 1 and len(state.native_reads) == 1
    assert state.native_reads[0][1]["document_ids"] == SOURCE


@pytest.mark.parametrize("function,arguments", [
    ("get_document_accessibility_report", {"document_id": "outside"}),
    ("retrieve_document_chunks", {"document_id": "outside"}),
    ("summarize_document", {"document_id": "outside"}),
    ("search_documents", {"query": "evidence", "document_ids": "outside"}),
])
def test_unselected_documents_are_rejected_before_source_io(native_action, function, arguments):
    state = native_action
    state.replies = [tool_call(function, arguments)]
    with pytest.raises(state.runtime.ActionExecutionError):
        state.loop.run_until_complete(execute(state))
    assert state.native_reads == []


def test_action_workspace_restrictions_remain_in_force(native_action):
    state = native_action
    state.manifest["additionalFields"] = {"allowed_scopes": ["group"]}
    state.replies = [tool_call(
        "get_document_accessibility_report", {"document_id": SOURCE, "doc_scope": "personal"},
    )]
    with pytest.raises(state.runtime.ActionExecutionError):
        state.loop.run_until_complete(execute(state))
    assert state.native_reads == []


def test_revoked_authority_stops_the_tool_before_source_io(native_action):
    state = native_action
    checks = []

    def authorize():
        checks.append(True)
        if len(checks) > 1:
            raise PermissionError("The source is no longer available.")

    state.check_sources = authorize
    state.replies = [tool_call("get_document_accessibility_report", {"document_id": SOURCE})]
    with pytest.raises(state.runtime.ActionExecutionError):
        state.loop.run_until_complete(execute(state))
    assert len(checks) == 2 and state.native_reads == []


def test_other_integrations_cannot_receive_a_document_source_binding(native_action):
    state = native_action
    state.action["type"] = state.manifest["type"] = "openapi"
    with pytest.raises(state.runtime.ActionExecutionError):
        state.loop.run_until_complete(execute(state))
    assert state.loads == state.requests == state.native_reads == []


def test_source_bindings_are_isolated_between_concurrent_tasks(modules):
    selection = importlib.import_module("functions_workflow_document_selection")

    async def inspect(document_id):
        entries = [{"document": {"document_id": document_id, "scope_type": "personal", "scope_id": "actor"}}]
        with selection.selected_document_sources(entries, "actor", restrict_ids=True):
            await asyncio.sleep(0)
            own = selection.selected_source_matches("actor", document_id, "personal", "actor")
            other = selection.selected_source_matches("actor", f"other-{document_id}", "personal", "actor")
            return own, other

    async def run():
        return await asyncio.gather(inspect("first"), inspect("second"))

    results = modules.execution_loop.run_until_complete(run())
    assert results == [(True, False), (True, False)]


@pytest.mark.parametrize("debug", [False, True])
def test_read_checkpoints_are_debug_gated_correlated_and_content_free(native_action, monkeypatch, caplog, debug):
    state = native_action
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.orchestration.native.read")
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": debug})
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    state.context.run_id, state.context.turn_id = "native-run", "native-turn"
    state.metadata["title"] = "PRIVATE_NATIVE_REPORT_CONTENT"
    state.replies = [tool_call("get_document_accessibility_report", {"document_id": SOURCE})]
    with caplog.at_level(logging.INFO, logger=logger.name):
        result = state.loop.run_until_complete(execute(state))
    records = [
        record for record in caplog.records
        if getattr(record, "sc_message", None)
        == "[ORCHESTRATION_ADAPTERS] Document action read checkpoint."
    ]
    assert result["calls"] == 1 and len(state.native_reads) == 1 and state.source_checks == 2
    assert len(state.requests) == 2
    assert len(records) == (2 if debug else 0)
    if debug:
        assert [record.sc_outcome for record in records] == ["started", "completed"]
        assert records[-1].sc_native_metadata_present is True
        assert records[-1].sc_citation_present is True
        for record in records:
            assert len(record.sc_conversation_id_hash) == len(record.sc_run_id_hash) == 64
            assert len(record.sc_turn_id_hash) == len(record.sc_step_id_hash) == 64
            assert len(record.sc_document_id_hash) == 64
        serialized = json.dumps([
            {name: value for name, value in record.__dict__.items() if name.startswith("sc_")}
            for record in records
        ])
        assert "PRIVATE_NATIVE_REPORT_CONTENT" not in serialized
        assert SOURCE not in serialized


@pytest.mark.parametrize("changed", [False, True])
def test_adapter_passes_exact_authorized_sources_and_rechecks_the_snapshot(native_action, monkeypatch, changed):
    state = native_action
    adapters = importlib.import_module("functions_orchestration_adapters")
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    registry = importlib.import_module("functions_orchestration_registry")
    context = state.context
    context.run_id, context.attempt_index, context.turn_id, context.seeds = "run-1", 1, "turn-1", {}
    producer = contracts.ProducerIdentity(
        "actor", "conversation", "run-1", 1, "inspect", "action_invoke",
        registry.get_capability("action_invoke")["result_contract_version"],
    )
    context.result_producer = lambda step: producer
    context.external_source_preflight = lambda **kwargs: None
    context.capture_external_source_configuration = lambda *args, **kwargs: True
    current = {"version": 1}
    reads = []

    def resolve(identifiers):
        reads.append(list(identifiers))
        return [{
            "document_id": identifier, "scope": "personal", "scope_id": "actor",
            "source_version": current["version"], "source_revision": str(current["version"]),
            "authorization_status": "authorized",
        } for identifier in identifiers]

    context.resolve_source_manifest = resolve

    async def invoke(*args, document_sources, document_source_check, **kwargs):
        assert [source["document_id"] for source in document_sources] == [SOURCE]
        if changed:
            current["version"] = 2
        document_source_check()
        return {
            "root_id": context.delegation_budget.root_id, "invocations": [], "calls": 1,
            "findings": "Native evidence from the selected source.", "artifacts": [],
        }

    monkeypatch.setattr(state.runtime, "invoke_action", invoke)
    # Windows' offline guard keeps the existing pre-created loop, not a new loopback socket pair.
    monkeypatch.setattr(asyncio, "run", state.loop.run_until_complete)
    result = adapters.run_action_invoke({
        "step_id": "inspect", "capability_id": "action_invoke",
        "arguments": {"action_ref": state.action["action_ref"], "task": "Inspect native evidence.",
                      "document_ids": [SOURCE]},
    }, context, settings=state.settings, user_id="actor", emit=None, cancel_requested=lambda: False)
    assert reads == [[SOURCE], [SOURCE]]
    assert result["status"] == ("failed" if changed else "completed")
