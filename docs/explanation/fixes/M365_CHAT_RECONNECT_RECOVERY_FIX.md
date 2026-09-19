# Microsoft 365 interactive reconnect recovery (v0.261.034)

Fixed in version: **0.261.034**

Related version update: `application/single_app/config.py`, from `0.261.033`
to `0.261.034`. Associated issue: [#1493](https://github.com/microsoft/simplechat/issues/1493);
feature PR: [#1497](https://github.com/microsoft/simplechat/pull/1497).

## Issue and diagnosis

Interactive Microsoft 365 sign-in could only be restarted through an existing
paused conversation. Profile's connection controls were for durable workflows,
which have separate Key Vault and Run as requirements. A user with a suspect
interactive cache therefore had no independent repair control in Profile.

When Graph rejected an otherwise unexpired bearer token with HTTP 401, the
transport also omitted the required scopes from the error. The existing
agent journal could identify a sign-in wait, but its saved request did not
contain enough scope information to begin the replacement connection.

The reported screenshot was investigated separately. At **2026-09-19
12:28:08 UTC**, the OneDrive and SharePoint search operations logged
`model_context_unavailable`; earlier discovery calls logged `invalid_query`.
A correlated Graph search returned HTTP 200. These are not evidence that
Microsoft rejected the user's connection. The selected `gpt-5.6-terra`
catalog entry has no declared context/output token limits. This change does
not invent token limits or relabel that configuration issue as authentication.

## Manual reconnect

Profile now contains a distinct **Microsoft 365 chat connection** card.
Users can select sources and choose **Reconnect Microsoft 365 for chat**
without a waiting request and even when a matching login cache is present.

The server endpoints are:

- `GET /api/m365/chat/connection`: reports only local session state, selected
  sources, the recorded connection time when available, and a CSRF token.
- `POST /api/m365/chat/connection/connect`: accepts source selections only.
  The current user, tenant, permission bundles, and callback are server-owned.

The existing state/nonce/PKCE flow and registered `/getAToken` callback are
reused. A fresh MSAL cache is verified before replacing the old one. Failure,
denial, expiry, or signing in as another account does not erase the old cache or
replace the SimpleChat principal. Success returns to Profile rather than
executing a conversation or workflow.

The local `available` status means matching credentials are saved, not that a
Graph call or file ACL has just been checked. Status reads do not probe
Microsoft Graph or return tokens, cache contents, or raw configuration.

Saved workflow credentials, connection generations, Run as approvals, and
sharing grants are not changed by interactive Profile reconnect. The workflow
connection still requires its separate configuration.

## Authentication-specific chat recovery

Graph HTTP 401 failures now carry the exact qualified scopes and source into
the existing sign-in wait and durable agent checkpoint. The current interactive
session is marked for reconnect instead of trusting the rejected cache entry.
A verified reconnect clears that marker. Workflow and other-user contexts
cannot mark a different interactive principal.

The paused file call resumes after sign-in without replaying completed sibling
calls. HTTP 403, throttling, service errors, and model/storage configuration
failures remain distinct. A temporary preauthenticated download URL returning
401 is reported as `download_link_expired`, not as an invalid Graph login.
No automatic retries are added to remote operations.

## Validation

- `test_m365_connections.py`: real MSAL Profile reconnection, fresh-cache
  publication only after verification, corrupt-cache repair, preserved old
  credentials on failure, local status without network access, and workflow/
  other-principal isolation.
- `test_m365_routes.py`: authentication/CSRF, source-only request body,
  fixed callback, no-store status, and return to Profile without request replay.
- `test_m365_provider_core.py`: qualified scope propagation for Graph 401,
  safe errors, no retry, and distinct policy/service/download-link failures.
- `test_m365_agent_continuation.py`: real Semantic Kernel sign-in pause with
  preserved scopes and no replay of an already completed tool call; model-limit
  failures do not become sign-in prompts.
- `ui_tests/test_m365_lifecycle_and_approvals.py`: Profile source selection,
  reconnect from an existing session, independent workflow controls, explicit
  errors, return handling, and cloud-compatible authorization navigation.

The backend integrated run passed **580 tests and 157 subtests**. Focused
optimized-Python coverage passed **201 tests and 107 subtests**, and all
**13** fresh-process web/scheduler import checks passed.
The isolated Microsoft 365 browser suite passed **98 tests** in local Chromium,
including Profile repair with and without an existing sign-in, independent
workflow controls, source selection, and Commercial/Government/custom URLs.
Route-policy, documentation, JavaScript syntax, and whitespace checks passed.

## Deployment and remaining limitation

Deploy **0.261.034** before using the new Profile control. No SDK update,
database migration, app-registration permission change, or workflow encryption
key is required for interactive reconnect.

Reconnecting alone does not resolve the screenshot's missing model-context
limits. That retrieval configuration remains a separate follow-up; the
application must not guess a model's capacity or bypass its file-context budget.
Azure inspection was read-only and this session did not deploy the application.
