# Group Activity Timestamp Overflow Fix

## Issue

The V2 group **Activity** feed (`GET /api/groups/<id>/insights/activity`)
answered 500 `group_settings_unavailable`, and logged an error, whenever one
record in the feed held a timestamp whose UTC offset moves it past the
calendar, for example `0001-01-01T00:30:00+01:00`. One such record hid the
whole feed.

## Root cause

`occurred_at` in `functions_group_insights.py` converted each stored timestamp
to UTC without guarding Python's `OverflowError`, which the conversion raises
before the year 1 or after the year 9999. Only a malformed stored record can
carry such a timestamp.

Fixed in version: **0.261.185**

## Technical details

Files modified: `application/single_app/functions_group_insights.py`.

`occurred_at` now leaves such a timestamp without a time (`occurred_at: null`),
as it already did for any other unreadable timestamp, and the rest of the feed
is shown. The public workspace activity feed, new in the same version, guards
the same case.

## Validation

`functional_tests/test_group_insights_apis.py` (170) pins both calendar edges
and a feed that keeps its other records with no error logged. All three checks
fail on the unfixed module.

## Related

- [Group Settings APIs](../features/GROUP_SETTINGS_APIS.md)
- [V2 Group Settings](../features/V2_GROUP_SETTINGS.md)
