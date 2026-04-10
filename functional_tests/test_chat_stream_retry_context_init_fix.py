# test_chat_stream_retry_context_init_fix.py
"""
Functional test for streaming retry context initialization.
Version: 0.240.081
Implemented in: 0.240.080

This test ensures the streaming chat route initializes retry/edit context before
referencing retry state during assistant thread alignment, preventing NameError
failures on normal streamed chat messages.
"""

import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'CHAT_STREAM_RETRY_CONTEXT_INIT_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_stream_route_initializes_retry_context_before_use():
    """Verify chat_stream_api initializes retry state before assistant thread logic uses it."""
    print('🔍 Testing streaming retry context initialization...')

    route_source = read_file_text(ROUTE_FILE)
    stream_route_marker = "@app.route('/api/chat/stream', methods=['POST'])"
    stream_route_index = route_source.find(stream_route_marker)
    assert stream_route_index != -1, 'Expected to find the /api/chat/stream route definition.'

    stream_source = route_source[stream_route_index:]

    retry_assignment_index = stream_source.find("retry_user_message_id = data.get('retry_user_message_id') or data.get('edited_user_message_id')")
    retry_flag_index = stream_source.find('is_retry = bool(retry_user_message_id)')
    compatibility_mode_index = stream_source.find("compatibility_mode = bool(data.get('image_generation')) or is_retry")
    assistant_attempt_index = stream_source.find('assistant_thread_attempt = retry_thread_attempt if is_retry else 1')

    assert retry_assignment_index != -1, 'Expected stream route to initialize retry_user_message_id.'
    assert retry_flag_index != -1, 'Expected stream route to initialize is_retry.'
    assert compatibility_mode_index != -1, 'Expected compatibility_mode to reuse initialized is_retry.'
    assert assistant_attempt_index != -1, 'Expected assistant thread logic to reference initialized retry state.'
    assert retry_assignment_index < retry_flag_index < compatibility_mode_index < assistant_attempt_index

    print('✅ Streaming retry context initialization passed')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert read_config_version() == '0.240.081'
    assert 'Fixed/Implemented in version: **0.240.080**' in fix_doc_content
    assert 'Related config.py update: `VERSION = "0.240.081"`' in fix_doc_content
    assert 'is_retry' in fix_doc_content
    assert '/api/chat/stream' in fix_doc_content
    assert 'NameError' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_stream_route_initializes_retry_context_before_use,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)