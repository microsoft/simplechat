# Shared (Multi-User) Conversation Reload and Streaming Fix

**Fixed in version: 0.250.224**
**Hardening added in version: 0.250.225**
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

## Follow-up Hardening (0.250.225)

Three further defects were found while tracing this bug. None of them caused the reported symptoms, so they were kept out of the original fix.

### Stream errors are now always attributed to the shared conversation

`chat-streaming.js` chooses its recovery endpoint from `conversation_kind`:

```js
if (data.conversation_kind === 'collaborative' && ...loadConversationMessages) {
    // collaboration endpoint
} else {
    loadMessages(data.conversation_id);   // personal endpoint, 404s for shared conversations
}
```

None of the seven `_serialize_stream_error()` call sites in the shared stream bridge set `conversation_kind`, so a shared conversation would fall into the `else` branch and hit the same 404 this fix removed.

It could not fire in practice, because the surrounding guard also requires `message_id` and those error payloads never carried one. It was a latent trap rather than a live defect: adding `message_id` to an error payload — a natural change — would have reintroduced the bug.

Rather than adding the field to seven call sites, all shared stream failures now funnel through a single nested helper that cannot omit it:

```python
def collaboration_stream_error(error_message, **extra_fields):
    """Serialize a stream error that stays attributed to this shared conversation."""
    return _serialize_stream_error(
        error_message,
        user_message_id=serialized_user_message.get('id'),
        message_persisted=True,
        conversation_id=conversation_id,
        conversation_kind=COLLABORATION_KIND,
        **extra_fields,
    )
```

`test_collaboration_stream_errors_always_carry_conversation_kind` walks the AST of `stream_collaboration_message_api` and asserts exactly one raw `_serialize_stream_error` call remains, that it sets `conversation_kind=COLLABORATION_KIND`, and that every failure path routes through the helper. Adding a new error path without the tag now fails the test.

### Stale `@app.route` assertions repaired across the test suite

The Blueprint migration left production with a single `@app.route` decorator — an example inside a `swagger_wrapper.py` docstring — while 82 test assertions across 40 files still expected the old form.

This is how the streaming defect shipped. `test_collaboration_shared_ai_workflow.py` existed to guard this exact bridge, but broke on line 35 (`@app.route`) and died before reaching line 37, which checked the endpoint lookup. The test that should have caught the bug was already red for an unrelated reason.

59 assertions across 32 files were rewritten to `@bp.route`, each verified against a real `@bp.route` path in `application/single_app` before being changed. 14 occurrences were deliberately left alone because no matching production route exists — those point at routes that appear to have been removed or renamed, which is a different problem and must not be papered over with a passing assertion.

Measured effect on the affected files: **47 failures to 34, with zero newly broken.**

### Dead post-stream reload guard (tracked separately)

`chat-streaming.js:1449` and `:1515` guard on `typeof window.chatMessages?.loadMessages === 'function'`, but `loadMessages` is not among the six functions `chat-messages.js` assigns to `window.chatMessages`, and `git log -S` confirms it never was. The guard has been dead since commit `54e37c87`.

The backend sets `reload_messages: true` when an agent plugin persists extra message documents into Cosmos, so those messages stay invisible until a manual reload. Impact is probably narrow — the final payload renders `image_url` separately — but sizing it needs a repro, and switching on a path that has never executed in production is not a safe blind change. Filed as [#1286](https://github.com/microsoft/simplechat/issues/1286).
