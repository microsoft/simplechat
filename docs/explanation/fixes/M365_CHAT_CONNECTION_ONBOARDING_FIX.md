# Microsoft 365 chat connection onboarding (v0.261.032)

Fixed in version: **0.261.032**

Related version update: `application/single_app/config.py`, from `0.261.031`
to `0.261.032`. Associated issue: [#1493](https://github.com/microsoft/simplechat/issues/1493);
feature PR: [#1497](https://github.com/microsoft/simplechat/pull/1497).

Follow-up: [consent scope-response validation](M365_CONSENT_SCOPE_RESPONSE_FIX.md)
was corrected in **0.261.033** after live sign-in reached the token callback.

## Reported behavior and evidence

An agent configured with the four new Microsoft 365 actions answered that it
could not access SharePoint, without offering sign-in. Profile's workflow
connection showed disconnected, and Connect returned HTTP 400. Selecting a
source also required a second set of optional permission checkboxes.

The reported deployment's logs showed that the four requested action IDs
matched available actions, yet the loader received zero effective manifests.
Connect requests were recorded with an HTTP application-side URL behind the
public HTTPS App Service endpoint. The configured login redirect override was
absent.

In the existing shared browser, Profile on version `0.261.031` reproduced an
initial stale-CSRF HTTP 403 and then the reported HTTP 400 after Refresh. The
investigation did not require sending mail or creating calendar events.

## Root causes

### Selected actions were bound after the kernel loaded

Streaming created the M365 execution context before kernel initialization but
did not bind the authoritative selected agent until afterward. The capability
preflight therefore correctly saw no selected actions and removed the M365
tools. Registering the selection later could not restore tools to the already
constructed agent.

### Workflow callback used the worker's HTTP scheme

When no configured public origin was available, the callback builder used
`request.host_url`. Azure terminates TLS before forwarding to Flask, so a valid
public HTTPS request produced an HTTP callback rejected by the connection
service. The browser received only the generic invalid-request response.

### Chat lacked a complete interactive consent workflow

Authorization errors relied on a tool being invoked, and the generic streaming
error renderer labeled authentication as Foundry access. A workflow connection
in Profile was separate from the interactive login cache, but that distinction
was unclear to users.

## Implementation

The streaming route now binds the selected agent and runs its source preflight
before constructing the kernel. New M365 conversations are persisted before a
possible consent pause, using the existing conversation-creation helper, so a
returning user can resume the original conversation rather than lose it.

Selected remote sources are checked before model execution. Snapshot-only
evidence reads do not force a new remote connection. Missing access produces a
structured `m365_sign_in_required` pause with the request's source names.

`POST /api/m365/requests/<request_id>/connect` accepts no caller-selected identity,
scopes, or redirect target. It reads the current user's paused interactive
request and begins a short-lived state/nonce/PKCE flow. The flow uses the existing
registered `/getAToken` callback, preserves the SimpleChat principal, and stores
the verified delegated cache in the existing server-side login session.
Interactive chat does not require Key Vault or a workflow connection.

The callback returns to the authorized visible conversation, including the
collaboration mapping when applicable. The browser then calls the existing
subject-bound resume API. It does not store credentials or duplicate the user's
prompt in browser storage. Workflow requests still require their own connected,
consenting Run as account.

Profile selects source permission bundles without extra checkboxes. Calendar
includes event reads, invitations, timezone, and recipient lookup. Email includes
reads, drafts/read-state changes, sending, and recipient lookup. File sources
retain discovery/read scopes. Consent remains explicit, and action capability
limits, sharing decisions, and delivery reviews still constrain execution.
Existing narrower connections are not silently upgraded.

The callback builder normalizes non-local fallback origins to HTTPS while
preserving local development and configured public origins. An exact
`m365_csrf_invalid` response permits one token refresh and retry; genuine
permission failures are not retried.

## Validation

- `test_m365_chat_preflight_order.py` reproduces empty selection, verifies the
  real policy preflight after binding, checks new-conversation persistence, and
  checks route initialization order.
- `test_m365_connections.py` exercises real MSAL PKCE/cache handling, source
  bundles, missing access, snapshot-only behavior, state expiry, replay,
  wrong-user/tenant/nonce/guest claims, and session-only chat credentials.
- `test_m365_routes.py` covers HTTP-behind-HTTPS callbacks, distinct CSRF
  rejection, saved-request scope binding, unauthorized/completed/workflow
  request rejection, and return to the original visible conversation.
- `ui_tests/test_m365_lifecycle_and_approvals.py` exercises the local browser
  connection prompt and resume workflow, source selection, visible failures,
  and existing sharing/Foundry behavior with deterministic APIs.
- Cold web/scheduler imports continue to use real modules in fresh normal and
  optimized interpreters with network access blocked.

The integrated backend run passed **559 tests and 114 subtests**. All **13**
fresh-process web/scheduler import checks and **12** route-policy checks passed.
The generated application surface inventory remained unchanged and its
documentation coverage and site-quality checks passed.
The isolated Microsoft 365 browser suite passed **62 tests**, including
Commercial, Government, and configured custom HTTPS authorities. These UI tests
use deterministic APIs; they do not certify live tenant consent.

## Deployment boundaries

The observed test deployment already registers `/getAToken`, so interactive
chat consent does not require another redirect registration. Its saved workflow
connection is separately unconfigured: the workflow encryption-key reference
is absent and `/api/m365/connections/callback` is not registered.
Those are administrator setup requirements, not reasons to disable chat or
fall back to plaintext workflow credentials.

The live browser reproduced the old behavior. The repaired flow must still be
deployed and checked with the user's authenticated account before claiming live
end-to-end Microsoft 365 connectivity. No app-registration permissions or
Key Vault credentials were modified during this investigation.
