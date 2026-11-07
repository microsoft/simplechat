# Microsoft 365 connection session race and setup fix (v0.261.302)

Fixed in version: **0.261.302**

Related version update: `application/single_app/config.py`, from `0.261.301`
to `0.261.302`. Associated issues:
[#1714](https://github.com/microsoft/simplechat/issues/1714) for the session
race, V2 links and chat connection status, and
[#1604](https://github.com/microsoft/simplechat/issues/1604) for the workflow
key, callback and readiness work.

## Issue

On a deployment where chat could already read the user's mail and SharePoint,
the Microsoft 365 settings misbehaved in several ways at once:

- **Reconnect Microsoft 365 for chat** opened a popup that showed raw JSON:
  `{"error":"m365_auth_state_invalid","message":"This sign-in request expired or changed. Connect again from chat."}`,
  seconds after the user had signed in.
- **Connect for workflows** failed in both interfaces with "Configure Key Vault
  and a dedicated workflow encryption-key secret before connecting Microsoft
  365", an error no end user can act on.
- The chat connection card said "Sources saved for this session: none" while
  chat was successfully using Email, OneDrive and SharePoint.
- Links in V2 chat (Connect Microsoft 365, Review the approval, Reconnect for
  workflows) opened the classic Profile and Approvals pages instead of V2.

## Root cause

### Lost session writes (the popup error)

Flask-Session 0.8 writes the whole stored session back at the end of every
request, including requests that changed nothing
(`should_set_storage` returns `session.modified or SESSION_REFRESH_EACH_REQUEST`,
and Flask's default is `True`). The request that finishes last wins.

The affected App Service runs three instances with ARR affinity off and
sessions in Redis. The V2 interface re-reads `GET /api/v2/bootstrap`, which
took 5.2 seconds at the median and 7.4 at p90, whenever the window regains
focus. Application Insights showed the same sequence for both failed attempts:

| Attempt | Bootstrap started | Connect POST saved the sign-in | Bootstrap finished and saved its copy | `/getAToken` |
|---|---|---|---|---|
| 1 | 14:09:39.2 (4865 ms) | 14:09:41.6 | ~14:09:44.1 | 14:09:44.9 → 400 |
| 2 | 14:11:00.3 (4971 ms) | 14:11:04.5 | ~14:11:05.3 | 14:11:08.6 → 400 |

Each bootstrap had loaded the session before the connect call stored the
pending sign-in, and wrote its stale copy back afterwards. The callback then
found no pending sign-in. The same race could silently drop any session
write: token-cache refreshes, the Microsoft 365 CSRF token, the workflow
connect binding, and it could even recreate a session that had just signed
out.

### Workflow connections had no key and no callback

Saved workflow sign-ins are encrypted with one deployment-wide AES-256 key in
Key Vault. Nothing created that key: an operator had to create the secret and
set `M365_WORKFLOW_TOKEN_KEY_SECRET_NAME`, and the deployment had neither. The
workflow callback `/api/m365/connections/callback` was also not registered on
the app registration, so connecting would have failed at Microsoft next.

### Chat status reported only explicit reconnects

The chat card listed only sources recorded by an explicit Profile reconnect.
Chat itself gets tokens silently with the session's refresh token, using
consent granted at sign-in or by an administrator, so a working session could
show "none".

### Hard-coded classic links

`m365Links.ts`, `m365Connect.ts` and the workflow proposal card pointed at
`/profile?...` and `/approvals`. V2 workflow connect also navigated the whole
page to Microsoft and returned to classic Profile.

## Fix

### Session saves merge instead of overwrite

`functions_session_store.py` replaces the Redis and filesystem session
interfaces right after every `Session(app)`. It records what a request loaded
and, on save:

- writes nothing when the request changed nothing, only refreshing the expiry
  (`EXPIRE`, which never recreates a deleted session);
- otherwise writes only the keys the request changed and removes only the keys
  it removed, merged into the latest stored copy. Redis applies the merge with
  `WATCH`/`MULTI`/`EXEC` and retries a conflict up to five times, then merges
  without the lock rather than overwriting;
- writes new, cleared and re-keyed sessions whole, as before;
- leaves a session that was deleted during the request deleted.

Two requests that change the same key still resolve last writer wins. The V2
shell also skips a focus-triggered bootstrap refresh while one is running or
started in the last 15 seconds.

### The workflow key creates itself

`_default_key_provider` now uses the secret `simplechat-m365-workflow-token-key`
by default; the app setting only renames it. When a connection is encrypted and
the secret does not exist, SimpleChat generates 32 random bytes and stores
them with `set_secret`, tagged and typed, without logging the value.
Decryption pins the stored key version and never creates a key, so two
instances creating it at once leave two readable versions rather than a broken
connection. Admin settings saves in both interfaces also make sure the key
exists when Key Vault storage is on; a failure is reported beside the Key
Vault settings only when that save changed them, and never blocks the save.
Missing write permission and a soft-deleted secret produce specific,
actionable errors.

`GET /api/m365/connections` now includes `workflow_connections`
(`available`, `reason`, `message`), computed from settings alone. Both
interfaces disable **Connect for workflows** and explain that an administrator
needs to turn on Key Vault secret storage, instead of failing on click.

### Workflow sign-in uses the registered callback

Workflow sign-in now returns to `/getAToken`, which is always registered, with
an `m365-workflow-` state prefix that routes it to the workflow completion.
`/api/m365/connections/callback` still completes sign-ins for deployments that
registered it.

### Sign-in results report back instead of showing JSON

Callbacks render `m365_connection_result.html` with a local script. A sign-in
started as a popup (`"completion": "popup"`, sent by V2 and the classic chat)
posts `m365-profile-reconnected`, `m365-workflow-connected` or
`m365-connect-failed` with the safe error message to the same-origin opener,
then closes. A full-page classic sign-in keeps its redirect on success and
shows a readable error with a link back on failure. V2 shows the failure
message where the user clicked.

### Chat status matches what chat does

`read_chat_connection` derives the usable sources from the session's token
cache: a refresh token for the user plus each source's permissions on the
cached Graph tokens. It makes no network call. Both interfaces now say, for
example, "Signed in to Microsoft 365 for this session. Chat can use: Email,
OneDrive, SharePoint Online (SPO)."

### V2 links stay in V2

`m365Links.ts` holds router paths: `/settings?tab=preferences&section=m365-chat-connection`,
`/settings?tab=preferences&section=m365-workflow-connection` and `/approvals/m365`,
rendered with `Link`. The Settings page scrolls to the card named by `section`.
V2 workflow connect uses the popup flow.

## Files modified

- `application/single_app/functions_session_store.py` (new),
  `application/single_app/app.py`
- `application/single_app/functions_m365_connections.py`,
  `application/single_app/route_backend_m365.py`,
  `application/single_app/route_frontend_authentication.py`
- `application/single_app/route_frontend_admin_settings.py`,
  `application/single_app/route_backend_v2.py`
- `application/single_app/templates/m365_connection_result.html` (new),
  `application/single_app/static/js/profile/profile-m365-connection-result.js` (new),
  `application/single_app/templates/profile.html`,
  `application/single_app/static/js/profile/profile-m365.js`,
  `application/single_app/static/js/chat/chat-m365-connect.js`
- `application/v2_ui/src/lib/m365Connect.ts`, `m365Links.ts`,
  `components/settings/M365Cards.tsx`, `pages/SettingsPage.tsx`,
  `stores/bootstrapStore.ts`, `App.tsx`, and the chat and approvals components
  that link to Microsoft 365 settings

## Validation

New and updated tests:

- `functional_tests/test_session_store_merge.py` (new, 14 tests): the production
  interleaving (a slow request against a concurrent sign-in write), expiry-only
  saves, no resurrection after sign-out, removals beside concurrent additions,
  nested in-place changes, `WATCH` retry and exhausted-retry fallback, whole
  writes for new and cleared sessions, unreadable stored data, the filesystem
  backend, real Flask requests and `session_transaction`, and that `app.py`
  installs the interface after every `Session(app)`.
- `functional_tests/test_m365_connections.py`: default secret name, key creation
  only when encrypting, specific 403/409 errors, the never-raising admin
  helper, settings-only readiness, the `m365-workflow-` state on `/getAToken`
  with the legacy callback still accepted, popup completion, and chat sources
  derived from the session cache, including no sources without a refresh token.
- `functional_tests/test_m365_routes.py`: result pages instead of JSON for chat
  and workflow callbacks, popup and full-page completion, readiness in the
  status read, `/getAToken` as the workflow callback, and the legacy route.
- `functional_tests/test_v2_user_settings_memory_m365.py` and
  `test_v2_workflow_run_tracking_xss_guardrail.py`: popup connect, V2-only
  link constants, and the `section` deep link.
- UI (local Chromium): `ui_tests/test_m365_connection_result_page.py` (new, 6),
  `ui_tests/test_v2_settings_m365_connections.py` (new, 5), and updated
  `test_v2_orchestration_m365_recovery.py`,
  `test_v2_orchestration_workflow_proposal_card.py`,
  `test_m365_lifecycle_and_approvals.py` and `test_m365_pending_action_cards.py`.

Results:

- 131 related functional test files, about 1,490 tests, were run here and on
  an unmodified checkout of the same commit. No test fails here that passes on
  the baseline. 72 tests fail, and 6 files cannot be collected, identically on
  both, because of this machine's environment: for example an older local
  Flask, an incompatible pyOpenSSL, and modules that need live Azure
  configuration.
- Route policy: 14/14, 9/9 and 3/3. Documentation quality 6/6 and coverage 7/7
  with the regenerated inventory.
- V2 `npm run typecheck` passed; the V2 `.mjs` logic suites passed, including
  the real bootstrap store (8/8), apart from two workspace-action suites that
  fail identically on the baseline.
- Playwright: classic Microsoft 365 suites 155 passed (one fixture fails to
  start on the same pyOpenSSL mismatch), result page 6, V2 Settings 5, V2
  orchestration recovery and workflow proposal card 54.
- `scripts/check_xss_sinks.py --full-file` over every changed browser-facing
  file reports only findings on unchanged `profile.html` lines.

## Deployment

Deploy **0.261.302**. With Key Vault secret storage on and the application
identity holding Key Vault Secrets Officer, as Key Vault storage already
requires, there is nothing else to configure: the key is created on the first
workflow connection or admin settings save, and `/getAToken` is already
registered. Users whose tenant blocks user consent still need an administrator
to grant the Microsoft 365 delegated permissions.

## Follow-ups

- `GET /api/v2/bootstrap` spends about five seconds in Python per call. The
  merge removes the correctness impact, but the latency deserves profiling.
- `Initialize-EntraApplication.ps1` does not declare the Microsoft 365
  delegated permissions (#1604, item 3).
