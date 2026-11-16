# Feedback My Routes Filter Unpack Fix

**Fixed in version: 0.261.277**

## Issue

The **Feedback** tab failed for every user in both the classic Profile page and V2 User
Settings. `/feedback/my`, `/feedback/my/stats`, and `/feedback/my/export` all returned
HTTP 500 with `too many values to unpack (expected 2)`.

## Root cause

`_parse_feedback_filters()` in `route_backend_feedback.py` gained a third return value
(the archive state) for the admin feedback views. The three user-facing routes still
unpacked two values, so each one raised before it queried anything.

## Technical details

### Files modified

- `application/single_app/route_backend_feedback.py`: `feedback_my`, `feedback_my_stats`,
  and `feedback_my_export` now unpack `filter_type, filter_ack_bool, _`. User routes
  ignore the archive state, which only applies to the admin review queue.

### Testing

- `functional_tests/test_feedback_my_routes_filter_unpack.py` parses the module. It checks
  that every caller of `_parse_feedback_filters()` unpacks exactly as many values as the
  helper returns, so a future change to the helper fails the test instead of the page.

## Validation

- Before: the Feedback tab showed an error and Export CSV returned a 500.
- After: users see their submitted feedback, summary counts, and the CSV export again.
