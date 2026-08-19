# New Chat Conversation Documents Drawer Reset Fix

Fixed in version: **0.260.004**

Associated issue: [#1298](https://github.com/microsoft/simplechat/issues/1298)

## Issue Description

The chat conversation side drawer has two modes, **Contents** and **Documents**. Clicking **New chat** correctly emptied the **Contents** pane and closed the drawer, but the **Documents** pane kept showing the documents from the conversation the user had just left.

Observed symptoms:

- Documents from the previous conversation remained listed after starting a new chat.
- The header documents toggle (`#conversation-documents-toggle`) stayed visible.
- The `#conversation-documents-count` badge kept the stale count.
- The drawer stayed open instead of closing.
- Switching between existing conversations behaved correctly; only the **New chat** path was affected.

## Root Cause Analysis

`createNewConversation()` in `chat-conversations.js` signals the reset **before** the new conversation exists, so the event carries a null id:

```js
notifyConversationContextChanged("new", null, { preserveSelections });
```

The drawer listener in `chat-conversation-contents.js` forwarded that as an empty string, and `refreshConversationDocuments()` resolved the conversation id with a fallback:

```js
const conversationId = String(options.conversationId || getCurrentConversationId()).trim();
```

At that moment `window.currentConversationId` still pointed at the **previous** conversation, because it is only reassigned after the `/api/create_conversation` response returns. The falsy id therefore fell through to the old conversation, and the "reset" signal was executed as "refresh the conversation I am already on": the old metadata was re-fetched and the old documents were re-rendered.

Because `documentEntries` never became empty, `updateDrawerTriggers()` never reached its terminal branch:

```js
if (!hasContents && !hasDocuments) {
    closeDrawer({ restoreFocus: false });
}
```

so the toggle, the count badge, and the open drawer all persisted.

The **Contents** pane reset correctly only because it is driven by a completely different mechanism: the `MutationObserver` on `#chatbox` reacting to `chatbox.innerHTML = ""` inside `createNewConversation()`.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-conversation-contents.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_new_conversation_documents_drawer_reset.py`
- `docs/explanation/release_notes.md`

### Code Changes Summary

- Added an `allowCurrentConversationFallback` option (default `true`) to `refreshConversationDocuments()` so a caller can require an explicit conversation id instead of silently resolving the active one.
- Updated the `chat:conversation-context-changed` listener to pass `allowCurrentConversationFallback: false`, so a null/empty id now means *reset* rather than *reload current*.
- No new reset logic was needed: the existing `if (!conversationId)` branch already clears `documentEntries`, resets the usage-tracking flags, clears the status line, shows the empty state, and calls `updateDrawerTriggers()`. The fix simply makes that branch reachable.
- Updated `config.py` to version `0.260.004` for this fix.

### Behavior Preserved

The current-conversation fallback is intentionally retained for the callers that depend on it:

- The module's initial `refreshConversationDocuments()` call on page load.
- The `chat:conversation-documents-refresh` event path used by streaming, retry, message edit, and collaboration.
- `chat:conversation-context-changed` with `reason: "select"`, which always supplies an explicit id.

A second context-changed event is deliberately **not** dispatched after the new conversation is created. Doing so would re-trigger the workspace, prompt, and toolbar reset listeners and wipe selections the user made immediately after starting the new chat. A brand-new conversation has no cited documents, and the first response already fires `chat:conversation-documents-refresh` from `chat-streaming.js`.

## Validation

### Test Results

`functional_tests/test_chat_new_conversation_documents_drawer_reset.py` — 7/7 checks passed:

- New chat still dispatches the context reset with a null conversation id.
- `refreshConversationDocuments()` exposes the fallback opt-out and no longer contains the unconditional fallback expression.
- The context-changed listener opts out of the fallback.
- The targeted document-refresh path and module init still resolve the active conversation.
- The empty-id branch clears document state and lets `updateDrawerTriggers()` close the drawer and hide the toggle/badge.
- The drawer markup still exposes every element the reset updates.
- `config.py` version is at least `0.260.004`.

A jsdom runtime harness exercised the real module against both the pre-fix and post-fix source:

| Check after clicking New chat | Before fix | After fix |
| --- | --- | --- |
| Documents pane empty | FAIL (2 entries) | PASS |
| Contents pane empty | PASS | PASS |
| Documents toggle hidden | FAIL | PASS |
| Documents count badge hidden | FAIL | PASS |
| Drawer closed | FAIL | PASS |
| No metadata refetch for the conversation being left | FAIL (1 fetch for `conv-a`) | PASS |
| Selecting another conversation still loads its documents | PASS | PASS |

### Regression Coverage

- `functional_tests/test_chat_cited_source_tracking.py` — passed.
- `functional_tests/test_chat_new_conversation_action_state_reset.py` — passed.
- `functional_tests/test_conversation_contents_drawer_settings.py` and `functional_tests/test_chat_new_conversation_tag_reset.py` fail on this branch, but both were verified to fail identically on the unmodified baseline and are unrelated to this change (a `route_backend_users.py` test-namespace gap and a `chat-documents.js` assertion drift respectively).

### Before/After Comparison

| Step | Before | After |
| --- | --- | --- |
| Open a conversation with cited documents | Documents pane lists them | Unchanged |
| Open the drawer in Documents mode | Drawer opens | Unchanged |
| Click **New chat** | Documents stay listed, toggle and badge stay visible, drawer stays open | Documents pane empties, toggle and badge hide, drawer closes |
| Switch to an existing conversation | Documents reload | Unchanged |

### User Experience Improvements

- A new chat no longer appears to already have documents associated with it.
- The **Documents** pane now behaves consistently with the **Contents** pane on **New chat**.
- One redundant conversation-metadata request per **New chat** click is eliminated.
