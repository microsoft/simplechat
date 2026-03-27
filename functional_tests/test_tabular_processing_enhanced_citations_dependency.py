#!/usr/bin/env python3
# test_tabular_processing_enhanced_citations_dependency.py
"""
Functional test for tabular processing enhanced citations dependency.
Version: 0.240.002
Implemented in: 0.240.002

This test ensures that tabular processing is automatically enabled when
enhanced citations is enabled, cannot be independently toggled from the
admin Actions settings, and that runtime consumers use the derived logic.
"""

import os


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

FUNCTIONS_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_settings.py')
ROUTE_BACKEND_PLUGINS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_plugins.py')
ROUTE_BACKEND_CHATS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_chats.py')
ROUTE_FRONTEND_ADMIN_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_frontend_admin_settings.py')
SEMANTIC_KERNEL_LOADER = os.path.join(REPO_ROOT, 'application', 'single_app', 'semantic_kernel_loader.py')
ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
FIX_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'fixes', 'TABULAR_PROCESSING_ENHANCED_CITATIONS_DEPENDENCY_FIX.md')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_functions_settings_derives_tabular_enablement():
    """Settings logic must derive the tabular flag from enhanced citations."""
    print('🔍 Testing derived tabular enablement in functions_settings.py...')

    content = read_text(FUNCTIONS_SETTINGS)

    required_markers = [
        "def is_tabular_processing_enabled(settings):",
        "return bool((settings or {}).get('enable_enhanced_citations', False))",
        "merged['enable_tabular_processing_plugin'] = is_tabular_processing_enabled(merged)",
        "settings_item['enable_tabular_processing_plugin'] = is_tabular_processing_enabled(settings_item)"
    ]

    missing_markers = [marker for marker in required_markers if marker not in content]
    if missing_markers:
        raise AssertionError(f'Missing derived settings markers: {missing_markers}')

    print('✅ functions_settings.py derives tabular enablement from enhanced citations')
    return True


def test_runtime_paths_use_derived_helper():
    """Chat, admin settings, and SK loader should use the derived helper."""
    print('🔍 Testing runtime consumers for derived tabular logic...')

    chats_content = read_text(ROUTE_BACKEND_CHATS)
    loader_content = read_text(SEMANTIC_KERNEL_LOADER)
    admin_settings_content = read_text(ROUTE_FRONTEND_ADMIN_SETTINGS)

    assert 'is_tabular_processing_enabled(settings)' in chats_content, 'Chat routes should use derived tabular helper'
    assert chats_content.count('is_tabular_processing_enabled(settings)') >= 6, 'Expected multiple tabular helper checks in chat flow'
    assert 'settings.get(\'enable_tabular_processing_plugin\', False) and settings.get(\'enable_enhanced_citations\', False)' not in chats_content, 'Legacy compound tabular gating should be removed from chat flow'

    assert 'is_tabular_processing_enabled(settings)' in loader_content, 'Semantic kernel loader should use derived tabular helper'
    assert loader_content.count('is_tabular_processing_enabled(settings)') >= 3, 'Expected multiple helper checks in semantic kernel loader'
    assert "settings['enable_tabular_processing_plugin'] = is_tabular_processing_enabled(settings)" in admin_settings_content, 'Admin settings route should expose the derived flag'

    print('✅ Runtime consumers use the derived tabular enablement helper')
    return True


def test_admin_plugin_settings_remove_independent_toggle():
    """Admin plugin API and UI should not expose an independent tabular toggle."""
    print('🔍 Testing admin plugin API and UI wiring...')

    backend_content = read_text(ROUTE_BACKEND_PLUGINS)
    template_content = read_text(ADMIN_TEMPLATE)
    js_content = read_text(ADMIN_JS)

    assert "'enable_tabular_processing_plugin': is_tabular_processing_enabled(settings)" in backend_content, 'Admin plugin GET response should return derived tabular state'
    assert "deprecated_optional_keys = ['enable_tabular_processing_plugin']" in backend_content, 'Admin plugin POST should tolerate legacy callers'
    assert "'enable_tabular_processing_plugin',\n        'allow_user_plugins'" not in backend_content, 'Independent tabular toggle should not remain in required plugin POST fields'

    assert 'toggle-tabular-processing-plugin' not in template_content, 'Admin template should not render an independent tabular checkbox'
    assert 'Automatically enabled when Enhanced Citations is enabled' in template_content, 'Admin template should explain the dependency'

    assert 'toggle-tabular-processing-plugin' not in js_content, 'Admin JS should not bind to a removed tabular checkbox'
    assert 'enable_tabular_processing_plugin: tabularProcessingToggle' not in js_content, 'Admin JS should not submit an independent tabular toggle'
    assert 'Enabled automatically because Enhanced Citations is enabled' in js_content, 'Admin JS should render derived enabled status text'

    print('✅ Admin plugin API and UI no longer expose an independent tabular toggle')
    return True


def test_fix_documentation_exists():
    """Fix documentation should be present for this behavior change."""
    print('🔍 Testing fix documentation...')

    assert os.path.exists(FIX_DOC), 'Missing fix documentation for tabular processing dependency change'

    doc_content = read_text(FIX_DOC)
    required_markers = [
        'Fixed/Implemented in version: **0.240.002**',
        'Root Cause Analysis',
        'Files modified',
        'functional_tests/test_tabular_processing_enhanced_citations_dependency.py'
    ]

    missing_markers = [marker for marker in required_markers if marker not in doc_content]
    if missing_markers:
        raise AssertionError(f'Missing fix documentation markers: {missing_markers}')

    print('✅ Fix documentation is present')
    return True


if __name__ == '__main__':
    print('🧪 Running tabular processing enhanced citations dependency tests...')
    print('=' * 72)

    tests = [
        test_functions_settings_derives_tabular_enablement,
        test_runtime_paths_use_derived_helper,
        test_admin_plugin_settings_remove_independent_toggle,
        test_fix_documentation_exists,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f'❌ {test.__name__} failed: {exc}')
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    success = all(results)

    print('\n' + '=' * 72)
    print(f'📊 Results: {passed}/{total} tests passed')
    print('✅ All tabular dependency checks passed' if success else '❌ Tabular dependency checks failed')

    raise SystemExit(0 if success else 1)