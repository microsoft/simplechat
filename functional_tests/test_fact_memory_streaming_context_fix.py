# test_fact_memory_streaming_context_fix.py
"""
Functional test for fact memory chat-context parity.
Version: 0.261.104
Implemented in: 0.240.050; 0.240.051

This test ensures both standard and streaming agent chat paths inject saved fact
memory into model context, and that fact lookup preserves the selected agent id
instead of silently falling back to the default configured agent.
"""

import ast
import copy
import os
from test_support.versioning import assert_app_version_at_least
from test_fact_memory_profile_and_mini_sk import CONTEXT_FILE, load_tabular_fact_memory_helpers


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.001',
    'FACT_MEMORY_STREAMING_CONTEXT_FIX.md',
)
TARGET_FUNCTIONS = {
    'get_facts_for_context',
    'inject_fact_memory_context',
}


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_fact_memory_helpers():
    route_source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(route_source, filename=ROUTE_FILE)
    selected_nodes = []

    class NestedFunctionCollector(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node.name in TARGET_FUNCTIONS:
                selected_nodes.append(copy.deepcopy(node))
            self.generic_visit(node)

    NestedFunctionCollector().visit(parsed)
    assert len(selected_nodes) == len(TARGET_FUNCTIONS), (
        f'Expected to find helpers {sorted(TARGET_FUNCTIONS)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace, FakeFactMemoryStore, _ = load_tabular_fact_memory_helpers()
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, route_source, FakeFactMemoryStore


def test_get_facts_for_context_preserves_selected_agent_id():
    """Verify fact lookup uses the caller-provided selected agent id."""
    print('🔍 Testing fact lookup preserves selected agent id...')

    namespace, _, fake_store_class = load_fact_memory_helpers()
    fake_store_class.created_instances = []
    fake_store_class.next_facts = [
        {'value': 'The user prefers hyphens instead of em dashes.', 'memory_type': 'fact', 'value_embedding': [1.0, 0.0]},
    ]

    facts = namespace['get_facts_for_context'](
        scope_id='user-123',
        scope_type='user',
        conversation_id='conversation-456',
        agent_id='agent-789',
        query_text='who am i?',
    )

    assert '- The user prefers hyphens instead of em dashes.' in facts, facts
    assert fake_store_class.created_instances, 'Expected FactMemoryStore to be instantiated.'
    assert fake_store_class.created_instances[-1].calls == [{
        'scope_type': 'user',
        'scope_id': 'user-123',
        'agent_id': 'agent-789',
        'conversation_id': 'conversation-456',
        'memory_type': 'fact',
    }], fake_store_class.created_instances[-1].calls

    print('✅ Fact lookup preserves selected agent id')
    return True


def test_inject_fact_memory_context_adds_metadata_and_facts():
    """Verify injected system messages prepend metadata and saved facts."""
    print('🔍 Testing fact memory context injection...')

    namespace, _, fake_store_class = load_fact_memory_helpers()
    fake_store_class.created_instances = []
    fake_store_class.next_facts = [
        {'value': 'The user prefers hyphens instead of em dashes.', 'memory_type': 'fact', 'value_embedding': [1.0, 0.0]},
    ]

    conversation_history = [
        {'role': 'user', 'content': 'Please draft the response.'},
    ]
    namespace['inject_fact_memory_context'](
        conversation_history=conversation_history,
        scope_id='user-123',
        scope_type='user',
        conversation_id='conversation-456',
        agent_id='agent-789',
        query_text='who am i?',
        include_metadata=True,
    )

    assert conversation_history[0]['role'] == 'system', conversation_history
    assert '<Conversation Metadata>' in conversation_history[0]['content'], conversation_history[0]
    assert '<Agent ID: agent-789>' in conversation_history[0]['content'], conversation_history[0]
    assert conversation_history[1]['role'] == 'system', conversation_history
    assert '<Fact Memory>' in conversation_history[1]['content'], conversation_history[1]
    assert 'The user prefers hyphens instead of em dashes.' in conversation_history[1]['content'], conversation_history[1]
    assert conversation_history[-1]['role'] == 'user', conversation_history

    print('✅ Fact memory context injection passed')
    return True


def test_route_wires_fact_memory_injection_for_standard_and_streaming_paths():
    """Verify both chat execution paths call the shared fact-memory injector."""
    print('🔍 Testing route wiring for standard and streaming fact injection...')

    _, route_source, _ = load_fact_memory_helpers()

    assert route_source.count('inject_fact_memory_context(') == 3, (
        'Expected one helper definition and two call sites for fact-memory injection.'
    )
    assert "agent_id=getattr(selected_agent, 'id', None)" in route_source, (
        'Expected streaming injection to use the selected agent id.'
    )
    context_source = read_file_text(CONTEXT_FILE)
    assert '<Fact Memory>' in context_source, 'Expected fact memory system message markup.'
    assert '<Conversation Metadata>' in context_source, 'Expected conversation metadata system message markup.'

    print('✅ Route wiring for standard and streaming fact injection passed')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert_app_version_at_least("0.240.051")
    assert 'Fixed/Implemented in version: **0.240.051**' in fix_doc_content
    assert 'streaming chat path' in fix_doc_content.lower()
    assert 'selected agent id' in fix_doc_content.lower()
    assert 'application/single_app/route_backend_chats.py' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_get_facts_for_context_preserves_selected_agent_id,
        test_inject_fact_memory_context_adds_metadata_and_facts,
        test_route_wires_fact_memory_injection_for_standard_and_streaming_paths,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)