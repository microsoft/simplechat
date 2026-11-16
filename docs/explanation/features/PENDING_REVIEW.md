# Pending Email and Calendar Review

## Overview

Implemented in version: **0.261.325**, tracked in
`application/single_app/config.py`.

The owner of a manually prepared Microsoft 365 email or calendar invitation can
review and revise it without repeating the agent request. Direct edits and AI
suggestions use the same working draft. Saving never sends email or meeting
invitations; sending remains an explicit action on the saved card.

Dependencies are the existing Microsoft 365 pending-action service, delegated
Graph authorization, the configured action AI assistant, and the React V2
dialog/assist framework. No delivery preference or new assistant setting is
introduced. Shared viewers and automatic/delayed actions do not get an editor.

## Technical Specifications

### Owner-authorized material and revisions

The editor reads the complete saved material through
`GET /api/msgraph/pending-actions/<id>/review`, rather than rebuilding it from a
shortened card preview. The response includes `fields`, `expected_version`, a
sanitized `pending_action`, and a bounded `history` page.

`PATCH` to that endpoint accepts `expected_version`, editable `fields`, an
`origin` of `direct` or `ai`, and an optional `assist_turn_id`. Saves are
conditional on the reviewed revision. Concurrent edits or delivery claims
produce a visible conflict instead of silently overwriting newer content.

Calendar inputs retain the authoritative wall time and timezone. Graph's
seven-digit fractional seconds are shortened only for native input display;
unmodified timestamps keep their original precision when other fields are saved.
Offset-bearing timestamps represent instants and display in the selected
timezone, including Windows timezone names resolved by the review response's
bounded `timezone_aliases` metadata. Offset-free Graph wall times are not
converted. Display conversion never rewrites saved fields; unsupported browser
zones show the unchanged ISO timestamp with an explicit notice rather than
silently dropping its offset.

For email, Save updates the actual Outlook draft. For calendar, it updates the
local invitation material; Outlook event creation and invitation delivery occur
only on Send. A partial email save stays non-sendable until the server reconciles
the Outlook and stored review material.
When the server offers **Edit** for an expired editing claim, reopening performs
that authorized reconciliation; it does not bypass the send restriction.

### AI assistance and durable history

`POST /api/msgraph/pending-actions/<id>/assist` accepts the current
`expected_version`, editable `fields`, `instruction`, and `submission_id`.
The service reuses the configured editor-assist model, limits and typed proposal
contract. The browser validates the field allowlist, displays the proposal in
the working copy, and adopts the new revision created by recording the turn.
It never invokes a delivery endpoint.

`GET /api/msgraph/pending-actions/<id>/history?cursor=<cursor>&limit=20`
loads another bounded page. History is stored separately from the pending
delivery receipt, with direct/AI attribution and saved/applied state. Closing and
reopening rereads saved history. Ordinary close retains the in-memory Ask AI
input/thread for reopening, while confirmed unsaved field edits are discarded.
Pending local exchanges are cancelled on close. Losing edit authorization
removes that action's global assist entry even with the editor closed; terminal
or denied actions also clear active review material. A temporary processing
pause keeps existing field edits read-only until authorized recovery.
History reads adopt a newer revision only when the saved fields are unchanged.
If another edit changed those fields, the working copy stays visible but locked
until an explicit saved-draft reload, rather than overwriting the newer material.
Persisted suggestions retain their original working-field snapshot and proposed
fields. After reopening, **Apply suggestion** copies only changed allowlisted
fields still matching that snapshot. Newer edits survive with a visible warning.
The result is an unsaved AI-attributed working change, not a save or delivery.

Undo uses the shared editor-assist rules: only a field still holding the
revision's value returns to its earlier value. Later edits survive. Undo itself
is another unsaved working change. Sending or cancelling clears active review
history without removing the final delivery receipt.

### Card preview and links

The card shows the subject/title, recipients/attendees and five rendered body
lines immediately. **Show More** / **Show Less** appears only for overflow or a
shortened server preview. HTML goes through the existing locally vendored
DOMPurify boundary, preserving safe prose and links without scripts, styles,
remote images, forms or embeds.
While the local sanitizer is loading, the card shows a preparing-preview status.
If it fails, the body stays hidden with an explicit error and a local-asset retry;
raw HTML source is never used as a preview fallback.

Resource links describe their actual destination: draft, verified sent message,
legacy retained draft, or created calendar event. A pending sent-copy link does
not point back to a stale draft or enable another send. Microsoft 365 acceptance
does not establish recipient delivery.
While `link_pending` is true, the existing card refresh cycle checks status
read-only; backend backoff bounds actual Graph lookups. A resolved
`link_status: available` enables the verified sent-message link. Exhaustion
changes only the link to `unavailable`, with an explicit Outlook Sent Items
notice. The action remains accepted, without exposing a stale draft URL or
offering another send.

### File structure

Frontend sources under `application/v2_ui/src`:

- `components/approvals/PendingActionCard.tsx` and `PendingActionBody.tsx`
- `components/approvals/PendingActionEditor.tsx` and `usePendingActionReview.ts`
- `lib/pendingActionReview.ts` and `stores/pendingActionReviewStore.ts`

Backend review/history services:

- `application/single_app/functions_m365_pending_review.py`
- `application/single_app/functions_m365_review_history.py`
- `application/single_app/route_backend_msgraph_pending_actions.py`

## Usage Instructions

1. Read the outgoing action card and expand a long body if needed.
2. Choose **Edit** on a manual-review action you own.
3. Change email To/Cc/Bcc, subject, body and body format. For calendar, check title,
   attendees, start/end, timezone, location, body and the existing Teams option.
4. Optionally use **Ask AI & history** to propose a change. On mobile, switch
   between **Draft** and **Ask AI & history** without losing the working copy.
5. Review changed fields and **Save changes**. Use **Undo this change** to revert
   eligible fields, then Save again.
6. Close the editor and explicitly choose **Send** or **Cancel** on the card.

Cancel/Escape asks before discarding unsaved edits. A failed save keeps the working
copy available. **Reload saved draft** explicitly replaces that working copy with
the latest authorized server material after confirmation.
Closing also refreshes the card's saved material and revision, including after
discarding an AI suggestion. This refresh never sends or saves the suggestion;
the next explicit Send uses the refreshed saved action.

## Testing and Validation

- `functional_tests/test_v2_pending_review_logic.mjs` executes real typed field
  proposals, safe undo, owner/manual gates, history normalization, assist-revision
  adoption and CSRF-protected request contracts.
- `ui_tests/test_v2_pending_review_editor.py` drives real React components with
  the actual compiled theme at desktop/mobile widths. Coverage includes direct
  and AI saves, reopen/history paging, later-edit-safe undo, stale AI rejection,
  recipient typing, discard, configurable AI availability and sanitized HTML.
- `ui_tests/test_v2_m365_pending_action_cards.py` covers live/reloaded card
  placement, keyboard expansion and explicit mocked Send/Cancel.
- `functional_tests/test_m365_pending_review.py` covers the backend service
  boundaries. All Graph/delivery calls in development validation are mocked.

The editor does not add recurrence, attachments, retroactive draft cleanup,
sent-message editing, a new send policy, or an extra AI approval gate. External
Outlook edits are not made atomic by a pre-send version check.
