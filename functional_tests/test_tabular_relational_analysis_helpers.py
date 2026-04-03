#!/usr/bin/env python3
# test_tabular_relational_analysis_helpers.py
"""
Functional test for tabular relational analysis helpers.
Version: 0.240.018
Implemented in: 0.240.018

This test ensures the tabular processing plugin can infer workbook relationship
metadata, return deterministic distinct values and row counts, and perform
explainable set-membership filtering and counting across related worksheets.
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

PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'semantic_kernel_plugins',
    'tabular_processing_plugin.py',
)
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')

PLUGIN_SPEC = importlib.util.spec_from_file_location('tabular_processing_plugin', PLUGIN_FILE)
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
TabularProcessingPlugin = PLUGIN_MODULE.TabularProcessingPlugin


def build_mock_workbook_plugin():
    """Create a plugin backed by in-memory workbook frames."""
    plugin = TabularProcessingPlugin()
    container_name = 'mock-container'
    blob_name = 'milestone_relationships.xlsx'

    engineer_frame = pd.DataFrame({
        'EngineerName': ['Paul Lizer', 'Alicia Stone', 'Morgan Lee'],
        'EngineerAlias': ['Paul-Lizer', '', ''],
        'Team': ['SE', 'SE', 'CSM'],
    })
    milestone_rows = [
        {'MilestoneID': f'MS{index:03d}', 'Owner': 'PAUL LIZER', 'OwnerAlias': '', 'MilestoneStatus': 'Open'}
        for index in range(1, 16)
    ]
    milestone_rows.extend([
        {'MilestoneID': f'MS{index:03d}', 'Owner': 'Paul-Lizer', 'OwnerAlias': 'Paul Lizer', 'MilestoneStatus': 'Open'}
        for index in range(16, 21)
    ])
    milestone_rows.extend([
        {'MilestoneID': f'MS{index:03d}', 'Owner': 'Alicia Stone', 'OwnerAlias': '', 'MilestoneStatus': 'Open'}
        for index in range(21, 31)
    ])
    milestone_rows.extend([
        {'MilestoneID': f'MS{index:03d}', 'Owner': 'Morgan Lee', 'OwnerAlias': '', 'MilestoneStatus': 'Closed'}
        for index in range(31, 36)
    ])
    milestone_rows.extend([
        {'MilestoneID': f'MS{index:03d}', 'Owner': 'Jamie Roe', 'OwnerAlias': '', 'MilestoneStatus': 'Open'}
        for index in range(36, 41)
    ])

    workbook_frames = {
        'solution_engineers': engineer_frame,
        'milestones': pd.DataFrame(milestone_rows),
        'metadata': pd.DataFrame({'RefreshDate': ['2026-04-02'], 'Source': ['unit-test']}),
    }
    workbook_metadata = {
        'is_workbook': True,
        'sheet_names': ['solution_engineers', 'milestones', 'metadata'],
        'sheet_count': 3,
        'default_sheet': 'solution_engineers',
    }

    plugin._resolve_blob_location_with_fallback = lambda *args, **kwargs: (container_name, blob_name)
    plugin._get_workbook_metadata = lambda *args, **kwargs: workbook_metadata.copy()

    def read_dataframe(container, blob, sheet_name=None, sheet_index=None, require_explicit_sheet=False):
        selected_sheet, _ = plugin._resolve_sheet_selection(
            container,
            blob,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
            require_explicit_sheet=require_explicit_sheet,
        )
        return workbook_frames[selected_sheet].copy()

    plugin._read_tabular_blob_to_dataframe = read_dataframe
    return plugin


def test_describe_tabular_file_infers_relationship_hints():
    """Verify workbook schema summaries include role and relationship hints."""
    print('🔍 Testing workbook relationship metadata...')

    try:
        plugin = build_mock_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.describe_tabular_file(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='milestone_relationships.xlsx',
            source='workspace',
        )))

        assert payload['is_workbook'] is True, payload
        assert payload['sheet_role_hints']['solution_engineers']['role'] == 'dimension', payload
        assert payload['sheet_role_hints']['milestones']['role'] == 'fact', payload
        relationship_hints = payload.get('relationship_hints', [])
        assert relationship_hints, payload
        top_hint = relationship_hints[0]
        assert top_hint['reference_sheet'] == 'solution_engineers', top_hint
        assert top_hint['fact_sheet'] == 'milestones', top_hint
        assert top_hint['normalized_overlap_count'] >= 2, top_hint

        print('✅ Workbook relationship metadata passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_get_distinct_values_returns_canonical_cohort():
    """Verify deterministic distinct values can build a filtered cohort."""
    print('🔍 Testing deterministic distinct values...')

    try:
        plugin = build_mock_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.get_distinct_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='milestone_relationships.xlsx',
            sheet_name='solution_engineers',
            column='EngineerName',
            filter_column='Team',
            filter_operator='equals',
            filter_value='SE',
            normalize_match='true',
            source='workspace',
        )))

        assert payload['selected_sheet'] == 'solution_engineers', payload
        assert payload['distinct_count'] == 2, payload
        assert payload['values'] == ['Alicia Stone', 'Paul Lizer'], payload

        print('✅ Deterministic distinct values passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_count_rows_returns_deterministic_row_count():
    """Verify the plugin returns an explicit row count after filtering."""
    print('🔍 Testing deterministic row counts...')

    try:
        plugin = build_mock_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.count_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='milestone_relationships.xlsx',
            sheet_name='milestones',
            filter_column='MilestoneStatus',
            filter_operator='equals',
            filter_value='Open',
            source='workspace',
        )))

        assert payload['selected_sheet'] == 'milestones', payload
        assert payload['row_count'] == 35, payload
        assert payload['rows_scanned'] == 40, payload

        print('✅ Deterministic row counts passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_related_value_helpers_return_explainable_outputs():
    """Verify semi-join helpers return deterministic counts and explainable metadata."""
    print('🔍 Testing related-value semi-join helpers...')

    try:
        plugin = build_mock_workbook_plugin()
        count_payload = json.loads(asyncio.run(plugin.count_rows_by_related_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='milestone_relationships.xlsx',
            source_sheet_name='solution_engineers',
            source_value_column='EngineerName',
            source_alias_column='EngineerAlias',
            source_filter_column='Team',
            source_filter_operator='equals',
            source_filter_value='SE',
            target_sheet_name='milestones',
            target_match_column='Owner',
            target_alias_column='OwnerAlias',
            target_filter_column='MilestoneStatus',
            target_filter_operator='equals',
            target_filter_value='Open',
            normalize_match='true',
            source='workspace',
        )))
        filter_payload = json.loads(asyncio.run(plugin.filter_rows_by_related_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='milestone_relationships.xlsx',
            source_sheet_name='solution_engineers',
            source_value_column='EngineerName',
            source_alias_column='EngineerAlias',
            source_filter_column='Team',
            source_filter_operator='equals',
            source_filter_value='SE',
            target_sheet_name='milestones',
            target_match_column='Owner',
            target_alias_column='OwnerAlias',
            target_filter_column='MilestoneStatus',
            target_filter_operator='equals',
            target_filter_value='Open',
            normalize_match='true',
            max_rows='5',
            source='workspace',
        )))

        assert count_payload['source_cohort_size'] == 2, count_payload
        assert count_payload['matched_source_value_count'] == 2, count_payload
        assert count_payload['unmatched_source_value_count'] == 0, count_payload
        assert count_payload['row_count'] == 30, count_payload
        assert count_payload['source_value_match_counts_returned'] == 2, count_payload
        assert count_payload['source_value_match_counts_limited'] is False, count_payload
        assert count_payload['source_value_match_counts'] == [
            {'source_value': 'Paul Lizer', 'matched_target_row_count': 20},
            {'source_value': 'Alicia Stone', 'matched_target_row_count': 10},
        ], count_payload
        assert filter_payload['matched_target_row_count'] == 30, filter_payload
        assert filter_payload['returned_rows'] == 5, filter_payload
        assert filter_payload['rows_limited'] is True, filter_payload
        assert filter_payload['data'][0]['_matched_on'], filter_payload
        assert filter_payload['data'][0]['_matched_source_values'], filter_payload

        print('✅ Related-value semi-join helpers passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_prompt_mentions_deterministic_relational_helpers():
    """Verify the analysis prompt advertises the new deterministic helper flow."""
    print('🔍 Testing route prompt guidance for relational helpers...')

    try:
        with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
            route_content = file_handle.read()

        checks = {
            'distinct helper advertised': 'get_distinct_values' in route_content,
            'count helper advertised': 'count_rows' in route_content,
            'related filter helper advertised': 'filter_rows_by_related_values' in route_content,
            'related count helper advertised': 'count_rows_by_related_values' in route_content,
            'cohort guidance exists': 'For cohort, membership, ownership-share, or percentage questions where one sheet defines the group and another sheet contains the fact rows' in route_content,
            'named member share guidance exists': "When the question asks for one named member's share within that cohort" in route_content,
            'deterministic count guidance exists': 'For deterministic how-many questions, use count_rows instead of estimating counts from partial returned rows.' in route_content,
            'relationship hints exposed in schema preload': "'relationship_hints': schema_info.get('relationship_hints', [])[:5]" in route_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f'Missing expected relational helper guidance: {failed_checks}'

        print('✅ Route prompt guidance for relational helpers passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_describe_tabular_file_infers_relationship_hints,
        test_get_distinct_values_returns_canonical_cohort,
        test_count_rows_returns_deterministic_row_count,
        test_related_value_helpers_return_explainable_outputs,
        test_route_prompt_mentions_deterministic_relational_helpers,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)