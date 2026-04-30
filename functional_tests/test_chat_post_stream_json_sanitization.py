#!/usr/bin/env python3
# test_chat_post_stream_json_sanitization.py
"""
Functional test for chat post-stream JSON sanitization.
Version: 0.240.063
Implemented in: 0.240.063

This test ensures that post-stream assistant persistence sanitizes non-finite
citation values before artifact storage, Cosmos message writes, and terminal
chat payload emission.
"""

import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.append(str(APP_ROOT))

from functions_message_artifacts import build_agent_citation_artifact_documents, make_json_serializable


ROUTE_FILE = APP_ROOT / "route_backend_chats.py"
CONFIG_FILE = APP_ROOT / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "CHAT_STREAM_POST_FINALIZATION_JSON_SANITIZATION_FIX.md"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_non_finite_values_are_sanitized() -> None:
    payload = {
        "score": math.nan,
        "nested": {
            "values": [math.inf, -math.inf, 1.5],
        },
    }

    sanitized = make_json_serializable(payload)

    assert sanitized["score"] is None, "Top-level NaN should be converted to None"
    assert sanitized["nested"]["values"][0] is None, "Positive infinity should be converted to None"
    assert sanitized["nested"]["values"][1] is None, "Negative infinity should be converted to None"
    assert sanitized["nested"]["values"][2] == 1.5, "Finite values should be preserved"


def test_artifact_payload_json_has_no_nan_tokens() -> None:
    citations = [{
        "tool_name": "TabularProcessingPlugin.lookup_value",
        "function_name": "lookup_value",
        "plugin_name": "TabularProcessingPlugin",
        "function_arguments": {"filename": "records.xlsx", "score": math.nan},
        "function_result": {"score": math.inf, "values": [1, math.nan]},
        "success": True,
    }]

    compact_citations, artifact_docs = build_agent_citation_artifact_documents(
        conversation_id="conversation-1",
        assistant_message_id="assistant-1",
        agent_citations=citations,
        created_timestamp="2026-04-07T00:00:00Z",
        user_info={"userId": "user-1"},
    )

    serialized_payload = artifact_docs[0]["content"]
    assert "NaN" not in serialized_payload, "Artifact JSON should not contain NaN literals"
    assert "Infinity" not in serialized_payload, "Artifact JSON should not contain Infinity literals"

    parsed_payload = json.loads(serialized_payload)
    parsed_citation = parsed_payload["citation"]
    assert parsed_citation["function_arguments"]["score"] is None
    assert parsed_citation["function_result"]["score"] is None
    assert parsed_citation["function_result"]["values"][1] is None
    assert compact_citations[0]["function_result"]["values"][1] is None


def test_chat_routes_use_shared_serializer() -> None:
    route_content = ROUTE_FILE.read_text(encoding="utf-8")

    required_markers = [
        "make_json_serializable,",
        "assistant_doc = make_json_serializable({",
        "final_data = make_json_serializable({",
        "return jsonify(make_json_serializable({",
        "return make_json_serializable({",
    ]

    missing_markers = [marker for marker in required_markers if marker not in route_content]
    if missing_markers:
        raise AssertionError(f"Missing route sanitization markers: {missing_markers}")


def test_version_and_fix_doc() -> None:
    assert_contains(CONFIG_FILE, 'VERSION = "0.240.063"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.240.063**")


def run_tests() -> None:
    print("Testing chat post-stream JSON sanitization...")
    test_non_finite_values_are_sanitized()
    test_artifact_payload_json_has_no_nan_tokens()
    test_chat_routes_use_shared_serializer()
    test_version_and_fix_doc()
    print("Chat post-stream JSON sanitization checks passed!")


if __name__ == "__main__":
    try:
        run_tests()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)