# Orchestration Microsoft 365 Approval and Retry Flow Fix

**Version: 0.261.304**

Fixed in version: **0.261.304**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

With **Orchestrate** on, a user asked "using my sharepoint documents, what is EVA
Swab Tool?". The plan's **Use an action** step with the user's **M365 SharePoint**
action stopped with "This step needs your approval before it can use Microsoft 365.
Review it in Approvals, then select Retry from failed step", and the answering step
was skipped. To get an answer, the user had to:

1. Leave the conversation for **Approvals**, decide there, and come back.
2. Select **Retry from failed step** and confirm "Retry this failed step?". The
   confirmation stayed on screen, busy, until the whole retry finished.
3. Read the answer under the original "The request could not be completed." message,
   which stayed in the thread.
4. Skip past a "Saved execution attempt - Attempt 2" box with **View previous attempt**
   and **Review saved attempt** under the answer.

A new conversation asking the same question later didn't stop at all, which made the
first approval look arbitrary.

## Root cause

### Why the step asked for approval

The conversation was private, so it wasn't a source-sharing approval:
`authorize_sources()` returns immediately for a conversation that isn't shared. The
stop was the **extended-analysis** guard. A SharePoint or OneDrive read that goes past
a quick read needs the user's approval while their per-source preference is **Ask**,
which is the default. A quick read covers at most 3 downloads, a 25 MB file and 12,000
tokens of file content (`M365_FAST_DOWNLOADS`, `M365_FAST_FILE_BYTES` and
`M365_FAST_CONTEXT_TOKENS` in `functions_m365_retrieval.py`). A NASA technical report
easily exceeds 12,000 tokens.

Choosing **Always allow deeper analysis** in Approvals saves that preference for the
source, which is why the next conversation didn't ask. The preference can also be set
ahead of time under **Settings > Preferences > Connected accounts > Microsoft 365
sharing > Extended analysis**. Nothing in the chat said any of this.

### Why the chat could only send the user to Approvals

`OrchestrationM365Error` kept the pending approval's id, but `build_failure()` and
`safe_failure()` kept only the failure's code, step, capability, provider status and
sources. The browser never learned which approval the step was waiting on.

### Why the confirmation appeared and stayed open

- `action_invoke` is an external-effect capability, so every failed action step was
  `effects_uncertain`, and `recovery_projection()` required confirmation. That was
  needed even for a Microsoft 365 step, although `step_m365_context()` removes the
  send, invite and mark-as-read functions from every plan step, so a Microsoft 365
  plan step can only read data.
- `retryOrchestrationRun()` and `runPreparedOrchestrationRetry()` awaited
  `executeSavedPlan()`, the whole streamed run, before returning. The dialog's
  `busy` state, and the dialog with it, lasted until the retry finished.

### Why the stopped attempt and the attempt box stayed

A retry saves its answer as a new assistant message and keeps the earlier attempt's
message, linked by `metadata.orchestration.retry_of_run_id`. Nothing hid the earlier
message, so it stayed in the thread. It was also sent to the model as history on every
later turn, in both `build_conversation_snapshot()` and
`build_conversation_history_segments()`. `OrchestrationRecoveryNotice` treated any
message with a `retry_of_run_id` as needing a notice, so a successful retry showed
"Saved execution attempt".

## Changes

### The failure carries the approval

`build_failure()` keeps an `approval_id` on an `m365_approval_required` failure, and
`safe_failure()` and `failure_from_exception()` carry it through. Only an id in the
shape the application mints, `m365-` and a 64-character lowercase SHA-256 digest, is
kept; anything else is dropped. The V2 normalizer applies the same check. The
approvals API still checks that the signed-in user is the approval's subject before
showing or deciding it.

### The approval is decided in the chat

The stopped message's recovery notice renders `M365ApprovalInlineCard` for an
`m365_approval_required` failure with an approval id. The card:

- Loads the approval with `GET /api/m365/approvals/<id>`.
- For a pending extended-analysis approval, explains why the step stopped from the
  approval's recorded counts, for example "To answer, this step needs to read more
  (about 18,400 tokens of file content, 1 file, 2.4 MB) than a quick read covers".
- Offers **Allow this time**, **Always allow for SharePoint** (or OneDrive) and
  **Quick read only**. Each choice is posted to
  `POST /api/m365/approvals/<id>/decision` with the Microsoft 365 CSRF token, and the
  plan continues only after the decision is saved.
- For an approval already decided, for example on the Approvals page, offers
  **Continue**.
- Links to the Settings card that holds the Extended analysis preference, and falls
  back to the V2 Approvals link, with **Retry from failed step**, for any other
  approval type or an approval it can't open.

The card replaces the notice's generic failure text, recovery lines and retry button,
so there is one clear next step.

### Microsoft 365 stops retry without confirmation

`recovery_projection()` no longer counts a failed step as effect-uncertain when it is
an `action_invoke` step whose failure is in `M365_STEP_FAILURE_CODES`. Such a step ran
only its one Microsoft 365 action, which can only read data in a plan.
`prepare_retry()` recomputes the same projection, so the server, not the browser,
decides that no confirmation is needed. **Ask an agent** steps keep the confirmation,
because an agent can load actions that send or change data. So do action steps that
failed for any other reason.

### The confirmation closes when the retry starts

`launchSavedPlan()` starts `executeSavedPlan()` without awaiting it.
`executeSavedPlan()` claims the run and enters the streaming state before its first
await, so the conversation stays busy and no second retry can start, while the
confirmation and the retry button are released as soon as the retry is admitted. A
retry whose progress can't be followed is reconciled with the saved run.

### The retry's answer replaces the stopped attempt

- `supersededOrchestrationRunIds()` and `isSupersededOrchestrationAttempt()` in
  `lib/orchestration.ts` find the runs a later attempt in the thread retried.
  `MessageList` hides those assistant messages, as it hides a workflow post replaced
  by its reply. They are read from saved message metadata, so they stay hidden after a
  reload.
- `functions_orchestration_attempts.py`, which imports only the standard library, does
  the same on the server. `build_conversation_snapshot()`,
  `build_conversation_history_segments()` and `_build_export_entry()` leave replaced
  attempts out of the model's history and out of exports. The messages stay stored.
- `collectConversationGeneratedFiles()` and `visibleGeneratedDocuments()` in
  `lib/conversationGeneratedFiles.ts` skip replaced attempts too. The V2 Documents
  drawer lists the files and agent documents of the replies the thread shows, so a
  hidden attempt's files aren't listed either.
- A completed retry shows no recovery notice. While a newer attempt has no saved
  answer yet, the earlier attempt shows one line, "A newer attempt of this plan
  exists.", with **View current attempt**.
- **Message details** on a retried answer shows the attempt number with **View
  previous attempt** and **Review saved attempt**.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_schema.py` | `approval_id` on `m365_approval_required` failures, validated by `_m365_approval_id()`. |
| `functions_orchestration_recovery.py` | `_stopped_without_effects()` and `_effects_uncertain()` exempt Microsoft 365 action stops from confirmation. |
| `functions_orchestration_attempts.py` | New: finds and excludes replaced attempts' messages. |
| `functions_orchestration_context.py` | `build_conversation_snapshot()` leaves replaced attempts out. |
| `route_backend_chats.py` | `build_conversation_history_segments()` leaves replaced attempts out. |
| `route_backend_conversation_export.py` | `_build_export_entry()` leaves replaced attempts out. |
| `v2_ui/src/components/chat/M365ApprovalInlineCard.tsx` | New inline approval card. |
| `v2_ui/src/components/chat/OrchestrationRecoveryNotice.tsx` | Renders the card, the one-line notice for a replaced attempt, and no notice for a completed retry. |
| `v2_ui/src/components/chat/MessageList.tsx` | Hides replaced attempts. |
| `v2_ui/src/components/chat/MessageInspector.tsx` | Attempt links in **Message details**. |
| `v2_ui/src/lib/orchestration.ts` | `approval_id` on failures, and the replaced-attempt helpers. |
| `v2_ui/src/lib/orchestrationController.ts` | `launchSavedPlan()`; retries resolve when admitted. |
| `v2_ui/src/lib/m365Links.ts` | `M365_SHARING_PREFERENCES_HREF`, the card's in-app link to the Microsoft 365 sharing card in Settings. |
| `v2_ui/src/lib/conversationGeneratedFiles.ts` | The Documents drawer skips replaced attempts' files and agent documents. |
| `config.py` | Version `0.261.304`. |

## Validation

### Tests

- `functional_tests/test_orchestration_m365_approval_retry_flow.py`:
  - Approval ids survive failure building and re-reading only in the minted shape.
  - Through the real retry route, a Microsoft 365 action stop retries with
    `confirm_external_effects: false` and runs only the stopped work.
  - Agent steps, and action steps that failed otherwise, are still refused with
    `confirmation_required`.
  - Replaced attempts are left out of orchestration history, chat history and
    exports.
- `ui_tests/test_v2_orchestration_m365_inline_approval.py` runs the real notice,
  card, controller, stores, message list, inspector and Review drawer in Chromium. It
  checks that:
  - The card explains the stop and each choice is saved before the plan continues.
  - No confirmation appears, and the answer replaces the stopped attempt with no
    attempt notice.
  - A decided approval offers **Continue**, and an approval that can't be opened
    falls back to Approvals.
  - **Message details** keeps the attempt links.
  - A confirmed retry's dialog closes while the retry is still running.
- `ui_tests/test_v2_orchestration_recovery_backend.py` now checks that, after a
  reload, the thread shows only the retry's answer.
- Hand-built test namespaces for `_build_export_entry()` and
  `build_conversation_history_segments()` gained the new helper.
- After integrating Microsoft 365 source citations, the Analyze route harness also
  loads the real citation attachment and conversation aggregation helpers. Its 29
  tests pass independently, alongside the citation/retry backend and browser tests.
- `functional_tests/test_v2_workflow_run_tracking_xss_guardrail.py` pins
  `M365_SHARING_PREFERENCES_HREF` with the other Microsoft 365 links, which the XSS
  checker trusts by name.
- `functional_tests/test_v2_drawer_generated_files_logic.mjs` checks that a replaced
  attempt's files and agent documents leave the Documents drawer once the retry exists.

### Before and after

| Before | After |
| --- | --- |
| The stopped message linked to Approvals; the user decided there, came back and retried. | The stopped message explains why and offers the decision; choosing continues the plan. |
| Retrying a Microsoft 365 stop asked "Retry this failed step?". | No confirmation for a Microsoft 365 action stop, enforced by the server. |
| A confirmation stayed open, busy, until the whole retry finished. | It closes as soon as the retry starts. |
| The stopped attempt's message stayed in the thread and in the model's history. | The retry's answer replaces it in the thread, history, exports and Documents drawer; it stays stored. |
| A successful retry showed "Saved execution attempt - Attempt 2". | No notice; the attempt links are in **Message details**. |

## Limitations

- The card explains the stop with the counts the approval records. It doesn't name
  the files: the retrieval budget that requests the approval tracks counts, not file
  names.
- Source-sharing and Run as approvals still link to Approvals. Plan steps don't ask
  for source sharing; the user's own request is their consent in a shared
  conversation.
- Normal chat with Orchestrate off still decides Microsoft 365 approvals in
  Approvals. Its request resumes on its own after the decision.

## Related

- [Orchestration Microsoft 365 file action evidence fix](ORCHESTRATION_M365_FILE_ACTION_EVIDENCE_FIX.md)
- [Microsoft 365 actions in plans](../../admin/orchestration.md#microsoft-365-actions-in-plans)
- [Orchestration failure recovery controls](../../reference/chat-controls.md#orchestration-failure-recovery-v2-interface)
