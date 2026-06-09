# test_chat_upload_personal_workspace_handoff.py
"""
Functional test for chat upload personal workspace handoff.
Version: 0.241.174
Implemented in: 0.241.174

This test ensures chat uploads are wired to queue personal workspace documents,
replace eligible chat-local file processing with workspace-backed messages,
automatically search ready linked workspace documents, display processing
progress, auto-select the completed workspace document, and warn on
conversation-linked workspace document deletion. It also
validates selectable linked-document deletion from the conversation delete modal,
duplicate workspace filename isolation for repeated chat uploads, and clean
workspace tagging that keeps conversation IDs in metadata instead of tags. It
also validates that chat upload progress can refresh from the workspace document.
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


def assert_occurs_at_least(content, expected, count, description):
    actual_count = content.count(expected)
    if actual_count < count:
        raise AssertionError(
            f"Expected at least {count} occurrences of {description}, found {actual_count}: {expected}"
        )


def test_backend_handoff_contract():
    """Validate chat upload queues personal workspace processing with conversation tags."""
    functions_documents = read_repo_file("application/single_app/functions_documents.py")
    route_frontend_chats = read_repo_file("application/single_app/route_frontend_chats.py")

    assert_contains(functions_documents, 'CHAT_UPLOAD_WORKSPACE_TAG = "conversations"', "plural conversations tag constant")
    assert_contains(functions_documents, "return [CHAT_UPLOAD_WORKSPACE_TAG]", "chat upload only applies conversations tag")
    assert_not_contains(functions_documents, "tags.append(normalized_conversation_id)", "conversation ID workspace tag append")
    assert_contains(functions_documents, "def queue_personal_workspace_upload_from_temp_file(", "workspace upload queue helper")
    assert_contains(functions_documents, "process_document_upload_background", "workspace background processor queue")
    assert_contains(functions_documents, "get_or_create_tag_definition(user_id, tag, workspace_type='personal')", "tag definition creation")
    assert_contains(functions_documents, "current_app.extensions.get('executor')", "workspace helper uses configured Flask executor extension")
    assert_contains(functions_documents, "cosmos_user_documents_container.delete_item", "orphan queued metadata cleanup")
    assert_contains(functions_documents, "def resolve_unique_personal_workspace_file_name", "unique personal workspace filename resolver")
    assert_contains(functions_documents, "SELECT TOP 1 VALUE c.id", "unique filename collision query")
    assert_contains(functions_documents, "chat_upload_workspace_filename", "workspace filename metadata preservation")
    assert_contains(functions_documents, "source_original_file_name", "original filename metadata preservation")
    assert_contains(functions_documents, "def sync_chat_upload_workspace_attachment_status", "chat message workspace attachment status sync helper")
    assert_contains(functions_documents, "cosmos_messages_container.read_item", "chat message status sync reads linked message")
    assert_contains(functions_documents, "workspace_attachment.update", "chat message workspace attachment status update")
    assert_contains(functions_documents, "container_type='personal'", "chat workspace upload activity logging signature")
    assert_not_contains(functions_documents, "workspace_type='personal',\n                file_name=workspace_file_name", "invalid chat workspace upload activity logging arguments")

    assert_contains(route_frontend_chats, "queue_personal_workspace_upload_from_temp_file(", "chat route workspace handoff call")
    assert_contains(route_frontend_chats, "tags=build_chat_upload_workspace_tags(conversation_id)", "conversation tags passed to helper")
    assert_contains(route_frontend_chats, "'conversation_id': conversation_id", "conversation id stored as metadata")
    assert_contains(route_frontend_chats, "'created_from_chat_upload': True", "workspace source metadata")
    assert_contains(route_frontend_chats, "copy_source_file=True", "separate temp copy for background processing")
    assert_contains(route_frontend_chats, "ensure_unique_file_name=True", "chat upload requests unique workspace filenames")
    assert_contains(route_frontend_chats, "unique_file_name_suffix=file_message_id", "chat upload identity suffix for duplicate filenames")
    assert_contains(route_frontend_chats, "File could not be queued in the personal workspace", "workspace queue failure does not silently use legacy chat storage")
    assert_contains(route_frontend_chats, "'file_content_source': 'workspace'", "workspace-backed chat upload message")
    assert_contains(route_frontend_chats, "'workspace_document_id': workspace_document_info.get('document_id')", "chat message workspace document id")
    assert_contains(route_frontend_chats, "['metadata']['workspace_attachment'] = workspace_attachment", "chat message workspace attachment metadata")
    assert_contains(route_frontend_chats, "'workspace_document_id':", "upload response workspace document id")
    assert_contains(route_frontend_chats, "'filename': workspace_file_name", "chat message displays resolved workspace filename")
    workspace_message_index = route_frontend_chats.index("'file_content_source': 'workspace'")
    legacy_processing_index = route_frontend_chats.index("extracted_content  = ''")
    if workspace_message_index > legacy_processing_index:
        raise AssertionError("Workspace-backed upload message must be created before legacy chat extraction fallback")


def test_chat_search_includes_ready_linked_workspace_documents_contract():
    """Validate ready linked workspace documents are merged into chat search context."""
    route_backend_chats = read_repo_file("application/single_app/route_backend_chats.py")

    assert_contains(route_backend_chats, "def _merge_chat_upload_workspace_context(", "chat-upload workspace context helper")
    assert_contains(route_backend_chats, "def _is_search_ready_chat_upload_workspace_document", "search-ready linked document guard")
    assert_contains(route_backend_chats, "get_chat_upload_workspace_documents_for_conversation(user_id, conversation_id)", "linked workspace document lookup")
    assert_contains(route_backend_chats, "indexed_chunk_count <= 0", "unindexed linked document exclusion")
    assert_occurs_at_least(route_backend_chats, "auto_linked_chat_upload_document_ids", 6, "auto-linked document metadata and merge usage")
    assert_occurs_at_least(route_backend_chats, "original_hybrid_search_enabled = True", 2, "history fallback suppression for auto-linked documents")
    assert_contains(route_backend_chats, "'auto_linked_chat_upload_document_ids'", "auto-linked document metadata recording")


def test_frontend_progress_and_workspace_notices_contract():
    """Validate chat progress UI and workspace linked-conversation notices."""
    chat_input_actions = read_repo_file("application/single_app/static/js/chat/chat-input-actions.js")
    chat_documents = read_repo_file("application/single_app/static/js/chat/chat-documents.js")
    chat_messages = read_repo_file("application/single_app/static/js/chat/chat-messages.js")
    workspace_documents = read_repo_file("application/single_app/static/js/workspace/workspace-documents.js")
    workspace_template = read_repo_file("application/single_app/templates/workspace.html")

    assert_contains(chat_input_actions, "watchChatWorkspaceUploadDocument", "upload response starts workspace completion watcher")
    assert_contains(chat_input_actions, "data.workspace_document_id", "upload response workspace document id consumed by client")

    assert_contains(chat_documents, "export async function selectPersonalWorkspaceDocumentForChatUpload", "chat upload completed document selection helper")
    assert_contains(chat_documents, "userWorkspaceContextActive = true", "workspace context activated for completed upload selection")
    assert_contains(chat_documents, "applyDocumentSelectionForIds([normalizedDocumentId]", "completed upload document selection by id")
    assert_contains(chat_documents, "replaceSelection: options.replaceSelection !== false", "completed upload replaces document picker selection by default")

    assert_contains(chat_messages, "chat-workspace-upload-progress", "chat workspace progress container")
    assert_contains(chat_messages, "fetch(`/api/documents/${encodeURIComponent(workspaceDocumentId)}`", "chat progress polling endpoint")
    assert_contains(chat_messages, "function normalizeChatWorkspaceDocumentResponse", "chat progress document response normalizer")
    assert_contains(chat_messages, "then(payload => normalizeChatWorkspaceDocumentResponse(payload))", "chat progress polling uses normalized document payload")
    assert_contains(chat_messages, "export function watchChatWorkspaceUploadDocument", "upload completion watcher exported for upload response flow")
    assert_contains(chat_messages, "chatWorkspaceUploadCompletionWatchers", "dedicated upload completion watcher state")
    assert_contains(chat_messages, "selectPersonalWorkspaceDocumentForChatUpload(workspaceDocumentId", "completed upload auto-selects personal workspace document")
    assert_contains(chat_messages, "buildCompletedChatWorkspaceAttachmentHtml", "completed progress details collapsed renderer")
    assert_contains(chat_messages, "chat-workspace-progress-toggle", "completed progress details expand control")
    assert_contains(chat_messages, "progress flex-grow-1", "in-progress card keeps progress bar visible next to details toggle")
    assert_contains(chat_messages, "chat-workspace-upload-progress-details d-none mt-1 small text-muted", "in-progress status details are collapsed by default")
    assert_contains(chat_messages, "container.dataset.workspaceUploadComplete = 'true'", "completed progress container skips live polling")
    assert_contains(chat_messages, "classList.toggle('d-none', isExpanded)", "completed progress details are hidden with Bootstrap d-none")
    assert_not_contains(chat_messages, "<a class=\"small\" href=\"${escapeHtml(workspaceUrl)}\">Workspace</a>", "duplicate workspace link in progress card")
    assert_contains(chat_messages, "disconnectedPolls > 1", "chat progress polling tolerates initial detached render")
    assert_contains(chat_messages, "if (error?.isPermanent)", "chat progress polling only stops for permanent errors")
    assert_contains(chat_messages, "statusElement.classList.remove('text-warning')", "chat progress polling clears transient warning on success")
    assert_contains(chat_messages, "progressBar.classList.remove('bg-warning')", "chat progress polling clears transient progress warning on success")
    assert_contains(chat_messages, "hydrateChatWorkspaceAttachmentProgress(messageDiv)", "progress hydration after message render")
    assert_contains(chat_messages, "workspace-file-link", "workspace-backed chat file link")
    assert_contains(chat_messages, "file_content_source || '').trim().toLowerCase() === 'workspace'", "workspace-backed file click branch")

    assert_contains(workspace_template, "doc-conversation-link-status", "metadata modal conversation link placeholder")
    assert_contains(workspace_documents, "setDocumentConversationStatusElement", "metadata modal conversation link renderer")
    assert_contains(workspace_documents, "conversation_linked_document_delete_requires_confirmation", "linked delete confirmation handler")
    assert_contains(workspace_documents, "conversation_linked_delete_confirmed", "linked delete confirmation query flag")


def test_conversation_delete_selectable_workspace_document_contract():
    """Validate conversation delete lists and selectively deletes linked workspace documents."""
    functions_documents = read_repo_file("application/single_app/functions_documents.py")
    route_backend_conversations = read_repo_file("application/single_app/route_backend_conversations.py")
    route_backend_documents = read_repo_file("application/single_app/route_backend_documents.py")
    chat_conversations = read_repo_file("application/single_app/static/js/chat/chat-conversations.js")
    chats_template = read_repo_file("application/single_app/templates/chats.html")

    assert_contains(functions_documents, "def delete_chat_upload_workspace_documents_for_conversation", "conversation cleanup helper")
    assert_contains(functions_documents, "def serialize_chat_upload_workspace_documents_for_conversation", "conversation delete document list serializer")
    assert_contains(functions_documents, "c.created_from_chat_upload = true", "chat-upload workspace document query")
    assert_contains(functions_documents, "if not selected_document_id_set:", "empty selection retains linked documents")
    assert_contains(functions_documents, "delete_document_revision(user_id, document_id, delete_mode='all_versions')", "workspace document cleanup deletion")
    assert_contains(route_backend_conversations, "\"linked_workspace_documents\": linked_workspace_documents", "metadata linked document list")
    assert_contains(route_backend_conversations, "delete_workspace_document_ids = _get_requested_workspace_document_delete_ids_for_conversation", "selected document payload parsing")
    assert_contains(route_backend_conversations, "if delete_workspace_document_ids:", "selected document deletion guard")
    assert_contains(route_backend_conversations, "selected_document_ids=delete_workspace_document_ids", "selected document IDs passed to cleanup helper")
    assert_not_contains(route_backend_conversations, "[ConversationBulkDelete] Failed to delete linked workspace documents", "bulk automatic linked document cleanup")
    assert_contains(chat_conversations, "getSelectedDeleteConversationLinkedDocumentIds", "conversation delete selected document collector")
    assert_contains(chat_conversations, "delete_workspace_document_ids: getSelectedDeleteConversationLinkedDocumentIds()", "delete payload selected document IDs")
    assert_contains(chats_template, "delete-conversation-linked-documents-container", "conversation delete linked documents modal section")
    assert_contains(route_backend_documents, "conversation_linked_document_delete_requires_confirmation", "workspace delete guard response")


def main():
    tests = [
        test_backend_handoff_contract,
        test_chat_search_includes_ready_linked_workspace_documents_contract,
        test_frontend_progress_and_workspace_notices_contract,
        test_conversation_delete_selectable_workspace_document_contract,
    ]

    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(tests)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)