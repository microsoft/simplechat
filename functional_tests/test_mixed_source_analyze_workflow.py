#!/usr/bin/env python3
# test_mixed_source_analyze_workflow.py
"""
Functional test for Phase 3 mixed-source combined Analyze.
Version: 0.250.107
Implemented in: 0.250.072; updated in 0.250.107

This test ensures #1058 composes native narrative and tabular analysis behind
automatic combined Analyze routing, retains terminal coverage after either
branch fails, and keeps per-document execution non-collective. Parent: #1055.
Prerequisites: #1056 and #1057.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_RUNNER = ROOT / 'application' / 'single_app' / 'functions_workflow_runner.py'
SETTINGS = ROOT / 'application' / 'single_app' / 'functions_settings.py'


def test_phase_3_mixed_analyze_contracts_are_wired():
    """Combined Analyze must resolve once, partition, run native engines, then reduce once."""
    source = WORKFLOW_RUNNER.read_text(encoding='utf-8')
    tree = ast.parse(source)
    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_execute_mixed_source_analyze_workflow'
    )
    helper_source = ast.get_source_segment(source, helper) or ''

    assert 'resolve_authorized_source_manifest(' in helper_source
    assert 'partition_source_manifest(manifest)' in helper_source
    assert "partitions['narrative_sources']" in helper_source
    assert "partitions['tabular_sources']" in helper_source
    assert 'run_document_analysis(' in helper_source
    assert "document_ids=[source.get('document_id') for source in narrative_sources]" in helper_source
    assert 'narrative_items_by_id' in helper_source
    assert "summary=str(narrative_item.get('text') or '')" in helper_source
    assert '_maybe_execute_tabular_document_action(' in helper_source
    assert 'build_evidence_envelope(' in helper_source
    assert 'build_mixed_source_evidence_handoff(' in helper_source
    assert "stage='mixed_source_reduction'" in helper_source
    assert "requested_selection_mode == 'all'" in helper_source
    assert 'Analyze All Documents is temporarily unavailable' in helper_source
    assert 'len(requested_ids) > int(max_documents)' in helper_source
    assert "'resolving_sources'" in helper_source
    assert "'analyzing_narrative'" in helper_source
    assert "'analyzing_tabular'" in helper_source
    assert "'combining_findings'" in helper_source
    assert "'phase': 'complete'" in helper_source
    assert 'Tabular evidence could not be completed for this source.' in helper_source
    assert 'Narrative evidence could not be completed for this source.' in helper_source
    assert "'generated_tabular_outputs': generated_tabular_outputs" in helper_source
    assert "'agent_citations': tabular_agent_citations" in helper_source


def test_phase_3_mixed_analyze_is_automatic_and_preserves_per_document_mode():
    """Combined Analyze must use native mixed-source execution without a feature gate."""
    settings_source = SETTINGS.read_text(encoding='utf-8')
    workflow_source = WORKFLOW_RUNNER.read_text(encoding='utf-8')
    tree = ast.parse(workflow_source)
    runner = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_execute_document_analysis_workflow'
    )
    runner_source = ast.get_source_segment(workflow_source, runner) or ''

    assert "'enable_mixed_source_analyze':" not in settings_source
    assert "settings.get('enable_mixed_source_analyze'" not in workflow_source
    assert 'def _raise_legacy_mixed_source_analyze_limitation(' not in workflow_source
    assert runner_source.count('analysis_result = _execute_mixed_source_analyze_workflow(') == 2
    assert '_is_per_document_analysis_mode(analysis_config)' in runner_source
    assert 'return _combine_per_document_analysis_results(per_document_results)' in runner_source
    assert "analysis_result.get('generated_tabular_outputs')" in runner_source
    assert "analysis_result.get('agent_citations')" in runner_source


def test_phase_3_reduction_prompt_requires_evidence_separation_and_failures():
    """The one collective prompt must distinguish native evidence and partial coverage."""
    source = WORKFLOW_RUNNER.read_text(encoding='utf-8')
    assert 'computed tabular facts as tool-backed calculations' in source
    assert 'narrative facts as document excerpts' in source
    assert 'Explicitly state missing, failed, unsupported, unresolved, or unprocessed evidence' in source
    assert 'never claim coverage for it' in source
