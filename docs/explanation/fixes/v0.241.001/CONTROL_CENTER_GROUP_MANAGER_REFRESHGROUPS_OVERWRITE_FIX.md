# Control Center GroupManager refreshGroups Overwrite Fix

Fixed in version: **0.239.145**

## Issue Description

The embedded `GroupManager` object in `control_center.html` defined `refreshGroups`
twice. In JavaScript object literals, the later property overwrote the earlier
one, which triggered the overwritten-property warning and discarded the version
that showed a loading placeholder before refreshing the groups list.

## Root Cause

An older backward-compatibility alias for `refreshGroups` remained in the same
object literal after the richer implementation had been added earlier in the
file. Because both members used the same property name, the later alias replaced
the intended implementation.

## Files Modified

- `application/single_app/templates/control_center.html`
- `application/single_app/config.py`
- `functional_tests/test_control_center_group_manager_refresh_groups_duplicate_fix.py`

## Code Changes Summary

- Removed the duplicate trailing `refreshGroups` alias from `GroupManager`.
- Kept the single `refreshGroups` implementation that updates the table with a
  loading message before delegating to `loadGroups()`.
- Added a regression test that fails if `refreshGroups` is defined more than
  once in the control center template.
- Updated the application version to `0.239.145`.

## Testing Approach

- Added a focused functional test that scans the control center template and
  asserts `refreshGroups` appears exactly once.
- The same test also verifies the retained implementation still includes the
  loading placeholder text.

## Impact Analysis

The fix removes a static-analysis warning, preserves the intended refresh UX,
and reduces the chance of future regressions caused by duplicated object literal
members in the control center group management script.

## Validation

Before:

- `GroupManager` contained two `refreshGroups` members.
- The second definition silently overwrote the first.

After:

- `GroupManager` contains a single `refreshGroups` member.
- The groups table retains the loading placeholder behavior during refresh.