#!/usr/bin/env python3
# test_exhaustive_review_generated_artifacts.py
"""
Functional test for exhaustive review generated artifacts.
Version: 0.241.125
Implemented in: 0.241.125

This test ensures exhaustive review can persist a chat-scoped generated
analysis artifact, return concise assistant content, and expose capability-
aware preview metadata to the generic chat artifact UI.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_exhaustive_review_workflow_artifact_plumbing() -> None:
    print("Testing exhaustive review workflow artifact plumbing...")

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert 'def _maybe_create_exhaustive_review_generated_artifacts(' in workflow_runner_content, (
        "Expected functions_workflow_runner.py to expose exhaustive review artifact generation."
    )
    assert 'upload_generated_analysis_artifact_for_current_user' in workflow_runner_content, (
        "Expected exhaustive review artifact generation to use the generic chat artifact uploader."
    )
    assert "capability='exhaustive_review'" in workflow_runner_content, (
        "Expected exhaustive review artifacts to persist with the exhaustive_review capability label."
    )
    assert "generated_analysis_artifacts': exhaustive_review_artifact_payload.get('artifacts', [])" in workflow_runner_content, (
        "Expected exhaustive review execution results to return generated analysis artifact metadata."
    )
    assert "exhaustive_review_artifact_payload.get('assistant_reply')" in workflow_runner_content, (
        "Expected exhaustive review artifact generation to swap in a concise assistant reply when an artifact is created."
    )

    print("Exhaustive review workflow artifact plumbing checks passed")


def test_document_action_metadata_and_ui_surface() -> None:
    print("Testing document action metadata and UI surface...")

    chat_route_content = read_text(CHAT_ROUTE_FILE)
    chat_messages_content = read_text(CHAT_MESSAGES_FILE)

    assert "generated_analysis_artifacts=execution_result.get('generated_analysis_artifacts')" in chat_route_content, (
        "Expected route_backend_chats.py to persist document-action generated analysis artifacts onto assistant metadata."
    )
    assert 'function getGeneratedAnalysisArtifactTitle(outputMetadata, outputFormat)' in chat_messages_content, (
        "Expected chat-messages.js to derive capability-aware artifact card titles."
    )
    assert 'Exhaustive Review ${outputFormat.toUpperCase()} artifact' in chat_messages_content, (
        "Expected exhaustive review artifacts to render a specific capability label in the chat UI."
    )

    print("Document action metadata and UI surface checks passed")


def run_tests() -> bool:
    tests = [
        test_exhaustive_review_workflow_artifact_plumbing,
        test_document_action_metadata_and_ui_surface,
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