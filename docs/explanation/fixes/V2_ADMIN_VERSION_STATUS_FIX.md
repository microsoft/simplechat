# V2 Admin Version Status Fix

Fixed/Implemented in version: **0.261.126**

## Issue and root cause

V2 Admin Settings received the running server version but never rendered it.
Release checking lived inside the classic settings GET route, so opening only
V2 neither checked GitHub nor displayed available updates.

## Technical changes

- `functions_settings.py` now owns `get_application_update_status`, shared by
  `route_frontend_admin_settings.py` and `route_backend_v2.py`.
- The helper preserves the classic releases-page URL, three-second request
  timeout, numeric version comparison, and greatest-numeric-tag selection.
  Cached availability is recomputed against the current server version rather
  than trusting a flag saved by an older deployment.
- Successful checks keep the existing `last_update_check_time` and
  `latest_version_available` cache fields. `last_update_check_attempt_time` and
  `last_update_check_failed` distinguish failed attempts and throttle subsequent
  visits for 24 hours without claiming the check succeeded.
- V2's existing admin-only GET returns an `update_status` projection outside
  editable settings. Existing authorization and secret redaction are unchanged;
  the general-user bootstrap does not check releases.
- `AdminSettingsPage.tsx` and `adminFields.ts` display and type the running
  version, newer-release notice, and unavailable/stale states. The bootstrap
  version remains visible when settings loading fails.
- The classic template uses the same status and labels stale release notices.
- `config.py` advances the application version from **0.261.125** to
  **0.261.126**.

## Behavior and impact

Opening either settings page reuses a fresh shared cache or performs a server-side
GitHub request. A strictly newer release links to the fixed SimpleChat releases
page. Equal and older versions never trigger an update notice. Invalid cached
timestamps or versions cause a new check rather than a page failure.

HTTP failures, timeouts, missing valid release tags, and failed cache writes
produce safe status messages and `[APP_UPDATES]` logs. Failed checks retain
the last successful result as potentially stale information. If settings storage
is unavailable, throttling cannot be persisted and later visits may retry.
The check does not install upgrades or prevent settings editing.

There is no new route, user-facing setting, scheduled task, external browser
asset, or manual refresh button.

## Validation

`functional_tests/test_admin_update_banner_version_comparison.py` exercises the
production checker, parser, comparator, and V2 response projection with mocked
HTTP/storage boundaries. Coverage includes numeric ordering, stale booleans,
shared caching, the exact 24-hour boundary, invalid cache data, failures, and
retained stale results. Isolated function loading does not claim to test
application startup.

`ui_tests/test_v2_admin_version_status.py` exercises the built SPA on desktop and
mobile, version and link visibility, equal/older releases, unavailable/stale
checks, settings-load failure, and settings saves without release metadata.
It also renders the classic version fragment for successful, stale, and unavailable
checks. The eleven browser scenarios and eleven functional tests passed, as did the V2
build and route-policy checks. The broader existing schema suite still reports
an unrelated `m365_trusted_download_hosts` textarea/list default mismatch.

Before this fix, V2-only administrators could not see their running version or
discover updates from Admin Settings. After the fix, both interfaces share release
status and preserve editable settings when GitHub is unavailable.

## Follow-up in 0.261.133

On the V2 shared workspaces branch, this follow-up arrives in 0.261.158.

The V2 release check no longer runs inside the settings GET. It is served by
`GET /api/v2/admin/update-status` and requested alongside the settings, so a
slow or unreachable releases page delays only the version banner. See
[V2 Admin Update Check Non-Blocking Fix](V2_ADMIN_UPDATE_CHECK_NON_BLOCKING_FIX.md).
