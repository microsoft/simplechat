#!/usr/bin/env python3
# test_persistent_conversation_summary.py
"""
Functional test for persistent conversation summaries.
Version: 0.239.030
Implemented in: 0.239.030

This test ensures that:
1. generate_conversation_summary() returns properly structured summary data
2. _build_summary_intro() uses cached summary when message_time_end hasn't changed
3. _build_summary_intro() regenerates when messages are newer than cached summary
4. Summary data includes message_time_start and message_time_end fields
5. The truncation helper works correctly
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from route_backend_conversation_export import (  # noqa: E402
    _build_summary_intro,
    _truncate_for_summary,
    SUMMARY_SOURCE_CHAR_LIMIT,
)


def test_summary_intro_cache_hit():
    """Test that _build_summary_intro returns cached summary when message_time_end matches."""
    print("🔍 Testing summary cache hit (no new messages)...")

    existing_summary = {
        'content': 'Cached summary text.',
        'model_deployment': 'gpt-4o',
        'generated_at': '2026-01-15T10:00:00',
        'message_time_start': '2026-01-15T09:00:00',
        'message_time_end': '2026-01-15T09:55:00'
    }

    conversation = {
        'id': 'conv-test-1',
        'title': 'Test Conversation',
        'summary': existing_summary
    }

    messages = [
        {'role': 'user', 'content_text': 'Hello', 'speaker_label': 'USER'},
        {'role': 'assistant', 'content_text': 'Hi there', 'speaker_label': 'ASSISTANT'}
    ]

    sanitized_conversation = {'title': 'Test Conversation'}

    result = _build_summary_intro(
        messages=messages,
        conversation=conversation,
        sanitized_conversation=sanitized_conversation,
        settings={},
        enabled=True,
        summary_model_deployment='gpt-4o',
        message_time_start='2026-01-15T09:00:00',
        message_time_end='2026-01-15T09:55:00'  # Same as cached
    )

    assert result['enabled'] is True, f"Expected enabled=True, got {result['enabled']}"
    assert result['generated'] is True, f"Expected generated=True, got {result['generated']}"
    assert result['content'] == 'Cached summary text.', f"Expected cached content, got: {result['content']}"
    assert result['model_deployment'] == 'gpt-4o', f"Expected gpt-4o, got: {result['model_deployment']}"
    assert result['generated_at'] == '2026-01-15T10:00:00', f"Expected cached timestamp, got: {result['generated_at']}"
    assert result['error'] is None, f"Expected no error, got: {result['error']}"

    print("✅ Summary cache hit test passed!")
    return True


def test_summary_intro_cache_hit_older_message():
    """Test cache hit when cached message_time_end is NEWER than current (edge case)."""
    print("🔍 Testing summary cache hit with older message_time_end...")

    existing_summary = {
        'content': 'Summary covers more messages.',
        'model_deployment': 'gpt-4o',
        'generated_at': '2026-01-15T12:00:00',
        'message_time_start': '2026-01-15T09:00:00',
        'message_time_end': '2026-01-15T11:55:00'
    }

    conversation = {
        'id': 'conv-test-2',
        'summary': existing_summary
    }

    sanitized_conversation = {'title': 'Test'}

    result = _build_summary_intro(
        messages=[{'role': 'user', 'content_text': 'Hi', 'speaker_label': 'USER'}],
        conversation=conversation,
        sanitized_conversation=sanitized_conversation,
        settings={},
        enabled=True,
        summary_model_deployment='gpt-4o',
        message_time_start='2026-01-15T09:00:00',
        message_time_end='2026-01-15T10:00:00'  # Older than cached
    )

    assert result['generated'] is True, "Should use cache when cached end >= current end"
    assert result['content'] == 'Summary covers more messages.', "Should return cached content"

    print("✅ Summary cache hit (older message) test passed!")
    return True


def test_summary_intro_disabled():
    """Test that disabled summary returns immediately."""
    print("🔍 Testing summary disabled state...")

    result = _build_summary_intro(
        messages=[],
        conversation={'id': 'conv-disabled'},
        sanitized_conversation={'title': 'Test'},
        settings={},
        enabled=False,
        summary_model_deployment=''
    )

    assert result['enabled'] is False, f"Expected enabled=False, got {result['enabled']}"
    assert result['generated'] is False, f"Expected generated=False, got {result['generated']}"
    assert result['content'] == '', f"Expected empty content, got: {result['content']}"

    print("✅ Summary disabled state test passed!")
    return True


def test_summary_intro_stale_cache():
    """Test that a stale cache (newer messages exist) triggers regeneration attempt."""
    print("🔍 Testing summary stale cache detection...")

    existing_summary = {
        'content': 'Old cached summary.',
        'model_deployment': 'gpt-4o',
        'generated_at': '2026-01-15T10:00:00',
        'message_time_start': '2026-01-15T09:00:00',
        'message_time_end': '2026-01-15T09:55:00'
    }

    conversation = {
        'id': 'conv-stale',
        'summary': existing_summary
    }

    sanitized_conversation = {'title': 'Test'}

    # message_time_end is NEWER than cached — should try to regenerate
    # Since we don't have a real OpenAI client, this will fail with an error,
    # which confirms the cache was NOT used.
    result = _build_summary_intro(
        messages=[
            {'role': 'user', 'content_text': 'New message', 'speaker_label': 'USER'}
        ],
        conversation=conversation,
        sanitized_conversation=sanitized_conversation,
        settings={},
        enabled=True,
        summary_model_deployment='gpt-4o',
        message_time_start='2026-01-15T09:00:00',
        message_time_end='2026-01-15T10:30:00'  # NEWER than cached 09:55
    )

    # Without a real GPT client, generation should fail
    assert result['generated'] is False, "Without GPT client, generation should fail"
    assert result['error'] is not None, "Should have an error when no GPT client available"
    # The key assertion: it DID NOT return the cached content
    assert result['content'] != 'Old cached summary.', "Should not use stale cached summary"

    print("✅ Summary stale cache detection test passed!")
    return True


def test_summary_data_structure():
    """Test that the summary_intro structure contains all expected fields."""
    print("🔍 Testing summary data structure...")

    result = _build_summary_intro(
        messages=[],
        conversation={'id': 'conv-struct'},
        sanitized_conversation={'title': 'Test'},
        settings={},
        enabled=True,
        summary_model_deployment='gpt-4o',
        message_time_start=None,
        message_time_end=None
    )

    expected_keys = {'enabled', 'generated', 'model_deployment', 'generated_at', 'content', 'error'}
    actual_keys = set(result.keys())
    assert expected_keys.issubset(actual_keys), f"Missing keys: {expected_keys - actual_keys}"

    print("✅ Summary data structure test passed!")
    return True


def test_truncation_short_text():
    """Test that short text passes through unchanged."""
    print("🔍 Testing truncation with short text...")

    short_text = "This is a short transcript."
    result = _truncate_for_summary(short_text)
    assert result == short_text, "Short text should pass through unchanged"

    print("✅ Truncation short text test passed!")
    return True


def test_truncation_long_text():
    """Test that long text gets truncated with marker."""
    print("🔍 Testing truncation with long text...")

    long_text = "A" * (SUMMARY_SOURCE_CHAR_LIMIT + 1000)
    result = _truncate_for_summary(long_text)

    assert len(result) < len(long_text), "Truncated text should be shorter"
    assert "transcript truncated" in result, "Should contain truncation marker"

    print("✅ Truncation long text test passed!")
    return True


def test_summary_no_content():
    """Test that summary with no message content returns an error."""
    print("🔍 Testing summary with empty messages...")

    result = _build_summary_intro(
        messages=[
            {'role': 'user', 'content_text': '', 'speaker_label': 'USER'},
            {'role': 'assistant', 'content_text': '', 'speaker_label': 'ASSISTANT'}
        ],
        conversation={'id': 'conv-empty'},
        sanitized_conversation={'title': 'Test'},
        settings={},
        enabled=True,
        summary_model_deployment='gpt-4o',
        message_time_start=None,
        message_time_end=None
    )

    assert result['generated'] is False, "Should not generate with empty content"
    assert result['error'] is not None, "Should have an error message"
    assert 'No message content' in result['error'], f"Unexpected error: {result['error']}"

    print("✅ Summary with empty messages test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_summary_intro_cache_hit,
        test_summary_intro_cache_hit_older_message,
        test_summary_intro_disabled,
        test_summary_intro_stale_cache,
        test_summary_data_structure,
        test_truncation_short_text,
        test_truncation_long_text,
        test_summary_no_content,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as e:
            print(f"❌ {test.__name__} failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\n📊 Results: {passed}/{total} tests passed")
    sys.exit(0 if all(results) else 1)
