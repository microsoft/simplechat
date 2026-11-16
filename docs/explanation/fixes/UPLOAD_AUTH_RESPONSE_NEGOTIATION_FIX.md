# Upload Authentication Response Negotiation Fix (v0.261.354)

Fixed in version: **0.261.354**

Related application version update: `application/single_app/config.py`,
`0.261.353` to `0.261.354` after integrating the current V2 base.

## Issue and root cause

Chat uploads use the multipart `POST /upload` endpoint. Unlike routes under
`/api/`, that path relies on response negotiation to distinguish an API caller
from browser navigation. The shared React V2 upload helper and the classic chat
upload helper did not send `Accept: application/json`. When the application
session was missing, the login guard could redirect their fetch requests into
the browser sign-in flow rather than return a structured 401.

The idle-timeout middleware had a separate inconsistency: its expiration
response considered only the `/api/` path prefix. Even an explicitly JSON
request to `/upload` received a logout redirect when the session expired.
Depending on the redirect chain, a fetch caller could encounter HTML or a
browser transport failure instead of the expected JSON error.

This is a general response-contract fix, not a file-format, filename, ingestion,
or orchestration workaround.

### Production incident attribution

The supplied FED-21 CSV and XLSX-output scenarios stopped at attachment upload,
before any prompt or orchestration ran. Neither exact incident window contained
a recorded upload POST or authentication redirect in the populated Application
Insights and App Service HTTP logs. Those logs do not establish the cause of
the browser's `Failed to fetch` result.

The observed deployment reported version `0.261.344`; the investigated checkout
was `0.261.350`. No live upload, deployment, or Azure configuration change was
performed. The defect below was reproduced locally, but this fix is **not proof
that those original incidents are resolved**. Harness findings remain separate
session evidence and are not application implementation work.

## Technical changes

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/apiClient.ts` | All consumers of the shared multipart helper request JSON responses. |
| `application/single_app/static/js/chat/chat-input-actions.js` | Classic chat uploads also request JSON responses. |
| `application/single_app/app.py` | The expired-session response honors JSON-only Accept negotiation as well as the existing `/api/` fallback. |
| `functional_tests/test_v2_app_session_recovery.mjs` | Runtime coverage for multipart headers, payload preservation, auth failures, denial, cancellation, and no replay. |
| `functional_tests/test_upload_auth_response_contract.py` | Network-blocked Flask response and activity checks under normal and optimized Python. |
| `ui_tests/test_chat_upload_session_responses.py` | Real-component browser coverage for upload state, recovery, draft preservation, explicit retry, and classic upload errors. |
| `ui_tests/test_v2_chat_image_uploads.py` | The reused HTTP fixture answers the current pending-credential discovery request, so existing image-upload regressions remain executable. |

The browser still generates the multipart Content-Type and boundary. File
contents, credentials, cancellation signals, authorization decorators, CSRF
checks, and upload limits are unchanged.

Only the idle-expiration **response selection** changed. Idle timestamps,
heartbeat behavior, exempt paths, and which requests refresh activity retain
their previous semantics. HTML navigation, ordinary forms, and requests that
accept both HTML and JSON keep their browser redirects on non-API routes.

## Behavior and recovery

| Situation | Before | After |
| --- | --- | --- |
| Missing app session, chat multipart client | Could receive a browser login redirect. | Receives the existing structured 401 from the login guard. |
| Idle-expired app session, JSON request outside `/api/` | Receives a logout redirect despite requesting JSON. | Receives the existing 401 payload with `requires_reauth: true`. |
| HTML navigation with an expired session | Redirects through logout. | Unchanged. |
| Active session, valid upload | Uploads the multipart file. | Unchanged. |
| Role/resource denial or inconclusive network failure | Distinct from confirmed app-session expiry. | Remains distinct. |

React V2 uses its existing app-level session notice. The mounted page and unsent
draft remain available. Signing in again and checking the session do **not**
repeat the upload. An explicit Retry is required; writes remain blocked by the
shared API client while sign-in is required.

Classic chat uses its existing upload-error notification. No new sign-in UI or
automatic retry is introduced there.

This application response contract cannot control an upstream Easy Auth redirect
or a network failure before Flask receives the request. A rejected fetch does
not prove that the server did not write a resource. Automatic mutation retries
would risk duplicate uploads and are deliberately not introduced.

## Testing and validation

Before the production fix, the new V2 checks failed because Accept was absent,
and both normal and optimized Flask probes failed on the expired JSON upload's
302 response. After the fix:

- The API runtime suite passes all **29** checks.
- Both fresh-process Flask probes pass. They execute real authentication
  decorators and the idle function's actual source, with external I/O blocked.
  Loading the idle function independently isolates response/activity behavior;
  it does not claim full application bootstrap or import-cycle coverage.
- All **8** new browser cases pass, including desktop/mobile recovery for
  missing and expired sessions, successful upload, permission denial, offline
  failure, and classic chat's structured error.
- All **15** existing image-upload browser cases pass.
- Existing idle-timeout checks pass **4/4**; route-policy checks pass **28/28**.
- The V2 production build/typecheck and classic JavaScript syntax check pass.

The browser tests run production React components/stores and classic upload
JavaScript with controlled HTTP boundaries. They use synthetic files and local
Chromium, not the live application or an external qualification harness.

Related recovery behavior is documented in
[Unrelated M365 Chat Warnings and Session Recovery](M365_UNRELATED_CHAT_SESSION_WARNING_FIX.md)
and the [upload guide](../../guides/upload-and-manage-documents.md#upload-failures).
