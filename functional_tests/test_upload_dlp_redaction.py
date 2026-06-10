# test_upload_dlp_redaction.py
#!/usr/bin/env python3
"""
Functional test for upload DLP redaction.
Version: 0.242.069
Implemented in: 0.242.069

This test ensures upload DLP redacts chunk text before embeddings and Azure AI
Search indexing, hardens raw chunk logs, stores counts-only metadata, and emits
safe upload telemetry/review summaries.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
FUNCTIONS_DOCUMENTS_FILE = os.path.join(APP_DIR, "functions_documents.py")
sys.path.insert(0, APP_DIR)


RAW_VALUE = "123-45-6789"


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text, filename=FUNCTIONS_DOCUMENTS_FILE)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


def test_upload_helper_redacts_or_blocks_with_safe_state():
    """Upload helper should shape redact/block states without raw values."""
    print("Testing upload DLP helper behavior...")
    from functions_dlp import evaluate_upload_content

    redact_result = evaluate_upload_content(
        f"Chunk contains {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
        },
        context={"document_id": "doc-1", "workspace_scope": "personal"},
    )
    block_result = evaluate_upload_content(
        f"Chunk contains {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "block",
        },
        context={"document_id": "doc-1", "workspace_scope": "personal"},
    )

    assert redact_result["decision"] == "redact"
    assert redact_result["upload_allowed"] is True
    assert redact_result["status"] == "accepted_with_redactions"
    assert "[REDACTED_US_SSN]" in redact_result["sanitized_text"]
    assert RAW_VALUE not in repr(redact_result)

    assert block_result["decision"] == "block"
    assert block_result["upload_allowed"] is False
    assert block_result["status"] == "blocked"
    assert block_result["sanitized_text"] == ""
    assert RAW_VALUE not in repr(block_result)


def test_upload_fail_on_match_overrides_redact_mode():
    """Fail-on-match should block even when mode would otherwise redact."""
    print("Testing upload fail-on-match behavior...")
    from functions_dlp import evaluate_upload_content

    result = evaluate_upload_content(
        f"Chunk contains {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
            "upload_dlp_fail_upload_on_match": True,
        },
        context={"document_id": "doc-1", "workspace_scope": "personal"},
    )

    assert result["decision"] == "block"
    assert result["upload_allowed"] is False
    assert result["status"] == "blocked"
    assert result["sanitized_text"] == ""
    assert RAW_VALUE not in repr(result)


def test_upload_dlp_uses_custom_regex_rules():
    """Upload DLP should honor admin-configured regex rules and confidence shaping."""
    print("Testing upload DLP custom regex rules...")
    from functions_dlp import evaluate_upload_content

    raw_document_id = "DOC-123456"
    result = evaluate_upload_content(
        f"Customer document {raw_document_id} is ready",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
            "dlp_regex_rules": [
                {
                    "id": "document_id",
                    "label": "Document ID",
                    "entity_type": "DOCUMENT_ID",
                    "enabled": True,
                    "pattern": r"DOC-\d{6}",
                    "replacement": "[REDACTED_DOCUMENT_ID]",
                    "surfaces": ["upload"],
                    "flags": [],
                    "validator": "none",
                    "confidence": {
                        "regex_only": "low",
                        "with_keywords": "high",
                        "keywords": ["document", "customer"],
                        "window_chars": 32,
                        "minimum": "high",
                    },
                }
            ],
        },
        context={"document_id": "doc-1", "workspace_scope": "personal"},
    )

    assert result["decision"] == "redact"
    assert result["upload_allowed"] is True
    assert result["status"] == "accepted_with_redactions"
    assert result["sanitized_text"] == "Customer document [REDACTED_DOCUMENT_ID] is ready"
    assert result["match_counts"] == {"DOCUMENT_ID": 1}
    assert raw_document_id not in repr(result)


def test_upload_dlp_blocks_when_text_exceeds_scan_limit():
    """Enforced upload DLP should block when text exceeds the scan limit."""
    print("Testing upload DLP scan-limit enforcement...")
    from functions_dlp import evaluate_upload_content

    result = evaluate_upload_content(
        "safe prefix " + ("x" * 50) + " 123-45-6789",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
            "dlp_default_engine": "regex",
            "dlp_max_scan_chars": 12,
        },
        context={"document_id": "doc-scan-limit", "workspace_scope": "personal"},
    )

    assert result["decision"] == "block"
    assert result["upload_allowed"] is False
    assert result["status"] == "scanner_failed"
    assert result["scanner_status"] == "truncated"
    assert result["sanitized_text"] == ""
    assert "123-45-6789" not in repr(result)


def test_upload_fail_on_match_blocks_truncated_monitor_mode():
    """Fail-on-match is an enforcing upload mode and should block truncated scans."""
    print("Testing upload fail-on-match scan-limit enforcement...")
    from functions_dlp import evaluate_upload_content

    result = evaluate_upload_content(
        "safe prefix " + ("x" * 50) + " 123-45-6789",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "monitor",
            "upload_dlp_fail_upload_on_match": True,
            "dlp_default_engine": "regex",
            "dlp_max_scan_chars": 12,
        },
        context={"document_id": "doc-scan-limit", "workspace_scope": "personal"},
    )

    assert result["decision"] == "block"
    assert result["upload_allowed"] is False
    assert result["status"] == "scanner_failed"
    assert result["scanner_status"] == "truncated"
    assert result["sanitized_text"] == ""
    assert "123-45-6789" not in repr(result)


def test_save_chunks_redacts_before_embedding_and_logs_safe_summary():
    """save_chunks should evaluate DLP before generate_embedding and avoid raw logs."""
    print("Testing save_chunks DLP ordering and log safety...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    save_chunks_source = extract_function_source(source, "save_chunks")

    assert "from functions_dlp import" in source
    assert "evaluate_upload_content" in source
    assert "build_upload_dlp_file_log_summary" in source
    assert save_chunks_source.find("_evaluate_upload_dlp_text(") < save_chunks_source.find("generate_embedding(")
    assert "generate_embedding(page_text_content)" not in save_chunks_source
    assert "page_text_content:{page_text_content}" not in save_chunks_source
    assert "chunk_text\": sanitized" in save_chunks_source or "chunk_text\": enhanced_chunk_text" in save_chunks_source
    assert "dlp_metadata" in save_chunks_source


def test_save_chunks_batch_redacts_before_batch_embedding():
    """save_chunks_batch should sanitize each chunk before batch embeddings."""
    print("Testing save_chunks_batch DLP ordering...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    batch_source = extract_function_source(source, "save_chunks_batch")

    assert batch_source.find("_evaluate_upload_dlp_text(") < batch_source.find("generate_embeddings_batch(")
    assert "texts = [c['page_text_content'] for c in chunks_data]" not in batch_source
    assert "sanitized_chunks_data" in batch_source
    assert "dlp_metadata" in batch_source


def test_save_video_chunk_redacts_transcript_and_ocr_before_embedding_and_indexing():
    """save_video_chunk should sanitize transcript and OCR before embedding/search."""
    print("Testing save_video_chunk DLP ordering...")
    source = read_file_text(FUNCTIONS_DOCUMENTS_FILE)
    video_source = extract_function_source(source, "save_video_chunk")

    assert video_source.find("_evaluate_upload_dlp_text(") < video_source.find("generate_embedding(")
    assert "generate_embedding(page_text_content)" not in video_source
    assert '"chunk_text":           sanitized_transcript_text' in video_source
    assert '"video_ocr_chunk_text": sanitized_ocr_text' in video_source


if __name__ == "__main__":
    tests = [
        test_upload_helper_redacts_or_blocks_with_safe_state,
        test_upload_fail_on_match_overrides_redact_mode,
        test_upload_dlp_uses_custom_regex_rules,
        test_upload_dlp_blocks_when_text_exceeds_scan_limit,
        test_upload_fail_on_match_blocks_truncated_monitor_mode,
        test_save_chunks_redacts_before_embedding_and_logs_safe_summary,
        test_save_chunks_batch_redacts_before_batch_embedding,
        test_save_video_chunk_redacts_transcript_and_ocr_before_embedding_and_indexing,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} upload DLP redaction tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
