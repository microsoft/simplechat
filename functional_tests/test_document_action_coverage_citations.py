"""
Regression coverage for document-action coverage citations and thought events.
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
    assert workflow_runner_content.count("'reply': _resolve_document_action_reply(") >= 4, (
        'Expected exhaustive review and document comparison results to use analysis-only replies in both agent and model paths.'
    )
    assert "elif event_type == 'window_started':" in workflow_runner_content, (
        'Expected document-action thoughts to track review window starts.'
    )
    assert "elif event_type == 'window_retry':" in workflow_runner_content, (
        'Expected document-action thoughts to track review window retries.'
    )
    assert "elif event_type == 'window_completed':" in workflow_runner_content, (
        'Expected document-action thoughts to track review window completion.'
    )
    assert "'file_name': 'Coverage'," in route_content, (
        'Expected document-action hybrid citations to add an overall coverage citation.'
    )
    assert "'metadata_type': 'document_comparison_coverage' if is_comparison else 'document_review_coverage'," in route_content, (
        'Expected the coverage citation to distinguish review and comparison metadata.'
    )
    assert "'location_value': 'Overall summary'," in route_content, (
        'Expected the overall coverage citation to expose a stable summary location label.'
    )
    assert "'metadata_type': 'document_comparison_summary' if role_label else 'document_review_summary'," in route_content, (
        'Expected per-document document-action citations to remain available alongside the overall coverage citation.'
    )