# functions_image_messages.py

"""Helpers for storing, hydrating, and serving image chat messages."""

import base64
from copy import deepcopy
from datetime import UTC, datetime


IMAGE_MESSAGE_SAFE_CONTENT_LIMIT = 1500000
IMAGE_MESSAGE_INLINE_RESPONSE_LIMIT = 1024 * 1024
IMAGE_MESSAGE_CHUNK_OVERHEAD_BUFFER = 200


def _normalize_timestamp(timestamp=None):
    return str(timestamp or '').strip() or datetime.now(UTC).isoformat()


def _split_image_content(image_content, max_content_size=IMAGE_MESSAGE_SAFE_CONTENT_LIMIT):
    normalized_content = str(image_content or '')
    data_url_prefix = ''
    content_body = normalized_content

    if normalized_content.startswith('data:image/') and ',' in normalized_content:
        header, content_body = normalized_content.split(',', 1)
        data_url_prefix = f'{header},'

    chunk_size = int(max_content_size or IMAGE_MESSAGE_SAFE_CONTENT_LIMIT) - len(data_url_prefix) - IMAGE_MESSAGE_CHUNK_OVERHEAD_BUFFER
    if chunk_size <= 0:
        raise ValueError('max_content_size is too small to store image content safely')

    chunks = [
        content_body[index:index + chunk_size]
        for index in range(0, len(content_body), chunk_size)
    ] or ['']

    return data_url_prefix, chunks


def build_image_message_documents(base_document, max_content_size=IMAGE_MESSAGE_SAFE_CONTENT_LIMIT):
    main_document = deepcopy(base_document or {})
    image_content = str(main_document.get('content') or '')
    if not image_content:
        raise ValueError('Image content is required')

    if not str(main_document.get('id') or '').strip():
        raise ValueError('Image document id is required')
    if not str(main_document.get('conversation_id') or '').strip():
        raise ValueError('Image document conversation_id is required')

    data_url_prefix, chunks = _split_image_content(
        image_content,
        max_content_size=max_content_size,
    )
    total_chunks = len(chunks)
    timestamp = _normalize_timestamp(main_document.get('timestamp') or main_document.get('created_at'))

    main_document['role'] = 'image'
    main_document['timestamp'] = timestamp
    main_document['created_at'] = str(main_document.get('created_at') or timestamp)
    main_document['content'] = f'{data_url_prefix}{chunks[0]}' if data_url_prefix else chunks[0]

    metadata = dict(main_document.get('metadata', {}) or {})
    metadata['is_chunked'] = total_chunks > 1
    metadata['original_size'] = len(image_content)

    if total_chunks > 1:
        metadata['total_chunks'] = total_chunks
        metadata['chunk_index'] = 0
    else:
        metadata.pop('total_chunks', None)
        metadata.pop('chunk_index', None)

    main_document['metadata'] = metadata

    documents = [main_document]
    for chunk_index in range(1, total_chunks):
        documents.append({
            'id': f"{main_document['id']}_chunk_{chunk_index}",
            'conversation_id': main_document['conversation_id'],
            'role': 'image_chunk',
            'content': chunks[chunk_index],
            'parent_message_id': main_document['id'],
            'created_at': timestamp,
            'timestamp': timestamp,
            'metadata': {
                'is_chunk': True,
                'chunk_index': chunk_index,
                'total_chunks': total_chunks,
                'parent_message_id': main_document['id'],
            },
        })

    return documents


def reassemble_image_message_content(message_doc, chunk_documents=None):
    complete_content = str((message_doc or {}).get('content') or '')
    metadata = (message_doc or {}).get('metadata', {}) if isinstance((message_doc or {}).get('metadata'), dict) else {}
    total_chunks = int(metadata.get('total_chunks', 1) or 1)

    if total_chunks <= 1:
        return complete_content

    chunk_lookup = {}
    for chunk_document in chunk_documents or []:
        chunk_metadata = chunk_document.get('metadata', {}) if isinstance(chunk_document.get('metadata'), dict) else {}
        chunk_index = int(chunk_metadata.get('chunk_index', 0) or 0)
        if chunk_index <= 0:
            continue
        chunk_lookup[chunk_index] = str(chunk_document.get('content') or '')

    for chunk_index in range(1, total_chunks):
        complete_content += chunk_lookup.get(chunk_index, '')

    return complete_content


def hydrate_image_messages(items, image_url_builder=None, inline_content_limit=IMAGE_MESSAGE_INLINE_RESPONSE_LIMIT):
    hydrated_messages = []
    chunk_lookup = {}

    for item in items or []:
        if item.get('role') == 'image_chunk':
            parent_message_id = str(item.get('parent_message_id') or '').strip()
            if not parent_message_id:
                continue
            chunk_lookup.setdefault(parent_message_id, []).append(deepcopy(item))
            continue

        hydrated_messages.append(deepcopy(item))

    for message in hydrated_messages:
        if message.get('role') != 'image':
            continue

        message_id = str(message.get('id') or '').strip()
        metadata = message.get('metadata', {}) if isinstance(message.get('metadata'), dict) else {}
        complete_content = reassemble_image_message_content(
            message,
            chunk_lookup.get(message_id, []),
        )

        if image_url_builder and len(complete_content) > int(inline_content_limit or IMAGE_MESSAGE_INLINE_RESPONSE_LIMIT):
            message['content'] = image_url_builder(message_id)
            metadata['is_large_image'] = True
            metadata['image_size'] = len(complete_content)
        else:
            message['content'] = complete_content
            metadata.pop('is_large_image', None)
            metadata.pop('image_size', None)

        message['metadata'] = metadata

    return hydrated_messages


def get_complete_image_content(message_container, conversation_id, image_message_id):
    main_document = message_container.read_item(
        item=image_message_id,
        partition_key=conversation_id,
    )

    chunk_documents = []
    metadata = main_document.get('metadata', {}) if isinstance(main_document.get('metadata'), dict) else {}
    if metadata.get('is_chunked'):
        chunk_documents = list(message_container.query_items(
            query=(
                'SELECT * FROM c '
                'WHERE c.conversation_id = @conversation_id '
                'AND c.parent_message_id = @parent_message_id'
            ),
            parameters=[
                {'name': '@conversation_id', 'value': conversation_id},
                {'name': '@parent_message_id', 'value': image_message_id},
            ],
            partition_key=conversation_id,
        ))

    return main_document, reassemble_image_message_content(main_document, chunk_documents)


def is_external_image_url(image_content):
    normalized_content = str(image_content or '').strip().lower()
    return normalized_content.startswith('http://') or normalized_content.startswith('https://')


def decode_image_content(image_content):
    normalized_content = str(image_content or '')
    if not normalized_content.startswith('data:image/') or ',' not in normalized_content:
        raise ValueError('Image content is not a supported data URL')

    header, base64_data = normalized_content.split(',', 1)
    mime_type = header.split(':', 1)[1].split(';', 1)[0]
    return mime_type, base64.b64decode(base64_data)