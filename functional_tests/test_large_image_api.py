#!/usr/bin/env python3
# test_large_image_api.py
"""
Functional test for large image retrieval helpers.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures that reassembled image content can be retrieved from a main
image record plus chunk records and decoded into binary image bytes suitable for
the `/api/image/<image_id>` response path.
"""

import copy
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_image_messages import (  # noqa: E402
    build_image_message_documents,
    decode_image_content,
    get_complete_image_content,
)


TINY_PNG_BASE64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII='
)
TINY_PNG_DATA_URL = f'data:image/png;base64,{TINY_PNG_BASE64}'


class FakeMessageContainer:
    """Minimal stand-in for Cosmos container image lookups."""

    def __init__(self, documents):
        self._documents_by_key = {
            (document['conversation_id'], document['id']): copy.deepcopy(document)
            for document in documents
        }
        self._documents_by_parent = {}
        for document in documents:
            parent_message_id = str(document.get('parent_message_id') or '').strip()
            if not parent_message_id:
                continue
            key = (document['conversation_id'], parent_message_id)
            self._documents_by_parent.setdefault(key, []).append(copy.deepcopy(document))

    def read_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self._documents_by_key:
            raise KeyError(item)
        return copy.deepcopy(self._documents_by_key[key])

    def query_items(self, query=None, parameters=None, partition_key=None):
        del query
        parameter_map = {
            parameter['name']: parameter['value']
            for parameter in parameters or []
        }
        parent_message_id = parameter_map.get('@parent_message_id')
        return [
            copy.deepcopy(document)
            for document in self._documents_by_parent.get((partition_key, parent_message_id), [])
        ]


def test_large_image_reassembly_and_decode():
    """Validate that chunked image records can be reassembled and decoded."""
    repeated_image_data_url = f"data:image/png;base64,{TINY_PNG_BASE64 * 20000}"
    documents = build_image_message_documents({
        'id': 'image-message-large',
        'conversation_id': 'conversation-large',
        'content': repeated_image_data_url,
        'metadata': {},
    })
    container = FakeMessageContainer(documents)

    _, complete_content = get_complete_image_content(
        container,
        'conversation-large',
        'image-message-large',
    )
    mime_type, image_bytes = decode_image_content(complete_content)

    assert complete_content == repeated_image_data_url
    assert mime_type == 'image/png'
    assert image_bytes.startswith(b'\x89PNG\r\n\x1a\n')


if __name__ == '__main__':
    test_large_image_reassembly_and_decode()
    print('Large image helper checks passed.')
