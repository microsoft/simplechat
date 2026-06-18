# test_web_search_dlp_route_integration.py
#!/usr/bin/env python3
"""
Functional test for web-search DLP route integration.
Version: 0.242.073
Implemented in: 0.242.073

This test ensures chat routes evaluate DLP before Foundry web search, suppress
Foundry calls on block, and send only the redacted query on redact.
"""

import os
import sys
from pathlib import Path


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
ROUTE_FILE = os.path.join(APP_DIR, "route_backend_chats.py")
ROUTE_BACKEND_CHATS = Path(ROUTE_FILE)


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def web_search_dlp_blocks(source_text):
    marker = "web_search_dlp_result = evaluate_web_search_egress("
    blocks = []
    start = 0
    while True:
        marker_index = source_text.find(marker, start)
        if marker_index == -1:
            break
        perform_index = source_text.find("perform_web_search(", marker_index)
        if perform_index == -1:
            raise AssertionError("Found DLP evaluation without a later perform_web_search call")
        block_start = source_text.rfind("if web_search_enabled:", 0, marker_index)
        block_end = source_text.find(")", perform_index)
        blocks.append(source_text[block_start:block_end])
        start = perform_index + len("perform_web_search(")
    return blocks


def extract_top_level_function_source(source_text, function_name):
    marker = f"def {function_name}("
    start = source_text.find(marker)
    if start == -1:
        raise AssertionError(f"Function {function_name} not found")

    next_function = source_text.find("\ndef ", start + len(marker))
    if next_function == -1:
        return source_text[start:]
    return source_text[start:next_function]


def test_dlp_guard_exists_in_both_chat_paths():
    """Both streaming and non-streaming routes should have a DLP-guarded web-search block."""
    print("Testing web-search DLP guarded blocks...")
    source = read_file_text(ROUTE_FILE)
    blocks = web_search_dlp_blocks(source)

    assert len(blocks) == 2, f"Expected two web-search DLP route blocks, found {len(blocks)}"


def test_blocked_dlp_result_suppresses_foundry_call():
    """Blocked DLP decisions should append a safe system message instead of calling Foundry."""
    print("Testing blocked DLP route behavior...")
    source = read_file_text(ROUTE_FILE)

    for block in web_search_dlp_blocks(source):
        dlp_index = block.find("web_search_dlp_result = evaluate_web_search_egress(")
        block_decision_index = block.find('if not web_search_dlp_result.get("web_search_allowed", True):')
        blocked_status_index = block.find("WEB_SEARCH_DLP_BLOCKED_STATUS")
        else_index = block.find("else:", block_decision_index)
        perform_index = block.find("perform_web_search(")

        assert dlp_index != -1
        assert block_decision_index > dlp_index
        assert blocked_status_index > block_decision_index
        assert else_index > blocked_status_index
        assert perform_index > else_index, "Foundry web search must stay in the allowed else branch"


def test_redacted_query_is_forwarded_to_foundry():
    """Allowed/redacted DLP decisions should replace the query before Foundry invocation."""
    print("Testing redacted query forwarding...")
    source = read_file_text(ROUTE_FILE)

    expected_assignment = (
        'web_search_query_text = web_search_dlp_result.get("web_search_query_text", web_search_query_text)'
    )
    for block in web_search_dlp_blocks(source):
        assignment_index = block.find(expected_assignment)
        perform_index = block.find("perform_web_search(")
        query_argument_index = block.find("web_search_query_text=web_search_query_text", perform_index)

        assert assignment_index != -1, "Route must replace raw query with DLP-safe query"
        assert perform_index > assignment_index, "Foundry call must occur after DLP-safe query assignment"
        assert query_argument_index > perform_index, "Foundry call must receive the DLP-safe query variable"


def test_route_emits_counts_only_dlp_telemetry():
    """Route telemetry should use the shared counts-only telemetry builder."""
    print("Testing route DLP telemetry integration...")
    source = read_file_text(ROUTE_FILE)

    for block in web_search_dlp_blocks(source):
        assert "should_emit_dlp_telemetry(web_search_dlp_result, settings)" in block
        assert "build_dlp_telemetry_properties(" in block
        assert 'surface="web_search"' in block
        assert "raw_matches" not in block


def test_perform_web_search_does_not_fallback_to_raw_user_message():
    source = ROUTE_BACKEND_CHATS.read_text(encoding="utf-8")
    perform_source = extract_top_level_function_source(source, "perform_web_search")

    assert "web_search_query_text or user_message" not in perform_source
    assert "query_text = (web_search_query_text or \"\").strip()" in perform_source


if __name__ == "__main__":
    tests = [
        test_dlp_guard_exists_in_both_chat_paths,
        test_blocked_dlp_result_suppresses_foundry_call,
        test_redacted_query_is_forwarded_to_foundry,
        test_route_emits_counts_only_dlp_telemetry,
        test_perform_web_search_does_not_fallback_to_raw_user_message,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} web-search DLP route integration tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
