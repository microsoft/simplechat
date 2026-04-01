#!/usr/bin/env python3
# test_plugin_validation_managed_fields_compatibility.py
"""
Functional test for persisted plugin validation managed-field compatibility.
Version: 0.240.011
Implemented in: 0.240.011

This test ensures storage-managed audit fields on persisted plugin documents do not
block validation during workspace action saves, while endpoint rules remain enforced.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'application', 'single_app'))


def test_persisted_msgraph_plugin_validation():
    """Persisted Microsoft Graph plugins should remain validation-safe."""
    print('🔍 Testing persisted MS Graph plugin validation...')

    try:
        from json_schema_validation import validate_plugin

        plugin = {
            'name': 'msgraph',
            'displayName': 'MSGraph',
            'type': 'msgraph',
            'description': 'Microsoft Graph action for user-scoped operations.',
            'endpoint': 'https://graph.microsoft.com/',
            'auth': {'type': 'user'},
            'metadata': {},
            'additionalFields': {},
            'created_by': 'user-123',
            'modified_by': 'user-123',
            'modified_at': '2026-04-01T12:00:00Z',
        }

        validation_error = validate_plugin(plugin)
        if validation_error:
            print(f'❌ Persisted MS Graph plugin validation failed: {validation_error}')
            return False

        print('✅ Persisted MS Graph plugin validation passed!')
        return True
    except Exception as exc:
        print(f'❌ Persisted MS Graph plugin validation test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_persisted_sql_plugin_validation():
    """Persisted SQL plugins should remain validation-safe with audit fields present."""
    print('🔍 Testing persisted SQL plugin validation...')

    try:
        from json_schema_validation import validate_plugin

        plugin = {
            'name': 'workforce_compensation_schema',
            'displayName': 'Workforce Compensation Schema',
            'type': 'sql_schema',
            'description': 'Schema plugin for workforce compensation data.',
            'endpoint': '',
            'auth': {'type': 'user'},
            'metadata': {},
            'additionalFields': {
                'database_type': 'azure_sql',
                'server': 'retroburnsqldemo.database.windows.net',
                'database': 'WorkforceCompensation',
            },
            'created_by': 'user-123',
            'modified_by': 'user-123',
            'modified_at': '2026-04-01T12:00:00Z',
        }

        validation_error = validate_plugin(plugin)
        if validation_error:
            print(f'❌ Persisted SQL plugin validation failed: {validation_error}')
            return False

        print('✅ Persisted SQL plugin validation passed!')
        return True
    except Exception as exc:
        print(f'❌ Persisted SQL plugin validation test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_non_sql_endpoint_requirement_still_applies():
    """Non-SQL plugins should still fail when the endpoint is missing."""
    print('🔍 Testing non-SQL endpoint enforcement with managed fields...')

    try:
        from json_schema_validation import validate_plugin

        plugin = {
            'name': 'custom_plugin',
            'displayName': 'Custom Plugin',
            'type': 'custom',
            'description': 'Generic plugin without an endpoint.',
            'endpoint': '',
            'auth': {'type': 'user'},
            'metadata': {},
            'additionalFields': {},
            'created_by': 'user-123',
            'modified_by': 'user-123',
            'modified_at': '2026-04-01T12:00:00Z',
        }

        validation_error = validate_plugin(plugin)
        if not validation_error:
            print('❌ Non-SQL plugin without an endpoint should have failed validation!')
            return False

        if 'valid endpoint' not in validation_error:
            print(f'❌ Unexpected validation error: {validation_error}')
            return False

        print(f'✅ Non-SQL endpoint requirement correctly enforced: {validation_error}')
        return True
    except Exception as exc:
        print(f'❌ Non-SQL endpoint enforcement test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print('🧪 Running persisted plugin validation managed-field compatibility tests...\n')

    tests = [
        test_persisted_msgraph_plugin_validation,
        test_persisted_sql_plugin_validation,
        test_non_sql_endpoint_requirement_still_applies,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)