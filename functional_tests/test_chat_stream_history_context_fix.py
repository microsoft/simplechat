# test_chat_stream_history_context_fix.py
#!/usr/bin/env python3
"""
Functional test for shared chat history context fix.
Version: 0.240.046
Implemented in: 0.240.046

This test ensures streaming and non-streaming chat paths share the same
history builder so older turns can be summarized instead of being dropped
when the recent message window is small, and that the selected history
context remains available for debugging without overloading the thoughts UI.
"""

import ast
import json
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_backend_chats.py")
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
THOUGHTS_JS = os.path.join(ROOT_DIR, "application", "single_app", "static", "js", "chat", "chat-thoughts.js")
MESSAGES_JS = os.path.join(ROOT_DIR, "application", "single_app", "static", "js", "chat", "chat-messages.js")
FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "CHAT_STREAM_HISTORY_CONTEXT_FIX.md",
)
TARGET_FUNCTIONS = {
    "remove_masked_content",
    "_format_history_message_ref",
    "_capture_history_refs",
    "_truncate_history_citation_text",
    "_serialize_history_citation_value",
    "_build_agent_citation_history_lines",
    "_build_document_citation_history_lines",
    "_build_web_citation_history_lines",
    "build_assistant_history_content_with_citations",
    "build_conversation_history_segments",
}


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def load_history_helpers():
    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        "json": json,
        "filter_assistant_artifact_items": lambda messages: list(messages),
        "build_message_artifact_payload_map": lambda messages: {},
        "hydrate_agent_citations_from_artifacts": lambda messages, artifact_payload_map: list(messages),
        "sort_messages_by_thread": lambda messages: list(messages),
        "debug_print": lambda *args, **kwargs: None,
    }
    exec(compile(module, ROUTE_FILE, "exec"), namespace)
    return namespace, source


class FakeSummaryMessage:
    def __init__(self, content):
        self.content = content


class FakeSummaryChoice:
    def __init__(self, content):
        self.message = FakeSummaryMessage(content)


class FakeSummaryResponse:
    def __init__(self, content):
        self.choices = [FakeSummaryChoice(content)]


class FakeChatCompletions:
    def __init__(self, summary_content):
        self.summary_content = summary_content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeSummaryResponse(self.summary_content)


class FakeGPTClient:
    def __init__(self, summary_content):
        self.chat = type("ChatNamespace", (), {})()
        self.chat.completions = FakeChatCompletions(summary_content)


def test_history_builder_summarizes_older_turns_when_recent_window_is_small():
    print("🔍 Testing shared history builder older-turn summarization...")

    namespace, _ = load_history_helpers()
    build_segments = namespace["build_conversation_history_segments"]
    fake_client = FakeGPTClient("Older context summary")

    all_messages = [
        {"id": "u1", "role": "user", "content": "How many discrete SharePoint sites appear in CCO locations?", "timestamp": "2026-04-03T10:00:00", "metadata": {}},
        {"id": "a1", "role": "assistant", "content": "There are 10 discrete SharePoint sites.", "timestamp": "2026-04-03T10:00:01", "metadata": {}},
        {"id": "u2", "role": "user", "content": "How many discrete SharePoint sites appear in CCO locations? please list them out", "timestamp": "2026-04-03T10:00:02", "metadata": {}},
        {"id": "a2", "role": "assistant", "content": "There are 2 discrete site locations from the Licensing sheet.", "timestamp": "2026-04-03T10:00:03", "metadata": {}},
        {"id": "u3", "role": "user", "content": "please list the locations out in a single table", "timestamp": "2026-04-03T10:00:04", "metadata": {}},
    ]

    result = build_segments(
        all_messages=all_messages,
        conversation_history_limit=2,
        enable_summarize_older_messages=True,
        gpt_client=fake_client,
        gpt_model="gpt-4o",
        user_message_id="u3",
        fallback_user_message="please list the locations out in a single table",
    )

    assert result["summary_of_older"] == "Older context summary"
    assert [msg["role"] for msg in result["history_messages"]] == ["assistant", "user"]
    assert result["history_messages"][0]["content"] == "There are 2 discrete site locations from the Licensing sheet."
    assert result["history_messages"][1]["content"] == "please list the locations out in a single table"
    assert len(fake_client.chat.completions.calls) == 1

    summary_prompt = fake_client.chat.completions.calls[0]["messages"][0]["content"]
    assert "There are 10 discrete SharePoint sites." in summary_prompt
    assert "please list the locations out in a single table" not in summary_prompt

    print("✅ Shared history builder older-turn summarization passed")
    return True


def test_history_builder_filters_inactive_and_masked_messages():
    print("🔍 Testing shared history builder filtering rules...")

    namespace, _ = load_history_helpers()
    build_segments = namespace["build_conversation_history_segments"]

    all_messages = [
        {
            "id": "a-inactive",
            "role": "assistant",
            "content": "inactive answer should not be reused",
            "timestamp": "2026-04-03T11:00:00",
            "metadata": {"thread_info": {"active_thread": False}},
        },
        {
            "id": "u-masked",
            "role": "user",
            "content": "AlphaSecretOmega",
            "timestamp": "2026-04-03T11:00:01",
            "metadata": {"masked_ranges": [{"start": 5, "end": 11}]},
        },
        {
            "id": "u-latest",
            "role": "user",
            "content": "latest follow-up",
            "timestamp": "2026-04-03T11:00:02",
            "metadata": {},
        },
    ]

    result = build_segments(
        all_messages=all_messages,
        conversation_history_limit=3,
        enable_summarize_older_messages=False,
        gpt_client=None,
        gpt_model=None,
        user_message_id="u-latest",
        fallback_user_message="latest follow-up",
    )

    contents = [message["content"] for message in result["history_messages"]]
    assert "inactive answer should not be reused" not in contents
    assert "AlphaOmega" in contents
    assert "AlphaSecretOmega" not in contents
    assert contents[-1] == "latest follow-up"

    print("✅ Shared history builder filtering rules passed")
    return True


def test_streaming_and_non_streaming_paths_share_history_builder():
    print("🔍 Testing shared history builder wiring...")

    _, route_source = load_history_helpers()
    assert route_source.count("history_segments = build_conversation_history_segments(") == 2
    assert "enable_summarize_content_history_beyond_conversation_history_limit = settings.get(" in route_source
    assert "msg.get('content', '').startswith('<Summary of previous conversation context>')" in route_source

    print("✅ Shared history builder wiring passed")
    return True


def test_history_builder_includes_prior_citation_results_for_follow_ups():
    print("🔍 Testing citation results are included in assistant history turns...")

    namespace, _ = load_history_helpers()
    build_segments = namespace["build_conversation_history_segments"]

    all_messages = [
        {
            "id": "u1",
            "role": "user",
            "content": "How many discrete SharePoint sites appear in CCO locations?",
            "timestamp": "2026-04-03T12:00:00",
            "metadata": {},
        },
        {
            "id": "a1",
            "role": "assistant",
            "content": "A total of 9 discrete SharePoint sites appear in CCO locations.",
            "timestamp": "2026-04-03T12:00:01",
            "metadata": {},
            "agent_citations": [
                {
                    "tool_name": "TabularProcessingPlugin.get_distinct_values [Legal]",
                    "function_arguments": {
                        "filename": "CCO-Legal File Plan 2025_Final Approved.xlsx",
                        "sheet_name": "Legal",
                        "column": "Location",
                    },
                    "function_result": {
                        "distinct_count": 8,
                        "values": [
                            "http://occtreasgovprod.sharepoint.com/sites/CCO/lawnotated",
                            "http://occtreasgovprod.sharepoint.com/sites/LCFrmwrk/Compliance%20Framework/Forms/Allltems.aspx",
                            "http://occtreasgovprod.sharepoint.com/sites/WDLD/Site",
                        ],
                    },
                    "success": True,
                },
                {
                    "tool_name": "TabularProcessingPlugin.get_distinct_values [Licensing]",
                    "function_arguments": {
                        "filename": "CCO-Licensing File Plan 2025_Final Approved.xlsx",
                        "sheet_name": "Licensing",
                        "column": "Location",
                    },
                    "function_result": {
                        "distinct_count": 1,
                        "values": [
                            "https://occtreasgovprod.sharepoint.com/sites/LIC",
                        ],
                    },
                    "success": True,
                },
            ],
        },
        {
            "id": "u2",
            "role": "user",
            "content": "please list them out",
            "timestamp": "2026-04-03T12:00:02",
            "metadata": {},
        },
    ]

    result = build_segments(
        all_messages=all_messages,
        conversation_history_limit=3,
        enable_summarize_older_messages=False,
        gpt_client=None,
        gpt_model=None,
        user_message_id="u2",
        fallback_user_message="please list them out",
    )

    assistant_turn = result["history_messages"][1]["content"]
    assert "Supporting citation context from this assistant turn" in assistant_turn
    assert "TabularProcessingPlugin.get_distinct_values [Legal]" in assistant_turn
    assert "https://occtreasgovprod.sharepoint.com/sites/LIC" in assistant_turn

    print("✅ Citation results are included in assistant history turns")
    return True


def test_history_context_diagnostics_are_exposed_in_backend_and_ui():
    print("🔍 Testing history context diagnostics visibility...")

    route_source = read_file_text(ROUTE_FILE)
    thoughts_source = read_file_text(THOUGHTS_JS)
    messages_source = read_file_text(MESSAGES_JS)

    assert "build_history_context_thought_content(history_debug_info)" in route_source
    assert "build_history_context_thought_detail(history_debug_info)" in route_source
    assert route_source.count("'history_context': history_debug_info") >= 3
    assert "build_history_context_debug_citation(history_debug_info, 'streaming')" in route_source
    assert "build_history_context_debug_citation(history_debug_info, 'standard')" in route_source

    assert "'history_context': 'bi-diagram-3'" in thoughts_source
    assert "t.detail != null && String(t.detail).trim()" not in thoughts_source
    assert "thought-detail" not in thoughts_source

    assert "History Context" in messages_source
    assert "selected_recent_message_refs" in messages_source
    assert "final_api_source_refs" in messages_source
    assert "renderHistoryContextSection" in messages_source

    print("✅ History context diagnostics visibility passed")
    return True


def test_version_and_fix_documentation_alignment():
    print("🔍 Testing version and fix documentation alignment...")

    version = read_config_version()
    fix_doc_content = read_file_text(FIX_DOC)

    assert version == "0.240.048", version
    assert "Fixed/Implemented in version: **0.240.048**" in fix_doc_content
    assert "build_conversation_history_segments" in fix_doc_content
    assert "history_context" in fix_doc_content
    assert "citation results" in fix_doc_content.lower()
    assert "application/single_app/route_backend_chats.py" in fix_doc_content

    print("✅ Version and fix documentation alignment passed")
    return True


if __name__ == "__main__":
    tests = [
        test_history_builder_summarizes_older_turns_when_recent_window_is_small,
        test_history_builder_filters_inactive_and_masked_messages,
        test_streaming_and_non_streaming_paths_share_history_builder,
        test_history_builder_includes_prior_citation_results_for_follow_ups,
        test_history_context_diagnostics_are_exposed_in_backend_and_ui,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)