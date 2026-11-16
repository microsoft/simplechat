# V2 Microsoft 365 Pending-Action Cards

## Overview

Implemented in version: **0.261.307**

Email review flow updated in version: **0.261.324** (`application/single_app/config.py`).

Review editor implemented in version: **0.261.325** (`application/single_app/config.py`).

Contextual warnings and app-session recovery fixed in version: **0.261.338** (`application/single_app/config.py`).

Tracking issue: [#1722](https://github.com/microsoft/simplechat/issues/1722), gap 2 (Chat, "M365 pending-action card").

An agent that prepares a Microsoft 365 email or calendar invitation for review saves it as a pending action. The action waits until its owner sends or cancels it, and a notification tells the owner it is waiting. Only the classic chat page drew that card, so every such notification opened classic chat.

The React V2 chat now draws the card itself, with the same controls and safeguards, and a notification about a saved action opens the V2 conversation, scrolls to the card, and highlights it. The link no longer depends on the classic interface being reachable, which matters wherever people are kept in V2.

Dependencies:

* [Microsoft Graph Pending Actions](MSGRAPH_PENDING_ACTIONS.md): the backend this reads and writes. The email review repair adds orchestration stream/history references, not a new delivery policy or setting.
* [Pending Email and Calendar Review](PENDING_REVIEW.md): owner editing, durable AI/revision history and the new draft-to-sent lifecycle.
* [V2 Terms of Use and Approval Requests](V2_TERMS_AND_APPROVALS.md): the Approvals page uses the same card.
* [V2 Notification Bell and Desktop Notifications](V2_NOTIFICATIONS_BELL.md): the notices that link to the card.
* [React V2 UI](REACT_V2_UI.md): the shell and chat page the card lives in.

## Technical Specifications

### Where a card appears

A card sits under the reply that saved it, as it does in classic chat. Placement is worked out once for the whole thread, in this order:

1. The message the action names, when that message is on screen.
2. While a new Orchestrate run prepares the email, beside its originating user turn; ordinary chat uses the streaming bubble.
3. Otherwise the user turn that caused it, when that turn is on screen. This is also where a card sits if its reply was never saved.
4. The last message of the same request, when the action carries a request id.
5. Otherwise the conversation-level section, **Microsoft 365 outgoing actions for this conversation**, so a pending send is never hidden.

When a conversation has a saved action, an action reference, or an explicitly opened action link, that section also carries a failed or partial read of the list ("Outgoing actions could not be loaded. Refresh to recover saved actions; this is not an empty inbox."), **Load more outgoing actions** when the list has another page, and **Refresh outgoing actions**. An optional background lookup failure alone does not show an M365 section in an unrelated chat. Background discovery continues, including discovery of actions missing from visible history; failures remain recorded rather than being treated as empty results. Image, file, and content-safety messages never carry a card.

Confirmed SimpleChat session expiry uses the shared app-level sign-in notice, not this section's permission warning. Microsoft 365 provider reconnect and conversation authorization failures remain separate. See [unrelated-chat warnings and session recovery](../fixes/M365_UNRELATED_CHAT_SESSION_WARNING_FIX.md).

### Where the cards come from

* **Opening a conversation.** The conversation's saved actions are listed with `GET /api/msgraph/pending-actions?conversation_id=<id>&limit=30`, following the continuation token for more. The list is read again when the browser window regains focus or comes back online.
* **History.** Messages loaded from history carry their cards and the ids of any that were not loaded with them. Ids without a card are fetched one at a time with `GET /api/msgraph/pending-actions/<id>?conversation_id=<id>`.
* **A live reply.** The `m365_pending_action` stream frame puts a card on screen while the reply is still streaming. The finishing frame can carry the final cards, which then sit under the saved reply, or `m365_pending_actions_error` when the server could not attach them, in which case the list is read again.
* **A live Orchestrate run.** Creation frames identify the conversation, run, producing step, original user message and request. The run reader rejects stale or cross-conversation frames; its controller gives valid cards to the existing store immediately. Terminal cards and `metadata.m365_pending_action_ids` promote the same cards beneath the final reply. History uses those saved references, not timestamps, subjects, or the newest message. Existing unlinked records keep their fallback section; this does not relink old attempts.
* **After a reply ends.** The conversation's list is read again when a reply finishes or fails, when the reader stops it (once the stop request has been sent, so an action the server saves after that shows on the next read, such as window focus or **Refresh outgoing actions**), and when a reply that was still running is picked up again. An action that the live frames did not deliver, for example after a dropped connection, is on screen before anyone repeats the request.
* **A shared conversation.** Other participants are told which action ids a reply saved, and read the list again. When the server could not list them, the thread says "Microsoft 365 actions were saved, but their cards could not be loaded. Reload the conversation to recover them. Do not repeat the request."

A card taken from message history is checked against the server before Send is available, while one from a live frame is as fresh as the server can make it. Either way, a card ignores a snapshot older than the one it holds, a version it has already moved past, and one that would reopen a finished action, and a response that arrives after the reader has left the conversation is dropped. A scheduled card whose send time has passed, and a card whose send is in progress, ask the server again about every 15 seconds.

### The card

The same `PendingActionCard` is used inline in chat and in the Approvals detail pane, so a card behaves the same wherever it is drawn. It shows recipients, times, location, the first five rendered body lines, and a status. HTML bodies retain safe prose formatting and links through the locally vendored DOMPurify boundary; executable content, styles, remote images and embeds are removed. **Show More** / **Show Less** appears only for overflowing or server-shortened content. Its controls are described in [chat controls](../../reference/chat-controls.md#microsoft-365-outgoing-action-cards):

An email awaiting review says **Ready to review — not sent**. Preparation and sending are separate outcomes: a later failed report does not discard the draft or mark it sent. After the owner sends, **Accepted for sending — recipient delivery is not confirmed** is the primary result. New draft-send actions send the actual Outlook draft; their sent-message link appears only after it is verified. Older retained-draft actions keep their compatibility behavior and an explicitly labeled retained-draft link. Conflict and unknown-outcome warnings remain, and nothing is sent or replayed automatically by the browser.

* **Send** or **Send now** (for a delayed action) submits the version of the action the reader reviewed, so the server can refuse it if the action changed in the meantime.
* **Cancel** stops an unclaimed delivery.
* **Edit** is available only to the owner of an editable manual-review action. The popup loads the complete authorized draft, not a reconstruction of the shortened card. Email exposes To/Cc/Bcc, subject and body; calendar exposes title, attendees, start/end, timezone, location, body and the existing Teams meeting option. **Save changes** persists reviewed edits and refreshes the card. Cancel/Escape discards only unsaved working changes, with a discard confirmation.
* **Ask AI & history** reuses the incumbent assist thread and typed proposal/undo mechanics. AI can suggest changes only to editable fields; it never sends or changes delivery policy. Applied suggestions remain a working copy until Save. Direct/AI revisions and suggestions are loaded from owner-only paged backend history when reopened. Undo preserves fields changed later and also requires Save. Active review history is cleared when the action is sent or cancelled; its final delivery receipt remains.
* **Review full message** or **Review full invitation** loads the complete content when the preview was shortened. Send stays hidden until it has loaded, and reviewing never sends.
* **Reconnect Microsoft 365** renews the Microsoft 365 sign-in for the saved action. It does not resume the chat request or send anything; select Send again afterwards. A saved action that belongs to a workflow links to the workflow's account in Settings instead.
* **Review sharing decision** opens the data-access approval that a send asked for. Approving that decision does not send the action.
* **Refresh status** asks the server for the current state. It never sends.
* Outlook links are labeled **Open draft in Outlook**, **Open sent message in Outlook**, **Open retained draft in Outlook**, or **Open calendar event in Outlook**, according to verified server resource metadata. Accepted sends with no resolved sent-copy link show a link-pending notice, never a stale draft link or another Send button.

Only the owner gets Send and Cancel; both are hidden for anyone else, who sees a read-only note instead. The countdown on a delayed action is informational: delivery is by the server's own timer, and loading an overdue card never submits a send.

### Deep links from a notification

A notification link that names a saved action, such as `/chats?conversationId=<id>&m365_pending_action=<action id>`, now opens V2 chat instead of classic chat.

* From another page, the V2 router opens `/chat?conversationId=<id>&m365_pending_action=<action id>`. On the chat page, a notice for another conversation opens it in place.
* The chat page reads the action id once and removes it from the address, so the final address is `/chat?conversationId=<id>`. A reload or a shared link does not scroll again.
* Once the conversation's messages and saved actions have loaded and the card is drawn, the thread scrolls to it, rings it for about two and a half seconds, and moves keyboard focus to it. Reduced-motion preferences turn the smooth scroll into a jump. Opening a card never sends it.
* A card that the conversation's list does not show is fetched by id. Only if that also fails does the thread say "That Microsoft 365 action is not available in this conversation. It may have been removed, or you may not have access to it." and leave the conversation open.
* An action id that could not be a safe path segment (empty, over 200 characters, `.`, `..`, or containing a slash, backslash, `?`, `#`, or a control character) is dropped, and the conversation still opens.

The Approvals detail pane's **Open conversation** link uses the same address.

Notices about a Microsoft 365 action inside a workflow run still open the classic workflow-activity page, which draws the action beside the run. That is unchanged and out of scope here.

### File structure

Paths are relative to `application/v2_ui/src`.

* `lib/m365PendingActions.ts`: pure rules for which snapshot to trust, where a card belongs, and what a stream frame or history message carries.
* `stores/m365PendingActionsStore.ts`: one store factory. Chat uses a shared instance, so the chat stream handlers, which run outside React, can hand it cards; every Approvals detail builds its own for the one action it shows.
* `components/approvals/PendingActionCard.tsx`: the shared card. `PendingActionsPanel.tsx` is now a thin wrapper that gives it a store.
* `components/approvals/PendingActionEditor.tsx`, `usePendingActionReview.ts`, `PendingActionBody.tsx`: shared responsive owner editor, durable assist integration and sanitized five-line body renderer.
* `lib/pendingActionReview.ts`, `stores/pendingActionReviewStore.ts`: typed review API contracts, editable-field proposal allowlist and isolated working-copy state.
* `components/chat/PendingActionSlots.tsx`: placement for the whole thread, the inline and streaming slots, the conversation-level section, list loading, and the deep-link focus.
* `components/chat/MessageList.tsx`: mounts the placement, the section, and a slot under each bubble.
* `lib/approvalsApi.ts`: `fetchConversationPendingActions` is new, `fetchPendingAction` takes a conversation id, and `PendingAction` carries the extra fields the chat endpoints return.
* `lib/sse.ts`, `lib/types.ts`, `lib/collaborationEvents.ts`, `stores/chatStore.ts`: the stream and shared-conversation wiring, and keeping the store pointed at the open conversation.
* `lib/orchestration.ts`, `lib/orchestrationController.ts`: run-stream creation events, original-turn placement, terminal reconciliation and finish refresh.
* `lib/conversationUrl.ts`, `lib/notificationLinks.ts`, `lib/notificationNavigation.ts`, `pages/ChatPage.tsx`: the `m365_pending_action` parameter, routing, and the one-shot focus.
* `scripts/check_xss_sinks.py`: `chatHrefForPendingAction` is listed as a reviewed same-origin link builder.

## Usage Instructions

Nothing new to enable. Cards appear whenever an agent uses a Microsoft Graph action in manual or delayed delivery mode, as described in [Microsoft Graph Pending Actions](MSGRAPH_PENDING_ACTIONS.md).

* Review the card under the reply. Use **Show More** for a long body, or **Edit** to adjust a manual-review draft. Save any edits before choosing **Send** or **Cancel** on the card.
* Choose a notification in the bell to land on the card in its conversation. The card is outlined for a moment so you can find it in a long thread.
* If a card is missing from a thread, use **Refresh outgoing actions** in the conversation-level section.

## Testing and Validation

Functional tests:

* `functional_tests/test_v2_m365_pending_actions.py`: the wiring across the chat page, stores, stream, collaboration events, routing, and shared card, and a run of the three Node tests below.
* `functional_tests/test_v2_m365_pending_actions_logic.mjs`: snapshot trust, placement, stream and history references, and countdown rules.
* `functional_tests/test_v2_m365_pending_actions_store.mjs`: the store's state machine, including late responses, version safety, polling, and focus.
* `functional_tests/test_v2_m365_pending_actions_stream.mjs`: real chat and orchestration SSE readers/controllers, multiple live cards, saved-reply promotion, failed reports, dropped streams, scoped stale-frame rejection and history recovery.
* `functional_tests/test_v2_app_session_recovery.mjs`: app-session/provider classification, bounded read-only verification, concurrent failures, stale bootstrap responses, identity changes and no mutation replay.
* `functional_tests/test_v2_pending_review_logic.mjs`: owner/manual edit gates, typed proposals, safe undo, working-copy state, history deduplication and CSRF-protected review contracts.
* `functional_tests/test_v2_workflow_run_link_routing.mjs`, `functional_tests/test_v2_notifications_bell.py`, `functional_tests/test_v2_user_settings_memory_m365.py`: updated for the new routing and files.

UI tests:

* `ui_tests/test_v2_m365_pending_action_cards.py`: the real message list with inline, streaming, and conversation-level cards, Send and Cancel, and focus; desktop/mobile Orchestrate preparation, report failure, reference-only reload, keyboard body review and explicit mocked Send/Cancel.
* `ui_tests/test_v2_workflow_plan_replay_card.py`: desktop/mobile session notices, retained composer and schedule-form drafts, explicit same-user recovery and schedule-preview retry without automatic workflow writes.
* `ui_tests/test_v2_pending_review_editor.py`: real desktop/mobile email editing, direct/AI saves, reopening history, focus return, calendar fields, conflict preservation, owner/timed edit denial and sanitized HTML overflow. All send/Graph operations are mocked.
* `ui_tests/test_v2_notifications_bell.py`: a notice for a saved action opens its card in V2 chat from another page, from the chat page, for an action the list does not show, and for one that is gone.
* `ui_tests/test_v2_approvals_and_terms_pages.py` and `ui_tests/test_v2_approvals_dashboard.py`: the Approvals page, which keeps its test ids on the shared card.

## Known Limitations

* A chat request that pauses for Microsoft 365 sign-in or a sharing approval (`m365_sign_in_required`, `m365_approval_required`) still shows as an ordinary stream error in V2 chat, as it did before. This change adds no pause interface for it. The list is read again when the request ends, so any action the request had already saved still gets its card. V2's orchestration notices for Microsoft 365 (`OrchestrationM365Notice.tsx`) are separate and unchanged.
* Notices about an action inside a workflow run open the classic workflow-activity page.
* Delivery policy is unchanged: delayed auto-send still uses the in-process timer described in [Microsoft Graph Pending Actions](MSGRAPH_PENDING_ACTIONS.md).
