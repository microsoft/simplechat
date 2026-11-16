# Microsoft 365 chat connection persistence (v0.261.355)

Fixed in version: **0.261.355**

Version tracking: `application/single_app/config.py`.

## Issue and root cause

Chat could show a signed-in user with no source permissions after previously
connecting successfully. Workflow access remained connected.

Chat status considered only unexpired access-token targets. MSAL removes
expired access tokens during cache searches, even when a valid refresh token
can silently obtain a replacement. Separately, chat credentials lived in the
ordinary app-login session cache, which normal login clears. Workflow
credentials already had independent, encrypted durable storage.

## Connection lifecycle

Explicit chat reconnect now saves a separate `chat_connection` record in the
existing `/user_id` Microsoft 365 connections container when Key Vault secret
storage is configured. The record has `ttl: -1`: SimpleChat adds no expiration
to the saved credential. Microsoft token lifetimes, Conditional Access,
organizational sign-in frequency, consent changes, and user revocation remain
authoritative.

Each cache is AES-GCM encrypted with the existing deployment key. Associated
data binds it to the chat record, user, tenant, deployment configuration,
account, and generation. The envelope pins its Key Vault key name and version.
The existing `simplechat-m365-workflow-token-key` secret name remains unchanged;
chat and workflows share encryption infrastructure, not credentials or
authorization.

Saved chat credentials are used only by the same currently signed-in tenant
member. They cannot supply unattended workflow Run as access. App sign-out
preserves the saved credential, but unauthenticated requests cannot use it.
Normal login and workflow callbacks do not publish a chat credential.

Refresh uses the existing conditional ownership lease. Rotated refresh tokens
are encrypted and saved before a refreshed access token is released. Temporary
provider, network, storage, or Key Vault failures do not clear source selections
or silently fall back to another credential. Microsoft interaction failures
and rejected chat credentials require reconnect; normal access-token expiry
does not.

**Disconnect chat** removes the encrypted cache and increments a retained
tombstone generation. Stale sessions, refreshes, and callbacks cannot restore
it. Chat and workflow disconnect are independent. Disconnect does not revoke
Microsoft-side consent or recall evidence already shared in conversations.
Chat authorization records are excluded from data transfers and raw admin
record editing, just like workflow credentials.

## Upgrade and configuration

Configure **Admin Settings > Security > Secrets > Key Vault** for persistent
chat access. The application's vault identity needs the existing secret
permissions; preserve historical encryption-key versions.

Existing users reconnect chat once to opt into durable storage. SimpleChat
does not automatically save an ambiguous old login/workflow session cache.
Without Key Vault, explicit chat reconnect still works for the current app
session, using an isolated chat cache. Both interfaces explain **saved** versus
**session-only** access. Disabling Key Vault does not downgrade or overwrite a
previously saved credential.

The connected-source list reflects verified consent and retained refresh-token
targets rather than the lifetime of an individual access token. It is not a
remote-resource access probe. Changed source permissions or policy can still
be reported on the next request.

## Files changed

- `functions_m365_connections.py`: chat storage, status, scope handling,
  isolated caches, refresh ownership, and disconnect fencing.
- `route_backend_m365.py`: authenticated, CSRF-protected empty-body chat
  disconnect endpoint; workflow callbacks remain independent.
- `functions_m365_data_lifecycle.py`: authorization transfer/edit exclusions.
- Classic `profile.html` / `profile-m365.js` and V2 `M365Cards.tsx`: persistence
  explanations and confirmed chat disconnect.
- `config.py`: application version `0.261.355`.

## Validation

`functional_tests/test_m365_chat_connection_persistence.py` uses real MSAL,
AES-GCM, the installed Cosmos response types, and an HTTP-isolated real Cosmos
SDK pipeline. It covers expired access tokens, multi-day fresh sessions,
rotated refresh tokens, principal/cloud isolation, corrupt caches, provider
interaction versus transient failures, rejected credentials, independent
workflow access, stale callbacks and concurrent disconnect.

The existing connection, route, preflight, storage, and lifecycle tests cover
the shared boundaries. Browser tests in
`ui_tests/test_v2_settings_m365_connections.py` and
`ui_tests/test_m365_lifecycle_and_approvals.py` cover saved status after reload,
retained sources, session-only explanations, reconnect states, and disconnect
confirmation at desktop and mobile widths.

The targeted connection/persistence/route run passed 103 tests and 108 subtests.
The provider/preflight/session/settings run passed 213 tests. All 18 persistence
regressions also passed under optimized Python, and 47 targeted Chromium cases
passed. Frontend type checking, JavaScript syntax, route-policy coverage, and
documentation coverage/quality checks passed.

The storage inventory reports zero review gaps. The network-blocked SDK and
chat-owner suite passed 30 tests. The broader 101-selector repository-wide
Cosmos contract sweep was stopped after slow progress through unrelated
bootstrap tests; it is not reported as a completed pass.

Two existing integration-fixture failures were reproduced against unchanged
baseline sources: the notification helper test lacks current group-function
stubs, and the conversation lifecycle fixture cannot resolve its assigned
action manifests. They are not silently counted as passing; the notification
case is excluded from the targeted route result above.

These checks replace external network I/O; they do not prove a particular
tenant's refresh-token or Conditional Access policy. Before deployment, verify
the organization's expected sign-in policy with a real account. Reconnect
once after upgrade, restart the browser, sign back in, and confirm the card
still reports saved source access. Confirm chat disconnect leaves workflow
access unchanged.

## Related documentation

- [Microsoft 365 actions](../features/MICROSOFT_365_ACTIONS.md)
- [Microsoft 365 data and approvals](../../guides/microsoft-365-conversation-data.md)
- [Profile preferences](../../guides/update-profile-preferences.md)
- [Key Vault configuration](../../admin/security.md#keyvault-section)
