# Workflow Activity Dark Mode And Layout Fix

Fixed in version: **0.241.043**

## Issue Description

The workflow activity timeline and detail view used light-only surface colors, which made the page hard to read in dark mode. The page also inherited the shared fixed-width container shell, so when the left navigation sidebar was expanded the workflow activity layout lost too much horizontal room and the detail panel became cramped.

## Root Cause Analysis

- The workflow activity stylesheet used hardcoded light backgrounds, borders, and scrollbar colors instead of theme-aware variables.
- The page rendered inside the shared `#main-content.container` shell without a page-specific width override, so the sidebar padding was applied on top of the Bootstrap container max width.
- The layout issue became most noticeable on large screens with the sidebar expanded because the timeline and detail columns had to compete inside a shell that was narrower than the viewport.

## Technical Details

### Files Modified

- `application/single_app/static/css/workflow-activity.css`
- `application/single_app/static/js/workflow/workflow-activity.js`
- `application/single_app/config.py`
- `functional_tests/test_workflow_activity_dark_mode_layout_contract.py`
- `ui_tests/test_workflow_activity_dark_mode_layout.py`

### Code Changes Summary

- Added theme-aware workflow activity surface, border, connector, and scrollbar tokens with explicit dark-mode overrides.
- Updated the workflow activity cards, panels, empty state, detail blocks, and event history items to use those theme tokens.
- Added a page-specific `workflow-activity-main-content` layout mode so the workflow activity page can break out of the shared container max width.
- Kept the widened shell compatible with the existing sidebar toggle behavior by relying on the `sidebar-padding` class already managed by the base layout.

## Testing Approach

- Added `functional_tests/test_workflow_activity_dark_mode_layout_contract.py` to assert the CSS and JavaScript contract for dark mode and widened layout behavior.
- Added `ui_tests/test_workflow_activity_dark_mode_layout.py` to validate the page remains readable in dark mode and roomy with simulated sidebar padding in a browser workflow.

## Validation

### Test Results

- `functional_tests/test_workflow_activity_dark_mode_layout_contract.py` passes locally.
- The UI regression was added but may require `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` to run in an authenticated environment.

### User Experience Improvements

- Workflow activity cards, timeline connectors, and detail surfaces remain readable in dark mode.
- The workflow activity page uses the available viewport width more effectively when the left navigation sidebar is expanded.
- The detail panel retains more usable horizontal space while preserving the workflow timeline layout.