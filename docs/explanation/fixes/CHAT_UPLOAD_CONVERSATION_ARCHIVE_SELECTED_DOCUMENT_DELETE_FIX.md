# Chat Upload Conversation Archive Selected Document Delete Fix

Fixed/Implemented in version: **0.241.192**

Related config.py update: `VERSION = "0.241.192"`

## Header Information

- Issue description: Deleting a chat conversation with conversation archiving enabled showed linked chat-upload workspace documents in the delete dialog, but checked documents were retained instead of deleted.
- Root cause analysis: The selected workspace-document cleanup was nested under the hard-delete-only `if not archiving_enabled` branch, so archive-enabled conversation deletes skipped the explicit checkbox selection.
- Version implemented: 0.241.192

## Technical Details

- Files modified: `application/single_app/route_backend_conversations.py`, `application/single_app/config.py`, `functional_tests/test_chat_upload_personal_workspace_handoff.py`, `docs/explanation/features/CHAT_UPLOAD_PERSONAL_WORKSPACE_HANDOFF.md`
- Code changes summary: Moved selected linked workspace-document cleanup ahead of the archive-mode chat blob cleanup guard. Conversation archiving still archives the conversation and messages, and selected workspace documents now follow the user's explicit delete choice.
- Testing approach: Updated the chat upload handoff functional contract test to assert selected document cleanup is not nested behind the non-archived delete guard.

## Validation

- Test results: Focused source-level regression coverage verifies the selected linked workspace-document cleanup runs before archive-mode-specific chat blob cleanup.
- Before/after comparison: Before the fix, checked linked files were retained whenever conversation archiving was enabled. After the fix, unselected files are retained by default and checked files are deleted through the normal workspace document deletion path.
- User experience improvements: The delete dialog now does what it says when a user checks a linked chat-uploaded file and deletes the conversation.
