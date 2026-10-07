# Orchestration Shared Conversations Fix

**Version: 0.261.269**

Fixed in version: **0.261.269**, recorded in
`application/single_app/config.py`.

Fixes [#1659](https://github.com/microsoft/simplechat/issues/1659). This affects the
React V2 branch (`paullizer-react-v2-ui`) and deployments built from it.

## Issue

In a shared conversation with **Orchestrate** on, "@person hey" was sent to the model,
which planned, reasoned and answered. With Orchestrate off, the same message was
posted to that person, as intended.

Orchestrated questions and answers also never reached the shared thread, so other
participants didn't see them. Microsoft 365 requests in shared conversations waited
for a sharing approval in chat and were refused outright in plans.

## Root cause

1. **No shared send rule.** `Composer.submit` sent every Orchestrate message to
   `startOrchestrationPlan`. Manual sends apply the shared conversation rule in
   `chatStore.sendMessage`, which posts a message that addresses only people.
2. **A private copy.** The plan route's `_ensure_conversation` didn't know about
   shared conversations. For a shared conversation's ID it created a personal
   conversation with that ID, owned by the sender, so each plan and answer lived in a
   private copy that other participants never saw.
3. **Microsoft 365 consent.** Shared conversations needed a source-sharing approval
   before Microsoft 365 data was read, and `step_m365_context` refused plan steps in
   shared conversations, because approvals resume chat requests, not plan steps.

## Changes

### Composer routing

`Composer.submit` applies `sharedConversationTarget()` (new in `lib/mentions.ts`),
the rule `chatStore.sendMessage` now also uses. A message that addresses only people
is posted through the normal shared send, with its mentions and reply. A message
that addresses the assistant is planned only for the person who started the
conversation. Anyone else's request is answered the classic way. The plan request
carries the AI target, mentions and reply, so the question can be posted as asked.

`mergeCollaborationMessage` (`stores/chatStore.ts`) matches a shared copy and the
run's own message through `metadata.source_message_id`, in either order, so neither
appears twice.

### A hidden backing conversation

`_ensure_conversation` (`route_backend_orchestration.py`) now resolves a shared
conversation's ID to a hidden backing conversation with the same ID. It belongs to the
person who started the shared conversation and has the fields of the classic
assistant's hidden source conversation: `conversation_kind='collaboration_source'`,
`collaboration_conversation_id`, `is_hidden`, and the shared conversation's workspace
lock. Keeping the ID keeps every plan, run and result where the V2 client already
looks for them, and memory rules treat the conversation as shared.

- Only the person who started the conversation can plan there. Another participant
  gets "Only the person who started this shared conversation can use Orchestrate
  here." Anyone who isn't a participant gets the same answer as for a conversation
  that doesn't exist.
- A private copy that an earlier version created for that person becomes the backing
  conversation. Another person's private copy is never adopted. The person who started
  the conversation is told that Orchestrate can't be used there and why.
- A backing conversation isn't announced as a new conversation, because the browser
  already holds its ID.
- The conversation list treats any personal record with a shared conversation's ID
  as part of that shared conversation, so earlier private copies no longer appear.
- Deleting the shared conversation, by its owner or by retention, deletes the backing
  first (`delete_orchestration_backing`). Its runs are fenced and their files enrolled
  for output cleanup, and its messages, thoughts and record are archived or deleted, as
  for a personal conversation. A co-owner who didn't start the conversation removes it
  without deleting its creator's plans, as with the classic source conversation.

### Lookups by a shared conversation's ID

Because the backing has the shared conversation's ID, every lookup that reads personal
storage first now treats it as part of the shared conversation, using
`is_shared_conversation_backing()` in `collaboration_models.py`. Without this, the
backing would have taken over the shared conversation for anyone looking it up by ID:

- `/api/conversations/<id>/kind` reports the shared conversation, so reloading the page
  or following a link never reopens it as a personal chat. It also does so for an
  earlier private copy, for anyone who can still see the shared conversation.
- Personal routes treat the backing as absent (`_authorize_personal_conversation_read`).
  Images, summaries, exports, scope lock, agent citation details, MCP tools and posts
  through SimpleChat operations then use the shared conversation, for every participant.
- `/api/chat/stream` never writes into the backing, and chat uploads go to the shared
  conversation's classic source conversation.
- Microsoft 365 action cards and audit records keep resolving to the classic source
  conversation (`resolve_m365_audit_conversation_id`).

### Posting to the shared thread

`functions_orchestration_collaboration.py` (new) posts the question when the plan is
saved and the final answer when the run finishes, through the same storage helpers
as the classic shared assistant. Each is posted once, keyed by the run message's ID.
The answer replies to its question, and each post publishes
`collaboration.message.created` and the participants' notifications. A failure to
post is logged and never changes the run's own answer.

- Each post rechecks that the backing's owner is still a participant who started the
  conversation, and that a group conversation still allows chat. If not, nothing is
  posted.
- A run republishes its answer under the same ID when it finishes later, for example
  after a waiting step completes or the run times out. The shared copy is then updated
  in place and `collaboration.message.updated` is published, so participants never keep
  the earlier text.

### Microsoft 365: your request is your consent

`M365ExecutionContext` has a new `shared_by_request` flag. Chat requests and plan steps
in a shared conversation set it, because the user is asking for their own data. It
can't be set for a workflow, and it isn't part of the approval fingerprint. A reviewed
email or invitation keeps the flag with its delivery (`functions_m365_pending_delivery.py`),
so sending it needs no approval its request didn't need.

`M365ApprovalService.authorize_sources` grants such a request without a pending
approval or notification and records one `shared_by_request` audit event for each
request and source. The grant has the shape of a request-only approval, so publishing
file evidence the request captured references that audit event. History publication
and workflow Run as approvals are unchanged. `step_m365_context` no longer refuses
shared conversations and uses the shared conversation's real audience.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_collaboration.py` | New. Backing fields, owner-only authorization, posting and refreshing the question and answer, and deleting the backing. |
| `route_backend_orchestration.py` | Backing conversation in `_ensure_conversation`, bounded shared details, posting the question. |
| `functions_orchestration_execution.py` | Posts the final answer. |
| `collaboration_models.py` | `is_shared_conversation_backing()`. |
| `route_backend_conversations.py` | Earlier private copies and backing records stay out of the conversation list and hidden count; kind, personal routes, summary and scope lock use the shared conversation. |
| `route_backend_conversation_export.py`, `functions_conversation_metadata.py`, `functions_mcp_server_tools.py`, `functions_simplechat_operations.py`, `route_frontend_conversations.py`, `route_frontend_chats.py`, `route_backend_chats.py` | Lookups by a shared conversation's ID use the shared conversation. |
| `functions_collaboration.py` | Deleting a shared conversation deletes its backing. |
| `functions_orchestration_artifacts.py` | `is_retained_orchestration_file()`, shared by both deletion paths. |
| `functions_m365_context.py`, `functions_m365_approvals.py`, `functions_m365_runtime.py`, `functions_m365_pending_delivery.py` | Consent by request. |
| `v2_ui/src/lib/mentions.ts`, `v2_ui/src/stores/chatStore.ts`, `v2_ui/src/components/chat/Composer.tsx` | The shared send rule, routing, and de-duplication. |
| `config.py` | Version `0.261.269`. |

## Validation

### Tests

- `functional_tests/test_orchestration_shared_conversations.py` drives the real
  orchestration routes over HTTP with the real collaboration storage functions. It
  checks the backing conversation and its lock, that no new conversation is
  announced, the posted question with its mentions and AI target, the answer posted
  as a reply, the live events, and that posting is idempotent. Another participant
  is asked to turn off Orchestrate, a non-participant learns nothing, the starter's
  earlier private copy is adopted, and another person's is not. A republished answer
  updates its shared copy, nothing is posted after the starter leaves, and deleting
  the shared conversation deletes the backing and fences its runs.
- `functional_tests/test_orchestration_shared_backing_lookups.py` runs the real
  lookups with a backing present: kind, personal routes and images, scope lock,
  metadata, exports, MCP tools, the chat stream, uploads and Microsoft 365 cards.
  Sixteen of these checks fail without the lookup changes.
- `functional_tests/test_m365_shared_request_consent.py` runs the real approval
  service: a shared request is its own consent with one audit event per request and
  source, without the flag a shared request still needs an approval, private
  conversations are unchanged, only interactive shared requests can carry the flag,
  and it doesn't change the approval fingerprint. A reviewed delivery keeps the
  consent, and one recorded before 0.261.269 still asks.
- `functional_tests/test_m365_provider_core.py` publishes file evidence captured by
  a shared request without an approval, end to end. With the earlier grant shape this
  failed with `KeyError: 'approval_id'`.
- `functional_tests/test_orchestration_m365_actions.py` replaces the shared
  conversation refusal with a step that reads mail for the shared audience, and a
  step that stops once the user is no longer a participant.
- `functional_tests/test_orchestration_collaboration_codeql_alerts.py` imports the
  real collaboration modules cold in fresh processes, in both orders, in normal and
  optimized Python, with network access blocked. The orchestration module imports
  collaboration storage lazily, so importing it never initializes Cosmos clients.
  It also checks that every return path of the collaboration mirror helper returns
  three values.
- `functional_tests/test_v2_shared_orchestration_routing.mjs` executes the shared
  send rule and the de-duplication, and checks the composer routing.
- `ui_tests/test_v2_shared_orchestration_routing.py` drives the real Composer in
  Chromium with HTTP doubled: "@Ada …" is posted without a plan, "@Research Assistant …"
  is planned with that agent, its AI target and its mentions, and another
  participant's request goes to the shared assistant stream. All three checks fail on
  0.261.264.

### Before and after

| Before | After |
| --- | --- |
| "@person hey" with Orchestrate on was planned and answered by the model. | It's posted to that person; no model or plan runs. |
| Orchestrated questions and answers stayed in a private copy. | They're posted to the shared thread for every participant. |
| Microsoft 365 in a shared conversation waited for approval in chat and was refused in plans. | The user's own request is their consent, recorded in their audit history. |

## Limitations

- Only the person who started a shared conversation plans in it.
- Other participants see the question and answer, not the plan card or run details.
- Files, images and charts that a plan creates aren't attached to the shared copy of
  the answer.
- The planner reads earlier planned turns, not messages that participants exchanged
  or that the classic assistant answered.
- If an earlier version made a private copy for another participant, Orchestrate stays
  unavailable to the person who started the conversation until that record is
  removed. It is the record in the conversations container whose ID is the shared
  conversation's ID and whose owner is that participant.

## Related

- [Shared conversations](../../admin/orchestration.md#shared-conversations)
- [Microsoft 365 data and approvals](../../guides/microsoft-365-conversation-data.md)
- [Orchestration session-trusted action and agent steps fix](ORCHESTRATION_SESSION_TRUSTED_ACTION_AGENT_STEPS_FIX.md)
