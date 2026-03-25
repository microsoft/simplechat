#!/usr/bin/env python3
# test_sql_plugin_key_vault_secret_storage.py
"""
Functional test for SQL plugin Key Vault secret storage.
Version: 0.239.114
Implemented in: 0.239.114

This test ensures that SQL plugin secret-bearing fields are stored in Key Vault,
preserved across edits, and cleaned up correctly when Key Vault storage is enabled.
"""

# pyright: reportMissingImports=false

import importlib
import os
import sys
import types
from copy import deepcopy


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeRetrievedSecret:
    def __init__(self, value):
        self.value = value


class FakeSecretClient:
    stored_secrets = {}
    deleted_secrets = []

    def __init__(self, vault_url, credential):
        self.vault_url = vault_url
        self.credential = credential

    @classmethod
    def reset(cls):
        cls.stored_secrets = {}
        cls.deleted_secrets = []

    def set_secret(self, name, value):
        FakeSecretClient.stored_secrets[name] = value

    def get_secret(self, name):
        return FakeRetrievedSecret(FakeSecretClient.stored_secrets[name])

    def begin_delete_secret(self, name):
        FakeSecretClient.deleted_secrets.append(name)
        FakeSecretClient.stored_secrets.pop(name, None)


class FakeCosmosResourceNotFoundError(Exception):
    pass


class FakeActionContainer:
    def __init__(self, existing_action=None):
        self.items = {}
        if existing_action:
            self.items[existing_action['id']] = dict(existing_action)

    def read_item(self, item, partition_key):
        action = self.items.get(item)
        if action is None:
            raise FakeCosmosResourceNotFoundError('not found')

        action_partition = action.get('user_id') or action.get('group_id') or action.get('id')
        if action_partition != partition_key:
            raise FakeCosmosResourceNotFoundError('not found')
        return dict(action)

    def query_items(self, query=None, parameters=None, partition_key=None, enable_cross_partition_query=False):
        parameters = parameters or []
        query_name = next((param['value'] for param in parameters if param['name'] == '@name'), None)

        results = []
        for action in self.items.values():
            action_partition = action.get('user_id') or action.get('group_id') or action.get('id')
            if partition_key and action_partition != partition_key:
                continue
            if query_name and action.get('name') != query_name:
                continue
            results.append(dict(action))
        return results

    def upsert_item(self, body):
        self.items[body['id']] = dict(body)
        return dict(body)

    def delete_item(self, item, partition_key):
        action = self.read_item(item, partition_key)
        self.items.pop(action['id'], None)


class ActionKeyVaultRecorder:
    def __init__(self):
        self.save_calls = []
        self.get_calls = []
        self.delete_calls = []

    def save(self, action_data, scope_value, scope, existing_plugin=None):
        self.save_calls.append(
            {
                'scope_value': scope_value,
                'scope': scope,
                'existing_plugin': deepcopy(existing_plugin),
            }
        )
        saved = dict(action_data)
        additional_fields = dict(saved.get('additionalFields', {}))
        existing_fields = (existing_plugin or {}).get('additionalFields', {})
        for field_name in ('connection_string', 'password'):
            if additional_fields.get(field_name) == 'Stored_In_KeyVault' and existing_fields.get(field_name):
                additional_fields[field_name] = existing_fields[field_name]
        saved['additionalFields'] = additional_fields
        return saved

    def get(self, action_data, scope_value, scope, return_type):
        self.get_calls.append(return_type)
        return dict(action_data)

    def delete(self, action, scope_value, scope):
        self.delete_calls.append({'scope_value': scope_value, 'scope': scope, 'action': deepcopy(action)})
        return action


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _load_functions_keyvault():
    config_stub = types.ModuleType('config')
    config_stub.KEY_VAULT_DOMAIN = '.vault.azure.net'

    appinsights_stub = types.ModuleType('functions_appinsights')
    appinsights_stub.log_event = lambda *args, **kwargs: None

    auth_stub = types.ModuleType('functions_authentication')
    settings_stub = types.ModuleType('functions_settings')

    settings_cache_stub = types.ModuleType('app_settings_cache')
    settings_cache_stub.get_settings_cache = lambda: {
        'enable_key_vault_secret_storage': True,
        'key_vault_name': 'unit-test-vault',
        'key_vault_identity': None,
    }

    azure_stub = types.ModuleType('azure')
    identity_stub = types.ModuleType('azure.identity')
    keyvault_stub = types.ModuleType('azure.keyvault')
    secrets_stub = types.ModuleType('azure.keyvault.secrets')

    class FakeDefaultAzureCredential:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    identity_stub.DefaultAzureCredential = FakeDefaultAzureCredential
    secrets_stub.SecretClient = FakeSecretClient
    azure_stub.identity = identity_stub
    azure_stub.keyvault = keyvault_stub
    keyvault_stub.secrets = secrets_stub

    original_modules = {}
    for module_name, module_stub in {
        'config': config_stub,
        'functions_appinsights': appinsights_stub,
        'functions_authentication': auth_stub,
        'functions_settings': settings_stub,
        'app_settings_cache': settings_cache_stub,
        'azure': azure_stub,
        'azure.identity': identity_stub,
        'azure.keyvault': keyvault_stub,
        'azure.keyvault.secrets': secrets_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules['functions_keyvault'] = sys.modules.get('functions_keyvault')
    sys.modules.pop('functions_keyvault', None)

    module = importlib.import_module('functions_keyvault')
    return module, original_modules


def _load_action_module(module_name, container, recorder):
    config_stub = types.ModuleType('config')
    if module_name == 'functions_personal_actions':
        config_stub.cosmos_personal_actions_container = container
    elif module_name == 'functions_global_actions':
        config_stub.cosmos_global_actions_container = container
    elif module_name == 'functions_group_actions':
        config_stub.cosmos_group_actions_container = container
    else:
        raise ValueError(f'Unsupported module name: {module_name}')

    keyvault_stub = types.ModuleType('functions_keyvault')

    class SecretReturnType:
        TRIGGER = 'trigger'
        NAME = 'name'
        VALUE = 'value'

    keyvault_stub.SecretReturnType = SecretReturnType
    keyvault_stub.keyvault_plugin_save_helper = recorder.save
    keyvault_stub.keyvault_plugin_get_helper = recorder.get
    keyvault_stub.keyvault_plugin_delete_helper = recorder.delete

    auth_stub = types.ModuleType('functions_authentication')
    auth_stub.get_current_user_id = lambda: 'admin-123'

    settings_stub = types.ModuleType('functions_settings')
    settings_stub.get_user_settings = lambda user_id: {'settings': {'plugins': []}}
    settings_stub.update_user_settings = lambda user_id, settings: True

    debug_stub = types.ModuleType('functions_debug')
    debug_stub.debug_print = lambda *args, **kwargs: None

    flask_stub = types.ModuleType('flask')
    flask_stub.current_app = None

    azure_stub = types.ModuleType('azure')
    cosmos_stub = types.ModuleType('azure.cosmos')
    cosmos_exceptions_stub = types.ModuleType('azure.cosmos.exceptions')
    cosmos_exceptions_stub.CosmosResourceNotFoundError = FakeCosmosResourceNotFoundError
    cosmos_stub.exceptions = cosmos_exceptions_stub
    azure_stub.cosmos = cosmos_stub

    original_modules = {}
    module_stubs = {
        'config': config_stub,
        'functions_keyvault': keyvault_stub,
        'functions_authentication': auth_stub,
        'functions_settings': settings_stub,
        'functions_debug': debug_stub,
        'flask': flask_stub,
        'azure': azure_stub,
        'azure.cosmos': cosmos_stub,
        'azure.cosmos.exceptions': cosmos_exceptions_stub,
    }

    for module_name_to_stub, module_stub in module_stubs.items():
        original_modules[module_name_to_stub] = sys.modules.get(module_name_to_stub)
        sys.modules[module_name_to_stub] = module_stub

    original_modules[module_name] = sys.modules.get(module_name)
    sys.modules.pop(module_name, None)

    module = importlib.import_module(module_name)
    return module, SecretReturnType, original_modules


def test_sql_keyvault_helper_stores_resolves_and_deletes_secrets():
    """Validate SQL helper stores connection secrets in Key Vault and preserves them across edits."""
    print('🔍 Testing SQL Key Vault helper secret lifecycle...')
    FakeSecretClient.reset()
    module, original_modules = _load_functions_keyvault()

    try:
        plugin = {
            'name': 'sql_orders',
            'type': 'sql_query',
            'auth': {'type': 'user'},
            'additionalFields': {
                'database_type': 'sqlserver',
                'connection_string': 'Server=tcp:example.database.windows.net;Database=Orders;Uid=readonly;Pwd=S3cr3t!',
                'username': 'readonly',
                'password': 'S3cr3t!',
            },
        }

        saved = module.keyvault_plugin_save_helper(plugin, scope_value='user-123', scope='user')
        connection_reference = saved['additionalFields']['connection_string']
        password_reference = saved['additionalFields']['password']

        assert module.validate_secret_name_dynamic(connection_reference), 'connection_string should be replaced with a Key Vault reference'
        assert module.validate_secret_name_dynamic(password_reference), 'password should be replaced with a Key Vault reference'
        assert saved['additionalFields']['username'] == 'readonly', 'username should remain stored as a non-secret field'
        assert FakeSecretClient.stored_secrets[connection_reference].startswith('Server=tcp:example.database.windows.net')
        assert FakeSecretClient.stored_secrets[password_reference] == 'S3cr3t!'

        trigger_view = module.keyvault_plugin_get_helper(saved, scope_value='user-123', scope='user', return_type=module.SecretReturnType.TRIGGER)
        assert trigger_view['additionalFields']['connection_string'] == module.ui_trigger_word
        assert trigger_view['additionalFields']['password'] == module.ui_trigger_word

        value_view = module.keyvault_plugin_get_helper(saved, scope_value='user-123', scope='user', return_type=module.SecretReturnType.VALUE)
        assert value_view['additionalFields']['connection_string'].startswith('Server=tcp:example.database.windows.net')
        assert value_view['additionalFields']['password'] == 'S3cr3t!'

        edited = deepcopy(trigger_view)
        preserved = module.keyvault_plugin_save_helper(
            edited,
            scope_value='user-123',
            scope='user',
            existing_plugin=saved,
        )
        assert preserved['additionalFields']['connection_string'] == connection_reference, 'placeholder updates should preserve the stored Key Vault reference'
        assert preserved['additionalFields']['password'] == password_reference, 'password placeholder updates should preserve the stored Key Vault reference'

        module.keyvault_plugin_delete_helper(preserved, scope_value='user-123', scope='user')
        assert connection_reference in FakeSecretClient.deleted_secrets
        assert password_reference in FakeSecretClient.deleted_secrets

        print('✅ SQL helper stores, resolves, preserves, and deletes Key Vault-backed SQL secrets')
        return True
    finally:
        _restore_modules(original_modules)


def test_personal_action_wrapper_preserves_existing_sql_secret_references():
    """Validate personal action save/delete passes stored SQL Key Vault references through the helper."""
    print('🔍 Testing personal action SQL Key Vault wrapper behavior...')
    existing_action = {
        'id': 'personal-action-1',
        'user_id': 'user-123',
        'name': 'sql_orders',
        'displayName': 'SQL Orders',
        'type': 'sql_query',
        'description': 'SQL query action',
        'endpoint': 'sql://sql_query',
        'auth': {'type': 'user'},
        'metadata': {},
        'additionalFields': {
            'database_type': 'sqlserver',
            'connection_string': 'user-123--action-addset--user--sql-orders-connection-string',
            'password': 'user-123--action-addset--user--sql-orders-password',
        },
    }
    container = FakeActionContainer(existing_action=existing_action)
    recorder = ActionKeyVaultRecorder()
    module, secret_return_type, original_modules = _load_action_module('functions_personal_actions', container, recorder)

    try:
        saved = module.save_personal_action(
            'user-123',
            {
                'id': 'personal-action-1',
                'name': 'sql_orders_renamed',
                'displayName': 'SQL Orders Renamed',
                'type': 'sql_query',
                'description': 'Updated SQL query action',
                'endpoint': 'sql://sql_query',
                'auth': {'type': 'user'},
                'metadata': {},
                'additionalFields': {
                    'database_type': 'sqlserver',
                    'connection_string': 'Stored_In_KeyVault',
                    'password': 'Stored_In_KeyVault',
                },
            },
        )

        assert recorder.save_calls[-1]['existing_plugin']['id'] == 'personal-action-1'
        assert saved['additionalFields']['connection_string'] == existing_action['additionalFields']['connection_string']
        assert saved['additionalFields']['password'] == existing_action['additionalFields']['password']

        deleted = module.delete_personal_action('user-123', 'personal-action-1')
        assert deleted is True
        assert recorder.delete_calls[-1]['action']['additionalFields']['connection_string'] == existing_action['additionalFields']['connection_string']
        assert secret_return_type.NAME in recorder.get_calls

        print('✅ Personal action wrapper preserves and deletes existing SQL Key Vault references')
        return True
    finally:
        _restore_modules(original_modules)


def test_global_and_group_action_wrappers_preserve_existing_sql_secret_references():
    """Validate global and group wrappers pass existing SQL Key Vault references into save/delete flows."""
    print('🔍 Testing global and group action SQL Key Vault wrapper behavior...')

    global_existing = {
        'id': 'global-action-1',
        'name': 'global_sql_orders',
        'displayName': 'Global SQL Orders',
        'type': 'sql_query',
        'description': 'Global SQL query action',
        'endpoint': 'sql://sql_query',
        'auth': {'type': 'user'},
        'metadata': {},
        'additionalFields': {
            'database_type': 'sqlserver',
            'connection_string': 'global-action-1--action-addset--global--global-sql-orders-connection-string',
            'password': 'global-action-1--action-addset--global--global-sql-orders-password',
        },
        'created_by': 'admin-123',
        'created_at': '2026-03-17T12:00:00',
    }
    global_container = FakeActionContainer(existing_action=global_existing)
    global_recorder = ActionKeyVaultRecorder()
    global_module, global_secret_return_type, global_original_modules = _load_action_module('functions_global_actions', global_container, global_recorder)

    try:
        saved_global = global_module.save_global_action(
            {
                'id': 'global-action-1',
                'name': 'global_sql_orders',
                'displayName': 'Global SQL Orders',
                'type': 'sql_query',
                'description': 'Updated global SQL query action',
                'endpoint': 'sql://sql_query',
                'auth': {'type': 'user'},
                'metadata': {},
                'additionalFields': {
                    'database_type': 'sqlserver',
                    'connection_string': 'Stored_In_KeyVault',
                    'password': 'Stored_In_KeyVault',
                },
            },
            user_id='admin-123',
        )

        assert global_recorder.save_calls[-1]['existing_plugin']['id'] == 'global-action-1'
        assert saved_global['additionalFields']['connection_string'] == global_existing['additionalFields']['connection_string']

        deleted_global = global_module.delete_global_action('global-action-1')
        assert deleted_global is True
        assert global_recorder.delete_calls[-1]['action']['additionalFields']['connection_string'] == global_existing['additionalFields']['connection_string']
        assert global_secret_return_type.NAME in global_recorder.get_calls
    finally:
        _restore_modules(global_original_modules)

    group_existing = {
        'id': 'group-action-1',
        'group_id': 'group-123',
        'name': 'group_sql_orders',
        'displayName': 'Group SQL Orders',
        'type': 'sql_query',
        'description': 'Group SQL query action',
        'endpoint': 'sql://sql_query',
        'auth': {'type': 'user'},
        'metadata': {},
        'additionalFields': {
            'database_type': 'sqlserver',
            'connection_string': 'group-123--action-addset--group--group-sql-orders-connection-string',
            'password': 'group-123--action-addset--group--group-sql-orders-password',
        },
    }
    group_container = FakeActionContainer(existing_action=group_existing)
    group_recorder = ActionKeyVaultRecorder()
    group_module, _, group_original_modules = _load_action_module('functions_group_actions', group_container, group_recorder)

    try:
        saved_group = group_module.save_group_action(
            'group-123',
            {
                'id': 'group-action-1',
                'name': 'group_sql_orders',
                'displayName': 'Group SQL Orders',
                'type': 'sql_query',
                'description': 'Updated group SQL query action',
                'endpoint': 'sql://sql_query',
                'auth': {'type': 'user'},
                'metadata': {},
                'additionalFields': {
                    'database_type': 'sqlserver',
                    'connection_string': 'Stored_In_KeyVault',
                    'password': 'Stored_In_KeyVault',
                },
            },
            user_id='owner-123',
        )

        assert group_recorder.save_calls[-1]['existing_plugin']['id'] == 'group-action-1'
        assert saved_group['additionalFields']['connection_string'] == group_existing['additionalFields']['connection_string']

        deleted_group = group_module.delete_group_action('group-123', 'group-action-1')
        assert deleted_group is True
        assert group_recorder.delete_calls[-1]['action']['additionalFields']['connection_string'] == group_existing['additionalFields']['connection_string']

        print('✅ Global and group action wrappers preserve and delete SQL Key Vault references correctly')
        return True
    finally:
        _restore_modules(group_original_modules)


if __name__ == '__main__':
    tests = [
        test_sql_keyvault_helper_stores_resolves_and_deletes_secrets,
        test_personal_action_wrapper_preserves_existing_sql_secret_references,
        test_global_and_group_action_wrappers_preserve_existing_sql_secret_references,
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