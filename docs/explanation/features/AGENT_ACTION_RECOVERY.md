# Agent action recovery

Fixed/Implemented in version: **0.261.347**.

Updated in version: **0.261.355** for V2 first-message context synchronization.

Related version update: `application/single_app/config.py`.

Issue: [#1781](https://github.com/microsoft/simplechat/issues/1781).

## Overview and dependencies

Classic and V2 chat ask for a decision when a selected local agent has assigned
actions that cannot load. This makes lost capabilities explicit instead of
letting the model answer as though the actions were available.

The feature reuses agent/action governance, the private action-interaction
store, existing credential and Microsoft 365 approval/sign-in flows, and in-app
notifications. No new capability setting or saved-agent migration is required.
Successful registration does not certify credentials or provider availability.

## Workflow

1. Select a local agent and send a message. Availability is checked before
   starting the model.
2. Review each unavailable action, its owning scope, and affected operations.
   The dialog explicitly says when all assigned actions are unavailable.
3. Choose **Cancel / choose another agent** to keep the request unsent, or
   **Recheck** after correcting the action. **Open action in a new tab** appears
   only when current policy permits editing that particular action.
4. Choose **Continue without these actions** only when an answer without the
   listed capabilities is useful. The exclusion applies to this request alone;
   it does not edit the agent or grant permission to another action.

After cancellation, **Recheck and send preserved request** starts a fresh check.
A healthy action does not cause a saved request to send itself. The preserved
message can be inspected in the notice; the browser stores only the incident
ID, not a copy of the prompt.

Supported missing or rejected personal credentials still use the existing
credential card. Microsoft 365 sign-in and approvals retain their dedicated
flows. A health-only check defers recognized interactions to those flows;
continuing without an unavailable action never substitutes for authentication
or approval. See [Personal action credentials](PERSONAL_ACTION_CREDENTIALS.md).

## Editing and reporting

Remediation follows the action's trusted scope, not the selected agent's scope.
Personal owners need action-authoring permission. Group links require current
membership and the group's action-management policy. Global links require the
Admin role. The destination reauthorizes access.

**Notify owner/admin** is optional and sends only after activation. Personal
reports target the owner; group reports target responsible current owner/admin
managers rather than the whole group; global reports target application
administrators. Reports contain a safe action reference/label, failure code,
version, correlation ID, and editor link, not the conversation or prompt.

**Reported** requires confirmed delivery. An uncertain result offers an
idempotent retry that preserves any existing notification's read/dismissal
state. Changed action revisions or revoked access invalidate the report.

## Technical contract

`functions_action_recovery.py` owns availability checks, private incidents,
draft checkpoints, current-policy remediation, and reports.
`route_backend_action_credentials.py` exposes authenticated, no-store routes:

| Route | Purpose |
| --- | --- |
| `GET /api/action-recovery/context` | Initializes the session's existing interaction CSRF token. |
| `POST /api/chat/action-health` | Checks an authorized request's local action loading. |
| `GET /api/action-recovery/<request_id>` | Rechecks access and restores an unconsumed incident and its private draft. |
| `POST /api/action-recovery/<request_id>/report` | Reports one currently authorized failed action. |
| `POST /api/action-recovery/<request_id>/cancel` | Cancels an incident explicitly through the interaction API. |

Writes require CSRF. Continuation is actor/conversation-bound, expiring,
fingerprint-checked against the selected agent, request, and authorized action
configuration, and claimed once using an ETag. A new failure needs a new
decision. Incidents expire after 30 minutes; the existing private checkpoint
owner's retention is 24 hours. Expired or unauthorized incidents cannot be
restored as permission grants.

Classic uses `static/js/chat/chat-action-recovery.js` and the existing stream
consumer. V2 uses `src/lib/actionRecovery.ts`, `ActionRecoveryNotice.tsx`, and
the existing chat store/SSE transport. Both invalidate pending decisions when
the agent or conversation changes. V2 additionally binds notices to the current
bootstrap actor. V2 synchronizes conversation identity in the chat store before
preflight starts; observing that identity again in React does not invalidate the
same send. Assigning a newly created conversation's ID therefore does not require
another Send or recheck action. A distinct New chat action still invalidates
pending recovery, even when no saved conversation ID is active. See
[V2 first-agent-message context race](../fixes/V2_FIRST_AGENT_MESSAGE_CONTEXT_RACE_FIX.md).
The UI uses local static assets and safe text rendering.

## Validation and limits

`functional_tests/test_action_runtime_recovery.py` exercises actual private
storage with SDK-shaped point responses, current permissions, stale decisions,
single-use claims, conditional-write conflicts, reports, and restored drafts.
`ui_tests/test_chat_action_recovery.py` covers both transports, mobile/desktop
dialogs, keyboard cancellation, reporting uncertainty, late responses, changed
agents, safe links/text, and no automatic transport replay.

The health pass constructs plugins and does not invoke a model or tool. It adds
registration work before a selected-agent request. Provider authentication and
operation success remain execution-time checks.

Shared-conversation bridges have already persisted their shared turn. A loading
failure there remains an explicit, fail-closed error, not a personal-chat
continuation. Background, delegated, and captured execution do not inherit an
ordinary user's exclusion. Mid-run failures never offer blind whole-request
retry; inspect existing outgoing calendar/email status and use only supported
checkpoint/reconciliation flows.
