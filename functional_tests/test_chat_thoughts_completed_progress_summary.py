# test_chat_thoughts_completed_progress_summary.py
"""
Functional test for completed thought progress summaries.
Version: 0.241.023
Implemented in: 0.241.098

This test ensures completed document-action thought histories do not keep
showing a live progress bar and that reduction activities close cleanly.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_completed_thought_progress_summaries_are_not_live() -> None:
    config_content = _read('application/single_app/config.py')
    thoughts_content = _read('application/single_app/static/js/chat/chat-thoughts.js')
    workflow_runner_content = _read('application/single_app/functions_workflow_runner.py')
    analysis_content = _read('application/single_app/functions_document_analysis.py')
    comparison_content = _read('application/single_app/functions_document_comparison.py')
    route_content = _read('application/single_app/route_backend_chats.py')

    assert 'VERSION = "0.241.023"' in config_content, (
        'Expected config.py version 0.241.023 for the completed thought progress summary fix.'
    )
    assert ': (state.completed || (counters.totalCount > 0 && counters.runningCount === 0));' in thoughts_content, (
        'Expected completed thought histories to derive completion when no activity remains running.'
    )
    assert 'if (!isLive && isCompleted) {' in thoughts_content, (
        'Expected historical thought summaries to switch away from the live progress-bar card after completion.'
    )
    assert 'Agent activity complete' in thoughts_content, (
        'Expected completed thought summaries to render a non-progress completion card.'
    )
    assert "'type': 'reduction_completed'" in analysis_content, (
        'Expected analysis progress updates to emit a terminal reduction completion event.'
    )
    assert "'type': 'comparison_reduction_completed'" in comparison_content, (
        'Expected document comparison progress updates to emit a terminal reduction completion event.'
    )
    assert "activity_key=f'analysis:{run_id}:{document_id}'," in workflow_runner_content, (
        'Expected document analysis start and completion thoughts to reuse the same activity key.'
    )
    assert 'activity_key=f\"compare:{run_id}:{document_id}:{event.get(\'right_document_id\')}\",' in workflow_runner_content, (
        'Expected comparison start and completion thoughts to reuse the same activity key.'
    )
    assert "if event_type == 'reduction_completed':" in route_content, (
        'Expected streamed document-action thoughts to label terminal analysis completion events.'
    )
    assert "if event_type == 'comparison_reduction_completed':" in route_content, (
        'Expected streamed document-action thoughts to label terminal comparison completion events.'
    )