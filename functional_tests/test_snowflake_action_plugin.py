# test_snowflake_action_plugin.py
#!/usr/bin/env python3
"""
Functional test for Snowflake query action configuration.
Version: 0.250.006
Implemented in: 0.250.006

This test ensures the Snowflake action factory, plugin, manifest validation,
and read-only SQL execution contract work without requiring a live Snowflake
account.
"""

import os
import sys
import traceback
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_snowflake_operations import (  # noqa: E402
    SNOWFLAKE_DEFAULT_ENDPOINT,
    SNOWFLAKE_PLUGIN_TYPE,
    normalize_snowflake_additional_fields,
)
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker  # noqa: E402
from semantic_kernel_plugins.snowflake_plugin_factory import SnowflakePluginFactory  # noqa: E402


class FakeSnowflakeCursor:
    def __init__(self, rows=None, description=None):
        self.description = description or [('ID', 0), ('NAME', 2)]
        self.rows = rows or [(1, 'Ada')]
        self.rowcount = len(self.rows)
        self.sfqid = 'snowflake-query-123'
        self.executed_statement = ''
        self.timeout = None
        self.closed = False

    def execute(self, statement, timeout=None):
        self.executed_statement = statement
        self.timeout = timeout
        return self

    def fetchmany(self, size):
        return self.rows[:size]

    def close(self):
        self.closed = True


class FakeSnowflakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def build_manifest(**overrides):
    manifest = {
        'id': 'snowflake-action-id',
        'name': 'snowflake_analytics',
        'displayName': 'Snowflake Analytics',
        'type': SNOWFLAKE_PLUGIN_TYPE,
        'description': 'Snowflake query tools',
        'endpoint': SNOWFLAKE_DEFAULT_ENDPOINT,
        'auth': {
            'type': 'username_password',
            'identity': 'ANALYST_USER',
            'key': 'test-password',
        },
        'metadata': {
            'description': 'Snowflake action for tests',
        },
        'additionalFields': {
            'account': 'organization-account',
            'user': 'ANALYST_USER',
            'auth_method': 'password',
            'warehouse': 'COMPUTE_WH',
            'database': 'ANALYTICS',
            'schema': 'PUBLIC',
            'role': 'ANALYST_ROLE',
            'read_only': True,
            'max_rows': 100,
            'timeout': 30,
            'login_timeout': 10,
        },
    }
    manifest.update(overrides)
    return manifest


def test_snowflake_defaults_and_factory_normalization():
    """Validate Snowflake defaults and factory normalization."""
    print('Testing Snowflake action defaults and factory normalization...')

    defaults = normalize_snowflake_additional_fields(None)
    assert defaults['auth_method'] == 'password'
    assert defaults['read_only'] is True
    assert defaults['max_rows'] == 1000
    assert defaults['timeout'] == 30

    plugin = SnowflakePluginFactory.create_from_config(build_manifest(endpoint=''))
    assert plugin.endpoint == SNOWFLAKE_DEFAULT_ENDPOINT
    assert plugin.account == 'organization-account'
    assert plugin.warehouse == 'COMPUTE_WH'
    assert plugin.get_functions() == [
        'execute_sql_query',
        'get_databases',
        'get_schemas',
        'get_tables',
        'describe_table',
    ]
    assert plugin.metadata['type'] == SNOWFLAKE_PLUGIN_TYPE

    print('Snowflake defaults and factory normalization verified.')
    return True


def test_snowflake_manifest_validation():
    """Validate health checker rules for Snowflake manifests."""
    print('Testing Snowflake manifest validation...')

    valid, errors = PluginHealthChecker.validate_plugin_manifest(build_manifest(), SNOWFLAKE_PLUGIN_TYPE)
    assert valid, f'Expected valid Snowflake manifest, got: {errors}'

    invalid_manifest = build_manifest(endpoint='https://example.snowflakecomputing.com')
    valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_manifest, SNOWFLAKE_PLUGIN_TYPE)
    assert not valid
    assert any(SNOWFLAKE_DEFAULT_ENDPOINT in error for error in errors)

    invalid_manifest = build_manifest(additionalFields={'account': 'organization-account', 'auth_method': 'password'})
    valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_manifest, SNOWFLAKE_PLUGIN_TYPE)
    assert not valid
    assert any('warehouse' in error for error in errors)

    print('Snowflake manifest validation verified.')
    return True


def test_snowflake_read_only_query_enforcement():
    """Validate that unsafe SQL is rejected before any Snowflake connection."""
    print('Testing Snowflake read-only query enforcement...')

    plugin = SnowflakePluginFactory.create_from_config(build_manifest())
    with patch.object(plugin, '_connect') as connect_mock:
        result = plugin.execute_sql_query('DELETE FROM ANALYTICS.PUBLIC.PEOPLE')

    assert result['success'] is False
    assert result['error_type'] == 'validation'
    assert connect_mock.call_count == 0

    print('Snowflake read-only query enforcement verified.')
    return True


def test_snowflake_query_limit_and_result_shape():
    """Validate Snowflake query execution and normalized response shape."""
    print('Testing Snowflake query limit and response normalization...')

    plugin = SnowflakePluginFactory.create_from_config(build_manifest())
    fake_cursor = FakeSnowflakeCursor()
    fake_connection = FakeSnowflakeConnection(fake_cursor)

    with patch.object(plugin, '_connect', return_value=fake_connection):
        result = plugin.execute_sql_query('SELECT id, name FROM ANALYTICS.PUBLIC.PEOPLE')

    assert result['success'] is True
    assert fake_cursor.executed_statement == 'SELECT id, name FROM ANALYTICS.PUBLIC.PEOPLE LIMIT 100'
    assert fake_cursor.timeout == 30
    assert fake_cursor.closed is True
    assert fake_connection.closed is True
    assert result['query_id'] == 'snowflake-query-123'
    assert result['columns'] == ['ID', 'NAME']
    assert result['rows'] == [{'ID': 1, 'NAME': 'Ada'}]
    assert result['row_count'] == 1
    assert result['truncated'] is False

    print('Snowflake query limit and response normalization verified.')
    return True


def test_snowflake_discovery_helpers():
    """Validate Snowflake discovery helper SQL generation."""
    print('Testing Snowflake discovery helper statements...')

    plugin = SnowflakePluginFactory.create_from_config(build_manifest())
    statements = []

    def capture(statement):
        statements.append(statement)
        return {'success': True, 'query': statement, 'rows': []}

    with patch.object(plugin, '_execute_read_only_statement', side_effect=capture):
        plugin.get_databases()
        plugin.get_schemas('ANALYTICS')
        plugin.get_tables('ANALYTICS', 'PUBLIC')
        plugin.describe_table('ANALYTICS.PUBLIC.PEOPLE')

    assert statements == [
        'SHOW DATABASES',
        'SHOW SCHEMAS IN DATABASE ANALYTICS',
        'SHOW TABLES IN SCHEMA ANALYTICS.PUBLIC',
        'DESCRIBE TABLE ANALYTICS.PUBLIC.PEOPLE',
    ]

    print('Snowflake discovery helper statements verified.')
    return True


if __name__ == '__main__':
    tests = [
        test_snowflake_defaults_and_factory_normalization,
        test_snowflake_manifest_validation,
        test_snowflake_read_only_query_enforcement,
        test_snowflake_query_limit_and_result_shape,
        test_snowflake_discovery_helpers,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f'Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)