# Classic Group Stats Export Fix

Fixed/Implemented in version: **0.261.163**

## Issue

On the classic **Manage group** page, exporting the group's statistics
downloaded nothing and showed "Failed to export group stats." whenever
**Storage Usage** was ticked, and it is ticked when the export dialog opens. So,
with the default choices, a group's statistics couldn't be exported from the
classic page. Unticking Storage Usage was the only way to get a file.

## Root cause

`exportGroupStats` in `static/js/group/manage_group.js` writes the storage rows'
"Formatted" column with `formatBytes`. The module never defines or imports that
function, and nothing else on the page provides it. The public workspace page
has its own copy, but the group page doesn't load that script. So the call
throws a `ReferenceError`, which the export's error handler reports as a failed
export.

The storage section and its `formatBytes` calls came in upstream (#912), so
every classic group export with storage has failed this way since then.

## Fix

`manage_group.js` now defines `formatBytes` beside its other CSV helpers. It
writes sizes in the same format as the public workspace export: `0 B`, then B,
KB, MB, GB or TB, rounded to two decimals, so 1,536 bytes is `1.5 KB`. Sizes of
a petabyte or more stay in TB rather than running past the list of units.

Nothing else about the export changes: the sections, rows, file name and
messages are the same.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/static/js/group/manage_group.js` | Adds `formatBytes`. |
| `functional_tests/test_classic_group_stats_export_fix.py` | New regression test. |

## Testing

`functional_tests/test_classic_group_stats_export_fix.py` runs the real
`exportGroupStats` in Node, together with the module's own CSV and time-window
helpers. The test takes these functions from `manage_group.js` by name, and
stubs only the browser: the checkbox reads, `fetch`, the toast, the dialog and
the file download. A helper the module doesn't define is therefore missing in
the test too.

- With every section ticked, as the dialog opens, the export downloads a CSV
  with all four sections. Its storage rows read `AI Search,1536,1.5 KB` and
  `Blob Storage,1048576,1 MB`, and the only message is "Group stats exported
  successfully."
- With Storage Usage unticked, the export downloads the other sections.
- The formatter's output is checked for nine sizes, from 0 bytes to 2 PiB.

On the unfixed module, the first and third tests fail, with "Failed to export
group stats." and an undefined `formatBytes`. The second passes, as it did
before the fix.

## Validation

| Export | Before | After |
| --- | --- | --- |
| Default choices (every section) | "Failed to export group stats.", nothing downloaded | The CSV downloads |
| Storage Usage unticked | The CSV downloads | The CSV downloads, unchanged |

The ten existing suites that read `manage_group.js` fail identically with and
without the fix.
