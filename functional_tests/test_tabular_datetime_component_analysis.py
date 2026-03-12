#!/usr/bin/env python3
# test_tabular_datetime_component_analysis.py
"""
Functional test for tabular datetime component analysis fix.
Version: 0.239.033
Implemented in: 0.239.033

This test ensures that time-based tabular questions can be computed by grouping
on datetime-derived components such as hour-of-day, reducing schema-only
fallbacks for questions like peak departure queue hours.
"""

import asyncio
import importlib.util
import json
import os
import sys

import pandas as pd

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))


ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
PLUGIN_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'semantic_kernel_plugins', 'tabular_processing_plugin.py')


PLUGIN_SPEC = importlib.util.spec_from_file_location('tabular_processing_plugin', PLUGIN_FILE)
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
TabularProcessingPlugin = PLUGIN_MODULE.TabularProcessingPlugin


def build_plugin_with_dataframe(dataframe):
    """Create a plugin instance backed by an in-memory DataFrame."""
    plugin = TabularProcessingPlugin()
    plugin._resolve_blob_location = lambda *args, **kwargs: ('mock-container', 'mock-file.csv')
    plugin._read_tabular_blob_to_dataframe = lambda *args, **kwargs: dataframe.copy()
    return plugin


def test_hour_grouping_with_iso_datetimes():
    """Verify hourly grouping works with ISO-style datetime strings."""
    print("🔍 Testing ISO datetime hour grouping...")

    try:
        dataframe = pd.DataFrame({
            'ActualDeparture': [
                '2026-03-12 17:05:00',
                '2026-03-12 17:35:00',
                '2026-03-12 18:10:00',
                '2026-03-12 06:55:00',
            ],
            'DepartureQueueLength': ['12', '8', '5', '2'],
        })

        plugin = build_plugin_with_dataframe(dataframe)
        result_json = asyncio.run(plugin.group_by_datetime_component(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='faa.csv',
            datetime_column='ActualDeparture',
            datetime_component='hour',
            aggregate_column='DepartureQueueLength',
            operation='mean',
            source='workspace',
            top_n='3',
        ))
        payload = json.loads(result_json)

        assert 'error' not in payload, f"Unexpected error payload: {payload}"
        assert payload['datetime_component'] == 'hour', 'Expected hour grouping.'
        assert float(payload['top_results']['17']) == 10.0, 'Hour 17 should have mean queue length 10.0.'
        assert float(payload['result']['6']) == 2.0, 'Hour 6 should be present in chronological results.'

        print("✅ ISO datetime hour grouping passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_hour_grouping_with_hhmm_values():
    """Verify HHMM-style time strings are parsed for hour grouping."""
    print("🔍 Testing HHMM hour grouping...")

    try:
        dataframe = pd.DataFrame({
            'ScheduledDeparture': ['0630', '0715', '0710', '1830'],
            'DepartureQueueLength': ['1', '4', '6', '3'],
        })

        plugin = build_plugin_with_dataframe(dataframe)
        result_json = asyncio.run(plugin.group_by_datetime_component(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='faa.csv',
            datetime_column='ScheduledDeparture',
            datetime_component='hour',
            aggregate_column='DepartureQueueLength',
            operation='mean',
            source='workspace',
            top_n='2',
        ))
        payload = json.loads(result_json)

        assert 'error' not in payload, f"Unexpected error payload: {payload}"
        assert float(payload['top_results']['7']) == 5.0, 'Hour 7 should have mean queue length 5.0.'
        assert payload['parsed_rows'] == 4, 'All HHMM rows should be parsed successfully.'

        print("✅ HHMM hour grouping passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_route_and_plugin_integration_text():
    """Verify the chat route references datetime grouping support and fallback guidance."""
    print("🔍 Testing route/plugin integration text...")

    try:
        with open(ROUTE_FILE, 'r', encoding='utf-8') as route_handle:
            route_content = route_handle.read()
        with open(PLUGIN_FILE, 'r', encoding='utf-8') as plugin_handle:
            plugin_content = plugin_handle.read()

        checks = {
            'plugin function exists': 'def group_by_datetime_component(' in plugin_content,
            'route prompt mentions datetime grouping': 'For time-based questions on datetime columns, use group_by_datetime_component.' in route_content,
            'route direct fallback exists': 'Direct datetime fallback succeeded' in route_content,
            'file guidance mentions datetime grouping': 'group_by_datetime_component) to analyze this data.' in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected integration text: {failed_checks}"

        print("✅ Route/plugin integration text passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_hour_grouping_with_iso_datetimes,
        test_hour_grouping_with_hhmm_values,
        test_route_and_plugin_integration_text,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
