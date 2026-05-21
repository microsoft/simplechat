# Source Review Depth Save Fix

Fixed/Implemented in version: **0.241.078**

## Issue Description

Admins could enter `2` for Deep Research Source Traversal Depth, and the save action appeared successful, but the page showed the value as `1` again after reload.

## Root Cause Analysis

The Admin Settings form contained an accidental duplicate `source_review_max_depth` input inside the User-Facing Latest Features visibility section. That earlier field was posted before the real Deep Research Source Traversal Depth field, so the backend read the stale first value from the form data.

## Version Implemented

- Application version updated in `application/single_app/config.py` to `0.241.078`.

## Technical Details

### Files Modified

- `application/single_app/templates/admin_settings.html`
- `application/single_app/config.py`
- `functional_tests/test_admin_source_review_depth_save.py`

### Code Changes Summary

- Restored the Latest Features visibility control to the intended `support_latest_feature_{{ feature.id }}` checkbox.
- Removed the duplicate `source_review_max_depth` form field outside the Deep Research settings card.
- Added a regression test to ensure the Admin Settings form contains only one `source_review_max_depth` field.

### Testing Approach

- Static functional test verifies the Source Traversal Depth field name appears exactly once.
- Static functional test verifies the Latest Features section posts feature visibility checkbox names instead of Deep Research settings.

## Impact Analysis

Saving Source Traversal Depth now persists the intended value from the Deep Research settings card. Latest Features visibility checkboxes also render with the expected field names again.

## Validation

Run:

```bash
python functional_tests/test_admin_source_review_depth_save.py
python -m py_compile functional_tests/test_admin_source_review_depth_save.py application/single_app/config.py
```