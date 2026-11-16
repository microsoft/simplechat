# Classic Public Stats Export Fix

## Issue

On the classic **Manage Public Workspace** page, the storage figures in the
statistics cards and in the exported CSV's storage "Formatted" column read
"2 undefined" for a size past a terabyte, and "NaN undefined" for a missing
size.

## Root cause

The page's `formatBytes` looked up a unit past the end of its list for sizes of
a petabyte or more, and computed a logarithm of a missing size. The classic
group page had the same formatter missing entirely until version 0.261.163.

Fixed in version: **0.261.185**

## Technical details

Files modified: `application/single_app/static/js/public/manage_public_workspace.js`.

`formatBytes` now writes "0 B" for no size, then B to TB to two decimals,
capped at TB. That's the classic group page's formatter, and what the V2
statistics export writes (`formatClassicBytes`).

## Validation

- `functional_tests/test_classic_public_stats_export_fix.py` (4) runs the real
  `exportWorkspaceStats` in Node, with only the browser seams stubbed, and pins
  the CSV section by section, the no-section warning, and the formatter. The
  export and formatter checks fail on the unfixed module.
- `functional_tests/test_v2_public_stats_formatter_parity.mjs` holds the classic
  public formatter to the V2 `formatClassicBytes`.

## Related

- [Classic Group Stats Export Fix](CLASSIC_GROUP_STATS_EXPORT_FIX.md)
- [V2 Public Settings](../features/V2_PUBLIC_SETTINGS.md)
