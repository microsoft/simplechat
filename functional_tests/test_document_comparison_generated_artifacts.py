#!/usr/bin/env python3
# test_document_comparison_generated_artifacts.py
"""
Functional test for document comparison generated artifacts.
Version: 0.241.125
Implemented in: 0.241.125

This test ensures document comparison can persist a chat-scoped generated
analysis artifact and return concise assistant content while reusing the
generic artifact UI surface.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_document_comparison_workflow_artifact_plumbing() -> None:
    print("Testing document comparison workflow artifact plumbing...")

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert 'def _maybe_create_comparison_generated_artifacts(' in workflow_runner_content, (
        "Expected functions_workflow_runner.py to expose comparison artifact generation."
    )
    assert "capability='comparison'" in workflow_runner_content, (
        "Expected comparison artifacts to persist with the comparison capability label."
    )
    assert "generated_analysis_artifacts': comparison_artifact_payload.get('artifacts', [])" in workflow_runner_content, (
        "Expected comparison execution results to return generated analysis artifact metadata."
    )
    assert "comparison_artifact_payload.get('assistant_reply')" in workflow_runner_content, (
        "Expected comparison artifact generation to swap in a concise assistant reply when an artifact is created."
    )

    print("Document comparison workflow artifact plumbing checks passed")


def test_document_comparison_ui_label() -> None:
    print("Testing document comparison UI label...")

    chat_messages_content = read_text(CHAT_MESSAGES_FILE)

    assert 'Comparison ${outputFormat.toUpperCase()} artifact' in chat_messages_content, (
        "Expected comparison artifacts to render a comparison-specific card title in the chat UI."
    )

    print("Document comparison UI label checks passed")


def run_tests() -> bool:
    tests = [
        test_document_comparison_workflow_artifact_plumbing,
        test_document_comparison_ui_label,
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