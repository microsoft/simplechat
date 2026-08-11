#!/usr/bin/env python3
# test_mixed_source_deferred_composition_phase5.py
"""
Functional test for Phase 5 mixed-source deferred composition.
Version: 0.250.161
Implemented in: 0.250.161

This test ensures pending durable tabular work remains nonterminal evidence,
blocks mixed-source Analyze reduction, and is guarded by a backend-only rollout
setting instead of being treated as completed source coverage.
"""

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP = ROOT / 'application' / 'single_app'
WORKFLOW_RUNNER = SINGLE_APP / 'functions_workflow_runner.py'
SETTINGS = SINGLE_APP / 'functions_settings.py'
sys.path.insert(0, str(SINGLE_APP))

from functions_mixed_source_orchestration import (  # noqa: E402
    AUTHORIZATION_STATUS_AUTHORIZED,
    EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
    EVIDENCE_ENGINE_TABULAR_TOOLS,
    EVIDENCE_STATUS_COMPLETED,
    EVIDENCE_STATUS_PENDING,
    SOURCE_KIND_NARRATIVE,
    SOURCE_KIND_TABULAR,
    build_evidence_envelope,
    build_mixed_source_evidence_handoff,
    evaluate_mixed_source_mode_outcome,
)


def test_pending_tabular_evidence_blocks_mixed_analyze_reduction():
    """Pending generated-output metadata must not count as completed evidence."""
    manifest = [
        {
            'document_id': 'narrative-1',
            'display_name': 'Policy.pdf',
            'source_kind': SOURCE_KIND_NARRATIVE,
            'authorization_status': AUTHORIZATION_STATUS_AUTHORIZED,
        },
        {
            'document_id': 'table-1',
            'display_name': 'Rows.csv',
            'source_kind': SOURCE_KIND_TABULAR,
            'authorization_status': AUTHORIZATION_STATUS_AUTHORIZED,
        },
    ]
    envelopes = [
        build_evidence_envelope(
            document_id='narrative-1',
            source_kind=SOURCE_KIND_NARRATIVE,
            engine=EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
            status=EVIDENCE_STATUS_COMPLETED,
            summary='Narrative analysis completed.',
            coverage={'terminal': True, 'processed_windows': 1, 'total_windows': 1},
        ),
        build_evidence_envelope(
            document_id='table-1',
            source_kind=SOURCE_KIND_TABULAR,
            engine=EVIDENCE_ENGINE_TABULAR_TOOLS,
            status=EVIDENCE_STATUS_PENDING,
            summary='Full-source tabular analysis is pending.',
            generated_artifacts=[{
                'run_id': 'run-1',
                'status': 'queued',
                'task_type': 'hierarchical_analysis',
                'background_export': True,
                'capability': 'tabular',
            }],
            coverage={
                'terminal': False,
                'execution_status': 'queued',
                'deferred_composition': {'required': True, 'enabled': True},
            },
        ),
    ]

    handoff = build_mixed_source_evidence_handoff(
        manifest,
        envelopes,
        'selected',
        mode='analyze',
        telemetry_settings={},
    )
    coverage = handoff['mixed_source_coverage']
    assert coverage['completed_source_count'] == 1
    assert coverage['pending_source_count'] == 1
    assert coverage['partial_coverage'] is True
    pending_entry = next(
        entry for entry in coverage['terminal_ledger']
        if entry['document_id'] == 'table-1'
    )
    assert pending_entry['status'] == EVIDENCE_STATUS_PENDING
    assert pending_entry['reason'] == 'pending_durable_evidence'

    outcome = evaluate_mixed_source_mode_outcome(
        'analyze',
        {
            'entries': coverage['terminal_ledger'],
            'partial_coverage': coverage['partial_coverage'],
        },
    )
    assert outcome['status'] == EVIDENCE_STATUS_PENDING
    assert outcome['should_reduce'] is False
    assert outcome['pending_source_count'] == 1
    assert outcome['reason'] == 'pending_required_evidence'


def test_workflow_runner_defers_pending_tabular_outputs_before_reduction():
    """Mixed Analyze must branch on pending tabular output before model reduction."""
    source = WORKFLOW_RUNNER.read_text(encoding='utf-8')
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_execute_mixed_source_analyze_workflow'
    )
    helper_source = ast.get_source_segment(source, helper) or ''

    pending_branch = "if pending_generated_output:"
    reduction_call = "stage='mixed_source_reduction'"
    assert pending_branch in helper_source
    assert "_build_pending_tabular_evidence_envelope(" in helper_source
    assert "pending_tabular_runs.append(" in helper_source
    assert "if mode_outcome.get('status') == EVIDENCE_STATUS_PENDING:" in helper_source
    assert "'deferred_composition': deferred_descriptor" in helper_source
    assert helper_source.index(pending_branch) < helper_source.index(reduction_call)
    assert "continue" in helper_source[
        helper_source.index(pending_branch):helper_source.index(reduction_call)
    ]

    artifact_helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_maybe_create_document_analysis_generated_artifacts'
    )
    artifact_source = ast.get_source_segment(source, artifact_helper) or ''
    assert "deferred_composition.get('status') in {'pending', 'gate_disabled'}" in artifact_source
    assert "return {'artifacts': [], 'assistant_reply': None}" in artifact_source
    assert "'deferred_composition': result.get('deferred_composition') or {}" in source
    assert source.count("'deferred_composition': analysis_result.get('deferred_composition') or {}") >= 2


def test_deferred_composition_setting_defaults_backend_only():
    """The Phase 5 gate must default off and remain sanitized from frontend settings."""
    settings_source = SETTINGS.read_text(encoding='utf-8')
    assert "'enable_tabular_mixed_deferred_composition': False" in settings_source
    assert "'enable_tabular_mixed_deferred_composition'," in settings_source
    backend_key_index = settings_source.index("'enable_tabular_mixed_deferred_composition',")
    sanitizer_index = settings_source.index('def sanitize_settings_for_user')
    assert backend_key_index < sanitizer_index


if __name__ == '__main__':
    tests = [
        test_pending_tabular_evidence_blocks_mixed_analyze_reduction,
        test_workflow_runner_defers_pending_tabular_outputs_before_reduction,
        test_deferred_composition_setting_defaults_backend_only,
    ]
    failures = []
    for test in tests:
        try:
            test()
            print(f'PASS {test.__name__}')
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f'FAIL {test.__name__}: {exc}')

    if failures:
        sys.exit(1)
    sys.exit(0)
