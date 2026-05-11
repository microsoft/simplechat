# test_document_revision_current_version_fix.py
"""
Functional test for document revision current-version behavior.
Version: 0.240.022
Implemented in: 0.240.022

This test ensures duplicate-name uploads preserve revision metadata, only the
latest revision stays visible/searchable, and workspace delete flows expose a
current-only versus all-versions choice.
"""

import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_FILE = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')
FUNCTIONS_DOCUMENTS = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_documents.py')
FUNCTIONS_SEARCH = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_search.py')
PERSONAL_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_documents.py')
GROUP_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_group_documents.py')
PUBLIC_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_public_documents.py')
EXTERNAL_PUBLIC_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_external_public_documents.py')
ENHANCED_CITATIONS_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_enhanced_citations.py')
WORKSPACE_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'workspace.html')
PUBLIC_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'public_workspaces.html')
GROUP_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'group_workspaces.html')
WORKSPACE_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'workspace', 'workspace-documents.js')
PUBLIC_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'public', 'public_workspace.js')
FIX_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'fixes', 'DOCUMENT_REVISION_CURRENT_VERSION_FIX.md')


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_revision_metadata_helpers_exist():
    """Ensure document metadata now models revision families and current visibility."""
    print('🔍 Validating revision metadata helpers...')

    documents_content = read_file_text(FUNCTIONS_DOCUMENTS)
    search_content = read_file_text(FUNCTIONS_SEARCH)
    enhanced_citations_content = read_file_text(ENHANCED_CITATIONS_ROUTE)

    for marker in [
        'revision_family_id',
        'is_current_version',
        'search_visibility_state',
        'select_current_documents',
        'normalize_document_revision_families',
        'set_document_chunk_visibility',
        'def delete_document_revision(',
        'carried_forward = _build_carried_forward_metadata(',
        'CURRENT_ALIAS_BLOB_PATH_MODE = "current_alias"',
        'ARCHIVED_REVISION_BLOB_PATH_MODE = "archived_revision"',
        'def build_current_blob_path(',
        'def build_archived_blob_path(',
        'def get_document_blob_storage_info(',
        'def get_document_blob_delete_targets(',
        'def _archive_previous_document_blob(',
        'def _promote_document_blob_to_current_alias(',
        '"search_visibility_state": "active"',
        "existing_document['search_visibility_state'] = 'archived'",
        "promoted_document['is_current_version'] = True",
        'blob_container',
        'archived_blob_path',
        'blob_path_mode',
    ]:
        assert marker in documents_content, f'Missing revision metadata marker: {marker}'

    assert 'normalize_document_revision_families(' in search_content, (
        'Hybrid search should normalize duplicate revision families before searching.'
    )
    assert 'get_document_blob_storage_info' in enhanced_citations_content, (
        'Enhanced citations should resolve stored blob metadata before falling back to legacy paths.'
    )

    print('✅ Revision metadata helpers are present')


def test_blob_revision_paths_preserve_current_alias_and_archive_history():
    """Ensure the blob storage model keeps the current alias and archives prior revisions hierarchically."""
    print('🔍 Validating blob revision path hierarchy...')

    documents_content = read_file_text(FUNCTIONS_DOCUMENTS)

    assert 'return f"{scope_id}/{blob_filename}"' in documents_content, (
        'Current revisions should keep the existing workspace alias path.'
    )
    assert 'return f"{scope_id}/{revision_family_id}/{document_id}/{file_name}"' in documents_content, (
        'Archived revisions should be grouped under revision_family_id/document_id/filename.'
    )
    assert 'previous_document["blob_path"] = archived_blob_path' in documents_content, (
        'Previous current revisions should move to the archived blob path.'
    )
    assert 'promoted_document["blob_path"] = current_blob_path' in documents_content, (
        'Promoted revisions should return to the current alias blob path.'
    )

    print('✅ Blob revision path hierarchy is present')


def test_workspace_routes_only_return_current_revisions_and_accept_delete_modes():
    """Ensure every workspace route collapses to current revisions and supports delete_mode."""
    print('🔍 Validating workspace route revision filtering and delete modes...')

    route_expectations = [
        PERSONAL_ROUTE,
        GROUP_ROUTE,
        PUBLIC_ROUTE,
        EXTERNAL_PUBLIC_ROUTE,
    ]

    for route_path in route_expectations:
        route_content = read_file_text(route_path)
        assert 'select_current_documents' in route_content, (
            f'{os.path.basename(route_path)} should collapse results to current revisions.'
        )
        assert 'sort_documents' in route_content, (
            f'{os.path.basename(route_path)} should sort collapsed current revisions.'
        )
        assert "delete_mode = request.args.get('delete_mode', 'all_versions')" in route_content, (
            f'{os.path.basename(route_path)} should accept delete_mode.'
        )
        assert 'delete_document_revision(' in route_content, (
            f'{os.path.basename(route_path)} should use revision-aware deletion.'
        )

    print('✅ Workspace routes enforce current revision visibility and delete modes')


def test_delete_ui_uses_revision_choice_modals():
    """Ensure personal, public, and group workspaces expose Bootstrap revision delete choices."""
    print('🔍 Validating delete choice UI wiring...')

    workspace_template = read_file_text(WORKSPACE_TEMPLATE)
    public_template = read_file_text(PUBLIC_TEMPLATE)
    group_template = read_file_text(GROUP_TEMPLATE)
    workspace_js = read_file_text(WORKSPACE_JS)
    public_js = read_file_text(PUBLIC_JS)

    assert 'documentDeleteModal' in workspace_template, 'Workspace template should include the delete choice modal.'
    assert 'publicDocumentDeleteModal' in public_template, 'Public workspace template should include the delete choice modal.'
    assert 'groupDocumentDeleteModal' in group_template, 'Group workspace template should include the delete choice modal.'

    for content, label in [
        (workspace_js, 'workspace JS'),
        (public_js, 'public workspace JS'),
        (group_template, 'group workspace template JS'),
    ]:
        assert 'Delete Current Version' in content, f'{label} should offer current-version deletion.'
        assert 'Delete All Versions' in content, f'{label} should offer all-version deletion.'
        assert 'delete_mode' in content, f'{label} should send delete_mode to the backend.'

    print('✅ Delete choice UI wiring is present across workspace pages')


def test_document_revision_fix_documentation_and_version_alignment():
    """Ensure config and fix documentation capture the new revision behavior."""
    print('🔍 Validating version bump and fix documentation...')

    config_content = read_file_text(CONFIG_FILE)
    fix_doc_content = read_file_text(FIX_DOC)

    assert 'VERSION = "0.240.022"' in config_content, 'Expected config.py version 0.240.022'
    assert 'Fixed/Implemented in version: **0.240.022**' in fix_doc_content, (
        'Fix documentation should reference version 0.240.022.'
    )
    assert 'Delete Current Version' in fix_doc_content, (
        'Fix documentation should describe the current-version delete option.'
    )
    assert 'Delete All Versions' in fix_doc_content, (
        'Fix documentation should describe the all-versions delete option.'
    )
    assert 'user-id/revision-family-id/revision-document-id/filename' in fix_doc_content, (
        'Fix documentation should describe the archived revision blob path hierarchy.'
    )
    assert 'user-id/filename' in fix_doc_content, (
        'Fix documentation should describe the retained current alias blob path.'
    )
    assert 'older revisions' in fix_doc_content.lower(), (
        'Fix documentation should explain older revision retention.'
    )

    print('✅ Version bump and fix documentation are aligned')


if __name__ == '__main__':
    test_revision_metadata_helpers_exist()
    print()
    test_blob_revision_paths_preserve_current_alias_and_archive_history()
    print()
    test_workspace_routes_only_return_current_revisions_and_accept_delete_modes()
    print()
    test_delete_ui_uses_revision_choice_modals()
    print()
    test_document_revision_fix_documentation_and_version_alignment()