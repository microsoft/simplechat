#!/usr/bin/env python3
# test_collaborative_conversation_foundation.py
"""
Functional test for collaborative conversation backend foundation.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures that the pure collaboration model helpers correctly build
personal and group collaborative conversations, preserve pending invite state,
apply invite acceptance, and build message documents for explicit reply-aware
multi-user chat flows.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from collaboration_models import (  # noqa: E402
    GROUP_MULTI_USER_CHAT_TYPE,
    PERSONAL_MULTI_USER_CHAT_TYPE,
    apply_personal_invite_response,
    build_collaboration_message_doc,
    build_group_collaboration_conversation,
    build_personal_collaboration_conversation,
    normalize_collaboration_user,
)


def test_personal_conversation_builder_and_acceptance():
    print('Testing personal collaborative conversation builder...')
    creator = normalize_collaboration_user({
        'userId': 'owner-001',
        'displayName': 'Owner User',
        'email': 'owner@example.com',
    })
    invitee = normalize_collaboration_user({
        'id': 'member-001',
        'displayName': 'Member User',
        'email': 'member@example.com',
    })

    conversation_doc = build_personal_collaboration_conversation(
        title='Roadmap Review',
        creator_user=creator,
        invited_participants=[invitee],
        conversation_id='conv-personal-001',
        created_at='2026-04-16T10:00:00',
    )

    assert conversation_doc['chat_type'] == PERSONAL_MULTI_USER_CHAT_TYPE
    assert conversation_doc['participant_count'] == 1
    assert conversation_doc['pending_invite_count'] == 1
    assert conversation_doc['accepted_participant_ids'] == ['owner-001']
    assert conversation_doc['pending_participant_ids'] == ['member-001']

    apply_personal_invite_response(
        conversation_doc,
        invited_user_id='member-001',
        action='accept',
        responded_at='2026-04-16T10:05:00',
    )

    assert conversation_doc['participant_count'] == 2
    assert conversation_doc['pending_invite_count'] == 0
    assert set(conversation_doc['accepted_participant_ids']) == {'owner-001', 'member-001'}

    accepted_participant = next(
        participant for participant in conversation_doc['participants']
        if participant['user_id'] == 'member-001'
    )
    assert accepted_participant['status'] == 'accepted'
    assert accepted_participant['joined_at'] == '2026-04-16T10:05:00'

    print('  Personal collaborative conversation checks passed!')
    return True


def test_group_conversation_builder():
    print('Testing group collaborative conversation builder...')
    creator = normalize_collaboration_user({
        'userId': 'owner-002',
        'displayName': 'Group Owner',
        'email': 'group.owner@example.com',
    })

    conversation_doc = build_group_collaboration_conversation(
        title='',
        creator_user=creator,
        group_id='group-123',
        group_name='Finance',
        conversation_id='conv-group-001',
        created_at='2026-04-16T11:00:00',
    )

    assert conversation_doc['chat_type'] == GROUP_MULTI_USER_CHAT_TYPE
    assert conversation_doc['scope']['group_id'] == 'group-123'
    assert conversation_doc['scope']['group_name'] == 'Finance'
    assert conversation_doc['scope']['allowed_scope_types'] == ['group', 'public']
    assert conversation_doc['participant_count'] == 1
    assert conversation_doc['pending_invite_count'] == 0

    print('  Group collaborative conversation checks passed!')
    return True


def test_message_builder():
    print('Testing collaborative message builder...')
    sender = normalize_collaboration_user({
        'userId': 'member-002',
        'displayName': 'Contributor',
        'email': 'contributor@example.com',
    })

    message_doc = build_collaboration_message_doc(
        conversation_id='conv-personal-002',
        sender_user=sender,
        content='I agree with the proposal.',
        reply_to_message_id='message-previous-001',
        timestamp='2026-04-16T12:00:00',
    )

    assert message_doc['role'] == 'user'
    assert message_doc['reply_to_message_id'] == 'message-previous-001'
    assert message_doc['metadata']['sender']['user_id'] == 'member-002'
    assert message_doc['metadata']['explicit_ai_invocation'] is False
    assert message_doc['metadata']['last_message_preview'] == 'I agree with the proposal.'

    print('  Collaborative message checks passed!')
    return True


if __name__ == '__main__':
    tests = [
        test_personal_conversation_builder_and_acceptance,
        test_group_conversation_builder,
        test_message_builder,
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