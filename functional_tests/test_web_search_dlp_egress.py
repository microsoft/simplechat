# test_web_search_dlp_egress.py
#!/usr/bin/env python3
"""
Functional test for web-search DLP egress.
Version: 0.242.074
Implemented in: 0.242.073

This test ensures web-search DLP runs after current-message query construction
and before Foundry web-search execution, blocks sensitive egress, redacts when
configured, and avoids raw query debug logging when DLP is enabled.
"""

import ast
import os
import sys
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
ROUTE_FILE = os.path.join(APP_DIR, "route_backend_chats.py")
sys.path.insert(0, APP_DIR)


RAW_VALUE = "123-45-6789"


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text, filename=ROUTE_FILE)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f"Function {function_name} not found")


def test_route_imports_and_calls_dlp_before_web_search():
    """Both chat paths should evaluate DLP before perform_web_search."""
    print("Testing web-search DLP call ordering...")
    source = read_file_text(ROUTE_FILE)

    assert "from functions_dlp import evaluate_web_search_egress" in source
    assert source.count("evaluate_web_search_egress(") >= 2

    non_stream_slice = source[source.find("web_search_query_text = build_web_search_query_text(user_message)"):]
    non_stream_slice = non_stream_slice[:non_stream_slice.find("perform_web_search(") + len("perform_web_search(")]
    assert "evaluate_web_search_egress(" in non_stream_slice

    streaming_start = source.find("def chat_stream_api")
    streaming_source = source[streaming_start:]
    streaming_slice = streaming_source[
        streaming_source.find("web_search_query_text = build_web_search_query_text(user_message)") :
    ]
    streaming_slice = streaming_slice[:streaming_slice.find("perform_web_search(") + len("perform_web_search(")]
    assert "evaluate_web_search_egress(" in streaming_slice


def test_dlp_helper_blocks_or_redacts_web_search_text():
    """DLP helper should block or redact web-search egress text."""
    print("Testing web-search DLP helper behavior...")
    from functions_dlp import evaluate_web_search_egress

    block_result = evaluate_web_search_egress(
        f"Search the web for employee SSN {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "block",
        },
        context={"chat_type": "user"},
    )
    redact_result = evaluate_web_search_egress(
        f"Search the web for employee SSN {RAW_VALUE}",
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "redact",
        },
        context={"chat_type": "user"},
    )

    assert block_result["decision"] == "block"
    assert block_result["web_search_allowed"] is False
    assert block_result["status_message"] == (
        "Web search was blocked because the message appears to contain non-public information."
    )
    assert redact_result["decision"] == "redact"
    assert redact_result["web_search_allowed"] is True
    assert "[REDACTED_US_SSN]" in redact_result["web_search_query_text"]
    assert RAW_VALUE not in redact_result["web_search_query_text"]
    assert redact_result["status_message"] == "Sensitive details were removed before web search."


def test_custom_regex_rule_can_redact_web_search_in_redact_mode():
    """Custom regex rules can redact web search when a high-confidence policy rule matches."""
    print("Testing custom regex rule web-search behavior...")
    from functions_dlp import evaluate_web_search_egress

    result = evaluate_web_search_egress(
        "Search employee EID-123456",
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "redact",
            "dlp_regex_rules": [
                {
                    "id": "employee_id",
                    "label": "Employee ID",
                    "entity_type": "EMPLOYEE_ID",
                    "enabled": True,
                    "pattern": r"EID-\d{6}",
                    "replacement": "[REDACTED_EMPLOYEE_ID]",
                    "surfaces": ["web_search"],
                    "flags": [],
                    "validator": "none",
                    "confidence": {
                        "regex_only": "low",
                        "with_keywords": "high",
                        "keywords": ["employee"],
                        "window_chars": 32,
                        "minimum": "high"
                    }
                }
            ],
        },
        context={"chat_type": "user"},
    )

    assert result["decision"] == "redact"
    assert result["web_search_allowed"] is True
    assert result["web_search_query_text"] == "Search employee [REDACTED_EMPLOYEE_ID]"
    assert "EID-123456" not in repr(result)


def test_scanner_error_fails_closed_by_default():
    """Scanner errors must not allow web-search egress by default."""
    import functions_dlp

    def fail_scan(text, settings, surface="generic"):
        raise RuntimeError("scanner unavailable")

    with patch.object(functions_dlp, "_apply_regex_engine", fail_scan):
        result = functions_dlp.evaluate_dlp_text(
            "send 123-45-6789 to web",
            settings={
                "enable_dlp_control_plane": True,
                "enable_web_search_dlp": True,
                "web_search_dlp_mode": "redact",
                "dlp_default_engine": "regex",
            },
            surface="web_search",
        )
        egress_result = functions_dlp.evaluate_web_search_egress(
            "send 123-45-6789 to web",
            settings={
                "enable_dlp_control_plane": True,
                "enable_web_search_dlp": True,
                "web_search_dlp_mode": "redact",
                "dlp_default_engine": "regex",
            },
            context={"chat_type": "user"},
        )

    assert result["scanner_status"] == "error"
    assert egress_result["web_search_allowed"] is False
    assert egress_result["web_search_query_text"] == ""
    assert "123-45-6789" not in repr(egress_result)
    assert result["decision"] == "block"
    assert result["text"] == ""


def test_blocked_status_continues_normal_chat_without_foundry_web_search():
    """Route source should add safe augmentation instead of calling web search when blocked."""
    print("Testing blocked web-search safe augmentation...")
    source = read_file_text(ROUTE_FILE)
    assert "Web search was blocked because the message appears to contain non-public information." in source
    assert "Sensitive details were removed before web search." in source
    assert "web_search_allowed" in source


def test_perform_web_search_debug_logging_masks_dlp_queries():
    """perform_web_search should avoid raw query/result debug logging when DLP is enabled."""
    print("Testing web-search debug logging safety...")
    source = read_file_text(ROUTE_FILE)
    perform_source = extract_function_source(source, "perform_web_search")
    citation_source = extract_function_source(source, "_extract_web_search_citations_from_content")

    forbidden = [
        "web_search_query_text[:100]",
        "user_message[:100]",
        "query_text[:100]",
        "result.message[:500]",
        "json.dumps(cit",
        "json.dumps(citation",
        "metadata_payload",
        "Metadata: {result.metadata}",
        "'search_query': query_text",
        '"search_query": query_text',
        "Adding agent citation with title",
        "Foundry agent invocation failed: {exc}",
        "Unexpected error invoking Foundry agent: {exc}",
        "Web search failed with error: {exc}",
        "Web search failed with an unexpected error: {exc}",
        "exceptionTraceback=True",
        "Failed to log web search token usage: {log_error}",
    ]
    for snippet in forbidden:
        assert snippet not in perform_source, f"Unsafe debug logging remains: {snippet}"

    assert "Extracting citations from:\\n{content}" not in citation_source
    assert " - {citations}" not in citation_source
    assert "dlp" in perform_source.lower()
    assert "query_length" in perform_source or "text_length" in perform_source
    assert "search_query_length" in perform_source


def test_deep_research_planned_queries_are_rechecked_before_web_search():
    """Deep Research planner output should be DLP-checked before Foundry web search."""
    print("Testing Deep Research planned query DLP enforcement...")
    source = read_file_text(ROUTE_FILE)
    function_source = extract_function_source(source, "perform_research_web_searches")

    recorded = {"planner_user_message": None, "queries": []}

    def fake_build_deep_research_query_plan(**kwargs):
        recorded["planner_user_message"] = kwargs.get("user_message")
        return {
            "queries": [
                {
                    "query": f"Find records for employee SSN {RAW_VALUE}",
                    "reason": "planner included sensitive source text",
                    "source": "planner",
                }
            ]
        }

    def fake_perform_web_search(**kwargs):
        recorded["queries"].append(kwargs["web_search_query_text"])

    from functions_dlp import evaluate_web_search_egress

    namespace = {
        "build_deep_research_query_plan": fake_build_deep_research_query_plan,
        "perform_web_search": fake_perform_web_search,
        "evaluate_web_search_egress": evaluate_web_search_egress,
        "should_emit_dlp_telemetry": lambda *args, **kwargs: False,
        "log_event": lambda *args, **kwargs: None,
        "build_dlp_telemetry_properties": lambda *args, **kwargs: {},
        "WEB_SEARCH_DLP_BLOCKED_STATUS": (
            "Web search was blocked because the message appears to contain non-public information."
        ),
    }
    exec(compile(function_source, ROUTE_FILE, "exec"), namespace)

    namespace["perform_research_web_searches"](
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "redact",
            "dlp_default_engine": "regex",
        },
        conversation_id="conv-1",
        user_id="user-1",
        user_message=f"Search for employee SSN {RAW_VALUE}",
        user_message_id="msg-1",
        chat_type="user",
        document_scope="personal",
        active_group_id=None,
        active_public_workspace_id=None,
        web_search_query_text="Search for employee SSN [REDACTED_US_SSN]",
        system_messages_for_augmentation=[],
        agent_citations_list=[],
        web_search_citations_list=[],
        deep_research_enabled=True,
        deep_research_planner_client=object(),
        deep_research_planner_model="planner",
    )

    assert RAW_VALUE not in recorded["planner_user_message"]
    assert recorded["queries"] == ["Find records for employee SSN [REDACTED_US_SSN]"]
    assert RAW_VALUE not in repr(recorded)


def test_deep_research_blocked_planned_queries_do_not_call_web_search():
    """Deep Research should skip planner queries when the per-query DLP check blocks."""
    print("Testing Deep Research planned query block enforcement...")
    source = read_file_text(ROUTE_FILE)
    function_source = extract_function_source(source, "perform_research_web_searches")

    recorded_queries = []
    system_messages = []

    def fake_build_deep_research_query_plan(**kwargs):
        return {
            "queries": [
                {
                    "query": f"Find records for employee SSN {RAW_VALUE}",
                    "reason": "planner included sensitive source text",
                    "source": "planner",
                }
            ]
        }

    def fake_perform_web_search(**kwargs):
        recorded_queries.append(kwargs["web_search_query_text"])

    from functions_dlp import evaluate_web_search_egress

    namespace = {
        "build_deep_research_query_plan": fake_build_deep_research_query_plan,
        "perform_web_search": fake_perform_web_search,
        "evaluate_web_search_egress": evaluate_web_search_egress,
        "should_emit_dlp_telemetry": lambda *args, **kwargs: False,
        "log_event": lambda *args, **kwargs: None,
        "build_dlp_telemetry_properties": lambda *args, **kwargs: {},
        "WEB_SEARCH_DLP_BLOCKED_STATUS": (
            "Web search was blocked because the message appears to contain non-public information."
        ),
    }
    exec(compile(function_source, ROUTE_FILE, "exec"), namespace)

    result = namespace["perform_research_web_searches"](
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "block",
            "dlp_default_engine": "regex",
        },
        conversation_id="conv-1",
        user_id="user-1",
        user_message="Search for employee SSN [REDACTED_US_SSN]",
        user_message_id="msg-1",
        chat_type="user",
        document_scope="personal",
        active_group_id=None,
        active_public_workspace_id=None,
        web_search_query_text="Search for employee SSN [REDACTED_US_SSN]",
        system_messages_for_augmentation=system_messages,
        agent_citations_list=[],
        web_search_citations_list=[],
        deep_research_enabled=True,
        deep_research_planner_client=object(),
        deep_research_planner_model="planner",
    )

    assert recorded_queries == []
    assert result["web_search_runs"] == []
    assert system_messages == [{"role": "system", "content": namespace["WEB_SEARCH_DLP_BLOCKED_STATUS"]}]
    assert RAW_VALUE not in repr(result)
    assert RAW_VALUE not in repr(system_messages)


def test_token_usage_extraction_logs_metadata_shape_only():
    """Token usage validation should not log raw provider usage metadata."""
    print("Testing web-search token usage extraction log safety...")
    source = read_file_text(ROUTE_FILE)
    token_source = extract_function_source(source, "_extract_token_usage_from_metadata")

    assert "usage={usage}" not in token_source
    assert "usage_keys={list(usage.keys())}" in token_source


if __name__ == "__main__":
    tests = [
        test_route_imports_and_calls_dlp_before_web_search,
        test_dlp_helper_blocks_or_redacts_web_search_text,
        test_custom_regex_rule_can_redact_web_search_in_redact_mode,
        test_scanner_error_fails_closed_by_default,
        test_blocked_status_continues_normal_chat_without_foundry_web_search,
        test_perform_web_search_debug_logging_masks_dlp_queries,
        test_deep_research_planned_queries_are_rechecked_before_web_search,
        test_deep_research_blocked_planned_queries_do_not_call_web_search,
        test_token_usage_extraction_logs_metadata_shape_only,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} web-search DLP egress tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
