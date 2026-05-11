#!/usr/bin/env python3
# test_agent_citation_full_results_modal.py
"""
Functional test for full agent citation result hydration.
Version: 0.240.048
Implemented in: 0.240.048

This test ensures the chat UI can lazy-load raw agent citation artifacts and
render tabular tool results with preview, 25-row, and full-row controls.
"""

import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_frontend_conversations.py')
MESSAGES_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-messages.js')
CITATIONS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'js', 'chat', 'chat-citations.js')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')


def read_file_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as file_handle:
        for line in file_handle:
            if line.startswith('VERSION = '):
                return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_route_exposes_agent_citation_artifact_endpoint():
    print('🔍 Testing agent citation artifact endpoint wiring...')

    route_source = read_file_text(ROUTE_FILE)
    required_snippets = [
        "@app.route('/api/conversation/<conversation_id>/agent-citation/<artifact_id>', methods=['GET'])",
        'build_message_artifact_payload_map',
        "artifact_payload_map.get(str(artifact_id or ''))",
        "return jsonify({'citation': citation})",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_source]
    assert not missing, f'Missing route snippets: {missing}'

    print('✅ Agent citation artifact endpoint wiring passed')
    return True


def test_chat_ui_uses_lazy_hydration_and_row_controls():
    print('🔍 Testing agent citation modal source and row controls...')

    messages_source = read_file_text(MESSAGES_FILE)
    citations_source = read_file_text(CITATIONS_FILE)

    required_message_snippets = [
        'data-artifact-id',
        'data-conversation-id',
    ]
    required_citation_snippets = [
        'AGENT_CITATION_EXPANDED_ROWS = 25',
        'fetchAgentCitationArtifact',
        'renderAgentCitationResult(',
        'Show 25 rows',
        'Show all rows',
        'displayed_rows',
        'data_rows_limited',
        '/api/conversation/${encodeURIComponent(conversationId)}/agent-citation/${encodeURIComponent(artifactId)}',
    ]

    missing_messages = [snippet for snippet in required_message_snippets if snippet not in messages_source]
    missing_citations = [snippet for snippet in required_citation_snippets if snippet not in citations_source]
    assert not missing_messages, f'Missing message snippets: {missing_messages}'
    assert not missing_citations, f'Missing citation snippets: {missing_citations}'

    print('✅ Agent citation modal source and row controls passed')
    return True


def test_version_bump_alignment():
    print('🔍 Testing version bump alignment...')

    assert read_config_version() == '0.240.048'

    print('✅ Version bump alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_route_exposes_agent_citation_artifact_endpoint,
        test_chat_ui_uses_lazy_hydration_and_row_controls,
        test_version_bump_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)