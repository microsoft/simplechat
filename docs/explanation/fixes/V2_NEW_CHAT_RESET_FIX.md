# V2 New Chat Keeps a Busy Conversation's Thinking State

**Fixed in version:** 0.261.218

**Issue:** [#1617](https://github.com/microsoft/simplechat/issues/1617)

## Issue

In the V2 interface, starting a new conversation while the open one was busy did not give a
clean conversation:

* Clicking **New chat** while chat orchestration was planning or running kept the old turn's
  "Thinking" bubble and a **Stop** button that did nothing. The new chat's empty state never
  appeared, and the composer refused to send until the page was reloaded.
* Clicking **New chat** while the first message of a new chat was still creating its
  conversation let that message take over the new chat. Its question and answer appeared in
  the chat the reader had just opened.
* Clicking **New chat** while a conversation's messages were loading left the loading
  placeholders in the new chat instead of its empty state.
* Choosing **Chat** on selected workspace documents or a tag, or **Start chatting** on the
  home page, opened whichever conversation was last open. The documents were attached to it,
  even if a reply was still being written there.

The classic interface always starts a fresh conversation in each of these cases.

## Root cause

### Orchestration turns stranded the `streaming` flag

`chatStore.ts` has one `streaming` flag for the conversation on screen. It drives the
streaming bubble, the Stop button and the empty state, and `sendMessage` refuses to send while
it is set.

A plain chat stream is owned by `activeStreamController`. Leaving its conversation runs
`detachActiveStream()`, which aborts the reader and clears `streaming`. `selectConversation`
and `startNewConversation` relied on that helper to clear the flag.

An orchestration plan or run is driven by `orchestrationController.ts`, which uses its own
controllers. Its turn sets `streaming` in `beginOrchestrationTurn` and clears it in
`settleOrchestrationTurn`, but both only write while that conversation is on screen. So:

1. `beginOrchestrationTurn` set `streaming: true`.
2. The reader clicked **New chat**. `detachActiveStream()` found no chat-stream controller and
   returned early, so `streaming` stayed `true`.
3. When the turn finished, `settleOrchestrationTurn` saw that its conversation was no longer
   on screen and skipped the write.

The flag stayed set for the rest of the page's life. The Stop button routed to
`stopStreaming()`, which also found no controller and did nothing.

### The first-message claim could not see a New chat

A first message has to create its conversation (`POST /api/create_conversation`) before it
can stream. After that round trip, `sendMessage`, `generateImageFromReference` and the
orchestration `ensureConversation` claimed the screen if `activeConversationId` was still
`null`. That check was meant to catch the reader opening another conversation meanwhile. But
**New chat** also leaves the id `null`, so a new chat opened during the round trip was
claimed by the old question.

### New chat did not reset `messagesLoading`

`selectConversation` sets `messagesLoading: true` and, when its response arrives for a
conversation that is no longer open, returns without clearing it. `startNewConversation` did
not clear it either.

### Hand-offs into chat reused the open conversation

`DocumentExplorer.onChat`, `TagsSection.onChat` and the home page link navigated to `/chat`
without resetting the chat store. The store outlives a route change, so the last-open
conversation was still active when the chat page mounted.

## Fix

### Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/stores/chatStore.ts` | Adds a module-level `orchestrationSurfaces` set of conversations whose orchestration turn holds the streaming surface. `beginOrchestrationTurn` adds to it and `settleOrchestrationTurn` removes from it, both before their on-screen guards, and `reassignOrchestrationTurn` moves the entry when the server re-keys a conversation. `startNewConversation` now clears `streaming` and `messagesLoading`. `selectConversation` sets `streaming` from the set. Both advance a new `conversationEpoch`, exposed through `currentConversationEpoch()`. `sendMessage` and `generateImageFromReference` claim the screen only if the epoch is unchanged since the message was sent. |
| `application/v2_ui/src/lib/orchestrationController.ts` | `ensureConversation` uses the same epoch-guarded claim |
| `application/v2_ui/src/components/documents/DocumentExplorer.tsx` | **Chat** on selected documents calls `startNewConversation()` immediately before navigating |
| `application/v2_ui/src/pages/workspace/TagsSection.tsx` | **Chat** on a tag does the same |
| `application/v2_ui/src/pages/HomePage.tsx` | **Start chatting** starts a new chat when followed |
| `application/single_app/config.py` | Version `0.261.217` -> `0.261.218` |

### Design notes

* Leaving a busy conversation still **detaches rather than cancels**. The answer, or the
  orchestration plan or run, keeps going and is saved. Only Stop ends work, as described in
  [V2_STREAM_CANCELLED_ON_CONVERSATION_LEAVE_FIX.md](V2_STREAM_CANCELLED_ON_CONVERSATION_LEAVE_FIX.md).
* Reopening a conversation whose orchestration turn is still running in this tab restores its
  Thinking state and Stop button, and the turn's next reasoning steps and answer land there as
  usual. Reasoning steps that arrived while the reader was elsewhere aren't replayed. The plan
  card and its step progress come from the orchestration store, which keeps updating while the
  reader is away.
* A first message whose new chat was replaced during its round trip is still sent. Its answer
  is generated and saved, and the conversation appears in the rail, as already happened when
  the reader opened a different conversation instead.
* The composer keeps unsent text, chips and an attached prompt across **New chat**. The
  documents or tag handed over by a workspace **Chat** action arrive as chips in the new chat.
* Clicking **Chats** in the navigation rail from another page still returns to a reply that is
  streaming instead of resetting it. That exception is deliberate (see
  [V2_NEW_CHAT_BUTTON_SCOPING_FIX.md](V2_NEW_CHAT_BUTTON_SCOPING_FIX.md)). With this
  fix, `streaming` reflects a reply that is really in progress.

## Behaviour after the fix

* **New chat** always shows an empty conversation: the "New chat" title, the empty state,
  **Send** and no Thinking bubble, whatever the previous conversation was doing.
* The previous conversation's plan, run or reply finishes in the background and is there when
  it is reopened.
* A new chat opened while another first message is still being created stays empty.
* **New chat** while a conversation is loading shows the empty state.
* **Chat** on workspace documents or a tag, and **Start chatting** on the home page, open a
  brand-new conversation.

## Validation

### Browser tests

`ui_tests/test_v2_new_chat_reset.py` (7 tests) runs the production AppShell, Sidebar, HomePage,
ChatPage, Composer, stores, orchestration controller and SSE reader against held, server-shaped
streams. It covers:

* **New chat** during planning. The test then reopens the conversation, checks that Thinking and
  Stop are restored, leaves again, lets the plan finish out of sight, and checks that the plan
  card is shown on return with no Thinking.
* **New chat** during a run. The run's answer must not appear in the new chat, the new chat must
  be able to send at once, and Stop must end the new chat's own turn.
* **New chat** during a plain chat stream. This is a regression check: no cancel request may be
  sent.
* **New chat** during the first message's `create_conversation` round trip, for both chat and
  orchestration.
* **New chat** while a conversation's messages are loading.
* **Start chatting** on the home page while orchestration is planning.

Six of the seven tests fail against the pre-fix code. The plain chat stream case already worked
and is kept as a regression check.

Updated browser tests:

* `ui_tests/test_v2_orchestration_planning_retry.py`: the late-retry test now also asserts that
  `streaming` is released and that Send, not Stop, is shown.
* `ui_tests/test_v2_chat_context_selection.py`: the workspace **Chat** hand-off test now starts
  from a busy conversation and expects a brand-new one, with the first message creating its own
  conversation.

All three updated tests fail against the pre-fix code.

### Functional tests

* `functional_tests/test_v2_new_chat_reset.py` (6 tests) pins the reset fields, the surface
  bookkeeping and its ordering against the on-screen guards, the epoch-guarded claims in all
  three creation paths, the hand-offs, and the version.
* `functional_tests/test_v2_stream_leave_without_cancel.py` now requires `startNewConversation`
  and `selectConversation` to set `streaming` themselves, requires the epoch-guarded claim in
  `sendMessage`, and follows the Stop button's `handleStop` routing.
* `functional_tests/test_v2_new_chat_scoping.py` selectors now match the Sidebar's current
  `mobile` prop and inline click handler.

## Related

* [V2_STREAM_CANCELLED_ON_CONVERSATION_LEAVE_FIX.md](V2_STREAM_CANCELLED_ON_CONVERSATION_LEAVE_FIX.md)
* [V2_NEW_CHAT_BUTTON_SCOPING_FIX.md](V2_NEW_CHAT_BUTTON_SCOPING_FIX.md)
* `ui_tests/test_v2_new_chat_reset.py`
* `functional_tests/test_v2_new_chat_reset.py`
