# Control Center Management Pagination Fix - v0.241.024

Fixed in version: **0.241.024**

## Issue Description

Control Center user management had pagination, but the page size was fixed from the client workflow and did not expose the same selectable page-size control used elsewhere. Group management and public workspace management requested a fixed page from the API, so larger result sets could not be navigated from those views.

## Root Cause Analysis

The user management API accepted pagination parameters, but the UI did not expose a page-size selector. The group and public workspace management views rendered pagination placeholders in the template, but the JavaScript hard-coded API calls to the first page with a fixed page size and did not render usable pagination controls.

## Version Implemented

Implemented in version: **0.241.024**

The application version was updated in `application/single_app/config.py` from `0.241.023` to `0.241.024` for this code change.

## Technical Details

Files modified:

- `application/single_app/route_backend_control_center.py`
- `application/single_app/templates/control_center.html`
- `application/single_app/static/js/control-center.js`
- `application/single_app/config.py`
- `functional_tests/test_control_center_management_pagination.py`
- `ui_tests/test_control_center_management_pagination.py`

Code changes summary:

- Added shared backend pagination parsing for Control Center management tables with a default of 25 and a maximum of 250 items per page.
- Added page-size selectors for user, group, and public workspace management using 10, 25, 50, 100, and 250 options.
- Added server-driven pagination rendering for group management and public workspace management.
- Removed hard-coded `page=1` and `per_page=100` requests from group and public workspace loading.
- Added server-side group status filtering and aligned public workspace status filtering with paginated totals.

## Testing Approach

- Added a source-level functional regression test to validate backend pagination helpers, template controls, and JavaScript pagination state.
- Added a Playwright UI test that verifies all three selectors expose the same options and that selected values are sent to the corresponding API endpoints.

## Impact Analysis

Admins can now choose page sizes consistently across user management, group management, and public workspace management. Group and public workspace result sets can be paged without relying on oversized first-page requests, and pagination totals now reflect server-side filters.

## Validation

Before:

- Users were limited to the client’s fixed page-size behavior.
- Groups and public workspaces requested a fixed first page and did not provide usable navigation.

After:

- Users, groups, and public workspaces all expose the same page-size selector.
- Groups and public workspaces render pagination controls and send the selected page and page size to the API.
- Backend pagination defaults, limits, and clamping are shared across all three management endpoints.
