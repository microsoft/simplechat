# test_admin_multi_endpoint_persistence_guard.py
#!/usr/bin/env python3
"""
Functional test for admin multi-endpoint persistence guard.
Version: 0.261.122
Implemented in: 0.239.199; updated in 0.250.172

This test ensures that once multi-endpoint model management is enabled, admin
settings saves preserve it even if the checkbox is omitted from later form
posts, and that the backend save helper enforces the same one-way behavior.
"""

import json
import logging
import os
import sys
import types
from contextlib import nullcontext
from unittest.mock import patch
from test_support.versioning import assert_app_version_at_least
from test_app_settings_store_consistency import FakeCosmos, FakeRedis, load_update_settings, store_module


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
ROUTE_FILE = os.path.join(SINGLE_APP_ROOT, 'route_frontend_admin_settings.py')
SETTINGS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_settings.py')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')

sys.path.append(ROOT_DIR)
sys.path.append(SINGLE_APP_ROOT)

from test_model_endpoint_normalization_backend import (
    _load_functions_settings_module as load_functions_settings_module,
)


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
    return load_functions_settings_module()


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

    container = FakeCosmos()
    container.document.update({
        'enable_multi_model_endpoints': True,
        'enable_enhanced_citations': True,
        'model_endpoints': [{'id': 'endpoint-1'}],
    })
    cache = FakeRedis()
    store = store_module.AppSettingsStore(container, cache, redis_required=True)
    update_settings = load_update_settings(store)
    coerce = update_settings.__globals__["coerce_multi_model_endpoint_enablement"]
    compatibility = types.SimpleNamespace(
        embedding_settings_write_guard=lambda *_args, **_kwargs: nullcontext(),
    )
    with patch.dict(sys.modules, {"functions_embedding_compatibility": compatibility}):
        result = update_settings({
            'enable_multi_model_endpoints': False,
            'app_title': 'Updated Title',
        })

    assert result is True, 'Expected update_settings to succeed'
    assert container.writes == 1, 'Expected one authoritative settings write'
    assert container.document['enable_multi_model_endpoints'] is True
    assert json.loads(cache.raw)["document"] == container.document
    assert coerce(True, False) is True
    assert coerce(False, True) is True
    assert coerce(False, False) is False

    print('✅ Shared settings multi-endpoint persistence guard passed')
    return True


def test_config_version_is_bumped_for_multi_endpoint_persistence_fix():
    """Verify config version was bumped for the admin persistence guard fix."""
    print('🔍 Testing config version bump...')

    config_content = read_file(CONFIG_FILE)
    assert_app_version_at_least("0.239.199")

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