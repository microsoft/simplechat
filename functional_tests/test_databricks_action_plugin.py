# test_databricks_action_plugin.py
#!/usr/bin/env python3
"""
Functional test for Azure Commercial Databricks action configuration.
Version: 0.241.104
Implemented in: 0.241.104

This test ensures the Databricks action factory, plugin, manifest validation,
and read-only SQL execution contract work without requiring a live Databricks
workspace.
"""

import os
import sys
import traceback
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_databricks_operations import (  # noqa: E402
    DATABRICKS_CLOUD_AZURE_COMMERCIAL,
    DATABRICKS_PLUGIN_TYPE,
    normalize_databricks_additional_fields,
)
from semantic_kernel_plugins.databricks_plugin_factory import DatabricksPluginFactory  # noqa: E402
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker  # noqa: E402


class FakeDatabricksResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def build_manifest(**overrides):
    manifest = {
        'id': 'databricks-action-id',
        'name': 'commercial_databricks',
        'displayName': 'Commercial Databricks',
        'type': DATABRICKS_PLUGIN_TYPE,
        'description': 'Commercial Databricks SQL tools',
        'endpoint': 'https://adb-1234567890123456.7.azuredatabricks.net/api/2.0/sql/statements',
        'auth': {
            'type': 'key',
            'key': 'test-token',
        },
        'metadata': {
            'description': 'Databricks action for tests',
        },
        'additionalFields': {
            'cloud': DATABRICKS_CLOUD_AZURE_COMMERCIAL,
            'warehouse_id': 'warehouse-123',
            'catalog': 'main',
            'schema': 'default',
            'read_only': True,
            'max_rows': 100,
            'timeout': 30,
            'wait_timeout': 10,
        },
    }
    manifest.update(overrides)
    return manifest


def test_databricks_defaults_and_factory_normalization():
    """Validate Databricks defaults and factory endpoint normalization."""
    print('Testing Databricks action defaults and factory normalization...')

    defaults = normalize_databricks_additional_fields(None)
    assert defaults['cloud'] == DATABRICKS_CLOUD_AZURE_COMMERCIAL
    assert defaults['auth_method'] == 'pat'
    assert defaults['read_only'] is True
    assert defaults['max_rows'] == 1000

    plugin = DatabricksPluginFactory.create_from_config(build_manifest())
    assert plugin.endpoint == 'https://adb-1234567890123456.7.azuredatabricks.net'
    assert plugin.warehouse_id == 'warehouse-123'
    assert plugin.get_functions() == [
        'execute_sql_query',
        'get_catalogs',
        'get_schemas',
        'get_tables',
        'describe_table',
    ]
    assert plugin.metadata['type'] == DATABRICKS_PLUGIN_TYPE

    print('Databricks defaults and factory normalization verified.')
    return True


def test_databricks_manifest_validation():
    """Validate health checker rules for Databricks manifests."""
    print('Testing Databricks manifest validation...')

    valid, errors = PluginHealthChecker.validate_plugin_manifest(build_manifest(), DATABRICKS_PLUGIN_TYPE)
    assert valid, f'Expected valid Databricks manifest, got: {errors}'

    invalid_manifest = build_manifest(additionalFields={'cloud': 'azure_government', 'warehouse_id': 'warehouse-123'})
    valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_manifest, DATABRICKS_PLUGIN_TYPE)
    assert not valid
    assert any('azure_commercial' in error for error in errors)

    print('Databricks manifest validation verified.')
    return True


def test_databricks_read_only_query_enforcement():
    """Validate that unsafe SQL is rejected before any Databricks HTTP call."""
    print('Testing Databricks read-only query enforcement...')

    plugin = DatabricksPluginFactory.create_from_config(build_manifest())
    with patch('semantic_kernel_plugins.databricks_plugin.requests.post') as post_mock:
        result = plugin.execute_sql_query('DELETE FROM main.default.people')

    assert result['success'] is False
    assert result['error_type'] == 'validation'
    assert post_mock.call_count == 0

    print('Databricks read-only query enforcement verified.')
    return True


def test_databricks_statement_execution_payload_and_result_shape():
    """Validate Statement Execution request payload and normalized response shape."""
    print('Testing Databricks statement execution payload and result normalization...')

    plugin = DatabricksPluginFactory.create_from_config(build_manifest())
    response_payload = {
        'statement_id': 'statement-123',
        'status': {'state': 'SUCCEEDED'},
        'manifest': {
            'total_row_count': 1,
            'schema': {
                'columns': [
                    {'name': 'id'},
                    {'name': 'name'},
                ]
            },
        },
        'result': {
            'data_array': [[1, 'Ada']],
        },
    }

    with patch('semantic_kernel_plugins.databricks_plugin.requests.post', return_value=FakeDatabricksResponse(response_payload)) as post_mock:
        result = plugin.execute_sql_query('SELECT id, name FROM main.default.people')

    assert result['success'] is True
    assert result['columns'] == ['id', 'name']
    assert result['rows'] == [{'id': 1, 'name': 'Ada'}]
    assert result['row_count'] == 1
    posted_payload = post_mock.call_args.kwargs['json']
    assert posted_payload['warehouse_id'] == 'warehouse-123'
    assert posted_payload['statement'] == 'SELECT id, name FROM main.default.people LIMIT 100'
    assert posted_payload['catalog'] == 'main'
    assert posted_payload['schema'] == 'default'

    print('Databricks statement execution payload and response normalization verified.')
    return True


if __name__ == '__main__':
    tests = [
        test_databricks_defaults_and_factory_normalization,
        test_databricks_manifest_validation,
        test_databricks_read_only_query_enforcement,
        test_databricks_statement_execution_payload_and_result_shape,
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