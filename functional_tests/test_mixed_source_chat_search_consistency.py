#!/usr/bin/env python3
# test_mixed_source_chat_search_consistency.py
"""
Functional test for mixed-source Chat and Search consistency.
Version: 0.260.025
Implemented in: 0.250.064; additive tabular evidence gating updated in 0.260.025

This test ensures Phase 2 of #1057 consumes the Phase 1 #1056 contracts for
standard and streaming Chat plus workflow Search without implementing later
phases from the parent initiative #1055.
"""

import ast
import asyncio
import json
import logging
import os
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTE_PATH = APP_ROOT / "route_backend_chats.py"
WORKFLOW_PATH = APP_ROOT / "functions_workflow_runner.py"
SEARCH_SERVICE_PATH = APP_ROOT / "functions_search_service.py"
CONVERSATIONS_PATH = APP_ROOT / "route_backend_conversations.py"
COLLABORATION_PATH = APP_ROOT / "route_backend_collaboration.py"
FOUNDRY_PATH = APP_ROOT / "foundry_agent_runtime.py"
SETTINGS_PATH = APP_ROOT / "functions_settings.py"
sys.path.insert(0, str(APP_ROOT))

import functions_mixed_source_orchestration as orchestration  # pyright: ignore[reportMissingImports]


def _read(path):
    return path.read_text(encoding="utf-8")


def _load_functions(path, function_names, namespace):
    tree = ast.parse(_read(path), filename=str(path))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in function_names
    ]
    assert {node.name for node in selected_nodes} == set(function_names)
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def _source(document_id, file_name, source_kind, scope="personal", scope_id="user-1"):
    return {
        "document_id": document_id,
        "display_name": file_name,
        "file_name": file_name,
        "extension": os.path.splitext(file_name)[1].lower(),
        "source_kind": source_kind,
        "scope": scope,
        "scope_id": scope_id,
        "group_id": scope_id if scope == "group" else None,
        "public_workspace_id": scope_id if scope == "public" else None,
        "conversation_id": scope_id if scope == "chat" else None,
        "source_version": 1,
        "authorization_status": "authorized",
    }


class FakeInvocation:
    def __init__(self, file_name):
        self.plugin_name = "TabularProcessingPlugin"
        self.function_name = "count_rows"
        self.parameters = {"filename": file_name}
        self.result = json.dumps({"filename": file_name, "count": 42})
        self.duration_ms = 5
        self.timestamp = "2026-07-22T00:00:00Z"
        self.success = True
        self.error_message = None
        self.user_id = "user-1"


class FakePluginLogger:
    def __init__(self):
        self.invocations = []

    def get_invocations_for_conversation(self, user_id, conversation_id, limit=1000):
        del user_id, conversation_id, limit
        return list(self.invocations)


def _load_shared_tabular_executor(failing_file_name=None, emit_tool_invocation=True):
    plugin_logger = FakePluginLogger()
    runner_calls = []

    async def run_tabular_analysis_with_thought_tracking(**kwargs):
        file_name = next(iter(kwargs["tabular_filenames"]))
        runner_calls.append({
            "file_name": file_name,
            "source_hint": kwargs.get("source_hint"),
            "group_id": kwargs.get("group_id"),
            "public_workspace_id": kwargs.get("public_workspace_id"),
        })
        if file_name == failing_file_name:
            raise RuntimeError("deterministic test failure")
        if emit_tool_invocation:
            plugin_logger.invocations.append(FakeInvocation(file_name))
        return f"Computed count for {file_name}: 42", False

    async def no_generated_output(**kwargs):
        del kwargs
        return None

    namespace = {
        "asyncio": asyncio,
        "has_request_context": lambda: False,
        "build_tabular_file_contexts_from_manifest": orchestration.build_tabular_file_contexts_from_manifest,
        "is_tabular_processing_enabled": lambda settings: settings.get("tabular", True),
        "should_run_tabular_evidence": orchestration.should_run_tabular_evidence,
        "get_plugin_logger": lambda: plugin_logger,
        "execute_tabular_evidence_sources": orchestration.execute_tabular_evidence_sources,
        "get_tabular_execution_mode": lambda question: (
            "schema_summary" if "worksheet" in question.lower() else "analysis"
        ),
        "run_tabular_analysis_with_thought_tracking": run_tabular_analysis_with_thought_tracking,
        "get_new_plugin_invocations": lambda invocations, baseline: invocations[baseline:],
        "split_tabular_analysis_invocations": lambda invocations: (list(invocations), []),
        "get_tabular_invocation_error_message": lambda invocation: None,
        "augment_tabular_invocations_with_related_document_evidence": lambda *args, **kwargs: {},
        "build_tabular_related_document_evidence_summary": lambda invocations: "",
        "get_tabular_tool_thought_payloads": lambda invocations: [],
        "get_tabular_status_thought_payloads": lambda invocations, analysis_succeeded: [],
        "maybe_create_tabular_generated_output": no_generated_output,
        "_build_tabular_sk_citations_from_invocations": lambda invocations: [
            {
                "tool_name": "Tabular count",
                "function_name": invocation.function_name,
                "file_name": invocation.parameters["filename"],
            }
            for invocation in invocations
        ],
        "build_tabular_inline_chart_citations": lambda question, invocations: [],
        "build_tabular_computed_results_system_message": lambda label, analysis, **kwargs: analysis,
        "_build_tabular_generated_output_system_message": lambda output: str(output),
        "get_tabular_invocation_compact_payload": lambda invocation, max_rows=5: {
            "file_name": invocation.parameters["filename"],
            "function_name": invocation.function_name,
            "max_rows": max_rows,
        },
    }
    _load_functions(
        ROUTE_PATH,
        {"_execute_mixed_source_tabular_evidence"},
        namespace,
    )
    return namespace["_execute_mixed_source_tabular_evidence"], runner_calls


def test_selected_context_is_equivalent_with_panel_open_or_closed():
    selected_ids = ["narrative-pdf", "table-xlsx"]
    panel_open = orchestration.normalize_document_context_request(
        selection_mode="selected",
        selected_document_ids=selected_ids,
        document_context_requested=True,
        hybrid_search=True,
    )
    panel_closed = orchestration.normalize_document_context_request(
        selection_mode="selected",
        selected_document_ids=selected_ids,
        document_context_requested=True,
        hybrid_search=False,
    )

    for contract in (panel_open, panel_closed):
        assert contract["selection_mode"] == "selected"
        assert contract["selected_document_ids"] == selected_ids
        assert contract["document_context_requested"] is True
        assert contract["explicit_selection"] is True
    assert panel_open["hybrid_search"] is True
    assert panel_closed["hybrid_search"] is False


def test_mixed_format_orders_and_calculation_tools_have_terminal_coverage():
    execute_tabular, runner_calls = _load_shared_tabular_executor()
    pairs = (
        (
            _source("narrative-pdf", "report.pdf", "narrative"),
            _source("table-xlsx", "data.xlsx", "tabular"),
        ),
        (
            _source("narrative-docx", "brief.docx", "narrative"),
            _source("table-csv", "facts.csv", "tabular"),
        ),
    )

    for narrative_source, tabular_source in pairs:
        for manifest in (
            [narrative_source, tabular_source],
            [tabular_source, narrative_source],
        ):
            partitions = orchestration.partition_source_manifest(manifest)
            result = execute_tabular(
                tabular_sources=partitions["tabular_sources"],
                selection_mode="selected",
                has_narrative_sources=True,
                user_question="Calculate the total row count from every selected table.",
                user_id="user-1",
                conversation_id="conversation-1",
                gpt_model="test-model",
                settings={"tabular": True},
            )
            envelopes = result["evidence_envelopes"]
            assert len(envelopes) == 1
            assert envelopes[0]["status"] == "completed"
            assert envelopes[0]["coverage"]["terminal"] is True
            assert envelopes[0]["coverage"]["tool_call_count"] == 1
            assert result["agent_citations"][0]["function_name"] == "count_rows"

    called_files = [call["file_name"] for call in runner_calls]
    assert called_files.count("data.xlsx") == 2
    assert called_files.count("facts.csv") == 2


def test_narrative_only_prompt_skips_rows_and_explicit_failure_is_partial():
    tabular_source = _source("table-xlsx", "data.xlsx", "tabular")
    execute_tabular, runner_calls = _load_shared_tabular_executor()
    skipped = execute_tabular(
        tabular_sources=[tabular_source],
        selection_mode="selected",
        has_narrative_sources=True,
        user_question="What policy does the PDF state?",
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="test-model",
        settings={"tabular": True},
    )
    assert runner_calls == []
    assert skipped["evidence_envelopes"][0]["status"] == "skipped"
    assert skipped["evidence_envelopes"][0]["coverage"]["terminal"] is True

    generic_narrative = execute_tabular(
        tabular_sources=[tabular_source],
        selection_mode="selected",
        has_narrative_sources=True,
        user_question="What does the introduction say?",
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="test-model",
        settings={"tabular": True},
    )
    # Evidence gathering is additive: a generic question no longer suppresses
    # computation of an in-scope tabular source. Only an unambiguous
    # narrative-artifact request (the PDF case above) skips it.
    assert generic_narrative["evidence_envelopes"][0]["status"] != "skipped"

    failing_executor, failure_calls = _load_shared_tabular_executor(
        failing_file_name="broken.csv"
    )
    manifest = [
        _source("narrative-docx", "brief.docx", "narrative"),
        _source("working-csv", "working.csv", "tabular"),
        _source("broken-csv", "broken.csv", "tabular"),
    ]
    tabular_result = failing_executor(
        tabular_sources=orchestration.partition_source_manifest(manifest)["tabular_sources"],
        selection_mode="selected",
        has_narrative_sources=True,
        user_question="Calculate totals for all selected tables.",
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="test-model",
        settings={"tabular": True},
    )
    assert [call["file_name"] for call in failure_calls] == ["working.csv", "broken.csv"]
    assert [envelope["status"] for envelope in tabular_result["evidence_envelopes"]] == [
        "completed",
        "failed",
    ]
    handoff = orchestration.build_mixed_source_evidence_handoff(
        manifest,
        tabular_result["evidence_envelopes"],
        "selected",
    )
    assert handoff["mixed_source_coverage"]["partial_coverage"] is True
    assert handoff["mixed_source_coverage"]["failed_source_count"] == 2

    zero_tool_executor, _ = _load_shared_tabular_executor(
        emit_tool_invocation=False
    )
    zero_tool_result = zero_tool_executor(
        tabular_sources=[tabular_source],
        selection_mode="selected",
        has_narrative_sources=False,
        user_question="Calculate the total.",
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="test-model",
        settings={"tabular": True},
    )
    assert zero_tool_result["evidence_envelopes"][0]["status"] == "failed"
    assert zero_tool_result["evidence_envelopes"][0]["coverage"]["terminal"] is True


def test_personal_group_public_and_chat_tabular_contexts_use_canonical_scope():
    sources = [
        _source("personal-csv", "personal.csv", "tabular"),
        _source("group-xlsx", "group.xlsx", "tabular", "group", "group-1"),
        _source("public-xls", "public.xls", "tabular", "public", "public-1"),
        _source("chat-csv", "chat.csv", "tabular", "chat", "conversation-1"),
    ]
    contexts = orchestration.build_tabular_file_contexts_from_manifest(sources)
    assert [context["source_hint"] for context in contexts] == [
        "workspace",
        "group",
        "public",
        "chat",
    ]
    assert contexts[1]["group_id"] == "group-1"
    assert contexts[2]["public_workspace_id"] == "public-1"
    assert contexts[3]["conversation_id"] == "conversation-1"


def test_relevance_candidate_stage_finds_table_beyond_initial_hits_and_stays_bounded():
    captured_requests = []
    search_results = [
        {
            "document_id": f"narrative-{index}",
            "file_name": f"note-{index}.pdf",
        }
        for index in range(20)
    ] + [
        {
            "document_id": f"table-{index}",
            "file_name": f"table-{index}.xlsx",
        }
        for index in range(10)
    ]

    namespace = {
        "MIXED_SOURCE_TABULAR_CANDIDATE_LIMIT": 6,
        "MIXED_SOURCE_TABULAR_CANDIDATE_TOP_N": 36,
        "MIXED_SOURCE_TABULAR_EXTENSIONS": frozenset({".csv", ".xls", ".xlsx", ".xlsm"}),
        "_coerce_positive_int": lambda value, default, min_value=1, max_value=None: min(
            max(int(value or default), min_value),
            max_value or int(value or default),
        ),
        "search_documents": lambda **kwargs: (
            captured_requests.append(kwargs)
            or {
                "results": search_results,
                "result_count": len(search_results),
                "query": kwargs["query"],
            }
        ),
        "os": os,
        "log_event": lambda *args, **kwargs: None,
        "logging": logging,
    }
    _load_functions(
        SEARCH_SERVICE_PATH,
        {"search_relevant_tabular_candidates"},
        namespace,
    )
    result = namespace["search_relevant_tabular_candidates"](
        query="quarterly revenue",
        user_id="user-1",
        document_ids=["authorized-catalog-hint"],
        max_candidates=99,
    )

    assert captured_requests[0]["top_n"] == 36
    assert captured_requests[0]["document_ids"] == ["authorized-catalog-hint"]
    assert captured_requests[0]["include_all_public_workspaces"] is True
    assert result["document_ids"] == [f"table-{index}" for index in range(6)]
    assert "table-0" not in [item["document_id"] for item in search_results[:12]]


def _load_workflow_search_helpers(flag_enabled, manifest, search_calls, tabular_calls):
    namespace = {
        "DOCUMENT_ACTION_TARGET_MODE_RECENT": "recent",
        "_get_workflow_group_id": lambda workflow: str(workflow.get("group_id") or ""),
        "assert_group_role": lambda *args, **kwargs: None,
        "_is_document_search_workflow": lambda action: action.get("type") == "search",
        "_resolve_recent_document_action_targets": lambda workflow, action, settings: dict(action),
        "normalize_search_id_list": lambda values: list(values or []),
        "is_mixed_source_chat_search_enabled": lambda settings: flag_enabled,
        "normalize_search_top_n": lambda value: int(value),
        "search_documents": lambda **kwargs: (
            search_calls.append(kwargs)
            or {
                "results": [
                    {
                        "document_id": "narrative-doc",
                        "chunk_text": "Narrative evidence",
                        "file_name": "brief.docx",
                        "id": "chunk-1",
                        "page_number": 1,
                    }
                ],
                "result_count": 1,
                "document_count": 1,
                "query": kwargs["query"],
            }
        ),
        "_format_workflow_search_results": lambda results: (
            "Narrative evidence",
            [{"document_id": "narrative-doc", "citation_id": "chunk-1"}],
        ),
        "_apply_runtime_document_action_config": lambda workflow, action: {
            **workflow,
            "document_action": dict(action),
        },
        "resolve_authorized_source_manifest": lambda *args, **kwargs: list(manifest),
        "partition_source_manifest": orchestration.partition_source_manifest,
        "build_failed_narrative_evidence_envelopes": orchestration.build_failed_narrative_evidence_envelopes,
        "build_narrative_evidence_envelopes": orchestration.build_narrative_evidence_envelopes,
        "deduplicate_mixed_source_references": orchestration.deduplicate_mixed_source_references,
        "_workflow_mixed_source_execution_context": lambda *args, **kwargs: nullcontext(),
        "_resolve_tabular_document_action_model_name": lambda workflow, settings: "test-model",
        "build_mixed_source_evidence_handoff": orchestration.build_mixed_source_evidence_handoff,
        "normalize_mixed_source_correlation_id": orchestration.normalize_mixed_source_correlation_id,
        "_create_token_usage_aggregate": lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
        },
        "_accumulate_token_usage_summary": lambda aggregate, usage: aggregate.update({
            key: aggregate.get(key, 0) + int((usage or {}).get(key, 0) or 0)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "request_count")
        }),
        "_finalize_token_usage": lambda aggregate: (
            dict(aggregate) if aggregate.get("request_count") else None
        ),
        "_merge_token_usage_summaries": lambda results: next(
            (
                dict(item.get("token_usage") or {})
                for item in results
                if isinstance(item, dict) and item.get("token_usage")
            ),
            None,
        ),
        "_add_workflow_activity_thought": lambda *args, **kwargs: None,
    }
    _load_functions(
        WORKFLOW_PATH,
        {"_build_workflow_search_prompt", "_prepare_workflow_search_context", "_attach_workflow_search_context"},
        namespace,
    )

    tabular_stub = types.ModuleType("functions_tabular_analysis")

    def execute_mixed_source_tabular_evidence(**kwargs):
        tabular_calls.append(kwargs)
        source = kwargs["tabular_sources"][0]
        return {
            "evidence_envelopes": [orchestration.build_evidence_envelope(
                document_id=source["document_id"],
                source_kind="tabular",
                engine="tabular_tools",
                status="completed",
                summary="Computed total: 42",
                citations=[{"tool_name": "count_rows"}],
                coverage={"terminal": True, "tool_call_count": 1},
            )],
            "system_messages": [{"role": "system", "content": "UNBOUNDED_DUPLICATE"}],
            "agent_citations": [{"tool_name": "count_rows"}],
            "generated_outputs": [{"id": "artifact-1"}],
        }

    tabular_stub.execute_mixed_source_tabular_evidence = execute_mixed_source_tabular_evidence
    return namespace, tabular_stub


def test_workflow_search_uses_mixed_evidence_for_model_and_agent_with_flag_rollback():
    manifest = [
        _source("narrative-doc", "brief.docx", "narrative"),
        _source("table-doc", "facts.csv", "tabular"),
    ]
    search_calls = []
    tabular_calls = []
    namespace, tabular_stub = _load_workflow_search_helpers(
        True,
        manifest,
        search_calls,
        tabular_calls,
    )
    previous_tabular_module = sys.modules.get("functions_tabular_analysis")
    sys.modules["functions_tabular_analysis"] = tabular_stub
    try:
        context = namespace["_prepare_workflow_search_context"](
            {
                "user_id": "user-1",
                "task_prompt": "Calculate totals and summarize the brief.",
                "runner_type": "model",
            },
            {
                "type": "search",
                "target_mode": "selected",
                "document_ids": ["narrative-doc", "table-doc"],
                "doc_scope": "all",
            },
            {"enable_mixed_source_chat_search": True},
            conversation_id="conversation-1",
        )
    finally:
        if previous_tabular_module is None:
            sys.modules.pop("functions_tabular_analysis", None)
        else:
            sys.modules["functions_tabular_analysis"] = previous_tabular_module

    assert search_calls[0]["document_ids"] == ["narrative-doc"]
    assert search_calls[0]["include_all_public_workspaces"] is True
    assert [source["document_id"] for source in tabular_calls[0]["tabular_sources"]] == [
        "table-doc"
    ]
    assert "Computed total: 42" in context["workflow"]["task_prompt"]
    assert "UNBOUNDED_DUPLICATE" not in context["workflow"]["task_prompt"]
    assert context["coverage"]["partial_coverage"] is False

    attach = namespace["_attach_workflow_search_context"]
    model_result = attach({"reply": "model", "provider": "model"}, context)
    agent_result = attach(
        {
            "reply": "agent",
            "provider": "agent",
            "agent_citations": [{"tool_name": "agent_tool"}],
        },
        context,
    )
    assert model_result["agent_citations"] == [{"tool_name": "count_rows"}]
    assert agent_result["agent_citations"] == [
        {"tool_name": "agent_tool"},
        {"tool_name": "count_rows"},
    ]
    assert model_result["generated_tabular_outputs"] == [{"id": "artifact-1"}]
    assert agent_result["document_search"]["document_count"] == 2

    legacy_search_calls = []
    legacy_tabular_calls = []
    legacy_namespace, legacy_stub = _load_workflow_search_helpers(
        False,
        manifest,
        legacy_search_calls,
        legacy_tabular_calls,
    )
    previous_tabular_module = sys.modules.get("functions_tabular_analysis")
    sys.modules["functions_tabular_analysis"] = legacy_stub
    try:
        legacy_context = legacy_namespace["_prepare_workflow_search_context"](
            {"user_id": "user-1", "task_prompt": "legacy", "runner_type": "model"},
            {
                "type": "search",
                "target_mode": "selected",
                "document_ids": ["narrative-doc", "table-doc"],
                "doc_scope": "all",
            },
            {"enable_mixed_source_chat_search": False},
            conversation_id="conversation-1",
        )
    finally:
        if previous_tabular_module is None:
            sys.modules.pop("functions_tabular_analysis", None)
        else:
            sys.modules["functions_tabular_analysis"] = previous_tabular_module
    assert legacy_search_calls[0]["document_ids"] == ["narrative-doc", "table-doc"]
    assert legacy_tabular_calls == []
    assert legacy_context["coverage"] == {}


def test_group_workflow_search_forces_stored_group_scope():
    group_manifest = [
        _source("group-narrative", "brief.docx", "narrative", "group", "group-safe"),
        _source("group-table", "facts.csv", "tabular", "group", "group-safe"),
    ]
    search_calls = []
    tabular_calls = []
    namespace, tabular_stub = _load_workflow_search_helpers(
        True,
        group_manifest,
        search_calls,
        tabular_calls,
    )
    manifest_calls = []
    role_calls = []
    namespace["resolve_authorized_source_manifest"] = lambda *args, **kwargs: (
        manifest_calls.append((args, kwargs)) or list(group_manifest)
    )
    namespace["assert_group_role"] = lambda *args, **kwargs: role_calls.append(
        (args, kwargs)
    )

    previous_tabular_module = sys.modules.get("functions_tabular_analysis")
    sys.modules["functions_tabular_analysis"] = tabular_stub
    try:
        context = namespace["_prepare_workflow_search_context"](
            {
                "user_id": "user-1",
                "group_id": "group-safe",
                "task_prompt": "Calculate totals and summarize the brief.",
                "runner_type": "model",
            },
            {
                "type": "search",
                "target_mode": "selected",
                "document_ids": ["group-narrative", "group-table"],
                "doc_scope": "personal",
                "active_group_ids": ["group-attacker"],
                "active_public_workspace_id": ["public-attacker"],
            },
            {"enable_mixed_source_chat_search": True},
            conversation_id="conversation-1",
        )
    finally:
        if previous_tabular_module is None:
            sys.modules.pop("functions_tabular_analysis", None)
        else:
            sys.modules["functions_tabular_analysis"] = previous_tabular_module

    assert role_calls[0][0][:2] == ("user-1", "group-safe")
    manifest_kwargs = manifest_calls[0][1]
    assert manifest_kwargs["doc_scope"] == "group"
    assert manifest_kwargs["active_group_ids"] == ["group-safe"]
    assert manifest_kwargs["active_public_workspace_ids"] == []
    prepared_action = context["workflow"]["document_action"]
    assert prepared_action["doc_scope"] == "group"
    assert prepared_action["active_group_ids"] == ["group-safe"]
    assert prepared_action["active_public_workspace_id"] == []


def test_workflow_search_narrative_failure_keeps_available_table_evidence():
    """A failed narrative cohort remains terminal while the table branch still answers."""
    manifest = [
        _source("narrative-doc", "brief.docx", "narrative"),
        _source("table-doc", "facts.csv", "tabular"),
    ]
    search_calls = []
    tabular_calls = []
    namespace, tabular_stub = _load_workflow_search_helpers(
        True,
        manifest,
        search_calls,
        tabular_calls,
    )

    def fail_narrative_search(**kwargs):
        search_calls.append(kwargs)
        raise RuntimeError("bounded narrative failure")

    namespace["search_documents"] = fail_narrative_search
    previous_tabular_module = sys.modules.get("functions_tabular_analysis")
    sys.modules["functions_tabular_analysis"] = tabular_stub
    try:
        context = namespace["_prepare_workflow_search_context"](
            {
                "user_id": "user-1",
                "task_prompt": "Calculate totals and summarize the brief.",
                "runner_type": "model",
            },
            {
                "type": "search",
                "target_mode": "selected",
                "document_ids": ["narrative-doc", "table-doc"],
                "doc_scope": "all",
            },
            {"enable_mixed_source_chat_search": True},
            conversation_id="conversation-1",
        )
    finally:
        if previous_tabular_module is None:
            sys.modules.pop("functions_tabular_analysis", None)
        else:
            sys.modules["functions_tabular_analysis"] = previous_tabular_module

    assert len(search_calls) == 1
    assert len(tabular_calls) == 1
    assert "Computed total: 42" in context["workflow"]["task_prompt"]
    assert context["coverage"]["partial_coverage"] is True
    statuses = {
        entry["document_id"]: entry["status"]
        for entry in context["coverage"]["terminal_ledger"]
    }
    assert statuses == {
        "narrative-doc": "failed",
        "table-doc": "completed",
    }


def test_replay_collaboration_foundry_and_chat_path_contracts():
    replay_namespace = {}
    _load_functions(
        CONVERSATIONS_PATH,
        {"_build_replayed_document_context"},
        replay_namespace,
    )
    replay = replay_namespace["_build_replayed_document_context"]({
        "workspace_search": {
            "search_enabled": True,
            "selection_mode": "selected",
            "document_context_requested": True,
            "hybrid_search_preference": False,
            "requested_document_ids": ["doc-1", "temporarily-unavailable"],
            "selected_document_ids": ["doc-1", "doc-2"],
            "document_scope": "all",
            "active_group_ids": ["group-1"],
        }
    })
    assert replay["hybrid_search"] is False
    assert replay["selection_mode"] == "selected"
    assert replay["document_context_requested"] is True
    assert replay["selected_document_ids"] == ["doc-1", "temporarily-unavailable"]

    collaboration_namespace = {}
    _load_functions(
        COLLABORATION_PATH,
        {"_build_collaboration_stream_request_payload"},
        collaboration_namespace,
    )
    forwarded = collaboration_namespace["_build_collaboration_stream_request_payload"](
        {
            "hybrid_search": False,
            "selection_mode": "selected",
            "document_context_requested": True,
            "selected_document_ids": ["doc-1"],
        },
        "conversation-1",
        "Question",
    )
    assert forwarded["selection_mode"] == "selected"
    assert forwarded["document_context_requested"] is True
    assert forwarded["selected_document_ids"] == ["doc-1"]

    chat_source = _read(ROUTE_PATH)
    template_source = _read(APP_ROOT / "templates" / "chats.html")
    frontend_source = _read(APP_ROOT / "static" / "js" / "chat" / "chat-messages.js")
    assert "'active_group_ids': effective_active_group_ids" in chat_source
    assert "'active_public_workspace_ids': effective_active_public_workspace_ids" in chat_source
    assert "'requested_document_ids': requested_selected_document_ids" in chat_source
    assert "enable_mixed_source_chat_search:" in template_source
    assert "workspaceContextInvocationRequested" in frontend_source
    assert "messageData.hybrid_search" in frontend_source
    assert "window.appSettings?.enable_mixed_source_chat_search" in frontend_source

    foundry_tree = ast.parse(_read(FOUNDRY_PATH), filename=str(FOUNDRY_PATH))
    internal_keys = next(
        ast.literal_eval(node.value)
        for node in foundry_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "FOUNDRY_INTERNAL_METADATA_KEYS"
            for target in node.targets
        )
    )
    assert {
        "selected_document_ids",
        "selection_mode",
        "document_context_requested",
    }.issubset(internal_keys)

    route_source = chat_source
    assert route_source.count("_normalize_chat_document_context_contract(") == 3
    assert route_source.count("_execute_mixed_source_tabular_evidence(") == 3
    assert route_source.count("build_mixed_source_evidence_handoff(") == 2
    assert route_source.count("and not mixed_source_explicit_selection") >= 4
    assert route_source.count("'selected_document_id': effective_selected_document_id") >= 2
    assert route_source.count("'document_scope': effective_document_scope") >= 2
    assert "if hybrid_search_enabled or history_grounded_search_used" not in route_source


def test_flag_defaults_off_and_diagnostics_are_privacy_safe():
    settings_source = _read(SETTINGS_PATH)
    assert "'enable_mixed_source_chat_search': False" in settings_source
    assert "'enable_mixed_source_relevance_candidates': False" in settings_source
    assert "enable_mixed_source_manifest" not in _read(ROUTE_PATH)[
        _read(ROUTE_PATH).find("def _normalize_chat_document_context_contract"):
        _read(ROUTE_PATH).find("def _resolve_chat_mixed_source_manifest")
    ]

    captured_events = []
    original_log_event = orchestration.log_event
    orchestration.log_event = lambda message, **kwargs: captured_events.append(
        {"message": message, **kwargs}
    )
    try:
        orchestration.execute_tabular_evidence_sources(
            [_source("sensitive-document-id", "sensitive-name.csv", "tabular")],
            lambda source: {"summary": "bounded result"},
            "selected",
        )
    finally:
        orchestration.log_event = original_log_event

    serialized_events = json.dumps(captured_events, sort_keys=True)
    assert "sensitive-document-id" not in serialized_events
    assert "sensitive-name.csv" not in serialized_events
    assert "bounded result" not in serialized_events


def test_relevance_table_rollout_is_independently_gated():
    route_source = _read(ROUTE_PATH)
    settings_source = _read(SETTINGS_PATH)
    assert "def is_mixed_source_relevance_candidates_enabled" in settings_source
    assert "if relevance_candidates_enabled:" in route_source
    assert "candidate_result = search_relevant_tabular_candidates(" in route_source


def test_foundry_context_opt_out_and_compacted_handoff_are_safe():
    foundry_namespace = {
        "List": List,
        "Optional": Optional,
        "ChatMessageContent": object,
        "FoundryAgentInvocationError": RuntimeError,
        "_extract_message_text": lambda message: str(message),
    }
    _load_functions(
        FOUNDRY_PATH,
        {"_looks_like_document_context_message", "_build_foundry_workflow_input_text"},
        foundry_namespace,
    )
    build_input = foundry_namespace["_build_foundry_workflow_input_text"]
    pure_evidence = (
        "Use the mixed-source evidence handoff below.\n"
        '{"evidence_envelopes":[{"summary":"secret evidence"}]}'
    )
    workflow_prompt = (
        "[Workflow document search context]\n"
        f"{pure_evidence}\n\n"
        "[Workflow task]\nWrite the user-facing answer."
    )
    assert "secret evidence" not in build_input(
        [pure_evidence, "Current user question"],
        include_document_context=False,
    )
    packed_workflow = build_input(
        [workflow_prompt],
        include_document_context=False,
    )
    assert "secret evidence" not in packed_workflow
    assert "Write the user-facing answer." in packed_workflow

    file_input_namespace = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "_coerce_bool": lambda value, default=True: bool(value),
    }
    _load_functions(
        FOUNDRY_PATH,
        {"_collect_foundry_response_file_inputs"},
        file_input_namespace,
    )
    assert file_input_namespace["_collect_foundry_response_file_inputs"](
        {"include_document_context": False, "include_file_inputs": True},
        {"selected_document_ids": ["sensitive-document"]},
    ) == ([], [])

    manifest = []
    envelopes = []
    for source_index in range(12):
        document_id = f"table-{source_index}"
        manifest.append(_source(document_id, f"table-{source_index}.csv", "tabular"))
        envelopes.append(orchestration.build_evidence_envelope(
            document_id=document_id,
            source_kind="tabular",
            engine="tabular_tools",
            status="completed",
            summary="s" * 4000,
            evidence=[{"rows": "x" * 1500} for _ in range(10)],
            citations=[{"tool": "count_rows", "payload": "y" * 1000}],
            coverage={"terminal": True, "tool_call_count": 1},
        ))
    handoff = orchestration.build_mixed_source_evidence_handoff(
        manifest,
        envelopes,
        "selected",
    )
    assert handoff["mixed_source_coverage"]["handoff_compacted"] is True
    assert handoff["mixed_source_coverage"]["partial_coverage"] is True
    assert handoff["mixed_source_coverage"]["evidence_compacted_count"] == 12

    plugin_source = _read(
        APP_ROOT / "semantic_kernel_plugins" / "tabular_processing_plugin.py"
    )
    assert "authorized_blob_locations" in plugin_source
    assert "exact_authorized_locations" in plugin_source
