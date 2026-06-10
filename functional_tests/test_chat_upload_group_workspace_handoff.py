# test_chat_upload_group_workspace_handoff.py
#!/usr/bin/env python3
"""
Functional test for chat upload group workspace handoff.
Version: 0.241.176
Implemented in: 0.241.176

This test ensures group-scoped chat uploads are queued into group workspaces,
respect group write roles, avoid accidental group document revisions through
unique filenames, and use a group-only upload target picker without a personal
workspace fallback.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content, expected, description):
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def assert_not_contains(content, unexpected, description):
    if unexpected in content:
        raise AssertionError(f"Unexpected {description}: {unexpected}")


def test_group_workspace_queue_helper_contract():
    """Validate the document helper queues group workspace chat uploads safely."""
    functions_documents = read_repo_file("application/single_app/functions_documents.py")

    assert_contains(functions_documents, "def resolve_unique_group_workspace_file_name", "unique group filename resolver")
    assert_contains(functions_documents, "def _group_workspace_file_name_exists", "group filename collision query helper")
    assert_contains(functions_documents, "cosmos_group_documents_container", "group documents container usage")
    assert_contains(functions_documents, "def queue_group_workspace_upload_from_temp_file(", "group workspace queue helper")
    assert_contains(functions_documents, "group_id=group_id", "group id is passed through metadata and processing calls")
    assert_contains(functions_documents, "workspace_type='group'", "group tag definition creation")
    assert_contains(functions_documents, "resolve_unique_group_workspace_file_name(", "group queue helper requests unique filenames")
    assert_contains(functions_documents, "process_document_upload_background", "group helper queues standard document processing")
    assert_contains(functions_documents, "container_type='group'", "group upload activity logging")
    assert_contains(functions_documents, "source_original_file_name", "original filename metadata preservation")
    assert_contains(functions_documents, "chat_upload_workspace_filename", "resolved workspace filename metadata preservation")


def test_upload_route_group_scope_contract():
    """Validate /upload resolves group targets and avoids legacy chat storage fallback."""
    route_frontend_chats = read_repo_file("application/single_app/route_frontend_chats.py")

    assert_contains(route_frontend_chats, "GROUP_CHAT_UPLOAD_ROLES = ('Owner', 'Admin', 'DocumentManager')", "group upload role allowlist")
    assert_contains(route_frontend_chats, "def _resolve_group_workspace_upload_target", "group upload target resolver")
    assert_contains(route_frontend_chats, "check_group_status_allows_operation(group_doc, 'upload')", "group upload status validation")
    assert_contains(route_frontend_chats, "assert_group_role(user_id, normalized_selected_group_id, allowed_roles=GROUP_CHAT_UPLOAD_ROLES)", "server-side write role enforcement")
    assert_contains(route_frontend_chats, "Selected group does not match the conversation scope", "trusted scope mismatch rejection")
    assert_contains(route_frontend_chats, "requires_group_upload_target", "multi-group picker response contract")
    assert_contains(route_frontend_chats, "queue_group_workspace_upload_from_temp_file(", "group workspace queue call")
    assert_contains(route_frontend_chats, "group_id=group_upload_target.get('id')", "selected group id passed to queue helper")
    assert_contains(route_frontend_chats, "invalidate_group_search_cache(group_upload_target.get('id'))", "group search cache invalidation")
    assert_contains(route_frontend_chats, "'source_subtype': 'group_collaboration_conversation_attachment'", "group collaboration metadata subtype")
    assert_contains(route_frontend_chats, "'chat_upload_group_id': group_upload_target.get('id')", "group id source metadata")
    assert_contains(route_frontend_chats, "'scope': workspace_scope", "workspace attachment scope metadata")
    assert_contains(route_frontend_chats, "f'{workspace_scope}_workspace'", "scope-specific upload source metadata")
    assert_contains(route_frontend_chats, "This file type is not supported for group workspace chat uploads.", "group unsupported file rejection")
    assert_contains(route_frontend_chats, "File could not be queued in the {workspace_upload_scope} workspace", "scope-specific queue failure")
    assert_contains(route_frontend_chats, "workspace_url = (\n                        f\"/group_workspaces?document_id=", "group workspace document URL")


def test_frontend_group_upload_picker_contract():
    """Validate the frontend derives group targets and never offers personal workspace as a group upload destination."""
    chat_input_actions = read_repo_file("application/single_app/static/js/chat/chat-input-actions.js")

    assert_contains(chat_input_actions, "import { getEffectiveScopes } from \"./chat-documents.js\";", "effective scope import")
    assert_contains(chat_input_actions, "const GROUP_UPLOAD_ROLES = new Set([\"Owner\", \"Admin\", \"DocumentManager\"])", "client role allowlist")
    assert_contains(chat_input_actions, "window.activeChatTabType === \"group\"", "active group tab detection")
    assert_contains(chat_input_actions, "getCollaborationGroupId()", "group collaboration context detection")
    assert_contains(chat_input_actions, "if (!scopes?.personal)", "group-only effective scope detection")
    assert_contains(chat_input_actions, "Choose Group Workspace", "group destination modal title")
    assert_contains(chat_input_actions, "group-upload-target-modal", "group destination modal element")
    assert_contains(chat_input_actions, "new bootstrap.Modal(modalEl)", "Bootstrap modal picker")
    assert_contains(chat_input_actions, "formData.append(\"group_upload_target_id\", groupUploadContext.selectedGroupId)", "selected target form field")
    assert_contains(chat_input_actions, "formData.append(\"upload_scope_group_ids\", groupId)", "effective group scope form field")
    assert_not_contains(chat_input_actions, "personal workspace", "personal workspace option in group upload picker")


def test_group_uploaded_documents_are_linked_to_chat_search_and_delete_contract():
    """Validate linked chat-upload document lookup includes group workspace documents."""
    functions_documents = read_repo_file("application/single_app/functions_documents.py")
    route_backend_chats = read_repo_file("application/single_app/route_backend_chats.py")

    assert_contains(functions_documents, "cosmos_group_documents_container.query_items", "group linked document query")
    assert_contains(functions_documents, "get_user_role_in_group(group_docs_by_id.get(group_id), user_id)", "group membership visibility filter")
    assert_contains(functions_documents, "document_item['workspace_scope'] = 'group'", "group linked document scope marker")
    assert_contains(functions_documents, "'workspace_scope': document_item.get('workspace_scope')", "linked document serializer scope field")
    assert_contains(functions_documents, "'group_id': document_item.get('group_id')", "linked document serializer group id")
    assert_contains(functions_documents, "group_id=document_item.get('group_id')", "conversation delete passes group id to document deletion")
    assert_contains(route_backend_chats, "linked_document_scopes.add('group' if document_item.get('group_id') else 'personal')", "chat search detects group linked docs")
    assert_contains(route_backend_chats, "if normalized_scope == 'group' or linked_document_scopes == {'group'}", "chat search preserves group scope")


def test_version_contract():
    """Validate the implementation version was bumped consistently."""
    config = read_repo_file("application/single_app/config.py")
    assert_contains(config, 'VERSION = "0.241.176"', "application version bump")


def main():
    tests = [
        test_group_workspace_queue_helper_contract,
        test_upload_route_group_scope_contract,
        test_frontend_group_upload_picker_contract,
        test_group_uploaded_documents_are_linked_to_chat_search_and_delete_contract,
        test_version_contract,
    ]

    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\nResults: {passed}/{total} tests passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
