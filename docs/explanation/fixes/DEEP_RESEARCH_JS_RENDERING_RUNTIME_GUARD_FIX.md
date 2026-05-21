# Deep Research JavaScript Rendering Runtime Guard Fix

Fixed in version: **0.241.072**

## Issue Description
Admins could leave `Allow JavaScript rendering fallback` enabled even when the app runtime reported that Playwright Chromium could not launch. This made the setting appear available while Deep Research would fail or skip rendered-page review at runtime.

## Root Cause
The Admin Settings page displayed runtime capability details but did not use that capability result to disable the JavaScript rendering setting. The save route also trusted the submitted checkbox value instead of coercing it through the runtime probe.

## Technical Details
- Added `normalize_source_review_js_rendering_enabled()` in `functions_source_review.py` to require verified `js_rendering_available` runtime support before enabling the setting.
- Updated `route_frontend_admin_settings.py` so stale stored values render as disabled/off when Chromium cannot launch and POST saves cannot persist the setting as enabled without runtime support.
- Updated `admin_settings.html` to disable the checkbox and explain that Playwright Chromium must be available before the option can be enabled.
- Updated `ui_tests/test_admin_source_review_settings.py` and `functional_tests/test_source_review_security.py` for regression coverage.
- Updated `config.py` version to `0.241.072`.

## Validation
- Python syntax checks cover the changed Python files and tests.
- Functional Source Review tests validate that the runtime gate returns false when `js_rendering_available` is false.
- Admin Settings UI test validates that the checkbox is disabled when runtime support is unavailable and enabled only when the status reports verified Chromium launch support.

## Impact
Admins can no longer enable Deep Research JavaScript rendering fallback unless the app host can actually launch Playwright Chromium. Existing stale saved values are shown as disabled/off and are coerced off on save until runtime support is available.
