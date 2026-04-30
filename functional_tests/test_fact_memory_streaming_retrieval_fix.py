# test_fact_memory_streaming_retrieval_fix.py
"""
Functional test for fact memory streaming retrieval and visibility.
Version: 0.240.081
Implemented in: 0.240.081

This test ensures streaming chat uses backward-compatible agent defaults,
retrieves only relevant fact memories for the current request, and exposes
fact-memory usage through thoughts and a dedicated citation.
"""

import ast
import copy
import os
import re
from datetime import datetime


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'FACT_MEMORY_STREAMING_RETRIEVAL_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_fact_memory_retrieval_helpers():
    route_source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(route_source, filename=ROUTE_FILE)
    target_functions = {
        '_tokenize_fact_memory_text',
        '_is_identity_fact_memory_query',
        '_looks_like_profile_fact',
        'retrieve_relevant_fact_memory_entries',
        'build_fact_memory_citation',
        'build_fact_memory_recall_payload',
    }
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in target_functions:
            selected_nodes.append(copy.deepcopy(node))

    assert len(selected_nodes) == len(target_functions), (
        f'Expected helpers {sorted(target_functions)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    class FakeFactMemoryStore:
        next_facts = []
        created_instances = []

        def __init__(self):
            self.calls = []
            self.__class__.created_instances.append(self)

        def list_facts(self, **kwargs):
            self.calls.append(kwargs)
            return list(self.__class__.next_facts)

    namespace = {
        'FactMemoryStore': FakeFactMemoryStore,
        'datetime': datetime,
        'make_json_serializable': lambda value: value,
        're': re,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, FakeFactMemoryStore


def test_fact_memory_retrieval_uses_request_relevance():
    """Verify fact memory retrieval selects relevant profile facts instead of all saved memories."""
    print('🔍 Testing fact memory retrieval relevance...')

    namespace, fake_store_class = load_fact_memory_retrieval_helpers()
    fake_store_class.created_instances = []
    fake_store_class.next_facts = [
        {'id': '1', 'value': "User's name is Paul.", 'updated_at': '2026-04-07T00:00:00Z'},
        {'id': '2', 'value': 'User lives in Alexandria.', 'updated_at': '2026-04-06T00:00:00Z'},
        {'id': '3', 'value': 'Server timeout is 30 seconds.', 'updated_at': '2026-04-05T00:00:00Z'},
    ]

    recall_payload = namespace['build_fact_memory_recall_payload'](
        scope_id='user-123',
        scope_type='user',
        query_text='who am i?',
        conversation_id='conversation-456',
        enabled=True,
        include_metadata=True,
    )

    assert recall_payload['thought_content'] == 'Fact memory search found 2 relevant memories'
    assert len(recall_payload['context_messages']) == 2, recall_payload
    assert "User's name is Paul." in recall_payload['context_messages'][1]['content']
    assert 'User lives in Alexandria.' in recall_payload['context_messages'][1]['content']
    assert 'Server timeout is 30 seconds.' not in recall_payload['context_messages'][1]['content']
    assert recall_payload['citation']['tool_name'] == 'Fact Memory Recall'
    assert fake_store_class.created_instances[-1].calls == [{
        'scope_type': 'user',
        'scope_id': 'user-123',
        'conversation_id': 'conversation-456',
    }]

    print('✅ Fact memory retrieval relevance passed')
    return True


def test_streaming_route_wires_fact_memory_visibility_and_agent_default():
    """Verify streaming route keeps agents backward-compatible and exposes fact-memory retrieval."""
    print('🔍 Testing streaming route fact-memory wiring...')

    route_source = read_file_text(ROUTE_FILE)

    assert "user_settings.get('enable_agents', True)" in route_source
    assert 'force_enable_agents = bool(request_agent_info)' in route_source
    assert 'Fact Memory Recall' in route_source
    assert "yield emit_thought(" in route_source and "'fact_memory'" in route_source
    assert 'Retrieved saved fact memories relevant to the current request.' in route_source

    print('✅ Streaming route fact-memory wiring passed')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert read_config_version() == '0.240.081'
    assert 'Fixed/Implemented in version: **0.240.081**' in fix_doc_content
    assert '/api/chat/stream' in fix_doc_content
    assert 'Fact Memory Recall' in fix_doc_content
    assert 'who am i' in fix_doc_content.lower()
    assert 'thoughts and citations' in fix_doc_content.lower()

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_fact_memory_retrieval_uses_request_relevance,
        test_streaming_route_wires_fact_memory_visibility_and_agent_default,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)