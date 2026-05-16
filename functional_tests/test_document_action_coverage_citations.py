"""
Functional test for document-action coverage citations and thought events.
Version: 0.241.023
Implemented in: 0.241.021

This test ensures Analyze and comparison actions expose stable coverage
citations and progress activity keys.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_document_action_coverage_is_citation_driven() -> None:
    workflow_runner_content = _read('application/single_app/functions_workflow_runner.py')
    route_content = _read('application/single_app/route_backend_chats.py')

    assert 'def _resolve_document_action_reply(result):' in workflow_runner_content, (
        'Expected a helper that prefers analysis-only replies for document-action chat and workflow messages.'
    )
    assert workflow_runner_content.count('_resolve_document_action_reply(') >= 4, (
        'Expected analysis and document comparison results to use analysis-only replies in both agent and model paths.'
    )
    assert "elif event_type == 'window_started':" in workflow_runner_content, (
        'Expected document-action thoughts to track analysis window starts.'
    )
    assert "elif event_type == 'window_retry':" in workflow_runner_content, (
        'Expected document-action thoughts to track analysis window retries.'
    )
    assert "elif event_type == 'window_completed':" in workflow_runner_content, (
        'Expected document-action thoughts to track analysis window completion.'
    )
    assert "'file_name': 'Coverage'," in route_content, (
        'Expected document-action hybrid citations to add an overall coverage citation.'
    )
    assert "'metadata_type': 'document_comparison_coverage' if is_comparison else 'document_analysis_coverage'," in route_content, (
        'Expected the coverage citation to distinguish analysis and comparison metadata.'
    )
    assert "'location_value': 'Overall summary'," in route_content, (
        'Expected the overall coverage citation to expose a stable summary location label.'
    )
    assert "'metadata_type': 'document_comparison_summary' if role_label else 'document_analysis_summary'," in route_content, (
        'Expected per-document document-action citations to remain available alongside the overall coverage citation.'
    )