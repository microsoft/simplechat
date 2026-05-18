# Profile Safety Category Tags Fix - v0.241.036

Fixed in version: **0.241.036**

## Issue Description

The profile Violations tab displayed triggered content safety categories as a comma-separated text list such as `Hate(s=0), SelfHarm(s=0), Sexual..., Violence...`. Categories with a score below 1 were still visible, which made inactive safety categories look like triggered findings.

## Root Cause Analysis

The profile tab formatted every stored `triggered_categories` entry as plain text without applying the severity filtering already used by the admin safety review UI. The table and detail modal both reused that comma-separated formatter.

## Version Implemented

Implemented in version: **0.241.036**

The application version is tracked in `application/single_app/config.py` and now reads `0.241.036` for this code change.

## Technical Details

Files modified:

- `application/single_app/static/js/profile/profile-tabs.js`
- `application/single_app/config.py`
- `ui_tests/fixtures/profile_violations_harness.html`
- `ui_tests/test_profile_violations_category_badges.py`

Code changes summary:

- Added profile-side safety category normalization that keeps only categories with severity scores from 1 through 4.
- Rendered the remaining categories as Bootstrap badge tags in the profile violations table.
- Rendered the same filtered badge tags in the View/Edit violation detail modal.
- Added a focused Playwright regression harness for profile violation category rendering.

## Testing Approach

- Added a UI regression test that serves a static profile harness and mocks the safety log API response.
- The test verifies that `Hate` with severity `0` is hidden while `Violence` with severity `2` and `SelfHarm` with severity `4` render as badge tags in both the table and detail modal.

## Impact Analysis

Users now see only categories that actually crossed the visible threshold, presented as compact tags instead of a dense comma-separated list. This aligns the profile experience with the admin safety review page and reduces confusion when reviewing personal safety violations.

## Validation

Before:

- All stored category entries were shown as plain comma-separated text.
- Severity `0` categories appeared even though they were not active findings.

After:

- Only severity `1` through `4` categories render.
- Each visible category appears as an individual badge tag in the table and detail modal.