#!/usr/bin/env python3
# test_collaboration_shared_ai_workflow.py
"""
Functional test for collaboration shared AI workflow parity.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures collaborative conversations route shared AI requests through
the collaboration stream bridge, persist explicit AI-request metadata, and
reuse the single-user payload builder and streaming client wiring, including
explicit @agent and @model targeting without a selected tool, while keeping
shared user-message metadata and shared conversation metadata aligned with the
actual resolved agent and model.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_repo_file(*parts):
    file_path = os.path.join(ROOT_DIR, *parts)
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_backend_collaboration_stream_bridge():
    route_source = read_repo_file('application', 'single_app', 'route_backend_collaboration.py')
    functions_source = read_repo_file('application', 'single_app', 'functions_collaboration.py')

    assert "@app.route('/api/collaboration/conversations/<conversation_id>/stream', methods=['POST'])" in route_source
    assert 'ensure_collaboration_source_conversation(' in route_source
    assert "current_app.view_functions.get('chat_stream_api')" in route_source
    assert 'mirror_source_message_to_collaboration(' in route_source
    assert 'message_kind=MESSAGE_KIND_AI_REQUEST' in route_source

    assert 'def ensure_collaboration_source_conversation(' in functions_source
    assert 'def mirror_source_message_to_collaboration(' in functions_source
    assert 'def get_collaboration_message_by_source_message(' in functions_source


def test_frontend_collaboration_stream_wiring():
    messages_source = read_repo_file('application', 'single_app', 'static', 'js', 'chat', 'chat-messages.js')
    collaboration_source = read_repo_file('application', 'single_app', 'static', 'js', 'chat', 'chat-collaboration.js')
    streaming_source = read_repo_file('application', 'single_app', 'static', 'js', 'chat', 'chat-streaming.js')
    styles_source = read_repo_file('application', 'single_app', 'static', 'css', 'chats.css')

    assert 'export function buildChatRequestPayload(' in messages_source
    assert 'export function getCollaborativeTagSuggestions(' in messages_source
    assert 'export function buildCollaborativeInvocationTarget(' in messages_source
    assert 'export function shouldUseCollaborativeAiWorkflow(' in messages_source
    assert 'function buildCollaborativeSendContext(' in messages_source
    assert "source_mode: 'explicit_tag'" in messages_source
    assert 'stripExplicitCollaborativeTargetText(' in messages_source
    assert 'renderInvocationTargetHtml(' in messages_source

    assert 'metadata.ai_invocation_target = { ...invocationTarget };' in collaboration_source
    assert 'async function sendCollaborativeAiMessage(' in collaboration_source
    assert '/api/collaboration/conversations/${encodeURIComponent(conversationId)}/stream' in collaboration_source
    assert "if (message.role === 'image')" in collaboration_source
    assert 'getCollaborativeTagSuggestions(query)' in collaboration_source
    assert "action === 'ai_tag'" in collaboration_source
    assert 'insertInvocationTargetMention(' in collaboration_source

    assert "const { endpoint = '/api/chat/stream' } = options;" in streaming_source
    assert '.collaboration-mention-chip-target-agent' in styles_source
    assert '.collaboration-mention-chip-target-model' in styles_source


def test_streaming_metadata_alignment_for_explicit_agent_targets():
    collaboration_route_source = read_repo_file('application', 'single_app', 'route_backend_collaboration.py')
    chat_route_source = read_repo_file('application', 'single_app', 'route_backend_chats.py')
    collaboration_functions_source = read_repo_file('application', 'single_app', 'functions_collaboration.py')

    assert 'sync_collaboration_conversation_metadata_from_source(' in collaboration_functions_source
    assert 'source_conversation_doc = cosmos_conversations_container.read_item(' in collaboration_route_source
    assert 'updated_conversation_doc, _ = sync_collaboration_conversation_metadata_from_source(' in collaboration_route_source

    assert 'if request_agent_info and isinstance(request_agent_info, dict):' in chat_route_source
    assert "user_metadata['agent_selection'] = {" in chat_route_source
    assert "user_message_doc['metadata']['model_selection']['selected_model'] = final_model_used if use_agent_streaming else gpt_model" in chat_route_source
    assert "model_deployment=final_model_used if use_agent_streaming else gpt_model" in chat_route_source


if __name__ == '__main__':
    test_backend_collaboration_stream_bridge()
    test_frontend_collaboration_stream_wiring()
    test_streaming_metadata_alignment_for_explicit_agent_targets()
    print('All collaboration shared AI workflow checks passed.')