#!/usr/bin/env python3
# test_streaming_thought_finalization.py
"""
Functional test for streaming thought rendering and finalization fixes.
Version: 0.239.185
Implemented in: 0.239.185

This test ensures the streaming client buffers split SSE events and prevents
late or stale thought updates from replacing already-streamed assistant content
or leaking across consecutive streaming responses.
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
PLUGIN_THOUGHTS_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'semantic_kernel_plugins', 'plugin_invocation_thoughts.py'
)
ROUTE_BACKEND_CHATS_FILE = os.path.join(
    ROOT_DIR,
    'application', 'single_app', 'route_backend_chats.py'
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

        assert all_passed

    except Exception as exc:
        print(f'  [FAIL] Exception: {exc}')
        raise


def test_late_thoughts_do_not_replace_streamed_content():
    """Verify thoughts stop overwriting the temp message after content starts."""
    print('\n🔍 Testing streaming thought overwrite guards...')

    try:
        streaming_content = read_file_content(STREAMING_FILE)
        thoughts_content = read_file_content(THOUGHTS_FILE)

        checks = {
            'content-start helper import': 'markStreamingThoughtContentStarted' in streaming_content,
            'content-start helper call': 'markStreamingThoughtContentStarted(messageId);' in streaming_content,
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

        assert all_passed

    except Exception as exc:
        print(f'  [FAIL] Exception: {exc}')
        raise


def test_streaming_thoughts_are_scoped_to_the_active_message():
    """Verify streaming thoughts target the current placeholder and include message identity."""
    print('\n🔍 Testing streaming thought message scoping...')

    try:
        streaming_content = read_file_content(STREAMING_FILE)
        thoughts_content = read_file_content(THOUGHTS_FILE)
        backend_content = read_file_content(ROUTE_BACKEND_CHATS_FILE)

        checks = {
            'streaming session starts with placeholder id': 'beginStreamingThoughtSession(tempAiMessageId);' in streaming_content,
            'sse thought handler receives placeholder id': 'handleStreamingThought(data, tempAiMessageId);' in streaming_content,
            'streaming path no longer starts pending-thought polling': 'startStreamingThoughtPolling(thoughtConversationId);' not in streaming_content,
            'thought renderer uses message helper': 'function getStreamingMessageElement(messageId)' in thoughts_content,
            'session reset helper': 'function resetStreamingPlaceholderState(messageElement)' in thoughts_content,
            'thought renderer tracks active backend message id': 'activeStreamingServerMessageId' in thoughts_content,
            'thought renderer ignores mismatched message ids': 'activeStreamingServerMessageId !== thoughtData.message_id' in thoughts_content,
            'thought renderer tracks dedupe signature': 'streamingThoughtSignature' in thoughts_content,
            'backend thought sse includes message id': "'message_id': assistant_message_id" in backend_content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name}')
            if not passed:
                all_passed = False

        assert all_passed

    except Exception as exc:
        print(f'  [FAIL] Exception: {exc}')
        raise


def test_plugin_invocation_thoughts_stream_live_during_agent_execution():
    """Verify plugin invocation callbacks can publish live SSE thought events."""
    print('\n🔍 Testing live plugin invocation thought emission...')

    try:
        route_content = read_file_content(ROUTE_BACKEND_CHATS_FILE)
        plugin_thoughts_content = read_file_content(PLUGIN_THOUGHTS_FILE)

        checks = {
            'callback helper supports live callback': 'live_thought_callback=None' in plugin_thoughts_content,
            'callback publishes live payload': "live_payload['step_index'] = thought_tracker.current_index - 1" in plugin_thoughts_content,
            'stream route defines background publisher': 'def publish_background_event(event_text):' in route_content,
            'stream route defines live plugin publisher': 'def publish_live_plugin_thought(thought_payload):' in route_content,
            'agent callback registers live publisher': 'live_thought_callback=publish_live_plugin_thought' in route_content,
            'completion replay removed': 'thought_tracker.current_index += 1' not in route_content,
        }

        all_passed = True
        for name, passed in checks.items():
            status = 'PASS' if passed else 'FAIL'
            print(f'  [{status}] {name}')
            if not passed:
                all_passed = False

        assert all_passed

    except Exception as exc:
        print(f'  [FAIL] Exception: {exc}')
        raise


if __name__ == '__main__':
    tests = [
        test_streaming_parser_buffers_split_sse_events,
        test_late_thoughts_do_not_replace_streamed_content,
        test_streaming_thoughts_are_scoped_to_the_active_message,
        test_plugin_invocation_thoughts_stream_live_during_agent_execution,
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