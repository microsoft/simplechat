# functions_image_generation.py
"""Shared helpers for opt-in chat image generation proposals."""

import json
import io
import mimetypes
import os
import random
import re
import tempfile
import time
import uuid
from datetime import datetime
from urllib.parse import urlparse

import requests
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from werkzeug.utils import secure_filename

from config import AzureOpenAI, CLIENTS, IMAGE_EXTENSIONS, cognitive_services_scope, cosmos_messages_container
from functions_appinsights import log_event
from functions_image_messages import (
    build_image_message_documents,
    decode_image_content,
    get_complete_image_content,
    is_blob_backed_image_message,
)


INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE = 'simpleimage'
IMAGE_PROPOSAL_GUIDANCE_MARKER = '[Opt-in Image Generation Proposal Guidance]'
IMAGE_PROPOSAL_PROMPT_MAX_LENGTH = 4000
IMAGE_PROPOSAL_TEXT_MAX_LENGTH = 600
IMAGE_PROPOSAL_ID_MAX_LENGTH = 120
IMAGE_REFERENCE_MAX_COUNT = 4
IMAGE_REFERENCE_MAX_BYTES = 20 * 1024 * 1024
IMAGE_REFERENCE_ALLOWED_MIME_TYPES = {'image/png', 'image/jpeg', 'image/webp'}
IMAGE_REFERENCE_GROUP_READ_ROLES = ('Owner', 'Admin', 'DocumentManager', 'User')
IMAGE_REFERENCE_GROUP_WRITE_ROLES = ('Owner', 'Admin', 'DocumentManager')
IMAGE_REFERENCE_MIN_AZURE_OPENAI_API_VERSION = '2025-04-01-preview'

IMAGE_PROPOSAL_ACTION_MARKERS = (
    'create',
    'generate',
    'make',
    'draw',
    'design',
    'render',
    'produce',
    'illustrate',
    'visualize',
    'visualise',
    'turn this into',
    'convert this into',
    'criar',
    'crie',
    'gerar',
    'gere',
    'fazer',
    'faca',
    'desenhar',
    'desenhe',
    'crear',
    'generar',
    'dibujar',
    'disenar',
)

IMAGE_PROPOSAL_REQUEST_MARKERS = (
    'image',
    'illustration',
    'illustrate',
    'visual',
    'visualize',
    'visualise',
    'picture',
    'graphic',
    'diagram',
    'timeline',
    'slide',
    'powerpoint',
    'presentation',
    'poster',
    'infographic',
    'storyboard',
    'concept art',
    'map',
    'workflow',
    'process',
    'logo',
    'icon',
    'banner',
    'thumbnail',
    'imagem',
    'imagen',
    'ilustracao',
    'ilustracion',
    'figura',
    'grafico',
    'diagrama',
    'mapa',
    'cartaz',
    'infografico',
)


class ImageReferenceTargetSelectionRequired(ValueError):
    """Raised when the user must choose one writable workspace target."""

    def __init__(self, message, target_options=None):
        super().__init__(message)
        self.target_options = target_options or []


def _coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _normalize_reference_text(value, max_length=300):
    return re.sub(r'\s+', ' ', str(value or '').strip())[:max_length]


def _normalize_scope_type(value):
    normalized_value = str(value or '').strip().lower().replace('-', '_')
    if normalized_value in {'user', 'personal_workspace'}:
        return 'personal'
    if normalized_value in {'group_workspace'}:
        return 'group'
    if normalized_value in {'public', 'public_workspace'}:
        return 'public'
    if normalized_value in {'chat', 'chat_image', 'conversation'}:
        return 'chat'
    return normalized_value


def _parse_api_version_date(value):
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', str(value or ''))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.groups())
    except ValueError:
        return None


def resolve_image_generation_api_version(api_version, require_reference_image_support=False):
    """Return an API version suitable for image generation or reference-image editing."""
    normalized_api_version = str(api_version or '').strip()
    if not require_reference_image_support:
        return normalized_api_version

    configured_date = _parse_api_version_date(normalized_api_version)
    minimum_date = _parse_api_version_date(IMAGE_REFERENCE_MIN_AZURE_OPENAI_API_VERSION)
    if not configured_date or (minimum_date and configured_date < minimum_date):
        return IMAGE_REFERENCE_MIN_AZURE_OPENAI_API_VERSION

    return normalized_api_version


def _normalize_target_payload(target_payload):
    if not isinstance(target_payload, dict):
        return {}

    scope_type = _normalize_scope_type(target_payload.get('scope_type') or target_payload.get('scopeType'))
    return {
        'scope_type': scope_type,
        'group_id': _normalize_reference_text(target_payload.get('group_id') or target_payload.get('groupId'), 120),
        'public_workspace_id': _normalize_reference_text(
            target_payload.get('public_workspace_id') or target_payload.get('publicWorkspaceId'),
            120,
        ),
    }


def _normalize_group_ids(group_ids):
    normalized_group_ids = []
    seen_group_ids = set()
    for group_id in _coerce_list(group_ids):
        normalized_group_id = _normalize_reference_text(group_id, 120)
        if not normalized_group_id or normalized_group_id in seen_group_ids:
            continue
        normalized_group_ids.append(normalized_group_id)
        seen_group_ids.add(normalized_group_id)
    return normalized_group_ids


def _build_personal_target(reason='personal'):
    return {
        'scope_type': 'personal',
        'scope_id': '',
        'label': 'Personal workspace',
        'reason': reason,
    }


def _build_group_target(user_id, group_id):
    # Lazy import avoids loading the full document/workspace stack for proposal-only helpers.
    from functions_group import assert_group_role, check_group_status_allows_operation, find_group_by_id

    normalized_group_id = _normalize_reference_text(group_id, 120)
    if not normalized_group_id:
        raise ValueError('group_id is required for group image reference target')

    role = assert_group_role(
        user_id,
        normalized_group_id,
        allowed_roles=IMAGE_REFERENCE_GROUP_WRITE_ROLES,
    )
    group_doc = find_group_by_id(normalized_group_id)
    allowed, reason = check_group_status_allows_operation(group_doc, 'upload')
    if not allowed:
        raise PermissionError(reason)

    return {
        'scope_type': 'group',
        'scope_id': normalized_group_id,
        'group_id': normalized_group_id,
        'label': group_doc.get('name') or 'Group workspace',
        'role': role,
    }


def _get_writable_group_target_options(user_id, group_ids):
    target_options = []
    for group_id in _normalize_group_ids(group_ids):
        try:
            group_target = _build_group_target(user_id, group_id)
            target_options.append({
                'scope_type': 'group',
                'group_id': group_target['group_id'],
                'label': group_target.get('label') or 'Group workspace',
                'role': group_target.get('role'),
            })
        except Exception as exc:
            log_event(
                '[ImageGeneration] Group workspace is not writable for image references',
                extra={'group_id': group_id, 'error': str(exc)},
                debug_only=True,
            )
    return target_options


def resolve_image_reference_target(
    *,
    user_id,
    target_payload=None,
    active_group_ids=None,
    active_public_workspace_id=None,
):
    """Resolve where reference and generated images must be saved."""
    target = _normalize_target_payload(target_payload)
    requested_scope_type = target.get('scope_type')

    if requested_scope_type == 'group':
        return _build_group_target(user_id, target.get('group_id'))

    if requested_scope_type in {'personal', 'public'}:
        reason = 'public_workspace_outputs_save_to_personal' if requested_scope_type == 'public' else 'explicit_personal'
        return _build_personal_target(reason=reason)

    writable_group_targets = _get_writable_group_target_options(user_id, active_group_ids)
    if len(writable_group_targets) == 1:
        return _build_group_target(user_id, writable_group_targets[0]['group_id'])
    if len(writable_group_targets) > 1:
        raise ImageReferenceTargetSelectionRequired(
            'Choose which group workspace should receive the saved reference and generated image.',
            target_options=writable_group_targets,
        )

    if _normalize_reference_text(active_public_workspace_id, 120):
        return _build_personal_target(reason='public_workspace_outputs_save_to_personal')

    if _normalize_group_ids(active_group_ids):
        raise PermissionError(
            'You do not have permission to save image references to the active group workspace. Save to personal workspace instead.'
        )

    return _build_personal_target(reason='default_personal')


def _guess_image_mime_type(file_name, fallback='image/png'):
    guessed_type = mimetypes.guess_type(str(file_name or ''))[0]
    normalized_type = str(guessed_type or fallback or 'image/png').split(';', 1)[0].strip().lower()
    return normalized_type or 'image/png'


def _validate_reference_image_bytes(image_bytes, mime_type, file_name):
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        raise ValueError('Reference image content is empty')

    normalized_bytes = bytes(image_bytes)
    if len(normalized_bytes) > IMAGE_REFERENCE_MAX_BYTES:
        max_mb = IMAGE_REFERENCE_MAX_BYTES // (1024 * 1024)
        raise ValueError(f'Reference images must be {max_mb} MB or smaller')

    normalized_mime_type = str(mime_type or _guess_image_mime_type(file_name)).split(';', 1)[0].strip().lower()
    if normalized_mime_type == 'image/jpg':
        normalized_mime_type = 'image/jpeg'
    if normalized_mime_type not in IMAGE_REFERENCE_ALLOWED_MIME_TYPES:
        raise ValueError('Reference images must be PNG, JPEG, or WEBP files')

    return normalized_mime_type, normalized_bytes


def _download_blob_bytes(blob_container, blob_path):
    normalized_container = _normalize_reference_text(blob_container, 160)
    normalized_blob_path = str(blob_path or '').strip()
    if not normalized_container or not normalized_blob_path:
        raise LookupError('Image blob reference is incomplete')

    blob_service_client = CLIENTS.get('storage_account_office_docs_client')
    if not blob_service_client:
        raise RuntimeError('Blob storage client not available')

    blob_client = blob_service_client.get_blob_client(
        container=normalized_container,
        blob=normalized_blob_path,
    )
    return blob_client.download_blob().readall()


def _slugify_file_stem(value, fallback='image'):
    normalized_value = secure_filename(str(value or '').replace('\\', '/').split('/')[-1].strip())
    base_name, _extension = os.path.splitext(normalized_value)
    slug_source = str(base_name or normalized_value).replace('_', '-')
    slug = re.sub(r'[^a-zA-Z0-9.-]+', '-', slug_source).strip('.-')
    return (slug or fallback)[:80]


def _normalize_image_file_name(file_name, mime_type, prefix='image-reference', unique_suffix=None):
    normalized_file_name = secure_filename(str(file_name or '').replace('\\', '/').split('/')[-1].strip())
    base_name, extension = os.path.splitext(normalized_file_name)
    if not extension:
        extension = _image_extension_for_mime_type(mime_type)
    if extension.lower() == '.jpeg':
        extension = '.jpg'

    normalized_base_name = _slugify_file_stem(base_name or normalized_file_name, fallback=prefix)
    suffix = str(unique_suffix or uuid.uuid4().hex[:8]).strip()[:16]
    return f'{prefix}-{normalized_base_name}-{suffix}{extension.lower()}'


def _build_generated_image_file_name(message_id, prompt, mime_type):
    prompt_stem = _slugify_file_stem(prompt, fallback='image')
    message_suffix = str(message_id or uuid.uuid4().hex).replace('-', '')[-8:]
    return _normalize_image_file_name(
        f'{prompt_stem}{_image_extension_for_mime_type(mime_type)}',
        mime_type,
        prefix='generated',
        unique_suffix=message_suffix,
    )


def _get_chat_image_source(user_id, conversation_id, reference):
    del user_id
    message_id = _normalize_reference_text(
        reference.get('message_id') or reference.get('messageId') or reference.get('id'),
        180,
    )
    if not message_id:
        raise ValueError('message_id is required for chat image references')

    try:
        image_message = cosmos_messages_container.read_item(
            item=message_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError('Chat image reference was not found') from exc

    if image_message.get('conversation_id') != conversation_id or image_message.get('role') != 'image':
        raise PermissionError('Chat image reference does not belong to this conversation')

    file_name = image_message.get('filename') or f'{message_id}.png'
    mime_type = image_message.get('mime_type') or _guess_image_mime_type(file_name)

    if is_blob_backed_image_message(image_message):
        image_bytes = _download_blob_bytes(image_message.get('blob_container'), image_message.get('blob_path'))
    else:
        _message_doc, complete_content = get_complete_image_content(
            cosmos_messages_container,
            conversation_id,
            message_id,
        )
        if str(complete_content or '').startswith('data:image/'):
            mime_type, image_bytes = decode_image_content(complete_content)
        else:
            mime_type, image_bytes = resolve_generated_image_bytes(complete_content)

    mime_type, image_bytes = _validate_reference_image_bytes(image_bytes, mime_type, file_name)
    vision_analysis = image_message.get('vision_analysis') if isinstance(image_message.get('vision_analysis'), dict) else {}
    if not vision_analysis and isinstance(image_message.get('metadata'), dict):
        vision_analysis = image_message['metadata'].get('vision_analysis') if isinstance(image_message['metadata'].get('vision_analysis'), dict) else {}
    return {
        'source_type': 'chat_image',
        'source_scope_type': 'chat',
        'source_message_id': message_id,
        'source_document_id': '',
        'source_workspace_id': '',
        'file_name': file_name,
        'mime_type': mime_type,
        'image_bytes': image_bytes,
        'source_label': image_message.get('filename') or reference.get('title') or 'Conversation image',
        'vision_analysis': vision_analysis,
        'extracted_text': image_message.get('extracted_text') or '',
    }


def _read_document_image_source(document_item, source_scope_type, source_workspace_id):
    # Lazy import avoids loading document processors until a workspace image is actually used.
    from functions_documents import get_document_blob_storage_info

    file_name = document_item.get('file_name') or document_item.get('filename') or f"{document_item.get('id') or 'image'}.png"
    extension = str(file_name or '').rsplit('.', 1)[-1].lower() if '.' in str(file_name or '') else ''
    if extension not in IMAGE_EXTENSIONS:
        raise ValueError('Selected workspace document is not an image')

    blob_container, blob_path = get_document_blob_storage_info(document_item)
    image_bytes = _download_blob_bytes(blob_container, blob_path)
    mime_type = document_item.get('mime_type') or _guess_image_mime_type(file_name)
    mime_type, image_bytes = _validate_reference_image_bytes(image_bytes, mime_type, file_name)
    return {
        'source_type': 'workspace_image',
        'source_scope_type': source_scope_type,
        'source_message_id': '',
        'source_document_id': document_item.get('id'),
        'source_workspace_id': source_workspace_id,
        'file_name': file_name,
        'mime_type': mime_type,
        'image_bytes': image_bytes,
        'source_label': document_item.get('title') or file_name,
        'vision_analysis': document_item.get('vision_analysis') if isinstance(document_item.get('vision_analysis'), dict) else {},
        'abstract': document_item.get('abstract') or '',
    }


def _get_public_workspace_image_document(user_id, document_id, public_workspace_id):
    # Lazy imports avoid loading workspace dependencies unless public references are used.
    from functions_documents import get_document_metadata
    from functions_public_workspaces import (
        check_public_workspace_status_allows_operation,
        find_public_workspace_by_id,
        get_user_visible_public_workspace_ids_from_settings,
    )

    normalized_workspace_id = _normalize_reference_text(public_workspace_id, 120)
    if not normalized_workspace_id:
        return None

    visible_workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
    if normalized_workspace_id not in visible_workspace_ids:
        raise PermissionError('Public workspace image is not visible to this user')

    workspace_doc = find_public_workspace_by_id(normalized_workspace_id)
    allowed, reason = check_public_workspace_status_allows_operation(workspace_doc, 'view')
    if not allowed:
        raise PermissionError(reason)

    return get_document_metadata(
        document_id=document_id,
        user_id=user_id,
        public_workspace_id=normalized_workspace_id,
    )


def _get_workspace_image_source(user_id, reference):
    # Lazy imports avoid loading document processors for text-only/proposal-only image paths.
    from functions_documents import get_document_metadata
    from functions_group import assert_group_role, get_user_groups
    from functions_public_workspaces import get_user_visible_public_workspace_ids_from_settings

    document_id = _normalize_reference_text(
        reference.get('document_id') or reference.get('documentId') or reference.get('doc_id') or reference.get('docId'),
        180,
    )
    if not document_id:
        raise ValueError('document_id is required for workspace image references')

    source_scope_type = _normalize_scope_type(reference.get('scope_type') or reference.get('scopeType'))
    group_id = _normalize_reference_text(reference.get('group_id') or reference.get('groupId'), 120)
    public_workspace_id = _normalize_reference_text(
        reference.get('public_workspace_id') or reference.get('publicWorkspaceId'),
        120,
    )

    if source_scope_type == 'group' or group_id:
        assert_group_role(user_id, group_id, allowed_roles=IMAGE_REFERENCE_GROUP_READ_ROLES)
        document_item = get_document_metadata(document_id=document_id, user_id=user_id, group_id=group_id)
        if not document_item:
            raise LookupError('Group workspace image was not found')
        return _read_document_image_source(document_item, 'group', group_id)

    if source_scope_type == 'public' or public_workspace_id:
        document_item = _get_public_workspace_image_document(user_id, document_id, public_workspace_id)
        if not document_item:
            raise LookupError('Public workspace image was not found')
        return _read_document_image_source(document_item, 'public', public_workspace_id)

    if source_scope_type in {'', 'personal'}:
        document_item = get_document_metadata(document_id=document_id, user_id=user_id)
        if document_item:
            return _read_document_image_source(document_item, 'personal', user_id)

    for group in get_user_groups(user_id):
        search_group_id = group.get('id')
        if not search_group_id:
            continue
        try:
            document_item = get_document_metadata(document_id=document_id, user_id=user_id, group_id=search_group_id)
            if document_item:
                return _read_document_image_source(document_item, 'group', search_group_id)
        except Exception:
            continue

    for workspace_id in get_user_visible_public_workspace_ids_from_settings(user_id):
        try:
            document_item = get_document_metadata(document_id=document_id, user_id=user_id, public_workspace_id=workspace_id)
            if document_item:
                return _read_document_image_source(document_item, 'public', workspace_id)
        except Exception:
            continue

    raise LookupError('Workspace image reference was not found')


def _resolve_image_reference_source(user_id, conversation_id, reference):
    if not isinstance(reference, dict):
        raise ValueError('Image reference must be an object')

    source_type = _normalize_scope_type(reference.get('source_type') or reference.get('sourceType'))
    if source_type in {'chat', 'chat_image'} or reference.get('message_id') or reference.get('messageId'):
        return _get_chat_image_source(user_id, conversation_id, reference)

    return _get_workspace_image_source(user_id, reference)


def _workspace_target_matches_source(target_scope, source_reference):
    if not target_scope or not source_reference:
        return False
    target_type = target_scope.get('scope_type')
    source_type = source_reference.get('source_scope_type')
    if source_type == 'chat' or source_type == 'public':
        return False
    if target_type == 'personal' and source_type == 'personal':
        return True
    return target_type == 'group' and source_type == 'group' and target_scope.get('group_id') == source_reference.get('source_workspace_id')


def save_image_bytes_to_reference_workspace(
    *,
    user_id,
    image_bytes,
    mime_type,
    file_name,
    target_scope,
    metadata,
    role='reference',
):
    """Save image bytes as a lightweight workspace document in the target scope."""
    # Lazy imports avoid loading the full document pipeline unless a reference is saved.
    from functions_documents import build_chat_upload_workspace_tags, create_document, upload_to_blob, update_document
    from utils_cache import invalidate_group_search_cache, invalidate_personal_search_cache

    normalized_target = target_scope or _build_personal_target()
    if normalized_target.get('scope_type') not in {'personal', 'group'}:
        normalized_target = _build_personal_target(reason='unsupported_target_fallback')

    mime_type, image_bytes = _validate_reference_image_bytes(image_bytes, mime_type, file_name)
    document_id = str(uuid.uuid4())
    if role == 'generated':
        saved_file_name = _build_generated_image_file_name(
            str(metadata.get('generated_image_message_id') or ''),
            metadata.get('prompt') or file_name,
            mime_type,
        )
    else:
        saved_file_name = _normalize_image_file_name(
            file_name,
            mime_type,
            prefix='reference',
            unique_suffix=str(metadata.get('reference_index') or uuid.uuid4().hex[:8]),
        )
    group_id = normalized_target.get('group_id') if normalized_target.get('scope_type') == 'group' else None
    status = 'Processing complete'
    temp_file_path = None

    try:
        create_document(
            file_name=saved_file_name,
            user_id=user_id,
            group_id=group_id,
            document_id=document_id,
            num_file_chunks=0,
            status='Saving image reference' if role == 'reference' else 'Saving generated image',
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(saved_file_name)[1]) as temp_file:
            temp_file.write(image_bytes)
            temp_file_path = temp_file.name

        upload_to_blob(
            temp_file_path,
            user_id=user_id,
            group_id=group_id,
            public_workspace_id=None,
            document_id=document_id,
            blob_filename=saved_file_name,
            update_callback=lambda **_kwargs: None,
            mark_enhanced_citations=True,
        )

        update_document(
            document_id=document_id,
            user_id=user_id,
            group_id=group_id,
            status=status,
            percentage_complete=100,
            mime_type=mime_type,
            source_file_available=True,
            tags=build_chat_upload_workspace_tags(metadata.get('conversation_id')),
            source_type='image_generation',
            source_subtype='generated_image' if role == 'generated' else 'image_reference',
            created_from_chat_upload=True,
            chat_upload_delete_with_conversation=True,
            chat_upload_link_state='linked',
            chat_upload_linked_at=datetime.utcnow().isoformat(),
            conversation_id=metadata.get('conversation_id'),
            conversation_url=f"/chats?conversation_id={metadata.get('conversation_id')}",
            chat_message_id=metadata.get('generated_image_message_id') or metadata.get('source_message_id'),
            chat_upload_original_filename=file_name,
            chat_upload_sanitized_filename=saved_file_name,
            image_generation_reference=metadata,
            image_generation_reference_role=role,
        )

        if group_id:
            invalidate_group_search_cache(group_id)
        else:
            invalidate_personal_search_cache(user_id)

        return {
            'document_id': document_id,
            'file_name': saved_file_name,
            'scope_type': normalized_target.get('scope_type'),
            'scope_id': group_id or user_id,
            'group_id': group_id or '',
            'mime_type': mime_type,
            'role': role,
            'conversation_id': metadata.get('conversation_id'),
            'conversation_url': f"/chats?conversation_id={metadata.get('conversation_id')}",
            'tags': build_chat_upload_workspace_tags(metadata.get('conversation_id')),
        }
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def _ensure_reference_saved_to_target(user_id, conversation_id, source_reference, target_scope, reference_index):
    if _workspace_target_matches_source(target_scope, source_reference):
        return {
            'document_id': source_reference.get('source_document_id'),
            'file_name': source_reference.get('file_name'),
            'scope_type': source_reference.get('source_scope_type'),
            'scope_id': source_reference.get('source_workspace_id') or user_id,
            'group_id': source_reference.get('source_workspace_id') if source_reference.get('source_scope_type') == 'group' else '',
            'mime_type': source_reference.get('mime_type'),
            'role': 'reference',
            'already_in_target': True,
        }

    metadata = {
        'used_as_image_reference': True,
        'conversation_id': conversation_id,
        'reference_index': reference_index,
        'source_type': source_reference.get('source_type'),
        'source_scope_type': source_reference.get('source_scope_type'),
        'source_workspace_id': source_reference.get('source_workspace_id'),
        'source_document_id': source_reference.get('source_document_id'),
        'source_message_id': source_reference.get('source_message_id'),
        'saved_at': datetime.utcnow().isoformat(),
    }
    return save_image_bytes_to_reference_workspace(
        user_id=user_id,
        image_bytes=source_reference['image_bytes'],
        mime_type=source_reference['mime_type'],
        file_name=source_reference['file_name'],
        target_scope=target_scope,
        metadata=metadata,
        role='reference',
    )


def prepare_image_references_for_generation(
    *,
    user_id,
    conversation_id,
    raw_references=None,
    target_scope=None,
):
    """Resolve, validate, and save image references before generation."""
    references = [reference for reference in _coerce_list(raw_references) if reference]
    if not references:
        return []
    if len(references) > IMAGE_REFERENCE_MAX_COUNT:
        raise ValueError(f'Image generation supports up to {IMAGE_REFERENCE_MAX_COUNT} reference images')

    prepared_references = []
    for index, reference in enumerate(references, start=1):
        source_reference = _resolve_image_reference_source(user_id, conversation_id, reference)
        saved_reference = _ensure_reference_saved_to_target(
            user_id,
            conversation_id,
            source_reference,
            target_scope or _build_personal_target(),
            index,
        )
        prepared_references.append({
            'reference_id': str(reference.get('reference_id') or reference.get('id') or saved_reference.get('document_id') or index),
            'reference_index': index,
            'file_name': source_reference['file_name'],
            'mime_type': source_reference['mime_type'],
            'image_bytes': source_reference['image_bytes'],
            'source': {key: value for key, value in source_reference.items() if key != 'image_bytes'},
            'saved_reference': saved_reference,
        })

    return prepared_references


def serialize_prepared_image_references(prepared_references):
    """Return image-reference metadata safe for Cosmos and the browser."""
    serialized_references = []
    for prepared_reference in prepared_references or []:
        serialized_references.append({
            'reference_id': prepared_reference.get('reference_id'),
            'reference_index': prepared_reference.get('reference_index'),
            'file_name': prepared_reference.get('file_name'),
            'mime_type': prepared_reference.get('mime_type'),
            'source': prepared_reference.get('source'),
            'saved_reference': prepared_reference.get('saved_reference'),
        })
    return serialized_references


def _build_reference_image_inputs(prepared_references):
    image_inputs = []
    for prepared_reference in prepared_references or []:
        image_input = io.BytesIO(prepared_reference['image_bytes'])
        image_input.name = _normalize_image_file_name(
            prepared_reference.get('file_name'),
            prepared_reference.get('mime_type'),
            prefix='reference-image',
        )
        image_inputs.append(image_input)
    return image_inputs


def _generate_image_response(image_gen_client, image_gen_model, prompt, prepared_references=None):
    if not prepared_references:
        return image_gen_client.images.generate(
            prompt=prompt,
            n=1,
            model=image_gen_model,
        )

    edit_method = getattr(image_gen_client.images, 'edit', None)
    if not callable(edit_method):
        raise ValueError(
            'The selected image generation deployment does not support reference images. Ask an administrator to enable a compatible image generation deployment.'
        )

    image_inputs = _build_reference_image_inputs(prepared_references)
    try:
        return edit_method(
            prompt=prompt,
            image=image_inputs if len(image_inputs) > 1 else image_inputs[0],
            n=1,
            model=image_gen_model,
        )
    except TypeError as exc:
        raise ValueError(
            'The selected image generation deployment does not support reference images. Ask an administrator to enable a compatible image generation deployment.'
        ) from exc
    except Exception as exc:
        error_message = str(exc)
        if 'resource not found' in error_message.lower() or '404' in error_message:
            raise ValueError(
                'The selected image generation deployment could not process reference images. Ask an administrator to verify the image generation deployment name, API version, and reference-image support.'
            ) from exc
        raise


def _format_reference_source_for_prompt(prepared_reference):
    source = prepared_reference.get('source') if isinstance(prepared_reference.get('source'), dict) else {}
    file_name = prepared_reference.get('file_name') or source.get('file_name') or 'selected image'
    parts = [f"Reference image {prepared_reference.get('reference_index') or ''}: {file_name}".strip()]

    vision_analysis = source.get('vision_analysis') if isinstance(source.get('vision_analysis'), dict) else {}
    if vision_analysis.get('description'):
        parts.append(f"Description: {vision_analysis.get('description')}")
    if vision_analysis.get('objects'):
        objects = vision_analysis.get('objects')
        if isinstance(objects, list):
            parts.append(f"Objects: {', '.join(str(item) for item in objects)}")
        else:
            parts.append(f"Objects: {objects}")
    if vision_analysis.get('text'):
        parts.append(f"Visible text: {vision_analysis.get('text')}")
    if vision_analysis.get('analysis'):
        parts.append(f"Context: {vision_analysis.get('analysis')}")
    if source.get('abstract'):
        parts.append(f"Document abstract: {source.get('abstract')}")
    if source.get('extracted_text'):
        parts.append(f"Extracted text: {source.get('extracted_text')}")

    if len(parts) == 1:
        parts.append('No image description metadata was available; use the filename and user prompt as the only reference context.')

    return ' '.join(_normalize_reference_text(part, 900) for part in parts if part)


def build_reference_fallback_prompt(prompt, prepared_references):
    """Build a text-only image prompt from selected image reference metadata."""
    reference_context = "\n".join(
        f"- {_format_reference_source_for_prompt(prepared_reference)}"
        for prepared_reference in prepared_references or []
    )
    if not reference_context:
        return _trim_text(prompt, IMAGE_PROPOSAL_PROMPT_MAX_LENGTH)

    fallback_prompt = f"""{prompt}

Selected image reference descriptions:
{reference_context}

Use the selected image descriptions as visual guidance. Preserve the relevant subject, composition, and notable visual details from the selected image while following the user's requested style and output instructions."""
    return _trim_text(fallback_prompt, IMAGE_PROPOSAL_PROMPT_MAX_LENGTH)


def save_generated_image_to_reference_workspace(
    *,
    user_id,
    conversation_id,
    message_id,
    prompt,
    image_bytes,
    mime_type,
    target_scope,
    prepared_references=None,
):
    """Save generated image output to the same target workspace used by reference images."""
    if not target_scope:
        return None

    metadata = {
        'created_from_image_references': serialize_prepared_image_references(prepared_references),
        'conversation_id': conversation_id,
        'generated_image_message_id': message_id,
        'prompt': _trim_text(prompt, IMAGE_PROPOSAL_PROMPT_MAX_LENGTH),
        'saved_at': datetime.utcnow().isoformat(),
    }
    return save_image_bytes_to_reference_workspace(
        user_id=user_id,
        image_bytes=image_bytes,
        mime_type=mime_type,
        file_name=f'{message_id}{_image_extension_for_mime_type(mime_type)}',
        target_scope=target_scope,
        metadata=metadata,
        role='generated',
    )


def image_generation_is_enabled(settings):
    """Return whether chat image generation is enabled in app settings."""
    return bool(isinstance(settings, dict) and settings.get('enable_image_generation'))


def user_request_supports_image_proposals(user_message):
    """Return true when a response could reasonably include optional image proposals."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    has_generation_intent = any(marker in normalized_message for marker in IMAGE_PROPOSAL_ACTION_MARKERS)
    has_visual_subject = any(marker in normalized_message for marker in IMAGE_PROPOSAL_REQUEST_MARKERS)
    return has_generation_intent and has_visual_subject


def build_image_proposal_guidance_message(selected_reference_count=0):
    """Return system guidance for assistant-authored image proposal cards."""
    try:
        reference_count = max(0, int(selected_reference_count or 0))
    except (TypeError, ValueError):
        reference_count = 0

    reference_guidance = ''
    if reference_count > 0:
        reference_label = 'image reference is' if reference_count == 1 else 'image references are'
        reference_guidance = f"\n- {reference_count} selected {reference_label} available for approved image generation. Do not ask the user to upload the selected reference image again; write the proposal prompt so it uses the selected reference image context."

    return f"""{IMAGE_PROPOSAL_GUIDANCE_MARKER}
Image generation is available as an opt-in user action. Do not generate or embed images directly in the assistant answer. When one or more generated images would materially help the user, include compact fenced `{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}` JSON proposals inline at the point where each visual belongs. The browser will render each block as an approval card with approve, cancel, and edit controls.

Use this exact fenced block shape and valid JSON only:
```{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}
{{
  "version": 1,
  "visualId": "short_stable_id",
  "title": "Short image title",
  "description": "One sentence describing the proposed image.",
  "prompt": "Detailed image-generation prompt with subject, composition, labels, style, accessibility/readability constraints, and any source context needed.",
  "visualType": "timeline|diagram|illustration|infographic|map|scene|other",
  "slideNumber": 9,
  "context": "Brief source context"
}}
```

Rules:
- Only propose images when they are useful; omit the block when text alone is better.
- Place each `{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}` block immediately after the paragraph, bullet, slide section, or visual suggestion it supports. Do not collect image proposals at the end unless the end is the relevant section.
- For slide decks, keep each proposal inside the slide it supports, directly after the slide's visual suggestion, include list, or speaker note.
- Suggest zero, one, or multiple images based on value. One strong image proposal is fine; multiple distinct proposals are appropriate when several slides or sections benefit from visuals.
- Avoid decorative duplicates and avoid proposing images that do not directly support the surrounding content.
- Keep each prompt self-contained and under {IMAGE_PROPOSAL_PROMPT_MAX_LENGTH} characters.
- The user must approve before generation; never state that an image has already been created.
- Do not include secrets, private URLs, or unsupported instructions in the prompt.
{reference_guidance}
""".strip()


def _trim_text(value, max_length):
    normalized_value = re.sub(r'\s+', ' ', str(value or '').strip())
    if len(normalized_value) <= max_length:
        return normalized_value
    return normalized_value[:max_length].rstrip()


def _normalize_visual_id(value):
    normalized_value = re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(value or '').strip())
    normalized_value = normalized_value.strip('._-')
    return normalized_value[:IMAGE_PROPOSAL_ID_MAX_LENGTH]


def normalize_image_proposal(raw_proposal):
    """Validate and normalize a model-authored image proposal payload."""
    if not isinstance(raw_proposal, dict):
        raise ValueError('Image proposal must be a JSON object')

    prompt = _trim_text(raw_proposal.get('prompt'), IMAGE_PROPOSAL_PROMPT_MAX_LENGTH)
    if not prompt:
        raise ValueError('Image proposal prompt is required')

    normalized_proposal = {
        'version': 1,
        'visualId': _normalize_visual_id(raw_proposal.get('visualId') or raw_proposal.get('visual_id')),
        'title': _trim_text(raw_proposal.get('title'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH),
        'description': _trim_text(raw_proposal.get('description'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH),
        'prompt': prompt,
        'visualType': _trim_text(raw_proposal.get('visualType') or raw_proposal.get('visual_type'), 80),
        'context': _trim_text(raw_proposal.get('context'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH),
    }

    slide_number = raw_proposal.get('slideNumber', raw_proposal.get('slide_number'))
    if slide_number is not None and str(slide_number).strip() != '':
        try:
            normalized_proposal['slideNumber'] = int(slide_number)
        except (TypeError, ValueError):
            normalized_proposal['slideNumber'] = _trim_text(slide_number, 40)

    return normalized_proposal


def resolve_image_generation_client(settings, require_reference_image_support=False):
    """Create the Azure OpenAI image generation client and return it with the deployment name."""
    if not image_generation_is_enabled(settings):
        raise PermissionError('Image generation is not enabled. This request is possible, but an administrator needs to enable image generation before it can run.')

    if settings.get('enable_image_gen_apim', False):
        image_gen_model = settings.get('azure_apim_image_gen_deployment')
        image_gen_api_version = resolve_image_generation_api_version(
            settings.get('azure_apim_image_gen_api_version'),
            require_reference_image_support=require_reference_image_support,
        )
        image_gen_client = AzureOpenAI(
            api_version=image_gen_api_version,
            azure_endpoint=settings.get('azure_apim_image_gen_endpoint'),
            api_key=settings.get('azure_apim_image_gen_subscription_key'),
        )
        return image_gen_client, image_gen_model

    image_gen_model = None
    image_gen_model_obj = settings.get('image_gen_model', {})
    if image_gen_model_obj and image_gen_model_obj.get('selected'):
        selected_image_gen_model = image_gen_model_obj['selected'][0]
        image_gen_model = selected_image_gen_model.get('deploymentName')

    if settings.get('azure_openai_image_gen_authentication_type') == 'managed_identity':
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
        image_gen_api_version = resolve_image_generation_api_version(
            settings.get('azure_openai_image_gen_api_version'),
            require_reference_image_support=require_reference_image_support,
        )
        image_gen_client = AzureOpenAI(
            api_version=image_gen_api_version,
            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
            azure_ad_token_provider=token_provider,
        )
    else:
        image_gen_api_version = resolve_image_generation_api_version(
            settings.get('azure_openai_image_gen_api_version'),
            require_reference_image_support=require_reference_image_support,
        )
        image_gen_client = AzureOpenAI(
            api_version=image_gen_api_version,
            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
            api_key=settings.get('azure_openai_image_gen_key'),
        )

    if not image_gen_model:
        raise ValueError('No image generation deployment is selected')

    return image_gen_client, image_gen_model


def extract_generated_image_source(image_response):
    """Extract a usable image URL or data URL from an Azure OpenAI image response."""
    response_dict = json.loads(image_response.model_dump_json())
    if 'data' not in response_dict or not response_dict['data']:
        raise ValueError('No image data in response')

    image_data = response_dict['data'][0]
    if image_data.get('url'):
        return image_data['url']

    if image_data.get('b64_json'):
        return f"data:image/png;base64,{image_data['b64_json']}"

    available_keys = list(image_data.keys())
    raise ValueError(f'No URL or base64 data in image response. Available keys: {available_keys}')


def resolve_generated_image_bytes(generated_image_url):
    """Resolve generated image output into bytes and a MIME type for blob storage."""
    normalized_image_url = str(generated_image_url or '').strip()
    if not normalized_image_url:
        raise ValueError('Generated image URL is empty')

    if normalized_image_url.startswith('data:image/'):
        return decode_image_content(normalized_image_url)

    parsed_url = urlparse(normalized_image_url)
    if parsed_url.scheme not in {'http', 'https'}:
        raise ValueError('Generated image output is not a supported image source')

    response = requests.get(normalized_image_url, timeout=30)
    response.raise_for_status()
    image_bytes = response.content
    if not image_bytes:
        raise ValueError('Generated image download returned empty content')

    content_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip()
    if not content_type or not content_type.startswith('image/'):
        content_type = mimetypes.guess_type(parsed_url.path)[0] or 'image/png'

    return content_type, image_bytes


def _image_extension_for_mime_type(mime_type):
    if mime_type == 'image/jpeg':
        return '.jpg'
    if mime_type == 'image/webp':
        return '.webp'
    if mime_type == 'image/gif':
        return '.gif'
    return '.png'


def _build_image_proposal_metadata(proposal, source_assistant_message_id=None):
    if not proposal:
        return None

    metadata = dict(proposal)
    metadata['approved_at'] = datetime.utcnow().isoformat()
    if source_assistant_message_id:
        metadata['source_assistant_message_id'] = str(source_assistant_message_id)
    return metadata


def generate_chat_image_message(
    *,
    settings,
    user_id,
    conversation_id,
    prompt,
    user_info=None,
    thread_id=None,
    previous_thread_id=None,
    proposal=None,
    source_assistant_message_id=None,
    store_in_blob=False,
    image_references=None,
    image_reference_target=None,
):
    """Generate an image, persist it as a chat image message, and return response data."""
    normalized_prompt = _trim_text(prompt, IMAGE_PROPOSAL_PROMPT_MAX_LENGTH)
    if not normalized_prompt:
        raise ValueError('Image generation prompt is required')

    prepared_image_references = prepare_image_references_for_generation(
        user_id=user_id,
        conversation_id=conversation_id,
        raw_references=image_references,
        target_scope=image_reference_target,
    )
    image_gen_client, image_gen_model = resolve_image_generation_client(
        settings,
        require_reference_image_support=bool(prepared_image_references),
    )
    reference_generation_mode = 'text_to_image'
    reference_generation_warning = ''
    try:
        image_response = _generate_image_response(
            image_gen_client,
            image_gen_model,
            normalized_prompt,
            prepared_references=prepared_image_references,
        )
        if prepared_image_references:
            reference_generation_mode = 'provider_reference_image'
    except ValueError as exc:
        if not prepared_image_references or 'reference image' not in str(exc).lower():
            raise

        fallback_prompt = build_reference_fallback_prompt(normalized_prompt, prepared_image_references)
        image_response = _generate_image_response(
            image_gen_client,
            image_gen_model,
            fallback_prompt,
            prepared_references=None,
        )
        reference_generation_mode = 'vision_summary_fallback'
        reference_generation_warning = (
            'The selected image generation deployment could not process reference-image bytes, '
            'so SimpleChat generated the image from the selected image description instead.'
        )
    generated_image_url = extract_generated_image_source(image_response)
    if not generated_image_url or generated_image_url == 'null':
        raise ValueError('Generated image URL is null or empty')

    image_message_id = f"{conversation_id}_image_{int(time.time())}_{random.randint(1000, 9999)}"
    image_timestamp = datetime.utcnow().isoformat()
    image_metadata = {
        'user_info': user_info,
        'thread_info': {
            'thread_id': thread_id,
            'previous_thread_id': previous_thread_id,
            'active_thread': True,
            'thread_attempt': 1,
        },
    }

    image_proposal_metadata = _build_image_proposal_metadata(
        proposal,
        source_assistant_message_id=source_assistant_message_id,
    )
    if image_proposal_metadata:
        image_metadata['image_proposal'] = image_proposal_metadata
    if prepared_image_references:
        image_metadata['image_references'] = serialize_prepared_image_references(prepared_image_references)
        image_metadata['image_reference_target'] = image_reference_target
        image_metadata['image_reference_generation_mode'] = reference_generation_mode
        if reference_generation_warning:
            image_metadata['image_reference_generation_warning'] = reference_generation_warning

    image_doc = {
        'id': image_message_id,
        'conversation_id': conversation_id,
        'role': 'image',
        'content': generated_image_url,
        'prompt': normalized_prompt,
        'created_at': image_timestamp,
        'timestamp': image_timestamp,
        'model_deployment_name': image_gen_model,
        'metadata': image_metadata,
    }

    response_image_url = generated_image_url
    generated_image_bytes_info = None
    if store_in_blob or image_reference_target:
        generated_image_bytes_info = resolve_generated_image_bytes(generated_image_url)

    if store_in_blob:
        # Lazy import keeps proposal-only helpers free of optional document processing dependencies.
        from functions_simplechat_operations import upload_chat_image_bytes_for_user

        image_mime_type, image_bytes = generated_image_bytes_info
        visual_id = _normalize_visual_id((proposal or {}).get('visualId')) if proposal else ''
        image_file_stem = visual_id or image_message_id
        blob_image_info = upload_chat_image_bytes_for_user(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=image_message_id,
            file_name=f"{image_file_stem}{_image_extension_for_mime_type(image_mime_type)}",
            image_bytes=image_bytes,
            content_type=image_mime_type,
            image_source='generated',
        )
        image_doc.update({
            'content': blob_image_info['content'],
            'filename': blob_image_info['filename'],
            'file_content_source': blob_image_info['file_content_source'],
            'blob_container': blob_image_info['blob_container'],
            'blob_path': blob_image_info['blob_path'],
            'mime_type': blob_image_info['mime_type'],
        })
        image_doc['metadata']['is_chunked'] = False
        image_doc['metadata']['is_blob_backed'] = True
        image_doc['metadata']['original_size'] = blob_image_info['image_size']
        cosmos_messages_container.upsert_item(image_doc)
        response_image_url = blob_image_info['content']
    else:
        image_documents = build_image_message_documents(image_doc)
        for image_document in image_documents:
            cosmos_messages_container.upsert_item(image_document)

    generated_workspace_document = None
    if image_reference_target:
        image_mime_type, image_bytes = generated_image_bytes_info
        generated_workspace_document = save_generated_image_to_reference_workspace(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=image_message_id,
            prompt=normalized_prompt,
            image_bytes=image_bytes,
            mime_type=image_mime_type,
            target_scope=image_reference_target,
            prepared_references=prepared_image_references,
        )
        if generated_workspace_document:
            image_doc.setdefault('metadata', {})['workspace_document'] = generated_workspace_document
            cosmos_messages_container.upsert_item(image_doc)

    log_event(
        '[ImageGeneration] Generated chat image message',
        extra={
            'conversation_id': conversation_id,
            'message_id': image_message_id,
            'model_deployment_name': image_gen_model,
            'store_in_blob': store_in_blob,
            'has_proposal': bool(proposal),
            'reference_count': len(prepared_image_references),
            'reference_generation_mode': reference_generation_mode,
        },
    )

    return {
        'reply': 'Image loading...',
        'image_url': response_image_url,
        'conversation_id': conversation_id,
        'model_deployment_name': image_gen_model,
        'message_id': image_message_id,
        'image_message': image_doc,
        'image_references': serialize_prepared_image_references(prepared_image_references),
        'workspace_document': generated_workspace_document,
        'reference_generation_mode': reference_generation_mode,
        'reference_generation_warning': reference_generation_warning,
    }
