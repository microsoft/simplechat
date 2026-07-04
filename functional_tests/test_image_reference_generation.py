#!/usr/bin/env python3
# test_image_reference_generation.py
"""
Functional test for chat image-reference generation support.
Version: 0.250.021
Implemented in: 0.250.015

This test ensures image-reference target selection, provider dispatch, and
metadata serialization work for reference-aware chat image generation without
requiring live Azure services.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import functions_image_generation as image_generation  # noqa: E402
import route_backend_chats as chat_routes  # noqa: E402
from functions_image_generation import (  # noqa: E402
    ImageReferenceTargetSelectionRequired,
    build_reference_fallback_prompt,
    resolve_image_reference_target,
    resolve_image_generation_api_version,
    serialize_prepared_image_references,
    user_request_supports_image_proposals,
)


class MockImageResponse:
    """Minimal Azure OpenAI image response double."""

    def __init__(self, image_url):
        self.image_url = image_url

    def model_dump_json(self):
        return '{"data":[{"url":"%s"}]}' % self.image_url


class MockImagesClient:
    """Image client double that records generate/edit calls."""

    def __init__(self):
        self.generate_calls = []
        self.edit_calls = []

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return MockImageResponse('https://example.test/generated.png')

    def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        return MockImageResponse('https://example.test/edited.png')


class MockMissingImagesClient(MockImagesClient):
    """Image client double that simulates provider 404 reference-image failure."""

    def edit(self, **kwargs):
        self.edit_calls.append(kwargs)
        raise Exception("Error code: 404 - {'error': {'code': 404, 'message': 'Resource not found'}}")


class MockImageClient:
    """Azure OpenAI client double with an images surface."""

    def __init__(self):
        self.images = MockImagesClient()


def _patch_module_attr(module_or_name, name_or_value, maybe_value=None):
    if maybe_value is None:
        module = image_generation
        name = module_or_name
        value = name_or_value
    else:
        module = module_or_name
        name = name_or_value
        value = maybe_value

    original = getattr(module, name)
    setattr(module, name, value)
    return original


def test_multiple_group_targets_require_user_selection():
    """Multiple writable active groups should require explicit target selection."""
    original = _patch_module_attr(
        '_get_writable_group_target_options',
        lambda user_id, group_ids: [
            {'scope_type': 'group', 'group_id': 'group-a', 'label': 'Group A', 'role': 'Owner'},
            {'scope_type': 'group', 'group_id': 'group-b', 'label': 'Group B', 'role': 'Admin'},
        ],
    )
    try:
        try:
            resolve_image_reference_target(user_id='user-1', active_group_ids=['group-a', 'group-b'])
        except ImageReferenceTargetSelectionRequired as exc:
            assert len(exc.target_options) == 2
            assert exc.target_options[0]['group_id'] == 'group-a'
            return
        raise AssertionError('Expected ImageReferenceTargetSelectionRequired')
    finally:
        setattr(image_generation, '_get_writable_group_target_options', original)


def test_public_workspace_target_saves_to_personal():
    """Public workspace image outputs should resolve to personal workspace storage."""
    target = resolve_image_reference_target(
        user_id='user-1',
        active_group_ids=[],
        active_public_workspace_id='public-1',
    )
    assert target['scope_type'] == 'personal'
    assert target['reason'] == 'public_workspace_outputs_save_to_personal'


def test_reference_metadata_serialization_strips_bytes():
    """Serialized reference metadata should never include raw image bytes."""
    serialized = serialize_prepared_image_references([
        {
            'reference_id': 'ref-1',
            'reference_index': 1,
            'file_name': 'logo.png',
            'mime_type': 'image/png',
            'image_bytes': b'not-for-cosmos',
            'source': {'source_type': 'workspace_image'},
            'saved_reference': {'document_id': 'doc-1'},
        }
    ])
    assert serialized == [
        {
            'reference_id': 'ref-1',
            'reference_index': 1,
            'file_name': 'logo.png',
            'mime_type': 'image/png',
            'source': {'source_type': 'workspace_image'},
            'saved_reference': {'document_id': 'doc-1'},
        }
    ]


def test_provider_uses_edit_when_references_exist():
    """Reference-aware generation should use the provider edit/reference surface."""
    client = MockImageClient()
    response = image_generation._generate_image_response(
        client,
        'mock-image-model',
        'Create a new branded image',
        prepared_references=[
            {
                'image_bytes': b'png-bytes',
                'file_name': 'logo.png',
                'mime_type': 'image/png',
            }
        ],
    )
    assert response.image_url.endswith('edited.png')
    assert len(client.images.edit_calls) == 1
    assert len(client.images.generate_calls) == 0
    assert client.images.edit_calls[0]['model'] == 'mock-image-model'
    assert client.images.edit_calls[0]['prompt'] == 'Create a new branded image'


def test_provider_uses_generate_without_references():
    """Text-only generation should preserve the existing generate path."""
    client = MockImageClient()
    response = image_generation._generate_image_response(
        client,
        'mock-image-model',
        'Create a text-only image',
        prepared_references=[],
    )
    assert response.image_url.endswith('generated.png')
    assert len(client.images.generate_calls) == 1
    assert len(client.images.edit_calls) == 0


def test_provider_404_reference_error_is_friendly():
    """Provider 404s for reference mode should become actionable user guidance."""
    client = MockImageClient()
    client.images = MockMissingImagesClient()
    try:
        image_generation._generate_image_response(
            client,
            'missing-image-model',
            'Create a pencil drawing',
            prepared_references=[
                {
                    'image_bytes': b'png-bytes',
                    'file_name': 'logo.png',
                    'mime_type': 'image/png',
                }
            ],
        )
    except ValueError as exc:
        assert 'could not process reference images' in str(exc)
        assert 'deployment name' in str(exc)
        return
    raise AssertionError('Expected provider 404 to raise friendly ValueError')


def test_reference_fallback_prompt_includes_vision_description():
    """Fallback text-to-image prompts should carry selected image vision context."""
    fallback_prompt = build_reference_fallback_prompt(
        'Create a pencil drawing of this image',
        [
            {
                'reference_index': 1,
                'file_name': 'me-cali-sq.jpg',
                'source': {
                    'vision_analysis': {
                        'description': 'A smiling person in a blue blazer in a warm office setting.',
                        'objects': ['person', 'books', 'plants'],
                    }
                },
            }
        ],
    )
    assert 'Create a pencil drawing of this image' in fallback_prompt
    assert 'A smiling person in a blue blazer' in fallback_prompt
    assert 'person, books, plants' in fallback_prompt
    assert 'Use the selected image descriptions as visual guidance' in fallback_prompt


def test_reference_api_version_upgrades_old_image_generation_versions():
    """Reference image edit calls require the newer Azure OpenAI image API version."""
    assert resolve_image_generation_api_version('2024-12-01-preview', True) == '2025-04-01-preview'
    assert resolve_image_generation_api_version('', True) == '2025-04-01-preview'
    assert resolve_image_generation_api_version('2025-04-01-preview', True) == '2025-04-01-preview'
    assert resolve_image_generation_api_version('2025-06-01-preview', True) == '2025-06-01-preview'
    assert resolve_image_generation_api_version('2024-12-01-preview', False) == '2024-12-01-preview'


def test_saved_generated_image_document_metadata_links_conversation():
    """Saved generated images should look like conversation-linked workspace documents."""
    calls = {
        'create_document': [],
        'update_document': [],
        'upload_to_blob': [],
    }

    import functions_documents  # noqa: E402
    import utils_cache  # noqa: E402

    originals = {
        'create_document': functions_documents.create_document,
        'upload_to_blob': functions_documents.upload_to_blob,
        'update_document': functions_documents.update_document,
        'invalidate_personal_search_cache': utils_cache.invalidate_personal_search_cache,
    }
    functions_documents.create_document = lambda **kwargs: calls['create_document'].append(kwargs)
    functions_documents.upload_to_blob = lambda *args, **kwargs: calls['upload_to_blob'].append({'args': args, 'kwargs': kwargs}) or 'user-1/generated-test.png'
    functions_documents.update_document = lambda **kwargs: calls['update_document'].append(kwargs)
    utils_cache.invalidate_personal_search_cache = lambda user_id: None
    try:
        result = image_generation.save_image_bytes_to_reference_workspace(
            user_id='user-1',
            image_bytes=b'png-bytes',
            mime_type='image/png',
            file_name='conversation-image.png',
            target_scope={'scope_type': 'personal'},
            metadata={
                'conversation_id': 'conversation-1',
                'generated_image_message_id': 'conversation-1_image_1234_5678',
                'prompt': 'Create a pencil drawing of my image',
            },
            role='generated',
        )
    finally:
        functions_documents.create_document = originals['create_document']
        functions_documents.upload_to_blob = originals['upload_to_blob']
        functions_documents.update_document = originals['update_document']
        utils_cache.invalidate_personal_search_cache = originals['invalidate_personal_search_cache']

    assert calls['create_document'][0]['file_name'].startswith('generated-Create-a-pencil-drawing-of-my-image-')
    update_payload = calls['update_document'][0]
    assert update_payload['created_from_chat_upload'] is True
    assert update_payload['conversation_id'] == 'conversation-1'
    assert update_payload['conversation_url'] == '/chats?conversation_id=conversation-1'
    assert update_payload['tags'] == ['conversations']
    assert update_payload['source_subtype'] == 'generated_image'
    assert result['conversation_id'] == 'conversation-1'
    assert result['tags'] == ['conversations']


def test_image_request_intent_requires_creation_action():
    """Selecting or asking about an image should not imply generation."""
    assert user_request_supports_image_proposals('What is in this image?') is False
    assert user_request_supports_image_proposals('Summarize the selected image') is False
    assert user_request_supports_image_proposals('Create a pencil drawing from this image') is True
    assert user_request_supports_image_proposals('criar uma imagem a partir desta referencia') is True


def test_selected_image_context_appends_vision_metadata():
    """Selected image documents should add direct Q&A context without search recall."""
    document_item = {
        'id': 'image-doc-1',
        'file_name': 'me-cali-sq.jpg',
        'user_id': 'user-1',
        'version': 1,
        'document_classification': 'None',
        'vision_analysis': {
            'description': 'A person standing near a palm tree.',
            'objects': ['person', 'palm tree'],
            'text': '',
            'analysis': 'Profile-style vacation image.',
        },
    }
    original_resolver = _patch_module_attr(
        chat_routes,
        '_resolve_selected_image_document_record',
        lambda **kwargs: (document_item, 'personal'),
    )
    system_messages = []
    citations = []
    combined_documents = []
    try:
        count = chat_routes.append_selected_image_document_context(
            user_id='user-1',
            selected_document_ids=['image-doc-1'],
            document_scope='personal',
            active_group_ids=[],
            active_public_workspace_ids=[],
            system_messages_for_augmentation=system_messages,
            hybrid_citations_list=citations,
            combined_documents=combined_documents,
        )
    finally:
        setattr(chat_routes, '_resolve_selected_image_document_record', original_resolver)

    assert count == 1
    assert len(system_messages) == 1
    assert 'A person standing near a palm tree.' in system_messages[0]['content']
    assert citations[0]['metadata_type'] == 'selected_image'
    assert combined_documents[0]['document_id'] == 'image-doc-1'


if __name__ == '__main__':
    tests = [
        test_multiple_group_targets_require_user_selection,
        test_public_workspace_target_saves_to_personal,
        test_reference_metadata_serialization_strips_bytes,
        test_provider_uses_edit_when_references_exist,
        test_provider_uses_generate_without_references,
        test_provider_404_reference_error_is_friendly,
        test_reference_fallback_prompt_includes_vision_description,
        test_reference_api_version_upgrades_old_image_generation_versions,
        test_saved_generated_image_document_metadata_links_conversation,
        test_image_request_intent_requires_creation_action,
        test_selected_image_context_appends_vision_metadata,
    ]
    results = []
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print(f'{test.__name__} passed')
            results.append(True)
        except Exception as exc:
            print(f'{test.__name__} failed: {exc}')
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f'Results: {passed}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
