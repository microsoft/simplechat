# test_fact_memory_profile_and_mini_sk.py
"""
Functional test for profile fact memory recall and mini-SK fact-memory support.
Version: 0.240.085
Implemented in: 0.240.077; 0.240.079; 0.240.081; 0.240.082; 0.240.083; 0.240.085

This test ensures fact memory supports instruction/fact memory types,
the mini-SK helper injects always-on instructions plus embedding-recalled
facts, and the profile route exposes typed CRUD endpoints.
"""

import ast
import copy
import re
import os
import types
import uuid
from datetime import datetime, timezone


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
STORE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'semantic_kernel_fact_memory_store.py')
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
PROFILE_ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_frontend_profile.py')
FEATURE_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'features',
    'FACT_MEMORY_PROFILE_AND_MINI_SK.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_store_class():
    store_source = read_file_text(STORE_FILE)
    parsed = ast.parse(store_source, filename=STORE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.ClassDef) and node.name == 'FactMemoryStore':
            selected_nodes.append(copy.deepcopy(node))
            break

    assert selected_nodes, 'Expected FactMemoryStore class in semantic_kernel_fact_memory_store.py'

    class FakeCosmosResourceNotFoundError(Exception):
        """Fake Cosmos DB not-found exception for isolated store tests."""

    namespace = {
        'uuid': uuid,
        'datetime': datetime,
        'timezone': timezone,
        'MEMORY_TYPE_FACT': 'fact',
        'MEMORY_TYPE_INSTRUCTION': 'instruction',
        'MEMORY_TYPE_LEGACY_DESCRIBER': 'describer',
        'VALID_MEMORY_TYPES': {'fact', 'instruction', 'describer'},
        'UNSET': object(),
        'generate_embedding': lambda value: ([float(len(str(value or ''))), 1.0], {'model_deployment_name': 'test-embedding-model'}),
        'exceptions': types.SimpleNamespace(CosmosResourceNotFoundError=FakeCosmosResourceNotFoundError),
        'cosmos_agent_facts_container': None,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, STORE_FILE, 'exec'), namespace)
    return namespace['FactMemoryStore'], FakeCosmosResourceNotFoundError


def load_tabular_fact_memory_helpers():
    route_source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(route_source, filename=ROUTE_FILE)
    selected_nodes = []
    selected_constant_names = {
        'FACT_MEMORY_TYPE_FACT',
        'FACT_MEMORY_TYPE_INSTRUCTION',
        'FACT_MEMORY_TYPE_LEGACY_DESCRIBER',
    }
    target_functions = {
        'normalize_fact_memory_type',
        '_normalize_fact_memory_item',
        '_is_embedding_vector',
        '_coerce_embedding_result',
        '_build_fact_memory_fact_payload',
        '_cosine_similarity',
        '_backfill_missing_fact_memory_embeddings',
        'build_instruction_memory_citation',
        'retrieve_relevant_fact_memory_entries',
        'build_fact_memory_citation',
        'build_instruction_memory_payload',
        'build_fact_memory_recall_payload',
        'build_fact_memory_prompt_payload',
        '_build_fact_memory_context_lines',
        'build_tabular_fact_memory_messages',
    }

    for node in parsed.body:
        if isinstance(node, ast.Assign):
            target_names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if target_names & selected_constant_names:
                selected_nodes.append(copy.deepcopy(node))
        if isinstance(node, ast.FunctionDef) and node.name in target_functions:
            selected_nodes.append(copy.deepcopy(node))

    found_function_names = {node.name for node in selected_nodes if isinstance(node, ast.FunctionDef)}
    assert found_function_names == target_functions, (
        f'Expected helpers {sorted(target_functions)}, '
        f'found {sorted(found_function_names)}'
    )

    class FakeFactMemoryStore:
        created_instances = []
        next_facts = []

        def __init__(self):
            self.calls = []
            self.__class__.created_instances.append(self)

        def list_facts(self, **kwargs):
            self.calls.append(kwargs)
            filtered_facts = []
            for fact in self.__class__.next_facts:
                if kwargs.get('memory_type') and fact.get('memory_type') != kwargs['memory_type']:
                    continue
                filtered_facts.append(dict(fact))
            return filtered_facts

        def get_facts(self, **kwargs):
            return self.list_facts(**kwargs)

        def update_fact_embedding(self, scope_id, fact_id, value_embedding, embedding_model=None):
            for fact in self.__class__.next_facts:
                if fact.get('id') == fact_id and fact.get('scope_id') == scope_id:
                    fact['value_embedding'] = list(value_embedding)
                    fact['embedding_model'] = embedding_model
                    return dict(fact)
            return None

    def fake_generate_embedding(value):
        query = str(value or '').lower()
        if 'who am i' in query or 'about me' in query or 'name' in query:
            return [1.0, 0.0], {'model_deployment_name': 'test-embedding-model'}
        return [0.0, 1.0], {'model_deployment_name': 'test-embedding-model'}

    namespace = {
        'FactMemoryStore': FakeFactMemoryStore,
        'datetime': datetime,
        'debug_print': lambda *args, **kwargs: None,
        'generate_embedding': fake_generate_embedding,
        'generate_embeddings_batch': lambda values: [fake_generate_embedding(value) for value in values],
        'make_json_serializable': lambda value: value,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, FakeFactMemoryStore, route_source


class FakeFactContainer:
    def __init__(self, not_found_error):
        self._items = {}
        self.not_found_error = not_found_error

    def upsert_item(self, item=None, body=None):
        document = dict(item if item is not None else body)
        self._items[document['id']] = document
        return document

    def read_item(self, item, partition_key):
        document = self._items.get(item)
        if document is None or document.get('scope_id') != partition_key:
            raise self.not_found_error()
        return dict(document)

    def query_items(self, query, parameters, partition_key):
        del query
        parameter_map = {entry['name']: entry['value'] for entry in parameters}
        results = []
        for item in self._items.values():
            if item.get('scope_id') != partition_key:
                continue
            if item.get('scope_type') != parameter_map.get('@scope_type'):
                continue
            results.append(dict(item))
        return results

    def delete_item(self, item, partition_key):
        document = self._items.get(item)
        if document is None or document.get('scope_id') != partition_key:
            raise self.not_found_error()
        del self._items[item]


def test_fact_memory_store_supports_memory_types_and_embeddings():
    """Verify the shared fact-memory store supports typed memories and embeddings."""
    print('🔍 Testing shared fact-memory store typed memory support...')

    fact_memory_store_class, not_found_error = load_store_class()
    fake_container = FakeFactContainer(not_found_error)
    fact_memory_store = fact_memory_store_class(container=fake_container)

    older_fact = fact_memory_store.set_fact(
        scope_type='user',
        scope_id='user-123',
        value='The user prefers short answers.',
        conversation_id=None,
        agent_id=None,
        memory_type='instruction',
    )
    newer_fact = fact_memory_store.set_fact(
        scope_type='user',
        scope_id='user-123',
        value='The user wants numbered next steps.',
        conversation_id=None,
        agent_id=None,
        memory_type='fact',
    )

    updated_fact = fact_memory_store.update_fact(
        scope_id='user-123',
        fact_id=older_fact['id'],
        value='The user prefers concise answers.',
        memory_type='instruction',
    )

    assert updated_fact is not None, 'Expected update_fact to return the updated document.'
    assert updated_fact['value'] == 'The user prefers concise answers.'
    assert updated_fact['memory_type'] == 'instruction'
    assert updated_fact.get('value_embedding') is None
    assert newer_fact.get('memory_type') == 'fact'
    assert isinstance(newer_fact.get('value_embedding'), list) and newer_fact['value_embedding']

    listed_facts = fact_memory_store.list_facts(scope_type='user', scope_id='user-123')
    assert [fact['id'] for fact in listed_facts] == [older_fact['id'], newer_fact['id']], listed_facts
    assert listed_facts[0]['updated_at'] >= listed_facts[1]['updated_at']

    instruction_facts = fact_memory_store.list_facts(scope_type='user', scope_id='user-123', memory_type='instruction')
    fact_memories = fact_memory_store.list_facts(scope_type='user', scope_id='user-123', memory_type='fact')
    assert [fact['id'] for fact in instruction_facts] == [older_fact['id']]
    assert [fact['id'] for fact in fact_memories] == [newer_fact['id']]

    assert fact_memory_store.delete_fact('user-123', newer_fact['id']) is True
    assert fact_memory_store.get_fact('user-123', newer_fact['id']) is None

    print('✅ Shared fact-memory store typed memory support passed')
    return True


def test_tabular_fact_memory_helper_respects_admin_toggle_and_types():
    """Verify mini-SK fact-memory messages include instruction and fact memories."""
    print('🔍 Testing mini-SK fact-memory helper typed recall...')

    namespace, fake_store_class, _ = load_tabular_fact_memory_helpers()
    fake_store_class.created_instances = []
    fake_store_class.next_facts = [
        {
            'id': 'instruction-1',
            'scope_id': 'user-123',
            'value': 'Use concise responses without em dashes.',
            'memory_type': 'instruction',
            'updated_at': '2025-01-01T00:00:00+00:00',
        },
        {
            'id': 'fact-1',
            'scope_id': 'user-123',
            'value': "User's name is Paul.",
            'memory_type': 'fact',
            'value_embedding': [1.0, 0.0],
            'updated_at': '2025-01-02T00:00:00+00:00',
        },
        {
            'id': 'fact-2',
            'scope_id': 'user-123',
            'value': 'User lives in Alexandria.',
            'memory_type': 'fact',
            'value_embedding': [0.92, 0.08],
            'updated_at': '2025-01-03T00:00:00+00:00',
        },
        {
            'id': 'fact-3',
            'scope_id': 'user-123',
            'value': 'Server timeout is 30 seconds.',
            'memory_type': 'fact',
            'value_embedding': [0.0, 1.0],
            'updated_at': '2025-01-04T00:00:00+00:00',
        },
    ]

    disabled_messages = namespace['build_tabular_fact_memory_messages'](
        scope_id='user-123',
        scope_type='user',
        conversation_id='conversation-456',
        enabled=False,
    )
    assert disabled_messages == [], disabled_messages

    enabled_messages = namespace['build_tabular_fact_memory_messages'](
        scope_id='user-123',
        scope_type='user',
        query_text='who am i?',
        conversation_id='conversation-456',
        enabled=True,
    )
    assert len(enabled_messages) == 3, enabled_messages
    assert '<Instruction Memory>' in enabled_messages[0]['content'], enabled_messages[0]
    assert 'Use concise responses without em dashes.' in enabled_messages[0]['content']
    assert '<Conversation Metadata>' in enabled_messages[1]['content'], enabled_messages[1]
    assert '<Fact Memory>' in enabled_messages[2]['content'], enabled_messages[2]
    assert "User's name is Paul." in enabled_messages[2]['content']
    assert 'User lives in Alexandria.' in enabled_messages[2]['content']
    assert 'Server timeout is 30 seconds.' not in enabled_messages[2]['content']
    recorded_calls = []
    for instance in fake_store_class.created_instances:
        recorded_calls.extend(instance.calls)
    assert recorded_calls == [
        {
            'scope_type': 'user',
            'scope_id': 'user-123',
            'memory_type': 'instruction',
        },
        {
            'scope_type': 'user',
            'scope_id': 'user-123',
            'memory_type': 'fact',
            'conversation_id': 'conversation-456',
        },
    ], recorded_calls

    print('✅ Mini-SK fact-memory helper typed recall passed')
    return True


def test_route_sources_wire_chat_and_profile_fact_memory_paths():
    """Verify chat/profile sources include the new fact-memory wiring."""
    print('🔍 Testing route wiring for chat and profile fact-memory paths...')

    route_source = read_file_text(ROUTE_FILE)
    profile_route_source = read_file_text(PROFILE_ROUTE_FILE)

    assert 'build_tabular_fact_memory_messages(' in route_source
    assert route_source.count('enabled=fact_memory_enabled') >= 3, route_source
    assert "settings.get('enable_fact_memory_plugin', False)" in route_source
    assert "user_settings.get('enable_agents', True)" in route_source
    assert 'Fact Memory Recall' in route_source
    assert 'Instruction Memory' in route_source
    assert "memory_type': 'instruction'" in route_source or 'FACT_MEMORY_TYPE_INSTRUCTION' in route_source
    assert "'fact_memory'" in route_source

    assert "@app.route('/api/profile/fact-memory', methods=['GET'])" in profile_route_source
    assert "@app.route('/api/profile/fact-memory', methods=['POST'])" in profile_route_source
    assert "@app.route('/api/profile/fact-memory/<fact_id>', methods=['PUT'])" in profile_route_source
    assert "@app.route('/api/profile/fact-memory/<fact_id>', methods=['DELETE'])" in profile_route_source
    assert 'FactMemoryStore()' in profile_route_source
    assert 'memory_type' in profile_route_source

    print('✅ Route wiring for chat and profile fact-memory paths passed')
    return True


def test_version_and_feature_documentation_alignment():
    """Verify version bump and feature documentation stay aligned."""
    print('🔍 Testing version and feature documentation alignment...')

    feature_doc_content = read_file_text(FEATURE_DOC)

    assert read_config_version() == '0.240.085'
    assert 'Implemented in version: **0.240.077**' in feature_doc_content
    assert 'Updated in version:' in feature_doc_content
    assert 'Updated in version: **0.240.085**' in feature_doc_content
    assert 'Related config.py update: `VERSION = "0.240.085"`' in feature_doc_content
    assert 'mini-SK' in feature_doc_content
    assert 'profile recall' in feature_doc_content.lower()
    assert 'popup manager' in feature_doc_content.lower()
    assert 'thoughts and citations' in feature_doc_content.lower()
    assert 'instruction memories' in feature_doc_content.lower()
    assert 'fact memories' in feature_doc_content.lower()
    assert 'latest features' in feature_doc_content.lower()
    assert 'functional_tests/test_fact_memory_profile_and_mini_sk.py' in feature_doc_content
    assert 'ui_tests/test_profile_fact_memory_editor.py' in feature_doc_content

    print('✅ Version and feature documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_fact_memory_store_supports_memory_types_and_embeddings,
        test_tabular_fact_memory_helper_respects_admin_toggle_and_types,
        test_route_sources_wire_chat_and_profile_fact_memory_paths,
        test_version_and_feature_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)