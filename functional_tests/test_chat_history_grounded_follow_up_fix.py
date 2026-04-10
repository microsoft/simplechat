# test_chat_history_grounded_follow_up_fix.py
"""
Functional test for grounded follow-up chat fallback.
Version: 0.241.003
Implemented in: 0.240.054; Updated in: 0.241.003

This test ensures follow-up turns with workspace search disabled can reuse
prior grounded document refs, derive bounded fallback search parameters, and
preserve the no-search grounding contract only for conversations that already
have grounded document history.
"""

import ast
import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
METADATA_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'functions_conversation_metadata.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.003',
    'CHAT_HISTORY_GROUNDED_FOLLOW_UP_FIX.md',
)
ROUTE_TARGET_FUNCTIONS = {
    '_normalize_prior_grounded_document_refs',
    'build_prior_grounded_document_search_parameters',
    'build_history_only_assessment_messages',
    'build_history_grounding_system_message',
    'should_apply_history_grounding_message',
}
METADATA_TARGET_FUNCTIONS = {
    '_extract_document_id_from_search_result',
    '_build_last_grounded_document_refs',
}


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_route_helpers():
    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in ROUTE_TARGET_FUNCTIONS
    ]
    assert len(selected_nodes) == len(ROUTE_TARGET_FUNCTIONS), (
        f'Expected route helpers {sorted(ROUTE_TARGET_FUNCTIONS)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, source


def load_metadata_helpers():
    source = read_file_text(METADATA_FILE)
    parsed = ast.parse(source, filename=METADATA_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in METADATA_TARGET_FUNCTIONS
    ]
    assert len(selected_nodes) == len(METADATA_TARGET_FUNCTIONS), (
        f'Expected metadata helpers {sorted(METADATA_TARGET_FUNCTIONS)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, METADATA_FILE, 'exec'), namespace)
    return namespace, source


def test_grounded_document_refs_capture_stable_document_ids():
    """Verify grounded refs preserve stable parent document ids across scopes."""
    print('🔍 Testing grounded document ref capture...')

    namespace, _ = load_metadata_helpers()
    extract_document_id = namespace['_extract_document_id_from_search_result']
    build_grounded_refs = namespace['_build_last_grounded_document_refs']

    assert extract_document_id({'document_id': 'doc-123', 'id': 'doc-123_0001'}) == 'doc-123'
    assert extract_document_id({'id': 'group_doc_0007'}) == 'group_doc'
    assert extract_document_id({'id': 'standalone-doc'}) == 'standalone-doc'

    grounded_refs = build_grounded_refs({
        'personal-doc': {
            'scope': {'scope': 'personal', 'id': 'user-1'},
            'classification': 'internal',
            'file_name': 'Personal Notes.pdf',
        },
        'group-doc': {
            'scope': {'scope': 'group', 'id': 'group-22'},
            'classification': 'confidential',
            'file_name': 'Group Plan.docx',
        },
        'public-doc': {
            'scope': {'scope': 'public', 'id': 'workspace-33'},
            'classification': 'public',
            'file_name': 'FAQ.md',
        },
    })

    assert grounded_refs == [
        {
            'document_id': 'personal-doc',
            'scope': 'personal',
            'scope_id': 'user-1',
            'file_name': 'Personal Notes.pdf',
            'classification': 'internal',
            'user_id': 'user-1',
        },
        {
            'document_id': 'group-doc',
            'scope': 'group',
            'scope_id': 'group-22',
            'file_name': 'Group Plan.docx',
            'classification': 'confidential',
            'group_id': 'group-22',
        },
        {
            'document_id': 'public-doc',
            'scope': 'public',
            'scope_id': 'workspace-33',
            'file_name': 'FAQ.md',
            'classification': 'public',
            'public_workspace_id': 'workspace-33',
        },
    ], grounded_refs

    print('✅ Grounded document ref capture passed')
    return True


def test_prior_grounded_refs_normalize_from_saved_refs_and_tags():
    """Verify fallback refs normalize saved grounded refs first, then tags."""
    print('🔍 Testing grounded ref normalization...')

    namespace, _ = load_route_helpers()
    normalize_refs = namespace['_normalize_prior_grounded_document_refs']

    normalized_refs = normalize_refs({
        'last_grounded_document_refs': [
            {
                'document_id': 'doc-1',
                'scope': 'group',
                'scope_id': 'group-1',
                'file_name': 'Plan A.docx',
                'classification': 'internal',
            },
            {
                'document_id': 'doc-1',
                'scope': 'group',
                'group_id': 'group-1',
                'file_name': 'Plan A.docx',
            },
            {
                'document_id': 'doc-2',
                'scope': 'personal',
                'user_id': 'user-1',
                'file_name': 'Notes.txt',
            },
        ]
    })

    assert normalized_refs == [
        {
            'document_id': 'doc-1',
            'scope': 'group',
            'scope_id': 'group-1',
            'file_name': 'Plan A.docx',
            'classification': 'internal',
            'group_id': 'group-1',
        },
        {
            'document_id': 'doc-2',
            'scope': 'personal',
            'scope_id': 'user-1',
            'file_name': 'Notes.txt',
            'classification': None,
            'user_id': 'user-1',
        },
    ], normalized_refs

    tag_fallback_refs = normalize_refs({
        'tags': [
            {
                'category': 'document',
                'document_id': 'doc-3',
                'title': 'Workspace FAQ.md',
                'classification': 'public',
                'scope': {'type': 'public', 'id': 'workspace-7'},
            },
        ]
    })

    assert tag_fallback_refs == [
        {
            'document_id': 'doc-3',
            'scope': 'public',
            'scope_id': 'workspace-7',
            'file_name': 'Workspace FAQ.md',
            'classification': 'public',
            'public_workspace_id': 'workspace-7',
        },
    ], tag_fallback_refs

    print('✅ Grounded ref normalization passed')
    return True


def test_prior_grounded_search_parameters_stay_bounded():
    """Verify grounded fallback search stays limited to previously grounded docs."""
    print('🔍 Testing grounded fallback search parameter derivation...')

    namespace, _ = load_route_helpers()
    build_search_parameters = namespace['build_prior_grounded_document_search_parameters']

    mixed_scope_parameters = build_search_parameters([
        {'document_id': 'doc-1', 'scope': 'group', 'group_id': 'group-1'},
        {'document_id': 'doc-2', 'scope': 'public', 'public_workspace_id': 'workspace-1'},
        {'document_id': 'doc-3', 'scope': 'personal', 'user_id': 'user-1'},
        {'document_id': 'doc-2', 'scope': 'public', 'public_workspace_id': 'workspace-1'},
    ])

    assert mixed_scope_parameters == {
        'document_ids': ['doc-1', 'doc-2', 'doc-3'],
        'doc_scope': 'all',
        'active_group_ids': ['group-1'],
        'active_group_id': 'group-1',
        'active_public_workspace_ids': ['workspace-1'],
        'active_public_workspace_id': 'workspace-1',
        'scope_types': ['group', 'personal', 'public'],
    }, mixed_scope_parameters

    group_only_parameters = build_search_parameters([
        {'document_id': 'group-doc-1', 'scope': 'group', 'group_id': 'group-9'},
        {'document_id': 'group-doc-2', 'scope': 'group', 'group_id': 'group-9'},
    ])

    assert group_only_parameters['doc_scope'] == 'group'
    assert group_only_parameters['active_group_ids'] == ['group-9']
    assert group_only_parameters['document_ids'] == ['group-doc-1', 'group-doc-2']

    print('✅ Grounded fallback search parameter derivation passed')
    return True


def test_history_only_prompt_contract_is_explicit():
    """Verify history-only assessment and final no-search prompt stay explicit."""
    print('🔍 Testing history-only prompt contract...')

    namespace, _ = load_route_helpers()
    build_assessment_messages = namespace['build_history_only_assessment_messages']
    build_grounding_message = namespace['build_history_grounding_system_message']
    should_apply_grounding_message = namespace['should_apply_history_grounding_message']

    assessment_messages = build_assessment_messages(
        {
            'summary_of_older': 'Older answer summary',
            'history_messages': [
                {'role': 'assistant', 'content': 'The cited policy says approvals take two days.'},
                {'role': 'user', 'content': 'What about exceptions?'},
            ],
        },
        'Use concise answers.',
    )

    assert assessment_messages[0]['role'] == 'system'
    assert '<Summary of previous conversation context>' in assessment_messages[0]['content']
    assert assessment_messages[1] == {'role': 'system', 'content': 'Use concise answers.'}
    assert assessment_messages[2]['role'] == 'assistant'
    assert assessment_messages[3]['content'] == 'What about exceptions?'

    grounding_message = build_grounding_message()
    assert grounding_message['role'] == 'system'
    assert 'Workspace search is disabled for this turn.' in grounding_message['content']
    assert 'ask the user to select a workspace or document' in grounding_message['content']

    assert should_apply_grounding_message(False, []) is False
    assert should_apply_grounding_message(False, None) is False
    assert should_apply_grounding_message(True, [{'document_id': 'doc-1'}]) is False
    assert should_apply_grounding_message(False, [{'document_id': 'doc-1'}]) is True

    print('✅ History-only prompt contract passed')
    return True


def test_route_and_metadata_wiring_cover_both_chat_paths():
    """Verify grounded follow-up fallback is wired in standard and streaming chat paths."""
    print('🔍 Testing grounded follow-up wiring...')

    _, route_source = load_route_helpers()
    _, metadata_source = load_metadata_helpers()

    assert "conversation_item['last_grounded_document_refs'] = _build_last_grounded_document_refs(document_map)" in metadata_source
    assert route_source.count('history_grounded_search_used = True') == 2
    assert route_source.count('Checking whether prior conversation context already answers the question') == 2
    assert route_source.count('Conversation context alone was insufficient; searching previously grounded documents') == 2
    assert route_source.count('No prior grounded documents were available; using conversation history only') == 2
    assert route_source.count("'history_grounded_fallback'") == 2
    assert route_source.count('if not original_hybrid_search_enabled:') == 2
    assert route_source.count('if should_apply_history_grounding_message(') == 2
    assert route_source.count('history_grounding_message = build_history_grounding_system_message()') == 2

    print('✅ Grounded follow-up wiring passed')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert read_config_version() == '0.241.003'
    assert 'Fixed/Implemented in version: **0.241.003**' in fix_doc_content
    assert 'last_grounded_document_refs' in fix_doc_content
    assert 'previously grounded documents' in fix_doc_content.lower()
    assert 'new conversations without prior grounded document refs now answer normally' in fix_doc_content.lower()
    assert 'application/single_app/route_backend_chats.py' in fix_doc_content
    assert 'application/single_app/functions_conversation_metadata.py' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_grounded_document_refs_capture_stable_document_ids,
        test_prior_grounded_refs_normalize_from_saved_refs_and_tags,
        test_prior_grounded_search_parameters_stay_bounded,
        test_history_only_prompt_contract_is_explicit,
        test_route_and_metadata_wiring_cover_both_chat_paths,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)