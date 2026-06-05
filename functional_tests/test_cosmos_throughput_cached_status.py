#!/usr/bin/env python3
# test_cosmos_throughput_cached_status.py
"""
Functional test for Cosmos throughput cached status rendering.
Version: 0.241.152
Implemented in: 0.241.152

This test ensures Cosmos throughput automation persists the last usable
database/container status so Admin Settings can render the saved view without
requiring a manual Refresh after server restart.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_cosmos_throughput import (  # noqa: E402
    build_runtime_update,
    get_cached_cosmos_throughput_status,
)


def _container_status():
    return {
        'configured': True,
        'resource': {
            'subscription_id': 'sub-123',
            'resource_group': 'rg-demo',
            'account_name': 'simplechat-cosmos',
            'database_name': 'SimpleChat',
            'account_id': '/subscriptions/sub-123/resourceGroups/rg-demo/providers/Microsoft.DocumentDB/databaseAccounts/simplechat-cosmos',
        },
        'throughput': {
            'scope': 'database',
            'mode': 'container_or_serverless',
            'current_ru': None,
            'is_scalable': False,
            'throughput_not_found': True,
        },
        'capacity_scope': 'container',
        'metrics': {
            'window_minutes': 5,
            'normalized_ru_percent': 82.5,
            'total_request_units': 6400,
        },
        'containers': [
            {
                'container_name': 'messages',
                'database_name': 'SimpleChat',
                'mode': 'autoscale',
                'current_ru': 4000,
                'is_scalable': True,
                'normalized_ru_percent': 82.5,
                'request_units': 3200,
                'has_normalized_ru_metric': True,
                'has_request_units_metric': True,
                'policy': {'container_name': 'messages', 'enabled': True},
            }
        ],
        'metric_error': '',
        'container_error': '',
        'last_checked_at': '2026-06-05T12:00:00+00:00',
    }


def test_runtime_update_persists_container_status_cache():
    """A successful throughput check should persist a compact cached status."""
    update = build_runtime_update(status=_container_status())
    cached_status = update['cosmos_throughput_cached_status']

    assert cached_status['configured'] is True
    assert cached_status['capacity_scope'] == 'container'
    assert cached_status['metrics']['normalized_ru_percent'] == 82.5
    assert cached_status['containers'][0]['container_name'] == 'messages'
    assert cached_status['containers'][0]['current_ru'] == 4000
    assert 'account_id' not in cached_status['resource']


def test_failed_runtime_update_does_not_clear_cached_status():
    """A failed check without status should not overwrite the last good cache."""
    update = build_runtime_update(error='credential unavailable')

    assert update['cosmos_throughput_last_error'] == 'credential unavailable'
    assert 'cosmos_throughput_cached_status' not in update


def test_cached_status_marks_initial_render_payload():
    """Cached status sent to Admin Settings should be marked as cached."""
    settings = {
        'cosmos_throughput_cached_status': build_runtime_update(status=_container_status())['cosmos_throughput_cached_status'],
    }
    cached_status = get_cached_cosmos_throughput_status(settings)

    assert cached_status['is_cached'] is True
    assert cached_status['last_checked_at'] == '2026-06-05T12:00:00+00:00'
    assert cached_status['containers'][0]['container_name'] == 'messages'


if __name__ == "__main__":
    tests = [
        test_runtime_update_persists_container_status_cache,
        test_failed_runtime_update_does_not_clear_cached_status,
        test_cached_status_marks_initial_render_payload,
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