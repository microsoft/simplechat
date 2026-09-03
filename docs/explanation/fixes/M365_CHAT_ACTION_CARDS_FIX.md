# Microsoft 365 chat action cards (v0.261.038)

Fixed in version: **0.261.038**

Version update: `application/single_app/config.py`.
Associated issue: #1493. Pull request: #1497.

## Issue and root cause

Manual Calendar and Email tools saved an `msgraph_pending_actions` record and
instructed the user to send or cancel from an action card. Workflow activity
rendered those records, but Chat did not consume them. A successful tool result
could therefore produce "ready for review" text with no controls.

Rendering buttons alone was insufficient. Interactive records lacked the
durable execution binding used by workflow delivery, the older interactive
send path had no conditional claim, and countdown rendering could submit a
send. Those paths needed one authoritative state machine rather than
independent executable copies of the action.

## Delivery contract

`functions_m365_action_cards.py` carries request-owned references from the
successful pending-record producer. Chat emits `m365_pending_action` SSE events
and includes `m365_pending_actions` in normal/final responses. Message metadata
retains `m365_pending_action_ids`; current, viewer-specific state is resolved
again for history and recovery. Model prose, display names, and compacted
citations are not authority to generate a card.

Shared-conversation streams remap cards to the visible conversation and preserve
them on interrupted responses. Shared event caches contain action references,
not the sender's private card DTO. Each subscriber's history/replay resolves
current read-only or owner controls; a shared refresh must also name an
authorized conversation.

`functions_msgraph_pending_actions.py` validates new bindings and creates the
record without overwriting another action. Its projection exposes allowlisted
summary fields, an opaque revision, and server-computed controls. The owner
can inspect the actual body and recipients; shared viewers cannot inspect
private bodies or recipient/BCC lists. A 4,000-character list preview is
explicitly incomplete and disables Send until the owner loads the full detail.

The existing `/api/msgraph/pending-actions` URLs remain the compatibility API.
Send, Send now, and Cancel require the signed-in owner, the M365 CSRF token, and
`{"expected_version": "the reviewed revision"}`. List/recovery queries are bounded
and paginated. Owner queries use single-partition ordering; shared-conversation
pagination uses a streamable cross-partition query compatible with the Python
Cosmos SDK. Storage failure is an error, not an empty successful inbox.

## Authorization and state

`functions_m365_pending_delivery.py` and `functions_m365_runtime.py` supply a
shared conditional-claim path while keeping chat and workflow authorization
distinct. Each Send rechecks the original subject, tenant/cloud, current
conversation audience, selected agent/action, and enabled operation. Workflow
delivery also rechecks its Run as binding and current workflow.

Competing clicks, tabs, and timer/send-now races cannot claim independent
deliveries. A stale card refreshes for review. Authentication recovery and
source-sharing decisions return to the existing card; they do not rerun the
agent or implicitly send it.

Cancellation records a local terminal state before any mailbox operation.
It cannot recall an already-claimed send. Timers and workers do not retry
potentially successful remote writes: an interrupted result, missing created
event identifier, or expired in-flight claim becomes recovery-required.
Microsoft Graph's event
[`transactionId`](https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0)
is set to the pending ID as an additional duplicate-request safeguard, not a
promise of distributed exactly-once delivery.

Interactive delayed sends keep the existing bounded in-process timer and
ephemeral token. After a lost timer or restart, overdue interactive records
require manual review. Workflow scheduling continues to acquire its approved
Run as credentials. Neither browser rendering nor countdown expiry posts Send.

## Reviewed email content and retained drafts

Graph's documented
[`message/send`](https://learn.microsoft.com/en-us/graph/api/message-send?view=graph-rest-1.0)
contract does not provide a conditional content-version send. SimpleChat
therefore checks that the Outlook draft is unchanged and still a draft, then
sends the frozen reviewed payload through
[`me/sendMail`](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0).

The original Outlook draft is retained after Send and Cancel to avoid deleting
concurrent edits. The card states this explicitly; users must not send that
draft a second time. HTTP 202 is acceptance for sending, not proof of delivery
to every recipient. If draft creation succeeds but action storage fails, the
tool reports the preparation problem instead of claiming a confirmed review
card exists. Inspect Approvals and Outlook before retrying.

## User experience and compatibility

`static/js/m365-pending-actions.js` renders the same local, accessible component
in Chat, Approvals, and workflow activity. Live events, final responses, and
history deduplicate by the authoritative pending ID. Failure and recovery states
remain visible, including actions prepared before a model or stream failure.

Existing unbound records are not silently assigned a current action. They
remain visible and cancellable, with an explicit requirement to prepare a new
review before sending. Deployment does not send or recreate historical drafts.
Immediate mail/invitation operations and marking messages read retain their
existing tool-result receipts and have no extra Send button. Sign-in, sharing,
analysis, and Run as approvals retain their specialized flows.

Commercial, Government, and custom cloud endpoints remain configured by the
deployment. The repair adds no application-permission or service-principal
fallback.

## Conversation lifecycle

Personal and bulk deletion, collaboration cleanup, retention, and the legacy
approved group-deletion path use `cancel_m365_conversation_deliveries()` after
authorizing the destination. Cleanup conditionally stops pending, scheduled,
and review-required intents without acquiring credentials or calling Graph.
An already-claimed send can still finish; deleting a conversation does not
recall mail or invitations. Existing Outlook drafts remain in the mailbox.
Storage failures or unresolved revision conflicts stop cleanup rather than
silently leaving an unclaimed delivery active.
Existing-chat updates use replacement writes, so a finishing chat or analysis
response cannot recreate a conversation that was deleted while it was running.

Shared cleanup verifies both sides of each backing-conversation link before
touching its deliveries. A co-owner can remove the shared destination and stop
its outgoing intents without deleting the creator's retained personal history.
The retention scheduler initializes the delivery service before its first
cleanup pass instead of depending on the workflow scheduler's startup order.

Forks, historical collaboration copies, and data transfers remove pending-action
IDs and structured card DTOs, including copies in citation metadata. They keep
ordinary historical text and do not cancel or recreate the original action.
Normal source-to-shared message mirroring remains a projection of the same
logical conversation, not a new independent delivery destination.

## Validation

The focused suites execute real application boundaries with external I/O
isolated:

- `test_m365_action_card_api.py`, `test_msgraph_pending_actions.py`: storage,
  owner/CSRF/revision checks, complete-content review, pagination, and safe DTOs.
- `test_m365_pending_delivery.py`, `test_m365_pending_authorization.py`: claims,
  races, draft edits, current authority/cloud checks, cancellation, and recovery.
- `test_m365_action_card_references.py`, `test_m365_chat_action_cards.py`,
  `test_m365_collaboration_action_cards.py`: authoritative references, real
  chat/stream routes, reference-only shared broadcasts, persistence, and history.
- `test_m365_conversation_lifecycle.py`: conditional cancellation, authorized
  deletion/bulk cleanup, independent copies, linked-source checks, archival,
  cancellation conflicts, and first-tick retention initialization.
- `test_m365_pending_action_cards.js` and
  `ui_tests/test_m365_pending_action_cards.py`: local browser controls, current
  state, safe rendering, and no send from render/countdown/reconnect.
- Existing provider, connection, workflow, SDK-contract, route-policy, and
  fresh web/scheduler import suites preserve adjacent behavior.

Offline checks do not certify live tenant consent or provider availability.
No live email or invitation is sent during these regressions. The deployment
owner should first check a newly prepared manual action without sending, then
use explicitly authorized test recipients for delivery smoke checks.
