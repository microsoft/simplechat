# test_chat_stream_retry_multiendpoint_resolution_fix.py
#!/usr/bin/env python3
"""
Functional test for chat stream retry multi-endpoint resolution.
Version: 0.241.004
Implemented in: 0.241.003

This test ensures the compatibility retry path reuses the in-app multi-endpoint
resolver and Foundry fallback helpers instead of calling undefined script-only
functions during GPT initialization.
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
    'v0.241.003',
    'CHAT_STREAM_RETRY_MULTI_ENDPOINT_RESOLUTION_FIX.md',
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


def test_chat_api_uses_shared_multi_endpoint_resolution_for_retry_compatibility():
    """Verify compatibility chat requests reuse the in-app multi-endpoint resolver."""
    print('🔍 Testing compatibility retry multi-endpoint resolution wiring...')

    route_source = read_file_text(ROUTE_FILE)
    chat_route_marker = "@app.route('/api/chat', methods=['POST'])"
    chat_stream_marker = "@app.route('/api/chat/stream', methods=['POST'])"

    chat_route_index = route_source.find(chat_route_marker)
    chat_stream_index = route_source.find(chat_stream_marker)
    assert chat_route_index != -1, 'Expected to find the /api/chat route definition.'
    assert chat_stream_index != -1, 'Expected to find the /api/chat/stream route definition.'

    chat_api_source = route_source[chat_route_index:chat_stream_index]

    assert 'resolve_streaming_multi_endpoint_gpt_config(' in chat_api_source, (
        'Expected /api/chat to reuse the in-app multi-endpoint resolver.'
    )
    assert 'active_group_ids=active_group_ids' in chat_api_source, (
        'Expected /api/chat to pass validated group scope into multi-endpoint resolution.'
    )
    assert 'allow_default_selection=should_use_default_model' in chat_api_source, (
        'Expected /api/chat retry compatibility requests to keep default-model fallback wiring.'
    )
    assert 'resolve_default_model_gpt_config(settings)' not in chat_api_source, (
        'Expected /api/chat to stop calling the removed default-model helper.'
    )
    assert 'resolve_multi_endpoint_gpt_config(settings, data, enable_gpt_apim)' not in chat_api_source, (
        'Expected /api/chat to stop calling the undefined script-only multi-endpoint resolver.'
    )

    assert 'def get_foundry_api_version_candidates(' in route_source, (
        'Expected route_backend_chats.py to define Foundry API-version fallback candidates in-app.'
    )
    assert 'retry_client = build_streaming_multi_endpoint_client(' in route_source, (
        'Expected Foundry fallback retries to reuse the in-app multi-endpoint client builder.'
    )

    print('✅ Compatibility retry multi-endpoint resolution wiring passed')


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert parse_version(read_config_version()) >= (0, 241, 3)
    assert 'Fixed/Implemented in version: **0.241.003**' in fix_doc_content
    assert 'Related config.py update: `VERSION = "0.241.003"`' in fix_doc_content
    assert 'resolve_multi_endpoint_gpt_config' in fix_doc_content
    assert 'build_multi_endpoint_client' in fix_doc_content
    assert '/api/chat/stream' in fix_doc_content
    assert 'compatibility bridge' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')


if __name__ == '__main__':
    tests = [
        test_chat_api_uses_shared_multi_endpoint_resolution_for_retry_compatibility,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ {test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)