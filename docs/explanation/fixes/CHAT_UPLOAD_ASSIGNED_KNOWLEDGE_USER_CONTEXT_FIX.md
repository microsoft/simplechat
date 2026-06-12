# Chat Upload Assigned Knowledge User Context Fix

Version: 0.241.200

Fixed/Implemented in version: **0.241.200**

Related config.py update: `VERSION = "0.241.200"`

## Header Information

- Issue description: Workspace-backed files uploaded in chat could appear as added file messages, but an Assigned Knowledge agent that allowed user workspace context did not always search those uploaded documents on the next prompt.
- Root cause analysis: The chat upload completion watcher only selected the workspace document after processing completed, and the request payload depended on a separate user workspace context toggle. In locked Assigned Knowledge conversations, the backend could still apply the agent's public workspace filters and leave `assigned_knowledge_user_context_active` false, so the linked personal workspace upload was omitted even though the agent policy allowed user task context. After enabling the backend user-context merge, the final search merge still sliced the combined result list back to the assigned corpus top-N, which could drop all personal/group upload chunks.
- Version implemented: 0.241.200

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/js/chat/chat-messages.js`, `application/single_app/static/js/chat/chat-input-actions.js`, `application/single_app/config.py`, `functional_tests/test_chat_upload_personal_workspace_handoff.py`, `ui_tests/test_chat_workspace_upload_progress_polling.py`.
- Code changes summary: Added a chat-upload activation helper for user workspace context, generalized chat-upload document selection across personal and group workspace scopes, passed workspace scope/group id through the upload watcher, hardened the backend merge so search-ready conversation-linked chat uploads activate Assigned Knowledge user context when the agent allows workspace search, and changed Assigned Knowledge search merging to keep the assigned corpus cap while appending all deduplicated personal/group user-context hits.
- Testing approach: Updated functional contract tests for the upload handoff, backend Assigned Knowledge merge activation, and the user-context result preservation behavior, plus UI polling test coverage to validate immediate context activation and scope-aware watcher behavior.
- Impact analysis: Agents with Assigned Knowledge and creator-approved user workspace context now include workspace-backed chat uploads as task context as soon as the upload is queued. The assigned corpus remains capped normally, while personal/group task-context chunks are preserved even when the combined citation count exceeds the usual top-N limit.

## Validation

- Test results: `functional_tests/test_chat_upload_personal_workspace_handoff.py` validates the updated upload-to-workspace contract, and `ui_tests/test_chat_workspace_upload_progress_polling.py` validates the browser watcher behavior.
- Before/after comparison: Before the fix, the uploaded document could be present in the conversation but omitted from the next agent request when Assigned Knowledge locked the effective search scope to public, or searched but dropped when assigned public results filled the top-N window. After the fix, the workspace-backed upload immediately enables user workspace context on the client, the backend auto-merges ready linked uploads as user task context when the agent policy allows it, and personal/group user-context chunks are appended after assigned results instead of being sliced away.
- User experience improvements: Users can upload a file in chat and immediately ask an Assigned Knowledge agent about it when that agent permits user workspace task context.