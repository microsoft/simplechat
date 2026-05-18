#!/usr/bin/env python3
# test_tabular_document_actions_workflow.py
"""
Functional test for tabular document-action workflow support.
Version: 0.241.038
Implemented in: 0.241.038

This test ensures tabular document actions reuse the shared tabular analysis
path for Analyze and comparison workflows instead of relying only on the
search-grounded chat path, including row-linked related-document evidence and
live tabular activity thoughts.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"


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

    assert "DOCUMENT_ACTION_TYPE_ANALYZE,\n                    workflow,\n                    analysis_config," in workflow_runner_content, (
        "Expected analysis workflow execution to call the shared tabular document-action helper."
    )
    assert "DOCUMENT_ACTION_TYPE_COMPARISON,\n                    workflow,\n                    comparison_config," in workflow_runner_content, (
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


def run_tests() -> bool:
    tests = [
        test_shared_tabular_document_action_helper_exists,
        test_analyze_and_compare_dispatch_use_tabular_helper,
        test_tabular_document_actions_stream_live_activity,
    ]
    results = []

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

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)