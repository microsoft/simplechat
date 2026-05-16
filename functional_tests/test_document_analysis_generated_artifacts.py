#!/usr/bin/env python3
# test_document_analysis_generated_artifacts.py
"""
Functional test for analysis generated artifacts.
Version: 0.241.023
Implemented in: 0.241.125

This test ensures analysis can persist a chat-scoped generated
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


def test_document_analysis_workflow_artifact_plumbing() -> None:
    print("Testing analysis workflow artifact plumbing...")

    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert 'def _maybe_create_document_analysis_generated_artifacts(' in workflow_runner_content, (
        "Expected functions_workflow_runner.py to expose analysis artifact generation."
    )
    assert 'upload_generated_analysis_artifact_for_current_user' in workflow_runner_content, (
        "Expected analysis artifact generation to use the generic chat artifact uploader."
    )
    assert "capability='analyze'" in workflow_runner_content, (
        "Expected analysis artifacts to persist with the analyze capability label."
    )
    assert "generated_analysis_artifacts': document_analysis_artifact_payload.get('artifacts', [])" in workflow_runner_content, (
        "Expected analysis execution results to return generated analysis artifact metadata."
    )
    assert "document_analysis_artifact_payload.get('assistant_reply')" in workflow_runner_content, (
        "Expected analysis artifact generation to swap in a concise assistant reply when an artifact is created."
    )

    print("Document analysis workflow artifact plumbing checks passed")


def test_document_action_metadata_and_ui_surface() -> None:
    print("Testing document action metadata and UI surface...")

    chat_route_content = read_text(CHAT_ROUTE_FILE)
    chat_messages_content = read_text(CHAT_MESSAGES_FILE)

    assert "document_generated_analysis_artifacts = list(execution_result.get('generated_analysis_artifacts') or [])" in chat_route_content, (
        "Expected route_backend_chats.py to collect document-action generated analysis artifacts before assistant metadata persistence."
    )
    assert 'generated_analysis_artifacts=document_generated_analysis_artifacts' in chat_route_content, (
        "Expected route_backend_chats.py to persist document-action generated analysis artifacts onto assistant metadata."
    )
    assert 'function getGeneratedAnalysisArtifactTitle(outputMetadata, outputFormat)' in chat_messages_content, (
        "Expected chat-messages.js to derive capability-aware artifact card titles."
    )
    assert 'Analyze ${outputFormat.toUpperCase()} artifact' in chat_messages_content, (
        "Expected analysis artifacts to render a specific capability label in the chat UI."
    )

    print("Document action metadata and UI surface checks passed")


def run_tests() -> bool:
    tests = [
        test_document_analysis_workflow_artifact_plumbing,
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