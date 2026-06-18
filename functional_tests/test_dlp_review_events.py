# test_dlp_review_events.py
#!/usr/bin/env python3
"""
Functional test for DLP review event safety.
Version: 0.242.073
Implemented in: 0.242.073

This test ensures DLP review routing defaults to disabled and any optional
review event summary uses distinct DLP policy typing with counts-only payloads.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
SETTINGS_FILE = os.path.join(APP_DIR, "functions_settings.py")
sys.path.insert(0, APP_DIR)


RAW_VALUE = "123-45-6789"


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_review_destination_defaults_to_none():
    """DLP findings should not enter review queues by default."""
    print("Testing default DLP review routing...")
    source = read_file_text(SETTINGS_FILE)
    assert "'dlp_review_destination': 'none'" in source
    assert "'web_search_dlp_track_review_events': False" not in source
    assert "'upload_dlp_track_review_events': False" not in source


def test_review_summary_has_dlp_type_and_no_raw_values():
    """Review payload summaries should be distinctly typed and counts-only."""
    print("Testing safe DLP review summary...")
    from functions_dlp import build_dlp_review_event_summary, evaluate_web_search_egress

    result = evaluate_web_search_egress(
        f"Please search for {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "block",
            "dlp_review_destination": "safety_violations",
            "web_search_dlp_track_review_events": True,
        },
        context={"conversation_id": "conversation-1", "chat_type": "user"},
    )
    summary = build_dlp_review_event_summary(
        result,
        surface="web_search",
        context={"conversation_id": "conversation-1", "user_id": "user-1"},
    )

    assert summary["policy_type"] == "dlp_web_search"
    assert summary["violation_type"] == "dlp"
    assert summary["action"] == "block"
    assert summary["entity_counts"] == {"US_SSN": 1}
    assert "raw_matches" not in summary or summary["raw_matches"] is None
    assert RAW_VALUE not in repr(summary)


def test_upload_review_summary_has_distinct_type_and_no_raw_values():
    """Upload review payloads should be distinctly typed and counts-only."""
    print("Testing safe upload DLP review summary...")
    from functions_dlp import build_dlp_review_event_summary, evaluate_upload_content

    result = evaluate_upload_content(
        f"Document chunk has {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_upload_dlp": True,
            "upload_dlp_mode": "redact",
            "dlp_review_destination": "safety_violations",
            "upload_dlp_track_review_events": True,
        },
        context={"document_id": "doc-1", "workspace_scope": "group"},
    )
    summary = build_dlp_review_event_summary(
        result,
        surface="upload",
        context={"document_id": "doc-1", "workspace_scope": "group"},
    )

    assert summary["policy_type"] == "dlp_upload"
    assert summary["violation_type"] == "dlp"
    assert summary["action"] == "redact"
    assert summary["entity_counts"] == {"US_SSN": 1}
    assert RAW_VALUE not in repr(summary)


if __name__ == "__main__":
    tests = [
        test_review_destination_defaults_to_none,
        test_review_summary_has_dlp_type_and_no_raw_values,
        test_upload_review_summary_has_distinct_type_and_no_raw_values,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} DLP review event tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
