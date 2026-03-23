#!/usr/bin/env python3
# test_streaming_thought_finalization.py
"""
Functional test for streaming thought finalization fix.
Version: 0.239.116
Implemented in: 0.239.116

This test ensures the streaming client buffers split SSE events and prevents
late thought updates from replacing already-streamed assistant content.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMING_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'static', 'js', 'chat', 'chat-streaming.js'
)
THOUGHTS_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'static', 'js', 'chat', 'chat-thoughts.js'
)


def read_file_content(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_streaming_parser_buffers_split_sse_events():
    """Verify the streaming client buffers SSE frames across fetch chunks."""
    print('🔍 Testing buffered SSE parsing...')

    try:
        content = read_file_content(STREAMING_FILE)

        checks = {
            'parseSseEventPayload helper': 'function parseSseEventPayload(eventBlock)' in content,
            'stream buffer state': "let sseBuffer = ''" in content,
            'buffer processor': 'function processSseBuffer(flush = false)' in content,
            'stream chunk buffer append': "sseBuffer += decoder.decode(value, { stream: true }).replace(/\\r/g, '');" in content,
            'final decoder flush': 'sseBuffer += decoder.decode();' in content,
            'no naive chunk split': "const lines = chunk.split('\\n');" not in content,
            'incomplete stream guard': 'Stream ended before completion metadata was received.' in content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name}')
            if not passed:
                all_passed = False

        return all_passed

    except Exception as exc:
        print(f'  [FAIL] Exception: {exc}')
        return False


def test_late_thoughts_do_not_replace_streamed_content():
    """Verify thoughts stop overwriting the temp message after content starts."""
    print('\n🔍 Testing streaming thought overwrite guards...')

    try:
        streaming_content = read_file_content(STREAMING_FILE)
        thoughts_content = read_file_content(THOUGHTS_FILE)

        checks = {
            'content-start tracking': "messageElement.dataset.streamingHasContent = 'true';" in streaming_content,
            'thought guard before render': "if (!hasStreamedContent && !streamCompleted) {" in streaming_content,
            'thought module data guard': "if (messageElement.dataset.streamingHasContent === 'true') {" in thoughts_content,
            'thought module early return': 'return;' in thoughts_content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name}')
            if not passed:
                all_passed = False

        return all_passed

    except Exception as exc:
        print(f'  [FAIL] Exception: {exc}')
        return False


if __name__ == '__main__':
    tests = [
        test_streaming_parser_buffers_split_sse_events,
        test_late_thoughts_do_not_replace_streamed_content,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    passed = sum(1 for result in results if result)
    total = len(results)
    success = passed == total

    print(f'\n📊 Results: {passed}/{total} tests passed')
    sys.exit(0 if success else 1)