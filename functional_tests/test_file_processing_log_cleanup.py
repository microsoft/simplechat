# test_file_processing_log_cleanup.py
"""
Functional test for file processing log cleanup.
Version: 0.250.075
Implemented in: 0.250.075

This test validates cutoff calculation, cross-partition Cosmos deletion,
partial failure reporting, request validation, and route authorization.
"""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

import pytest
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_LOGGING_PATH = REPO_ROOT / 'application' / 'single_app' / 'functions_logging.py'
ADMIN_ROUTE_PATH = REPO_ROOT / 'application' / 'single_app' / 'route_frontend_admin_settings.py'
CONFIG_PATH = REPO_ROOT / 'application' / 'single_app' / 'config.py'


class FakeContainer:
    """Capture Cosmos queries and deletes without external dependencies."""

    def __init__(self, items, fail_delete_number=None):
        self.items = items
        self.fail_delete_number = fail_delete_number
        self.query_calls = []
        self.delete_calls = []

    def query_items(self, **kwargs):
        self.query_calls.append(kwargs)
        return list(self.items)

    def delete_item(self, *, item, partition_key):
        delete_number = len(self.delete_calls) + 1
        if self.fail_delete_number == delete_number:
            raise RuntimeError('simulated Cosmos delete failure')
        self.delete_calls.append((item, partition_key))


def load_functions_logging():
    """Load the helper with lightweight stubs for application dependencies."""
    fake_config = types.ModuleType('config')
    fake_config.cosmos_file_processing_container = FakeContainer([])
    fake_appinsights = types.ModuleType('functions_appinsights')
    fake_appinsights.log_event = lambda *args, **kwargs: None
    fake_settings = types.ModuleType('functions_settings')
    fake_settings.get_settings = lambda: {'enable_file_processing_logs': True}

    dependencies = {
        'config': fake_config,
        'functions_appinsights': fake_appinsights,
        'functions_settings': fake_settings,
    }
    previous_modules = {name: sys.modules.get(name) for name in dependencies}
    sys.modules.update(dependencies)
    try:
        module_name = 'testable_functions_logging'
        spec = importlib.util.spec_from_file_location(module_name, FUNCTIONS_LOGGING_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous_module in previous_modules.items():
            if previous_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous_module


def test_cutoff_uses_days_weeks_and_fixed_30_day_months():
    """Verify supported age units produce strict UTC cutoffs."""
    module = load_functions_logging()
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    assert module.calculate_file_processing_log_cutoff(2, 'days', now=now).isoformat() == (
        '2026-07-28T12:00:00+00:00'
    )
    assert module.calculate_file_processing_log_cutoff(2, 'weeks', now=now).isoformat() == (
        '2026-07-16T12:00:00+00:00'
    )
    assert module.calculate_file_processing_log_cutoff(2, 'months', now=now).isoformat() == (
        '2026-05-31T12:00:00+00:00'
    )


@pytest.mark.parametrize(
    ('age', 'unit'),
    [
        (0, 'days'),
        (-1, 'days'),
        (True, 'days'),
        (1.5, 'days'),
        (1_000_000_000, 'days'),
        (1, 'hours'),
        (1, ''),
    ],
)
def test_cutoff_rejects_invalid_age_or_unit(age, unit):
    """Reject unsupported or ambiguous cleanup input."""
    module = load_functions_logging()

    with pytest.raises(ValueError):
        module.calculate_file_processing_log_cutoff(age, unit)


def test_age_cleanup_queries_across_partitions_and_point_deletes():
    """Delete selected items with their document partition keys."""
    module = load_functions_logging()
    container = FakeContainer([
        {'id': 'log-1', 'document_id': 'document-a'},
        {'id': 'log-2', 'document_id': 'document-b'},
    ])
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)

    result = module.delete_file_processing_logs(
        age=30,
        unit='days',
        now=now,
        container=container,
    )

    assert result == {
        'deleted_count': 2,
        'delete_all': False,
        'cutoff': '2026-06-30T12:00:00+00:00',
    }
    assert container.delete_calls == [
        ('log-1', 'document-a'),
        ('log-2', 'document-b'),
    ]
    query_call = container.query_calls[0]
    assert query_call['enable_cross_partition_query'] is True
    assert 'c.timestamp < @cutoff' in query_call['query']
    assert query_call['parameters'] == [
        {'name': '@cutoff', 'value': '2026-06-30T12:00:00'},
    ]


def test_delete_all_has_no_cutoff_and_rejects_mixed_scope():
    """Keep full deletion explicit and mutually exclusive with age input."""
    module = load_functions_logging()
    container = FakeContainer([
        {'id': 'log-1', 'document_id': 'document-a'},
        {'id': 'log-2', 'document_id': ''},
    ])

    result = module.delete_file_processing_logs(delete_all=True, container=container)

    assert result == {
        'deleted_count': 2,
        'delete_all': True,
        'cutoff': None,
    }
    assert container.delete_calls == [
        ('log-1', 'document-a'),
        ('log-2', ''),
    ]
    assert 'c.timestamp' not in container.query_calls[0]['query']
    assert container.query_calls[0]['parameters'] is None

    with pytest.raises(ValueError):
        module.delete_file_processing_logs(
            delete_all=True,
            age=30,
            unit='days',
            container=container,
        )


def test_partial_failure_reports_completed_delete_count():
    """Surface a failed cleanup and preserve its exact partial count."""
    module = load_functions_logging()
    container = FakeContainer(
        [
            {'id': 'log-1', 'document_id': 'document-a'},
            {'id': 'log-2', 'document_id': 'document-b'},
        ],
        fail_delete_number=2,
    )

    with pytest.raises(module.FileProcessingLogDeletionError) as exc_info:
        module.delete_file_processing_logs(delete_all=True, container=container)

    assert exc_info.value.deleted_count == 1
    assert container.delete_calls == [('log-1', 'document-a')]


def test_cleanup_route_is_admin_only_and_versioned():
    """Verify the cleanup endpoint keeps the required authorization boundary."""
    route_source = ADMIN_ROUTE_PATH.read_text(encoding='utf-8')
    config_source = CONFIG_PATH.read_text(encoding='utf-8')
    decorator_block = """    @bp.route('/api/admin/settings/file-processing-logs/cleanup', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def cleanup_file_processing_logs():"""

    assert decorator_block in route_source
    assert "request.get_json(silent=True)" in route_source
    assert "if payload.get('confirmed') is not True:" in route_source
    assert "'error': 'Explicit confirmation is required.'" in route_source
    assert "log_general_admin_action(" in route_source
    assert "action='file_processing_logs_deleted'" in route_source
    assert_app_version_at_least("0.250.075")
