# Orchestration Microsoft 365 Action Context Fix

**Version: 0.261.238**

Fixed in version: **0.261.238**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

A V2 chat plan that used a Microsoft 365 action never read Microsoft 365 data.
For "what are my latest emails", the planner chose the user's Microsoft 365 Email
action, and the **Retrieve latest emails** step reported completed. The answer
then said the mail couldn't be retrieved. No Microsoft Graph request was made.

Production telemetry for the step showed one
`[MS_GRAPH_PLUGIN] Microsoft 365 operation could not complete.` event for the
`get_my_messages` operation, about half a second after the model called the
email function, with `sc_error_code_length` 21. The event logged only the code's
length. Without a Microsoft 365 execution context, the function's first check can
only refuse with `m365_context_required`, which is 21 characters.

## Root cause

Each orchestration action step runs inside the execution identity's bridge: a
fresh Flask app and request context, built because the plan runs on a worker
thread. The bridge copies the user's signed-in session, but Flask's `g` starts
empty.

Microsoft 365 functions require an `M365ExecutionContext` in `g`. It names the
data user, the conversation and its audience, and the logical request. It also
selects the actions that request may use. Classic chat creates it for each chat
request, and workflows create it for their Run as account. Orchestration never
created one, so:

1. The email function's first authorization check, `authorize_m365_source`,
   raised `M365PolicyError("m365_context_required")`.
2. The plugin returned that refusal as an ordinary function result.
3. The orchestration action loop treated every function result as data. The
   model described the refusal as findings, and the step completed.

Two more problems would have stopped the step once a context existed. Microsoft
365 selects actions through a chat agent selection, so a direct action step would
have been refused with `m365_action_not_selected`. The V2 UI had no way for a user
to connect Microsoft 365 after a step stopped for sign-in.

## Changes

### A Microsoft 365 request for each action step

`step_m365_context()` in `functions_m365_runtime.py` creates the step's
`M365ExecutionContext` inside its bridge, through the new
`functions_orchestration_m365.py`. `invoke_action()` enters it once the step's
saved action resolves to a Microsoft 365 type. The context:

- Uses the signed-in user as actor and data user, after confirming the bridge's
  session belongs to them.
- Selects only the step's own saved action, by its exact action reference.
  `resolve_m365_selected_manifests()` reads that selection again from storage on
  each call, so current governance and the action's own capabilities apply.
- Removes `send_mail`, `create_calendar_invite` and `mark_message_as_read`, so
  plans only read. Those functions are never loaded into the step's kernel.
- Refuses shared conversations before any Microsoft 365 work. Their
  source-sharing approvals resume chat requests, not plan steps.
- Runs the existing Microsoft 365 preflight before the step's model or any
  Microsoft Graph call. It checks the user's delegated sign-in for the action's
  sources.
- Records the request in the Microsoft 365 execution container as running, then
  completed or failed. The record keeps the run, attempt and step, so sharing the
  conversation waits for a running step, as it does for a chat request.

The request ID is derived from the plan's first attempt and the step. A retried
step reuses the same request, so an approval the user gave after the step
stopped applies while the action is unchanged. A stop for approval records the
approval on the request and marks it failed. Deciding that approval then reports
the request as not resumable, instead of resuming a chat request. When a retry
of the step finishes, Approvals shows its outcome on that approval, as it does
for a resumed chat.

### Refusals stop the step

A Microsoft 365 sign-in, approval or authorization refusal now stops the step,
whether it is raised or returned as a function result. Ordinary Microsoft Graph
outcomes, such as nothing found, throttling or access denied, stay findings that
the model reports.

The step fails with one of these new failures. Each names what to do next:

| Failure code | When |
| --- | --- |
| `m365_sign_in_required` | Delegated sign-in or consent is missing or expired, or Microsoft Graph rejected the token. |
| `m365_approval_required` | The step needs the user's approval, for example deeper file analysis. |
| `m365_unavailable` | The action, its sources or the request couldn't be authorized. |
| `m365_shared_conversation` | The conversation is shared. |
| `m365_read_only` | The action enables only send, invitation or mark-as-read functions. |

`failure_from_exception()` reads the failure code from the stop. The sign-in and
approval failures also carry `m365_sources`, which `build_failure()` limits to
`calendar`, `email`, `onedrive` and `spo`.

### Connect Microsoft 365 from the V2 run details

When a run's failures include `m365_sign_in_required`, the V2 recovery notice shows
**Connect Microsoft 365** for the failure's sources. It uses the existing Profile
reconnect flow (`POST /api/m365/chat/connection/connect` with the
`X-M365-CSRF-Token` header) in a popup. It treats the Profile page's
`m365-profile-reconnected` message, or a newer saved connection covering the
sources, as success. The user then selects **Retry from failed step**. An approval
failure links to Approvals. No backend route changed.

### Telemetry

`log_m365_failure()` now also logs the refusal code as `sc_failure_code` and the
source as `sc_resource`. A step that stops logs
`[ORCHESTRATION_M365] A Microsoft 365 step stopped.` with `sc_failure_code`,
`sc_authority_reason` (the Microsoft 365 code), `sc_capability_id` and
`sc_source_count`.

## Files modified

| File | Change |
| --- | --- |
| `functions_orchestration_m365.py` | New. Step scope, stable request IDs, refusal-to-failure mapping and stop logging. |
| `functions_m365_runtime.py` | `step_m365_context()`, the step selection in `resolve_m365_selected_manifests()`, read-only filtering and the step's request record. |
| `functions_orchestration_actions.py` | Enters the step scope for Microsoft 365 actions and stops on Microsoft 365 refusals. |
| `functions_orchestration_adapters.py` | Passes each action step's stable request key and record origin. |
| `functions_orchestration_schema.py` | The five failures and `m365_sources`. |
| `functions_m365_transport.py` | Logs the refusal code and source as text. |
| `v2_ui/src/lib/m365Connect.ts` | New. The popup connect flow. |
| `v2_ui/src/components/chat/OrchestrationM365Notice.tsx` | New. Connect and Approvals follow-ups. |
| `v2_ui/src/components/chat/OrchestrationRecoveryNotice.tsx`, `v2_ui/src/lib/orchestration.ts` | Show the follow-up and keep `m365_sources`. |
| `config.py` | Version `0.261.238`. |

## Validation

### Tests

`functional_tests/test_orchestration_m365_actions.py` runs the real action runner,
step scope, Microsoft 365 runtime and execution boundary, approval service and
Email plugin through a real Flask bridge. Storage, tokens, Microsoft Graph and the
model are doubled, and network access is blocked:

- An email step reads mail through its own step context. Both token requests use
  the step's request, the signed-in user and the conversation, and the request
  record ends completed with the step's origin.
- A plan step never loads send or mark-as-read functions, even when the action
  enables them.
- Missing sign-in stops the step before any model, Microsoft Graph or plugin
  load, with `m365_sign_in_required` and the `email` source.
- A Microsoft Graph 401 fails the step instead of becoming findings. A 404 stays a
  finding.
- Shared conversations and send-only actions are refused before any Microsoft 365
  work or record.
- A stop for approval records the approval. A retry reuses the request and
  completes, and the approval then shows that outcome. A retry that stops for
  another approval reports nothing on either approval.
- The step scope hides a chat agent selection and restores it afterward. A step
  without a signed-in session is refused.
- An answer built from the step's tool calls counts as Email history for
  conversation sharing.

Each of ten deliberate breaks makes at least one of these 14 tests fail. The
breaks are: no step scope, refusals kept as data, write functions kept, a new
request for every attempt, shared conversations allowed, the approval not
recorded, sources dropped from failures, no sign-in check before the model, no
outcome reported on the approval, and an outcome reported while the step stops
for another approval.

`ui_tests/test_v2_orchestration_m365_recovery.py` runs the real V2 recovery
notice and connect flow in Chromium, with HTTP responses doubled:

- A sign-in stop connects only the step's known sources and sends the Microsoft
  365 CSRF header. The sign-in window closes when Profile reports the
  connection, and retrying stays the user's choice.
- A window closed without a saved sign-in says sign-in wasn't completed, and
  the user can connect again.
- A window that can't report, as when the API is on another origin, is
  confirmed by the saved connection.
- A sign-in stop without sources links to Profile, an approval stop links to
  Approvals, and other failures show neither.

Removing the notice from the recovery view, or dropping `m365_sources` when a
failure is read, makes these tests fail.

The V2 UI type-checks and builds with `npm run typecheck` and `npm run build`.

### Before and after

| Before | After |
| --- | --- |
| Every Microsoft 365 call in a plan was refused with `m365_context_required`, and the step reported completed. | The step reads as the signed-in user through its own Microsoft 365 request. |
| A refusal became findings, so the answer said the data couldn't be read. | A refusal stops the step with a failure that names the fix. |
| Telemetry showed only the refusal code's length. | Telemetry shows the refusal code and source. |
| A user had no way to connect Microsoft 365 from a plan. | The run details offer **Connect Microsoft 365**, then **Retry from failed step**. |

## Limitations

Since **0.261.270**, shared conversations and agents' Microsoft 365 actions are
supported. See the
[session-trusted action and agent steps fix](ORCHESTRATION_SESSION_TRUSTED_ACTION_AGENT_STEPS_FIX.md)
and the [shared conversations fix](ORCHESTRATION_SHARED_CONVERSATIONS_FIX.md). The
limits below describe 0.261.238.

- Plans only read Microsoft 365 data. Sending mail or invitations from a plan
  needs pending-action review designed for plan steps.
- Shared conversations are refused. Plan steps would need their own
  source-sharing approval flow.
- An **Ask an agent** step doesn't make its agent's Microsoft 365 actions
  available. A local agent called through a classic chat **Call agent** action
  also runs in a bridge without a Microsoft 365 request. Giving it one needs care
  inside workflows, which must use their Run as account.
- The V2 connect popup relies on the classic Profile page to confirm sign-in.
  When the API is on another origin, the saved connection check confirms it after
  the popup closes.

## Related

- [Microsoft 365 actions in plans](../../admin/orchestration.md#microsoft-365-actions-in-plans)
- [Microsoft 365 data and approvals](../../guides/microsoft-365-conversation-data.md)
- [Orchestration settings document type fix](ORCHESTRATION_SETTINGS_DOCUMENT_TYPE_FIX.md)
- [Logging tags](../../reference/logging-tags.md)
