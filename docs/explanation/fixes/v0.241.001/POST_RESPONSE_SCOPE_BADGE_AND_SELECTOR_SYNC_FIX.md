# Post Response Scope Badge And Selector Sync Fix

Fixed/Implemented in version: **0.239.198**

## Overview

This fix ensures that once an agent or model response completes for a newly created scoped conversation, the chat UI updates all related scope indicators immediately instead of waiting for a browser refresh.

## Root Cause

The stream completion path updated the main conversation metadata and title, but it only refreshed the sidebar title text. It did not update the sidebar conversation scope badge or trigger the agent/model selector refresh after the active conversation changed from `new` into a persisted scoped conversation.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_scope_selector_sync.py`
- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`
- `ui_tests/test_chat_scope_selector_sync.py`

### Code Changes Summary

- added a sidebar metadata update helper that applies `chat_type`, context attributes, and the group scope badge without reloading the full sidebar list
- updated the shared conversation metadata update path to also sync the sidebar conversation item
- refreshed agents and models immediately when the active conversation receives a scoped metadata update
- updated the stream completion path to apply conversation metadata updates whenever scope metadata is present, not only when a title is present
- bumped the application version to `0.239.198`

## Validation

### Tests

- `functional_tests/test_chat_scope_selector_sync.py`
- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`
- `ui_tests/test_chat_scope_selector_sync.py`

### User Experience Improvements

- the top-of-chat workspace badge, left-pane sidebar badge, and locked-scope agent/model filtering now become consistent immediately after the response completes
- refreshing the page is no longer required to see the final scoped state of the conversation