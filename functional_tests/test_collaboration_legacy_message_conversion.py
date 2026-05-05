#!/usr/bin/env python3
# test_collaboration_legacy_message_conversion.py
"""
Functional test for legacy-to-collaboration message conversion helpers.
Version: 0.241.008
Implemented in: 0.241.008

This test ensures that legacy personal-chat messages can be safely converted
into collaboration messages, preserving sender metadata for uploaded content,
mapping assistant replies into shared AI messages, and skipping artifact-only
records that should not appear in the collaborative transcript.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from collaboration_models import (  # noqa: E402
    MESSAGE_KIND_ASSISTANT,
    MESSAGE_KIND_HUMAN,
    build_collaboration_message_doc_from_legacy,
)


DEFAULT_SENDER = {
    'userId': 'owner-legacy-001',
    'displayName': 'Legacy Owner',
    'email': 'owner@example.com',
}


def test_uploaded_image_conversion_preserves_user_sender():
    print('Testing uploaded image conversion...')
    legacy_message = {
        'id': 'legacy-image-001',
        'role': 'image',
        'content': 'https://example.invalid/uploads/diagram.png',
        'filename': 'diagram.png',
        'timestamp': '2026-04-16T13:00:00',
        'metadata': {
            'is_user_upload': True,
        },
    }

    collaboration_message = build_collaboration_message_doc_from_legacy(
        conversation_id='collab-legacy-001',
        legacy_message=legacy_message,
        default_sender_user=DEFAULT_SENDER,
    )

    assert collaboration_message is not None
    assert collaboration_message['role'] == 'user'
    assert collaboration_message['message_kind'] == MESSAGE_KIND_HUMAN
    assert collaboration_message['content'] == '[Uploaded image] diagram.png'
    assert collaboration_message['metadata']['sender']['user_id'] == 'owner-legacy-001'
    assert collaboration_message['metadata']['source_message_id'] == 'legacy-image-001'
    assert collaboration_message['metadata']['source_role'] == 'image'
    assert collaboration_message['metadata']['legacy_image_url'] == 'https://example.invalid/uploads/diagram.png'

    print('  Uploaded image conversion checks passed!')
    return True


def test_assistant_conversion_uses_shared_ai_identity():
    print('Testing assistant response conversion...')
    legacy_message = {
        'id': 'legacy-assistant-001',
        'role': 'assistant',
        'content': 'Here is the consolidated answer.',
        'timestamp': '2026-04-16T13:05:00',
        'agent_display_name': 'Project Copilot',
        'model_deployment_name': 'gpt-4o',
    }

    collaboration_message = build_collaboration_message_doc_from_legacy(
        conversation_id='collab-legacy-002',
        legacy_message=legacy_message,
        default_sender_user=DEFAULT_SENDER,
    )

    assert collaboration_message is not None
    assert collaboration_message['role'] == 'assistant'
    assert collaboration_message['message_kind'] == MESSAGE_KIND_ASSISTANT
    assert collaboration_message['metadata']['sender']['user_id'] == 'assistant'
    assert collaboration_message['metadata']['sender']['display_name'] == 'Project Copilot'
    assert collaboration_message['model_deployment_name'] == 'gpt-4o'

    print('  Assistant conversion checks passed!')
    return True


def test_assistant_artifact_messages_are_skipped():
    print('Testing assistant artifact filtering...')
    legacy_message = {
        'id': 'legacy-artifact-001',
        'role': 'assistant_artifact_chunk',
        'content': '{"partial": true}',
        'timestamp': '2026-04-16T13:06:00',
    }

    collaboration_message = build_collaboration_message_doc_from_legacy(
        conversation_id='collab-legacy-003',
        legacy_message=legacy_message,
        default_sender_user=DEFAULT_SENDER,
    )

    assert collaboration_message is None

    print('  Assistant artifact filtering checks passed!')
    return True


if __name__ == '__main__':
    tests = [
        test_uploaded_image_conversion_preserves_user_sender,
        test_assistant_conversion_uses_shared_ai_identity,
        test_assistant_artifact_messages_are_skipped,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            results.append(test())
        except Exception as exc:
            import traceback
            print(f'  FAILED: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)