#!/usr/bin/env python3
# test_tabular_retry_sheet_recovery.py
"""
Functional test for workbook retry-sheet recovery.
Version: 0.239.117
Implemented in: 0.239.117

This test ensures tabular analytical tool failures on the wrong worksheet
return candidate recovery sheets, camel-case sheet names tokenize cleanly,
and the route retry helpers promote a better worksheet on the next attempt.
"""

import ast
import asyncio
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

import pandas as pd


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
PLUGIN_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'semantic_kernel_plugins',
    'tabular_processing_plugin.py',
)

TARGET_FUNCTIONS = {
    'get_tabular_analysis_function_names',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_candidate_sheets',
    'get_tabular_retry_sheet_overrides',
    '_normalize_tabular_sheet_token',
    '_tokenize_tabular_sheet_text',
}


def load_tabular_route_helpers():
    """Load selected helpers from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'json': json,
        're': __import__('re'),
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


PLUGIN_SPEC = importlib.util.spec_from_file_location('tabular_processing_plugin', PLUGIN_FILE)
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)
TabularProcessingPlugin = PLUGIN_MODULE.TabularProcessingPlugin


def build_mock_retry_plugin():
    """Create a plugin backed by an in-memory multi-sheet workbook."""
    plugin = TabularProcessingPlugin()
    container_name = 'mock-container'
    blob_name = 'irs_treasury_multi_tab_workbook.xlsx'
    workbook_frames = {
        'Taxpayers': pd.DataFrame({
            'TaxpayerID': ['TP000123'],
            'FirstName': ['Daniel'],
            'LastName': ['Garcia'],
        }),
        'TaxReturns': pd.DataFrame({
            'ReturnID': ['RET000123'],
            'TaxpayerID': ['TP000123'],
            'TaxLiability': ['4200'],
            'CreditsClaimed': ['300'],
            'WithholdingAmount': ['5000'],
            'EstimatedPaymentsAmount': ['250'],
            'RefundAmount': ['1350'],
            'BalanceDue': ['0'],
        }),
        'EstimatedPayments': pd.DataFrame({
            'ReturnID': ['RET000123'],
            'PaymentAmount': ['250'],
        }),
    }
    workbook_metadata = {
        'is_workbook': True,
        'sheet_names': ['Taxpayers', 'TaxReturns', 'EstimatedPayments'],
        'sheet_count': 3,
        'default_sheet': 'Taxpayers',
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


def test_sheet_tokenizer_splits_camel_case_names():
    """Verify camel-case worksheet names become analyzable tokens."""
    print('🔍 Testing camel-case sheet tokenization...')

    try:
        helpers, _ = load_tabular_route_helpers()
        tokenize_sheet_text = helpers['_tokenize_tabular_sheet_text']

        tokens = tokenize_sheet_text('TaxReturns')
        assert 'tax' in tokens, tokens
        assert 'return' in tokens, tokens

        payment_tokens = tokenize_sheet_text('EstimatedPayments')
        assert 'estimated' in payment_tokens, payment_tokens
        assert 'payment' in payment_tokens, payment_tokens

        print('✅ Camel-case sheet tokenization passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_lookup_value_missing_column_returns_candidate_sheets():
    """Verify cross-sheet search finds results when sheet_name is omitted, and
    missing-column errors include candidate recovery sheets when sheet_name is explicit."""
    print('🔍 Testing workbook-aware missing-column payloads...')

    try:
        plugin = build_mock_retry_plugin()

        # Case 1: cross-sheet search succeeds when sheet_name is omitted
        result_json = asyncio.run(plugin.lookup_value(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='irs_treasury_multi_tab_workbook.xlsx',
            lookup_column='ReturnID',
            lookup_value='RET000123',
            target_column='RefundAmount',
            source='workspace',
        ))
        payload = json.loads(result_json)
        assert payload['selected_sheet'] == 'ALL (cross-sheet search)', payload
        assert 'TaxReturns' in payload.get('sheets_matched', []), payload
        assert payload['total_matches'] >= 1, payload

        # Case 2: missing-column error with candidate sheets when sheet_name is explicit
        result_json_2 = asyncio.run(plugin.lookup_value(
            user_id='test-user',
            conversation_id='test-conversation',
            filename='irs_treasury_multi_tab_workbook.xlsx',
            lookup_column='ReturnID',
            lookup_value='RET000123',
            target_column='RefundAmount',
            sheet_name='Taxpayers',
            source='workspace',
        ))
        payload_2 = json.loads(result_json_2)
        assert payload_2['missing_column'] == 'ReturnID', payload_2
        assert payload_2['selected_sheet'] == 'Taxpayers', payload_2
        assert payload_2['candidate_sheets'][0] == 'TaxReturns', payload_2
        assert "Column 'ReturnID' not found on sheet 'Taxpayers'" in payload_2['error'], payload_2

        print('✅ Workbook-aware missing-column payloads passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_retry_sheet_override_prefers_candidate_sheet():
    """Verify retry helpers promote the best candidate worksheet after failure."""
    print('🔍 Testing retry worksheet override selection...')

    try:
        helpers, route_content = load_tabular_route_helpers()
        get_retry_sheet_overrides = helpers['get_tabular_retry_sheet_overrides']

        failed_invocation = SimpleNamespace(
            function_name='lookup_value',
            parameters={
                'filename': 'irs_treasury_multi_tab_workbook.xlsx',
            },
            result=json.dumps({
                'error': "Column 'ReturnID' not found on sheet 'Taxpayers'.",
                'filename': 'irs_treasury_multi_tab_workbook.xlsx',
                'missing_column': 'ReturnID',
                'selected_sheet': 'Taxpayers',
                'candidate_sheets': ['TaxReturns', 'EstimatedPayments'],
            }),
            error_message=None,
        )

        retry_sheet_overrides = get_retry_sheet_overrides([failed_invocation])

        assert retry_sheet_overrides['irs_treasury_multi_tab_workbook.xlsx']['sheet_name'] == 'TaxReturns', retry_sheet_overrides
        assert 'get_tabular_retry_sheet_overrides(failed_analytical_invocations)' in route_content, route_content
        assert "tabular_plugin.set_default_sheet(" in route_content, route_content

        print('✅ Retry worksheet override selection passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_sheet_tokenizer_splits_camel_case_names,
        test_lookup_value_missing_column_returns_candidate_sheets,
        test_retry_sheet_override_prefers_candidate_sheet,
    ]

    results = []
    for test_function in tests:
        print(f'\n🧪 Running {test_function.__name__}...')
        results.append(test_function())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)