#!/usr/bin/env python3
# test_plugin_logging_clear_logs_authorization.py
"""
Functional test for plugin logging admin authorization hardening.
Version: 0.241.022
Implemented in: 0.241.013; 0.241.014; 0.241.022

This test ensures only admins can clear the shared plugin invocation history
or read the cross-user recent invocation feed, non-admin users receive a
forbidden response without mutating logger state, and unauthenticated
requests still receive the existing unauthorized response.
"""

import copy
import importlib
import os
import sys
import types

from flask import Flask, jsonify, request, session
import werkzeug


if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = '3'


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'application', 'single_app'))


class FakePluginLogger:
    """In-memory plugin logger for authorization tests."""

    def __init__(self, invocations=None):
        self.invocations = [FakeInvocation(item) for item in (invocations or [])]
        self.clear_calls = 0
        self.recent_calls = 0

    def get_recent_invocations(self, limit=50):
        self.recent_calls += 1
        return self.invocations[-limit:] if self.invocations else []

    def clear_history(self):
        self.clear_calls += 1
        self.invocations.clear()


class FakeInvocation:
    """Simple plugin invocation object matching the route's response contract."""

    def __init__(self, payload):
        self.payload = copy.deepcopy(payload)

    def to_dict(self):
        return copy.deepcopy(self.payload)


def _install_route_import_stubs():
    """Install lightweight dependency stubs for route_plugin_logging."""
    stub_modules = {}

    auth_module = types.ModuleType('functions_authentication')

    def login_required(func):
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                is_api_request = (
                    request.accept_mimetypes.accept_json and
                    not request.accept_mimetypes.accept_html
                ) or request.path.startswith('/api/')

                if is_api_request:
                    return jsonify({'error': 'Unauthorized', 'message': 'Authentication required'}), 401
                return 'Unauthorized', 401

            return func(*args, **kwargs)

        decorated_function.__name__ = func.__name__
        return decorated_function

    def admin_required(func):
        def decorated_function(*args, **kwargs):
            user = session.get('user', {})
            if 'roles' not in user or 'Admin' not in user['roles']:
                is_api_request = (
                    request.accept_mimetypes.accept_json and
                    not request.accept_mimetypes.accept_html
                ) or request.path.startswith('/api/')

                if is_api_request:
                    return jsonify({'error': 'Forbidden', 'message': 'Insufficient permissions (Admin role required)'}), 403
                return 'Forbidden', 403

            return func(*args, **kwargs)

        decorated_function.__name__ = func.__name__
        return decorated_function

    auth_module.login_required = login_required
    auth_module.admin_required = admin_required
    auth_module.get_current_user_id = lambda: (session.get('user', {}) or {}).get('oid')
    stub_modules['functions_authentication'] = auth_module

    appinsights_module = types.ModuleType('functions_appinsights')
    appinsights_module.log_event = lambda *args, **kwargs: None
    stub_modules['functions_appinsights'] = appinsights_module

    plugin_logger_module = types.ModuleType('semantic_kernel_plugins.plugin_invocation_logger')
    plugin_logger_module._plugin_logger = None
    plugin_logger_module.get_plugin_logger = lambda: plugin_logger_module._plugin_logger
    stub_modules['semantic_kernel_plugins.plugin_invocation_logger'] = plugin_logger_module

    swagger_module = types.ModuleType('swagger_wrapper')
    swagger_module.swagger_route = lambda **kwargs: (lambda func: func)
    swagger_module.get_auth_security = lambda: {}
    stub_modules['swagger_wrapper'] = swagger_module

    for module_name, module in stub_modules.items():
        sys.modules[module_name] = module


def _load_route_plugin_logging_module():
    """Import the plugin logging route module after installing stubs."""
    _install_route_import_stubs()
    if 'route_plugin_logging' in sys.modules:
        del sys.modules['route_plugin_logging']
    return importlib.import_module('route_plugin_logging')


def build_test_app(invocations=None):
    """Register the plugin logging blueprint with a fake shared logger."""
    route_plugin_logging = _load_route_plugin_logging_module()
    fake_logger = FakePluginLogger(invocations=invocations)

    route_plugin_logging.get_plugin_logger = lambda: fake_logger

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'
    app.register_blueprint(route_plugin_logging.bpl)

    def create_client(user=None):
        client = app.test_client()
        if user is not None:
            with client.session_transaction() as flask_session:
                flask_session['user'] = user
        return client

    return create_client, fake_logger


def test_unauthenticated_clear_logs_returns_unauthorized():
    """Verify the existing unauthenticated response contract is preserved."""
    print('🔍 Testing unauthenticated clear-logs rejection...')

    create_client, fake_logger = build_test_app(invocations=[{'id': 'invocation-1'}])
    client = create_client()
    response = client.post('/api/plugins/clear-logs', headers={'Accept': 'application/json'})

    payload = response.get_json()
    if response.status_code != 401:
        print(f'❌ Expected 401, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Unauthorized':
        print(f'❌ Expected Unauthorized error, got {payload}')
        return False
    if fake_logger.clear_calls != 0 or len(fake_logger.invocations) != 1:
        print(f'❌ Logger state should remain unchanged, got clear_calls={fake_logger.clear_calls}, invocations={fake_logger.invocations}')
        return False

    print('✅ Unauthenticated clear-logs requests preserve the existing 401 contract')
    return True


def test_unauthenticated_recent_invocations_returns_unauthorized():
    """Verify the recent invocations endpoint preserves the existing unauthenticated contract."""
    print('🔍 Testing unauthenticated recent-invocations rejection...')

    create_client, fake_logger = build_test_app(invocations=[{'id': 'invocation-1'}])
    client = create_client()
    response = client.get('/api/plugins/invocations/recent?limit=5', headers={'Accept': 'application/json'})

    payload = response.get_json()
    if response.status_code != 401:
        print(f'❌ Expected 401, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Unauthorized':
        print(f'❌ Expected Unauthorized error, got {payload}')
        return False
    if fake_logger.recent_calls != 0:
        print(f'❌ get_recent_invocations should not run for unauthenticated users, got {fake_logger.recent_calls}')
        return False

    print('✅ Unauthenticated recent-invocations requests preserve the existing 401 contract')
    return True


def test_non_admin_clear_logs_returns_forbidden_and_preserves_history():
    """Verify non-admin users cannot clear the shared plugin history."""
    print('🔍 Testing non-admin clear-logs rejection...')

    create_client, fake_logger = build_test_app(
        invocations=[
            {'id': 'invocation-1'},
            {'id': 'invocation-2'},
        ]
    )
    client = create_client(user={'oid': 'user-attacker', 'roles': ['User']})
    response = client.post('/api/plugins/clear-logs', headers={'Accept': 'application/json'})

    payload = response.get_json()
    if response.status_code != 403:
        print(f'❌ Expected 403, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Forbidden':
        print(f'❌ Expected Forbidden error, got {payload}')
        return False
    if fake_logger.clear_calls != 0:
        print(f'❌ clear_history should not run for a non-admin, got {fake_logger.clear_calls}')
        return False
    if len(fake_logger.invocations) != 2:
        print(f'❌ Logger history should be preserved, got {fake_logger.invocations}')
        return False

    print('✅ Non-admin clear-logs requests are rejected without mutating history')
    return True


def test_non_admin_recent_invocations_returns_forbidden_without_reading_history():
    """Verify non-admin users cannot read the cross-user recent invocation feed."""
    print('🔍 Testing non-admin recent-invocations rejection...')

    create_client, fake_logger = build_test_app(
        invocations=[
            {'id': 'invocation-1', 'plugin_name': 'PluginA'},
            {'id': 'invocation-2', 'plugin_name': 'PluginB'},
        ]
    )
    client = create_client(user={'oid': 'user-attacker', 'roles': ['User']})
    response = client.get('/api/plugins/invocations/recent?limit=5', headers={'Accept': 'application/json'})

    payload = response.get_json()
    if response.status_code != 403:
        print(f'❌ Expected 403, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Forbidden':
        print(f'❌ Expected Forbidden error, got {payload}')
        return False
    if fake_logger.recent_calls != 0:
        print(f'❌ get_recent_invocations should not run for a non-admin, got {fake_logger.recent_calls}')
        return False

    print('✅ Non-admin recent-invocations requests are rejected before reading history')
    return True


def test_admin_clear_logs_succeeds_and_empties_history():
    """Verify admins can still clear the shared plugin invocation history."""
    print('🔍 Testing admin clear-logs success...')

    create_client, fake_logger = build_test_app(
        invocations=[
            {'id': 'invocation-1'},
            {'id': 'invocation-2'},
        ]
    )
    client = create_client(user={'oid': 'user-admin', 'roles': ['Admin']})
    response = client.post('/api/plugins/clear-logs', headers={'Accept': 'application/json'})

    payload = response.get_json()
    if response.status_code != 200:
        print(f'❌ Expected 200, got {response.status_code}: {payload}')
        return False
    if payload.get('previous_count') != 2:
        print(f'❌ Expected previous_count=2, got {payload}')
        return False
    if fake_logger.clear_calls != 1:
        print(f'❌ Expected one clear_history call, got {fake_logger.clear_calls}')
        return False
    if fake_logger.invocations:
        print(f'❌ Expected empty invocation history after admin clear, got {fake_logger.invocations}')
        return False

    print('✅ Admin clear-logs requests still clear the shared history')
    return True


def test_admin_recent_invocations_succeeds_and_returns_feed():
    """Verify admins can still read the cross-user recent invocation feed."""
    print('🔍 Testing admin recent-invocations success...')

    create_client, fake_logger = build_test_app(
        invocations=[
            {'id': 'invocation-1', 'plugin_name': 'PluginA'},
            {'id': 'invocation-2', 'plugin_name': 'PluginB'},
        ]
    )
    client = create_client(user={'oid': 'user-admin', 'roles': ['Admin']})
    response = client.get('/api/plugins/invocations/recent?limit=1', headers={'Accept': 'application/json'})

    payload = response.get_json()
    if response.status_code != 200:
        print(f'❌ Expected 200, got {response.status_code}: {payload}')
        return False
    if payload.get('total_count') != 1:
        print(f'❌ Expected total_count=1, got {payload}')
        return False
    if payload.get('invocations', [{}])[0].get('id') != 'invocation-2':
        print(f'❌ Expected the most recent invocation in the response, got {payload}')
        return False
    if fake_logger.recent_calls != 1:
        print(f'❌ Expected one get_recent_invocations call, got {fake_logger.recent_calls}')
        return False

    print('✅ Admin recent-invocations requests still return the shared feed')
    return True


if __name__ == '__main__':
    tests = [
        test_unauthenticated_clear_logs_returns_unauthorized,
        test_unauthenticated_recent_invocations_returns_unauthorized,
        test_non_admin_clear_logs_returns_forbidden_and_preserves_history,
        test_non_admin_recent_invocations_returns_forbidden_without_reading_history,
        test_admin_clear_logs_succeeds_and_empties_history,
        test_admin_recent_invocations_succeeds_and_returns_feed,
    ]

    print('🧪 Running plugin logging admin authorization tests...')
    print('=' * 60)

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print('\n' + '=' * 60)
    print(f'📊 Test Results: {sum(results)}/{len(results)} tests passed')

    sys.exit(0 if success else 1)