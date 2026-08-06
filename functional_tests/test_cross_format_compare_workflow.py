#!/usr/bin/env python3
# test_cross_format_compare_workflow.py
"""
Functional test for Phase 4 cross-format Compare.
Version: 0.250.067
Implemented in: 0.250.067

This test ensures #1059 retains one Source and ordered Targets, uses bounded
native evidence, and preserves failed Targets during pairwise reduction.
Parent: #1055. Prerequisites: #1056, #1057, and #1058.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPARISON = ROOT / 'application' / 'single_app' / 'functions_document_comparison.py'
WORKFLOW = ROOT / 'application' / 'single_app' / 'functions_workflow_runner.py'
SETTINGS = ROOT / 'application' / 'single_app' / 'functions_settings.py'


def _load_evidence_comparison():
    source = COMPARISON.read_text(encoding='utf-8')
    tree = ast.parse(source)
    names = {
        '_build_pairwise_comparison_prompt',
        '_build_comparison_reduction_prompt',
        'run_evidence_document_comparison',
    }
    module = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(COMPARISON), 'exec'), namespace)
    return namespace['run_evidence_document_comparison']


def test_pairwise_reducer_preserves_target_order_and_partial_failure():
    """Completed Targets are compared in order while a failed Target remains visible."""
    compare = _load_evidence_comparison()
    calls = []

    def invoke_prompt(prompt, stage='', metadata=None):
        calls.append((stage, metadata or {}))
        return f"{stage}:{metadata.get('right_document_id', 'reduction')}"

    result = compare(
        'Compare calculated facts with stated policy.',
        {
            'document_id': 'source-csv',
            'document_name': 'Source.csv',
            'source_kind': 'tabular',
            'engine': 'tabular_tools',
            'status': 'completed',
            'summary': 'Computed total: 24.',
        },
        [
            {
                'document_id': 'target-pdf',
                'document_name': 'Target.pdf',
                'source_kind': 'narrative',
                'engine': 'document_analysis',
                'status': 'completed',
                'summary': 'The policy states a total of 23.',
            },
            {
                'document_id': 'target-xlsx',
                'document_name': 'Target.xlsx',
                'source_kind': 'tabular',
                'engine': 'tabular_tools',
                'status': 'failed',
                'summary': '',
            },
        ],
        invoke_prompt,
    )

    assert [item['right_document_id'] for item in result['comparison_items']] == ['target-pdf']
    assert result['coverage']['failed_targets'] == ['Target.xlsx']
    assert calls == [('comparison', {'comparison_index': 1, 'comparison_count': 2, 'left_document_id': 'source-csv', 'right_document_id': 'target-pdf'})]
    assert 'Evidence engines: document_analysis, tabular_tools' in result['reply']
    assert 'Conclusion level: aggregate or narrative' in result['reply']


def test_cross_format_coordinator_uses_native_partitions_and_rollout_guards():
    """CSV/XLSX and PDF/DOCX combinations must use native branches, not chunk fallback."""
    source = WORKFLOW.read_text(encoding='utf-8')
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_execute_cross_format_comparison_workflow'
    )
    helper_source = ast.get_source_segment(source, helper) or ''

    assert '_resolve_cross_format_comparison_manifest(' in helper_source
    assert "partitions['narrative_sources']" in helper_source
    assert "partitions['tabular_sources']" in helper_source
    assert 'run_document_analysis(' in helper_source
    assert '_maybe_execute_tabular_document_action(' in helper_source
    assert 'DOCUMENT_ACTION_TYPE_ANALYZE' in helper_source
    assert 'build_evidence_envelope(' in helper_source
    assert 'source_version' in helper_source
    assert 'run_evidence_document_comparison(' in helper_source
    assert "'computed tabular facts'" in helper_source
    assert "'narrative document analysis'" in helper_source
    assert 'is_cross_format_compare_one_to_many_enabled(settings)' in helper_source
    assert 'Mixed narrative and tabular Compare is temporarily unavailable while cross-format Compare is disabled.' in source


def test_phase_4_flags_default_off_and_all_runner_paths_use_them():
    """Model and agent Compare retain flag-off rollback and staged one-to-many rollout."""
    settings_source = SETTINGS.read_text(encoding='utf-8')
    workflow_source = WORKFLOW.read_text(encoding='utf-8')

    assert "'enable_cross_format_compare': False" in settings_source
    assert "'enable_cross_format_compare_one_to_many': False" in settings_source
    assert 'def is_cross_format_compare_enabled(settings):' in settings_source
    assert 'def is_cross_format_compare_one_to_many_enabled(settings):' in settings_source
    assert workflow_source.count('mixed_comparison_enabled = is_cross_format_compare_enabled(settings)') == 2
    assert workflow_source.count('_execute_cross_format_comparison_workflow(') >= 3


if __name__ == '__main__':
    test_pairwise_reducer_preserves_target_order_and_partial_failure()
    test_cross_format_coordinator_uses_native_partitions_and_rollout_guards()
    test_phase_4_flags_default_off_and_all_runner_paths_use_them()
    print('Phase 4 cross-format Compare tests passed.')