# Chat New Conversation Action State Reset Fix

Fixed in version: **0.241.106**

## Issue Description

Starting a new chat did not consistently clear per-chat toolbar actions. Web Search and some other toolbar surfaces could remain visibly selected after clicking New Chat, while URL Access and Deep Research were already reset through a conversation context-change listener.

## Root Cause Analysis

The New Chat flow dispatched `chat:conversation-context-changed`, but only `chat-input-actions.js` listened to that event, and its reset only covered URL Access and Deep Research. Workspace search, prompt selection, Web Search, image generation, and pending file state were owned by separate modules or code paths and did not share a consistent reset contract.

## Version Implemented

Implemented in version: **0.241.106**

The application version was updated in `application/single_app/config.py` from `0.241.105` to `0.241.106` for this fix.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-input-actions.js`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-prompts.js`
- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `functional_tests/test_chat_new_conversation_action_state_reset.py`
- `functional_tests/test_chat_preserves_workspace_selection_on_auto_create.py`
- `ui_tests/test_chat_deep_research_toggle.py`
- `ui_tests/test_chat_new_conversation_tag_reset.py`

Code changes summary:

- Added a consistent conversation context reset for per-chat input actions: Web Search, URL Access, visible Deep Research state, image generation, and pending file selection.
- Added a workspace reset listener that hides the Workspaces panel, clears selected document/tag/action state, and keeps auto-created conversations able to preserve selections through `preserveSelections`.
- Added a prompt reset listener so the prompt picker does not stay open across explicit New Chat.
- Added a saved `deepResearchDefaultEnabled` preference so Deep Research can be restored when Web Search is opened or direct URLs are present, without programmatic New Chat resets overwriting that preference.
- Switched the Web Search notice container to Bootstrap `d-none` visibility so reset behavior is class-based.

## Testing Approach

- Added `functional_tests/test_chat_new_conversation_action_state_reset.py` to statically verify the reset listeners, Deep Research default preference, Web Search notice visibility, and version update.
- Updated `ui_tests/test_chat_deep_research_toggle.py` to verify saved Deep Research defaults reapply for Web Search and direct URL prompts while stubbing user settings persistence.
- Updated `ui_tests/test_chat_new_conversation_tag_reset.py` to verify explicit New Chat clears Workspaces and Web Search action state in addition to selected tags.

## Impact Analysis

Explicit New Chat now starts from a clean per-chat toolbar state. Auto-created conversations from typing, sending, prompt use, or file upload continue to preserve current selections through the existing `preserveSelections` path. Deep Research remains user-friendly for repeat use because the remembered preference survives resets and can reapply when the relevant source action becomes available.

## Validation

Expected after validation:

- `node --check application/single_app/static/js/chat/chat-input-actions.js`
- `node --check application/single_app/static/js/chat/chat-documents.js`
- `node --check application/single_app/static/js/chat/chat-prompts.js`
- `python functional_tests/test_chat_new_conversation_action_state_reset.py`
- `python functional_tests/test_chat_preserves_workspace_selection_on_auto_create.py`
- Focused UI tests where environment variables are configured.