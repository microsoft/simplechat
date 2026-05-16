# test_profile_last_login_activity_logs.py
#!/usr/bin/env python3
"""
Functional test for profile last login activity log source.
Version: 0.241.027
Implemented in: 0.241.027

This test ensures that the user profile page gets last login activity from
activity_logs instead of stale cached/refreshed user metrics.
"""

import importlib.util
import logging
import sys
import types
from pathlib import Path

from flask import Flask, jsonify, request, session


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / 'application' / 'single_app'
ACTIVITY_LOGGING_PATH = APP_DIR / 'functions_activity_logging.py'
PROFILE_ROUTE_PATH = APP_DIR / 'route_frontend_profile.py'


class FakeActivityLogsContainer:
    """Small activity_logs container fake for query-focused tests."""

    def __init__(self, items):
        self.items = list(items)
        self.query_calls = []

    def create_item(self, body):
        self.items.append(body)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        self.query_calls.append({
            'query': query,
            'parameters': parameters or [],
            'partition_key': partition_key,
            'kwargs': kwargs,
        })

        user_id = _get_parameter_value(parameters or [], '@user_id')
        user_login_records = [
            item for item in self.items
            if item.get('user_id') == user_id and item.get('activity_type') == 'user_login'
        ]

        if 'COUNT(1)' in query:
            return [len(user_login_records)]

        order_field = 'created_at' if 'ORDER BY c.created_at DESC' in query else 'timestamp'
        ordered_records = sorted(
            [item for item in user_login_records if item.get(order_field)],
            key=lambda item: str(item.get(order_field) or ''),
            reverse=True,
        )
        return [
            {
                'timestamp': item.get('timestamp'),
                'created_at': item.get('created_at'),
            }
            for item in ordered_records[:1]
        ]


def _get_parameter_value(parameters, parameter_name):
    for parameter in parameters:
        if parameter.get('name') == parameter_name:
            return parameter.get('value')
    return None


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _identity_decorator(function):
    return function


def _load_activity_logging_module(fake_container):
    fake_config = types.ModuleType('config')
    fake_config.cosmos_activity_logs_container = fake_container

    fake_appinsights = types.ModuleType('functions_appinsights')
    fake_appinsights.logged_events = []

    def log_event(message, extra=None, level=None, debug_only=False):
        fake_appinsights.logged_events.append({
            'message': message,
            'extra': extra,
            'level': level,
            'debug_only': debug_only,
        })

    fake_appinsights.log_event = log_event

    fake_debug = types.ModuleType('functions_debug')
    fake_debug.debug_messages = []
    fake_debug.debug_print = lambda *args, **kwargs: fake_debug.debug_messages.append(args)

    module_name = 'functional_test_functions_activity_logging_profile_last_login'
    original_modules = {
        module_name: sys.modules.get(module_name),
        'config': sys.modules.get('config'),
        'functions_appinsights': sys.modules.get('functions_appinsights'),
        'functions_debug': sys.modules.get('functions_debug'),
    }

    sys.modules['config'] = fake_config
    sys.modules['functions_appinsights'] = fake_appinsights
    sys.modules['functions_debug'] = fake_debug
    sys.modules.pop(module_name, None)

    try:
        module_spec = importlib.util.spec_from_file_location(module_name, ACTIVITY_LOGGING_PATH)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        return module
    finally:
        _restore_modules(original_modules)


def _load_profile_route_module(settings_doc, login_activity_summary):
    fake_config = types.ModuleType('config')
    fake_config.jsonify = jsonify
    fake_config.logging = logging
    fake_config.render_template = lambda template_name, **kwargs: f'rendered {template_name}'
    fake_config.request = request
    fake_config.session = session

    fake_activity_logging = types.ModuleType('functions_activity_logging')
    fake_activity_logging.get_user_login_activity_summary = lambda user_id: login_activity_summary

    fake_appinsights = types.ModuleType('functions_appinsights')
    fake_appinsights.log_event = lambda *args, **kwargs: None

    fake_authentication = types.ModuleType('functions_authentication')
    fake_authentication.get_current_user_id = lambda: 'user-123'
    fake_authentication.get_user_profile_image = lambda: None
    fake_authentication.login_required = _identity_decorator
    fake_authentication.user_required = _identity_decorator

    fake_debug = types.ModuleType('functions_debug')
    fake_debug.debug_print = lambda *args, **kwargs: None

    fake_settings = types.ModuleType('functions_settings')
    fake_settings.get_settings = lambda: {
        'enable_group_workspaces': False,
        'enable_public_workspaces': False,
    }
    fake_settings.get_user_settings = lambda user_id: settings_doc
    fake_settings.update_user_settings = lambda user_id, settings_update: True

    fake_fact_memory = types.ModuleType('semantic_kernel_fact_memory_store')
    fake_fact_memory.FactMemoryStore = type('FactMemoryStore', (), {})

    fake_swagger = types.ModuleType('swagger_wrapper')
    fake_swagger.get_auth_security = lambda: []
    fake_swagger.swagger_route = lambda **kwargs: _identity_decorator

    module_name = 'functional_test_route_frontend_profile_last_login'
    stub_names = {
        module_name: sys.modules.get(module_name),
        'config': sys.modules.get('config'),
        'functions_activity_logging': sys.modules.get('functions_activity_logging'),
        'functions_appinsights': sys.modules.get('functions_appinsights'),
        'functions_authentication': sys.modules.get('functions_authentication'),
        'functions_debug': sys.modules.get('functions_debug'),
        'functions_settings': sys.modules.get('functions_settings'),
        'semantic_kernel_fact_memory_store': sys.modules.get('semantic_kernel_fact_memory_store'),
        'swagger_wrapper': sys.modules.get('swagger_wrapper'),
    }

    sys.modules['config'] = fake_config
    sys.modules['functions_activity_logging'] = fake_activity_logging
    sys.modules['functions_appinsights'] = fake_appinsights
    sys.modules['functions_authentication'] = fake_authentication
    sys.modules['functions_debug'] = fake_debug
    sys.modules['functions_settings'] = fake_settings
    sys.modules['semantic_kernel_fact_memory_store'] = fake_fact_memory
    sys.modules['swagger_wrapper'] = fake_swagger
    sys.modules.pop(module_name, None)

    try:
        module_spec = importlib.util.spec_from_file_location(module_name, PROFILE_ROUTE_PATH)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        return module
    finally:
        _restore_modules(stub_names)


def test_login_activity_summary_queries_activity_logs_partition():
    print('Testing login activity summary reads from activity_logs...')
    fake_container = FakeActivityLogsContainer([
        {
            'id': 'older-login',
            'user_id': 'user-123',
            'activity_type': 'user_login',
            'timestamp': '2026-05-05T09:00:00',
            'created_at': '2026-05-05T09:00:00',
        },
        {
            'id': 'latest-created-login',
            'user_id': 'user-123',
            'activity_type': 'user_login',
            'created_at': '2026-05-16T10:30:00',
        },
        {
            'id': 'other-user-login',
            'user_id': 'user-999',
            'activity_type': 'user_login',
            'timestamp': '2026-05-17T10:30:00',
            'created_at': '2026-05-17T10:30:00',
        },
        {
            'id': 'chat-activity',
            'user_id': 'user-123',
            'activity_type': 'chat_activity',
            'timestamp': '2026-05-18T10:30:00',
            'created_at': '2026-05-18T10:30:00',
        },
    ])
    activity_logging = _load_activity_logging_module(fake_container)

    summary = activity_logging.get_user_login_activity_summary('user-123')

    assert summary['total_logins'] == 2
    assert summary['last_login'] == '2026-05-16T10:30:00'
    assert summary['total_logins_lookup_succeeded'] is True
    assert summary['last_login_lookup_succeeded'] is True
    assert fake_container.query_calls
    assert all(call['partition_key'] == 'user-123' for call in fake_container.query_calls)


def test_profile_settings_overlays_activity_log_last_login():
    print('Testing profile settings response overlays activity-log last login...')
    settings_doc = {
        'display_name': 'Test User',
        'email': 'test@example.com',
        'lastUpdated': '2026-05-01T00:00:00',
        'settings': {
            'selected_agent': 'agent-1',
            'metrics': {
                'calculated_at': '2026-05-05T00:00:00',
                'login_metrics': {
                    'total_logins': 320,
                    'last_login': '2026-05-05T09:00:00',
                },
                'chat_metrics': {
                    'total_conversations': 504,
                },
            },
        },
    }
    live_last_login = '2026-05-16T10:30:00'
    login_activity_summary = {
        'total_logins': 321,
        'last_login': live_last_login,
        'total_logins_lookup_succeeded': True,
        'last_login_lookup_succeeded': True,
    }
    profile_route = _load_profile_route_module(settings_doc, login_activity_summary)

    app = Flask(__name__)
    app.secret_key = 'test-secret'
    profile_route.register_route_frontend_profile(app)

    with app.test_client() as client:
        response = client.get('/api/user/settings')

    assert response.status_code == 200
    payload = response.get_json()
    login_metrics = payload['settings']['metrics']['login_metrics']

    assert login_metrics['last_login'] == live_last_login
    assert payload['metrics']['login_metrics']['last_login'] == live_last_login
    assert login_metrics['last_login_source'] == 'activity_logs'
    assert login_metrics['total_logins'] == 320
    assert settings_doc['settings']['metrics']['login_metrics']['last_login'] == '2026-05-05T09:00:00'


def test_profile_settings_clears_cached_last_login_when_logs_are_empty():
    print('Testing profile settings clears stale cached last login when activity logs are empty...')
    settings_doc = {
        'settings': {
            'metrics': {
                'login_metrics': {
                    'total_logins': 12,
                    'last_login': '2026-05-05T09:00:00',
                },
            },
        },
    }
    login_activity_summary = {
        'total_logins': 0,
        'last_login': None,
        'total_logins_lookup_succeeded': True,
        'last_login_lookup_succeeded': True,
    }
    profile_route = _load_profile_route_module(settings_doc, login_activity_summary)

    app = Flask(__name__)
    app.secret_key = 'test-secret'
    profile_route.register_route_frontend_profile(app)

    with app.test_client() as client:
        response = client.get('/api/user/settings')

    assert response.status_code == 200
    payload = response.get_json()
    login_metrics = payload['settings']['metrics']['login_metrics']

    assert login_metrics['last_login'] is None
    assert login_metrics['last_login_source'] == 'activity_logs'
    assert settings_doc['settings']['metrics']['login_metrics']['last_login'] == '2026-05-05T09:00:00'


if __name__ == '__main__':
    tests = [
        test_login_activity_summary_queries_activity_logs_partition,
        test_profile_settings_overlays_activity_log_last_login,
        test_profile_settings_clears_cached_last_login_when_logs_are_empty,
    ]

    failures = 0
    for test in tests:
        try:
            print(f'\nRunning {test.__name__}...')
            test()
            print(f'{test.__name__} passed')
        except Exception as exc:
            failures += 1
            print(f'{test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()

    raise SystemExit(1 if failures else 0)