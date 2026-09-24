# V2 Admin Update Check Non-Blocking Fix

Fixed/Implemented in version: **0.261.133**

## Issue

V2 Admin Settings showed only loading placeholders until the application release
check finished. The version banner read **Checking for updates...**, and no setting
could be seen or edited until the server had finished checking GitHub for a newer
release.

## Root cause

`v2_admin_get_settings` in `route_backend_v2.py` called
`get_application_update_status` before returning the settings. When the shared
24-hour cache had expired, or the previous attempt could not be cached, that call
did three things before the settings response was sent:

1. Requested the GitHub releases page with a three-second timeout. That timeout
   does not bound DNS resolution, so an unreachable GitHub can take longer.
2. Parsed the page with BeautifulSoup.
3. Saved the result with `update_settings`.

`AdminSettingsPage.tsx` drew the version banner and the settings pane from that
one request and one `loading` flag, so the whole page waited on GitHub.

## Technical changes

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_v2.py` | The settings GET no longer runs the release check or returns `update_status`. Adds `GET /api/v2/admin/update-status`. |
| `application/v2_ui/src/lib/adminFields.ts` | Adds `ApplicationUpdateStatus` and `AdminUpdateStatusResponse`, and removes `update_status` from `AdminSettingsResponse`. |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Requests the release status on its own, at the same time as the settings. |
| `application/single_app/config.py` | Version `0.261.132` -> `0.261.133`. |
| `functional_tests/test_admin_update_banner_version_comparison.py` | Covers both sides of the new boundary. |
| `ui_tests/fixtures/v2_admin_settings.py` | Serves the new endpoint and can hold it to stand in for a slow check. |
| `ui_tests/test_v2_admin_version_status.py` | Adds the pending-check and failed-check regressions. |
| `ui_tests/test_v2_content_screening.py`, `ui_tests/test_agent_delegation_v2.py` | Serve the new endpoint in their closed API fixtures. |

### Code changes

- **The settings GET no longer runs the check.** It still returns `version`, the
  running server version.
- **New `v2_admin_get_update_status` route.** It is defined by
  `register_route_backend_v2_admin`, so the `backend_v2_admin` Blueprint's admin
  guard applies. It also carries `@swagger_route(security=get_auth_security())`,
  `@login_required` and `@admin_required`. It returns
  `{"version": ..., "update_status": ...}`.
  - A GitHub timeout, HTTP error or unparseable page is still reported as a `stale`
    or `unavailable` status in a 200 response.
  - An unexpected failure logs `[APP_UPDATES]` with only the exception type, and
    returns a 500 with a fixed message.
- **`get_application_update_status` is unchanged.** It uses the same releases URL,
  timeout, 24-hour caching of successes and failures, and numeric comparison.
- **The SPA runs the two requests independently.** The release check has its own
  state and effect, and is only requested for administrators. Settings placeholders
  depend only on the settings request. The banner shows **Checking for updates...**
  until the check answers, then the same messages as before. A failed check shows
  **Unable to check for application updates.**

## Behavior and impact

**Before:** after the cache expired, V2 Admin Settings stayed on placeholders for as
long as the GitHub request, parse and cache write took. An unreachable GitHub held
the page for at least the full timeout.

**After:** settings render as soon as they are read and can be edited and saved
while the check is still running. Only the version banner waits.

The check's cache write can now land while the page is already interactive. If an
administrator saves in that same sub-second window, the Redis-backed settings
store may reject one of the two writes through its existing "save in progress"
handling. This can happen at most once per 24-hour refresh, and it is the same as
two administrators saving at the same moment.

Classic Admin Settings is unchanged and still runs the check while it renders.
No settings keys, admin tabs or browser assets were added. The general-user
bootstrap still does not check releases.

## Validation

- **Functional:** `functional_tests/test_admin_update_banner_version_comparison.py`
  passes 12 tests. Two are new:
  - the settings GET never calls the checker, even with an empty cache;
  - the new route has the expected decorator order and registrar, and returns
    `checked` on success, `unavailable` on a timeout, and a safe 500 on an
    unexpected error.

  Both new tests fail against the previous route module.
- **UI:** `ui_tests/test_v2_admin_version_status.py` passes 13 tests. Three are new
  or changed:
  - settings can be saved while the check is still pending, and saving does not
    start another check;
  - a failed check still leaves the settings usable;
  - a failed settings load still shows the release status.

  All three fail against the previous SPA build.
- **Security, routes and docs:** these pass:
  - `functional_tests/test_v2_api_security.py`
  - `functional_tests/test_v2_admin_settings_secret_handling.py`
  - the three `functional_tests/route_tests/test_route_*.py` policy tests
  - `test_docs_site_quality.py`
  - `test_docs_app_surface_coverage.py`
- **Other admin UI suites:** the 13 suites that load V2 Admin Settings or its
  fixtures were run with this change (188 passed). The same 74 tests fail or error
  with and without the change, all in the AI Connections and Custom Connections
  suites plus one content screening test. They were already failing on the
  previous commit, and nothing new fails.
