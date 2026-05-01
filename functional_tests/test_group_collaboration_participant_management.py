# test_group_collaboration_participant_management.py
"""
Functional test for group collaborative participant management.
Version: 0.241.034
Implemented in: 0.241.034

This test ensures group multi-user conversations use explicit participant
invites, preserve participant lifecycle state, and expose the new group
conversion and member-management wiring across the backend and chat UI.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from collaboration_models import (  # noqa: E402
    MEMBERSHIP_STATUS_PENDING,
    add_personal_pending_participants,
    apply_personal_invite_response,
    build_group_collaboration_conversation,
    normalize_collaboration_user,
    remove_personal_participant,
)


ROUTE_FILE = APP_ROOT / 'route_backend_collaboration.py'
HELPER_FILE = APP_ROOT / 'functions_collaboration.py'
CHAT_COLLABORATION_FILE = APP_ROOT / 'static' / 'js' / 'chat' / 'chat-collaboration.js'
CHAT_CONVERSATIONS_FILE = APP_ROOT / 'static' / 'js' / 'chat' / 'chat-conversations.js'
CHAT_SIDEBAR_FILE = APP_ROOT / 'static' / 'js' / 'chat' / 'chat-sidebar-conversations.js'


def read_text(path):
    return path.read_text(encoding='utf-8')


def test_group_builder_uses_invited_member_visibility():
    print('🔍 Testing invite-managed group conversation builder...')

    creator = normalize_collaboration_user({
        'userId': 'owner-001',
        'displayName': 'Group Owner',
        'email': 'owner@example.com',
    })
    invitee = normalize_collaboration_user({
        'id': 'member-001',
        'displayName': 'Member One',
        'email': 'member.one@example.com',
    })

    conversation_doc = build_group_collaboration_conversation(
        title='Security Review',
        creator_user=creator,
        group_id='group-001',
        group_name='Security Team',
        invited_participants=[invitee],
        conversation_id='group-collab-001',
        created_at='2026-04-17T10:00:00',
    )

    assert conversation_doc['scope']['visibility_mode'] == 'invited_members'
    assert conversation_doc['participant_count'] == 1
    assert conversation_doc['pending_invite_count'] == 1
    assert conversation_doc['accepted_participant_ids'] == ['owner-001']
    assert conversation_doc['pending_participant_ids'] == ['member-001']

    pending_invitee = next(
        participant for participant in conversation_doc['participants']
        if participant['user_id'] == 'member-001'
    )
    assert pending_invitee['status'] == MEMBERSHIP_STATUS_PENDING
    assert pending_invitee['role'] == 'member'

    print('✅ Invite-managed group builder checks passed.')


def test_group_participant_lifecycle_helpers():
    print('🔍 Testing group participant lifecycle helpers...')

    creator = normalize_collaboration_user({
        'userId': 'owner-002',
        'displayName': 'Owner Two',
        'email': 'owner.two@example.com',
    })
    first_invitee = normalize_collaboration_user({
        'id': 'member-002',
        'displayName': 'Member Two',
        'email': 'member.two@example.com',
    })
    second_invitee = normalize_collaboration_user({
        'id': 'member-003',
        'displayName': 'Member Three',
        'email': 'member.three@example.com',
    })

    conversation_doc = build_group_collaboration_conversation(
        title='Incident Bridge',
        creator_user=creator,
        group_id='group-002',
        group_name='Incident Response',
        invited_participants=[first_invitee],
        conversation_id='group-collab-002',
        created_at='2026-04-17T11:00:00',
    )

    apply_personal_invite_response(
        conversation_doc,
        invited_user_id='member-002',
        action='accept',
        responded_at='2026-04-17T11:05:00',
    )
    assert set(conversation_doc['accepted_participant_ids']) == {'owner-002', 'member-002'}

    added_participants = add_personal_pending_participants(
        conversation_doc,
        [second_invitee],
        invited_at='2026-04-17T11:10:00',
    )
    assert len(added_participants) == 1
    assert added_participants[0]['user_id'] == 'member-003'
    assert 'member-003' in conversation_doc['pending_participant_ids']

    removed_participant = remove_personal_participant(
        conversation_doc,
        participant_user_id='member-002',
        removed_at='2026-04-17T11:15:00',
    )
    assert removed_participant['user_id'] == 'member-002'
    assert removed_participant['status'] == 'removed'
    assert 'member-002' not in conversation_doc['accepted_participant_ids']

    re_invited_participants = add_personal_pending_participants(
        conversation_doc,
        [first_invitee],
        invited_at='2026-04-17T11:20:00',
    )
    assert len(re_invited_participants) == 1
    assert re_invited_participants[0]['user_id'] == 'member-002'
    assert re_invited_participants[0]['status'] == MEMBERSHIP_STATUS_PENDING

    print('✅ Group participant lifecycle checks passed.')


def test_group_participant_management_wiring():
    print('🔍 Testing group participant-management wiring...')

    route_source = read_text(ROUTE_FILE)
    helper_source = read_text(HELPER_FILE)
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    conversation_source = read_text(CHAT_CONVERSATIONS_FILE)
    sidebar_source = read_text(CHAT_SIDEBAR_FILE)

    assert '/api/collaboration/conversations/from-group/<conversation_id>/members' in route_source
    assert 'def ensure_group_collaboration_for_legacy_conversation' in helper_source
    assert 'Only current group members can be added to this shared conversation' in helper_source
    assert 'def is_invited_group_collaboration_conversation' in helper_source

    assert 'group-single-user' in collaboration_source
    assert 'group_multi_user' in collaboration_source
    assert '/api/collaboration/conversations/from-group/${conversationId}/members' in collaboration_source
    assert 'searchConversationParticipantCandidates' in collaboration_source

    assert 'group-single-user' in conversation_source
    assert 'group_multi_user' in conversation_source
    assert 'group-single-user' in sidebar_source
    assert 'group_multi_user' in sidebar_source

    print('✅ Group participant-management wiring checks passed.')


if __name__ == '__main__':
    tests = [
        test_group_builder_uses_invited_member_visibility,
        test_group_participant_lifecycle_helpers,
        test_group_participant_management_wiring,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            results.append(False)

    passed_count = sum(1 for result in results if result)
    print(f'\n📊 Results: {passed_count}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)