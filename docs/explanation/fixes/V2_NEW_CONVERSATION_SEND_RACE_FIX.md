# V2 Send Race While a New Conversation Is Being Created

**Fixed in version:** 0.261.051

## Issue

Sending the **first** message in a brand-new chat and then clicking a different conversation
within the next fraction of a second produced two wrong outcomes:

* The reader was snapped back into the new chat, silently undoing the conversation they had
  just clicked.
* In the unluckier ordering, where the clicked conversation's messages finished loading
  first, that conversation's history rendered underneath the new chat, with the new
  question and its streaming answer appended below it.

Nothing was lost or saved to the wrong conversation. The effect was confined to what was on
screen, and reloading or reselecting the thread corrected it.

## Root cause

A new chat has no conversation until the server makes one, so the first send has to wait for
`createConversation` before it can stream. That is the only pause in `sendMessage` between
pressing send and the stream starting — everything after it runs synchronously — so it is
precisely the window in which a click can land.

Two things then went wrong when it did:

1. `sendMessage` claimed `activeConversationId` unconditionally once the conversation came
   back, overwriting whatever the reader had opened in the meantime. Because the message
   list is keyed on the active conversation, an in-flight load for the clicked thread could
   also deposit its messages under the new one.
2. `runChatStream` decided whether its handlers should render using only
   `activeStreamController === controller`. That is the right question for teardown, but it
   does not cover this window: no controller exists yet while the conversation is being
   created, so there is nothing for a thread switch to clear. The stream installed its
   controller afterwards, the check passed, and the answer rendered into whichever thread
   was open.

This is a separate defect from
[V2 Stream Cancelled On Conversation Leave](V2_STREAM_CANCELLED_ON_CONVERSATION_LEAVE_FIX.md),
which addressed the same "leave straight after sending" scenario once a stream already
existed. That fix relies on detaching a live reader, and here there is not yet one to detach.

## Fix

The reader's click wins. The message is still sent, and the answer is still generated and
saved, but the interface stays where they put it.

### Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/stores/chatStore.ts` | `sendMessage` claims `activeConversationId` only when nothing has been opened during the round trip; the optimistic user message and streaming state are written only when this send owns the screen; `runChatStream` separates `ownsController` from `isCurrent` |
| `application/single_app/config.py` | Version `0.261.050` -> `0.261.051` |

Two questions that had been answered by one check are now answered separately:

* `ownsController()` — does this invocation still own the module's `AbortController`? This
  governs teardown. Only the owner may clear the controller, and it must stay identity-based:
  a stream whose conversation is off screen still owns it, and `resumeChatStream` refuses to
  attach while one is set.
* `isCurrent()` — is this stream's conversation still the one on screen? This governs
  rendering, and now additionally requires
  `getState().activeConversationId === conversationId`.

## Behaviour after the fix

* Clicking a conversation while a new chat is being created keeps you in the conversation
  you clicked.
* The backgrounded send still runs. Its answer is generated, saved, and the new chat appears
  in the rail with its server-generated title and the usual unread marker.
* No other thread's messages can appear under a conversation they do not belong to.
* Ordinary sends are unaffected: the stream's conversation is the active one throughout, so
  the added condition is always true and behaviour is unchanged.

## Validation

Covered by `functional_tests/test_v2_stream_leave_without_cancel.py`, which holds the whole
"leave straight after sending" contract in one place (15 tests). The three added for this
fix assert:

* `sendMessage` guards its `activeConversationId` claim on nothing else having been opened.
* The optimistic user message and streaming state are written only under `ownsScreen`.
* `runChatStream` defines `ownsController` and a conversation-scoped `isCurrent`, and gates
  teardown on `ownsController` so a backgrounded stream still clears the controller.

Each was confirmed to fail against the pre-fix code. `tsc -b --noEmit` passes, and
`functional_tests/test_v2_stream_reconnect.py` continues to pass.

## Related

* [V2 Stream Cancelled On Conversation Leave](V2_STREAM_CANCELLED_ON_CONVERSATION_LEAVE_FIX.md)
  — the same scenario once a stream exists
