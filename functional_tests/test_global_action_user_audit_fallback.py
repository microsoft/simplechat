#!/usr/bin/env python3
# test_global_action_user_audit_fallback.py
"""
Functional test for global action audit user fallback.
Version: 0.239.103
Implemented in: 0.239.103

This test ensures that save_global_action() resolves a missing user ID from
get_current_user_id() and falls back to a non-null system audit value.
"""

# pyright: reportMissingImports=false

import importlib
import os
import sys
import types


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeContainer:
    def __init__(self, existing_action=None):
        self.existing_action = existing_action
        self.upserted_body = None

    def read_item(self, item, partition_key):
        if self.existing_action is None:
            raise Exception('not found')
        return dict(self.existing_action)

    def upsert_item(self, body):
        self.upserted_body = dict(body)
        self.existing_action = dict(body)
        return dict(body)


def _load_functions_global_actions(fake_container, current_user_id):
    config_stub = types.ModuleType('config')
    config_stub.cosmos_global_actions_container = fake_container

    auth_stub = types.ModuleType('functions_authentication')
    auth_stub.get_current_user_id = lambda: current_user_id

    keyvault_stub = types.ModuleType('functions_keyvault')

    class SecretReturnType:
        TRIGGER = 'trigger'

    keyvault_stub.SecretReturnType = SecretReturnType
    keyvault_stub.keyvault_plugin_save_helper = lambda action_data, scope_value, scope: action_data
    keyvault_stub.keyvault_plugin_get_helper = (
        lambda action_data, scope_value, scope, return_type: action_data
    )
    keyvault_stub.keyvault_plugin_delete_helper = lambda action, scope_value, scope: None

    original_modules = {}
    for module_name, module_stub in {
        'config': config_stub,
        'functions_authentication': auth_stub,
        'functions_keyvault': keyvault_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules['functions_global_actions'] = sys.modules.get('functions_global_actions')
    sys.modules.pop('functions_global_actions', None)

    module = importlib.import_module('functions_global_actions')
    return module, original_modules


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def test_save_global_action_uses_current_user_when_missing():
    """Validate missing user_id is filled from get_current_user_id."""
    print('🔍 Testing global action audit fallback to current user...')

    fake_container = FakeContainer()
    module, original_modules = _load_functions_global_actions(fake_container, 'user-123')

    try:
        result = module.save_global_action(
            {
                'name': 'test_plugin',
                'displayName': 'Test Plugin',
                'type': 'custom',
                'description': 'Regression coverage for missing user audit fields',
                'endpoint': 'https://example.com/plugin',
                'auth': {'type': 'identity'},
                'metadata': {},
                'additionalFields': {},
            }
        )

        assert result is not None, 'save_global_action should return the saved action'
        assert result['created_by'] == 'user-123', 'created_by should use current user ID'
        assert result['modified_by'] == 'user-123', 'modified_by should use current user ID'
        assert fake_container.upserted_body['created_by'] == 'user-123'
        assert fake_container.upserted_body['modified_by'] == 'user-123'

        print('✅ Missing user_id now resolves to get_current_user_id()')
        return True
    finally:
        _restore_modules(original_modules)


def test_save_global_action_falls_back_to_system_and_repairs_null_creator():
    """Validate update flow repairs null created_by and never persists null audit values."""
    print('🔍 Testing global action audit fallback to system...')

    existing_action = {
        'id': 'action-1',
        'name': 'test_plugin',
        'created_by': None,
        'created_at': '2026-03-01T12:00:00',
    }
    fake_container = FakeContainer(existing_action=existing_action)
    module, original_modules = _load_functions_global_actions(fake_container, None)

    try:
        result = module.save_global_action(
            {
                'id': 'action-1',
                'name': 'test_plugin',
                'displayName': 'Test Plugin',
                'type': 'custom',
                'description': 'Regression coverage for null audit repair',
                'endpoint': 'https://example.com/plugin',
                'auth': {'type': 'identity'},
                'metadata': {},
                'additionalFields': {},
            },
            user_id=None,
        )

        assert result is not None, 'save_global_action should return the saved action'
        assert result['created_by'] == 'system', 'created_by should fall back to system'
        assert result['modified_by'] == 'system', 'modified_by should fall back to system'
        assert result['created_at'] == '2026-03-01T12:00:00', 'created_at should be preserved'
        assert fake_container.upserted_body['created_by'] == 'system'
        assert fake_container.upserted_body['modified_by'] == 'system'

        print('✅ Null audit values are repaired to a non-null system value')
        return True
    finally:
        _restore_modules(original_modules)


if __name__ == '__main__':
    tests = [
        test_save_global_action_uses_current_user_when_missing,
        test_save_global_action_falls_back_to_system_and_repairs_null_creator,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            results.append(test())
        except Exception as exc:
            print(f'❌ {test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(bool(result) for result in results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)