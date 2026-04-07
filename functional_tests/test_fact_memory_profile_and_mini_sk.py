# test_fact_memory_profile_and_mini_sk.py
"""
Functional test for profile fact memory recall and mini-SK fact-memory support.
Version: 0.240.077
Implemented in: 0.240.077

This test ensures fact memory can be updated in the shared store, the mini-SK
tabular helper only injects fact memory when the admin toggle is enabled, and
the profile route exposes CRUD endpoints for user-controlled memory recall.
"""

import ast
import copy
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
    target_functions = {
        '_build_fact_memory_context_lines',
        'build_tabular_fact_memory_messages',
    }

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in target_functions:
            selected_nodes.append(copy.deepcopy(node))

    assert len(selected_nodes) == len(target_functions), (
        f'Expected helpers {sorted(target_functions)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    class FakeFactMemoryStore:
        created_instances = []
        next_facts = []

        def __init__(self):
            self.calls = []
            self.__class__.created_instances.append(self)

        def get_facts(self, **kwargs):
            self.calls.append(kwargs)
            return list(self.__class__.next_facts)

    namespace = {
        'FactMemoryStore': FakeFactMemoryStore,
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


def test_fact_memory_store_supports_update_and_sorted_listing():
    """Verify the shared fact-memory store can update and sort recalled facts."""
    print('🔍 Testing shared fact-memory store update support...')

    fact_memory_store_class, not_found_error = load_store_class()
    fake_container = FakeFactContainer(not_found_error)
    fact_memory_store = fact_memory_store_class(container=fake_container)

    older_fact = fact_memory_store.set_fact(
        scope_type='user',
        scope_id='user-123',
        value='The user prefers short answers.',
        conversation_id=None,
        agent_id=None,
    )
    newer_fact = fact_memory_store.set_fact(
        scope_type='user',
        scope_id='user-123',
        value='The user wants numbered next steps.',
        conversation_id=None,
        agent_id=None,
    )

    updated_fact = fact_memory_store.update_fact(
        scope_id='user-123',
        fact_id=older_fact['id'],
        value='The user prefers concise answers.',
    )

    assert updated_fact is not None, 'Expected update_fact to return the updated document.'
    assert updated_fact['value'] == 'The user prefers concise answers.'

    listed_facts = fact_memory_store.list_facts(scope_type='user', scope_id='user-123')
    assert [fact['id'] for fact in listed_facts] == [older_fact['id'], newer_fact['id']], listed_facts
    assert listed_facts[0]['updated_at'] >= listed_facts[1]['updated_at']

    assert fact_memory_store.delete_fact('user-123', newer_fact['id']) is True
    assert fact_memory_store.get_fact('user-123', newer_fact['id']) is None

    print('✅ Shared fact-memory store update support passed')
    return True


def test_tabular_fact_memory_helper_respects_admin_toggle():
    """Verify mini-SK fact-memory messages are gated by the admin toggle."""
    print('🔍 Testing mini-SK fact-memory helper gating...')

    namespace, fake_store_class, _ = load_tabular_fact_memory_helpers()
    fake_store_class.created_instances = []
    fake_store_class.next_facts = [
        {'value': 'The user prefers fiscal years labeled by start year.'},
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
        conversation_id='conversation-456',
        enabled=True,
    )
    assert len(enabled_messages) == 2, enabled_messages
    assert '<Conversation Metadata>' in enabled_messages[0]['content'], enabled_messages[0]
    assert '<Fact Memory>' in enabled_messages[1]['content'], enabled_messages[1]
    assert 'The user prefers fiscal years labeled by start year.' in enabled_messages[1]['content']
    assert fake_store_class.created_instances[-1].calls == [{
        'scope_type': 'user',
        'scope_id': 'user-123',
        'conversation_id': 'conversation-456',
    }], fake_store_class.created_instances[-1].calls

    print('✅ Mini-SK fact-memory helper gating passed')
    return True


def test_route_sources_wire_chat_and_profile_fact_memory_paths():
    """Verify chat/profile sources include the new fact-memory wiring."""
    print('🔍 Testing route wiring for chat and profile fact-memory paths...')

    route_source = read_file_text(ROUTE_FILE)
    profile_route_source = read_file_text(PROFILE_ROUTE_FILE)

    assert 'build_tabular_fact_memory_messages(' in route_source
    assert route_source.count('enabled=fact_memory_enabled') >= 3, route_source
    assert "settings.get('enable_fact_memory_plugin', False)" in route_source

    assert "@app.route('/api/profile/fact-memory', methods=['GET'])" in profile_route_source
    assert "@app.route('/api/profile/fact-memory', methods=['POST'])" in profile_route_source
    assert "@app.route('/api/profile/fact-memory/<fact_id>', methods=['PUT'])" in profile_route_source
    assert "@app.route('/api/profile/fact-memory/<fact_id>', methods=['DELETE'])" in profile_route_source
    assert 'FactMemoryStore()' in profile_route_source

    print('✅ Route wiring for chat and profile fact-memory paths passed')
    return True


def test_version_and_feature_documentation_alignment():
    """Verify version bump and feature documentation stay aligned."""
    print('🔍 Testing version and feature documentation alignment...')

    feature_doc_content = read_file_text(FEATURE_DOC)

    assert read_config_version() == '0.240.077'
    assert 'Implemented in version: **0.240.077**' in feature_doc_content
    assert 'mini-SK' in feature_doc_content
    assert 'profile recall' in feature_doc_content.lower()
    assert 'functional_tests/test_fact_memory_profile_and_mini_sk.py' in feature_doc_content
    assert 'ui_tests/test_profile_fact_memory_editor.py' in feature_doc_content

    print('✅ Version and feature documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_fact_memory_store_supports_update_and_sorted_listing,
        test_tabular_fact_memory_helper_respects_admin_toggle,
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