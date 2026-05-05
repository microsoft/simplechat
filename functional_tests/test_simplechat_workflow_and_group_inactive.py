# test_simplechat_workflow_and_group_inactive.py
#!/usr/bin/env python3
"""
Functional test for SimpleChat workflow creation and group inactive controls.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures SimpleChat can create personal workflows with the normal
workflow payload shape and can make groups inactive only when the current user
has the same admin access required by Control Center.
"""

import importlib
import os
import sys
import traceback

from flask import Flask, session


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


class FakeGroupsContainer:
    def __init__(self):
        self.upserted_items = []

    def upsert_item(self, document):
        stored_document = dict(document)
        self.upserted_items.append(stored_document)
        return stored_document


def test_create_personal_workflow_for_current_user_builds_expected_payload():
    """SimpleChat should map conversational workflow inputs into the standard personal workflow payload."""
    print('🔍 Testing SimpleChat personal workflow creation...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    saved_calls = []
    logged_creations = []

    with PatchSet(
        operations_module,
        {
            'get_settings': lambda: {'allow_user_workflows': True},
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'save_personal_workflow': lambda user_id, workflow_data, actor_user_id=None: saved_calls.append(
                {
                    'user_id': user_id,
                    'workflow_data': dict(workflow_data),
                    'actor_user_id': actor_user_id,
                }
            ) or {
                'id': 'workflow-123',
                'name': workflow_data['name'],
                'runner_type': workflow_data['runner_type'],
                'trigger_type': workflow_data['trigger_type'],
            },
            'log_workflow_creation': lambda **kwargs: logged_creations.append(dict(kwargs)),
        },
    ):
        result = operations_module.create_personal_workflow_for_current_user(
            name='Stale Group Review',
            description='Review groups that may need cleanup',
            task_prompt='Review group activity and summarize stale groups.',
            runner_type='agent',
            trigger_type='interval',
            selected_agent_name='researcher_agent',
            selected_agent_is_global=True,
            alert_priority='medium',
            is_enabled=False,
            schedule_value=2,
            schedule_unit='hours',
            conversation_id='conversation-123',
        )

    assert result['workflow']['id'] == 'workflow-123'
    assert len(saved_calls) == 1
    assert saved_calls[0]['user_id'] == 'user-123'
    assert saved_calls[0]['actor_user_id'] == 'user-123'
    assert saved_calls[0]['workflow_data'] == {
        'name': 'Stale Group Review',
        'description': 'Review groups that may need cleanup',
        'task_prompt': 'Review group activity and summarize stale groups.',
        'runner_type': 'agent',
        'trigger_type': 'interval',
        'alert_priority': 'medium',
        'is_enabled': False,
        'conversation_id': 'conversation-123',
        'selected_agent': {
            'id': '',
            'name': 'researcher_agent',
            'is_global': True,
        },
        'schedule': {
            'value': 2,
            'unit': 'hours',
        },
    }
    assert logged_creations == [
        {
            'user_id': 'user-123',
            'workflow_id': 'workflow-123',
            'workflow_name': 'Stale Group Review',
            'runner_type': 'agent',
            'trigger_type': 'interval',
        }
    ]

    print('✅ SimpleChat personal workflow creation verified.')


def test_make_group_inactive_for_current_user_requires_admin_access():
    """SimpleChat should reject group inactive requests when the current user lacks Control Center admin access."""
    print('🔍 Testing SimpleChat group inactive permission checks...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    app = Flask(__name__)
    app.secret_key = 'simplechat-test-secret'

    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'get_settings': lambda: {'require_member_of_control_center_admin': False},
        },
    ):
        with app.test_request_context('/'):
            session['user'] = {
                'oid': 'user-123',
                'preferred_username': 'user@example.com',
                'roles': ['User'],
            }
            try:
                operations_module.make_group_inactive_for_current_user(group_id='group-123')
                raise AssertionError('Expected PermissionError when the caller lacks admin access')
            except PermissionError as exc:
                assert str(exc) == 'Insufficient permissions (Admin role required)'

    print('✅ SimpleChat group inactive permission rejection verified.')


def test_make_group_inactive_for_current_user_updates_status_and_history():
    """SimpleChat should mark the target group inactive and log the change when admin access is present."""
    print('🔍 Testing SimpleChat group inactive success path...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    fake_groups_container = FakeGroupsContainer()
    logged_status_changes = []
    logged_events = []
    app = Flask(__name__)
    app.secret_key = 'simplechat-test-secret'

    with PatchSet(
        operations_module,
        {
            'cosmos_groups_container': fake_groups_container,
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'admin@example.com',
                'displayName': 'Admin User',
                'email': 'admin@example.com',
            },
            'get_settings': lambda: {'require_member_of_control_center_admin': True},
            'find_group_by_id': lambda group_id: {
                'id': group_id,
                'name': 'Quarterly Review',
                'status': 'active',
                'statusHistory': [],
            },
            'log_group_status_change': lambda **kwargs: logged_status_changes.append(dict(kwargs)),
            'log_event': lambda message, extra=None, **kwargs: logged_events.append(
                {
                    'message': message,
                    'extra': dict(extra or {}),
                    'kwargs': dict(kwargs),
                }
            ),
            'require_active_group': lambda user_id: (_ for _ in ()).throw(AssertionError('Active group lookup should not run when default_group_id is provided')),
        },
    ):
        with app.test_request_context('/'):
            session['user'] = {
                'oid': 'admin-123',
                'preferred_username': 'admin@example.com',
                'roles': ['ControlCenterAdmin'],
            }
            result = operations_module.make_group_inactive_for_current_user(
                reason='No recent activity',
                default_group_id='group-123',
            )

    assert result['old_status'] == 'active'
    assert result['new_status'] == 'inactive'
    assert len(fake_groups_container.upserted_items) == 1
    updated_group = fake_groups_container.upserted_items[0]
    assert updated_group['status'] == 'inactive'
    assert len(updated_group['statusHistory']) == 1
    assert updated_group['statusHistory'][0]['old_status'] == 'active'
    assert updated_group['statusHistory'][0]['new_status'] == 'inactive'
    assert updated_group['statusHistory'][0]['changed_by_user_id'] == 'admin-123'
    assert updated_group['statusHistory'][0]['changed_by_email'] == 'admin@example.com'
    assert updated_group['statusHistory'][0]['reason'] == 'No recent activity'
    assert logged_status_changes == [
        {
            'group_id': 'group-123',
            'group_name': 'Quarterly Review',
            'old_status': 'active',
            'new_status': 'inactive',
            'changed_by_user_id': 'admin-123',
            'changed_by_email': 'admin@example.com',
            'reason': 'No recent activity',
        }
    ]
    assert logged_events[0]['message'] == '[SimpleChat] Group marked inactive'
    assert logged_events[0]['extra']['group_id'] == 'group-123'

    print('✅ SimpleChat group inactive success path verified.')


def test_simplechat_plugin_forwards_new_workflow_and_group_status_calls():
    """SimpleChat plugin should forward new workflow and group inactive operations with the expected arguments."""
    print('🔍 Testing SimpleChat plugin forwarding for new capabilities...')

    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')
    workflow_calls = []
    group_status_calls = []

    with PatchSet(
        plugin_module,
        {
            'create_personal_workflow_for_current_user': lambda **kwargs: workflow_calls.append(dict(kwargs)) or {
                'workflow': {
                    'id': 'workflow-123',
                    'name': kwargs['name'],
                }
            },
            'make_group_inactive_for_current_user': lambda **kwargs: group_status_calls.append(dict(kwargs)) or {
                'group': {
                    'id': kwargs.get('group_id') or kwargs.get('default_group_id'),
                    'status': 'inactive',
                }
            },
        },
    ):
        plugin = plugin_module.SimpleChatPlugin(
            {
                'id': 'simplechat-action-id',
                'name': 'simplechat_tools',
                'type': 'simplechat',
                'default_group_id': 'group-123',
                'enabled_functions': [
                    'create_personal_workflow',
                    'make_group_inactive',
                ],
            }
        )

        workflow_result = plugin.create_personal_workflow(
            name='Research Roundup',
            task_prompt='Summarize new documents.',
            runner_type='model',
            trigger_type='manual',
        )
        group_result = plugin.make_group_inactive(reason='Cleanup old workspace')

    assert workflow_result['success'] is True
    assert workflow_calls == [
        {
            'name': 'Research Roundup',
            'task_prompt': 'Summarize new documents.',
            'description': '',
            'runner_type': 'model',
            'trigger_type': 'manual',
            'selected_agent_name': '',
            'selected_agent_id': '',
            'selected_agent_is_global': False,
            'model_endpoint_id': '',
            'model_id': '',
            'alert_priority': 'none',
            'is_enabled': True,
            'schedule_value': 1,
            'schedule_unit': 'hours',
            'conversation_id': '',
        }
    ]
    assert group_result['success'] is True
    assert group_status_calls == [
        {
            'group_id': '',
            'reason': 'Cleanup old workspace',
            'default_group_id': 'group-123',
        }
    ]

    print('✅ SimpleChat plugin forwarding for new capabilities verified.')


if __name__ == '__main__':
    tests = [
        test_create_personal_workflow_for_current_user_builds_expected_payload,
        test_make_group_inactive_for_current_user_requires_admin_access,
        test_make_group_inactive_for_current_user_updates_status_and_history,
        test_simplechat_plugin_forwards_new_workflow_and_group_status_calls,
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