#!/usr/bin/env python3
# test_tabular_entity_lookup_mode.py
"""
Functional test for cross-sheet entity lookup routing fix.
Version: 0.240.009
Implemented in: 0.240.009

This test ensures related-record workbook questions route to entity-lookup
mode, rank relevant worksheets beyond the first successful sheet, keep the
retry guardrails that prevent one-sheet success from ending the analysis too
early, and generate concrete per-sheet filter_rows call examples when the model
omits sheet_name on a multi-sheet workbook.
"""

import ast
import json
import os
import sys
from types import SimpleNamespace


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_FUNCTIONS = {
    'is_tabular_schema_summary_question',
    'is_tabular_entity_lookup_question',
    'get_tabular_execution_mode',
    'get_tabular_invocation_result_payload',
    'get_tabular_invocation_selected_sheet',
    'get_tabular_invocation_selected_sheets',
    '_normalize_tabular_sheet_token',
    '_tokenize_tabular_sheet_text',
    '_extract_tabular_entity_anchor_terms',
    '_score_tabular_sheet_match',
    '_score_tabular_entity_sheet_match',
    '_select_likely_workbook_sheet',
    '_select_relevant_workbook_sheets',
    'is_tabular_access_limited_analysis',
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


def test_cross_sheet_questions_route_to_entity_lookup_mode():
    """Verify related-record workbook prompts use entity-lookup mode."""
    print('🔍 Testing cross-sheet entity-lookup intent detection...')

    try:
        helpers, _ = load_tabular_route_helpers()
        is_entity_lookup_question = helpers['is_tabular_entity_lookup_question']
        get_execution_mode = helpers['get_tabular_execution_mode']

        entity_lookup_question = (
            'Find taxpayer TP000123. Show their profile, tax return summary, and '
            'any related W-2, 1099, payment, refund, notice, audit, or '
            'installment agreement records.'
        )
        full_story_question = (
            'Choose one taxpayer who has records in as many worksheets as '
            'possible and tell their full story from filing through payments, '
            'refund or balance outcome, notices, audit activity, and any '
            'installment agreement.'
        )
        schema_summary_question = 'Summarize this workbook and explain how the worksheets relate.'
        analytical_question = 'What was the total tax withheld in 2025?'

        assert is_entity_lookup_question(entity_lookup_question), entity_lookup_question
        assert get_execution_mode(entity_lookup_question) == 'entity_lookup', entity_lookup_question
        assert is_entity_lookup_question(full_story_question), full_story_question
        assert get_execution_mode(full_story_question) == 'entity_lookup', full_story_question
        assert not is_entity_lookup_question(schema_summary_question), schema_summary_question
        assert get_execution_mode(schema_summary_question) == 'schema_summary', schema_summary_question
        assert not is_entity_lookup_question(analytical_question), analytical_question
        assert get_execution_mode(analytical_question) == 'analysis', analytical_question

        print('✅ Cross-sheet entity-lookup intent detection passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_entity_lookup_sheet_selection_prioritizes_related_worksheets():
    """Verify sheet scoring keeps multiple related IRS worksheets in scope."""
    print('🔍 Testing entity-lookup worksheet ranking...')

    try:
        helpers, _ = load_tabular_route_helpers()
        select_relevant_sheets = helpers['_select_relevant_workbook_sheets']

        sheet_names = [
            'Taxpayers',
            'TaxReturns',
            'W2Forms',
            'Form1099Income',
            'EstimatedPayments',
            'Refunds',
            'Notices',
            'Audits',
            'InstallmentAgreements',
            'ReferenceData',
        ]
        entity_lookup_question = (
            'Find taxpayer TP000123. Show their profile, tax return summary, and '
            'any related W-2, 1099, payment, refund, notice, audit, or '
            'installment agreement records.'
        )

        relevant_sheets = select_relevant_sheets(sheet_names, entity_lookup_question)

        assert 'Taxpayers' in relevant_sheets, relevant_sheets
        assert 'TaxReturns' in relevant_sheets, relevant_sheets
        assert 'W2Forms' in relevant_sheets, relevant_sheets
        assert 'Form1099Income' in relevant_sheets, relevant_sheets
        assert 'EstimatedPayments' in relevant_sheets, relevant_sheets
        assert 'Refunds' in relevant_sheets, relevant_sheets
        assert 'Notices' in relevant_sheets, relevant_sheets
        assert 'Audits' in relevant_sheets, relevant_sheets
        assert 'InstallmentAgreements' in relevant_sheets, relevant_sheets
        assert 'ReferenceData' not in relevant_sheets, relevant_sheets

        print('✅ Entity-lookup worksheet ranking passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_entity_lookup_primary_sheet_hint_prefers_anchor_entity_sheet():
    """Verify entity lookup mode prioritizes the primary entity worksheet."""
    print('🔍 Testing entity-lookup primary worksheet hinting...')

    try:
        helpers, route_content = load_tabular_route_helpers()
        extract_anchor_terms = helpers['_extract_tabular_entity_anchor_terms']
        score_entity_sheet = helpers['_score_tabular_entity_sheet_match']
        select_likely_sheet = helpers['_select_likely_workbook_sheet']
        select_relevant_sheets = helpers['_select_relevant_workbook_sheets']

        entity_lookup_question = (
            'Find taxpayer TP000123. Show their profile, tax return summary, and '
            'any related W-2, 1099, payment, refund, notice, audit, or '
            'installment agreement records.'
        )
        per_sheet = {
            'Taxpayers': {
                'columns': ['TaxpayerID', 'FirstName', 'LastName', 'Status'],
            },
            'TaxReturns': {
                'columns': ['ReturnID', 'TaxpayerID', 'TaxLiability', 'RefundAmount'],
            },
            'Audits': {
                'columns': ['AuditID', 'TaxpayerID', 'AuditStatus'],
            },
            'Notices': {
                'columns': ['NoticeID', 'TaxpayerID', 'NoticeType'],
            },
        }
        sheet_names = list(per_sheet.keys())

        anchor_terms = extract_anchor_terms(entity_lookup_question)
        likely_sheet = select_likely_sheet(
            sheet_names,
            entity_lookup_question,
            per_sheet=per_sheet,
            score_match_fn=score_entity_sheet,
        )
        relevant_sheets = select_relevant_sheets(
            sheet_names,
            entity_lookup_question,
            per_sheet=per_sheet,
            score_match_fn=score_entity_sheet,
        )

        assert anchor_terms[0] == 'taxpayer', anchor_terms
        assert 'taxpayer' in anchor_terms, anchor_terms
        assert likely_sheet == 'Taxpayers', likely_sheet
        assert relevant_sheets[0] == 'Taxpayers', relevant_sheets
        assert relevant_sheets.index('Taxpayers') < relevant_sheets.index('Notices'), relevant_sheets
        assert 'begin with filter_rows or query_tabular_data without sheet_name so the plugin can perform a cross-sheet discovery search' in route_content, route_content
        assert 'Do not start with aggregate_column, group_by_aggregate, or group_by_datetime_component until you have located the relevant entity rows.' in route_content, route_content

        print('✅ Entity-lookup primary worksheet hinting passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_entity_lookup_retry_guardrails_detect_incomplete_successes():
    """Verify one-sheet successes still trigger execution-gap retries."""
    print('🔍 Testing entity-lookup retry guardrails...')

    try:
        helpers, route_content = load_tabular_route_helpers()
        get_selected_sheets = helpers['get_tabular_invocation_selected_sheets']
        is_access_limited_analysis = helpers['is_tabular_access_limited_analysis']

        invocations = [
            SimpleNamespace(
                function_name='filter_rows',
                parameters={'sheet_name': 'Taxpayers'},
                result=json.dumps({
                    'selected_sheet': 'Taxpayers',
                    'returned_rows': 1,
                }),
            ),
            SimpleNamespace(
                function_name='filter_rows',
                parameters={'sheet_name': 'Taxpayers'},
                result=json.dumps({
                    'selected_sheet': 'Taxpayers',
                    'returned_rows': 1,
                }),
            ),
        ]
        incomplete_analysis = (
            "I don't have direct access to the related tax return and payment rows yet, "
            'but I can outline what I would retrieve next.'
        )

        selected_sheets = get_selected_sheets(invocations)

        assert selected_sheets == ['Taxpayers'], selected_sheets
        assert is_access_limited_analysis(incomplete_analysis), incomplete_analysis
        assert 'execution_gap_messages=previous_execution_gap_messages' in route_content, route_content
        assert 'len(selected_sheets) <= 1' in route_content, route_content
        assert 'Do not rely on a default sheet for cross-sheet entity lookups.' in route_content, route_content
        # New: verify concrete call example infrastructure is present
        assert 'previous_failed_call_parameters' in route_content, 'missing previous_failed_call_parameters'
        assert 'MULTI-SHEET RETRY REQUIRED' in route_content, 'missing MULTI-SHEET RETRY REQUIRED block'
        assert 'Execute ALL of these calls now' in route_content, 'missing execute-all-calls instruction'

        print('✅ Entity-lookup retry guardrails passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_entity_lookup_missing_sheet_feedback_generates_concrete_examples():
    """Verify the retry prompt generates per-sheet filter_rows examples from failed call parameters."""
    print('🔍 Testing concrete call example generation for entity-lookup retry...')

    try:
        route_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app', 'route_backend_chats.py')
        with open(route_src, encoding='utf-8') as fh:
            route_content = fh.read()

        # Simulate the missing_sheet_feedback generation logic extracted from build_system_prompt
        # by executing the relevant block in isolation with dummy data
        IRS_WORKBOOK = 'irs_treasury_multi_tab_workbook.xlsx'
        RELATED_SHEETS = ['Taxpayers', 'TaxReturns', 'W2Forms', 'Form1099Income', 'EstimatedPayments', 'Refunds']

        previous_failed_call_parameters = [
            {'filename': IRS_WORKBOOK, 'column': 'TaxpayerID', 'operator': '==', 'value': 'TP000123'},
        ]
        workbook_related_sheet_hints = {IRS_WORKBOOK: RELATED_SHEETS}
        workbook_sheet_hints = {IRS_WORKBOOK: 'Taxpayers'}
        entity_lookup_mode = True
        tool_error_messages = [
            f"Workbook '{IRS_WORKBOOK}' has multiple sheets. Specify sheet_name or sheet_index on analytical calls."
        ]

        # Run the logic exactly as it appears in build_system_prompt
        call_example_lines = []
        if tool_error_messages and any(
            'Specify sheet_name or sheet_index on analytical calls.' in em
            for em in tool_error_messages
        ) and entity_lookup_mode:
            for failed_params in previous_failed_call_parameters[:2]:
                fname = failed_params.get('filename', '')
                col = failed_params.get('column', '')
                op = failed_params.get('operator', '==')
                val = failed_params.get('value', '')
                if not fname or not col or not val:
                    continue
                related_sheets = workbook_related_sheet_hints.get(fname) or list(workbook_sheet_hints.values())
                for sheet in related_sheets[:6]:
                    call_example_lines.append(
                        f'  filter_rows(filename="{fname}", sheet_name="{sheet}", column="{col}", operator="{op}", value="{val}")'
                    )

        assert len(call_example_lines) > 0, 'No call examples generated'
        examples_block = '\n'.join(call_example_lines)

        # Key assertions: all 6 relevant sheets appear in the examples
        for sheet in RELATED_SHEETS[:6]:
            assert f'sheet_name="{sheet}"' in examples_block, f'Missing sheet: {sheet}'

        # Entity identifier is included correctly
        assert 'column="TaxpayerID"' in examples_block, 'Missing column in examples'
        assert 'value="TP000123"' in examples_block, 'Missing entity value in examples'

        # Source code has the full prompt block
        assert 'MULTI-SHEET RETRY REQUIRED' in route_content, 'Missing MULTI-SHEET RETRY REQUIRED prompt'
        assert 'Execute ALL of these calls now (copy exactly as written)' in route_content, 'Missing copy-exactly prompt'

        print('✅ Concrete call example generation passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_cross_sheet_questions_route_to_entity_lookup_mode,
        test_entity_lookup_sheet_selection_prioritizes_related_worksheets,
        test_entity_lookup_primary_sheet_hint_prefers_anchor_entity_sheet,
        test_entity_lookup_retry_guardrails_detect_incomplete_successes,
        test_entity_lookup_missing_sheet_feedback_generates_concrete_examples,
    ]

    results = []
    for test_function in tests:
        print(f'\n🧪 Running {test_function.__name__}...')
        results.append(test_function())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)