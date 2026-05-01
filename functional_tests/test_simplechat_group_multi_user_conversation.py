# test_simplechat_group_multi_user_conversation.py
"""
Functional test for SimpleChat group multi-user conversation guidance.
Version: 0.241.038
Implemented in: 0.241.038

This test ensures the SimpleChat group conversation capability is described as
an invite-managed group multi-user path and returns guidance that current
group members still need to be added as participants with the dedicated invite
operation.
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


def test_simplechat_group_conversation_metadata_describes_invite_managed_group_chat():
    """SimpleChat metadata should describe group conversation creation as an invite-managed multi-user flow."""
    print('🔍 Testing SimpleChat group multi-user conversation metadata...')

    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')
    plugin = plugin_module.SimpleChatPlugin(
        {
            'id': 'simplechat-action-id',
            'name': 'simplechat_tools',
            'type': 'simplechat',
            'enabled_functions': ['create_group_conversation'],
        }
    )

    method_metadata = next(
        method for method in plugin.metadata['methods']
        if method['name'] == 'create_group_conversation'
    )
    description = method_metadata['description'].lower()

    assert 'multi-user' in description
    assert 'invite-managed' in description
    assert 'group members' in description
    assert 'grant access' in description

    print('✅ SimpleChat group conversation metadata verified.')


def test_simplechat_group_conversation_result_explains_participant_management():
    """SimpleChat should return an explicit message that participants must be added to the created group conversation."""
    print('🔍 Testing SimpleChat group multi-user conversation result messaging...')

    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')

    with PatchSet(
        plugin_module,
        {
            'create_group_collaboration_conversation_for_current_user': lambda **kwargs: (
                {
                    'id': 'conversation-123',
                    'title': 'Incident Coordination',
                },
                {
                    'user_id': 'user-123',
                },
                {
                    'id': kwargs.get('group_id') or kwargs.get('default_group_id'),
                    'name': 'Defender Suspicious Activity - Malicious URL in AI Agent Tool Response',
                },
            ),
        },
    ):
        plugin = plugin_module.SimpleChatPlugin(
            {
                'id': 'simplechat-action-id',
                'name': 'simplechat_tools',
                'type': 'simplechat',
                'default_group_id': 'group-123',
                'enabled_functions': ['create_group_conversation'],
            }
        )
        result = plugin.create_group_conversation()

    assert result['success'] is True
    assert result['conversation']['id'] == 'conversation-123'
    assert 'group multi-user conversation' in result['message'].lower()
    assert 'invite_group_conversation_members' in result['message'].lower()
    assert 'add current group members as participants' in result['message'].lower()

    print('✅ SimpleChat group conversation result messaging verified.')


if __name__ == '__main__':
    tests = [
        test_simplechat_group_conversation_metadata_describes_invite_managed_group_chat,
        test_simplechat_group_conversation_result_explains_participant_management,
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