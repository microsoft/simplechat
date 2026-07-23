#!/usr/bin/env python3
# test_tabular_document_actions_workflow.py
"""
Functional test for tabular document-action workflow support.
Version: 0.250.062
Implemented in: 0.241.038; mixed-source manifest coverage added in 0.250.062

This test ensures tabular document actions reuse the shared tabular analysis
path for Analyze and comparison workflows instead of relying only on the
search-grounded chat path, including row-linked related-document evidence and
live tabular activity thoughts. It also ensures the Phase 1 contract from
#1056 preserves valid tabular sources in a mixed selection. Parent: #1055.
"""

import ast
import logging
from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
WORKFLOW_RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
sys.path.insert(0, str(APP_ROOT))

import functions_mixed_source_orchestration as orchestration

ORIGINAL_ORCHESTRATION_LOG_EVENT = orchestration.log_event


def setup_module(module=None):
    orchestration.log_event = lambda *args, **kwargs: None


def teardown_module(module=None):
    orchestration.log_event = ORIGINAL_ORCHESTRATION_LOG_EVENT


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shared_tabular_document_action_helper_exists() -> None:
    print("Testing shared tabular document-action helper plumbing...")

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert 'def _maybe_execute_tabular_document_action(' in workflow_runner_content, (
        "Expected functions_workflow_runner.py to define a shared tabular document-action helper."
    )
    assert 'run_tabular_analysis_with_thought_tracking(' in workflow_runner_content, (
        "Expected the shared helper to reuse the tabular analysis runner."
    )
    assert 'def _resolve_tabular_document_action_documents(' in workflow_runner_content, (
        "Expected functions_workflow_runner.py to resolve selected tabular documents before dispatching analysis or comparison."
    )
    assert 'resolve_authorized_source_manifest(' in workflow_runner_content, (
        "Expected workflow document actions to support the authorized Phase 1 source manifest."
    )
    assert 'is_mixed_source_manifest_enabled(settings)' in workflow_runner_content, (
        "Expected Phase 1 workflow manifest production to remain behind its internal flag."
    )
    assert 'augment_tabular_invocations_with_related_document_evidence(' in workflow_runner_content, (
        "Expected the shared helper to reuse row-linked related-document augmentation for tabular workflows."
    )
    assert 'maybe_create_tabular_generated_output(' in workflow_runner_content, (
        "Expected the shared helper to reuse generated tabular export creation for workflow-backed tabular actions."
    )

    print("Shared tabular document-action helper checks passed")


def test_analyze_and_compare_dispatch_use_tabular_helper() -> None:
    print("Testing Analyze and comparison workflow dispatch...")

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert workflow_runner_content.count('_maybe_execute_tabular_document_action(') >= 5, (
        "Expected analysis workflow execution to preserve the shared tabular helper for flag-off rollback."
    )
    assert workflow_runner_content.count('_execute_mixed_source_analyze_workflow(') >= 3, (
        "Expected combined Analyze model and agent paths to use the Phase 3 coordinator."
    )
    assert workflow_runner_content.count(
        'DOCUMENT_ACTION_TYPE_COMPARISON, workflow, comparison_config, settings,'
    ) >= 2, (
        "Expected document comparison workflow execution to call the shared tabular document-action helper."
    )
    assert "related_document_evidence_summary=tabular_document.get('related_document_evidence_summary') or ''" in workflow_runner_content, (
        "Expected tabular analysis prompts to carry resolved related-document evidence into synthesis."
    )
    assert "related_document_evidence_summary=left_document.get('related_document_evidence_summary') or ''" in workflow_runner_content, (
        "Expected tabular comparison prompts to carry source-document related evidence into synthesis."
    )
    assert "'generated_tabular_outputs': list((tabular_action_payload or {}).get('generated_tabular_outputs') or [])" in workflow_runner_content, (
        "Expected workflow execution results to expose generated tabular outputs when the shared helper is used."
    )

    print("Analyze and comparison dispatch checks passed")


def test_tabular_document_actions_stream_live_activity() -> None:
    print("Testing tabular document-action live thought plumbing...")

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert 'def _build_tabular_document_action_thought_callback(' in workflow_runner_content, (
        "Expected a bridge that persists and streams tabular post-processing thoughts."
    )
    assert 'thought_tracker=None,' in workflow_runner_content, (
        "Expected the tabular document-action helper to accept a ThoughtTracker."
    )
    assert 'live_thought_callback=None,' in workflow_runner_content, (
        "Expected the tabular document-action helper to accept a live thought callback."
    )
    assert 'thought_tracker=thought_tracker,\n                    live_thought_callback=live_thought_callback,' in workflow_runner_content, (
        "Expected run_tabular_analysis_with_thought_tracking to receive the live tracker plumbing."
    )
    assert 'thought_callback=tabular_post_processing_thought_callback,' in workflow_runner_content, (
        "Expected generated tabular output post-processing to publish live activity thoughts."
    )
    assert workflow_runner_content.count('live_thought_callback=external_activity_callback') >= 4, (
        "Expected analyze and comparison model/agent paths to stream tabular activity through the document-action callback."
    )

    print("Tabular document-action live thought plumbing checks passed")


def test_mixed_sources_preserve_valid_tabular_partition() -> None:
    print("Testing mixed-source tabular partition behavior...")

    source_records = {
        "narrative-doc": {
            "scope": "personal",
            "document": {
                "id": "narrative-doc",
                "user_id": "user-1",
                "title": "Narrative",
                "file_name": "narrative.docx",
            },
        },
        "tabular-doc": {
            "scope": "personal",
            "document": {
                "id": "tabular-doc",
                "user_id": "user-1",
                "title": "Table",
                "file_name": "table.csv",
            },
        },
    }
    resolver = lambda **kwargs: source_records.get(kwargs["document_id"])
    manifest = orchestration.resolve_authorized_source_manifest(
        ["narrative-doc", "tabular-doc"],
        user_id="user-1",
        context_resolver=resolver,
    )
    partitions = orchestration.partition_source_manifest(manifest)

    assert [entry["document_id"] for entry in manifest] == [
        "narrative-doc",
        "tabular-doc",
    ]
    assert [entry["document_id"] for entry in partitions["narrative_sources"]] == [
        "narrative-doc",
    ]
    assert [entry["document_id"] for entry in partitions["tabular_sources"]] == [
        "tabular-doc",
    ]

    print("Mixed-source tabular partition checks passed")


def test_manifest_flag_does_not_change_workflow_dispatch() -> None:
    print("Testing workflow manifest flag behavior equivalence...")

    workflow_runner_tree = ast.parse(read_text(WORKFLOW_RUNNER_FILE))
    helper_node = next(
        node
        for node in workflow_runner_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_maybe_execute_tabular_document_action"
    )
    helper_module = ast.Module(body=[helper_node], type_ignores=[])
    ast.fix_missing_locations(helper_module)

    legacy_resolver_calls = []
    manifest_calls = []
    namespace = {
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "DOCUMENT_ACTION_TYPE_COMPARISON": "comparison",
        "is_tabular_processing_enabled": lambda settings: True,
        "is_mixed_source_manifest_enabled": lambda settings: bool(
            settings.get("enable_mixed_source_manifest")
        ),
        "_get_document_action_source_ids": lambda action_config: (
            list(action_config.get("document_ids") or []),
            {},
        ),
        "resolve_authorized_source_manifest": lambda *args, **kwargs: (
            manifest_calls.append((args, kwargs)) or []
        ),
        "_resolve_tabular_document_action_documents": lambda *args, **kwargs: (
            legacy_resolver_calls.append((args, kwargs)) or [{"document_id": "table-1"}]
        ),
        "_resolve_tabular_document_action_model_name": lambda workflow, settings: "",
        "log_event": lambda *args, **kwargs: None,
        "logging": logging,
    }
    exec(compile(helper_module, str(WORKFLOW_RUNNER_FILE), "exec"), namespace)
    helper = namespace["_maybe_execute_tabular_document_action"]
    action_config = {"type": "analyze", "document_ids": ["table-1"]}
    workflow = {"user_id": "user-1"}

    disabled_result = helper(
        "analyze",
        workflow,
        action_config,
        {"enable_mixed_source_manifest": False},
        conversation_id="conversation-1",
        invoke_prompt=lambda *args, **kwargs: None,
    )
    disabled_legacy_call = legacy_resolver_calls[-1]
    assert manifest_calls == []

    enabled_result = helper(
        "analyze",
        workflow,
        action_config,
        {"enable_mixed_source_manifest": True},
        conversation_id="conversation-1",
        invoke_prompt=lambda *args, **kwargs: None,
    )
    enabled_legacy_call = legacy_resolver_calls[-1]

    assert disabled_result == enabled_result is None
    assert disabled_legacy_call == enabled_legacy_call
    assert len(manifest_calls) == 1
    assert manifest_calls[0][0] == (["table-1"],)

    namespace["is_tabular_processing_enabled"] = lambda settings: False
    manifest_calls.clear()
    legacy_resolver_calls.clear()
    disabled_tabular_result = helper(
        "analyze",
        workflow,
        action_config,
        {"enable_mixed_source_manifest": True},
        conversation_id="conversation-1",
        invoke_prompt=lambda *args, **kwargs: None,
    )
    assert disabled_tabular_result is None
    assert len(manifest_calls) == 1
    assert legacy_resolver_calls == []

    print("Workflow manifest flag behavior equivalence checks passed")


def test_document_action_chat_does_not_duplicate_shadow_manifest() -> None:
    print("Testing document-action Chat manifest ownership...")

    route_tree = ast.parse(
        read_text(ROOT / "application" / "single_app" / "route_backend_chats.py")
    )
    document_action_function = next(
        node
        for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "execute_document_action_chat_request"
    )
    manifest_calls = [
        node
        for node in ast.walk(document_action_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_maybe_resolve_chat_source_manifest"
    ]
    assert manifest_calls == []

    print("Document-action Chat manifest ownership checks passed")


def run_tests() -> bool:
    tests = [
        test_shared_tabular_document_action_helper_exists,
        test_analyze_and_compare_dispatch_use_tabular_helper,
        test_tabular_document_actions_stream_live_activity,
        test_mixed_sources_preserve_valid_tabular_partition,
        test_manifest_flag_does_not_change_workflow_dispatch,
        test_document_action_chat_does_not_duplicate_shadow_manifest,
    ]
    results = []
    setup_module()
    try:
        for test in tests:
            print(f"\nRunning {test.__name__}...")
            try:
                test()
                print("PASS")
                results.append(True)
            except Exception as exc:
                print(f"FAIL: {exc}")
                traceback.print_exc()
                results.append(False)
    finally:
        teardown_module()

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)