# Unrelated M365 Chat Warnings and Session Recovery

Fixed/Implemented in version: **0.261.338**

Application version: `application/single_app/config.py`.

## Issue and root cause

A React V2 conversation with no Microsoft 365 work could show an outgoing-actions
permission banner. Every conversation discovers saved actions in the background,
including on focus, reconnect and reply completion. A failed list request alone
made the M365 section visible, and every list HTTP 403 was described as an M365
permission denial even when it was an app-wide access response.

In the reported incident, **Repeat on a schedule** also failed with a connection
message until the page was refreshed. That message comes from a rejected fetch,
not proof of an expired Graph token or app session. Without the original response
trace, the incident's upstream authentication or network cause remains unconfirmed.

## Changes

`PendingActionSlots.tsx` requires current-conversation action evidence or explicit
action navigation before showing background list errors. Discovery still runs:
an orphaned saved action can appear even when no visible message references it.
The store retains failures, blocks unsafe action changes, and exposes contextual
recovery if action evidence arrives later.

`apiClient.ts` distinguishes explicit app-session responses and recognized sign-in
redirects from provider reconnect/consent, object-level denials and server errors.
Ambiguous protected-request transport failures may trigger one shared read-only
bootstrap verification, with a five-second timeout and a 15-second automatic-check
cooldown. A failed probe does not establish expiry. Neither JSON nor multipart
requests are replayed.

`appSessionStore.ts`, `bootstrapStore.ts` and `SessionNotice.tsx` keep runtime
recovery separate from startup failure state. One notice in `AppShell.tsx` offers
the existing sign-in flow in a new tab and **Check sign-in**, preserving the mounted
chat, composer and open schedule form. Late bootstrap reads cannot clear a newer
expiry signal. A changed account cannot replace the current bootstrap; users must
copy unsaved text and explicitly reload. New API writes are blocked while the app
knows sign-in is required or the account has changed.

`workflowPlanReplay.ts` reports confirmed app-session failures accurately.
Opening **Repeat on a schedule** still performs reads only; saving or enabling a
workflow requires a separate explicit action.

No backend authorization, Graph permissions, token lifetime, delivery policy or
classic UI behavior changes.

## Validation

| Before | After |
| --- | --- |
| An unrelated failed action-list read could create an M365 permission panel. | Background failures remain internal until actual action context exists. |
| Runtime expiry could surface only as disconnected feature errors. | Explicit app-session failures produce one app-level recovery notice. |
| A fetch rejection could only be reported as connectivity failure. | A bounded bootstrap check can confirm expiry; inconclusive checks remain neutral. |
| A full reload was needed to reset the affected interface. | Same-account sign-in can be confirmed in place; retry remains user-initiated. |

Runtime regression coverage executes real API, bootstrap, replay and pending-action
modules in `functional_tests/test_v2_app_session_recovery.mjs`, alongside the existing
bootstrap, pending-action and replay suites. Browser coverage in
`ui_tests/test_v2_m365_pending_action_cards.py` checks unrelated 401/403/500 reads,
focus/online refreshes, late action evidence and contextual recovery. Tests in
`ui_tests/test_v2_workflow_plan_replay_card.py` exercise desktop/mobile session
recovery with the real shell, retained draft DOM, retained schedule fields and no
automatic POST replay. HTTP boundaries are mocked; these tests do not prove the
cause of the original production incident.

The affected browser suites, runtime regression suites, pending-action functional
wrapper, production V2 build, TypeScript check and documentation coverage/quality
checks passed. The UI mechanical detector reported no findings.

See [V2 pending-action cards](../features/V2_M365_PENDING_ACTION_CARDS.md) and
[chat sign-in controls](../../reference/chat-controls.md#react-v2-sign-in-recovery).
