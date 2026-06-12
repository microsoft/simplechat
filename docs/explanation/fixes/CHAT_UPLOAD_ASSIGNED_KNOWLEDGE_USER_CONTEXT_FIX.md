# Chat Upload Assigned Knowledge User Context Fix

Version: 0.241.198

Fixed/Implemented in version: **0.241.198**

Related config.py update: `VERSION = "0.241.198"`

## Header Information

- Issue description: Workspace-backed files uploaded in chat could appear as added file messages, but an Assigned Knowledge agent that allowed user workspace context did not always search those uploaded documents on the next prompt.
- Root cause analysis: The chat upload completion watcher only selected the workspace document after processing completed, and the request payload depended on a separate user workspace context toggle. If the user sent a message before that auto-selection completed, assigned knowledge filters stayed active while the uploaded workspace document was omitted.
- Version implemented: 0.241.198

## Technical Details

- Files modified: `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/js/chat/chat-messages.js`, `application/single_app/static/js/chat/chat-input-actions.js`, `application/single_app/config.py`, `functional_tests/test_chat_upload_personal_workspace_handoff.py`, `ui_tests/test_chat_workspace_upload_progress_polling.py`.
- Code changes summary: Added a chat-upload activation helper for user workspace context, generalized chat-upload document selection across personal and group workspace scopes, and passed workspace scope/group id through the upload watcher so progress polling and auto-selection use the correct workspace path.
- Testing approach: Updated functional contract tests for the upload handoff and UI polling test coverage to validate immediate context activation and scope-aware watcher behavior.
- Impact analysis: Agents with Assigned Knowledge and creator-approved user workspace context now include workspace-backed chat uploads as task context as soon as the upload is queued, while agents that do not allow user context still keep their assigned corpus locked.

## Validation

- Test results: `functional_tests/test_chat_upload_personal_workspace_handoff.py` validates the updated upload-to-workspace contract, and `ui_tests/test_chat_workspace_upload_progress_polling.py` validates the browser watcher behavior.
- Before/after comparison: Before the fix, the uploaded document could be present in the conversation but omitted from the next agent request until completion auto-selection succeeded. After the fix, the workspace-backed upload immediately enables user workspace context and carries scope through polling and selection.
- User experience improvements: Users can upload a file in chat and immediately ask an Assigned Knowledge agent about it when that agent permits user workspace task context.