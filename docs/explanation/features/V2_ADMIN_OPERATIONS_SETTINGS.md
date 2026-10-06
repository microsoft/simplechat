# V2 Admin Operations Settings

## Overview

The V2 Admin Settings page renders from `admin_settings_fields.py`. A section with no entry
there falls back to scanning the settings document for `enable_*` booleans, which can only
produce switches named after their keys.

Operations was almost entirely undescribed, so that fallback was most of its interface.
Two of its seven sections had partial declarations; the other five rendered as guessed
switches such as "Dai debug" or did not render at all. This work describes the whole group,
moves the rules the classic page used for schedules and timers into shared modules so both
pages and the background checks agree, and replaces the classic page's three setup modals
with in-app guides.

**Implemented in version:** 0.261.260

**Dependencies:** `admin_settings_nav.py` for section ids, the existing
`/api/admin/settings/file-processing-logs/cleanup` endpoint, `swagger_wrapper.py` route
registration, `functions_appinsights.py` exporter state, and the shared V2 Admin Settings
renderer (`AdminSettingsPage.tsx`, `SettingsSection.tsx`, `fields.tsx`).

## What was missing

| Section | V2 before | V2 after |
| --- | --- | --- |
| Automatic Data Refresh | Not rendered | Switch, time picker, timezone with **Use my timezone**, next and last refresh in both zones, link to the Control Center |
| Control Center Access | Two switches | Two switches, an access table that follows unsaved edits, copyable role values, **Role setup guide** |
| Application Insights | One switch | Switch, connection status, running state against the saved value |
| Debug Logging | Switch plus a raw "Dai debug" switch | Switch, nested timer with per-unit limits, turnoff time in the reader's zone, Document Access Index diagnostics with a link to DAI Metrics |
| File Process Logging | One switch | Switch, nested timer, turnoff time, stored log cleanup |
| Health Check | Not rendered | Two switches, full copyable endpoint addresses with live state, **Configuration guide** |
| API Documentation | Not rendered | Switch, running state, copyable documentation links, **Why enable Swagger?** guide |

## Architecture

### Shared rules

Two pure modules hold the rules that the classic save, the V2 normalizer and the
background tasks previously implemented separately or not at all. Neither imports
`config`, so `admin_settings_fields.py` stays importable in isolated tests.

| Module | Holds |
| --- | --- |
| `functions_logging_timers.py` | `LOGGING_TIMERS` key map, per-unit limits, clamping, `calculate_logging_turnoff_time`, `parse_logging_turnoff_time`, `is_logging_turnoff_due`, `resolve_logging_timer_settings` |
| `functions_control_center_schedule.py` | Schedule helpers moved from `functions_control_center.py` (re-exported there), time and timezone validation, `resolve_control_center_auto_refresh_settings` |

`resolve_logging_timer_settings` recalculates a turnoff time only when the timer, duration
or unit changed, the log was newly enabled, or no usable time is stored, so saving an
unrelated setting no longer restarts a timer. `resolve_control_center_auto_refresh_settings`
does the same for the next scheduled refresh.

### Turnoff times in UTC

The classic page stored turnoff times as naive `datetime.now()` values in the server's
clock. They are now stored as UTC ISO strings. `parse_logging_turnoff_time` reads a value
without an offset as server-local time, which is how it was written, so a timer set before
an upgrade still ends when it was meant to. `check_logging_timers_once` compares in UTC for
both logs and logs `[LOGGING_TIMERS]` when it turns one off.

### Schema additions

| Addition | Purpose |
| --- | --- |
| `input_type: "time"` and `"timezone"` on `text` | HH:MM picker; IANA zone with browser suggestions and **Use my timezone** |
| `watches`, `runtime_flag`, `runtime_requires` | Compare a saved switch with how the running process started |
| `timer_keys` | Bind a turnoff readout to one entry of `LOGGING_TIMERS` |
| `endpoints` | Addresses a section exposes, with access level and live-state gate |
| `related_section` | Point a setting at the section its effect appears in; `classic_only` links the classic page |
| `ADMIN_SECTION_GUIDES` | Which section header offers which in-app guide, and its documentation anchor |

Five derived keys are added to `NON_PATCHABLE_KEYS`:
`control_center_auto_refresh_next_run`, `control_center_auto_refresh_hour`,
`control_center_auto_refresh_minute`, `debug_logging_turnoff_time` and
`file_processing_logs_turnoff_time`. `enable_dai_debug` is declared in `V2_ONLY_FIELDS`,
because the classic page has never had a control for it.

### Normalizer

`normalize_admin_settings_updates` now:

- Refuses a refresh time that is not `HH:MM` and a timezone the server's `zoneinfo` does not
  know, as field errors. The classic page still falls back to `02:00` and
  `America/New_York`.
- Clamps a timer duration to its unit's limit and returns a warning saying so.
- Calls `_apply_operations_derivations` to calculate turnoff times and the next refresh with
  the shared helpers, so a V2 save stores the same derived values a classic save does.

### V2 settings payload

`GET /api/v2/admin/settings` adds:

| Key | Contents |
| --- | --- |
| `section_guides` | `get_admin_section_guides()` |
| `runtime_flags.appinsights_connection_configured` | Whether `APPLICATIONINSIGHTS_CONNECTION_STRING` is set |
| `runtime_flags.appinsights_global_logging_active` | Whether the running process started with global logging |
| `runtime_flags.swagger_routes_registered` | Whether the Swagger blueprint is registered on the running app |
| `status_readouts.appinsights_connection` | Missing, exporter-failed or connected, as `{ok, message}` |

Only booleans and fixed messages are returned; the connection string never leaves the
server.

### Frontend components

| File | Role |
| --- | --- |
| `lib/adminOperations.ts` | Pure readout logic, including a TypeScript mirror of the Python schedule and timer rules |
| `components/admin/RefreshScheduleStatus.tsx` | Next and last refresh, in the schedule's zone and the reader's |
| `components/admin/ControlCenterAccessMatrix.tsx` | Access table read from the two switches, unsaved edits included |
| `components/admin/LoggingTimerStatus.tsx` | Turnoff time, or what a save would set |
| `components/admin/RestartStatus.tsx` | Running state against saved and draft values |
| `components/admin/EndpointLinks.tsx` | Full addresses with copy, access level, live state and **Open** |
| `components/admin/FileProcessingLogCleanup.tsx` | Age or delete-all cleanup with confirmation and partial-failure reporting |
| `components/admin/RelatedSectionLink.tsx` | Cross-reference to another section |
| `components/admin/CopyValue.tsx`, `ReadoutRow.tsx`, `useNow.ts` | Shared copy affordance, readout frame and clock |
| `components/admin/guides/*` | Guide frame and building blocks, the three guides, and the guide registry |

### Corrections carried into V2

The classic modals were ported, not copied. Each of these statements was checked against the
code and corrected in the V2 guides and documentation:

| Classic statement | Behavior |
| --- | --- |
| Health checks return JSON with per-dependency results and HTTP 503 when unhealthy | `/external/healthcheck` returns the server time as text; `/external/healthcheckz` returns `{"status", "time"}`; either returns HTTP 400 naming its setting while switched off |
| Swagger requires an admin sign-in | Any signed-in user can open it (`login_required`) |
| A ControlCenterAdmin holder also needs the Admin role | While the requirement is on, ControlCenterAdmin is enough by itself |

The app role registry (`admin_app_roles.py`) also described ControlCenterDashboardReader as
depending on the ControlCenterAdmin requirement. It does not, and the entry now says so.

## Usage

Open **Admin Settings** in V2 and choose **Operations**. Administrator documentation is in
`docs/admin/operations.md`, which the guide dialogs link to by section anchor.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_operations_parity.py` | Every classic control is declared, guides and anchors exist, derived keys are read-only |
| `functional_tests/test_v2_admin_operations_derivations.py` | Shared timer and schedule rules, normalizer validation and derivations, the payload additions, and the TypeScript logic checks |
| `functional_tests/test_v2_admin_operations_logic.ts` | Zone arithmetic across daylight saving, readout states, access table, cleanup requests, relative time |
| `functional_tests/test_app_settings_auxiliary_writers.py` | The background timer check with the shared helpers |
| `functional_tests/test_control_center_auto_refresh_schedule.py` | Schedule helpers after the move |
| `ui_tests/test_v2_admin_operations_settings.py` | The built page: sections, timer and schedule saves, access table, guides, endpoints, restart state, cleanup, and overflow at phone and desktop widths in light and dark |

## Known limitations

- The Document Access Index diagnostics are drawn only by the classic Scale > Cosmos card,
  so the V2 switch links there.
- Application Insights global logging and Swagger still need an App Service restart; V2
  reports whether one is pending but cannot perform it.
- A manual Control Center refresh updates the last-refreshed time only. The next scheduled
  run moves when the schedule is saved or a scheduled refresh completes.
- The timezone suggestions come from the browser. The server validates the saved name
  against its own `zoneinfo` data.
- The classic page's own modals are unchanged and still carry the statements corrected
  above.
