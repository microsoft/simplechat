# V2 Inline Image Proposal Resume Fix

Fixed in version: **0.261.050**

## Issue

Approving an inline image proposal in the V2 interface only reported itself for as long as the
user stayed on the conversation.

Leaving the conversation and coming back showed every mid-generation card as untouched: no
status, no queue position, the **Approve** button enabled again and **Approve all** back. The
images did eventually appear, which was the confusing part — nothing was actually broken, but
nothing said anything was happening either, and pressing **Approve** again on a card that was
already generating would have paid for the same image twice.

Reloading the page had the same symptom for a different reason.

## Root cause

Two separate lifetimes were being treated as one.

An approval is a blocking `POST /api/chat/image-proposals/generate`. The request is owned by the
page that made it. The *work* is not: the server generates the image and writes it to Cosmos
whether or not anything is still connected, and the serial approval queue in
`imageProposalQueue.ts` is module-level, so it keeps draining across navigation.

The state describing that work, however, was held in `ImageProposalScope` — React state owned by
the message bubble. `selectConversation` sets `messages: []` before loading the next
conversation, so leaving a conversation unmounts every scope in it and destroys that state.
Returning re-created the scope empty and every card fell back to `IDLE_CARD_STATE`.

A page reload additionally destroyed the request itself. The image still arrived, because the
server had already been asked for it, but the browser had no way left to learn that it had.

There is no stream to reconnect here. Image approval is not an SSE generation like
`/api/chat/stream`, so there is no server-side session for a returning page to reattach to; the
`reconnectPhase` machinery in `chatStore` does not apply.

## Fix

### Approval state moved to a store

`application/v2_ui/src/stores/imageProposalStore.ts` now owns every card's approval state,
keyed by conversation and then by assistant message, along with the set of approvals still
running. The scope supplies the address; it no longer holds the data. Because the store is a
module, an approval keeps reporting itself through a card rebuild, a message-list teardown, and
a route change alike.

The store also refuses a second approval record for a card that already has one, which is the
guard against paying twice.

### In-flight approvals persisted and resumed

`application/v2_ui/src/lib/imageProposalTracking.ts` describes an approval independently of the
request behind it: which card started it, the proposal fields its image will carry back, and
when it started. Records are written to `sessionStorage` before the request is sent —
`sessionStorage` rather than `localStorage`, so they survive the reload being recovered from
without reaching a second tab that could not settle them.

`application/v2_ui/src/lib/imageProposalResume.ts` restores them when the app starts, puts the
affected cards back into a generating state, and polls until each image lands. Polling backs off
from 1.5s to a 15s ceiling, pauses while the tab is hidden, and gives up on a record ten minutes
after it was started — at which point the card says the page reloaded and offers to approve
again, rather than spinning forever. A record more than fifteen minutes old is not resumed at
all.

Matching an image to the approval waiting for it reuses `findResultForSpec`'s field precedence
(visual id, then prompt, then title) and adds two constraints that only apply here: the image
must have been proposed by the same assistant message, and it must not predate the approval.
Without the second one, re-approving a proposal that already had an image would resolve
instantly against the old one.

### A route cheap enough to poll

`GET /api/chat/image-proposals/status/<conversation_id>` returns the identity of each proposal
result in a conversation and nothing else. Polling `/api/get_messages` would have worked, but a
small generated image is inlined into its message's `content` as a base64 data URI, so an
image-heavy conversation is megabytes per poll; this stays about a kilobyte regardless of thread
size, and an optional `since` parameter narrows it further. When a poll shows the image exists,
the client re-reads the conversation once through the ordinary path so the image lands in its
card exactly as it would have done.

The route authorizes with `_authorize_personal_conversation_access`, the same helper the
approval route uses, so it is not a second access rule that can drift.

### Reporting from where the user actually is

The conversation's row in the rail shows a spinner and a count while it has approvals running,
and a single notice reports approvals whose cards are not on screen. "Not on screen" is
reported by the chat page rather than inferred from the open conversation, because the chat
store keeps a conversation open while the reader is in My Workspace, where the cards are as
invisible as they are in another thread. The notice is deliberately suppressed over the
conversation that owns the cards, where it would only repeat what each card is already saying.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_chats.py` | Added the image proposal status route and its result limit. |
| `application/single_app/config.py` | Version to `0.261.050`. |
| `application/v2_ui/src/lib/imageProposalTracking.ts` | New. Record shape, matching rules, bounds and storage. |
| `application/v2_ui/src/stores/imageProposalStore.ts` | New. Owns card state and in-flight approvals. |
| `application/v2_ui/src/lib/imageProposalResume.ts` | New. Restore, poll, write off, and report. |
| `application/v2_ui/src/lib/imageProposalCardState.ts` | Added `resumed` to a card's state. |
| `application/v2_ui/src/components/chat/ImageProposalContext.tsx` | Reads card state from the store instead of owning it. |
| `application/v2_ui/src/components/chat/InlineImageProposal.tsx` | Tracks its approval, and clears the record when the image appears. |
| `application/v2_ui/src/components/chat/ConversationRail.tsx` | Per-row generating indicator. |
| `application/v2_ui/src/stores/toastStore.ts` | `update`, so a pending notice can count down in place. |
| `application/v2_ui/src/lib/endpoints.ts` | `fetchImageProposalStatus`. |
| `application/v2_ui/src/pages/ChatPage.tsx` | Reports which conversation's cards are on screen. |
| `application/v2_ui/src/App.tsx` | Starts approval tracking with the shell. |

## Validation

- `functional_tests/test_v2_inline_image_proposal_resume.py` — 10/10.
- `functional_tests/test_v2_inline_image_proposal_resume_logic.mjs` — 22/22 runtime checks
  against the real matching, windowing and storage rules.
- `functional_tests/test_v2_inline_image_proposal_store.mjs` — 17/17 runtime checks against the
  real store, covering the duplicate-approval guard, persistence, restore precedence, card
  isolation and pruning.
- `functional_tests/test_image_proposal_status_endpoint.py` — 7/7.
- `functional_tests/test_v2_inline_image_proposal_status_persistence.py` — 7/7, with its
  "the scope owns the map" assertion repointed at the store.
- `functional_tests/test_v2_inline_image_proposals.py` — 13/13, and
  `functional_tests/test_v2_inline_image_proposal_logic.mjs` — 32/32, both unchanged.
- `functional_tests/test_collaboration_inline_image_proposal_porting_fix.py` — 3/3.
- `functional_tests/route_tests/` — all three route policy tests passing with the new route.
- `npm run build` in `application/v2_ui`.

## Before and after

| | Before | After |
| --- | --- | --- |
| Leave the conversation and return | Cards read as untouched; **Approve** enabled again | Cards still show queue position or "Generating image…" |
| Reload the page mid-approval | Same, and the browser had no way to learn the image arrived | Cards show "Still generating from before the page reloaded…" until it does |
| While elsewhere in the app | Nothing | Spinner and count on the conversation row, plus one notice wherever you are |
| Approval never completes | Silent; the card looked ready to approve | Written off after ten minutes with an explanation and an offer to retry |
| Cost of finding out | Not attempted | About a kilobyte per poll, regardless of thread size |
