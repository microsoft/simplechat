# CHAT_SCOPE_SELECTOR_SYNC_FIX

Fixed in version: **0.239.194**

## Issue Description

New chat conversations only exposed agents and models from the active group instead of the full set of groups the user belonged to. The chat header workspace badge also lagged behind title updates and usually required a reload before the selected scope appeared.

## Root Cause Analysis

- The chat page only loaded group agents through the single active-group endpoint.
- Model selection state depended on the server-rendered dropdown and did not have a chat-specific catalog for scope-aware filtering.
- Scope changes reloaded documents and tags, but there was no shared event pipeline for agent and model selectors to react to.
- Conversation metadata was primarily inferred from search results, so scoped conversations without retrieved documents did not immediately produce primary context metadata.
- Streaming completion updated the title text but did not immediately apply the new `context` and `chat_type` metadata back into the active conversation UI.

## Files Modified

- `application/single_app/route_frontend_chats.py`
- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-agents.js`
- `application/single_app/static/js/chat/chat-model-selector.js`
- `application/single_app/static/js/chat/chat-conversation-scope.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-onload.js`
- `application/single_app/static/js/chat/chat-reasoning.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/static/js/chat/chat-export.js`
- `application/single_app/static/js/chat/chat-retry.js`
- `application/single_app/functions_conversation_metadata.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_scope_selector_sync.py`
- `ui_tests/test_chat_scope_selector_sync.py`

## Code Changes Summary

- Added preloaded chat agent and model catalogs that include personal, global, and all eligible group-scoped options for the current user.
- Added a shared scope helper and a programmatic scope setter that dispatches a `chat:scope-changed` event for selector synchronization.
- Reworked the chat agent selector to filter from the preloaded catalog and only narrow the chat scope when the user explicitly picks a scoped agent.
- Reworked the chat model selector to filter from the preloaded catalog, preserve restored defaults, and only narrow the chat scope when the user explicitly picks a scoped model.
- Updated chat message submission to send full public workspace scope selections and to persist unique model selection keys while still submitting concrete model metadata.
- Added explicit scope-to-primary-context metadata derivation so scoped conversations can immediately render group and public workspace badges even when no document retrieval occurs.
- Updated streaming and title update flows so `context`, `chat_type`, and scope-lock metadata can refresh the active conversation badge state immediately.

## Testing Approach

- Added `functional_tests/test_chat_scope_selector_sync.py` to validate the new scope synchronization and metadata propagation wiring.
- Added `ui_tests/test_chat_scope_selector_sync.py` to validate browser-side selector filtering and immediate workspace badge rendering.

## Validation

- Functional regression test passed locally: `functional_tests/test_chat_scope_selector_sync.py`
- UI regression test is in place and currently skips when the required authenticated UI test environment variables are not configured.

## Impact Analysis

- New conversations can expose agents and models across all eligible group memberships until the user explicitly narrows scope.
- Existing conversations remain filtered to their persisted personal, group, or public workspace context.
- Workspace badges now appear immediately after title and metadata updates instead of waiting for a page reload.
- Agent, model, workspace, document, and tag state changes now share a single synchronization path, reducing inconsistent chat composer state.