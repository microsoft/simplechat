# test_citation_revision_lookup_fix.py
#!/usr/bin/env python3
"""
Functional test for citation revision lookup fix.
Version: 0.240.024
Implemented in: 0.240.024

This test ensures citation lookup resolves access by the exact document ID
behind a chunk so new revisions continue to point at the correct document
record as revision-aware blob paths are introduced.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_documents.py')
ENHANCED_ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_enhanced_citations.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(ROOT_DIR, 'docs', 'explanation', 'fixes', 'CITATION_REVISION_LOOKUP_FIX.md')
TARGET_FUNCTIONS = {
    '_extract_citation_document_id',
    '_try_get_document_json',
    '_find_accessible_citation_document',
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self):
        return self.payload


def load_citation_helpers():
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {}
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, source


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_extract_citation_document_id_prefers_chunk_metadata():
    print('🔍 Testing citation document ID extraction...')

    namespace, _ = load_citation_helpers()
    extract_document_id = namespace['_extract_citation_document_id']

    assert extract_document_id({'document_id': 'doc-revision-2'}, 'doc-revision-1_4') == 'doc-revision-2'
    assert extract_document_id({}, 'doc-revision-1_4') == 'doc-revision-1'
    assert extract_document_id({}, 'raw-citation-id') == 'raw-citation-id'

    print('✅ Citation document ID extraction passed')
    return True


def test_find_accessible_citation_document_uses_exact_document_id():
    print('🔍 Testing exact document lookup across citation scopes...')

    namespace, _ = load_citation_helpers()
    find_accessible_document = namespace['_find_accessible_citation_document']
    calls = []

    def fake_get_settings():
        return {
            'enable_user_workspace': True,
            'enable_group_workspaces': True,
            'enable_public_workspaces': True,
        }

    def fake_get_document(user_id, document_id, group_id=None, public_workspace_id=None):
        calls.append({
            'user_id': user_id,
            'document_id': document_id,
            'group_id': group_id,
            'public_workspace_id': public_workspace_id,
        })

        if document_id != 'doc-revision-2':
            return {'error': 'not found'}, 404

        if group_id == 'group-1':
            return FakeResponse({'id': document_id, 'group_id': group_id}), 200

        if public_workspace_id == 'ws-1':
            return FakeResponse({'id': document_id, 'public_workspace_id': public_workspace_id}), 200

        if group_id is None and public_workspace_id is None:
            return FakeResponse({'id': document_id, 'user_id': user_id}), 200

        return {'error': 'not found'}, 404

    namespace['get_settings'] = fake_get_settings
    namespace['get_document'] = fake_get_document
    namespace['get_user_groups'] = lambda user_id: [{'id': 'group-1'}, {'id': 'group-2'}]
    namespace['get_user_visible_public_workspace_ids_from_settings'] = lambda user_id: ['ws-1']

    personal_doc = find_accessible_document('user-1', 'doc-revision-2', 'personal')
    group_doc = find_accessible_document('user-1', 'doc-revision-2', 'group')
    public_doc = find_accessible_document('user-1', 'doc-revision-2', 'public')

    assert personal_doc['id'] == 'doc-revision-2'
    assert group_doc['group_id'] == 'group-1'
    assert public_doc['public_workspace_id'] == 'ws-1'
    assert all(call['document_id'] == 'doc-revision-2' for call in calls), calls

    print('✅ Exact document lookup across citation scopes passed')
    return True


def test_revision_lookup_is_wired_into_text_and_enhanced_citations():
    print('🔍 Testing citation route wiring...')

    _, route_source = load_citation_helpers()
    enhanced_route_source = read_file_text(ENHANCED_ROUTE_FILE)

    assert "document_id = _extract_citation_document_id(chunk, citation_id)" in route_source
    assert "accessible_document = _find_accessible_citation_document(user_id, document_id, scope_name)" in route_source
    assert 'Unauthorized access to citation' in route_source
    assert 'backend_get_document(user_id, doc_id)' in enhanced_route_source
    assert 'get_document_blob_storage_info(raw_doc)' in enhanced_route_source

    print('✅ Citation route wiring passed')
    return True


def test_version_and_fix_documentation_alignment():
    print('🔍 Testing version and fix documentation alignment...')

    version = read_config_version()
    fix_doc_content = read_file_text(FIX_DOC)

    assert version == '0.240.024', version
    assert 'Fixed/Implemented in version: **0.240.024**' in fix_doc_content
    assert 'exact document ID behind the citation chunk' in fix_doc_content
    assert 'application/single_app/route_backend_documents.py' in fix_doc_content

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_extract_citation_document_id_prefers_chunk_metadata,
        test_find_accessible_citation_document_uses_exact_document_id,
        test_revision_lookup_is_wired_into_text_and_enhanced_citations,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)