#!/usr/bin/env python3
# test_admin_multi_endpoint_persistence_guard.py
"""
Functional test for admin multi-endpoint persistence guard.
Version: 0.239.199
Implemented in: 0.239.199

This test ensures that once multi-endpoint model management is enabled, admin
settings saves preserve it even if the checkbox is omitted from later form
posts, and that the backend save helper enforces the same one-way behavior.
"""

import importlib
import json
import os
import sys
import types


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
ROUTE_FILE = os.path.join(SINGLE_APP_ROOT, 'route_frontend_admin_settings.py')
SETTINGS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_settings.py')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')

sys.path.append(ROOT_DIR)
sys.path.append(SINGLE_APP_ROOT)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _load_functions_settings_module():
    config_stub = types.ModuleType('config')
    config_stub.json = json
    config_stub.re = __import__('re')
    config_stub.WORD_CHUNK_SIZE = 400
    config_stub.video_indexer_endpoint = ''
    config_stub.cosmos_settings_container = types.SimpleNamespace(upsert_item=lambda item: item)

    appinsights_stub = types.ModuleType('functions_appinsights')
    appinsights_stub.log_event = lambda *args, **kwargs: None

    cache_stub = types.ModuleType('app_settings_cache')
    cache_stub.get_settings_cache = lambda: None
    cache_stub.update_settings_cache = lambda settings: None

    original_modules = {}
    for module_name, module_stub in {
        'config': config_stub,
        'functions_appinsights': appinsights_stub,
        'app_settings_cache': cache_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    module_name = 'application.single_app.functions_settings'
    original_modules[module_name] = sys.modules.get(module_name)
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    return module, original_modules


def test_admin_settings_route_preserves_enabled_multi_endpoint_flag():
    """Verify the admin POST handler keeps multi-endpoint enabled once active."""
    print('🔍 Testing admin route multi-endpoint persistence guard...')

    route_content = read_file(ROUTE_FILE)
    required_snippets = [
        "requested_enable_multi_model_endpoints = form_data.get('enable_multi_model_endpoints') == 'on'",
        "enable_multi_model_endpoints = coerce_multi_model_endpoint_enablement(",
        "existing_multi_endpoints_enabled,",
        "requested_enable_multi_model_endpoints,",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_content]
    assert not missing, f'Missing admin route persistence guard snippets: {missing}'

    print('✅ Admin route multi-endpoint persistence guard passed')
    return True


def test_update_settings_preserves_enabled_multi_endpoint_flag():
    """Verify shared settings persistence cannot turn multi-endpoint back off."""
    print('🔍 Testing shared settings multi-endpoint persistence guard...')

    functions_settings, original_modules = _load_functions_settings_module()
    saved_items = []

    try:
        functions_settings.get_settings = lambda: {
            'id': 'app_settings',
            'enable_multi_model_endpoints': True,
            'enable_enhanced_citations': True,
            'model_endpoints': [{'id': 'endpoint-1'}],
        }
        functions_settings.cosmos_settings_container = types.SimpleNamespace(
            upsert_item=lambda item: saved_items.append(json.loads(json.dumps(item)))
        )
        functions_settings.app_settings_cache = types.SimpleNamespace(
            update_settings_cache=lambda settings: None
        )

        result = functions_settings.update_settings({
            'enable_multi_model_endpoints': False,
            'app_title': 'Updated Title',
        })

        assert result is True, 'Expected update_settings to succeed'
        assert saved_items, 'Expected update_settings to persist an updated settings item'
        assert saved_items[-1]['enable_multi_model_endpoints'] is True, 'Multi-endpoint flag should remain enabled once set'
        assert functions_settings.coerce_multi_model_endpoint_enablement(True, False) is True
        assert functions_settings.coerce_multi_model_endpoint_enablement(False, True) is True
        assert functions_settings.coerce_multi_model_endpoint_enablement(False, False) is False

        print('✅ Shared settings multi-endpoint persistence guard passed')
        return True
    finally:
        _restore_modules(original_modules)


def test_config_version_is_bumped_for_multi_endpoint_persistence_fix():
    """Verify config version was bumped for the admin persistence guard fix."""
    print('🔍 Testing config version bump...')

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.239.199"' in config_content, 'Expected config.py version 0.239.199'

    print('✅ Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_admin_settings_route_preserves_enabled_multi_endpoint_flag,
        test_update_settings_preserves_enabled_multi_endpoint_flag,
        test_config_version_is_bumped_for_multi_endpoint_persistence_fix,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)