# test_dlp_telemetry.py
#!/usr/bin/env python3
"""
Functional test for safe DLP telemetry.
Version: 0.241.011
Implemented in: 0.241.008

This test ensures DLP telemetry properties include bounded decision metadata
without raw matched values, raw prompts, raw web-search queries, raw chunk text,
or raw filenames.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
FUNCTIONS_DLP_FILE = os.path.join(APP_DIR, "functions_dlp.py")
sys.path.insert(0, APP_DIR)


RAW_TEXT = "Search for 123-45-6789 in the confidential roadmap"
RAW_FILENAME = "alice-123-45-6789-roadmap.txt"


def test_telemetry_properties_are_counts_only():
    """Telemetry should contain safe bounded DLP properties only."""
    print("Testing DLP telemetry safety...")
    from functions_dlp import build_dlp_telemetry_properties, evaluate_dlp_text

    result = evaluate_dlp_text(
        RAW_TEXT,
        settings={"enable_dlp_control_plane": True, "web_search_dlp_mode": "redact"},
        surface="web_search",
    )
    properties = build_dlp_telemetry_properties(
        result,
        surface="web_search",
        context={
            "conversation_id": "conversation-123",
            "chat_type": "user",
            "workspace_scope": "personal",
            "file_name": RAW_FILENAME,
            "raw_text": RAW_TEXT,
        },
    )

    assert properties["activity_type"] == "dlp_decision"
    assert properties["dlp_surface"] == "web_search"
    assert properties["dlp_action"] == "redact"
    assert properties["dlp_engine"] == "regex"
    assert properties["dlp_mode"] == "redact"
    assert properties["workspace_scope"] == "personal"
    assert properties["scanner_status"] == "ok"
    assert properties["dlp_total_replacements"] == 1
    assert properties["dlp_entity_counts"] == {"US_SSN": 1}

    serialized = repr(properties)
    forbidden = [
        "123-45-6789",
        "confidential roadmap",
        RAW_TEXT,
        RAW_FILENAME,
        "[REDACTED_US_SSN]",
    ]
    for value in forbidden:
        assert value not in serialized, f"Unsafe telemetry value leaked: {value}"


def test_scanner_error_telemetry_is_safe():
    """Scanner failure telemetry should avoid source text and raw errors."""
    print("Testing scanner error telemetry safety...")
    from functions_dlp import build_dlp_telemetry_properties

    result = {
        "enabled": True,
        "engine": "presidio_service",
        "mode": "block",
        "decision": "block",
        "scanner_status": "error",
        "text": RAW_TEXT,
        "redacted_text": RAW_TEXT,
        "total_replacements": 0,
        "match_counts": {},
        "matches": [],
        "metadata": {"error": "service saw 123-45-6789 before timeout"},
    }

    properties = build_dlp_telemetry_properties(
        result,
        surface="web_search",
        context={"raw_text": RAW_TEXT, "file_name": RAW_FILENAME},
    )

    assert properties["scanner_status"] == "error"
    assert "scanner_error" in properties
    serialized = repr(properties)
    assert "123-45-6789" not in serialized
    assert RAW_TEXT not in serialized
    assert RAW_FILENAME not in serialized


def test_upload_dlp_telemetry_is_safe():
    """Upload DLP telemetry should include counts and no raw chunk text."""
    print("Testing upload DLP telemetry safety...")
    from functions_dlp import build_dlp_telemetry_properties, evaluate_upload_content

    result = evaluate_upload_content(
        RAW_TEXT,
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
        },
        context={"document_id": "doc-1", "workspace_scope": "public"},
    )
    properties = build_dlp_telemetry_properties(
        result,
        surface="upload",
        context={"document_id": "doc-1", "workspace_scope": "public", "raw_text": RAW_TEXT},
    )

    assert properties["dlp_surface"] == "upload"
    assert properties["dlp_action"] == "redact"
    assert properties["workspace_scope"] == "public"
    assert properties["dlp_entity_counts"] == {"US_SSN": 1}
    assert RAW_TEXT not in repr(properties)
    assert "123-45-6789" not in repr(properties)


def test_scanner_error_log_avoids_raw_traceback_capture():
    """Scanner exception logging should not send traceback text to telemetry."""
    print("Testing scanner error log traceback safety...")
    with open(FUNCTIONS_DLP_FILE, "r", encoding="utf-8") as file_handle:
        source = file_handle.read()

    scanner_error_index = source.find('"[DLP] Scanner error"')
    traceback_index = source.find("exceptionTraceback=False", scanner_error_index)
    error_type_index = source.find('"error_type": type(exc).__name__', scanner_error_index)

    assert scanner_error_index != -1
    assert traceback_index > scanner_error_index
    assert error_type_index > scanner_error_index
    assert "exceptionTraceback=True" not in source[scanner_error_index:traceback_index]


def test_monitor_detections_emit_telemetry_by_default():
    """Monitor-mode detections should emit telemetry even when allow sampling is disabled."""
    print("Testing monitor-mode DLP telemetry emission...")
    from functions_dlp import evaluate_dlp_text, should_emit_dlp_telemetry

    result = evaluate_dlp_text(
        RAW_TEXT,
        settings={"enable_dlp_control_plane": True, "web_search_dlp_mode": "monitor"},
        surface="web_search",
    )

    assert result["decision"] == "monitor"
    assert result["match_counts"] == {"US_SSN": 1}
    assert result["total_replacements"] == 1
    assert should_emit_dlp_telemetry(result, settings={}) is True
    assert should_emit_dlp_telemetry(
        result,
        settings={"dlp_telemetry_sample_allow_events": False},
    ) is True


def test_clean_allow_telemetry_respects_sampling_default():
    """Clean allow events should stay silent unless allow sampling is enabled."""
    print("Testing clean allow DLP telemetry sampling...")
    from functions_dlp import evaluate_dlp_text, should_emit_dlp_telemetry

    result = evaluate_dlp_text(
        "Search for public weather forecast",
        settings={"enable_dlp_control_plane": True, "web_search_dlp_mode": "monitor"},
        surface="web_search",
    )

    assert result["decision"] == "allow"
    assert result["match_counts"] == {}
    assert result["total_replacements"] == 0
    assert should_emit_dlp_telemetry(result, settings={}) is False
    assert should_emit_dlp_telemetry(
        result,
        settings={"dlp_telemetry_sample_allow_events": False},
    ) is False


if __name__ == "__main__":
    tests = [
        test_telemetry_properties_are_counts_only,
        test_scanner_error_telemetry_is_safe,
        test_upload_dlp_telemetry_is_safe,
        test_scanner_error_log_avoids_raw_traceback_capture,
        test_monitor_detections_emit_telemetry_by_default,
        test_clean_allow_telemetry_respects_sampling_default,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} DLP telemetry tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
