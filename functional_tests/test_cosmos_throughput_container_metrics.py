#!/usr/bin/env python3
# test_cosmos_throughput_container_metrics.py
"""
Functional test for Cosmos throughput container metric dimensions.
Version: 0.241.156
Implemented in: 0.241.154; container throughput scan performance added in 0.241.155; REST metadata parsing added in 0.241.156

This test ensures Azure Monitor Cosmos throughput queries request container
dimensions with the raw Metrics REST API, parse returned container metadata,
and still fall back to aggregate metrics when dimensional rows are temporarily
unavailable. It also validates that container throughput settings are read with
a shared ARM request context instead of serial token acquisition.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import functions_cosmos_throughput as cosmos_throughput  # noqa: E402


class _FakeMetricsRestResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code
        self.reason = 'OK'
        self.text = ''

    def json(self):
        return self.body


def _resource_ids():
    return {
        'subscription_id': 'sub-123',
        'resource_group': 'rg-demo',
        'account_name': 'simplechat-cosmos',
        'database_name': 'SimpleChat',
        'account_id': '/subscriptions/sub-123/resourceGroups/rg-demo/providers/Microsoft.DocumentDB/databaseAccounts/simplechat-cosmos',
        'database_id': '/subscriptions/sub-123/resourceGroups/rg-demo/providers/Microsoft.DocumentDB/databaseAccounts/simplechat-cosmos/sqlDatabases/SimpleChat',
    }


def _settings():
    return {
        'cosmos_throughput_subscription_id': 'sub-123',
        'cosmos_throughput_resource_group': 'rg-demo',
        'cosmos_throughput_account_name': 'simplechat-cosmos',
        'cosmos_throughput_database_name': 'SimpleChat',
        'cosmos_throughput_metrics_window_minutes': 5,
    }


def _container_metric_response():
    return {
        'value': [
            {
                'name': {'value': 'NormalizedRUConsumption'},
                'timeseries': [
                    _time_series('SimpleChat', 'messages', [{'maximum': 82.5}, {'maximum': 74.0}]),
                    _time_series('SimpleChat', 'documents', [{'maximum': 15.0}]),
                    _time_series('OtherDatabase', 'messages', [{'maximum': 99.0}]),
                ],
            },
            {
                'name': {'value': 'TotalRequestUnits'},
                'timeseries': [
                    _time_series('SimpleChat', 'messages', [{'total': 120.0}, {'total': 80.0}]),
                    _time_series('SimpleChat', 'documents', [{'total': 30.0}]),
                    _time_series('OtherDatabase', 'messages', [{'total': 400.0}]),
                ],
            },
        ],
    }


def _aggregate_metric_response():
    return {
        'value': [
            {
                'name': {'value': 'NormalizedRUConsumption'},
                'timeseries': [_time_series('SimpleChat', None, [{'maximum': 11.0}])],
            },
            {
                'name': {'value': 'TotalRequestUnits'},
                'timeseries': [_time_series('SimpleChat', None, [{'total': 900.0}])],
            },
        ],
    }


def _time_series(database_name, container_name, data):
    metadata_values = []
    if container_name:
        metadata_values.append({'name': {'value': 'collectionname'}, 'value': container_name})
    if database_name:
        metadata_values.append({'name': {'value': 'databasename'}, 'value': database_name})
    return {'metadatavalues': metadata_values, 'data': data}


def test_metric_parser_keeps_container_rows_and_ignores_other_databases():
    """Metric parsing should preserve Cosmos container dimensions."""
    result = cosmos_throughput._parse_cosmos_metrics_response(
        _container_metric_response(),
        _resource_ids(),
        window_minutes=5,
        container_dimensions_requested=True,
    )

    assert result['normalized_ru_percent'] == 82.5
    assert result['total_request_units'] == 230.0
    assert result['container_dimensions_requested'] is True
    assert result['container_metric_count'] == 2
    assert result['containers'][0]['container_name'] == 'messages'
    assert result['containers'][0]['request_units'] == 200.0
    assert result['containers'][0]['has_normalized_ru_metric'] is True
    assert result['containers'][0]['has_request_units_metric'] is True


def test_query_requests_cosmos_container_dimensions():
    """The live query path should request DatabaseName/CollectionName splits."""
    original_get = cosmos_throughput.requests.get
    calls = []

    def fake_get(request_url, headers=None, params=None, timeout=None):
        calls.append({
            'request_url': request_url,
            'headers': headers,
            'params': params,
            'timeout': timeout,
        })
        return _FakeMetricsRestResponse(_container_metric_response())

    try:
        cosmos_throughput.requests.get = fake_get
        response = cosmos_throughput._query_cosmos_metrics_response(
            _resource_ids(),
            cosmos_throughput.datetime(2026, 6, 5, 12, 0, tzinfo=cosmos_throughput.timezone.utc),
            cosmos_throughput.datetime(2026, 6, 5, 12, 5, tzinfo=cosmos_throughput.timezone.utc),
            split_by_container=True,
            request_context={
                'resource_manager_endpoint': 'https://management.azure.com',
                'token': 'token',
                'credential_elapsed_ms': 0,
            },
        )
    finally:
        cosmos_throughput.requests.get = original_get

    first_call = calls[0]
    result = cosmos_throughput._parse_cosmos_metrics_response(
        response,
        _resource_ids(),
        window_minutes=5,
        container_dimensions_requested=True,
    )

    assert len(calls) == 1
    assert first_call['params']['$filter'] == cosmos_throughput.build_cosmos_container_metric_filter('SimpleChat')
    assert first_call['params']['metricnamespace'] == cosmos_throughput.COSMOS_THROUGHPUT_METRIC_NAMESPACE
    assert first_call['params']['metricnames'] == 'NormalizedRUConsumption,TotalRequestUnits'
    assert first_call['params']['aggregation'] == 'Maximum,Total'
    assert first_call['params']['top'] == str(cosmos_throughput.COSMOS_THROUGHPUT_CONTAINER_METRIC_MAX_RESULTS)
    assert result['container_metric_count'] == 2
    assert result['containers'][0]['container_name'] == 'messages'


def test_query_falls_back_to_aggregate_metrics_when_dimension_rows_are_empty():
    """Aggregate status should remain available if container dimensions lag."""
    original_query = cosmos_throughput._query_cosmos_metrics_response
    original_context = cosmos_throughput._build_arm_request_context
    calls = []

    def fake_query(resource_ids, start_time, end_time, split_by_container=False, request_context=None):
        calls.append({'split_by_container': split_by_container, 'request_context': request_context})
        return {'value': []} if split_by_container else _aggregate_metric_response()

    try:
        cosmos_throughput._query_cosmos_metrics_response = fake_query
        cosmos_throughput._build_arm_request_context = lambda refresh_id='', resource_kind='unknown': {
            'resource_manager_endpoint': 'https://management.azure.com',
            'token': 'token',
            'credential_elapsed_ms': 0,
        }
        result = cosmos_throughput.query_cosmos_metrics(_settings(), refresh_id='test-aggregate-fallback')
    finally:
        cosmos_throughput._query_cosmos_metrics_response = original_query
        cosmos_throughput._build_arm_request_context = original_context

    assert len(calls) == 2
    assert calls[0]['split_by_container'] is True
    assert calls[1]['split_by_container'] is False
    assert calls[0]['request_context'] is calls[1]['request_context']
    assert result['normalized_ru_percent'] == 11.0
    assert result['total_request_units'] == 900.0
    assert result['container_metric_count'] == 0


def test_container_throughput_scan_reuses_arm_context_and_preserves_order():
    """Container throughput reads should share one ARM context and keep row order."""
    original_list = cosmos_throughput.list_database_containers
    original_context = cosmos_throughput._build_arm_request_context
    original_get = cosmos_throughput.get_container_throughput
    context_calls = []

    def fake_list(settings=None, resource_ids=None, refresh_id=''):
        return ['messages', 'documents', 'settings']

    def fake_context(refresh_id='', resource_kind='unknown'):
        context_calls.append({'refresh_id': refresh_id, 'resource_kind': resource_kind})
        return {'resource_manager_endpoint': 'https://management.azure.com', 'token': 'token', 'credential_elapsed_ms': 7}

    def fake_get(settings, container_name, resource_ids=None, refresh_id='', request_context=None):
        assert request_context['token'] == 'token'
        return {
            'scope': 'container',
            'container_name': container_name,
            'mode': 'autoscale',
            'current_ru': 4000,
            'resource': {},
            'resource_ids': {},
            'is_scalable': True,
        }

    try:
        cosmos_throughput.list_database_containers = fake_list
        cosmos_throughput._build_arm_request_context = fake_context
        cosmos_throughput.get_container_throughput = fake_get
        result = cosmos_throughput.get_container_throughputs(
            _settings(),
            resource_ids=_resource_ids(),
            refresh_id='test-parallel-container-reads',
        )
    finally:
        cosmos_throughput.list_database_containers = original_list
        cosmos_throughput._build_arm_request_context = original_context
        cosmos_throughput.get_container_throughput = original_get

    assert context_calls == [{
        'refresh_id': 'test-parallel-container-reads',
        'resource_kind': 'container_throughput_batch',
    }]
    assert [item['container_name'] for item in result] == ['messages', 'documents', 'settings']


def test_merge_prefers_current_arm_container_list_over_metric_only_rows():
    """Stale metric-only rows should not appear when ARM returned containers."""
    merged = cosmos_throughput.merge_container_statuses(
        _settings(),
        container_throughputs=[
            {
                'container_name': 'messages',
                'mode': 'autoscale',
                'current_ru': 4000,
                'is_scalable': True,
            },
        ],
        metrics={
            'containers': [
                {
                    'container_name': 'messages',
                    'database_name': 'SimpleChat',
                    'normalized_ru_percent': 12,
                    'request_units': 30,
                    'has_normalized_ru_metric': True,
                    'has_request_units_metric': True,
                },
                {
                    'container_name': 'deleted_container',
                    'database_name': 'SimpleChat',
                    'normalized_ru_percent': 99,
                    'request_units': 300,
                    'has_normalized_ru_metric': True,
                    'has_request_units_metric': True,
                },
            ],
        },
    )

    assert [row['container_name'] for row in merged] == ['messages']
    assert merged[0]['normalized_ru_percent'] == 12


if __name__ == "__main__":
    tests = [
        test_metric_parser_keeps_container_rows_and_ignores_other_databases,
        test_query_requests_cosmos_container_dimensions,
        test_query_falls_back_to_aggregate_metrics_when_dimension_rows_are_empty,
        test_container_throughput_scan_reuses_arm_context_and_preserves_order,
        test_merge_prefers_current_arm_container_list_over_metric_only_rows,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)