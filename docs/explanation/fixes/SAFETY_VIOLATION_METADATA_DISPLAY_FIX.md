# Safety Violation Metadata Display Fix

Fixed in version: **0.261.060**

## Issue description

Safety violation review pages and exports did not consistently show date and user metadata. Older Content Safety log records stored a `timestamp` value but did not always include `created_at` or `last_updated`, which caused cards to show `N/A` and CSV date columns to be blank. CSV exports also emphasized the user ID instead of the user name shown in the violation detail modal.

## Root cause

Content Safety log creation stored `timestamp` but not the standard review metadata fields. Admin list, card, and CSV rendering relied on `created_at` and `last_updated` without normalizing older records. The admin list view also omitted date and user columns even though the detail modal resolved the user display name.

## Technical details

### Files modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_safety.py`
- `application/single_app/static/js/admin/admin-safety-violations.js`
- `application/single_app/templates/admin_safety_violations.html`
- `functional_tests/test_admin_review_record_lifecycle.py`
- `ui_tests/test_admin_review_list_card_views.py`

### Code changes summary

- New safety logs now include `created_at` and `last_updated` alongside the existing `timestamp`.
- Safety log API responses normalize missing dates from `created_at`, `timestamp`, or Cosmos `_ts` metadata.
- Safety log API responses enrich records with `user_name` and `user_email` for admin list views.
- CSV export adds `User Name` and fills `Created At`, `Last Updated`, and archive timestamp fields from normalized metadata.
- The admin list view now includes Created and User columns.
- The card view uses the created date in the upper-left metadata position.
- Archive actions normalize date metadata before saving archive state so archived records retain usable timestamps.

## Validation

- `python .\functional_tests\test_admin_review_record_lifecycle.py`
- `python -m pytest .\ui_tests\test_admin_review_list_card_views.py -q`

## Impact

Admins can now identify safety violations by date and target user directly from list/card views, and exported CSV files contain usable date and user-name metadata for review and reporting workflows.
