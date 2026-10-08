# Access Restricted Sign-In Screen

Implemented in version: **0.261.296**

## Overview and Purpose

When an administrator suspends or blocks an account, the user can still sign in, but every app surface used to answer with a bare `Access Denied: Access denied by administrator` page or a 403 error. The notice the administrators sent explaining why went to the notification bell, which a restricted user can no longer open, so they never saw it.

Every app surface now sends a restricted user to an **Access restricted** screen instead. It shows the notice they were sent, says whether the restriction is a suspension (with the restore date and time in the reader's own locale) or a block, gives the safety violation reference when there is one, and offers **Sign out**. The V2 interface shows the V2 page; the classic interface shows a matching server-rendered page.

The Admin role is not subject to access restrictions, as before.

Related changes in the same version:
- Safety warnings are sent without a second reviewer and must be acknowledged. See [Safety Remediation Actions Fix](../fixes/SAFETY_REMEDIATION_ACTIONS_FIX.md).

Dependencies:
- `application/single_app/functions_access_restriction.py` (new)
- `application/single_app/functions_authentication.py`
- `application/single_app/route_access_restriction.py` (new)
- `application/single_app/functions_safety_remediation.py`
- `application/single_app/app.py`
- `application/single_app/templates/access_restricted.html` (new)
- `application/single_app/static/js/access-restricted.js` (new)
- `application/v2_ui/src/pages/AccessRestrictedPage.tsx` (new)
- `application/v2_ui/src/lib/accessRestriction.ts` (new)
- `application/v2_ui/src/lib/apiClient.ts`
- `application/v2_ui/src/stores/bootstrapStore.ts`
- `application/v2_ui/src/App.tsx`

## Technical Specifications

### Stored restriction and notice

Control Center and safety remediation both restrict a user through `settings.access`:

```json
{
  "status": "deny",
  "datetime_to_allow": "2026-10-08T14:00:00Z",
  "notice": {
    "kind": "suspended",
    "title": "Account Suspension Notice",
    "message": "Your access is suspended pending review.",
    "until": "2026-10-08T14:00:00Z",
    "source": "safety_violation",
    "reference_id": "<safety violation id>",
    "applied_at": "2026-10-07T21:40:10+00:00"
  }
}
```

- `datetime_to_allow` set means a suspension that ends on its own; `null` means a block.
- `notice` is written by `execute_safety_violation_action` when an approved safety suspension or block takes effect. Its title and message are exactly the ones in the notification sent to the user, including the default text used when the reviewer left the notification blank.
- Control Center writes replace the whole `access` value, so restoring access there also clears the notice. A restriction applied from Control Center has no notice, and the screen shows generic copy for it.
- A notice written for a different kind of restriction than the one now stored is ignored.

### Access gate

`user_required` still decides access with `check_user_access_status(user_id)`, whose signature and return values are unchanged. Both it and the new `get_user_access_restriction(user_id)` read the setting through `functions_access_restriction.describe_access_restriction`, so they always agree:

- A suspension whose restore time has passed is restored on read, as before, which clears the notice.
- A failure to read the settings allows access, as before, so a storage fault never locks users out.
- A restore time without a UTC offset is read as UTC, as Control Center reads it. Previously such a value made the comparison fail and the user was let in.
- A restore time that cannot be parsed keeps the deny in force with no end date, and is described as a block.

When a non-Admin user is restricted:

| Request | Response |
| --- | --- |
| API call (`/api/...`, or a request that accepts JSON and not HTML) | `403 {"error": "access_restricted", "message": <sentence>, "restriction": {...}, "restricted_url": <page>}` |
| V2 page (`/v2`, `/v2/...`) | Redirect to `/v2/access-restricted` |
| Any other page | Redirect to `/access-restricted` |

`restriction` holds only the caller's own data: `kind` (`suspended` or `blocked`), `until` (ISO 8601 UTC, suspensions only), `title`, `message` and `reference_id`.

### Routes

These are registered on the `access_restriction` Blueprint with a login-only policy. They must not require `user_required`, because it is what refuses restricted users. None of them accepts a user id; each reads the signed-in user's own settings.

| Route | Purpose |
| --- | --- |
| `GET /v2/access-restricted` | Serves the V2 SPA shell. As a static rule it is matched ahead of the `/v2/<path:subpath>` catch-all. |
| `GET /api/v2/access-restriction` | `{"restricted": bool, "restriction"?: {...}, "branding": {...}}`, with `Cache-Control: no-store`. `branding` carries the application title, logo URLs and classification banner the page draws. An Admin is always `restricted: false`. |
| `GET /access-restricted` | The classic page. Autoescaped Jinja, sanitized settings only, `Cache-Control: no-store`. |

All three are exempt from the Terms of Use gate. The Terms of Use pages require an unrestricted account, so gating the restricted screen on the terms would bounce a restricted user between the two. Idle-session timeout still applies to them, so an idle session ends as usual and the user sees the screen again after signing back in.

### V2 interface

- `lib/apiClient.ts` adds `isAccessRestricted(status, payload)` and sends the tab to `/v2/access-restricted` whenever any call is refused by the gate, so a restriction applied while a tab is open is shown at once. It does not navigate when the tab is already on that page.
- `bootstrapStore.load()` stays on the boot screen while that navigation happens, rather than flashing the "session expired" error.
- `App.tsx` renders `AccessRestrictedPage` outside the bootstrap gate for the `/access-restricted` path and loads nothing the shell needs there.
- The page reads `GET /api/v2/access-restriction`. A restricted account sees the notice title and message as plain text, **Access returns** with the restore time formatted in the reader's locale or "No automatic restore date", the reference when there is one, and **Sign out**. If the account is no longer restricted, for example because the suspension ended, it says so and offers **Continue**. An expired session offers **Sign in**.

### Classic interface

`templates/access_restricted.html` renders the same information without the application navigation, whose calls would all be refused. The restore time is rendered in UTC and `static/js/access-restricted.js` rewrites it in the reader's locale.

## Usage Instructions

Nothing needs to be enabled. To see the screen:

1. As a safety reviewer, choose **Suspend user** or **Block user** on a violation and save. Another eligible reviewer approves the request in **Approval Requests**.
2. Sign in as the affected user. Every page opens the Access restricted screen with the notice they were sent.
3. Restore access from Control Center, or wait for the suspension to end. The screen then offers **Continue**.

## Testing and Validation

- `functional_tests/test_access_restricted_gate.py`: restriction description and expiry, legacy reasons, the structured 403 for API calls, V2 and classic redirects, the static route winning over the catch-all, caller-only data, expired-suspension restore, the Admin bypass, allow-on-error, the classic page escaping notice text, login-only routes, and the Terms of Use and idle-timeout exemptions. Real modules run in fresh processes with network access blocked, under normal and optimized Python.
- `functional_tests/test_safety_violation_remediation_approvals.py`: suspend and block write the notice with the text the user was sent.
- `functional_tests/test_v2_access_restriction_and_safety_warning_logic.mjs`: the real V2 API client redirects once on the gate's 403 and never loops on the page; the restriction payload is parsed defensively.
- `ui_tests/test_v2_access_restricted_and_safety_warning.py`: a restricted user lands on the page instead of an error, the notice renders as text, the restore time is localized, and blocked and restored accounts read differently.
- `functional_tests/route_tests/`: the three routes are classified as login-only, and the Blueprint is registered with `login_required_blueprint`.

Known limitations:

- The gate covers every route that requires the User role (`user_required`), which includes every chat, workspace and V2 surface. Routes that have only ever required sign-in, such as the classic Profile page and custom pages, are unchanged, so a restricted user can still open them.
- A restricted user cannot acknowledge a pending safety warning until access returns, because the warning routes require an unrestricted account.
