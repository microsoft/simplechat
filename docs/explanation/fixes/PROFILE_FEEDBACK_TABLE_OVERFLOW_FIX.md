# Profile Feedback Table Overflow Fix

Fixed in version: **0.241.034**

## Issue Description

The profile My Feedback table could show a horizontal scrollbar because it included wide AI response and admin action columns in the list view. Those fields made the table difficult to scan and pushed the row beyond the available card width.

## Root Cause Analysis

- The feedback table rendered eight columns, including long-form AI response and admin action text.
- The table used the generic responsive wrapper, so overflow appeared as a horizontal scrollbar instead of keeping the row inside the profile card.
- Prompt, reason, response, and action cells all used truncation-oriented styles, which still preserved enough column width to make the table exceed the view.

## Technical Details

### Files Modified

- `application/single_app/templates/profile.html`
- `application/single_app/static/js/profile/profile-tabs.js`
- `application/single_app/config.py`
- `functional_tests/test_profile_feedback_table_overflow_fix.py`
- `ui_tests/test_profile_feedback_table_no_scroll.py`

### Code Changes Summary

- Removed AI Response and Admin Action from the visible My Feedback table columns.
- Kept AI response and admin action values available in the Feedback Details modal.
- Added a profile-feedback-specific fixed table layout with wrapping cells and a non-scrolling wrapper.
- Updated feedback table loading, empty, and error row colspans to match the compact six-column table.

## Testing Approach

- Added `functional_tests/test_profile_feedback_table_overflow_fix.py` to validate the compact table contract, six-column colspans, version bump, and retained modal details.
- Added `ui_tests/test_profile_feedback_table_no_scroll.py` to mock feedback API responses, verify the compact column set, assert the table wrapper does not overflow horizontally, and confirm full details remain available from the modal.

## Validation

### Test Results

- JavaScript syntax checks passed for the updated profile renderer.
- Python compile checks passed for the new functional and UI tests.
- `functional_tests/test_profile_feedback_table_overflow_fix.py` passes locally.
- The UI regression test was added but requires `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` to run in an authenticated environment.

### User Experience Improvements

- The My Feedback list view now fits within the profile page card without a horizontal scrollbar.
- Users can scan timestamp, prompt, feedback, reason, acknowledgement, and details without wide administrative fields crowding the table.
- Full AI response and admin action information remains accessible from the row Details view.