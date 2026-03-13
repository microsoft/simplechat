#!/usr/bin/env python3
# test_tabular_grouped_peak_summary.py
"""
Functional test for generic grouped peak summary and datetime parsing fix.
Version: 0.239.036
Implemented in: 0.239.036

This test ensures that generic grouping tools return explicit highest/lowest
summary fields and that artifact-style US datetime strings can be grouped by
hour for peak-style analytical questions.
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


def test_artifact_style_hour_grouping_returns_peak_summary():
    """Verify M/D/YYYY h:mm:ss AM/PM timestamps group correctly by hour."""
    print("🔍 Testing artifact-style datetime hour grouping summary...")

    try:
        dataframe = pd.DataFrame({
            'ActualDeparture': [
                '5/14/2026 8:31:36 AM',
                '5/14/2026 8:46:10 AM',
                '5/14/2026 9:00:36 PM',
                '5/14/2026 9:15:36 PM',
            ],
            'DepartureQueueLength': ['18', '20', '22', '18'],
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
            top_n='2',
        ))
        payload = json.loads(result_json)

        assert 'error' not in payload, f"Unexpected error payload: {payload}"
        assert payload['highest_group'] == '21', payload
        assert float(payload['highest_value']) == 20.0, payload
        assert payload['second_highest_group'] == '8', payload
        assert payload['lowest_group'] == '8', payload
        assert float(payload['top_results']['21']) == 20.0, payload

        print("✅ Artifact-style datetime hour grouping summary passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_group_by_aggregate_returns_generic_peak_summary():
    """Verify generic grouped aggregation exposes highest and lowest group metadata."""
    print("🔍 Testing generic grouped aggregation peak summary...")

    try:
        dataframe = pd.DataFrame({
            'Airline': ['A', 'A', 'B', 'B', 'C', 'C'],
            'DelayMinutes': ['1', '2', '5', '7', '3', '4'],
        })

        plugin = build_plugin_with_dataframe(dataframe)
        result_json = asyncio.run(plugin.group_by_aggregate(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='faa.csv',
            group_by_column='Airline',
            aggregate_column='DelayMinutes',
            operation='median',
            source='workspace',
            top_n='2',
        ))
        payload = json.loads(result_json)

        assert 'error' not in payload, f"Unexpected error payload: {payload}"
        assert payload['highest_group'] == 'B', payload
        assert float(payload['highest_value']) == 6.0, payload
        assert payload['lowest_group'] == 'A', payload
        assert float(payload['lowest_value']) == 1.5, payload
        assert list(payload['top_results'].keys()) == ['B', 'C'], payload

        print("✅ Generic grouped aggregation peak summary passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_route_prompt_mentions_group_summary_fields():
    """Verify the tabular prompt guides the model to use grouped summary fields."""
    print("🔍 Testing route prompt guidance for grouped summaries...")

    try:
        with open(ROUTE_FILE, 'r', encoding='utf-8') as route_handle:
            route_content = route_handle.read()

        checks = {
            'prompt mentions highest_group summary': 'highest_group, highest_value, lowest_group, and lowest_value summary fields' in route_content,
            'plugin helper exists': 'def _build_grouped_summary(' in open(PLUGIN_FILE, 'r', encoding='utf-8').read(),
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f"Missing expected grouped-summary guidance: {failed_checks}"

        print("✅ Route prompt grouped-summary guidance passed")
        return True

    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_artifact_style_hour_grouping_returns_peak_summary,
        test_group_by_aggregate_returns_generic_peak_summary,
        test_route_prompt_mentions_group_summary_fields,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
