# V2 Control Center Refresh

## Overview

The Users and Groups views, and the figures on the Dashboard that come from them, read stored
snapshots of each user's and group's activity rather than counting live. A refresh recalculates
those snapshots for everyone. It runs on its own on a daily schedule, and the classic Control
Center had a button to run it now, with a readout of when it last ran and when it runs next. V2
had neither: it showed a read-out in Admin Settings and linked to the classic page.

The V2 Control Center now has a **Refresh data** strip under its header. It says when the data was
last refreshed and when the daily refresh runs next, and **Refresh data** runs it now, reports what
it covered, and reloads the section on screen.

**Implemented in version:** **0.261.445** (`application/single_app/config.py`)

**Dependencies:** `route_backend_control_center.py` (the two existing routes below),
`functions_authentication.py` (`control_center_required`), `functions_control_center_schedule.py`
(the schedule read-out), and the V2 Control Center page. No new routes, settings or packages.

## Technical specifications

### Routes

Both routes already existed and are unchanged.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/admin/control-center/refresh` | Recalculates every user's and every group's stored metrics, then stores `control_center_last_refresh` |
| GET | `/api/admin/control-center/refresh-status` | The last refresh and the daily schedule |

Both are behind `control_center_required('admin')`, which the server maps to the
`can_manage_users` capability. V2 draws the strip only for that capability, so a Control Center
Dashboard Reader, who can open the Dashboard but not manage anything, never sees a button that
could only fail.

The refresh answers `{success, message, refreshed_users, failed_users, refreshed_groups,
failed_groups, refresh_timestamp}`. If the data refreshed but the timestamp could not be stored it
answers 500 with `{success: false, error: "Data refreshed, but the refresh timestamp could not be
saved."}`. The status answers `{last_refresh, last_refresh_formatted, auto_refresh_enabled,
auto_refresh_time, auto_refresh_timezone, auto_refresh_next_run_utc}`.

The classic button was labelled "Refresh user, group, public workspace data", but the route covers
users and groups only. Public workspace figures are read from stored records; their list says so
([V2 Control Center](V2_CONTROL_CENTER.md#public-workspaces)). The V2 strip says what the route
does: "Recalculates the stored activity figures for every user and group."

### The strip

`components/controlCenter/RefreshDataStrip.tsx`, with its wording in `lib/controlCenterRefresh.ts`:

- It reads the status when the page opens and shows two lines: **Data last refreshed** (in the
  reader's time, with how long ago) and **Automatic refresh** (daily at the schedule's time and
  zone, with the next run), or "Automatic refresh is off." A stored time with no zone is shown as
  written, "server time", not converted on a guess. A stored value that cannot be read says so; it
  is not reported as "never refreshed". A failed status read shows its error and leaves the button.
- **Refresh data** posts an empty body. While it runs the button reads "Refreshing data…" and is
  `aria-busy`; it stays focusable, and a second click is ignored rather than starting another run.
- A clean run says "Data refreshed. Updated N users and M groups." and clears itself after eight
  seconds. A run that skipped anyone is a **warning**, "Data refreshed with problems. Updated ...;
  ... could not be refreshed.", and stays until the next run, because the figures for those people
  are as old as before. A failure shows the server's message in an alert, and an answer that does
  not say `success: true` is reported as not having finished.
- After a clean or partial run it reads the status again and reloads the section on screen.

### Reloading the section

One run feeds every section, so the strip sits above all of them (`pages/ControlCenterPage.tsx`).
It bumps a data version in a context (`components/controlCenter/refreshContext.ts`); each section
calls `useReloadOnDataRefresh` with the reload it already had:

| Section | What reloads |
| --- | --- |
| Dashboard | Summary and insights, asking the server to bypass its 90-second cache (`force_refresh=1`) |
| Users | The list, and the open detail drawer |
| Groups, Public Workspaces | The list |
| Activity Logs | The log, as its own **Refresh** does |

A failed run reloads nothing. The sections are a `Record<SectionId, ComponentType>`, so a section
without a view is a build error. That replaced the `SectionPlaceholder` branch, which no route
could reach, together with its link to the classic Control Center.

### Admin Settings

The **Automatic Data Refresh** read-out in Operations now links to the V2 Control Center
(`/v2/control-center`, in a new tab) instead of the classic page.

## Usage

Open **Control Center**. Under the title:

1. Read when the data was last refreshed and when the daily refresh runs next.
2. Choose **Refresh data** to recalculate now, for example after a deployment whose schedule has
   not yet fired, when Users reads "Not refreshed".
3. Read the result beside the button. A warning means some users or groups were skipped: the
   counts say how many, and the reasons are in the server's debug log.

The strip does not change the schedule. That is set under Admin Settings > Operations > Automatic
Data Refresh.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_admin_parity.py` | The strip calls the two routes, reads the fields the server provides, follows the admin capability, and the placeholder is gone |
| `functional_tests/test_v2_admin_parity_logic.ts` | Status reading, the last-refresh and schedule wording, outcome reading, and the warning for a partial run |
| `ui_tests/test_v2_control_center_refresh.py` | The built page: both lines, busy state, a second click ignored, success wording, forced Dashboard reload and a status re-read, the activity log reloading, a warning that stays, a failure that reloads nothing, an answer that does not say it finished, an unreadable status, no strip for a dashboard reader, and no overflow at 390px and 1440px |
| `ui_tests/test_v2_admin_operations_settings.py` | The read-out links to `/v2/control-center` in a new tab |
| `ui_tests/test_v2_control_center_dashboard.py`, `_users.py`, `_groups.py`, `_public_workspaces.py`, `_activity_logs.py`, `_data_health_removed.py` | The existing Control Center suites. Their closed fixtures answer `GET /api/admin/control-center/refresh-status`, which every section now requests for a full administrator, so the strip does not count as an unexpected request |

### Known limitations

- A manual refresh moves only the last-refreshed time. The next scheduled run moves when the
  schedule is saved or a scheduled refresh completes, so after a manual run the next-run line is
  unchanged.
- The route recalculates everyone in one request. A large deployment waits for it to finish; the
  button stays busy until it does.
- Not run against a live Cosmos deployment: the tests intercept the two routes.
