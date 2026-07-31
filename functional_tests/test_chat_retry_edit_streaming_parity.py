# test_chat_retry_edit_streaming_parity.py
#!/usr/bin/env python3
"""
Functional test for retry and edit streaming parity.
Version: 0.250.106
Implemented in: 0.250.106

This test ensures retry and edit chat requests use the same full SSE stream
generator as first-send chat instead of the legacy terminal compatibility
bridge, while still reusing the prepared retry/edit user message.
"""

import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
RETRY_JS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-retry.js')
EDIT_JS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-edit.js')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'CHAT_RETRY_EDIT_STREAMING_PARITY_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def parse_version(version_text):
    return tuple(int(part) for part in str(version_text).split('.'))


def get_chat_stream_route_source():
    route_source = read_file_text(ROUTE_FILE)
    stream_route_marker = "@bp.route('/api/chat/stream', methods=['POST'])"
    cancel_route_marker = "@bp.route('/api/chat/stream/cancel/<conversation_id>', methods=['POST'])"
    stream_route_index = route_source.find(stream_route_marker)
    cancel_route_index = route_source.find(cancel_route_marker, stream_route_index)

    assert stream_route_index != -1, 'Expected to find the /api/chat/stream route definition.'
    assert cancel_route_index != -1, 'Expected to find the stream cancel route after /api/chat/stream.'
    return route_source[stream_route_index:cancel_route_index]


def test_retry_and_edit_are_not_stream_compatibility_mode():
    """Verify retry/edit requests are not diverted away from the full stream generator."""
    print('Testing retry/edit streaming route selection...')

    stream_source = get_chat_stream_route_source()
    retry_flag_index = stream_source.find('is_retry = bool(retry_user_message_id)')
    compatibility_mode_index = stream_source.find("compatibility_mode = bool(data.get('image_generation'))")
    compatibility_bridge_index = stream_source.find('if compatibility_mode:')
    generator_index = stream_source.find('def generate(publish_background_event=None):')
    retry_reuse_index = stream_source.find('if is_retry:', generator_index)

    assert retry_flag_index != -1, 'Expected stream route to detect retry/edit requests.'
    assert compatibility_mode_index != -1, 'Expected compatibility mode to be calculated.'
    assert compatibility_bridge_index != -1, 'Expected image compatibility bridge branch to remain.'
    assert generator_index != -1, 'Expected full stream generator to remain.'
    assert retry_reuse_index != -1, 'Expected retry/edit reuse logic inside the full stream generator.'
    assert "compatibility_mode = bool(data.get('image_generation')) or is_retry" not in stream_source
    assert retry_flag_index < compatibility_mode_index < compatibility_bridge_index < generator_index < retry_reuse_index

    print('Retry/edit route selection passed')


def test_stream_generator_reuses_prepared_retry_edit_user_message():
    """Verify the stream generator reuses the retry/edit message created by preparation routes."""
    print('Testing retry/edit stream message reuse...')

    stream_source = get_chat_stream_route_source()
    generator_index = stream_source.find('def generate(publish_background_event=None):')
    retry_reuse_index = stream_source.find('if is_retry:', generator_index)
    assistant_tracking_index = stream_source.find(
        'assistant_message_id, thought_tracker, assistant_thread_attempt, response_message_context = _initialize_assistant_response_tracking',
        retry_reuse_index,
    )
    retry_reuse_source = stream_source[retry_reuse_index:assistant_tracking_index]

    assert "user_message_id = retry_user_message_id" in retry_reuse_source
    assert 'cosmos_messages_container.read_item(' in retry_reuse_source
    assert 'item=user_message_id' in retry_reuse_source
    assert "data['message'] = user_message" in retry_reuse_source
    assert 'Retry thread metadata mismatch' in retry_reuse_source
    assert 'current_user_thread_id = requested_thread_id or stored_thread_id' in retry_reuse_source
    assert 'effective_retry_thread_attempt = (' in retry_reuse_source
    assert 'retry_thread_attempt=effective_retry_thread_attempt' in stream_source
    assert 'Reusing retry/edit user message' in retry_reuse_source

    print('Retry/edit stream message reuse passed')


def test_retry_and_edit_frontend_use_shared_streaming_client():
    """Verify retry and edit UI paths continue to call the shared streaming client."""
    print('Testing retry/edit frontend streaming calls...')

    retry_source = read_file_text(RETRY_JS_FILE)
    edit_source = read_file_text(EDIT_JS_FILE)

    assert "import { sendMessageWithStreaming } from './chat-streaming.js';" in retry_source
    assert "import { sendMessageWithStreaming } from './chat-streaming.js';" in edit_source
    assert "fetch(`/api/message/${messageId}/retry`" in retry_source
    assert "fetch(`/api/message/${messageId}/edit`" in edit_source
    assert 'sendMessageWithStreaming(' in retry_source
    assert 'sendMessageWithStreaming(' in edit_source

    print('Retry/edit frontend streaming calls passed')


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert parse_version(read_config_version()) >= (0, 250, 106)
    assert 'Fixed/Implemented in version: **0.250.106**' in fix_doc_content
    assert 'Related config.py update: `VERSION = "0.250.106"`' in fix_doc_content
    assert 'microsoft/simplechat#963' in fix_doc_content
    assert '/api/chat/stream' in fix_doc_content
    assert 'compatibility bridge' in fix_doc_content

    print('Version and fix documentation alignment passed')


if __name__ == '__main__':
    tests = [
        test_retry_and_edit_are_not_stream_compatibility_mode,
        test_stream_generator_reuses_prepared_retry_edit_user_message,
        test_retry_and_edit_frontend_use_shared_streaming_client,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'{test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)
