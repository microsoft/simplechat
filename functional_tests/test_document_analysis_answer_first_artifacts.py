#!/usr/bin/env python3
# test_document_analysis_answer_first_artifacts.py
"""
Functional test for document analysis answer-first artifact replies.
Version: 0.241.124
Implemented in: 0.241.124

This test ensures Analyze responses lead with a concise answer summary while
keeping full generated CSV/Markdown artifacts available behind collapsed
preview sections in the chat UI, with CSV artifacts previewed as rows.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
WORKFLOW_RUNNER_FILE = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
CHAT_MESSAGES_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
CHATS_CSS_FILE = ROOT / "application" / "single_app" / "static" / "css" / "chats.css"
EXPECTED_VERSION = "0.241.124"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_current_version() -> str:
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError("Expected config.py to define VERSION")


def test_backend_answer_first_reply_contract() -> None:
    print("Testing document analysis answer-first backend reply contract...")

    current_version = read_current_version()
    workflow_runner_content = read_text(WORKFLOW_RUNNER_FILE)

    assert current_version == EXPECTED_VERSION, (
        f"Expected config.py version {EXPECTED_VERSION} for the answer-first analysis artifact fix."
    )
    assert "def _build_document_analysis_answer_summary(" in workflow_runner_content, (
        "Expected workflow runner to build a concise answer summary before artifact details."
    )
    assert "def _build_document_analysis_page_count_summary(" in workflow_runner_content, (
        "Expected page/count analysis requests to get a direct summarized answer."
    )
    assert "Pages with matches:" in workflow_runner_content, (
        "Expected page/count summaries to identify non-zero pages in the assistant message."
    )
    assert "Answer summary:" in workflow_runner_content, (
        "Expected generated artifact replies to lead with an explicit answer summary."
    )
    assert "structured_rows=structured_rows" in workflow_runner_content, (
        "Expected multi-artifact replies to receive structured rows for fallback summarization."
    )
    assert "Small preview:" not in workflow_runner_content, (
        "Expected artifact-backed analysis replies to avoid inline preview fragments."
    )
    assert "preview_rows=structured_rows[:DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT]" in workflow_runner_content, (
        "Expected CSV analysis artifacts to expose row previews instead of JSON preview items."
    )

    print("Document analysis backend reply contract checks passed")


def test_generated_analysis_preview_collapse_contract() -> None:
    print("Testing generated analysis preview collapse UI contract...")

    chat_messages_content = read_text(CHAT_MESSAGES_FILE)
    chats_css_content = read_text(CHATS_CSS_FILE)

    assert "function shouldCollapseGeneratedAnalysisPreview(outputMetadata)" in chat_messages_content, (
        "Expected chat UI to decide when generated analysis previews should be collapsed."
    )
    assert "capability === 'analyze' || capability === 'comparison'" in chat_messages_content, (
        "Expected Analyze and Comparison artifact previews to collapse by default."
    )
    assert "document.createElement('details')" in chat_messages_content, (
        "Expected generated analysis previews to use native collapsible details elements."
    )
    assert "generated-analysis-preview-details" in chat_messages_content, (
        "Expected generated analysis preview details to use a dedicated CSS class."
    )
    assert "Show preview" in chat_messages_content, (
        "Expected collapsed artifact cards to expose a clear preview disclosure control."
    )
    assert "function shouldRenderPreviewItemsAsRows(outputMetadata, outputFormat)" in chat_messages_content, (
        "Expected CSV-like artifact preview items to render as tabular rows for existing metadata."
    )
    assert "buildGeneratedTabularPreviewTable(previewItems)" in chat_messages_content, (
        "Expected CSV-like preview items to use the table preview renderer."
    )
    assert ".generated-analysis-preview-details > summary" in chats_css_content, (
        "Expected collapsed generated analysis previews to have dedicated summary styling."
    )

    print("Generated analysis preview collapse UI checks passed")


def run_tests() -> bool:
    tests = [
        test_backend_answer_first_reply_contract,
        test_generated_analysis_preview_collapse_contract,
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
