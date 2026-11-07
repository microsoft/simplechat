# Statistics Window Span Limit Fix (v0.261.176)

## Issue

The classic statistics routes accepted a custom date range of any length:
- the group statistics on the classic Manage group page;
- the public workspace statistics on the classic manage page;
- the personal statistics on the profile page (`/api/user/activity-trends`).

Each route builds a day-by-day series across the whole range. A request for
2000-01-01 to 9998-12-31, about 2.9 million days, took about 19 seconds of
processing and 1.5 GB of memory on its own. It also built a 114 MB debug string
even with debug output off, and answered with a 114 MB response. Any group or
public workspace member could send it, and the profile route is open to every
signed-in user.

The profile route also had no calendar bound. A date at the calendar's edge
failed with a 500.

Fixed in version: **0.261.176**, tracked in `application/single_app/config.py`.

## Root cause

- Version 0.261.160 moved the classic group statistics to the bounded window
  resolver, and version 0.261.173 moved the public one. That resolver refuses
  dates outside 2000-01-01 to 9998-12-31, but not long spans.
- The native V2 group statistics route capped custom ranges at 366 days in
  its own code (`GROUP_STATS_MAX_CUSTOM_DAYS`), so the classic routes didn't
  benefit.
- The profile route still used the unbounded resolver. This was recorded as a
  follow-up in the public writer-safety contract.

An independent review of the public writer-safety release found the long-span
case.

## Technical details

- `functions_stats_windows.py` defines one limit, `STATS_MAX_CUSTOM_DAYS = 366`.
  The bounded resolver refuses a longer custom range with "Choose a date range
  of 366 days or fewer." (a `StatsDateRangeError`, after the calendar check).
- The V2 group statistics use the shared limit instead of their own constant.
- The profile route uses the bounded resolver.
- The public statistics route formats its "Final stats" debug message only
  when debug output is on.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_stats_windows.py` | The shared limit and its refusal |
| `application/single_app/functions_group_insights.py` | Uses the shared limit |
| `application/single_app/route_frontend_profile.py` | The bounded resolver |
| `application/single_app/route_backend_public_workspaces.py` | The debug message is formatted only when needed |
| `application/single_app/route_backend_groups.py` | A comment corrected at integration |

### Classic pages

None of the three classic pages shows the server's message on a 400:
- **Manage group:** the cards show "Error", and export shows "Unable to load
  stats for export.".
- **Public workspace manage page:** the cards show "N/A", and export shows the
  same generic message.
- **Profile:** the charts render empty, and export shows "Unable to load export
  data.".

Showing the server's message on those pages is a classic follow-up. The V2
statistics show it.

## Validation

- `functional_tests/test_stats_custom_window_cap.py` (10): a 366-day custom
  range passes and a 367-day one is refused, in the resolver and on the group,
  public and profile routes. The profile route refuses edge-offset and pre-2000
  dates. The shared constant is pinned.
- Mutations: restoring the profile route's unbounded resolver, or removing the
  cap, fails the pins.

## Related

- [Public Workspace Writer Safety Fix](PUBLIC_WORKSPACE_WRITER_SAFETY_FIX.md)
- [Group Classic Request Gaps Fix](GROUP_CLASSIC_REQUEST_GAPS_FIX.md)
