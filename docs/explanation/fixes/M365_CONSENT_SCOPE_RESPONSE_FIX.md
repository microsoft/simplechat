# Microsoft 365 consent scope-response validation (v0.261.033)

Fixed in version: **0.261.033**

Related version update: `application/single_app/config.py`, from `0.261.032`
to `0.261.033`. Associated issue: [#1493](https://github.com/microsoft/simplechat/issues/1493);
feature PR: [#1497](https://github.com/microsoft/simplechat/pull/1497).

## Reported failure

The in-chat connection prompt opened Microsoft sign-in and consent, but the
returning callback displayed:

```json
{"error":"m365_scopes_invalid","message":"An unsupported Microsoft 365 permission was requested.","success":false}
```

Read-only Azure telemetry at **2026-09-19 00:14:53 UTC** confirmed that the
Microsoft token endpoint returned HTTP 200 before `/getAToken` returned
HTTP 400. The failure therefore occurred after token exchange, not while
opening the consent prompt. Token bodies were not retrieved from the deployment.
A read-only query of this application's consent metadata also found an existing
tenant grant for `User.ReadWrite`, outside SimpleChat's M365 request allowlist.

## Root cause

The interactive and workflow callbacks passed Microsoft's returned `scope`
string into the same validator used for outgoing permission requests. That
validator intentionally permits only SimpleChat's supported delegated scopes
and at most 30 requested entries.

A returned token can include previously consented permissions beyond the
current source request, along with identity scopes. Applying the outgoing
allowlist to that response rejected otherwise sufficient grants. A regression
using real MSAL callback processing reproduced the exact error when the response
included additional prior grants. Coverage includes the deployment's
`User.ReadWrite` grant as well as `Directory.Read.All`. Larger returned scope sets
also triggered the outgoing request-count limit.

The previous token-endpoint fixture echoed exactly the requested scopes, so it
did not exercise broader real-world consent responses.

## Changes and authorization boundaries

`functions_m365_connections.py` now uses a shared `_require_granted_scopes()`
check in both connection callbacks:

- The requested scopes still pass through the existing strict allowlist.
- Every requested permission must appear in the token response.
- Bare permission names and names qualified by the deployment's configured
  Graph resource are recognized. Government and custom resources remain pinned;
  another cloud's qualified permission cannot satisfy the request.
- Extra returned scopes do not cause a false rejection and are not copied into
  a workflow's `authorized_scopes`. Saved source selections, capability limits,
  and explicit workflow Run as approvals are unchanged.
- Missing or invalid scope responses fail with `m365_consent_required` before
  publishing the cache to the chat session or marking a workflow connection
  connected. A similarly named or broader permission is not silently treated
  as the exact requested permission.

No scope was added to the outbound allowlist. Account/tenant binding, guest
rejection, state, nonce, PKCE, encryption, and disconnect-generation checks
remain in place.

## Validation

`functional_tests/test_m365_connections.py` now varies the token endpoint's
scope response while retaining real MSAL authorization-code/cache behavior.
Coverage includes:

- Both interactive and saved-workflow callbacks.
- Commercial, Government, and custom authorities/resources, including a custom
  Graph resource with a port and path.
- Bare, qualified, and mixed scopes; identity scopes; extra prior grants; and
  responses larger than the outgoing request limit.
- Missing grants, wrong clouds, lookalike hosts, wrong resource paths/schemes,
  invalid scope response types, and an empty response.
- A narrow read-only workflow connection receiving a token that also contains
  `Mail.Send`: the application still rejects sending without reconnect consent.
- Continued rejection of unsupported outgoing scope requests.

The token-response reproduction failed before this change and passes with the
shared grant check. No browser assets or deployment resources were changed.
The connected authorization/retrieval suite passed **268 tests and 149 subtests**;
focused optimized-Python coverage passed **86 tests and 130 subtests**. The
documentation inventory and site-quality checks also passed.

## Deployment and retry

Deploy application version **0.261.033**, then return to the original chat or
Approvals and choose **Connect Microsoft 365** again. The failed OAuth callback
has already consumed its one-use flow; refreshing that callback URL is not a
valid retry.

No app-registration permission expansion, SDK upgrade, or database migration
is required for this fix. The repaired callback still needs live retesting after
deployment; offline regressions do not certify tenant-specific Graph access.
