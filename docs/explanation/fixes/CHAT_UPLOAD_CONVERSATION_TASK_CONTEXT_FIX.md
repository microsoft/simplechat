# Chat Upload Conversation Task Context Fix

Version: 0.241.203

Fixed/Implemented in version: **0.241.203**

Related config.py update: `VERSION = "0.241.203"`

## Header Information

- Issue description: Assigned Knowledge conversations could ignore a document uploaded at the start of the chat, especially when the user selected Analyze before the workspace picker could select the processed upload.
- Root cause analysis: The existing upload merge was tied to normal search context and frontend scope selection. Analyze validated selected document IDs before resolving conversation-linked uploads, and the scope lock could prevent the uploaded personal document from appearing in the selected workspace scope even though the agent policy allowed user task documents.
- Version implemented: 0.241.203

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/js/chat/chat-messages.js`, `application/single_app/static/js/chat/chat-input-actions.js`, `functional_tests/test_chat_upload_personal_workspace_handoff.py`, `ui_tests/test_chat_workspace_upload_progress_polling.py`, `application/single_app/config.py`.
- Code changes summary: Added an action-aware conversation task document resolver for search-ready chat uploads, used it for normal Search and Analyze policy checks, auto-filled Analyze targets from ready linked uploads before document-action validation, and added frontend task-document state that survives scope lock and message reloads.
- Testing approach: Updated source-contract functional coverage for the backend resolver, assigned-knowledge policy gates, Analyze autofill, frontend task-document payloads, and pending/denied Analyze warnings; updated the upload polling UI test to validate completed uploads register as task documents.
- Impact analysis: Scope lock still prevents broad workspace browsing, but explicit files uploaded into the current conversation are available as task context when the selected agent allows the requested user workspace action.

## Validation

- Test results: `functional_tests/test_chat_upload_personal_workspace_handoff.py` covers the backend and frontend task-document contracts; `ui_tests/test_chat_workspace_upload_progress_polling.py` covers upload watcher task-document registration.
- Before/after comparison: Before the fix, upload-first Assigned Knowledge conversations could remain locked to public assigned sources and Analyze could fail with no selected documents. After the fix, ready conversation-linked uploads are resolved on the backend and can satisfy Analyze without unlocking the whole personal workspace.
- User experience improvements: Users can upload a task document to an Assigned Knowledge chat and ask for Search or Analyze behavior as long as the agent policy allows that action, with clearer warnings when the upload is still processing or the agent disallows uploaded task documents.
