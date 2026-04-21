# test_blob_storage_action_capabilities.py
#!/usr/bin/env python3
"""
Functional test for Blob Storage action capabilities.
Version: 0.241.061
Implemented in: 0.241.061

This test ensures the Blob Storage action defaults, connection-string endpoint
derivation, and capability-gated plugin surface work correctly without
requiring a live Azure Storage account.
"""

import os
import sys
import traceback


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_blob_storage_operations import (  # noqa: E402
    derive_blob_endpoint_from_connection_string,
    normalize_blob_storage_capabilities,
    normalize_blob_storage_read_file_types,
    normalize_blob_storage_upload_file_types,
)
from semantic_kernel_plugins.blob_storage_plugin import BlobStoragePlugin  # noqa: E402


def test_blob_storage_defaults_and_endpoint_derivation():
    """Blob helpers should normalize defaults and derive a storage endpoint from a connection string."""
    print('🔍 Testing Blob Storage helper defaults and endpoint derivation...')

    connection_string = (
        'DefaultEndpointsProtocol=https;'
        'AccountName=sampleacct;'
        'AccountKey=ZmFrZUtleQ==;'
        'EndpointSuffix=core.windows.net'
    )

    endpoint = derive_blob_endpoint_from_connection_string(connection_string)
    assert endpoint == 'https://sampleacct.blob.core.windows.net'

    capabilities = normalize_blob_storage_capabilities(None)
    assert capabilities['list_container_contents'] is True
    assert capabilities['read_file_content'] is True
    assert capabilities['upload_file_to_container'] is False

    read_file_types = normalize_blob_storage_read_file_types(None)
    upload_file_types = normalize_blob_storage_upload_file_types(None)
    assert read_file_types == {'markdown': True}
    assert upload_file_types == {'markdown': True}

    print('✅ Blob Storage helper defaults verified.')
    return True


def test_blob_storage_plugin_metadata_and_capabilities():
    """BlobStoragePlugin should expose only enabled functions and preserve prefix-based blob naming."""
    print('🔍 Testing Blob Storage plugin metadata and capability gating...')

    connection_string = (
        'DefaultEndpointsProtocol=https;'
        'AccountName=sampleacct;'
        'AccountKey=ZmFrZUtleQ==;'
        'EndpointSuffix=core.windows.net'
    )
    plugin = BlobStoragePlugin(
        {
            'id': 'blob-storage-action-id',
            'name': 'markdown_blob_storage',
            'type': 'blob_storage',
            'auth': {
                'type': 'connection_string',
                'key': connection_string,
            },
            'additionalFields': {
                'container_name': 'knowledge-base',
                'blob_prefix': 'docs/reference',
                'blob_storage_capabilities': {
                    'list_container_contents': False,
                    'read_file_content': True,
                    'upload_file_to_container': True,
                },
                'blob_storage_read_file_types': {
                    'markdown': True,
                },
                'blob_storage_upload_file_types': {
                    'markdown': True,
                },
            },
        }
    )

    assert plugin.endpoint == 'https://sampleacct.blob.core.windows.net'
    assert plugin.container_name == 'knowledge-base'
    assert plugin.get_functions() == ['read_file_content', 'upload_file_to_container']
    assert plugin._resolve_blob_name('guide.md') == 'docs/reference/guide.md'
    assert plugin._get_relative_blob_name('docs/reference/guide.md') == 'guide.md'
    assert plugin._is_read_supported('docs/reference/guide.md') is True
    assert plugin._is_upload_supported('docs/reference/guide.md') is True
    assert plugin._is_read_supported('docs/reference/guide.txt') is False

    method_names = [method['name'] for method in plugin.metadata['methods']]
    assert method_names == ['read_file_content', 'upload_file_to_container']

    print('✅ Blob Storage plugin metadata and capability gating verified.')
    return True


if __name__ == '__main__':
    tests = [
        test_blob_storage_defaults_and_endpoint_derivation,
        test_blob_storage_plugin_metadata_and_capabilities,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)