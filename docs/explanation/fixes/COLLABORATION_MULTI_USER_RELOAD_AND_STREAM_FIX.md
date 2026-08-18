# Shared (Multi-User) Conversation Reload and Streaming Fix

**Fixed in version: 0.250.224**
**Tracking issue: [#1281](https://github.com/microsoft/simplechat/issues/1281)**

## Issue Description

Once a personal conversation was shared with another user (`chat_type = personal_multi_user`), the conversation became unusable end to end. Two independent defects were involved.

### Symptom 1 — 404 on every reload or conversation click

Every page reload or sidebar click on a shared conversation produced a failed request and a `Conversation not found` danger toast:

```
addChatTypeBadges: chatType="personal_multi_user", groupName="null"
GET /conversation/9f615422-f4d8-4352-ad09-016cb3d735c1/messages?ts=... 404 (Not Found)
Error loading messages: Error: Conversation not found
    at chat-messages.js:2140
    at async selectConversation (chat-conversations.js:1688)
```

### Symptom 2 — AI never responded

Every AI request in a shared conversation short-circuited before the model was called:

```
AI
Stream interrupted before any content was received.
⚠ Stream interrupted: Chat streaming endpoint is unavailable
Response may be incomplete. The partial content above has been saved.
```

## Root Cause Analysis

### Root cause 1 — the personal-only messages endpoint was used for shared conversations

`selectConversation()` in `chat-conversations.js` called the personal message loader inside its collaborative branch:

```js
if (isCollaborativeConversation && window.chatCollaboration?.activateConversation) {
    await loadMessages(conversationId);          // personal-only endpoint
    scrollConversationViewToBottom();
    await window.chatCollaboration.activateConversation(conversationId, metadata);
}
```

`loadMessages()` fetches `/conversation/<id>/messages`. That handler (`route_frontend_conversations.get_conversation_messages`) reads only `cosmos_conversations_container`. A collaborative conversation lives in `cosmos_collaboration_conversations_container` under a **different id** than its hidden `source_conversation_id` — see `ensure_personal_collaboration_for_legacy_conversation()`, which creates a brand new collaboration document and links back to the original. The read therefore always raised `CosmosResourceNotFoundError`, producing a guaranteed `404`.

The call was also redundant. `activateConversation()` calls `loadConversationMessages()`, which already clears `#chatbox` and renders the shared messages from `/api/collaboration/conversations/<id>/messages`.

Two side effects regressed as a consequence of the failing call:

| Side effect | Behavior before the fix |
|---|---|
| `updateComparisonChatUploadCatalog()` | Called with `[]` from the `catch` block, so chat uploads in shared conversations never reached the Compare/Analyze picker. |
| `updateConversationTaskDocumentsFromMessages()` | Never ran, so task documents from the previously viewed conversation stayed cached against the wrong conversation. |

### Root cause 2 — the Blueprint migration broke the internal stream endpoint lookup

`route_backend_collaboration.py` bridged shared AI requests into the single-user chat pipeline by looking the view function up by name:

```python
internal_stream_view = current_app.view_functions.get('chat_stream_api')
```

Commit `094424bc` ("Harden route blueprint security policies") moved every route module onto Blueprints. `app.py` now registers chat routes with `register_route_blueprint('backend_chats', register_route_backend_chats, user_required_blueprint)`, so `/api/chat/stream` is declared with `@bp.route(...)` and Flask stores it under the qualified endpoint **`backend_chats.chat_stream_api`**.

The unqualified lookup returned `None`, so the bridge emitted `Chat streaming endpoint is unavailable` and the model was never invoked. This affected both personal and group collaborative conversations, which share the same bridge.

`current_app.view_functions` was the only remaining Blueprint-prefix assumption in the application — every `url_for()` call was already dotted.

## Files Modified

| File | Change |
|---|---|
| `application/single_app/route_backend_collaboration.py` | Added `_resolve_internal_view_function()` and used it for the chat stream bridge; added a `[COLLABORATION]` log event when resolution fails. |
| `application/single_app/static/js/chat/chat-conversations.js` | Removed the personal `loadMessages()` call from the collaborative branch of `selectConversation()`. |
| `application/single_app/static/js/chat/chat-collaboration.js` | `loadConversationMessages()` now clears stale search highlights, rehydrates conversation task documents, refreshes the comparison chat upload catalog, and reapplies a pending search highlight. |
| `application/single_app/static/js/chat/chat-messages.js` | Exported `updateComparisonChatUploadCatalog` so the collaboration loader can reuse it. |
| `application/single_app/config.py` | `VERSION` bumped to `0.250.224`. |

## Code Changes

### Blueprint-tolerant view resolution

```python
def _resolve_internal_view_function(endpoint_name):
    """Resolve a registered Flask view function, tolerating Blueprint endpoint prefixes."""
    view_functions = getattr(current_app, 'view_functions', None) or {}
    view_function = view_functions.get(endpoint_name)
    if callable(view_function):
        return view_function

    for registered_endpoint, registered_view in view_functions.items():
        if str(registered_endpoint).rsplit('.', 1)[-1] == endpoint_name and callable(registered_view):
            return registered_view

    return None
```

The exact-match fast path is kept first so views registered directly on an application (as in several existing collaboration test harnesses) continue to resolve unchanged.

### Shared conversation selection

```js
if (isCollaborativeConversation && window.chatCollaboration?.activateConversation) {
    await window.chatCollaboration.activateConversation(conversationId, metadata);
    scrollConversationViewToBottom();
} else {
    // unchanged personal path
}
```

### Side-effect parity in the collaboration loader

```js
async function loadConversationMessages(conversationId) {
    clearSearchHighlight();
    const payload = await fetchJson(`/api/collaboration/conversations/${conversationId}/messages`);
    ...
    const messages = Array.isArray(payload.messages) ? payload.messages : [];
    updateConversationTaskDocumentsFromMessages(messages, conversationId);
    updateComparisonChatUploadCatalog(messages);
    ...
    reapplyPendingSearchHighlight();
    return messages;
}
```

`buildComparisonChatUploadCatalog()` already reads only fields that `serialize_collaboration_message()` emits (`role`, `filename`, `extracted_text`, `file_content_source`, `vision_analysis`, `metadata.is_user_upload`), so no shape adapter was required.

## Testing

### Functional tests

`functional_tests/test_collaboration_multi_user_reload_and_stream_fix.py`

* Builds a Flask app registering `chat_stream_api` on a Blueprint named `backend_chats` — exactly like production — and asserts the resolver finds it even though `chat_stream_api` is not a `view_functions` key.
* Asserts a directly registered (unprefixed) view still resolves and that an unknown endpoint name resolves to `None`.
* Asserts the collaborative branch of `selectConversation()` no longer calls `loadMessages(` while the personal branch still does.
* Asserts `loadConversationMessages()` performs all four side effects.
* Uses `assert_app_version_at_least()` from `functional_tests/test_support/versioning.py`.

The resolver is loaded by compiling just its AST node out of `route_backend_collaboration.py`, so its real behavior is exercised without standing up Cosmos, Search, and OpenAI clients.

`functional_tests/test_collaboration_shared_ai_workflow.py` was repaired: it asserted `@app.route(...)` for the collaboration stream route and two `route_backend_chats.py` snippets that had drifted, so it had been failing since the Blueprint migration.

### UI test

`ui_tests/test_chat_collaboration_conversation_load.py` extracts the shipped `loadConversationMessages()` source, runs it in Chromium against a static harness, and asserts:

* `/conversation/<id>/messages` is never requested.
* `/api/collaboration/conversations/<id>/messages` is requested exactly once, with the shared conversation id.
* Stale highlights are cleared before loading.
* Task documents are hydrated against the shared conversation id.
* Shared chat uploads reach the comparison catalog.
* A fresh pending search highlight is reapplied after rendering.
* No browser console errors occur.

### Validation results

| Check | Result |
|---|---|
| `test_collaboration_multi_user_reload_and_stream_fix.py` | 6/6 passed |
| `test_collaboration_shared_ai_workflow.py` | passed |
| `ui_tests/test_chat_collaboration_conversation_load.py` | passed |
| `route_tests/test_route_blueprint_policy_inventory.py` | 6/6 passed |
| `route_tests/test_route_unauthenticated_policy_contract.py` | 4/4 passed |
| `route_tests/test_route_policy_test_coverage.py` | 2/2 passed |
| Both new tests against pre-fix source | failed as expected |
| Chat ES module graph loaded in Chromium | resolved with no console or page errors |

## Before / After

| Scenario | Before | After |
|---|---|---|
| Reload or click a shared conversation | `404` on `/conversation/<id>/messages` plus a `Conversation not found` danger toast | Messages load from the collaboration endpoint only; no failed request, no toast |
| Send a message in a shared conversation | `Stream interrupted: Chat streaming endpoint is unavailable`, model never called | Request bridges into the chat stream pipeline and streams normally |
| Chat uploads in a shared conversation | Never appeared in the Compare/Analyze picker | Available like they are in personal conversations |
| Task documents after switching to a shared conversation | Stale entries from the previously viewed conversation | Rehydrated against the shared conversation |

## Related

* Fix note: this also restores group collaborative conversations, which use the same stream bridge.
* Feature documentation: `docs/explanation/features/COLLABORATIVE_CONVERSATIONS_FOUNDATION.md`
