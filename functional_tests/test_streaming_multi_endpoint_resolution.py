# test_streaming_multi_endpoint_resolution.py
#!/usr/bin/env python3
"""
Functional test for streaming multi-endpoint model resolution.
Version: 0.239.200
Implemented in: 0.239.200

This test ensures streaming requests resolve selected models by endpoint and
model identifiers, hydrate saved endpoint auth, and build provider-aware
clients for Azure OpenAI and Foundry selections.
"""

import os


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_streaming_multi_endpoint_resolution_wiring():
    """Verify the streaming route resolves selected models from endpoint metadata."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    chat_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_chats.py')

    content = read_file_text(chat_path)

    assert "frontend_model_id = data.get('model_id')" in content, (
        'Expected streaming payload parsing to capture model_id.'
    )
    assert "frontend_model_endpoint_id = data.get('model_endpoint_id')" in content, (
        'Expected streaming payload parsing to capture model_endpoint_id.'
    )
    assert "frontend_model_provider = data.get('model_provider')" in content, (
        'Expected streaming payload parsing to capture model_provider.'
    )
    assert 'def resolve_foundry_scope_for_auth(' in content, (
        'Expected streaming route helpers to include Foundry scope resolution.'
    )
    assert 'def build_streaming_multi_endpoint_client(' in content, (
        'Expected streaming route helpers to build provider-aware inference clients.'
    )
    assert 'def resolve_streaming_multi_endpoint_gpt_config(' in content, (
        'Expected streaming route helpers to resolve endpoint/model selections.'
    )
    assert 'keyvault_model_endpoint_get_helper(' in content, (
        'Expected streaming model resolution to hydrate stored secrets before inference.'
    )
    assert 'streaming_multi_endpoint_config = resolve_streaming_multi_endpoint_gpt_config(' in content, (
        'Expected /api/chat/stream to resolve models from endpoint/model ids before fallback.'
    )
    assert 'active_group_ids=active_group_ids' in content, (
        'Expected streaming group context to be supplied when resolving scoped model endpoints.'
    )

    print('✅ Streaming multi-endpoint model resolution wiring verified.')


def run_tests():
    tests = [test_streaming_multi_endpoint_resolution_wiring]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print('✅ Test passed')
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == '__main__':
    raise SystemExit(0 if run_tests() else 1)