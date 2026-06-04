#!/usr/bin/env python3
# test_collaboration_inline_image_proposal_porting_fix.py
"""
Functional test for collaborative inline image proposal porting.
Version: 0.241.144
Implemented in: 0.241.144

This test ensures generated inline image proposal results keep their assistant
card association when legacy conversations are converted into collaborative
conversations and when shared conversation messages are loaded in the browser.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / 'application' / 'single_app'
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from collaboration_models import (  # noqa: E402
    build_collaboration_message_doc_from_legacy,
    translate_image_proposal_source_metadata,
)


CHAT_COLLABORATION_JS = APP_DIR / 'static' / 'js' / 'chat' / 'chat-collaboration.js'
CHAT_MESSAGES_JS = APP_DIR / 'static' / 'js' / 'chat' / 'chat-messages.js'


def read_text(path):
    """Read a UTF-8 repository text file."""
    return path.read_text(encoding='utf-8')


def assert_contains(source, snippets, description):
    """Assert every required snippet exists in source."""
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f'Missing {description} snippets: {missing}'


def test_image_proposal_source_metadata_translates_to_collaboration_message_id():
    """Generated proposal images must point at the copied assistant message."""
    print('Testing image proposal source metadata translation...')
    metadata = {
        'image_proposal': {
            'visualId': 'proposal-001',
            'title': 'Shared classroom visual',
            'prompt': 'Create a classroom diagram.',
            'source_assistant_message_id': 'legacy-assistant-001',
        },
    }

    translated = translate_image_proposal_source_metadata(
        metadata,
        {
            'legacy-assistant-001': 'shared-assistant-001',
            'legacy-image-001': 'shared-image-001',
        },
    )

    assert translated is True
    assert metadata['image_proposal']['source_assistant_message_id'] == 'shared-assistant-001'
    assert metadata['image_proposal']['legacy_source_assistant_message_id'] == 'legacy-assistant-001'
    print('  Image proposal source metadata translation checks passed.')


def test_legacy_generated_image_can_attach_to_copied_assistant_message():
    """Legacy generated image metadata should attach to the copied assistant card."""
    print('Testing legacy generated image association after collaboration copy...')
    default_sender = {
        'user_id': 'owner-001',
        'display_name': 'Conversation Owner',
        'email': 'owner@example.com',
    }
    copied_assistant = build_collaboration_message_doc_from_legacy(
        conversation_id='shared-conversation-001',
        legacy_message={
            'id': 'legacy-assistant-002',
            'role': 'assistant',
            'content': 'Here is a useful visual.\n\n```simpleimage\n{"title":"Map"}\n```',
            'timestamp': '2026-04-16T13:05:00',
        },
        default_sender_user=default_sender,
    )
    copied_image = build_collaboration_message_doc_from_legacy(
        conversation_id='shared-conversation-001',
        legacy_message={
            'id': 'legacy-image-002',
            'role': 'image',
            'content': '/api/image/legacy-image-002',
            'timestamp': '2026-04-16T13:06:00',
            'metadata': {
                'image_proposal': {
                    'visualId': 'proposal-002',
                    'title': 'Map',
                    'prompt': 'Create a map.',
                    'source_assistant_message_id': 'legacy-assistant-002',
                },
            },
        },
        default_sender_user=default_sender,
    )
    source_to_collaboration_message_ids = {
        'legacy-assistant-002': copied_assistant['id'],
        'legacy-image-002': copied_image['id'],
    }

    translated = translate_image_proposal_source_metadata(
        copied_image['metadata'],
        source_to_collaboration_message_ids,
    )

    assert translated is True
    assert copied_image['metadata']['source_message_id'] == 'legacy-image-002'
    assert copied_image['metadata']['source_role'] == 'image'
    assert copied_image['metadata']['image_proposal']['source_assistant_message_id'] == copied_assistant['id']
    assert copied_image['metadata']['image_proposal']['legacy_source_assistant_message_id'] == 'legacy-assistant-002'
    print('  Legacy generated image association checks passed.')


def test_collaboration_loader_folds_generated_images_into_assistant_cards():
    """Shared frontend loading must reuse the personal image proposal folding contract."""
    print('Testing collaboration frontend folding contract...')
    chat_collaboration_source = read_text(CHAT_COLLABORATION_JS)
    chat_messages_source = read_text(CHAT_MESSAGES_JS)

    assert_contains(
        chat_messages_source,
        [
            'export function getGeneratedImageProposalSourceMessageId(message)',
            'export function groupGeneratedImageProposalMessages(messages = [])',
        ],
        'shared generated image proposal helpers',
    )
    assert_contains(
        chat_collaboration_source,
        [
            'groupGeneratedImageProposalMessages(messages)',
            'decoratedMessage.generated_image_proposals = generatedImageProposalMessages.get(decoratedMessage.id);',
            'getGeneratedImageProposalSourceMessageId(decoratedMessage)',
            'foldGeneratedImageProposalIntoRenderedAssistant(decoratedMessage)',
            'attachGeneratedImageProposalResults(sourceAssistantMessage, [message]);',
        ],
        'collaboration generated image folding',
    )
    print('  Collaboration frontend folding contract checks passed.')


if __name__ == '__main__':
    tests = [
        test_image_proposal_source_metadata_translates_to_collaboration_message_id,
        test_legacy_generated_image_can_attach_to_copied_assistant_message,
        test_collaboration_loader_folds_generated_images_into_assistant_cards,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            import traceback
            print(f'  FAILED: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)