#!/usr/bin/env python3
# test_document_action_conversation_scope_metadata.py
"""
Functional test for document-action conversation scope metadata.
Version: 0.241.124
Implemented in: 0.241.124

This test ensures Analyze and tabular document-action results can assign
conversation workspace metadata from selected document summaries when no
hybrid search results are present, while preserving personal assigned-knowledge
primary context behavior.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METADATA_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'functions_conversation_metadata.py')
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_VERSION = '0.241.124'
TEST_USER_ID = 'scope-user-1'
CRIMSON_GROUP_ID = 'crimson-group-1'
PUBLIC_WORKSPACE_ID = 'public-workspace-1'

METADATA_TARGET_FUNCTIONS = {
    '_normalize_scope_id_list',
    '_build_primary_context_from_scope_selection',
    '_extract_document_id_from_search_result',
    '_build_last_grounded_document_refs',
    '_add_document_metadata_entry',
    '_determine_selected_document_scope',
    '_extract_selected_document_id',
    '_determine_document_scope',
    '_extract_semantic_keywords',
    'collect_conversation_metadata',
}


def read_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_metadata_helpers():
    source = read_text(METADATA_FILE)
    parsed = ast.parse(source, filename=METADATA_FILE)
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in METADATA_TARGET_FUNCTIONS
    ]
    assert len(selected_nodes) == len(METADATA_TARGET_FUNCTIONS), (
        f'Expected metadata helpers {sorted(METADATA_TARGET_FUNCTIONS)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, METADATA_FILE, 'exec'), namespace)
    namespace.update({
        'debug_print': lambda *args, **kwargs: None,
        'get_current_user_info': lambda: {
            'userId': TEST_USER_ID,
            'displayName': 'Scope Tester',
            'email': 'scope.tester@example.com',
        },
        'get_user_info_by_id': lambda user_id: {
            'userId': user_id,
            'name': 'Scope Tester',
            'email': 'scope.tester@example.com',
        },
        'find_group_by_id': lambda group_id: {
            'id': group_id,
            'name': 'Crimson',
        } if group_id == CRIMSON_GROUP_ID else None,
        'find_public_workspace_by_id': lambda workspace_id: {
            'id': workspace_id,
            'name': 'Public Knowledge',
        } if workspace_id == PUBLIC_WORKSPACE_ID else None,
        'get_document_metadata': lambda document_id, user_id, **kwargs: {
            'id': document_id,
            'title': 'Crimson Workbook' if kwargs.get('group_id') else 'Public Guide',
            'file_name': 'Crimson.xlsx' if kwargs.get('group_id') else 'Public Guide.md',
        },
    })
    return namespace


def test_selected_group_document_sets_conversation_primary_context():
    """Selected document summaries should assign group metadata without search results."""
    print('Testing selected group document metadata fallback...')
    namespace = load_metadata_helpers()
    collect_metadata = namespace['collect_conversation_metadata']

    updated = collect_metadata(
        user_message='Analyze the Crimson workbook',
        conversation_id='conversation-1',
        user_id=TEST_USER_ID,
        document_scope='all',
        active_group_ids=[CRIMSON_GROUP_ID],
        selected_documents=[{
            'document_id': 'crimson-workbook-doc',
            'file_name': 'Crimson.xlsx',
            'scope': 'group',
            'scope_id': CRIMSON_GROUP_ID,
            'classification': 'Confidential',
        }],
        search_results=None,
        conversation_item={
            'context': [],
            'tags': [],
            'strict': False,
        },
    )

    primary_context = next(context for context in updated['context'] if context.get('type') == 'primary')
    assert primary_context['scope'] == 'group'
    assert primary_context['id'] == CRIMSON_GROUP_ID
    assert primary_context['name'] == 'Crimson'
    assert updated['chat_type'] == 'group-single-user'
    assert updated['scope_locked'] is True

    locked_contexts = {(context.get('scope'), context.get('id')) for context in updated['locked_contexts']}
    assert ('group', CRIMSON_GROUP_ID) in locked_contexts

    document_tag = next(tag for tag in updated['tags'] if tag.get('category') == 'document')
    assert document_tag['document_id'] == 'crimson-workbook-doc'
    assert document_tag['scope']['type'] == 'group'
    assert document_tag['scope']['id'] == CRIMSON_GROUP_ID

    grounded_ref = updated['last_grounded_document_refs'][0]
    assert grounded_ref['document_id'] == 'crimson-workbook-doc'
    assert grounded_ref['scope'] == 'group'
    assert grounded_ref['group_id'] == CRIMSON_GROUP_ID
    print('PASS: selected group document metadata fallback')


def test_assigned_knowledge_personal_agent_keeps_personal_primary_context():
    """Assigned public knowledge should not replace personal-agent primary context."""
    print('Testing assigned-knowledge primary context preservation...')
    namespace = load_metadata_helpers()
    collect_metadata = namespace['collect_conversation_metadata']

    updated = collect_metadata(
        user_message='What documents can you use?',
        conversation_id='conversation-2',
        user_id=TEST_USER_ID,
        document_scope='all',
        active_public_workspace_ids=[PUBLIC_WORKSPACE_ID],
        selected_agent='PersonalAgent',
        selected_agent_details={
            'assigned_knowledge_enabled': True,
            'is_global': False,
        },
        selected_documents=[{
            'document_id': 'public-guide-doc',
            'file_name': 'Public Guide.md',
            'scope': 'public',
            'scope_id': PUBLIC_WORKSPACE_ID,
            'classification': 'Public',
        }],
        search_results=None,
        conversation_item={
            'context': [],
            'tags': [],
            'strict': False,
        },
    )

    primary_context = next(context for context in updated['context'] if context.get('type') == 'primary')
    assert primary_context['scope'] == 'personal'
    assert primary_context['id'] == TEST_USER_ID
    assert updated['chat_type'] == 'personal_single_user'

    secondary_contexts = {
        (context.get('scope'), context.get('id'))
        for context in updated['context']
        if context.get('type') == 'secondary'
    }
    assert ('public', PUBLIC_WORKSPACE_ID) in secondary_contexts

    locked_contexts = {(context.get('scope'), context.get('id')) for context in updated['locked_contexts']}
    assert ('personal', TEST_USER_ID) in locked_contexts
    assert ('public', PUBLIC_WORKSPACE_ID) in locked_contexts
    print('PASS: assigned-knowledge primary context preservation')


def test_document_action_stream_payload_preserves_metadata_fields():
    """Streaming document-action responses should carry conversation metadata updates."""
    print('Testing document-action stream payload metadata fields...')
    route_source = read_text(ROUTE_FILE)
    required_snippets = [
        "'context': payload.get('context', []),",
        "'chat_type': payload.get('chat_type'),",
        "'scope_locked': payload.get('scope_locked'),",
        "'locked_contexts': payload.get('locked_contexts', []),",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in route_source]
    assert not missing, f'Missing streaming payload metadata snippets: {missing}'
    print('PASS: document-action stream payload metadata fields')


def test_version_bumped_for_fix():
    """Verify config.py version was bumped for this fix."""
    print('Testing version bump...')
    assert read_config_version() == FIX_VERSION
    print('PASS: version bump')


if __name__ == '__main__':
    tests = [
        test_selected_group_document_sets_conversation_primary_context,
        test_assigned_knowledge_personal_agent_keeps_personal_primary_context,
        test_document_action_stream_payload_preserves_metadata_fields,
        test_version_bumped_for_fix,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {test.__name__}: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)