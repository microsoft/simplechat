# V2 Microsoft 365 Pending-Action Cards

## Overview

Implemented in version: **0.261.307**

Tracking issue: [#1722](https://github.com/microsoft/simplechat/issues/1722), gap 2 (Chat, "M365 pending-action card").

An agent that prepares a Microsoft 365 email or calendar invitation for review saves it as a pending action. The action waits until its owner sends or cancels it, and a notification tells the owner it is waiting. Only the classic chat page drew that card, so every such notification opened classic chat.

The React V2 chat now draws the card itself, with the same controls and safeguards, and a notification about a saved action opens the V2 conversation, scrolls to the card, and highlights it. The link no longer depends on the classic interface being reachable, which matters wherever people are kept in V2.

Dependencies:

* [Microsoft Graph Pending Actions](MSGRAPH_PENDING_ACTIONS.md): the backend this reads and writes. No route, schema, or setting changed.
* [V2 Terms of Use and Approval Requests](V2_TERMS_AND_APPROVALS.md): the Approvals page uses the same card.
* [V2 Notification Bell and Desktop Notifications](V2_NOTIFICATIONS_BELL.md): the notices that link to the card.
* [React V2 UI](REACT_V2_UI.md): the shell and chat page the card lives in.

## Technical Specifications

### Where a card appears

A card sits under the reply that saved it, as it does in classic chat. Placement is worked out once for the whole thread, in this order:

1. The message the action names, when that message is on screen.
2. While the reply that saved it is still streaming, under the streaming bubble.
3. Otherwise the user turn that caused it, when that turn is on screen. This is also where a card sits if its reply was never saved.
4. The last message of the same request, when the action carries a request id.
5. Otherwise the conversation-level section, **Microsoft 365 outgoing actions for this conversation**, so a pending send is never hidden.

That section also carries the things that belong to the conversation rather than to one reply: a failed or partial read of the list ("Outgoing actions could not be loaded. Refresh to recover saved actions; this is not an empty inbox."), **Load more outgoing actions** when the list has another page, and **Refresh outgoing actions**. Image, file, and content-safety messages never carry a card.

### Where the cards come from

* **Opening a conversation.** The conversation's saved actions are listed with `GET /api/msgraph/pending-actions?conversation_id=<id>&limit=30`, following the continuation token for more. The list is read again when the browser window regains focus or comes back online.
* **History.** Messages loaded from history carry their cards and the ids of any that were not loaded with them. Ids without a card are fetched one at a time with `GET /api/msgraph/pending-actions/<id>?conversation_id=<id>`.
* **A live reply.** The `m365_pending_action` stream frame puts a card on screen while the reply is still streaming. The finishing frame can carry the final cards, which then sit under the saved reply, or `m365_pending_actions_error` when the server could not attach them, in which case the list is read again.
* **After a reply ends.** The conversation's list is read again when a reply finishes or fails, when the reader stops it (once the stop request has been sent, so an action the server saves after that shows on the next read, such as window focus or **Refresh outgoing actions**), and when a reply that was still running is picked up again. An action that the live frames did not deliver, for example after a dropped connection, is on screen before anyone repeats the request.
* **A shared conversation.** Other participants are told which action ids a reply saved, and read the list again. When the server could not list them, the thread says "Microsoft 365 actions were saved, but their cards could not be loaded. Reload the conversation to recover them. Do not repeat the request."

A card taken from message history is checked against the server before Send is available, while one from a live frame is as fresh as the server can make it. Either way, a card ignores a snapshot older than the one it holds, a version it has already moved past, and one that would reopen a finished action, and a response that arrives after the reader has left the conversation is dropped. A scheduled card whose send time has passed, and a card whose send is in progress, ask the server again about every 15 seconds.

### The card

The same `PendingActionCard` is used inline in chat and in the Approvals detail pane, so a card behaves the same wherever it is drawn. It shows recipients, times, location, a body preview that is always plain text, and a status. Its controls match the [classic card](../../reference/chat-controls.md#microsoft-365-outgoing-action-cards):

* **Send** or **Send now** (for a delayed action) submits the version of the action the reader reviewed, so the server can refuse it if the action changed in the meantime.
* **Cancel** stops an unclaimed delivery.
* **Review full message** or **Review full invitation** loads the complete content when the preview was shortened. Send stays hidden until it has loaded, and reviewing never sends.
* **Reconnect Microsoft 365** renews the Microsoft 365 sign-in for the saved action. It does not resume the chat request or send anything; select Send again afterwards. A saved action that belongs to a workflow links to the workflow's account in Settings instead.
* **Review sharing decision** opens the data-access approval that a send asked for. Approving that decision does not send the action.
* **Refresh status** asks the server for the current state. It never sends.
* **Open in Microsoft 365** opens the web link, only when it is an `https` link without credentials.

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
* `components/chat/PendingActionSlots.tsx`: placement for the whole thread, the inline and streaming slots, the conversation-level section, list loading, and the deep-link focus.
* `components/chat/MessageList.tsx`: mounts the placement, the section, and a slot under each bubble.
* `lib/approvalsApi.ts`: `fetchConversationPendingActions` is new, `fetchPendingAction` takes a conversation id, and `PendingAction` carries the extra fields the chat endpoints return.
* `lib/sse.ts`, `lib/types.ts`, `lib/collaborationEvents.ts`, `stores/chatStore.ts`: the stream and shared-conversation wiring, and keeping the store pointed at the open conversation.
* `lib/conversationUrl.ts`, `lib/notificationLinks.ts`, `lib/notificationNavigation.ts`, `pages/ChatPage.tsx`: the `m365_pending_action` parameter, routing, and the one-shot focus.
* `scripts/check_xss_sinks.py`: `chatHrefForPendingAction` is listed as a reviewed same-origin link builder.

## Usage Instructions

Nothing new to enable. Cards appear whenever an agent uses a Microsoft Graph action in manual or delayed delivery mode, as described in [Microsoft Graph Pending Actions](MSGRAPH_PENDING_ACTIONS.md).

* Review the card under the reply, open **Review message body** to read the body, then choose **Send** or **Cancel**.
* Choose a notification in the bell to land on the card in its conversation. The card is outlined for a moment so you can find it in a long thread.
* If a card is missing from a thread, use **Refresh outgoing actions** at the foot of the conversation-level section.

## Testing and Validation

Functional tests:

* `functional_tests/test_v2_m365_pending_actions.py`: the wiring across the chat page, stores, stream, collaboration events, routing, and shared card, and a run of the three Node tests below.
* `functional_tests/test_v2_m365_pending_actions_logic.mjs`: snapshot trust, placement, stream and history references, and countdown rules.
* `functional_tests/test_v2_m365_pending_actions_store.mjs`: the store's state machine, including late responses, version safety, polling, and focus.
* `functional_tests/test_v2_m365_pending_actions_stream.mjs`: stream frames and shared-conversation events reaching the store.
* `functional_tests/test_v2_workflow_run_link_routing.mjs`, `functional_tests/test_v2_notifications_bell.py`, `functional_tests/test_v2_user_settings_memory_m365.py`: updated for the new routing and files.

UI tests:

* `ui_tests/test_v2_m365_pending_action_cards.py`: the real message list with inline, streaming, and conversation-level cards, Send and Cancel, and focus.
* `ui_tests/test_v2_notifications_bell.py`: a notice for a saved action opens its card in V2 chat from another page, from the chat page, for an action the list does not show, and for one that is gone.
* `ui_tests/test_v2_approvals_and_terms_pages.py` and `ui_tests/test_v2_approvals_dashboard.py`: the Approvals page, which keeps its test ids on the shared card.

## Known Limitations

* A chat request that pauses for Microsoft 365 sign-in or a sharing approval (`m365_sign_in_required`, `m365_approval_required`) still shows as an ordinary stream error in V2 chat, as it did before. This change adds no pause interface for it. The list is read again when the request ends, so any action the request had already saved still gets its card. V2's orchestration notices for Microsoft 365 (`OrchestrationM365Notice.tsx`) are separate and unchanged.
* Notices about an action inside a workflow run open the classic workflow-activity page.
* The backend is unchanged: delayed auto-send still uses the in-process timer described in [Microsoft Graph Pending Actions](MSGRAPH_PENDING_ACTIONS.md).
