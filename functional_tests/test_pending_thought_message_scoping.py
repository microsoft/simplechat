#!/usr/bin/env python3
# test_pending_thought_message_scoping.py
"""
Functional test for pending thought message scoping.
Version: 0.239.185
Implemented in: 0.239.185

This test ensures the pending-thought polling path can be scoped to the active
assistant message so reconnect and fallback flows do not read thoughts from a
different in-flight reply.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THOUGHTS_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'functions_thoughts.py'
)
ROUTE_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'route_backend_thoughts.py'
)
CLIENT_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'static', 'js', 'chat', 'chat-thoughts.js'
)


def read_file_content(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_pending_thoughts_support_optional_message_id_scope():
    """Verify the backend query path supports an explicit message scope."""
    print('🔍 Testing pending thought backend message scoping...')

    thoughts_content = read_file_content(THOUGHTS_FILE)

    checks = {
        'optional message_id parameter': 'def get_pending_thoughts(conversation_id, user_id, message_id=None):' in thoughts_content,
        'query supports message filter': 'AND c.message_id = @msg_id ' in thoughts_content,
        'message filter parameter append': 'params.append({"name": "@msg_id", "value": message_id})' in thoughts_content,
        'message scoped branch': 'if message_id:' in thoughts_content,
        'legacy fallback branch preserved': 'latest_message_id = results[0].get(\'message_id\')' in thoughts_content,
    }

    all_passed = True
    for name, passed in checks.items():
        status = 'PASS' if passed else 'FAIL'
        print(f'  [{status}] {name}')
        if not passed:
            all_passed = False

    assert all_passed


def test_pending_thought_route_forwards_query_message_id():
    """Verify the route reads message_id from the query string and returns it."""
    print('\n🔍 Testing pending thought route query forwarding...')

    route_content = read_file_content(ROUTE_FILE)

    checks = {
        'route reads query string message_id': "message_id = request.args.get('message_id')" in route_content,
        'route forwards scoped query': 'get_pending_thoughts(conversation_id, user_id, message_id=message_id)' in route_content,
        'sanitized response includes message_id': "'message_id': t.get('message_id')" in route_content,
    }

    all_passed = True
    for name, passed in checks.items():
        status = 'PASS' if passed else 'FAIL'
        print(f'  [{status}] {name}')
        if not passed:
            all_passed = False

    assert all_passed


def test_pending_thought_client_builds_scoped_request_urls():
    """Verify the browser helper can request pending thoughts for one message."""
    print('\n🔍 Testing pending thought client URL construction...')

    client_content = read_file_content(CLIENT_FILE)

    checks = {
        'pending url helper exists': 'function buildPendingThoughtsUrl(conversationId, messageId = null)' in client_content,
        'query param name is message_id': "queryParams.set('message_id', messageId);" in client_content,
        'startThoughtPolling accepts message id': 'export function startThoughtPolling(conversationId, messageId = null)' in client_content,
        'startStreamingThoughtPolling accepts message id': 'export function startStreamingThoughtPolling(conversationId, messageId = null)' in client_content,
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
        test_pending_thoughts_support_optional_message_id_scope,
        test_pending_thought_route_forwards_query_message_id,
        test_pending_thought_client_builds_scoped_request_urls,
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