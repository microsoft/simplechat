# Support Application Title Copy Fix

Fixed in version: **0.241.002**

## Overview

User-facing Support content now uses the configured application title instead of hard-coded `SimpleChat` branding.

## Issue Description

The Send Feedback page and parts of the Support Latest Features catalog still referenced `SimpleChat` directly. That caused user-facing copy in customized environments to ignore `app_title` from `config.py` and Admin Settings.

## Root Cause

The support feature catalog stored user-facing copy as static Python strings, and the Send Feedback experience also used fixed product naming in both the page copy and the generated mail draft subject.

## Technical Details

### Files Modified

- `application/single_app/support_menu_config.py`
- `application/single_app/templates/support_send_feedback.html`
- `application/single_app/route_backend_settings.py`
- `functional_tests/test_support_menu_user_feature.py`
- `functional_tests/test_support_app_title_personalization.py`
- `ui_tests/test_support_latest_features_image_modal.py`
- `ui_tests/test_support_send_feedback_field_selection.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added support-copy personalization helpers that replace `SimpleChat` with the configured `app_title` when building user-facing latest-feature data.
- Updated the Send Feedback page intro text to reference `app_settings.app_title`.
- Updated the user-facing Send Feedback mail draft subject to use the configured application title.
- Added regression coverage for both rendered support metadata and the Send Feedback flow.

## Testing Approach

- Added `functional_tests/test_support_app_title_personalization.py` to validate personalized support content and dynamic Send Feedback subject generation.
- Updated existing support functional coverage in `functional_tests/test_support_menu_user_feature.py`.
- Updated support UI tests to assert Send Feedback copy reflects the application title and that support latest-features text no longer leaks hard-coded `SimpleChat` copy.

## Impact Analysis

- Customized deployments now present consistent product naming across Support Latest Features, Previous Release Features, and Send Feedback.
- Default deployments continue to work without extra configuration because the fallback title remains `Simple Chat`.

## Validation

- Before: Support copy could display `SimpleChat` even when the app title had been customized.
- After: Support copy and the user-visible feedback draft subject resolve the configured application title at runtime.