#!/usr/bin/env python3
# test_chat_streaming_sse_metadata_fix.py
"""
Functional test for chat streaming SSE and metadata preservation fixes.
Version: 0.241.049
Implemented in: 0.241.049

This test ensures that streaming responses use real SSE delimiters, preserve
assistant metadata in the final client handoff, and avoid noisy missing-metadata
logging for temporary AI placeholders.
"""

import os
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_BACKEND_CHATS = os.path.join(REPO_ROOT, "application", "single_app", "route_backend_chats.py")
CHAT_STREAMING = os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "chat", "chat-streaming.js")
CHAT_MESSAGES = os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "chat", "chat-messages.js")


def _read(path):
    with open(path, encoding="utf-8") as file_handle:
        return file_handle.read()


def test_agent_stream_uses_real_sse_delimiters():
    """The agent streaming branch must not emit literal backslash delimiters."""
    print("Testing agent streaming SSE delimiter handling...")
    content = _read(ROUTE_BACKEND_CHATS)
    errors = []

    bad_snippet = 'yield f"data: {json.dumps({\'content\': chunk_content})}\\\\n\\\\n"'
    if bad_snippet in content:
        errors.append("Found literal \\n\\n SSE delimiters in the agent chunk streaming branch.")

    required_snippet = "'metadata': assistant_doc.get('metadata', {})"
    if required_snippet not in content:
        errors.append("Final streaming payload does not include assistant metadata.")

    required_safety_snippet = "'metadata': safety_doc.get('metadata', {})"
    if required_safety_snippet not in content:
        errors.append("Blocked safety streaming payload does not include safety metadata.")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        return False

    print("  SSE delimiter and metadata payload checks passed.")
    return True


def test_streaming_client_preserves_final_message_object():
    """The client finalize path must reuse the final SSE payload as the message object."""
    print("Testing streaming client final-message handoff...")
    content = _read(CHAT_STREAMING)
    errors = []

    if "function normalizeLegacyEscapedSseDelimiters(chunk)" not in content:
        errors.append("Legacy SSE delimiter normalization helper is missing from chat-streaming.js.")

    if "const finalMessageObject = {" not in content:
        errors.append("Streaming finalization does not build a reusable finalMessageObject.")

    append_call_count = content.count("        finalMessageObject,")
    if append_call_count < 2:
        errors.append("Expected streamed final message rendering to pass finalMessageObject into appendMessage for both image and AI paths.")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        return False

    print("  Streaming client handoff checks passed.")
    return True


def test_ai_placeholder_logging_is_quiet():
    """Temporary AI placeholders should not emit noisy missing-metadata logs."""
    print("Testing AI placeholder logging noise reduction...")
    content = _read(CHAT_MESSAGES)
    errors = []

    if "No metadata found for AI message" in content:
        errors.append("chat-messages.js still logs missing metadata for AI messages.")

    if errors:
        for error in errors:
            print(f"  FAIL: {error}")
        return False

    print("  AI placeholder logging checks passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_agent_stream_uses_real_sse_delimiters,
        test_streaming_client_preserves_final_message_object,
        test_ai_placeholder_logging_is_quiet,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print('=' * 60)
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    print('=' * 60)
    sys.exit(0 if all(results) else 1)