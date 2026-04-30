#!/usr/bin/env python3
# test_user_plugin_bulk_save_id_preservation.py
"""
Functional test for user plugin bulk-save ID preservation.
Version: 0.240.019
Implemented in: 0.240.019

This test ensures bulk user plugin saves preserve existing action IDs during
rename flows so persisted actions are updated in place instead of deleted and
recreated with new IDs.
"""

import importlib
import os
import sys
import types
from copy import deepcopy


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'application', 'single_app'))


def _passthrough_decorator(*decorator_args, **decorator_kwargs):
    """Return the wrapped function unchanged for route/auth decorator stubs."""
    if decorator_args and callable(decorator_args[0]) and len(decorator_args) == 1 and not decorator_kwargs:
        return decorator_args[0]

    def decorator(func):
        return func

    return decorator


class DummyBlueprint:
    """Minimal Flask Blueprint stub used for importing route modules."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def route(self, *args, **kwargs):
        return _passthrough_decorator


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _load_route_module(state):
    request_stub = types.SimpleNamespace(json=None)

    flask_stub = types.ModuleType('flask')
    flask_stub.Blueprint = DummyBlueprint
    flask_stub.jsonify = lambda payload: payload
    flask_stub.request = request_stub
    flask_stub.current_app = types.SimpleNamespace(root_path=os.path.join(REPO_ROOT, 'application', 'single_app'))

    plugin_loader_stub = types.ModuleType('semantic_kernel_plugins.plugin_loader')
    plugin_loader_stub.get_all_plugin_metadata = lambda: []

    plugin_health_checker_stub = types.ModuleType('semantic_kernel_plugins.plugin_health_checker')

    class PluginHealthChecker:
        @staticmethod
        def validate_plugin_manifest(plugin, plugin_type):
            return True, []

    plugin_health_checker_stub.PluginHealthChecker = PluginHealthChecker
    plugin_health_checker_stub.PluginErrorRecovery = object

    base_plugin_stub = types.ModuleType('semantic_kernel_plugins.base_plugin')

    class BasePlugin:
        pass

    base_plugin_stub.BasePlugin = BasePlugin

    settings_stub = types.ModuleType('functions_settings')
    settings_stub.get_settings = lambda: {}
    settings_stub.is_tabular_processing_enabled = lambda: False
    settings_stub.update_settings = lambda updates: True

    auth_stub = types.ModuleType('functions_authentication')
    auth_stub.login_required = _passthrough_decorator
    auth_stub.user_required = _passthrough_decorator
    auth_stub.admin_required = _passthrough_decorator
    auth_stub.enabled_required = _passthrough_decorator
    auth_stub.get_current_user_id = lambda: state['user_id']

    appinsights_stub = types.ModuleType('functions_appinsights')
    appinsights_stub.log_event = lambda *args, **kwargs: None

    swagger_stub = types.ModuleType('swagger_wrapper')
    swagger_stub.swagger_route = _passthrough_decorator
    swagger_stub.get_auth_security = lambda: []

    debug_stub = types.ModuleType('functions_debug')
    debug_stub.debug_print = lambda *args, **kwargs: None

    plugins_stub = types.ModuleType('functions_plugins')
    plugins_stub.get_merged_plugin_settings = lambda *args, **kwargs: {}

    global_actions_stub = types.ModuleType('functions_global_actions')
    global_actions_stub.get_global_actions = lambda: []

    personal_actions_stub = types.ModuleType('functions_personal_actions')

    def get_personal_actions(user_id, return_type=None):
        return [deepcopy(action) for action in state['current_actions']]

    def save_personal_action(user_id, plugin):
        plugin_to_save = deepcopy(plugin)
        if not plugin_to_save.get('id'):
            plugin_to_save['id'] = 'generated-new-id'
        state['saved_plugins'].append({'user_id': user_id, 'plugin': plugin_to_save})
        return plugin_to_save

    def delete_personal_action(user_id, action_id):
        state['deleted_actions'].append({'user_id': user_id, 'action_id': action_id})
        return True

    personal_actions_stub.get_personal_actions = get_personal_actions
    personal_actions_stub.save_personal_action = save_personal_action
    personal_actions_stub.delete_personal_action = delete_personal_action

    group_stub = types.ModuleType('functions_group')
    group_stub.require_active_group = lambda *args, **kwargs: None
    group_stub.assert_group_role = lambda *args, **kwargs: None

    group_actions_stub = types.ModuleType('functions_group_actions')
    group_actions_stub.get_group_actions = lambda *args, **kwargs: []
    group_actions_stub.get_group_action = lambda *args, **kwargs: None
    group_actions_stub.save_group_action = lambda *args, **kwargs: None
    group_actions_stub.delete_group_action = lambda *args, **kwargs: None
    group_actions_stub.validate_group_action_payload = lambda *args, **kwargs: None

    keyvault_stub = types.ModuleType('functions_keyvault')

    class SecretReturnType:
        NAME = 'name'
        TRIGGER = 'trigger'

    keyvault_stub.SecretReturnType = SecretReturnType
    keyvault_stub.redact_plugin_secret_values = lambda plugin: plugin
    keyvault_stub.retrieve_secret_from_key_vault_by_full_name = lambda *args, **kwargs: None
    keyvault_stub.ui_trigger_word = 'Stored_In_KeyVault'
    keyvault_stub.validate_secret_name_dynamic = lambda *args, **kwargs: True

    validation_stub = types.ModuleType('json_schema_validation')
    validation_stub.PLUGIN_STORAGE_MANAGED_FIELDS = {
        'created_at',
        'created_by',
        'id',
        'is_global',
        'last_updated',
        'modified_at',
        'modified_by',
        'updated_at',
        'user_id',
    }

    def validate_plugin(plugin):
        state['validation_inputs'].append(deepcopy(plugin))
        return None

    validation_stub.validate_plugin = validate_plugin

    activity_stub = types.ModuleType('functions_activity_logging')
    activity_stub.log_action_creation = lambda *args, **kwargs: None
    activity_stub.log_action_update = lambda *args, **kwargs: None
    activity_stub.log_action_deletion = lambda *args, **kwargs: None

    original_modules = {}
    module_stubs = {
        'flask': flask_stub,
        'semantic_kernel_plugins.plugin_loader': plugin_loader_stub,
        'semantic_kernel_plugins.plugin_health_checker': plugin_health_checker_stub,
        'semantic_kernel_plugins.base_plugin': base_plugin_stub,
        'functions_settings': settings_stub,
        'functions_authentication': auth_stub,
        'functions_appinsights': appinsights_stub,
        'swagger_wrapper': swagger_stub,
        'functions_debug': debug_stub,
        'functions_plugins': plugins_stub,
        'functions_global_actions': global_actions_stub,
        'functions_personal_actions': personal_actions_stub,
        'functions_group': group_stub,
        'functions_group_actions': group_actions_stub,
        'functions_keyvault': keyvault_stub,
        'json_schema_validation': validation_stub,
        'functions_activity_logging': activity_stub,
    }

    for module_name, module_stub in module_stubs.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules['route_backend_plugins'] = sys.modules.get('route_backend_plugins')
    sys.modules.pop('route_backend_plugins', None)

    module = importlib.import_module('route_backend_plugins')
    return module, request_stub, original_modules


def test_bulk_save_preserves_existing_id_on_rename():
    """Bulk saves should keep the original ID when a personal plugin is renamed."""
    print('🔍 Testing user plugin bulk-save ID preservation on rename...')

    state = {
        'user_id': 'test-user-plugin-rename',
        'current_actions': [
            {
                'id': 'existing-plugin-id',
                'name': 'legacy_plugin_name',
                'description': 'Original plugin description',
            }
        ],
        'saved_plugins': [],
        'deleted_actions': [],
        'validation_inputs': [],
    }

    module = None
    original_modules = {}

    try:
        module, request_stub, original_modules = _load_route_module(state)
        request_stub.json = [
            {
                'id': 'existing-plugin-id',
                'name': 'renamed_plugin',
                'displayName': 'Renamed Plugin',
                'type': 'sql_schema',
                'description': 'Updated plugin description',
                'endpoint': 'sql://sql_schema',
                'auth': {'type': 'identity'},
                'metadata': {},
                'additionalFields': {},
                'created_by': 'stale-user',
                'modified_at': '2026-04-02T12:00:00Z',
                'user_id': 'stale-user',
            }
        ]

        response = module.set_user_plugins()
        if response != {'success': True}:
            print(f'❌ Unexpected route response: {response}')
            return False

        if len(state['saved_plugins']) != 1:
            print(f"❌ Expected 1 saved plugin, found {len(state['saved_plugins'])}")
            return False

        saved_plugin = state['saved_plugins'][0]['plugin']
        if saved_plugin.get('id') != 'existing-plugin-id':
            print(f"❌ Expected preserved ID 'existing-plugin-id', got {saved_plugin.get('id')}")
            return False

        if saved_plugin.get('name') != 'renamed_plugin':
            print(f"❌ Expected renamed plugin name, got {saved_plugin.get('name')}")
            return False

        if state['deleted_actions']:
            print(f"❌ Existing action should not be deleted during rename: {state['deleted_actions']}")
            return False

        validation_input = state['validation_inputs'][0]
        if validation_input.get('id') != 'existing-plugin-id':
            print(f"❌ Validation payload lost the existing ID: {validation_input}")
            return False

        leaked_fields = [field for field in ('created_by', 'modified_at', 'user_id') if field in validation_input or field in saved_plugin]
        if leaked_fields:
            print(f'❌ Storage-managed fields leaked through the route sanitization: {leaked_fields}')
            return False

        print('✅ Existing plugin ID was preserved during rename')
        print('✅ Existing action was not deleted during rename')
        print('✅ Storage-managed audit fields were stripped before validation/save')
        return True
    except Exception as exc:
        print(f'❌ User plugin bulk-save ID preservation test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False
    finally:
        _restore_modules(original_modules)


if __name__ == '__main__':
    print('🧪 Running user plugin bulk-save ID preservation tests...\n')

    tests = [
        test_bulk_save_preserves_existing_id_on_rename,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)