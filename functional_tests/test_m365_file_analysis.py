# test_m365_file_analysis.py
#!/usr/bin/env python3
"""
Functional tests for source-specific retained-file analysis tools.
Version: 0.261.029
Implemented in: 0.261.029

Real provider modules validate capability and retained conversation context.
The parent-owned async callback controls source checks, approvals, and one
bounded processing batch; the adapter never reads fresh Microsoft 365 content.
"""

import asyncio
from copy import deepcopy
from dataclasses import replace
from inspect import iscoroutinefunction
from unittest.mock import AsyncMock, Mock

import pytest

from test_m365_provider_core import (
    ContentGraphFixture,
    REAL_AUTHORIZE_CAPABILITY,
    _analysis_required,
    execution,
    memory_runtime,
    real_content_helpers,
)
import functions_m365_execution as execution_module
import functions_m365_retrieval as retrieval
from functions_conversation_memory import MemoryAuthorizationError
from semantic_kernel_plugins.m365_onedrive_plugin import M365OneDrivePlugin
from semantic_kernel_plugins.m365_sharepoint_plugin import M365SharePointPlugin


def _plugin(source):
    plugin_class = M365OneDrivePlugin if source == "onedrive" else M365SharePointPlugin
    return plugin_class({"id": f"action-{source}"})


def _configure_analysis(runtime, monkeypatch, callback):
    monkeypatch.setattr(retrieval, "_analysis_callback", None)
    retrieval.configure_m365_retrieval(
        memory_resolver=runtime.binding,
        request_run_resolver=runtime.request_run,
        model_budget_resolver=lambda context: runtime.settings["model_room"],
        token_counter=lambda text, context: len(text),
        analysis_callback=callback,
    )


@pytest.mark.parametrize("source", ["onedrive", "spo"])
@pytest.mark.parametrize("reference_key", ["memory_id", "evidence_reference"])
def test_analyze_delegates_one_authorized_batch_and_preserves_progress(
    execution, memory_runtime, real_content_helpers, monkeypatch, source, reference_key,
):
    fixture = ContentGraphFixture(source=source)
    prepared = fixture.operations().prepare_file("drive-1", "item-1")
    store, ctx = memory_runtime.binding(execution)
    analysis = store.create_run(ctx, request_id=execution.request_id, purpose="conversation_analysis")
    queued = {
        "status": "queued", "analysis_id": analysis["run_id"],
        "progress": {"completed_chunks": 1, "total_chunks": 2},
        "cursor": {"next_chunk": 1}, "results": ["First bounded finding."],
    }
    completed = {
        "status": "completed", "analysis_id": analysis["run_id"],
        "progress": {"completed_chunks": 2, "total_chunks": 2},
        "cursor": None, "results": ["Completed bounded finding."],
    }
    callback = AsyncMock(side_effect=[queued, completed])
    _configure_analysis(memory_runtime, monkeypatch, callback)
    forbidden = Mock(side_effect=AssertionError("The adapter must not load chunks, tokens, or fresh source data."))
    monkeypatch.setattr(retrieval, "_analysis_choice", forbidden)
    monkeypatch.setattr(store, "read_evidence_range", forbidden)
    monkeypatch.setattr(store, "read_manifest", forbidden)
    monkeypatch.setattr(retrieval, "authorize_m365_source", forbidden)
    monkeypatch.setattr(retrieval.M365Transport, "get_token", forbidden)
    monkeypatch.setattr(retrieval.M365Transport, "request_json", forbidden)
    reference = prepared[reference_key]
    plugin = _plugin(source)

    first = asyncio.run(plugin.analyze_file(reference, "Compare the retained numbers."))
    assert first is queued
    assert callback.await_count == 1
    second = asyncio.run(plugin.analyze_file(reference, "Compare the retained numbers.", first["analysis_id"]))
    assert second is completed
    assert callback.await_count == 2
    assert callback.call_args.args == (
        execution, source, f"action-{source}", reference,
        "Compare the retained numbers.", analysis["run_id"],
    )
    assert forbidden.call_count == 0


def test_analyze_awaits_callback_on_the_original_loop(
    execution, memory_runtime, real_content_helpers, monkeypatch,
):
    prepared = ContentGraphFixture(source="spo").operations().prepare_file("drive-1", "item-1")
    loops = []

    async def process(*args):
        loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0)
        return {"status": "queued", "cursor": {"next_chunk": 1}}

    _configure_analysis(memory_runtime, monkeypatch, process)
    async def invoke():
        original = asyncio.get_running_loop()
        result = await _plugin("spo").analyze_file(prepared["evidence_reference"], "Summarize this file.")
        return original, result

    original, result = asyncio.run(invoke())
    assert result["status"] == "queued"
    assert loops == [original]


def test_analyze_propagates_pending_approval_and_skips_model_work(
    execution, memory_runtime, real_content_helpers, monkeypatch,
):
    prepared = ContentGraphFixture().operations().prepare_file("drive-1", "item-1")
    pending = _analysis_required()
    callback = AsyncMock(side_effect=pending)
    _configure_analysis(memory_runtime, monkeypatch, callback)
    with pytest.raises(retrieval.M365ApprovalRequired) as caught:
        asyncio.run(_plugin("onedrive").analyze_file(prepared["memory_id"], "Analyze all rows."))
    assert caught.value is pending
    assert callback.await_count == 1


def test_analyze_preserves_the_parent_fast_answer_decision(
    execution, memory_runtime, real_content_helpers, monkeypatch,
):
    prepared = ContentGraphFixture().operations().prepare_file("drive-1", "item-1")
    fast_answer = {
        "status": "fast_answer", "coverage": {"complete": False},
        "analysis_decision": {"mode": "fast", "approval_id": "declined"},
    }
    callback = AsyncMock(return_value=fast_answer)
    _configure_analysis(memory_runtime, monkeypatch, callback)
    result = asyncio.run(_plugin("onedrive").analyze_file(prepared["memory_id"], "Analyze all rows."))
    assert result is fast_answer
    assert result["status"] == "fast_answer"
    assert result["coverage"]["complete"] is False
    assert callback.await_count == 1


def test_analyze_missing_callback_is_explicitly_unsupported(execution, monkeypatch):
    monkeypatch.setattr(retrieval, "_analysis_callback", None)
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, "Analyze this file."))
    assert result["status"] == "error"
    assert result["provider"] == "conversation_memory"
    assert result["error"]["code"] == "m365_analysis_unavailable"
    assert result["coverage"]["complete"] is False


def test_analyze_requires_retained_conversation_context(execution, monkeypatch):
    callback = AsyncMock()
    monkeypatch.setattr(retrieval, "_analysis_callback", callback)
    monkeypatch.setattr(retrieval, "_memory_resolver", None)
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == "memory_unavailable"
    assert callback.await_count == 0


def test_analyze_is_an_async_kernel_function():
    for plugin_type in (M365OneDrivePlugin, M365SharePointPlugin):
        asynchronous = iscoroutinefunction(plugin_type.analyze_file)
        assert asynchronous
        assert plugin_type.analyze_file.__kernel_function__ is True


def test_analyze_disabled_function_stops_before_memory_or_callback(execution, monkeypatch):
    callback = AsyncMock()
    monkeypatch.setattr(retrieval, "_analysis_callback", callback)
    memory = Mock(side_effect=AssertionError("Disabled capabilities must not read memory."))
    monkeypatch.setattr(retrieval, "_memory_resolver", memory)
    plugin = M365OneDrivePlugin({
        "id": "action-1",
        "additionalFields": {"m365_capabilities": {"analyze_file": False}},
        "m365_capabilities": {"analyze_file": True},
        "enabled_functions": ["analyze_file"],
    })
    result = asyncio.run(plugin.analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == "function_not_enabled"
    assert callback.call_count == memory.call_count == 0


def test_analyze_rechecks_current_capability_on_a_reused_plugin(execution, monkeypatch):
    manifest = {
        "id": "action-1", "type": "m365_onedrive",
        "enabled_functions": ["analyze_file"],
        "additionalFields": {"m365_capabilities": {"analyze_file": True}},
    }
    plugin = M365OneDrivePlugin(deepcopy(manifest))
    context = execution_module.M365ExecutionContext(
        actor_user_id="user-1", data_user_id="user-1", tenant_id="tenant-1",
        conversation_id="conversation-1", request_id="request-1",
        action_configs={"action-1": manifest},
    )
    current = deepcopy(manifest)
    current["additionalFields"]["m365_capabilities"]["analyze_file"] = False
    monkeypatch.setattr(execution_module, "_action_config_resolver", lambda *args: current)
    monkeypatch.setattr(retrieval, "get_m365_context", lambda **kwargs: execution_module.get_m365_execution_context())
    monkeypatch.setattr(retrieval, "authorize_m365_capability", REAL_AUTHORIZE_CAPABILITY)
    callback = AsyncMock()
    monkeypatch.setattr(retrieval, "_analysis_callback", callback)
    with execution_module.m365_execution_context(context):
        result = asyncio.run(plugin.analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == "m365_function_not_authorized"
    assert callback.call_count == 0


@pytest.mark.parametrize("source", ["onedrive", "spo"])
@pytest.mark.parametrize("error,expected", [
    (retrieval.M365PolicyError("m365_source_mismatch", "The retained evidence belongs to another source."), "m365_source_mismatch"),
    (retrieval.M365PolicyError("m365_evidence_not_shared", "Approve publication before shared analysis."), "m365_evidence_not_shared"),
    (MemoryAuthorizationError("The selected capture is not accessible."), "memory_access_denied"),
    (retrieval.M365ProviderError("invalid_analysis_reference", "The analysis belongs to another input."), "invalid_analysis_reference"),
])
def test_analyze_preserves_parent_source_and_access_errors(
    execution, memory_runtime, monkeypatch, source, error, expected,
):
    callback = AsyncMock(side_effect=error)
    _configure_analysis(memory_runtime, monkeypatch, callback)
    result = asyncio.run(_plugin(source).analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == expected
    assert result["source"] == source
    assert result["provider"] == "conversation_memory"
    assert result["coverage"]["complete"] is False
    assert callback.await_count == 1


@pytest.mark.parametrize("field,value", [
    ("principal_id", "different-user"),
    ("conversation_id", "different-conversation"),
    ("tenant_id", "different-tenant"),
])
def test_analyze_requires_a_matching_authorized_memory_context(
    execution, memory_runtime, monkeypatch, field, value,
):
    callback = AsyncMock()
    _configure_analysis(memory_runtime, monkeypatch, callback)
    store, ctx = memory_runtime.binding(execution)
    monkeypatch.setattr(retrieval, "_memory_resolver", lambda context: (store, replace(ctx, **{field: value})))
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == "memory_context_mismatch"
    assert callback.call_count == 0


def test_analyze_published_capture_keeps_the_invoking_principal(
    execution, memory_runtime, real_content_helpers, monkeypatch,
):
    execution.shared = True
    prepared = ContentGraphFixture().operations().prepare_file("drive-1", "item-1")
    execution.actor_user_id = execution.data_user_id = "user-2"
    execution.request_id = "viewer-request"
    callback = AsyncMock(return_value={"status": "queued", "cursor": {"next_chunk": 1}})
    _configure_analysis(memory_runtime, monkeypatch, callback)
    forbidden = Mock(side_effect=AssertionError("Published analysis must not borrow source credentials."))
    monkeypatch.setattr(retrieval, "authorize_m365_source", forbidden)
    monkeypatch.setattr(retrieval.M365Transport, "get_token", forbidden)
    result = asyncio.run(_plugin("onedrive").analyze_file(prepared["evidence_reference"], "Analyze this file."))
    assert result["status"] == "queued"
    assert callback.call_args.args[0] is execution
    assert callback.call_args.args[0].data_user_id == "user-2"
    assert forbidden.call_count == 0


def test_analyze_does_not_publish_owner_private_staging_implicitly(
    execution, memory_runtime, real_content_helpers, monkeypatch,
):
    prepared = ContentGraphFixture().operations().prepare_file("drive-1", "item-1")
    execution.shared = True
    callback = AsyncMock(side_effect=retrieval.M365PolicyError(
        "m365_evidence_not_shared", "Approve publication before shared analysis.",
    ))
    _configure_analysis(memory_runtime, monkeypatch, callback)
    monkeypatch.setattr(memory_runtime.store, "publish", Mock(side_effect=AssertionError("The adapter must not publish source data.")))
    result = asyncio.run(_plugin("onedrive").analyze_file(prepared["memory_id"], "Analyze this file."))
    assert result["error"]["code"] == "m365_evidence_not_shared"
    assert callback.await_count == 1
    store, ctx = memory_runtime.binding(execution)
    manifest = store.read_manifest(ctx, prepared["memory_id"])
    assert manifest["publication"] is None


@pytest.mark.parametrize("question,analysis_id,code", [
    ("", "", "invalid_analysis_question"),
    ("x" * 12001, "", "invalid_analysis_question"),
    ("Analyze.", "not-an-analysis-id", "invalid_analysis_reference"),
])
def test_analyze_preserves_parent_input_validation_errors(
    execution, memory_runtime, monkeypatch, question, analysis_id, code,
):
    callback = AsyncMock(side_effect=retrieval.M365ProviderError(code, "Invalid retained-analysis input."))
    _configure_analysis(memory_runtime, monkeypatch, callback)
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, question, analysis_id))
    assert result["error"]["code"] == code
    assert callback.await_count == 1


def test_analyze_requires_an_async_callback(execution, memory_runtime, monkeypatch):
    callback = Mock(return_value={"status": "completed"})
    _configure_analysis(memory_runtime, monkeypatch, callback)
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == "invalid_analysis_callback"
    assert result["coverage"]["complete"] is False


@pytest.mark.parametrize("callback_result", [None, {}, "completed"])
def test_analyze_rejects_success_shaped_empty_callback_outputs(
    execution, memory_runtime, real_content_helpers, monkeypatch, callback_result,
):
    prepared = ContentGraphFixture().operations().prepare_file("drive-1", "item-1")
    callback = AsyncMock(return_value=callback_result)
    _configure_analysis(memory_runtime, monkeypatch, callback)
    result = asyncio.run(_plugin("onedrive").analyze_file(prepared["memory_id"], "Analyze this file."))
    assert result["error"]["code"] == "invalid_analysis_result"
    assert result["coverage"]["complete"] is False
    assert callback.call_count == 1


def test_invalid_analysis_configuration_does_not_replace_existing_dependencies(
    execution, memory_runtime, monkeypatch,
):
    callback = AsyncMock()
    _configure_analysis(memory_runtime, monkeypatch, callback)
    resolver = retrieval._memory_resolver
    with pytest.raises(TypeError):
        retrieval.configure_m365_retrieval(analysis_callback="not-callable")
    assert retrieval._memory_resolver is resolver
    assert retrieval._analysis_callback is callback


def test_partial_configuration_preserves_bootstrap_callbacks(execution, memory_runtime, monkeypatch):
    callback = AsyncMock(return_value={"status": "queued", "cursor": {"next_chunk": 1}})
    _configure_analysis(memory_runtime, monkeypatch, callback)
    original_memory = retrieval._memory_resolver
    original_request = retrieval._request_run_resolver
    original_counter = retrieval._token_counter
    new_budget = lambda context: 9000

    retrieval.configure_m365_retrieval(model_budget_resolver=new_budget)
    retrieval.configure_m365_retrieval()

    assert retrieval._analysis_callback is callback
    assert retrieval._memory_resolver is original_memory
    assert retrieval._request_run_resolver is original_request
    assert retrieval._token_counter is original_counter
    assert retrieval._model_budget_resolver is new_budget
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, "Analyze this file."))
    assert result["status"] == "queued"
    assert callback.await_count == 1


def test_explicit_none_clears_only_the_selected_callback(execution, memory_runtime, monkeypatch):
    callback = AsyncMock()
    _configure_analysis(memory_runtime, monkeypatch, callback)
    original_memory = retrieval._memory_resolver
    retrieval.configure_m365_retrieval(analysis_callback=None)
    assert retrieval._analysis_callback is None
    assert retrieval._memory_resolver is original_memory
    result = asyncio.run(_plugin("onedrive").analyze_file("0" * 32, "Analyze this file."))
    assert result["error"]["code"] == "m365_analysis_unavailable"
    assert callback.await_count == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
