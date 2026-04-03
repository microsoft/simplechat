#!/usr/bin/env python3
# test_tabular_relational_analysis_helpers.py
"""
Functional test for tabular relational analysis helpers.
Version: 0.240.043
Implemented in: 0.240.018; 0.240.037; 0.240.038; 0.240.039; 0.240.040; 0.240.041; 0.240.042; 0.240.043

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


def build_multi_filter_workbook_plugin():
    """Create a plugin backed by workbook sheets for multi-condition text filters."""
    plugin = TabularProcessingPlugin()
    container_name = 'mock-container'
    blob_name = 'cco_sharepoint_sites.xlsx'

    workbook_frames = {
        'File Plan Q1': pd.DataFrame([
            {
                'Business Unit': 'CCO - Supervision',
                'Location': 'AIL: SharePoint - https://contoso.sharepoint.com/sites/Alpha/SitePages/Home.aspx',
                'Site': 'Alpha',
                'Schedule Notes': 'Primary schedules: GRS 6.1; GRS 2.4',
            },
            {
                'Business Unit': 'CCO - Supervision',
                'Location': 'BA: SharePoint - https://contoso.sharepoint.com/sites/Beta/Forms/AllItems.aspx',
                'Site': 'Beta',
                'Schedule Notes': 'Secondary schedules: GRS 2.4',
            },
            {
                'Business Unit': 'Finance',
                'Location': 'Finance docs - https://contoso.sharepoint.com/sites/Gamma/SitePages/Home.aspx',
                'Site': 'Gamma',
                'Schedule Notes': 'Finance schedules: GRS 8.3',
            },
            {
                'Business Unit': 'CCO - Supervision',
                'Location': 'Network Drive',
                'Site': 'Legacy',
                'Schedule Notes': 'Legacy schedules: GRS 1.1',
            },
        ]),
        'File Plan Q2': pd.DataFrame([
            {
                'Business Unit': 'CCO Legal',
                'Location': 'DCCO: SharePoint - https://contoso.sharepoint.com/sites/Delta/Shared%20Documents/Forms/AllItems.aspx',
                'Site': 'Delta',
                'Schedule Notes': 'Legal schedules: GRS 6.1',
            },
            {
                'Business Unit': 'CCO Legal',
                'Location': 'WEDO: SharePoint - https://contoso.sharepoint.com/sites/Beta/SitePages/Home.aspx',
                'Site': 'Beta',
                'Schedule Notes': 'Duplicates: GRS 2.4; GRS 6.1',
            },
            {
                'Business Unit': 'Treasury',
                'Location': 'Treasury docs - https://contoso.sharepoint.com/sites/Zeta/SitePages/Home.aspx',
                'Site': 'Zeta',
                'Schedule Notes': 'Treasury schedules: GRS 9.1',
            },
        ]),
        'Notes': pd.DataFrame([
            {'Comment': 'Ignore this sheet for site searches'},
        ]),
    }
    workbook_metadata = {
        'is_workbook': True,
        'sheet_names': ['File Plan Q1', 'File Plan Q2', 'Notes'],
        'sheet_count': 3,
        'default_sheet': 'File Plan Q1',
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


def test_multi_filter_helpers_support_cross_sheet_contains_queries():
    """Verify count and distinct helpers can combine two text filters across sheets."""
    print('🔍 Testing cross-sheet multi-filter helpers...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        distinct_payload = json.loads(asyncio.run(plugin.get_distinct_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            column='Site',
            filter_column='Business Unit',
            filter_operator='contains',
            filter_value='CCO',
            additional_filter_column='Location',
            additional_filter_operator='contains',
            additional_filter_value='sharepoint',
            normalize_match='false',
            source='workspace',
        )))
        count_payload = json.loads(asyncio.run(plugin.count_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            filter_column='Business Unit',
            filter_operator='contains',
            filter_value='CCO',
            additional_filter_column='Location',
            additional_filter_operator='contains',
            additional_filter_value='sharepoint',
            normalize_match='false',
            source='workspace',
        )))

        assert distinct_payload['selected_sheet'] == 'ALL (cross-sheet search)', distinct_payload
        assert distinct_payload['distinct_count'] == 3, distinct_payload
        assert distinct_payload['values'] == ['Alpha', 'Beta', 'Delta'], distinct_payload
        assert len(distinct_payload['filter_applied']) == 2, distinct_payload
        assert count_payload['selected_sheet'] == 'ALL (cross-sheet search)', count_payload
        assert count_payload['row_count'] == 4, count_payload
        assert len(count_payload['filter_applied']) == 2, count_payload

        print('✅ Cross-sheet multi-filter helpers passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_filter_rows_supports_additional_column_filter():
    """Verify filter_rows can apply a second literal filter without query syntax."""
    print('🔍 Testing additional filter support in filter_rows...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.filter_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            column='Business Unit',
            operator='contains',
            value='CCO',
            additional_filter_column='Location',
            additional_filter_operator='contains',
            additional_filter_value='sharepoint',
            normalize_match='false',
            source='workspace',
            max_rows='10',
        )))

        assert payload['selected_sheet'] == 'ALL (cross-sheet search)', payload
        assert payload['total_matches'] == 4, payload
        assert payload['returned_rows'] == 4, payload
        assert len(payload['filter_applied']) == 2, payload
        assert {row['_sheet'] for row in payload['data']} == {'File Plan Q1', 'File Plan Q2'}, payload

        print('✅ Additional filter support in filter_rows passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_get_distinct_values_extracts_embedded_url_roots_from_filtered_cells():
    """Verify embedded URL extraction can normalize higher-level site roots from text cells."""
    print('🔍 Testing embedded URL extraction in distinct values...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.get_distinct_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            column='Location',
            filter_column='Business Unit',
            filter_operator='contains',
            filter_value='CCO',
            additional_filter_column='Location',
            additional_filter_operator='contains',
            additional_filter_value='sharepoint',
            extract_mode='url',
            url_path_segments='2',
            normalize_match='false',
            source='workspace',
        )))

        assert payload['selected_sheet'] == 'ALL (cross-sheet search)', payload
        assert payload['extract_mode'] == 'url', payload
        assert payload['url_path_segments'] == 2, payload
        assert payload['matched_cell_count'] == 4, payload
        assert payload['extracted_match_count'] == 4, payload
        assert payload['distinct_count'] == 3, payload
        assert payload['values'] == [
            'https://contoso.sharepoint.com/sites/Alpha',
            'https://contoso.sharepoint.com/sites/Beta',
            'https://contoso.sharepoint.com/sites/Delta',
        ], payload

        print('✅ Embedded URL extraction in distinct values passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_get_distinct_values_supports_regex_extraction_from_text_cells():
    """Verify regex extraction can return canonical identifiers embedded in text cells."""
    print('🔍 Testing regex extraction in distinct values...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.get_distinct_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            column='Schedule Notes',
            filter_column='Business Unit',
            filter_operator='contains',
            filter_value='CCO',
            extract_mode='regex',
            extract_pattern=r'(GRS\s+\d+\.\d+)',
            normalize_match='false',
            source='workspace',
        )))

        assert payload['extract_mode'] == 'regex', payload
        assert payload['matched_cell_count'] == 5, payload
        assert payload['extracted_match_count'] == 7, payload
        assert payload['distinct_count'] == 3, payload
        assert payload['values'] == ['GRS 1.1', 'GRS 2.4', 'GRS 6.1'], payload

        print('✅ Regex extraction in distinct values passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_search_rows_can_search_all_columns_and_return_target_values():
    """Verify generic row search can scan all columns and surface chosen values."""
    print('🔍 Testing generic row search across all columns...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        payload = json.loads(asyncio.run(plugin.search_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            search_value='GRS 6.1',
            return_columns='Business Unit,Location,Site',
            normalize_match='false',
            source='workspace',
            max_rows='10',
        )))

        assert payload['selected_sheet'] == 'ALL (cross-sheet search)', payload
        assert payload['search_value'] == 'GRS 6.1', payload
        assert payload['total_matches'] == 3, payload
        assert payload['returned_rows'] == 3, payload
        assert payload['matched_columns'] == ['Schedule Notes'], payload
        assert payload['return_columns'] == ['Business Unit', 'Location', 'Site'], payload
        assert payload['data'][0]['_matched_columns'] == ['Schedule Notes'], payload
        assert 'Schedule Notes' not in payload['data'][0], payload
        assert payload['data'][0]['Business Unit'], payload
        assert payload['data'][0]['Location'], payload
        assert payload['data'][0]['Site'], payload

        print('✅ Generic row search across all columns passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_reviewer_style_text_query_expression_rewrites_for_count_and_distinct_calls():
    """Verify reviewer-style pseudo queries are rewritten instead of failing."""
    print('🔍 Testing reviewer-style pseudo query rewrite...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        pseudo_query = "`Business Unit`.astype(str).str.contains('CCO', case=False, na=False) and Location.astype(str).str.contains('sharepoint', case=False, na=False)"

        count_payload = json.loads(asyncio.run(plugin.count_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            query_expression=pseudo_query,
            normalize_match='false',
            source='workspace',
        )))
        distinct_payload = json.loads(asyncio.run(plugin.get_distinct_values(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            column='Location',
            query_expression=pseudo_query,
            extract_mode='url',
            url_path_segments='2',
            normalize_match='false',
            source='workspace',
        )))

        assert count_payload['selected_sheet'] == 'ALL (cross-sheet search)', count_payload
        assert count_payload['row_count'] == 4, count_payload
        assert count_payload['filter_applied'][0].endswith('[reviewer-style fallback]'), count_payload
        assert distinct_payload['selected_sheet'] == 'ALL (cross-sheet search)', distinct_payload
        assert distinct_payload['distinct_count'] == 3, distinct_payload
        assert distinct_payload['filter_applied'][0].endswith('[reviewer-style fallback]'), distinct_payload
        assert distinct_payload['values'] == [
            'https://contoso.sharepoint.com/sites/Alpha',
            'https://contoso.sharepoint.com/sites/Beta',
            'https://contoso.sharepoint.com/sites/Delta',
        ], distinct_payload

        print('✅ Reviewer-style pseudo query rewrite passed')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_reviewer_style_null_literal_query_expression_rewrites_for_count_calls():
    """Verify reviewer-style null literals are rewritten instead of failing."""
    print('🔍 Testing reviewer-style null literal query rewrite...')

    try:
        plugin = build_multi_filter_workbook_plugin()
        count_payload = json.loads(asyncio.run(plugin.count_rows(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='cco_sharepoint_sites.xlsx',
            query_expression='Location != null',
            filter_column='Business Unit',
            filter_operator='contains',
            filter_value='CCO',
            normalize_match='false',
            source='workspace',
        )))

        assert count_payload['selected_sheet'] == 'ALL (cross-sheet search)', count_payload
        assert count_payload['row_count'] == 5, count_payload
        assert count_payload['filter_applied'][0].endswith('[reviewer-style fallback]'), count_payload

        print('✅ Reviewer-style null literal query rewrite passed')
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
            'generic search tool advertised': 'search_rows' in route_content,
            'whole-doc search guidance exists': 'If the question includes an exact identifier or asks where a topic, phrase, path, code, or other value appears and the correct starting worksheet or column is unclear, begin with search_rows' in route_content,
            'return columns guidance exists': 'use return_columns to surface the columns most relevant to the question' in route_content.casefold(),
            'multi-condition guidance exists': 'When the cohort is defined by two literal conditions on different columns' in route_content,
            'additional filter args advertised': 'additional_filter_column' in route_content,
            'embedded extraction guidance exists': "extract_mode='url' or extract_mode='regex'" in route_content,
            'url root guidance exists': 'url_path_segments' in route_content,
            'contextual text-search guidance exists': 'If whether an embedded URL, site, link, or identifier counts depends on surrounding text in the original cell rather than the extracted value itself' in route_content,
            'full row context guidance exists': 'Prefer filter_rows when the matching row context matters, and return the full matching rows when the cohort is modest enough to fit comfortably.' in route_content,
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
        test_multi_filter_helpers_support_cross_sheet_contains_queries,
        test_filter_rows_supports_additional_column_filter,
        test_get_distinct_values_extracts_embedded_url_roots_from_filtered_cells,
        test_get_distinct_values_supports_regex_extraction_from_text_cells,
        test_search_rows_can_search_all_columns_and_return_target_values,
        test_reviewer_style_text_query_expression_rewrites_for_count_and_distinct_calls,
        test_reviewer_style_null_literal_query_expression_rewrites_for_count_calls,
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