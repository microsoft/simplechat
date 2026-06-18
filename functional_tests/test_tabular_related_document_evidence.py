#!/usr/bin/env python3
# test_tabular_related_document_evidence.py
"""
Functional test for tabular related-document evidence.
Version: 0.242.071
Implemented in: 0.241.140; updated in 0.242.067

This test ensures that tabular rows can resolve explicit references to related
workspace documents, summarize that evidence for prompt handoff, and preserve
the related-document wiring in all tabular execution flows.
"""

import ast
import json
import os
import re
import sys
from types import SimpleNamespace


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'application', 'single_app'))

PLUGIN_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'semantic_kernel_plugins', 'tabular_processing_plugin.py')
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
TARGET_ASSIGNMENTS = {
    'TABULAR_RELATED_DOCUMENT_MAX_MATCHES_PER_ROW',
    'TABULAR_RELATED_DOCUMENT_MAX_SUMMARY_ROWS',
    'TABULAR_RELATED_DOCUMENT_MAX_EXCERPT_CHARS',
    'TABULAR_COMPUTED_RESULTS_HANDOFF_MAX_CHARS',
}
TARGET_FUNCTIONS = {
    '_normalize_requested_scope_ids',
    '_normalize_tabular_related_document_text',
    '_normalize_tabular_related_document_basename',
    '_is_tabular_related_document_candidate',
    '_tabular_text_mentions_related_document_reference',
    '_resolve_tabular_related_document_scope_ids',
    '_extract_tabular_row_related_documents',
    '_extract_tabular_related_row_identity',
    'build_tabular_related_document_evidence_summary',
    'build_tabular_computed_results_system_message',
}


def _truncate_log_text(value, max_length=80):
    normalized_value = str(value or '')
    if len(normalized_value) <= max_length:
        return normalized_value
    return f"{normalized_value[:max_length]}..."


def load_related_document_helpers():
    """Load the related-document helpers from the chat route source."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        route_content = file_handle.read()

    parsed = ast.parse(route_content, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            assignment_targets = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assignment_targets & TARGET_ASSIGNMENTS:
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'json': json,
        'os': os,
        're': re,
        'g': SimpleNamespace(),
        'has_request_context': lambda: False,
        'TABULAR_EXTENSIONS': {'csv', 'xlsx', 'xls', 'xlsm'},
        '_truncate_log_text': _truncate_log_text,
        'get_tabular_invocation_error_message': lambda invocation: getattr(invocation, 'error_message', None),
        'get_tabular_invocation_result_payload': lambda invocation: getattr(invocation, 'result', None),
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_content


def load_plugin_source() -> str:
    with open(PLUGIN_FILE, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def build_catalog_document(helpers, document_id, file_name, title=''):
    """Build a normalized catalog document payload for helper tests."""
    normalize_text = helpers['_normalize_tabular_related_document_text']
    normalize_basename = helpers['_normalize_tabular_related_document_basename']
    return {
        'document_id': document_id,
        'file_name': file_name,
        'title': title,
        'normalized_file_name': normalize_text(file_name),
        'normalized_basename': normalize_basename(file_name),
    }


def test_related_document_row_matching_detects_explicit_references():
    """Verify row matching resolves filename and basename references."""
    print('🔍 Testing row-level related-document reference matching...')

    try:
        helpers, _ = load_related_document_helpers()
        extract_matches = helpers['_extract_tabular_row_related_documents']
        is_candidate = helpers['_is_tabular_related_document_candidate']

        row_payload = {
            'RecordId': 'ROW-100',
            'ReferenceFile': 'Appendix A.pdf',
            'Notes': 'Support Plan describes the exception path for this row.',
            'Status': 'Open',
        }
        document_catalog = {
            'documents': [
                build_catalog_document(helpers, 'doc-appendix', 'Appendix A.pdf', title='Appendix A'),
                build_catalog_document(helpers, 'doc-plan', 'Support Plan.docx', title='Support Plan'),
            ]
        }

        matches = extract_matches(row_payload, document_catalog)

        assert is_candidate('Appendix A.pdf') is True
        assert is_candidate('worksheet.csv') is False
        assert len(matches) == 2, matches
        assert {match['document_id'] for match in matches} == {'doc-appendix', 'doc-plan'}, matches
        assert {match['matched_column'] for match in matches} == {'ReferenceFile', 'Notes'}, matches

        print('✅ Row-level related-document matching passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_related_document_summary_preserves_row_identity():
    """Verify the evidence summary keeps row identity and document excerpts."""
    print('🔍 Testing related-document evidence summary rendering...')

    try:
        helpers, _ = load_related_document_helpers()
        build_summary = helpers['build_tabular_related_document_evidence_summary']

        invocations = [
            SimpleNamespace(
                result={
                    'data': [
                        {
                            'OrderId': 'ORD-42',
                            'AccountName': 'Contoso',
                            'referenced_documents': [
                                {
                                    'document_id': 'doc-appendix',
                                    'file_name': 'Appendix A.pdf',
                                    'matched_column': 'ReferenceFile',
                                    'matched_reference': 'Appendix A.pdf',
                                    'page_number': 4,
                                    'excerpt': 'Appendix A confirms the invoice adjustment and payment terms.',
                                }
                            ],
                        }
                    ]
                }
            )
        ]

        summary_payload = build_summary(invocations)
        summary_rows = json.loads(summary_payload)

        assert len(summary_rows) == 1, summary_rows
        assert summary_rows[0]['row_identity']['OrderId'] == 'ORD-42', summary_rows
        assert summary_rows[0]['referenced_documents'][0]['file_name'] == 'Appendix A.pdf', summary_rows
        assert 'invoice adjustment' in summary_rows[0]['referenced_documents'][0]['excerpt'], summary_rows

        print('✅ Related-document evidence summary passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_related_document_row_matching_uses_preserved_reference_columns():
    """Verify hidden attachment/file columns remain available for document matching."""
    print('🔍 Testing related-document matching with preserved attachment columns...')

    try:
        helpers, _ = load_related_document_helpers()
        extract_matches = helpers['_extract_tabular_row_related_documents']

        row_payload = {
            'RecordId': 'ROW-200',
            'Notes': 'The comment is ambiguous and does not mention the appendix directly.',
            '_related_document_reference_values': {
                'Attached Files': 'Appendix A.pdf; Support Plan.docx',
            },
        }
        document_catalog = {
            'documents': [
                build_catalog_document(helpers, 'doc-appendix', 'Appendix A.pdf', title='Appendix A'),
                build_catalog_document(helpers, 'doc-plan', 'Support Plan.docx', title='Support Plan'),
            ]
        }

        matches = extract_matches(row_payload, document_catalog)

        assert len(matches) == 2, matches
        assert {match['matched_column'] for match in matches} == {'Attached Files'}, matches
        assert {match['document_id'] for match in matches} == {'doc-appendix', 'doc-plan'}, matches

        print('✅ Preserved attachment-column matching passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_related_document_scope_fallback_uses_authorized_chat_context():
    """Verify group/public related-document lookup can recover scope IDs from authorized chat context."""
    print('🔍 Testing related-document scope fallback from authorized chat context...')

    try:
        helpers, _ = load_related_document_helpers()
        resolve_scope_ids = helpers['_resolve_tabular_related_document_scope_ids']

        helpers['has_request_context'] = lambda: True
        helpers['g'] = SimpleNamespace(authorized_chat_context={
            'user_id': 'user-123',
            'conversation_id': 'conversation-456',
            'active_group_id': 'group-abc',
            'active_group_ids': ['group-abc'],
            'active_public_workspace_id': 'public-xyz',
            'active_public_workspace_ids': ['public-xyz'],
        })

        resolved_group_scope = resolve_scope_ids(
            'group',
            'user-123',
            conversation_id='conversation-456',
        )
        resolved_public_scope = resolve_scope_ids(
            'public',
            'user-123',
            conversation_id='conversation-456',
        )
        mismatched_scope = resolve_scope_ids(
            'group',
            'different-user',
            conversation_id='conversation-456',
        )

        assert resolved_group_scope['group_id'] == 'group-abc', resolved_group_scope
        assert resolved_public_scope['public_workspace_id'] == 'public-xyz', resolved_public_scope
        assert mismatched_scope['group_id'] is None, mismatched_scope

        print('✅ Related-document scope fallback passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_tabular_handoff_prompt_includes_related_document_evidence():
    """Verify the outer-model handoff includes resolved related-document evidence."""
    print('🔍 Testing tabular handoff prompt with related-document evidence...')

    try:
        helpers, _ = load_related_document_helpers()
        build_prompt = helpers['build_tabular_computed_results_system_message']
        related_summary = json.dumps([
            {
                'row_identity': {'OrderId': 'ORD-42'},
                'referenced_documents': [
                    {
                        'file_name': 'Appendix A.pdf',
                        'page_number': 4,
                        'excerpt': 'Appendix A confirms the invoice adjustment and payment terms.',
                    }
                ],
            }
        ])

        prompt = build_prompt(
            'the file(s) finance-workbook.xlsx',
            'OrderId=ORD-42; AdjustmentAmount=1250',
            related_document_evidence_summary=related_summary,
        )

        assert 'Related document evidence resolved from explicit document references in the tabular rows' in prompt, prompt
        assert related_summary in prompt, prompt
        assert 'Treat these excerpts as tabular-adjacent source evidence' in prompt, prompt

        print('✅ Tabular handoff prompt passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_route_wires_related_document_augmentation_into_all_tabular_flows():
    """Verify the route keeps related-document augmentation in each tabular flow."""
    print('🔍 Testing route wiring for related-document augmentation...')

    try:
        _, route_content = load_related_document_helpers()

        assert route_content.count('augment_tabular_invocations_with_related_document_evidence(') == 5, route_content
        assert route_content.count('related_document_evidence_summary=tabular_related_document_summary') == 2, route_content
        assert route_content.count('related_document_evidence_summary=chat_tabular_related_document_summary') == 2, route_content
        assert route_content.count('Input rows may include a referenced_documents array') == 1, route_content

        print('✅ Route wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_tabular_plugin_preserves_attachment_columns_when_return_columns_trim_rows():
    """Verify trimmed tabular row payloads keep hidden file/attachment columns for enrichment."""
    print('🔍 Testing tabular plugin attachment-column preservation...')

    try:
        plugin_content = load_plugin_source()

        assert 'def _build_related_document_reference_values(' in plugin_content, plugin_content
        assert 'def _is_related_document_reference_column_name(' in plugin_content, plugin_content
        assert "row_payload['_related_document_reference_values'] = related_document_reference_values" in plugin_content, plugin_content
        assert 'excluded_columns=resolved_return_columns' in plugin_content, plugin_content

        print('✅ Tabular plugin attachment-column preservation passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_related_document_row_matching_detects_explicit_references,
        test_related_document_summary_preserves_row_identity,
        test_related_document_row_matching_uses_preserved_reference_columns,
        test_related_document_scope_fallback_uses_authorized_chat_context,
        test_tabular_handoff_prompt_includes_related_document_evidence,
        test_route_wires_related_document_augmentation_into_all_tabular_flows,
        test_tabular_plugin_preserves_attachment_columns_when_return_columns_trim_rows,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)