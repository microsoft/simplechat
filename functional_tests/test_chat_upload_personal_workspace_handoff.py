# test_chat_upload_personal_workspace_handoff.py
"""
Functional test for chat upload personal workspace handoff.
Version: 0.241.209
Implemented in: 0.241.203; expanded in: 0.241.207, 0.241.208, and 0.241.209

This test ensures chat uploads are wired to queue personal workspace documents,
replace eligible chat-local file processing with workspace-backed messages,
automatically search ready linked workspace documents, display processing
progress, enable the user workspace context as soon as workspace processing
starts, auto-select the completed workspace document, and warn on
conversation-linked workspace document deletion. It also
validates selectable linked-document deletion from the conversation delete modal,
including when conversation archiving is enabled,
duplicate workspace filename isolation for repeated chat uploads, and clean
workspace tagging that keeps conversation IDs in metadata instead of tags. It
also validates that chat upload progress can refresh from the workspace document
and that assigned-knowledge chats treat ready linked uploads as explicit
conversation task documents for allowed Search and Analyze actions. It also
validates that assigned knowledge stays separate from task documents, is searched
as top-12 reference context for Search, Analyze, and Compare, and does not let
Search answer from assigned knowledge alone while uploaded task documents are
still processing. It also validates that auto-linked uploads cannot broaden
search into other users' personal workspace documents and that chat document
actions cannot use unauthorized group or public workspace scope ids.
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


def assert_order(content, earlier, later, description):
    earlier_index = content.find(earlier)
    later_index = content.find(later)
    if earlier_index == -1:
        raise AssertionError(f"Missing earlier marker for {description}: {earlier}")
    if later_index == -1:
        raise AssertionError(f"Missing later marker for {description}: {later}")
    if earlier_index >= later_index:
        raise AssertionError(f"Expected {description}: {earlier} before {later}")


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
    assert_contains(route_frontend_chats, "File could not be queued in the {workspace_upload_scope} workspace", "workspace queue failure does not silently use legacy chat storage")
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
    assert_contains(route_backend_chats, "def _resolve_conversation_task_documents(", "action-aware linked task document resolver")
    assert_contains(route_backend_chats, "def _merge_document_scope_with_conversation_task_documents", "task document scope merge helper")
    assert_contains(route_backend_chats, "get_chat_upload_workspace_documents_for_conversation(user_id, normalized_conversation_id)", "linked workspace document lookup")
    assert_contains(route_backend_chats, "assigned_knowledge_user_context_active", "assigned knowledge user context merge switch")
    assert_contains(route_backend_chats, "assigned_knowledge_action_not_allowed", "assigned knowledge linked-upload backend activation guard")
    assert_contains(route_backend_chats, "document_action_type=DOCUMENT_ACTION_TYPE_NONE", "search action policy used for normal chat linked uploads")
    assert_contains(route_backend_chats, "_assigned_knowledge_allows_document_action(", "assigned knowledge policy check for linked chat uploads")
    assert_contains(route_backend_chats, "assigned_knowledge_user_context_active = True", "auto-linked uploads activate assigned knowledge user context")
    assert_contains(route_backend_chats, "g.assigned_knowledge_user_context_active = True", "request context reflects auto-linked assigned knowledge user context")
    assert_contains(route_backend_chats, "Enabled Assigned Knowledge user context", "debug log for linked chat upload user context activation")
    assert_contains(route_backend_chats, "base_document_ids = []", "assigned knowledge ids excluded from uploaded task document merge")
    assert_contains(route_backend_chats, "merged_scope_source = next(iter(linked_scope_set))", "auto-linked task search uses linked document scope instead of assigned knowledge scope")
    assert_contains(route_backend_chats, "search_args[\"enable_file_sharing\"] = False", "normal search disables shared personal docs for auto-linked uploads")
    assert_contains(route_backend_chats, "search_args['enable_file_sharing'] = False", "streaming search disables shared personal docs for auto-linked uploads")
    assert_contains(route_backend_chats, "def _merge_assigned_knowledge_user_context_search_results", "assigned knowledge user-context preserving search merge helper")
    assert_contains(route_backend_chats, "_is_personal_or_group_search_result(result, user_id=user_id)", "assigned knowledge merge filters user-context hits by current user")
    assert_contains(route_backend_chats, "result_user_id == normalized_user_id", "personal user-context results must belong to current user")
    assert_contains(route_backend_chats, "user_id=user_id,", "assigned knowledge merge receives current user id")
    assert_contains(route_backend_chats, "user_context_appended_count += 1", "assigned knowledge merge keeps appended user-context result count")
    assert_contains(route_backend_chats, "user_context_appended=", "assigned knowledge merge logs appended user-context hits")
    assert_not_contains(route_backend_chats, ")[:top_n]\n                        else:\n                            search_results = assigned_search_results", "assigned knowledge merge must not slice off user-context hits after merge")
    assert_not_contains(route_backend_chats, ")[:12]\n                            else:\n                                search_results = assigned_search_results", "streaming assigned knowledge merge must not slice off user-context hits after merge")
    assert_contains(route_backend_chats, "indexed_chunk_count <= 0", "unindexed linked document exclusion")
    assert_occurs_at_least(route_backend_chats, "auto_linked_chat_upload_document_ids", 6, "auto-linked document metadata and merge usage")
    assert_occurs_at_least(route_backend_chats, "original_hybrid_search_enabled = True", 2, "history fallback suppression for auto-linked documents")
    assert_contains(route_backend_chats, "'auto_linked_chat_upload_document_ids'", "auto-linked document metadata recording")


def test_analyze_uses_conversation_task_documents_contract():
    """Validate Analyze can target ready linked uploads without unlocked broad scopes."""
    route_backend_chats = read_repo_file("application/single_app/route_backend_chats.py")
    chat_messages = read_repo_file("application/single_app/static/js/chat/chat-messages.js")
    chat_documents = read_repo_file("application/single_app/static/js/chat/chat-documents.js")

    assert_contains(route_backend_chats, "conversation_task_document_ids", "backend accepts task document hint ids")
    assert_contains(route_backend_chats, "document_action_type=DOCUMENT_ACTION_TYPE_ANALYZE", "Analyze action policy used for linked uploads")
    assert_contains(route_backend_chats, "Auto-filled Analyze targets from linked chat uploads", "Analyze autofill debug log")
    assert_contains(route_backend_chats, "Uploaded task documents are still processing", "Analyze pending-upload response")
    assert_contains(route_backend_chats, "This agent does not allow document analysis with uploaded task documents", "Analyze assigned-knowledge denial")
    assert_order(
        route_backend_chats,
        "Auto-filled Analyze targets from linked chat uploads",
        "normalized_action = normalize_document_action_config(",
        "linked task document autofill before document-action validation",
    )

    assert_contains(chat_documents, "conversationTaskDocumentsByConversationId", "frontend task document state map")
    assert_contains(chat_documents, "export function registerConversationTaskDocument", "frontend task document registration")
    assert_contains(chat_documents, "export function updateConversationTaskDocumentsFromMessages", "frontend task document reload hydration")
    assert_contains(chat_documents, "export function getConversationTaskDocumentSummary", "frontend task document preflight summary")
    assert_contains(chat_documents, "canUseConversationTaskDocumentsForAction", "assigned-knowledge task action policy mirror")
    assert_contains(chat_messages, "conversation_task_document_ids: conversationTaskDocumentIds", "request payload includes task document hints")
    assert_contains(chat_messages, "updateConversationTaskDocumentsFromMessages", "loaded messages hydrate task docs")
    assert_contains(chat_messages, "conversationTaskDocumentSummary.readyCount", "Analyze preflight accepts ready task docs")
    assert_contains(chat_messages, "Uploaded task documents are still processing", "Analyze pending task document warning")
    assert_contains(chat_messages, "This agent does not allow uploaded task documents for analysis", "Analyze disallowed task document warning")


def test_assigned_knowledge_context_is_separate_from_task_documents_contract():
    """Validate assigned knowledge is searched as reference context, not task docs."""
    route_backend_chats = read_repo_file("application/single_app/route_backend_chats.py")

    assert_contains(route_backend_chats, "ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N = 12", "assigned knowledge top-12 context constant")
    assert_contains(route_backend_chats, "def _build_assigned_knowledge_reference_context(", "assigned knowledge reference search helper")
    assert_contains(route_backend_chats, "top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N", "assigned knowledge search uses fixed top-12 cap")
    assert_contains(route_backend_chats, "metadata_type='assigned_knowledge_context'", "assigned knowledge context citation marker")
    assert_contains(route_backend_chats, "assigned_knowledge_context_citations", "assigned knowledge citations retained for action responses")
    assert_contains(route_backend_chats, "hybrid_citations_list.extend(assigned_knowledge_context_citations)", "action citations include assigned knowledge references")
    assert_contains(route_backend_chats, "def _build_document_action_prompt_with_assigned_knowledge_context(", "document-action prompt enrichment helper")
    assert_contains(route_backend_chats, "Do not treat these assigned-knowledge excerpts as task documents", "assigned context is not analyzed as task corpus")
    assert_contains(route_backend_chats, "workflow_task_prompt = _build_document_action_prompt_with_assigned_knowledge_context", "action runner receives enriched prompt")
    assert_contains(route_backend_chats, "'assigned_knowledge_context': assigned_context_metadata", "assigned context metadata is stored with action response")
    assert_contains(route_backend_chats, "def _resolve_chat_upload_workspace_context(", "chat upload context state helper")
    assert_occurs_at_least(route_backend_chats, "candidate_document_ids=data.get('conversation_task_document_ids')", 2, "normal and streaming search respect task document hints")
    assert_contains(route_backend_chats, "'pending_document_ids': []", "pending linked upload ids tracked for guard decisions")
    assert_contains(route_backend_chats, "def _build_chat_upload_pending_response_payload", "pending upload response helper")
    assert_contains(route_backend_chats, "def _has_nonpending_requested_task_document_selection", "pending guard allows explicit non-pending task selections")
    assert_occurs_at_least(route_backend_chats, "_build_chat_upload_pending_response_payload(task_resolution)", 2, "normal and streaming search block pending-only uploads")
    assert_contains(route_backend_chats, "This agent does not allow uploaded task documents for search.", "search policy denial for blocked uploaded task docs")


def test_document_action_scope_authorization_contract():
    """Validate document actions and related tabular evidence use authorized scopes."""
    route_backend_chats = read_repo_file("application/single_app/route_backend_chats.py")
    functions_search_service = read_repo_file("application/single_app/functions_search_service.py")

    assert_contains(route_backend_chats, "requested_action_group_ids = _normalize_requested_scope_ids", "document action normalizes requested group ids")
    assert_contains(route_backend_chats, "requested_action_public_workspace_ids = _normalize_requested_scope_ids", "document action normalizes requested public workspace ids")
    assert_contains(route_backend_chats, "action_scope_context = _get_authorized_chat_scope_context(", "document action revalidates group/public scopes")
    assert_contains(route_backend_chats, "unauthorized_group_ids = [", "document action detects unauthorized groups")
    assert_contains(route_backend_chats, "unauthorized_public_workspace_ids = [", "document action detects unauthorized public workspaces")
    assert_contains(route_backend_chats, "You do not have access to one or more selected workspaces.", "document action rejects unauthorized scopes")
    assert_contains(route_backend_chats, "normalized_action['active_group_ids'] = action_scope_context.get('active_group_ids', [])", "document action replaces group ids with authorized group ids")
    assert_contains(route_backend_chats, "normalized_action['active_public_workspace_id'] = action_scope_context.get('active_public_workspace_ids', [])", "document action replaces public workspace ids with authorized public ids")
    assert_contains(route_backend_chats, "doc_info = _resolve_chat_selected_document_metadata(", "document action selected metadata uses safe resolver")
    assert_contains(route_backend_chats, "active_group_ids=active_group_ids,", "document action metadata resolver receives authorized group ids")
    assert_contains(route_backend_chats, "active_public_workspace_ids=active_public_workspace_ids,", "document action metadata resolver receives authorized public ids")
    assert_not_contains(route_backend_chats, "'FROM c WHERE c.id = @doc_id '\n                    'ORDER BY c.version DESC'", "document action unscoped metadata lookup")
    assert_contains(route_backend_chats, "authorized_group_ids = _normalize_requested_scope_ids(authorized_context.get('active_group_ids'))", "tabular related-document scope uses authorized group ids")
    assert_contains(route_backend_chats, "authorized_public_workspace_ids = _normalize_requested_scope_ids(", "tabular related-document scope uses authorized public workspace ids")
    assert_contains(route_backend_chats, "if resolved_group_id not in authorized_group_ids:", "tabular related-document rejects unauthorized group id")
    assert_contains(route_backend_chats, "if resolved_public_workspace_id not in authorized_public_workspace_ids:", "tabular related-document rejects unauthorized public workspace id")

    assert_contains(functions_search_service, "def _get_user_accessible_group_ids(user_id):", "search service group access helper")
    assert_contains(functions_search_service, "authorized_group_ids = set(accessible_group_ids)", "search service builds authorized group set")
    assert_contains(functions_search_service, "return [group_id for group_id in requested_group_ids if group_id in authorized_group_ids]", "search service intersects requested group ids")
    assert_contains(functions_search_service, "visible_workspace_id_set = set(visible_workspace_ids)", "search service builds visible public workspace set")
    assert_contains(functions_search_service, "if workspace_id in visible_workspace_id_set", "search service intersects requested public workspace ids")


def test_frontend_progress_and_workspace_notices_contract():
    """Validate chat progress UI and workspace linked-conversation notices."""
    chat_input_actions = read_repo_file("application/single_app/static/js/chat/chat-input-actions.js")
    chat_documents = read_repo_file("application/single_app/static/js/chat/chat-documents.js")
    chat_messages = read_repo_file("application/single_app/static/js/chat/chat-messages.js")
    workspace_documents = read_repo_file("application/single_app/static/js/workspace/workspace-documents.js")
    workspace_template = read_repo_file("application/single_app/templates/workspace.html")

    assert_contains(chat_input_actions, "watchChatWorkspaceUploadDocument", "upload response starts workspace completion watcher")
    assert_contains(chat_input_actions, "data.workspace_document_id", "upload response workspace document id consumed by client")
    assert_contains(chat_input_actions, "registerConversationTaskDocument({", "upload response registers pending task document")
    assert_contains(chat_input_actions, "activateUserWorkspaceContextForChatUpload();", "upload success immediately enables user workspace context")
    assert_contains(chat_input_actions, "workspaceScope: data.workspace_scope", "upload response passes workspace scope to completion watcher")
    assert_contains(chat_input_actions, "groupId: data.workspace_document?.group_id", "upload response passes group id to completion watcher")

    assert_contains(chat_documents, "export function activateUserWorkspaceContextForChatUpload", "chat upload user workspace context activation helper")
    assert_contains(chat_documents, "export async function selectWorkspaceDocumentForChatUpload", "chat upload completed document selection helper")
    assert_contains(chat_documents, "userWorkspaceContextActive = true", "workspace context activated for workspace-backed upload")
    assert_contains(chat_documents, "workspaceScope === 'group'", "completed group upload scope handling")
    assert_contains(chat_documents, "groupIds: [...currentScopes.groupIds, groupId]", "completed group upload adds group scope")
    assert_contains(chat_documents, "applyDocumentSelectionForIds([normalizedDocumentId]", "completed upload document selection by id")
    assert_contains(chat_documents, "replaceSelection: options.replaceSelection !== false", "completed upload replaces document picker selection by default")

    assert_contains(chat_messages, "chat-workspace-upload-progress", "chat workspace progress container")
    assert_contains(chat_messages, "const statusEndpoint = workspaceScope === 'group'", "chat progress polling chooses endpoint by workspace scope")
    assert_contains(chat_messages, "`/api/group_documents/${encodeURIComponent(workspaceDocumentId)}`", "group chat upload progress polling endpoint")
    assert_contains(chat_messages, "`/api/documents/${encodeURIComponent(workspaceDocumentId)}`", "personal chat upload progress polling endpoint")
    assert_contains(chat_messages, "function normalizeChatWorkspaceDocumentResponse", "chat progress document response normalizer")
    assert_contains(chat_messages, "then(payload => normalizeChatWorkspaceDocumentResponse(payload))", "chat progress polling uses normalized document payload")
    assert_contains(chat_messages, "export function watchChatWorkspaceUploadDocument", "upload completion watcher exported for upload response flow")
    assert_contains(chat_messages, "chatWorkspaceUploadCompletionWatchers", "dedicated upload completion watcher state")
    assert_contains(chat_messages, "registerConversationTaskDocument({", "upload completion watcher records task document state")
    assert_contains(chat_messages, "activateUserWorkspaceContextForChatUpload();", "workspace-backed upload immediately activates context")
    assert_contains(chat_messages, "selectWorkspaceDocumentForChatUpload(workspaceDocumentId", "completed upload auto-selects workspace document")
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
    assert_contains(functions_documents, "delete_document_revision(\n                user_id,\n                document_id,\n                delete_mode='all_versions'", "workspace document cleanup deletion")
    assert_contains(route_backend_conversations, "\"linked_workspace_documents\": linked_workspace_documents", "metadata linked document list")
    assert_contains(route_backend_conversations, "delete_workspace_document_ids = _get_requested_workspace_document_delete_ids_for_conversation", "selected document payload parsing")
    assert_contains(route_backend_conversations, "if delete_workspace_document_ids:", "selected document deletion guard")
    assert_contains(route_backend_conversations, "selected_document_ids=delete_workspace_document_ids", "selected document IDs passed to cleanup helper")
    assert_order(
        route_backend_conversations,
        "if delete_workspace_document_ids:",
        "if not archiving_enabled:\n            delete_blob_backed_chat_message_files(results)",
        "selected workspace document deletion before archive-mode chat blob cleanup guard",
    )
    assert_not_contains(route_backend_conversations, "[ConversationBulkDelete] Failed to delete linked workspace documents", "bulk automatic linked document cleanup")
    assert_contains(chat_conversations, "getSelectedDeleteConversationLinkedDocumentIds", "conversation delete selected document collector")
    assert_contains(chat_conversations, "delete_workspace_document_ids: getSelectedDeleteConversationLinkedDocumentIds()", "delete payload selected document IDs")
    assert_contains(chats_template, "delete-conversation-linked-documents-container", "conversation delete linked documents modal section")
    assert_contains(route_backend_documents, "conversation_linked_document_delete_requires_confirmation", "workspace delete guard response")


def main():
    tests = [
        test_backend_handoff_contract,
        test_chat_search_includes_ready_linked_workspace_documents_contract,
        test_analyze_uses_conversation_task_documents_contract,
        test_assigned_knowledge_context_is_separate_from_task_documents_contract,
        test_document_action_scope_authorization_contract,
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