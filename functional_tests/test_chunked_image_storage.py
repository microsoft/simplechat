#!/usr/bin/env python3
# test_chunked_image_storage.py
"""
Functional test for chunked image storage helpers.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures that large image payloads are split across safe document
sizes, preserve chunk metadata, and rehydrate back into either inline data URLs
or image endpoint references depending on response size.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_image_messages import (  # noqa: E402
    IMAGE_MESSAGE_SAFE_CONTENT_LIMIT,
    build_image_message_documents,
    hydrate_image_messages,
)


TINY_PNG_BASE64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII='
)
TINY_PNG_DATA_URL = f'data:image/png;base64,{TINY_PNG_BASE64}'


def test_large_images_split_into_multiple_documents():
    """Validate chunk creation and metadata for oversized images."""
    large_image_data_url = f"data:image/png;base64,{'A' * (IMAGE_MESSAGE_SAFE_CONTENT_LIMIT + 4096)}"
    documents = build_image_message_documents({
        'id': 'image-message-1',
        'conversation_id': 'conversation-1',
        'content': large_image_data_url,
        'metadata': {
            'thread_info': {
                'thread_id': 'thread-1',
                'active_thread': True,
            },
        },
    })

    main_document = documents[0]
    chunk_documents = documents[1:]

    assert len(documents) > 1
    assert main_document['role'] == 'image'
    assert main_document['metadata']['is_chunked'] is True
    assert main_document['metadata']['total_chunks'] == len(documents)
    assert main_document['metadata']['original_size'] == len(large_image_data_url)
    assert all(chunk_document['role'] == 'image_chunk' for chunk_document in chunk_documents)
    assert all(chunk_document['parent_message_id'] == 'image-message-1' for chunk_document in chunk_documents)


def test_hydration_uses_image_endpoint_for_large_responses():
    """Validate that large hydrated images return a lightweight endpoint path."""
    large_image_data_url = f"data:image/png;base64,{'B' * (IMAGE_MESSAGE_SAFE_CONTENT_LIMIT + 4096)}"
    documents = build_image_message_documents({
        'id': 'image-message-2',
        'conversation_id': 'conversation-2',
        'content': large_image_data_url,
        'metadata': {},
    })

    hydrated_messages = hydrate_image_messages(
        documents,
        image_url_builder=lambda image_id: f'/api/image/{image_id}',
    )

    assert len(hydrated_messages) == 1
    assert hydrated_messages[0]['content'] == '/api/image/image-message-2'
    assert hydrated_messages[0]['metadata']['is_large_image'] is True
    assert hydrated_messages[0]['metadata']['image_size'] == len(large_image_data_url)


def test_hydration_keeps_small_images_inline():
    """Validate that safe images stay inline for immediate display."""
    documents = build_image_message_documents({
        'id': 'image-message-3',
        'conversation_id': 'conversation-3',
        'content': TINY_PNG_DATA_URL,
        'metadata': {
            'is_user_upload': True,
        },
    })

    hydrated_messages = hydrate_image_messages(
        documents,
        image_url_builder=lambda image_id: f'/api/image/{image_id}',
    )

    assert len(hydrated_messages) == 1
    assert hydrated_messages[0]['content'] == TINY_PNG_DATA_URL
    assert hydrated_messages[0]['metadata'].get('is_large_image') is None


if __name__ == '__main__':
    test_large_images_split_into_multiple_documents()
    test_hydration_uses_image_endpoint_for_large_responses()
    test_hydration_keeps_small_images_inline()
    print('Chunked image storage checks passed.')
