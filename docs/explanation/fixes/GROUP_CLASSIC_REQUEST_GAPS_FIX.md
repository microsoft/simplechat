# Group Classic Request Gaps Fix

Fixed/Implemented in version: **0.261.160**

## Issue

Three classic group routes mishandled requests the classic page never sends,
but any client could:

- **File downloads.** `PATCH /api/groups/<group_id>/download-settings` read
  `disable_file_downloads` with Python truthiness, so the string `"false"`
  turned downloads off.
- **Retention.** The retention save read its body with `request.get_json()`.
  A body that wasn't JSON raised an unsupported-media error inside the route's
  error handler, and the route answered 500.
- **Statistics.** A custom date at the edge of the calendar, or one that a UTC
  offset carried past it, overflowed the day-by-day series and failed the
  request. The native statistics reader was bounded in 0.261.154; the classic
  route wasn't.

These gaps were recorded by the 0.261.154 group settings work.

## Fix

- **File downloads.** After the existing refusals, a value that isn't a
  boolean is refused with 400 "Set disable_file_downloads to true or false.",
  and nothing is written. The classic page always sends a boolean, so it's
  unaffected.
- **Retention.** The body is read quietly. After the group and role checks,
  anything that isn't a JSON object is refused with 400
  `{"success": false, "error": "A JSON object is required for this request."}`.
- **Statistics.** `functions_stats_windows.py` now holds the bounds and the
  check, and both statistics routes use them. A date outside 2000-01-01 to
  9998-12-31 is refused with 400 "Choose dates between 2000-01-01 and
  9998-12-31." The native reader keeps its 366-day limit, and still reports a
  date out of range before a window that's too long. Classic windows keep no
  length limit.

Public workspace statistics and the profile trends still use the unbounded
window, and are unchanged.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_groups.py` | The downloads value check; classic statistics use the bounded window. |
| `application/single_app/route_backend_retention_policy.py` | The retention body check. |
| `application/single_app/functions_stats_windows.py` | The shared bounds, message and bounded window. |
| `application/single_app/functions_group_insights.py` | The native reader uses the shared bounds. |

## Testing

`functional_tests/test_group_classic_request_gaps.py` (47) covers each refusal,
that nothing is written, that the classic page's boolean still works, the
shared bounds, and that public statistics and profile trends still use the
unbounded window.

## Related

- [Group Settings Write Safety Fix](GROUP_SETTINGS_WRITE_SAFETY_FIX.md)
- [Group Retention Settings Fix](GROUP_RETENTION_SETTINGS_FIX.md)
- [Group Residual Writers Write Safety Fix](GROUP_RESIDUAL_WRITERS_WRITE_SAFETY_FIX.md)
