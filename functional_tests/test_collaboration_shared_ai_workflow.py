#!/usr/bin/env python3
# test_collaboration_shared_ai_workflow.py
"""
Functional test for collaboration shared AI workflow parity.
Version: 0.241.019
Implemented in: 0.241.019

This test ensures collaborative conversations route shared AI requests through
the collaboration stream bridge, persist explicit AI-request metadata, and
reuse the single-user payload builder and streaming client wiring.
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

    assert 'export function buildChatRequestPayload(' in messages_source
    assert 'export function buildCollaborativeInvocationTarget(' in messages_source
    assert 'export function shouldUseCollaborativeAiWorkflow(' in messages_source
    assert 'renderInvocationTargetHtml(' in messages_source

    assert 'metadata.ai_invocation_target = { ...invocationTarget };' in collaboration_source
    assert 'async function sendCollaborativeAiMessage(' in collaboration_source
    assert '/api/collaboration/conversations/${encodeURIComponent(conversationId)}/stream' in collaboration_source
    assert "if (message.role === 'image')" in collaboration_source

    assert "const { endpoint = '/api/chat/stream' } = options;" in streaming_source


if __name__ == '__main__':
    test_backend_collaboration_stream_bridge()
    test_frontend_collaboration_stream_wiring()
    print('All collaboration shared AI workflow checks passed.')