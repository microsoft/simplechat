#!/usr/bin/env python3
# test_document_action_debug_logging.py
"""
Functional test for document action debug logging.
Version: 0.241.023
Implemented in: 0.241.095

This test ensures analysis and document comparison flows emit
debug_print instrumentation for start, progress, failure, and completion in
their shared runners and chat/workflow entry points.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_ANALYSIS_FILE = ROOT / "application" / "single_app" / "functions_document_analysis.py"
DOCUMENT_COMPARISON_FILE = ROOT / "application" / "single_app" / "functions_document_comparison.py"
WORKFLOW_RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_document_action_debug_logging_markers() -> None:
    print("🔍 Testing document action debug logging markers...")

    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Starting analysis | ")
    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Starting document | ")
    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Starting window | ")
    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Window attempt failed | ")
    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Completed window | ")
    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Starting reduction batch | ")
    assert_contains(DOCUMENT_ANALYSIS_FILE, "[DocumentAnalysis] Completed analysis | ")

    assert_contains(DOCUMENT_COMPARISON_FILE, "[DocumentComparison] Starting comparison | ")
    assert_contains(DOCUMENT_COMPARISON_FILE, "[DocumentComparison] Starting summary pass | ")
    assert_contains(DOCUMENT_COMPARISON_FILE, "[DocumentComparison] Starting pairwise comparison | ")
    assert_contains(DOCUMENT_COMPARISON_FILE, "[DocumentComparison] Completed pairwise comparison | ")
    assert_contains(DOCUMENT_COMPARISON_FILE, "[DocumentComparison] Starting comparison reduction | ")
    assert_contains(DOCUMENT_COMPARISON_FILE, "[DocumentComparison] Completed comparison | ")

    assert_contains(WORKFLOW_RUNNER_FILE, "from functions_debug import debug_print")
    assert_contains(WORKFLOW_RUNNER_FILE, "[WorkflowDocumentAnalysis] Starting workflow action | ")
    assert_contains(WORKFLOW_RUNNER_FILE, "[WorkflowDocumentComparison] Starting workflow action | ")
    assert_contains(WORKFLOW_RUNNER_FILE, "[WorkflowDocumentAction] Dispatching action | ")
    assert_contains(WORKFLOW_RUNNER_FILE, "[WorkflowDocumentAction] Action failed | ")
    assert_contains(WORKFLOW_RUNNER_FILE, "[WorkflowDocumentAction] Action completed | ")

    assert_contains(CHAT_ROUTE_FILE, "[ChatDocumentAction] Received request | ")
    assert_contains(CHAT_ROUTE_FILE, "[ChatDocumentAction] Validation failed | ")
    assert_contains(CHAT_ROUTE_FILE, "[ChatDocumentAction] Normalized action | ")
    assert_contains(CHAT_ROUTE_FILE, "[ChatDocumentAction] Executing action | ")
    assert_contains(CHAT_ROUTE_FILE, "[ChatDocumentAction] Execution failed | ")
    assert_contains(CHAT_ROUTE_FILE, "[ChatDocumentAction] Execution completed | ")

    assert_contains(CONFIG_FILE, 'VERSION = "0.241.023"')

    print("✅ Document action debug logging markers verified")


def run_tests() -> bool:
    tests = [test_document_action_debug_logging_markers]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)