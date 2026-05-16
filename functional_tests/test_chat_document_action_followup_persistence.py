# test_chat_document_action_followup_persistence.py
"""
Functional test for chat document action follow-up persistence.
Version: 0.241.023
Implemented in: 0.241.095

This test ensures new chat conversations started with analysis or
document comparison update the default title, persist thoughts, and attach
document citations for the assistant response.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_workspace_file(*relative_parts: str) -> str:
    return REPO_ROOT.joinpath(*relative_parts).read_text(encoding='utf-8')


def test_chat_document_action_followups_are_persisted() -> None:
    route_content = _read_workspace_file('application', 'single_app', 'route_backend_chats.py')
    config_content = _read_workspace_file('application', 'single_app', 'config.py')

    assert 'VERSION = "0.241.023"' in config_content, (
        'Expected config.py version 0.241.023 for the chat document action follow-up persistence fix.'
    )
    assert 'def _build_document_action_hybrid_citations(execution_result):' in route_content, (
        'Expected a helper that synthesizes document citations for chat document actions.'
    )
    assert (
        'assistant_message_id, thought_tracker, assistant_thread_attempt, response_message_context = _initialize_assistant_response_tracking('
        in route_content
    ), 'Expected document-action chat requests to keep the initialized ThoughtTracker.'
    assert 'run_id=assistant_message_id,' in route_content, (
        'Expected document-action workflow execution to use the assistant message id as its activity run id.'
    )
    assert 'thought_tracker=thought_tracker,' in route_content, (
        'Expected document-action workflow execution to persist thoughts through the ThoughtTracker.'
    )
    assert 'hybrid_citations_list = _build_document_action_hybrid_citations(execution_result)' in route_content, (
        'Expected document-action chat requests to build hybrid citations from the analysis coverage.'
    )
    assert route_content.count("'hybrid_citations': hybrid_citations_list,") >= 2, (
        'Expected assistant persistence and response payloads to both carry document-action hybrid citations.'
    )
    assert "'thoughts_enabled': thought_tracker.enabled," in route_content, (
        'Expected document-action chat responses to report the actual thought-tracker enabled state.'
    )
    assert "if conversation_item.get('title', 'New Conversation') == 'New Conversation' and user_message:" in route_content, (
        'Expected document-action chat requests to update default conversation titles from the first user message.'
    )
