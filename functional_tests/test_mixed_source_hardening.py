#!/usr/bin/env python3
# test_mixed_source_hardening.py
"""
Functional tests for mixed-source hardening, extraction, and rollout.
Version: 0.250.167
Implemented in: 0.250.070; direct-run telemetry isolation updated in 0.250.160; aggregate tabular parity harness coverage updated in 0.250.166

This test ensures Phase 6 of #1061 preserves the bounded Phase 1-5 evidence
contracts from #1056, #1057, #1058, #1059, and #1060 under parent #1055.
"""

import sys
import ast
import importlib.util
import time
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
COMPARISON_PATH = APP_ROOT / "functions_document_comparison.py"
sys.path.insert(0, str(APP_ROOT))

import functions_mixed_source_orchestration as orchestration  # pyright: ignore[reportMissingImports]
from functions_tabular_analysis import get_new_plugin_invocations  # pyright: ignore[reportMissingImports]


def _load_evidence_comparison():
    source = COMPARISON_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(COMPARISON_PATH))
    names = {
        "_build_pairwise_comparison_prompt",
        "_build_comparison_reduction_prompt",
        "run_evidence_document_comparison",
    }
    module = ast.Module(
        body=[
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {
        "MixedSourceCancellationError": orchestration.MixedSourceCancellationError,
        "raise_if_mixed_source_cancelled": orchestration.raise_if_mixed_source_cancelled,
    }
    exec(compile(module, str(COMPARISON_PATH), "exec"), namespace)
    return namespace["run_evidence_document_comparison"]


def _load_route_helpers(function_names, namespace=None):
    route_path = APP_ROOT / "route_backend_chats.py"
    source = route_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(route_path))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in set(function_names)
    ]
    assert {node.name for node in selected_nodes} == set(function_names)
    loaded_namespace = dict(namespace or {})
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(route_path), "exec"),
        loaded_namespace,
    )
    return loaded_namespace


def _load_document_action_contract():
    action_path = APP_ROOT / "functions_document_actions.py"
    source = action_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(action_path))
    function_names = {
        "normalize_document_action_type",
        "normalize_document_action_analysis_mode",
        "normalize_document_action_target_mode",
        "normalize_recent_document_window_minutes",
        "_resolve_max_documents",
        "_build_document_action_disabled_message",
        "normalize_document_action_config",
    }
    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    namespace = {
        "DOCUMENT_ACTION_TYPE_NONE": "none",
        "DOCUMENT_ACTION_TYPE_SEARCH": "search",
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "DOCUMENT_ACTION_TYPE_COMPARISON": "comparison",
        "DOCUMENT_ACTION_ANALYSIS_MODE_COMBINED": "combined",
        "DOCUMENT_ACTION_ANALYSIS_MODE_PER_DOCUMENT": "per_document",
        "DOCUMENT_ACTION_TARGET_MODE_ALL": "all",
        "DOCUMENT_ACTION_TARGET_MODE_SELECTED": "selected",
        "DOCUMENT_ACTION_TARGET_MODE_RECENT": "recent",
        "DEFAULT_RECENT_DOCUMENT_WINDOW_MINUTES": 10,
        "VALID_DOCUMENT_ACTION_ANALYSIS_MODES": {"combined", "per_document"},
        "VALID_DOCUMENT_ACTION_TARGET_MODES": {"all", "selected", "recent"},
        "VALID_DOCUMENT_ACTION_TYPES": {"none", "search", "analyze", "comparison"},
        "normalize_search_id_list": lambda values: [
            str(value).strip()
            for value in list(values or [])
            if str(value or "").strip()
        ],
        "normalize_document_analysis_targets": lambda **kwargs: {
            "document_ids": list(kwargs.get("document_ids") or []),
            "doc_scope": kwargs.get("doc_scope") or "all",
            "active_group_ids": list(kwargs.get("active_group_ids") or []),
            "active_public_workspace_id": list(kwargs.get("active_public_workspace_id") or []),
            "window_unit": kwargs.get("window_unit") or "pages",
            "window_size": kwargs.get("window_size"),
            "window_percent": kwargs.get("window_percent"),
            "max_retries_per_window": kwargs.get("max_retries_per_window", 1),
        },
    }
    exec(
        compile(ast.Module(body=function_nodes, type_ignores=[]), str(action_path), "exec"),
        namespace,
    )
    return namespace


def _load_document_analysis_module():
    analysis_path = APP_ROOT / "functions_document_analysis.py"
    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None
    debug_stub = types.ModuleType("functions_debug")
    debug_stub.debug_print = lambda *args, **kwargs: None
    search_stub = types.ModuleType("functions_search")
    search_stub.normalize_search_id_list = lambda values: [
        str(value).strip()
        for value in list(values or [])
        if str(value or "").strip()
    ]
    search_stub.normalize_search_scope = lambda value: (
        str(value or "all").strip().lower()
        if str(value or "all").strip().lower() in {"all", "personal", "group", "public"}
        else "all"
    )
    replacements = {
        "functions_appinsights": appinsights_stub,
        "functions_debug": debug_stub,
        "functions_search": search_stub,
    }
    originals = {name: sys.modules.get(name) for name in replacements}
    sys.modules.update(replacements)
    try:
        spec = importlib.util.spec_from_file_location(
            "phase6_document_analysis",
            analysis_path,
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def test_handoff_exposes_the_same_bounded_envelopes_used_for_synthesis():
    """Analyze and Compare receive the compacted envelopes represented in the prompt."""
    manifest = [{
        "document_id": "table-1",
        "display_name": "table.csv",
        "source_kind": orchestration.SOURCE_KIND_TABULAR,
        "scope": orchestration.SOURCE_SCOPE_PERSONAL,
        "scope_id": "user-1",
        "source_version": 3,
        "authorization_status": orchestration.AUTHORIZATION_STATUS_AUTHORIZED,
    }]
    envelope = orchestration.build_evidence_envelope(
        document_id="table-1",
        source_kind=orchestration.SOURCE_KIND_TABULAR,
        engine=orchestration.EVIDENCE_ENGINE_TABULAR_TOOLS,
        status=orchestration.EVIDENCE_STATUS_COMPLETED,
        summary="Computed row count: 42.",
        coverage={"terminal": True, "tool_call_count": 1},
    )

    handoff = orchestration.build_mixed_source_evidence_handoff(
        manifest,
        [envelope],
        orchestration.SELECTION_MODE_SELECTED,
    )

    assert handoff["evidence_envelopes"] == [envelope]
    assert handoff["mixed_source_coverage"]["completed_source_count"] == 1


def test_terminal_ledger_preserves_canonical_identity_and_rejects_stale_evidence():
    """Duplicate names stay distinct while duplicate or unrelated evidence cannot reach synthesis."""
    manifest = [
        {
            "document_id": "personal-table",
            "display_name": "duplicate.csv",
            "source_kind": orchestration.SOURCE_KIND_TABULAR,
            "scope": orchestration.SOURCE_SCOPE_PERSONAL,
            "scope_id": "user-1",
            "source_version": "v1",
            "authorization_status": orchestration.AUTHORIZATION_STATUS_AUTHORIZED,
        },
        {
            "document_id": "group-table",
            "display_name": "duplicate.csv",
            "source_kind": orchestration.SOURCE_KIND_TABULAR,
            "scope": orchestration.SOURCE_SCOPE_GROUP,
            "scope_id": "group-1",
            "source_version": "v2",
            "authorization_status": orchestration.AUTHORIZATION_STATUS_AUTHORIZED,
        },
    ]

    def completed(document_id):
        return orchestration.build_evidence_envelope(
            document_id=document_id,
            source_kind=orchestration.SOURCE_KIND_TABULAR,
            engine=orchestration.EVIDENCE_ENGINE_TABULAR_TOOLS,
            status=orchestration.EVIDENCE_STATUS_COMPLETED,
            summary="Computed result.",
            coverage={"terminal": True, "tool_call_count": 1},
        )

    ledger = orchestration.build_terminal_coverage_ledger(
        manifest,
        [
            completed("group-table"),
            completed("personal-table"),
            completed("personal-table"),
            completed("unrelated-table"),
        ],
    )

    assert [entry["document_id"] for entry in ledger["entries"]] == [
        "personal-table",
        "group-table",
    ]
    assert [entry["scope"] for entry in ledger["entries"]] == ["personal", "group"]
    assert [entry["source_version"] for entry in ledger["entries"]] == ["v1", "v2"]
    assert [entry["request_order"] for entry in ledger["entries"]] == [0, 1]
    assert ledger["entries"][0]["status"] == orchestration.EVIDENCE_STATUS_FAILED
    assert ledger["entries"][0]["reason"] == "duplicate_terminal_evidence"
    assert [item["document_id"] for item in ledger["evidence_envelopes"]] == ["group-table"]
    assert ledger["duplicate_evidence_count"] == 1
    assert ledger["unexpected_evidence_count"] == 1
    assert ledger["partial_coverage"] is True


def test_mode_failure_policy_requires_success_and_a_prepared_compare_source():
    """Analyze needs one successful source; Compare needs both Source and a valid Target."""
    all_failed = {
        "entries": [
            {"role": "selected", "status": orchestration.EVIDENCE_STATUS_FAILED},
            {"role": "selected", "status": orchestration.EVIDENCE_STATUS_SKIPPED},
        ],
        "partial_coverage": True,
    }
    analyze_outcome = orchestration.evaluate_mixed_source_mode_outcome(
        "analyze",
        all_failed,
    )
    assert analyze_outcome["status"] == orchestration.EVIDENCE_STATUS_FAILED
    assert analyze_outcome["should_reduce"] is False

    failed_source = {
        "entries": [
            {"role": "left", "status": orchestration.EVIDENCE_STATUS_FAILED},
            {"role": "right", "status": orchestration.EVIDENCE_STATUS_COMPLETED},
        ],
        "partial_coverage": True,
    }
    compare_outcome = orchestration.evaluate_mixed_source_mode_outcome(
        "compare",
        failed_source,
    )
    assert compare_outcome["status"] == orchestration.EVIDENCE_STATUS_FAILED
    assert compare_outcome["should_reduce"] is False
    assert compare_outcome["reason"] == "source_preparation_failed"

    partial_targets = {
        "entries": [
            {"role": "left", "status": orchestration.EVIDENCE_STATUS_COMPLETED},
            {"role": "right", "status": orchestration.EVIDENCE_STATUS_FAILED},
            {"role": "right", "status": orchestration.EVIDENCE_STATUS_COMPLETED},
        ],
        "partial_coverage": True,
    }
    partial_outcome = orchestration.evaluate_mixed_source_mode_outcome(
        "compare",
        partial_targets,
    )
    assert partial_outcome["status"] == orchestration.EVIDENCE_STATUS_PARTIAL
    assert partial_outcome["should_reduce"] is True


def test_compare_failed_source_is_fatal_and_failed_target_does_not_stop_later_targets():
    """Compare rejects an unavailable Source and keeps a failed Target visible."""
    compare = _load_evidence_comparison()
    prompt_calls = []

    def invoke_prompt(prompt, stage="", metadata=None):
        del prompt
        prompt_calls.append((stage, dict(metadata or {})))
        if (metadata or {}).get("right_document_id") == "target-failed":
            raise RuntimeError("bounded target failure")
        return "Compared available evidence."

    try:
        compare(
            "Compare the sources.",
            {
                "document_id": "source",
                "document_name": "Source.csv",
                "status": "failed",
                "summary": "Failure boilerplate must not be evidence.",
            },
            [{"document_id": "target", "status": "completed", "summary": "Ready."}],
            invoke_prompt,
        )
    except RuntimeError as exc:
        assert "Source" in str(exc)
    else:
        raise AssertionError("A failed Compare Source must fail the operation")

    result = compare(
        "Compare the sources.",
        {
            "document_id": "source",
            "document_name": "Source.csv",
            "source_kind": "tabular",
            "engine": "tabular_tools",
            "status": "completed",
            "summary": "Computed source evidence.",
        },
        [
            {
                "document_id": "target-failed",
                "document_name": "Failed.pdf",
                "source_kind": "narrative",
                "engine": "document_analysis",
                "status": "completed",
                "summary": "Prepared, but pairwise reduction fails.",
            },
            {
                "document_id": "target-valid",
                "document_name": "Valid.pdf",
                "source_kind": "narrative",
                "engine": "document_analysis",
                "status": "completed",
                "summary": "Prepared target evidence.",
            },
        ],
        invoke_prompt,
    )

    assert [item["right_document_id"] for item in result["comparison_items"]] == [
        "target-valid"
    ]
    assert result["coverage"]["failed_targets"] == ["Failed.pdf"]
    assert "Failed or partial targets: 1" in result["analysis_reply"]


def test_tabular_invocation_slicing_is_extracted_without_route_runtime_import():
    """The reusable helper preserves retry slices without loading the Chat route."""
    route_was_loaded = "route_backend_chats" in sys.modules
    invocations = [object(), object(), object()]

    assert get_new_plugin_invocations([], 0) == []
    copied = get_new_plugin_invocations(invocations, 0)
    assert copied == invocations
    assert copied is not invocations
    assert get_new_plugin_invocations(invocations, 1) == invocations[1:]
    assert get_new_plugin_invocations(invocations, len(invocations)) == []
    assert get_new_plugin_invocations(invocations, len(invocations) + 1) == []
    assert ("route_backend_chats" in sys.modules) is route_was_loaded

    tabular_source = (APP_ROOT / "functions_tabular_analysis.py").read_text(encoding="utf-8")
    route_source = (APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8")
    function_source = ast.get_source_segment(
        tabular_source,
        next(
            node
            for node in ast.parse(tabular_source).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_new_plugin_invocations"
        ),
    ) or ""
    assert "_load_chat_helper" not in function_source
    assert "return _shared_get_new_plugin_invocations" in route_source


def test_manifest_and_tabular_cancellation_stop_work_without_failure_downgrade():
    """Cancellation remains a lifecycle signal and never becomes a failed envelope."""
    resolver_calls = []

    def cancel_manifest():
        return True

    try:
        orchestration.resolve_authorized_source_manifest(
            ["source-1"],
            user_id="user-1",
            context_resolver=lambda **kwargs: resolver_calls.append(kwargs),
            cancel_requested=cancel_manifest,
            request_correlation_id="1de45079-f43e-4de5-a2c7-1794f23d9ea4",
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "manifest"
    else:
        raise AssertionError("Manifest cancellation must abort resolution")
    assert resolver_calls == []

    source = {
        "document_id": "table-1",
        "source_kind": orchestration.SOURCE_KIND_TABULAR,
    }
    execute_calls = []
    cancel_checks = iter([False, True])

    try:
        orchestration.execute_tabular_evidence_sources(
            [source],
            lambda item: execute_calls.append(item) or {"summary": "Computed."},
            orchestration.SELECTION_MODE_SELECTED,
            cancel_requested=lambda: next(cancel_checks),
            request_correlation_id="1de45079-f43e-4de5-a2c7-1794f23d9ea4",
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "tabular"
    else:
        raise AssertionError("Tabular cancellation must abort without a failed envelope")
    assert execute_calls == [source]


def test_narrative_comparison_and_reduction_cancellation_stop_later_work():
    """Cancellation after blocking calls prevents retries, later pairs, and final reductions."""
    analysis = _load_document_analysis_module()
    windows = [
        {
            "window_number": index,
            "window_unit": "pages",
            "start_page": index,
            "end_page": index,
            "start_chunk_sequence": index,
            "end_chunk_sequence": index,
            "page_count": 1,
            "chunk_count": 1,
            "chunks": [{
                "chunk_text": f"Window {index}",
                "page_number": index,
                "chunk_sequence": index,
            }],
        }
        for index in (1, 2)
    ]
    analysis._get_search_service_helpers = lambda: (
        lambda chunks, **kwargs: list(windows),
        lambda **kwargs: {
            "document": {
                "id": "narrative-1",
                "file_name": "brief.pdf",
                "title": "Brief",
            },
            "chunks": [chunk for window in windows for chunk in window["chunks"]],
            "chunk_count": 2,
            "scope": "personal",
            "scope_id": "user-1",
        },
    )
    narrative_state = {"cancelled": False}
    narrative_calls = []
    narrative_events = []

    def invoke_narrative(prompt, **kwargs):
        del prompt
        narrative_calls.append(kwargs)
        narrative_state["cancelled"] = True
        return "First window result."

    try:
        analysis.run_document_analysis(
            user_id="user-1",
            analysis_prompt="Review every window.",
            document_ids=["narrative-1"],
            invoke_prompt=invoke_narrative,
            activity_callback=narrative_events.append,
            cancel_requested=lambda: narrative_state["cancelled"],
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "narrative"
    else:
        raise AssertionError("Narrative cancellation must abort after the active model call")
    assert len(narrative_calls) == 1
    assert all(event.get("type") != "window_completed" for event in narrative_events)
    assert all(not str(event.get("type") or "").startswith("reduction") for event in narrative_events)

    compare = _load_evidence_comparison()
    comparison_state = {"cancelled": False}
    comparison_calls = []

    def invoke_comparison(prompt, stage="", metadata=None):
        del prompt
        comparison_calls.append((stage, dict(metadata or {})))
        comparison_state["cancelled"] = True
        return "Pair result."

    try:
        compare(
            "Compare.",
            {"document_id": "source", "status": "completed", "summary": "Source."},
            [
                {"document_id": "target-1", "status": "completed", "summary": "One."},
                {"document_id": "target-2", "status": "completed", "summary": "Two."},
            ],
            invoke_comparison,
            cancel_requested=lambda: comparison_state["cancelled"],
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "comparison"
    else:
        raise AssertionError("Comparison cancellation must stop later Targets")
    assert [call[1].get("right_document_id") for call in comparison_calls] == ["target-1"]

    reduction_state = {"armed": False, "post_pair_grace": False}
    reduction_calls = []

    def reduction_cancel_requested():
        if not reduction_state["armed"]:
            return False
        if reduction_state["post_pair_grace"]:
            reduction_state["post_pair_grace"] = False
            return False
        return True

    def invoke_before_reduction(prompt, stage="", metadata=None):
        del prompt
        reduction_calls.append((stage, dict(metadata or {})))
        if (metadata or {}).get("right_document_id") == "target-2":
            reduction_state["armed"] = True
            reduction_state["post_pair_grace"] = True
        return "Pair result."

    try:
        compare(
            "Compare.",
            {"document_id": "source", "status": "completed", "summary": "Source."},
            [
                {"document_id": "target-1", "status": "completed", "summary": "One."},
                {"document_id": "target-2", "status": "completed", "summary": "Two."},
            ],
            invoke_before_reduction,
            cancel_requested=reduction_cancel_requested,
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "comparison_reduction"
    else:
        raise AssertionError("Cancellation before reduction must suppress the reduction call")
    assert [stage for stage, _ in reduction_calls] == ["comparison", "comparison"]


def test_export_cancellation_rolls_back_queued_and_uploaded_artifacts():
    """Cancellation after queue/upload uses existing cancellation or exact artifact rollback."""
    queued_runs = []
    canceled_runs = []
    deleted_artifacts = []
    uploaded_artifacts = []

    def load_export_helpers(queue_background):
        return _load_route_helpers(
            {"_has_generated_tabular_csv_output", "maybe_create_generated_file_output"},
            namespace={
                "MixedSourceCancellationError": orchestration.MixedSourceCancellationError,
                "raise_if_mixed_source_cancelled": orchestration.raise_if_mixed_source_cancelled,
                "has_generated_tabular_csv_output": lambda outputs: False,
                "get_requested_generated_file_format": lambda question: "csv",
                "has_generated_file_output": lambda outputs, output_format: False,
                "build_generated_file_export": lambda *args, **kwargs: {
                    "capability": "file_export",
                    "file_name": "answer.csv",
                    "file_content": "name,value\nalpha,1\n",
                    "output_format": "csv",
                    "row_count": 1,
                    "summary": "One row.",
                    "_structured_rows": [{"name": "alpha", "value": 1}],
                },
                "build_generated_file_artifact_metadata": lambda export_payload, upload_result, conversation_id: {
                    "artifact_message_id": upload_result["message"]["id"],
                    "conversation_id": conversation_id,
                    "file_name": upload_result["message"]["file_name"],
                    "output_format": export_payload["output_format"],
                },
                "_safe_int": lambda value: int(value or 0),
                "get_settings": lambda: {},
                "_build_tabular_generated_output_row_batches": lambda rows, settings=None: [rows],
                "should_queue_tabular_generated_output_background": lambda *args: queue_background,
                "queue_tabular_generated_output_run": lambda **kwargs: (
                    queued_runs.append(kwargs) or {"id": "run-1"}
                ),
                "build_background_tabular_generated_output_metadata": lambda run: {
                    "export_run_id": run["id"],
                    "background_export": True,
                },
                "get_current_user_id": lambda: "user-1",
                "storage_account_personal_chat_container_name": "chat-files",
                "cancel_tabular_generated_output_run": lambda user_id, run_id: canceled_runs.append((user_id, run_id)),
                "upload_generated_analysis_artifact_for_current_user": lambda **kwargs: (
                    uploaded_artifacts.append(kwargs)
                    or {"message": {"id": "artifact-1", "file_name": "answer.csv"}}
                ),
                "delete_generated_chat_artifact_for_current_user": lambda conversation_id, message_id: deleted_artifacts.append((conversation_id, message_id)),
                "log_event": lambda *args, **kwargs: None,
                "logging": __import__("logging"),
            },
        )["maybe_create_generated_file_output"]

    queued_helper = load_export_helpers(queue_background=True)
    queued_checks = iter([False, True])
    try:
        queued_helper(
            "Export this table.",
            "| name | value |\n| --- | --- |\n| alpha | 1 |",
            "conversation-1",
            cancel_requested=lambda: next(queued_checks),
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "export"
    else:
        raise AssertionError("Queued export cancellation must abort publication")
    assert len(queued_runs) == 1
    assert canceled_runs == [("user-1", "run-1")]

    upload_helper = load_export_helpers(queue_background=False)
    upload_checks = iter([False, False, True])
    try:
        upload_helper(
            "Export this table.",
            "| name | value |\n| --- | --- |\n| alpha | 1 |",
            "conversation-1",
            cancel_requested=lambda: next(upload_checks),
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "artifact_publication"
    else:
        raise AssertionError("Uploaded artifact cancellation must roll back publication")
    assert len(uploaded_artifacts) == 1
    assert deleted_artifacts == [("conversation-1", "artifact-1")]


def test_citation_artifact_cancellation_rolls_back_partial_publication():
    """Citation records written before cancellation are deleted by exact stored identity."""
    persisted_ids = []
    deleted_ids = []

    class CitationContainer:
        def upsert_item(self, item):
            persisted_ids.append(item["id"])

        def delete_item(self, item, partition_key):
            deleted_ids.append((item, partition_key))

    persist = _load_route_helpers(
        {"persist_agent_citation_artifacts"},
        namespace={
            "build_agent_citation_artifact_documents": lambda **kwargs: (
                [{"artifact_id": "citation-artifact-1"}],
                [
                    {"id": "citation-artifact-1"},
                    {"id": "citation-artifact-2"},
                ],
            ),
            "cosmos_messages_container": CitationContainer(),
            "MixedSourceCancellationError": orchestration.MixedSourceCancellationError,
            "raise_if_mixed_source_cancelled": orchestration.raise_if_mixed_source_cancelled,
            "log_event": lambda *args, **kwargs: None,
            "logging": __import__("logging"),
            "_strip_agent_citation_artifact_refs": lambda citations: citations,
        },
    )["persist_agent_citation_artifacts"]
    cancel_checks = iter([False, False, True])

    try:
        persist(
            conversation_id="conversation-1",
            assistant_message_id="assistant-1",
            agent_citations=[{"tool_name": "count_rows"}],
            created_timestamp="2026-07-23T00:00:00Z",
            cancel_requested=lambda: next(cancel_checks),
        )
    except orchestration.MixedSourceCancellationError as exc:
        assert exc.phase == "artifact_publication"
    else:
        raise AssertionError("Citation cancellation must abort publication")

    assert persisted_ids == ["citation-artifact-1"]
    assert deleted_ids == [("citation-artifact-1", "conversation-1")]


def test_finalization_reauthorizes_scope_and_version_before_publication():
    """Finalization blocks revoked/rebound/version-changed contributors but keeps prior omissions partial."""
    helpers = _load_route_helpers(
        {"_validate_reauthorized_manifest_finalization"},
        namespace={
            "compare_reauthorized_source_manifests": orchestration.compare_reauthorized_source_manifests,
            "MixedSourceFinalizationError": orchestration.MixedSourceFinalizationError,
            "emit_mixed_source_telemetry": lambda *args, **kwargs: False,
            "log_event": lambda *args, **kwargs: None,
            "logging": __import__("logging"),
        },
    )
    validate = helpers["_validate_reauthorized_manifest_finalization"]

    for scope, scope_id in (
        ("personal", "user-1"),
        ("group", "group-1"),
        ("public", "public-1"),
        ("chat", "conversation-1"),
    ):
        execution_manifest = [{
            "document_id": f"{scope}-doc",
            "scope": scope,
            "scope_id": scope_id,
            "source_version": "v1",
            "authorization_status": "authorized",
        }]
        validate(execution_manifest, [dict(execution_manifest[0])])

        revoked = [{
            "document_id": f"{scope}-doc",
            "scope": None,
            "scope_id": None,
            "source_version": None,
            "authorization_status": "unresolved",
        }]
        try:
            validate(execution_manifest, revoked)
        except orchestration.MixedSourceFinalizationError as exc:
            assert exc.reason == "authorization_lost"
        else:
            raise AssertionError(f"Revoked {scope} access must block final publication")

    try:
        validate(
            [{
                "document_id": "doc-1",
                "scope": "personal",
                "scope_id": "user-1",
                "source_version": "v1",
                "authorization_status": "authorized",
            }],
            [{
                "document_id": "doc-1",
                "scope": "personal",
                "scope_id": "user-1",
                "source_version": "v2",
                "authorization_status": "authorized",
            }],
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("A source-version change must block final publication")

    validate(
        [{
            "document_id": "already-missing",
            "authorization_status": "unresolved",
        }],
        [{
            "document_id": "already-missing",
            "authorization_status": "unresolved",
        }],
    )

    strict_version_result = orchestration.compare_reauthorized_source_manifests(
        [{
            "document_id": "legacy-versioned",
            "scope": "personal",
            "scope_id": "user-1",
            "source_version": "v1",
            "authorization_status": "authorized",
        }],
        [{
            "document_id": "legacy-versioned",
            "scope": "personal",
            "scope_id": "user-1",
            "source_version": None,
            "authorization_status": "authorized",
        }],
    )
    assert strict_version_result["source_version_changed_count"] == 1


def test_bounded_catalog_query_uses_approved_rows_only():
    """Analyze All candidate queries never enumerate unapproved access-index projections."""
    access_index_path = APP_ROOT / "functions_document_access_index.py"
    source = access_index_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(access_index_path))
    query_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_query_bounded_projection_rows_for_scope"
    )
    captured = {}

    class FakeContainer:
        def query_items(self, **kwargs):
            captured.update(kwargs)
            return []

    namespace = {
        "cosmos_document_access_index_container": FakeContainer(),
        "_safe_int": lambda value: int(value or 0),
        "DOCUMENT_ACCESS_INDEX_TYPE": "document_access_index",
        "DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION": 2,
    }
    exec(
        compile(ast.Module(body=[query_function], type_ignores=[]), str(access_index_path), "exec"),
        namespace,
    )
    namespace["_query_bounded_projection_rows_for_scope"](
        "user:user-1",
        "personal",
        6,
    )
    assert "c.access_granted = true" in captured["query"]
    assert "approval_not_approved" not in captured["query"]
    assert all(item["name"] != "@approval_not_approved" for item in captured["parameters"])


def test_foundry_context_opt_out_filters_mixed_evidence_for_all_runtime_shapes():
    """The runtime strips mixed evidence before Foundry transport when context is disabled."""
    foundry_path = APP_ROOT / "foundry_agent_runtime.py"
    source = foundry_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(foundry_path))
    function_names = {
        "_looks_like_document_context_message",
        "_filter_foundry_document_context_messages",
    }
    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]

    class FakeMessage:
        def __init__(self, role="user", content="", metadata=None):
            self.role = role
            self.content = content
            self.metadata = metadata or {}

    namespace = {
        "List": list,
        "ChatMessageContent": FakeMessage,
        "_extract_message_text": lambda message: str(message.content),
    }
    exec(
        compile(ast.Module(body=function_nodes, type_ignores=[]), str(foundry_path), "exec"),
        namespace,
    )
    filter_messages = namespace["_filter_foundry_document_context_messages"]
    messages = [
        FakeMessage("system", "Use the mixed-source evidence handoff below: secret evidence"),
        FakeMessage("user", "Current user question"),
        FakeMessage(
            "user",
            "[Workflow document search context]\nsecret evidence\n\n[Workflow task]\nSafe task.",
        ),
    ]
    filtered = filter_messages(messages, include_document_context=False)
    filtered_text = "\n".join(message.content for message in filtered)
    assert "secret evidence" not in filtered_text
    assert "Current user question" in filtered_text
    assert "Safe task." in filtered_text


def test_mixed_analyze_forwards_observed_native_token_usage():
    """Native tabular usage reaches the existing workflow aggregate callback without estimates."""
    workflow_path = APP_ROOT / "functions_workflow_runner.py"
    source = workflow_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(workflow_path))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_execute_mixed_source_analyze_workflow"
    )
    captured_usage = []
    manifest = [{
        "document_id": "table-1",
        "display_name": "table.csv",
        "source_kind": "tabular",
        "scope": "personal",
        "scope_id": "user-1",
        "source_version": 1,
        "authorization_status": "authorized",
    }]

    def execute_tabular(*args, **kwargs):
        kwargs["token_usage_callback"]({
            "prompt_tokens": 11,
            "completion_tokens": 4,
            "total_tokens": 15,
            "request_count": 1,
        })
        return {
            "result": {"analysis_reply": "Computed."},
            "agent_citations": [],
            "generated_tabular_outputs": [],
        }

    namespace = {
        "SELECTION_MODE_SELECTED": "selected",
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "EVIDENCE_ENGINE_DOCUMENT_ANALYSIS": orchestration.EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
        "EVIDENCE_ENGINE_TABULAR_TOOLS": orchestration.EVIDENCE_ENGINE_TABULAR_TOOLS,
        "EVIDENCE_STATUS_CANCELED": orchestration.EVIDENCE_STATUS_CANCELED,
        "EVIDENCE_STATUS_COMPLETED": orchestration.EVIDENCE_STATUS_COMPLETED,
        "EVIDENCE_STATUS_FAILED": orchestration.EVIDENCE_STATUS_FAILED,
        "MixedSourceCancellationError": orchestration.MixedSourceCancellationError,
        "_get_document_action_source_ids": lambda config: (list(config.get("document_ids") or []), {}),
        "resolve_authorized_source_manifest": lambda *args, **kwargs: list(manifest),
        "partition_source_manifest": orchestration.partition_source_manifest,
        "run_document_analysis": lambda **kwargs: {},
        "_maybe_execute_pure_tabular_analyze_preflight": lambda *args, **kwargs: None,
        "_get_pending_tabular_generated_output": lambda outputs: None,
        "_get_terminal_unsuccessful_tabular_generated_output": lambda outputs: None,
        "_maybe_execute_tabular_document_action": execute_tabular,
        "build_evidence_envelope": orchestration.build_evidence_envelope,
        "build_mixed_source_evidence_handoff": orchestration.build_mixed_source_evidence_handoff,
        "evaluate_mixed_source_mode_outcome": orchestration.evaluate_mixed_source_mode_outcome,
        "raise_if_mixed_source_cancelled": orchestration.raise_if_mixed_source_cancelled,
        "normalize_mixed_source_correlation_id": orchestration.normalize_mixed_source_correlation_id,
        "emit_mixed_source_telemetry": lambda *args, **kwargs: False,
        "_build_mixed_source_analyze_reduction_prompt": lambda prompt, handoff: handoff["content"],
        "_build_mixed_source_analysis_coverage": lambda handoff: handoff["mixed_source_coverage"],
        "time": time,
    }
    exec(
        compile(ast.Module(body=[function_node], type_ignores=[]), str(workflow_path), "exec"),
        namespace,
    )
    namespace["_execute_mixed_source_analyze_workflow"](
        {"user_id": "user-1", "task_prompt": "Analyze."},
        {"document_ids": ["table-1"]},
        {},
        lambda *args, **kwargs: "Combined.",
        token_usage_callback=captured_usage.append,
    )
    assert captured_usage == [{
        "prompt_tokens": 11,
        "completion_tokens": 4,
        "total_tokens": 15,
        "request_count": 1,
    }]


def test_publication_rollback_uses_exact_ids_without_source_metadata():
    """Cancellation/finalization rollback only targets known generated outputs and citation artifacts."""
    canceled_runs = []
    deleted_generated = []
    deleted_citations = []
    helpers = _load_route_helpers(
        {"_rollback_mixed_source_chat_publication"},
        namespace={
            "cancel_tabular_generated_output_run": lambda user_id, run_id: (
                canceled_runs.append((user_id, run_id)) or {"canceled": True}
            ),
            "delete_generated_chat_artifact_for_current_user": lambda conversation_id, artifact_id: (
                deleted_generated.append((conversation_id, artifact_id)) or True
            ),
            "_rollback_agent_citation_artifacts": lambda conversation_id, citations: (
                deleted_citations.append((conversation_id, list(citations or [])))
                or {"deleted_artifact_count": 1, "rollback_failure_count": 0}
            ),
            "log_event": lambda *args, **kwargs: None,
            "logging": __import__("logging"),
        },
    )
    result = helpers["_rollback_mixed_source_chat_publication"](
        "user-1",
        "conversation-1",
        [{"export_run_id": "run-1"}, {"artifact_message_id": "artifact-1"}],
        compact_citations=[{"artifact_id": "citation-1"}],
    )
    assert canceled_runs == [("user-1", "run-1")]
    assert deleted_generated == [("conversation-1", "artifact-1")]
    assert deleted_citations == [("conversation-1", [{"artifact_id": "citation-1"}])]
    assert result["rollback_failure_count"] == 0


def test_continuity_keeps_terminal_state_and_never_reuses_incomplete_evidence():
    """Failed, partial, truncated, or version-changed hints require fresh native execution."""
    helpers = _load_route_helpers(
        {"_normalize_prior_grounded_document_refs", "_build_reauthorized_continuity_decision"},
        namespace={"_safe_metadata_int": lambda value: int(value or 0)},
    )
    refs = helpers["_normalize_prior_grounded_document_refs"]({
        "last_grounded_document_refs": [{
            "document_id": "table-1",
            "scope": "group",
            "scope_id": "group-1",
            "source_role": "target",
            "requested_order": 2,
            "source_kind": "tabular",
            "engine": "tabular_tools",
            "source_version": "v1",
            "status": "partial",
            "coverage": {"partial_coverage": True, "failed": False},
            "citation_count": 3,
            "artifact_count": 1,
        }],
    })
    assert refs[0]["source_version"] == "v1"
    assert refs[0]["status"] == "partial"
    assert refs[0]["coverage"]["partial_coverage"] is True
    assert refs[0]["requested_order"] == 2

    decision = helpers["_build_reauthorized_continuity_decision"](
        refs,
        [{
            "document_id": "table-1",
            "source_version": "v1",
            "authorization_status": "authorized",
        }],
        explicit_selection=False,
    )
    assert decision["incomplete_prior_source_count"] == 1
    assert decision["requires_native_execution"] is True

    explicit = helpers["_build_reauthorized_continuity_decision"](
        refs,
        [],
        explicit_selection=True,
    )
    assert explicit["selection_origin"] == "selected"
    assert explicit["prior_source_count"] == 0

    reuse_helper = _load_route_helpers(
        {"_can_reuse_prior_grounded_history"},
    )["_can_reuse_prior_grounded_history"]
    history_says_yes = {"can_answer_from_history": True}
    assert reuse_helper(history_says_yes, None) is True
    assert reuse_helper(
        history_says_yes,
        {"requires_native_execution": True},
    ) is False


def test_reference_deduplication_preserves_first_payload_and_envelope_compatibility():
    """Hybrid, tool, and generated references keep their shape without duplicates."""
    citation = {
        "citation_id": "citation-1",
        "document_id": "doc-1",
        "page_number": 2,
        "custom_payload": {"kept": True},
    }
    artifact = {
        "artifact_message_id": "artifact-1",
        "file_name": "result.csv",
        "output_format": "csv",
        "custom_payload": {"kept": True},
    }
    assert orchestration.deduplicate_mixed_source_references(
        [citation, dict(citation)],
        reference_type="citation",
    ) == [citation]
    assert orchestration.deduplicate_mixed_source_references(
        [artifact, dict(artifact)],
        reference_type="artifact",
    ) == [artifact]

    envelope = orchestration.build_evidence_envelope(
        document_id="doc-1",
        source_kind=orchestration.SOURCE_KIND_TABULAR,
        engine=orchestration.EVIDENCE_ENGINE_TABULAR_TOOLS,
        status=orchestration.EVIDENCE_STATUS_COMPLETED,
        summary="Computed.",
        citations=[citation, dict(citation)],
        generated_artifacts=[artifact, dict(artifact)],
        coverage={"terminal": True},
    )
    assert envelope["citations"] == [citation]
    assert envelope["generated_artifacts"] == [artifact]


def test_bounded_analyze_all_catalog_rejects_over_limit_without_truncation():
    """The ready access-index catalog returns every bounded ID or no IDs on overflow."""
    access_index_path = APP_ROOT / "functions_document_access_index.py"
    source = access_index_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(access_index_path))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "enumerate_bounded_document_access_index_ids"
    )
    query_limits = []
    rows = [
        {"source_document_id": "doc-1", "revision_family_id": "family-1", "source_ts": 3},
        {"source_document_id": "doc-2", "revision_family_id": "family-2", "source_ts": 2},
    ]
    namespace = {
        "DOCUMENT_ACCESS_SOURCE_SCOPES": ("personal", "group", "public"),
        "DOCUMENT_ACCESS_BOUNDED_CATALOG_MAX_SCOPES": 25,
        "_safe_int": lambda value: int(value or 0),
        "_get_document_access_index_readiness": lambda *args, **kwargs: {"ready": True},
        "_build_shadow_scope": lambda *args, **kwargs: ["user:user-1"],
        "_query_bounded_projection_rows_for_scope": lambda scope, kind, limit: (
            query_limits.append(limit) or list(rows)
        ),
        "_document_family_identity": lambda row, kind: row.get("revision_family_id"),
        "_prefer_projection_row": lambda existing, candidate: candidate,
    }
    exec(
        compile(ast.Module(body=[function_node], type_ignores=[]), str(access_index_path), "exec"),
        namespace,
    )
    enumerate_ids = namespace["enumerate_bounded_document_access_index_ids"]

    bounded = enumerate_ids("personal", 2, user_id="user-1")
    assert bounded["success"] is True
    assert bounded["document_ids"] == ["doc-1", "doc-2"]
    assert query_limits == [3]

    rows.append({
        "source_document_id": "doc-3",
        "revision_family_id": "family-3",
        "source_ts": 1,
    })
    overflow = enumerate_ids("personal", 2, user_id="user-1")
    assert overflow["success"] is False
    assert overflow["status"] == "document_limit_exceeded"
    assert overflow["document_ids"] == []


def test_analyze_all_action_is_analyze_only_and_manifest_is_fresh():
    """All mode requires Analyze and enumerated IDs still pass through the sole manifest resolver."""
    action_contract = _load_document_action_contract()
    normalize_action = action_contract["normalize_document_action_config"]
    normalized = normalize_action({
        "type": "analyze",
        "target_mode": "all",
        "doc_scope": "all",
        "active_group_ids": ["group-1"],
        "active_public_workspace_id": ["public-1"],
    })
    assert normalized["target_mode"] == "all"
    assert normalized["document_ids"] == []

    for action_type in ("search", "comparison"):
        try:
            normalize_action({
                "type": action_type,
                "target_mode": "all",
                "left_document_id": "source",
                "right_document_ids": ["target"],
            })
        except ValueError:
            pass
        else:
            raise AssertionError("All Documents must remain Analyze-only")

    workflow_path = APP_ROOT / "functions_workflow_runner.py"
    workflow_source = workflow_path.read_text(encoding="utf-8")
    workflow_tree = ast.parse(workflow_source, filename=str(workflow_path))
    function_node = next(
        node
        for node in workflow_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_execute_mixed_source_analyze_workflow"
    )
    manifest_calls = []
    reduction_calls = []
    manifest = [
        {
            "document_id": "personal-table",
            "display_name": "duplicate.csv",
            "source_kind": "tabular",
            "scope": "personal",
            "scope_id": "user-1",
            "source_version": 1,
            "authorization_status": "authorized",
        },
        {
            "document_id": "group-table",
            "display_name": "duplicate.csv",
            "source_kind": "tabular",
            "scope": "group",
            "scope_id": "group-1",
            "source_version": 1,
            "authorization_status": "authorized",
        },
    ]

    def resolve_manifest(document_ids, **kwargs):
        manifest_calls.append({"document_ids": list(document_ids), **kwargs})
        return list(manifest)

    def execute_tabular(action_type, workflow, action_config, settings, **kwargs):
        document_id = action_config["document_ids"][0]
        return {
            "result": {"analysis_reply": f"Computed {document_id}."},
            "agent_citations": [{"tool_name": "count_rows", "document_id": document_id}],
            "generated_tabular_outputs": [],
        }

    namespace = {
        "SELECTION_MODE_SELECTED": "selected",
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "EVIDENCE_ENGINE_DOCUMENT_ANALYSIS": orchestration.EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
        "EVIDENCE_ENGINE_TABULAR_TOOLS": orchestration.EVIDENCE_ENGINE_TABULAR_TOOLS,
        "EVIDENCE_STATUS_CANCELED": orchestration.EVIDENCE_STATUS_CANCELED,
        "EVIDENCE_STATUS_COMPLETED": orchestration.EVIDENCE_STATUS_COMPLETED,
        "EVIDENCE_STATUS_FAILED": orchestration.EVIDENCE_STATUS_FAILED,
        "MixedSourceCancellationError": orchestration.MixedSourceCancellationError,
        "_get_document_action_source_ids": lambda config: (list(config.get("document_ids") or []), {}),
        "_resolve_analyze_all_document_ids": lambda *args, **kwargs: {
            "document_ids": ["personal-table", "group-table"],
            "doc_scope": "all",
            "active_group_ids": ["group-1"],
            "active_public_workspace_id": [],
            "target_mode": "all",
        },
        "resolve_authorized_source_manifest": resolve_manifest,
        "partition_source_manifest": orchestration.partition_source_manifest,
        "run_document_analysis": lambda **kwargs: {},
        "_maybe_execute_pure_tabular_analyze_preflight": lambda *args, **kwargs: None,
        "_get_pending_tabular_generated_output": lambda outputs: None,
        "_get_terminal_unsuccessful_tabular_generated_output": lambda outputs: None,
        "_maybe_execute_tabular_document_action": execute_tabular,
        "build_evidence_envelope": orchestration.build_evidence_envelope,
        "build_mixed_source_evidence_handoff": orchestration.build_mixed_source_evidence_handoff,
        "emit_mixed_source_telemetry": orchestration.emit_mixed_source_telemetry,
        "evaluate_mixed_source_mode_outcome": orchestration.evaluate_mixed_source_mode_outcome,
        "normalize_mixed_source_correlation_id": orchestration.normalize_mixed_source_correlation_id,
        "raise_if_mixed_source_cancelled": orchestration.raise_if_mixed_source_cancelled,
        "time": time,
        "_build_mixed_source_analyze_reduction_prompt": lambda prompt, handoff: handoff["content"],
        "_build_mixed_source_analysis_coverage": lambda handoff: handoff["mixed_source_coverage"],
    }
    exec(
        compile(ast.Module(body=[function_node], type_ignores=[]), str(workflow_path), "exec"),
        namespace,
    )
    result = namespace["_execute_mixed_source_analyze_workflow"](
        {"user_id": "user-1", "task_prompt": "Analyze all."},
        {"target_mode": "all", "document_ids": []},
        {"enable_mixed_source_analyze_all": True},
        lambda prompt, **kwargs: reduction_calls.append(kwargs) or "Combined.",
        max_documents=5,
    )
    assert manifest_calls[0]["document_ids"] == ["personal-table", "group-table"]
    assert manifest_calls[0]["selection_mode"] == "all"
    assert result["reply"] == "Combined."
    assert result["coverage"]["completed_source_count"] == 2
    assert len(reduction_calls) == 1


def test_development_telemetry_is_default_off_allowlisted_and_privacy_safe():
    """Development telemetry emits only approved aggregate fields when explicitly enabled."""
    captured_events = []
    original_log_event = orchestration.log_event
    orchestration.log_event = lambda message, **kwargs: captured_events.append({
        "message": message,
        **kwargs,
    })
    try:
        assert orchestration.emit_mixed_source_telemetry(
            {},
            "terminal_coverage",
            "analyze",
            metrics={"completed_source_count": 1},
        ) is False
        assert captured_events == []

        assert orchestration.emit_mixed_source_telemetry(
            {"enable_mixed_source_development_telemetry": True},
            "terminal_coverage",
            "analyze",
            request_correlation_id="1de45079-f43e-4de5-a2c7-1794f23d9ea4",
            metrics={
                "completed_source_count": 2,
                "failed_source_count": 1,
                "missing_coverage_violation_count": 0,
                "latency_ms": 12.5,
            },
            dimensions={
                "selection_mode": "all",
                "outcome_status": "partial",
            },
        ) is True
    finally:
        orchestration.log_event = original_log_event

    serialized = repr(captured_events)
    assert "sensitive-document-id" not in serialized
    assert "secret.csv" not in serialized
    assert "evidence text" not in serialized
    assert captured_events[0]["extra"]["completed_source_count"] == 2
    assert captured_events[0]["extra"]["selection_mode"] == "all"

    try:
        orchestration.emit_mixed_source_telemetry(
            {"enable_mixed_source_development_telemetry": True},
            "terminal_coverage",
            "chat",
            metrics={"document_id": 1},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Source-shaped telemetry fields must be rejected")


if __name__ == "__main__":
    original_main_log_event = orchestration.log_event
    orchestration.log_event = lambda *args, **kwargs: None
    try:
        test_handoff_exposes_the_same_bounded_envelopes_used_for_synthesis()
        test_terminal_ledger_preserves_canonical_identity_and_rejects_stale_evidence()
        test_mode_failure_policy_requires_success_and_a_prepared_compare_source()
        test_compare_failed_source_is_fatal_and_failed_target_does_not_stop_later_targets()
        test_tabular_invocation_slicing_is_extracted_without_route_runtime_import()
        test_manifest_and_tabular_cancellation_stop_work_without_failure_downgrade()
        test_narrative_comparison_and_reduction_cancellation_stop_later_work()
        test_export_cancellation_rolls_back_queued_and_uploaded_artifacts()
        test_citation_artifact_cancellation_rolls_back_partial_publication()
        test_finalization_reauthorizes_scope_and_version_before_publication()
        test_bounded_catalog_query_uses_approved_rows_only()
        test_foundry_context_opt_out_filters_mixed_evidence_for_all_runtime_shapes()
        test_mixed_analyze_forwards_observed_native_token_usage()
        test_publication_rollback_uses_exact_ids_without_source_metadata()
        test_continuity_keeps_terminal_state_and_never_reuses_incomplete_evidence()
        test_reference_deduplication_preserves_first_payload_and_envelope_compatibility()
        test_bounded_analyze_all_catalog_rejects_over_limit_without_truncation()
        test_analyze_all_action_is_analyze_only_and_manifest_is_fresh()
        test_development_telemetry_is_default_off_allowlisted_and_privacy_safe()
    finally:
        orchestration.log_event = original_main_log_event
    print("Mixed-source hardening functional tests passed.")