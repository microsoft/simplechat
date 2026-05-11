#!/usr/bin/env python3
# test_content_safety_thread_alignment.py
"""
Functional test for content safety message threading alignment.
Version: 0.240.076
Implemented in: 0.240.076

This test ensures blocked content-safety replies reuse the reserved response
message id, persist thread metadata, and finalize streamed placeholders as
threaded safety messages instead of temporally orphaned responses.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'route_backend_chats.py'
)
STREAMING_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'static', 'js', 'chat', 'chat-streaming.js'
)


def read_file_content(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_safety_messages_reuse_reserved_response_id():
    """Verify blocked safety messages persist with the reserved assistant id."""
    print('🔍 Testing content safety message id alignment...')

    route_content = read_file_content(ROUTE_FILE)

    checks = {
        'threaded safety helper exists': 'def _build_safety_message_doc(' in route_content,
        'blocked http response returns reserved id': "'message_id': assistant_message_id" in route_content,
        'safety doc builder called with reserved id': route_content.count('message_id=assistant_message_id,') >= 2,
        'blocked response exposes safety role': "'role': 'safety'" in route_content,
    }

    all_passed = True
    for name, passed in checks.items():
        status = 'PASS' if passed else 'FAIL'
        print(f'  [{status}] {name}')
        if not passed:
            all_passed = False

    assert all_passed


def test_safety_messages_persist_thread_metadata():
    """Verify blocked safety messages carry the active thread metadata."""
    print('\n🔍 Testing content safety thread metadata persistence...')

    route_content = read_file_content(ROUTE_FILE)

    checks = {
        'response context helper exists': 'def _load_user_message_response_context(' in route_content,
        'thread id copied from response context': "'thread_id': response_context.get('thread_id')" in route_content,
        'previous thread id copied from response context': "'previous_thread_id': response_context.get('previous_thread_id')" in route_content,
        'assistant thread attempt reused for safety': "'thread_attempt': assistant_thread_attempt" in route_content,
        'safety audit metadata stores reserved message id': "'message_id': assistant_message_id" in route_content,
    }

    all_passed = True
    for name, passed in checks.items():
        status = 'PASS' if passed else 'FAIL'
        print(f'  [{status}] {name}')
        if not passed:
            all_passed = False

    assert all_passed


def test_blocked_streams_finalize_as_safety_messages():
    """Verify streamed blocked replies complete with safety-role finalization."""
    print('\n🔍 Testing streamed blocked response finalization...')

    route_content = read_file_content(ROUTE_FILE)
    streaming_content = read_file_content(STREAMING_FILE)

    checks = {
        'blocked stream emits done payload': "'done': True" in route_content,
        'blocked stream emits full content': "'full_content': blocked_msg_content.strip()" in route_content,
        'blocked stream preserves user message id': "'user_message_id': user_message_id" in route_content,
        'stream finalizer handles safety sender': "const sender = finalData.role === 'safety' || finalData.blocked ? 'safety' : 'AI';" in streaming_content,
    }

    all_passed = True
    for name, passed in checks.items():
        status = 'PASS' if passed else 'FAIL'
        print(f'  [{status}] {name}')
        if not passed:
            all_passed = False

    assert all_passed


if __name__ == '__main__':
    tests = [
        test_safety_messages_reuse_reserved_response_id,
        test_safety_messages_persist_thread_metadata,
        test_blocked_streams_finalize_as_safety_messages,
    ]

    success = True
    passed = 0
    total = len(tests)

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            passed += 1
        except Exception:
            success = False
            import traceback

            traceback.print_exc()

    print(f'\n📊 Results: {passed}/{total} tests passed')
    sys.exit(0 if success else 1)