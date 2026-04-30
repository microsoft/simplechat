# Chat Workspace Selection Reset Fix

## Fix Title
Implicit chat conversation creation now preserves selected workspace scope, tags, and documents.

## Issue Description
When a user arrived on the chat page with workspace context already selected, either by choosing documents manually or by coming from a workspace link that preselected scope, tags, or documents, clicking into the message input created a conversation and immediately reset the workspace filters back to their defaults.

## Root Cause Analysis

1. The chat bootstrap in `chat-onload.js` auto-created a conversation on first input focus when no conversation ID existed.
2. `createNewConversation()` in `chat-conversations.js` always called `resetScopeLock()` in full reset mode, which restored the scope dropdown to `All` and reloaded document and tag controls.
3. That full reset path rebuilt the document and tag UI in `chat-documents.js`, which cleared the preselected workspace context before the user sent the first message.

## Version Implemented
Fixed in version: **0.239.105**

## Files Modified

| File | Change |
|------|--------|
| `application/single_app/static/js/chat/chat-documents.js` | Added a preserve-selection mode to `resetScopeLock()` so lock state can be cleared without rebuilding current scope, tag, and document selections. |
| `application/single_app/static/js/chat/chat-conversations.js` | Added a `preserveSelections` option to `createNewConversation()` and reused in-flight create requests so implicit creation does not race duplicate conversations. |
| `application/single_app/static/js/chat/chat-onload.js` | Changed implicit auto-create entry points for input focus, prompt selection, and file selection to preserve current workspace filters. |
| `application/single_app/static/js/chat/chat-input-actions.js` | Updated file-upload auto-create flows to preserve workspace selections. |
| `application/single_app/static/js/chat/chat-messages.js` | Updated the first-send auto-create flow to preserve workspace selections. |
| `functional_tests/test_chat_preserves_workspace_selection_on_auto_create.py` | Added regression coverage for preserve-selection reset logic and implicit conversation creation call sites. |
| `application/single_app/config.py` | Version bump to `0.239.105`. |

## Code Changes Summary

### Preserve Selection State During Implicit Auto-Create
- Added an options-based preserve path to the scope reset helper so a new conversation can start unlocked without forcing the workspace picker back to `All`.
- Updated implicit conversation creation flows to request preserved selections.

### Prevent Duplicate Conversation Creation
- Reused a single in-flight create-conversation request so focus-triggered creation and an immediate send action do not create duplicate empty conversations.

### Keep Explicit Reset Behavior Intact
- Left the explicit `New Conversation` button on the default reset path so a deliberate fresh chat still restores default workspace scope.

## Testing Approach
- Added functional regression coverage in `functional_tests/test_chat_preserves_workspace_selection_on_auto_create.py`.
- Validates that `resetScopeLock()` supports a preserve-selection path.
- Validates that `createNewConversation()` preserves selections when requested and reuses a pending create request.
- Validates that implicit creation call sites in the chat bootstrap, first-send flow, and file upload flow all request preserved selections.

## Impact Analysis
- Users can now click into the message input and continue with the workspace, tag, and document filters they already chose.
- Workspace deep links remain stable through the first interaction instead of reverting to the default chat scope.
- Explicit new chat creation still resets to the default workspace scope, so existing fresh-start behavior remains available.

## Validation
- Before: first focus in the message box could silently reset workspace-related filters before the user sent a message.
- After: implicit conversation creation preserves the active workspace context, while explicit new chat creation keeps the full reset behavior.