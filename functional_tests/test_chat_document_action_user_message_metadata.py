# test_chat_document_action_user_message_metadata.py
"""
Functional test for document-action user message metadata enrichment.
Version: 0.241.095
Implemented in: 0.241.095

This test ensures analysis and document comparison user messages
persist the same metadata categories that standard search messages expose
in the metadata drawer.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_workspace_file(*relative_parts: str) -> str:
    return REPO_ROOT.joinpath(*relative_parts).read_text(encoding='utf-8')


def test_document_action_user_metadata_is_enriched() -> None:
    route_content = _read_workspace_file('application', 'single_app', 'route_backend_chats.py')
    config_content = _read_workspace_file('application', 'single_app', 'config.py')

    assert 'VERSION = "0.241.095"' in config_content, (
        'Expected config.py version 0.241.095 for the document-action user metadata logging fix.'
    )
    assert 'def _build_document_action_user_metadata(' in route_content, (
        'Expected a dedicated helper for document-action user message metadata.'
    )
    assert "'button_states': {" in route_content, (
        'Expected document-action user messages to log button state metadata like standard search messages.'
    )
    assert "'workspace_search': workspace_search," in route_content, (
        'Expected document-action user messages to log workspace and document selection metadata.'
    )
    assert "'chat_context': {" in route_content, (
        'Expected document-action user messages to log chat context metadata.'
    )
    assert "'selected_document_names': resolved_document_names," in route_content, (
        'Expected document-action user messages to record resolved selected document names.'
    )
    assert "selected_document_summary = f'Left: {left_document_name} | Right: {right_document_summary}'" in route_content, (
        'Expected comparison user messages to summarize left and right document selections.'
    )
    assert "'streaming': bool(streaming_enabled)," in route_content, (
        'Expected document-action user messages to log whether the request was streamed.'
    )
    assert 'user_metadata = _build_document_action_user_metadata(' in route_content, (
        'Expected document-action requests to use the shared metadata builder when saving the user message.'
    )
