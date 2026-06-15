#!/usr/bin/env python3
# test_user_profile_idor_authorization.py
"""
Functional test for user profile endpoint object authorization.
Version: 0.241.203
Implemented in: 0.241.202

This test ensures that cross-user profile lookups are blocked unless the caller
is the same user, an admin, or has a legitimate app relationship with the target.
It also verifies the BAC checker flags the previous direct user-settings read.
"""

import importlib.util
import sys
import types
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT_DIR / 'application' / 'single_app' / 'route_backend_users.py'
CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_broken_access_control.py'


class FakeCosmosResourceNotFoundError(Exception):
    """Minimal stand-in for Azure Cosmos not-found errors."""


class FakeUserSettingsContainer:
    def __init__(self):
        self.documents = {}
        self.read_calls = []

    def read_item(self, item, partition_key):
        self.read_calls.append((item, partition_key))
        if item not in self.documents:
            raise FakeCosmosResourceNotFoundError()
        return self.documents[item]


class FakeDocumentContainer:
    def __init__(self):
        self.has_relationship = False
        self.query_calls = []

    def query_items(self, **kwargs):
        self.query_calls.append(kwargs)
        return ['document-relationship'] if self.has_relationship else []


class FakeCollaborationStateContainer:
    def __init__(self):
        self.actor_states = []
        self.target_states = {}
        self.query_calls = []
        self.read_calls = []

    def query_items(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.actor_states

    def read_item(self, item, partition_key):
        self.read_calls.append((item, partition_key))
        if item not in self.target_states:
            raise FakeCosmosResourceNotFoundError()
        return self.target_states[item]


class UserProfileTestContext:
    def __init__(self):
        self.user_settings_container = FakeUserSettingsContainer()
        self.document_container = FakeDocumentContainer()
        self.collaboration_state_container = FakeCollaborationStateContainer()
        self.session = {'user': {'oid': 'actor-user', 'roles': ['User']}}
        self.current_user_id = 'actor-user'
        self.groups = []
        self.logged_events = []


def _identity_decorator(function):
    return function


def install_route_stubs(context):
    """Install lightweight modules needed to import route_backend_users.py."""
    config_module = types.ModuleType('config')
    config_module.cosmos_user_settings_container = context.user_settings_container
    config_module.cosmos_user_documents_container = context.document_container
    config_module.cosmos_collaboration_user_state_container = context.collaboration_state_container
    config_module.exceptions = types.SimpleNamespace(CosmosResourceNotFoundError=FakeCosmosResourceNotFoundError)
    config_module.logging = __import__('logging')
    config_module.session = context.session
    config_module.request = types.SimpleNamespace(args={}, get_json=lambda: {})
    config_module.jsonify = lambda payload=None, **kwargs: payload if payload is not None else kwargs

    collaboration_models_module = types.ModuleType('collaboration_models')
    collaboration_models_module.COLLABORATION_KIND = 'collaborative'
    collaboration_models_module.MEMBERSHIP_STATUS_ACCEPTED = 'accepted'
    collaboration_models_module.MEMBERSHIP_STATUS_PENDING = 'pending'
    collaboration_models_module.get_collaboration_user_state_doc_id = lambda user_id, conversation_id: f'{user_id}:{conversation_id}'
    collaboration_models_module.normalize_collaboration_user = lambda raw_user, fallback_user_id=None: {
        'user_id': raw_user.get('user_id') or raw_user.get('id') or fallback_user_id,
        'display_name': raw_user.get('display_name', ''),
        'email': raw_user.get('email', ''),
    } if isinstance(raw_user, dict) and (raw_user.get('user_id') or raw_user.get('id') or fallback_user_id) else None

    appinsights_module = types.ModuleType('functions_appinsights')
    appinsights_module.log_event = lambda *args, **kwargs: context.logged_events.append((args, kwargs))

    authentication_module = types.ModuleType('functions_authentication')
    authentication_module.get_current_user_id = lambda: context.current_user_id
    authentication_module.login_required = _identity_decorator
    authentication_module.user_required = _identity_decorator

    group_module = types.ModuleType('functions_group')
    group_module.check_group_status_allows_operation = lambda group_doc, operation: (group_doc.get('status', 'active') != 'inactive', '')
    group_module.get_user_groups = lambda user_id: context.groups
    group_module.get_user_role_in_group = lambda group_doc, user_id: group_doc.get('roles', {}).get(user_id)
    group_module.update_active_group_for_user = lambda *args, **kwargs: None

    public_workspaces_module = types.ModuleType('functions_public_workspaces')
    public_workspaces_module.update_active_public_workspace_for_user = lambda *args, **kwargs: None

    settings_module = types.ModuleType('functions_settings')
    settings_module.get_user_settings = lambda user_id: {}
    settings_module.update_user_settings = lambda user_id, settings: True

    swagger_module = types.ModuleType('swagger_wrapper')
    swagger_module.swagger_route = lambda *args, **kwargs: _identity_decorator
    swagger_module.get_auth_security = lambda: []

    sys.modules.update({
        'config': config_module,
        'collaboration_models': collaboration_models_module,
        'functions_appinsights': appinsights_module,
        'functions_authentication': authentication_module,
        'functions_group': group_module,
        'functions_public_workspaces': public_workspaces_module,
        'functions_settings': settings_module,
        'swagger_wrapper': swagger_module,
    })


def load_route_module(context):
    """Load route_backend_users.py with stubbed dependencies."""
    install_route_stubs(context)
    module_name = 'route_backend_users_user_profile_test'
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, ROUTE_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_checker_module():
    """Load the BAC checker module from disk."""
    module_name = 'check_broken_access_control_user_profile_test'
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, CHECKER_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def prepare_context():
    """Create a fresh route module and fake data context."""
    context = UserProfileTestContext()
    context.user_settings_container.documents = {
        'actor-user': {'id': 'actor-user', 'email': 'actor@example.com', 'display_name': 'Actor User', 'settings': {}},
        'target-user': {'id': 'target-user', 'email': 'target@example.com', 'display_name': 'Target User', 'settings': {'profileImage': 'data:image/png;base64,abc'}},
    }
    return context, load_route_module(context)


def test_self_lookup_allowed():
    """A user may read their own profile document."""
    context, module = prepare_context()
    _, target_user_id, user_doc = module._read_authorized_user_profile_document('actor-user')

    assert target_user_id == 'actor-user'
    assert user_doc['email'] == 'actor@example.com'
    assert context.user_settings_container.read_calls == [('actor-user', 'actor-user')]


def test_unrelated_user_lookup_denied_before_read():
    """An unrelated low-privilege user must be denied before the target document read."""
    context, module = prepare_context()

    try:
        module._read_authorized_user_profile_document('target-user')
    except PermissionError:
        pass
    else:
        raise AssertionError('Expected unrelated cross-user lookup to be denied')

    assert context.user_settings_container.read_calls == []
    assert any('Denied cross-user profile lookup' in event[0][0] for event in context.logged_events)


def test_admin_and_relationship_lookups_allowed():
    """Admins and users with documented app relationships may read target profiles."""
    context, module = prepare_context()
    context.session['user']['roles'] = ['Admin']
    _, target_user_id, _ = module._read_authorized_user_profile_document('target-user')
    assert target_user_id == 'target-user'

    context, module = prepare_context()
    context.groups = [{'roles': {'target-user': 'User'}}]
    _, target_user_id, _ = module._read_authorized_user_profile_document('target-user')
    assert target_user_id == 'target-user'

    context, module = prepare_context()
    context.document_container.has_relationship = True
    _, target_user_id, _ = module._read_authorized_user_profile_document('target-user')
    assert target_user_id == 'target-user'

    context, module = prepare_context()
    context.collaboration_state_container.actor_states = [{'conversation_id': 'conversation-1'}]
    context.collaboration_state_container.target_states = {
        'target-user:conversation-1': {'membership_status': 'accepted'},
    }
    _, target_user_id, _ = module._read_authorized_user_profile_document('target-user')
    assert target_user_id == 'target-user'


def test_bac_checker_flags_previous_direct_profile_read():
    """The BAC checker must catch direct user-settings reads in profile routes."""
    checker = load_checker_module()
    vulnerable_source = """
def register_route_backend_users(app):
    @app.route('/api/user/info/<user_id>', methods=['GET'])
    @login_required
    @user_required
    def api_get_user_info(user_id):
        return cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
""".strip()

    issues = checker.inspect_source(
        ROOT_DIR / 'application' / 'single_app' / 'route_backend_users.py',
        vulnerable_source,
    )
    messages = [issue.message for issue in issues]
    assert any('Avoid direct user settings reads from request-derived user_id' in message for message in messages), messages


if __name__ == '__main__':
    tests = [
        test_self_lookup_allowed,
        test_unrelated_user_lookup_denied_before_read,
        test_admin_and_relationship_lookups_allowed,
        test_bac_checker_flags_previous_direct_profile_read,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)