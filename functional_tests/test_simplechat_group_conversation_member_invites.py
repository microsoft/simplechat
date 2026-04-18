# test_simplechat_group_conversation_member_invites.py
#!/usr/bin/env python3
"""
Functional test for SimpleChat group conversation member invites.
Version: 0.241.038
Implemented in: 0.241.038

This test ensures SimpleChat can invite current group members into an existing
invite-managed group multi-user conversation and exposes the new capability
through the plugin surface.
"""

import importlib
import os
import sys
import traceback


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class PatchSet:
    def __init__(self, module, replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for attribute_name, replacement in self.replacements.items():
            self.originals[attribute_name] = getattr(self.module, attribute_name)
            setattr(self.module, attribute_name, replacement)
        return self

    def __exit__(self, exc_type, exc, tb):
        for attribute_name, original in self.originals.items():
            setattr(self.module, attribute_name, original)
        return False


def test_invite_group_conversation_members_for_current_user_builds_invite_payload():
    """SimpleChat should resolve identifiers and invite the matching current group members."""
    print('🔍 Testing SimpleChat group conversation member invites...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    invite_calls = []

    with PatchSet(
        operations_module,
        {
            '_require_collaboration_feature_enabled': lambda: None,
            '_require_current_user_info': lambda: {
                'userId': 'owner-123',
                'email': 'owner@example.com',
                'displayName': 'Owner User',
            },
            'get_collaboration_conversation': lambda conversation_id: {
                'id': conversation_id,
                'title': 'Incident Coordination',
                'chat_type': 'group_multi_user',
                'scope': {
                    'group_id': 'group-123',
                    'group_name': 'Ops Group',
                    'visibility_mode': 'invited_members',
                },
            },
            'resolve_directory_user': lambda user_identifier='': {
                'member.one@example.com': {
                    'id': 'member-001',
                    'displayName': 'Member One',
                    'email': 'member.one@example.com',
                },
                'member.two@example.com': {
                    'id': 'member-002',
                    'displayName': 'Member Two',
                    'email': 'member.two@example.com',
                },
            }[user_identifier],
            'invite_personal_collaboration_participants': lambda conversation_id, owner_user_id, participants_to_add: invite_calls.append(
                {
                    'conversation_id': conversation_id,
                    'owner_user_id': owner_user_id,
                    'participants_to_add': list(participants_to_add),
                }
            ) or (
                {
                    'id': conversation_id,
                    'title': 'Incident Coordination',
                    'chat_type': 'group_multi_user',
                    'scope': {
                        'group_id': 'group-123',
                        'group_name': 'Ops Group',
                        'visibility_mode': 'invited_members',
                    },
                },
                [
                    {
                        'user_id': 'member-001',
                        'user_display_name': 'Member One',
                        'user_email': 'member.one@example.com',
                        'membership_status': 'pending',
                    },
                    {
                        'user_id': 'member-002',
                        'user_display_name': 'Member Two',
                        'user_email': 'member.two@example.com',
                        'membership_status': 'pending',
                    },
                ],
            ),
        },
    ):
        result = operations_module.invite_group_conversation_members_for_current_user(
            conversation_id='conversation-123',
            participant_identifiers='member.one@example.com, member.two@example.com',
        )

    assert invite_calls == [
        {
            'conversation_id': 'conversation-123',
            'owner_user_id': 'owner-123',
            'participants_to_add': [
                {
                    'user_id': 'member-001',
                    'display_name': 'Member One',
                    'email': 'member.one@example.com',
                },
                {
                    'user_id': 'member-002',
                    'display_name': 'Member Two',
                    'email': 'member.two@example.com',
                },
            ],
        }
    ]
    assert result['group']['id'] == 'group-123'
    assert len(result['invited_participants']) == 2
    assert 'invited 2 current group member(s)' in result['message'].lower()

    print('✅ SimpleChat group conversation member invites verified.')


def test_invite_group_conversation_members_for_current_user_rejects_non_group_chat():
    """SimpleChat should reject invite requests for non-group conversations."""
    print('🔍 Testing SimpleChat non-group invite rejection...')

    operations_module = importlib.import_module('functions_simplechat_operations')

    with PatchSet(
        operations_module,
        {
            '_require_collaboration_feature_enabled': lambda: None,
            '_require_current_user_info': lambda: {
                'userId': 'owner-123',
                'email': 'owner@example.com',
                'displayName': 'Owner User',
            },
            'get_collaboration_conversation': lambda conversation_id: {
                'id': conversation_id,
                'title': 'Personal Collaboration',
                'chat_type': 'personal_multi_user',
            },
        },
    ):
        try:
            operations_module.invite_group_conversation_members_for_current_user(
                conversation_id='conversation-123',
                participant_identifiers='member.one@example.com',
            )
            raise AssertionError('Expected ValueError for a non-group collaborative conversation')
        except ValueError as exc:
            assert str(exc) == 'conversation_id must reference a group multi-user conversation'

    print('✅ SimpleChat non-group invite rejection verified.')


def test_simplechat_plugin_exposes_and_forwards_group_member_invites():
    """SimpleChat plugin metadata and forwarding should expose the group invite capability."""
    print('🔍 Testing SimpleChat plugin forwarding for group member invites...')

    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')
    helper_calls = []

    with PatchSet(
        plugin_module,
        {
            'invite_group_conversation_members_for_current_user': lambda **kwargs: helper_calls.append(dict(kwargs)) or {
                'conversation': {
                    'id': kwargs['conversation_id'],
                    'title': 'Incident Coordination',
                },
                'group': {
                    'id': 'group-123',
                    'name': 'Ops Group',
                },
                'invited_participants': [
                    {
                        'user_id': 'member-001',
                        'display_name': 'Member One',
                        'email': 'member.one@example.com',
                        'membership_status': 'pending',
                    }
                ],
            },
        },
    ):
        plugin = plugin_module.SimpleChatPlugin(
            {
                'id': 'simplechat-action-id',
                'name': 'simplechat_tools',
                'type': 'simplechat',
                'enabled_functions': ['invite_group_conversation_members'],
            }
        )
        result = plugin.invite_group_conversation_members(
            conversation_id='conversation-123',
            participant_identifiers='member.one@example.com',
        )

    method_metadata = next(
        method for method in plugin.metadata['methods']
        if method['name'] == 'invite_group_conversation_members'
    )

    assert 'current group members' in method_metadata['description'].lower()
    assert helper_calls == [
        {
            'conversation_id': 'conversation-123',
            'participant_identifiers': 'member.one@example.com',
        }
    ]
    assert result['success'] is True
    assert result['conversation']['id'] == 'conversation-123'

    print('✅ SimpleChat plugin group member invite forwarding verified.')


if __name__ == '__main__':
    tests = [
        test_invite_group_conversation_members_for_current_user_builds_invite_payload,
        test_invite_group_conversation_members_for_current_user_rejects_non_group_chat,
        test_simplechat_plugin_exposes_and_forwards_group_member_invites,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)