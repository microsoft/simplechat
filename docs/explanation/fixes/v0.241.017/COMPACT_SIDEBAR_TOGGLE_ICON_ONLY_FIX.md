# Compact Sidebar Toggle Icon-Only Fix - Version 0.241.017

Fixed in version: **0.241.017**

## Issue Description

The compact sidebar collapse control still showed button edging, making it look like a small outlined button instead of a quiet icon-only affordance.

## Root Cause Analysis

The compact control reused Bootstrap's `btn-outline-secondary` class and inherited shared sidebar toggle border styling intended for the large button variant.

## Technical Details

### Files Modified

- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/_sidebar_short_nav.html`
- `application/single_app/static/css/sidebar.css`
- `ui_tests/test_chat_sidebar_toggle_controls.py`
- `application/single_app/config.py`

### Code Changes Summary

- Removed `btn-outline-secondary` from compact sidebar toggle buttons.
- Added compact-specific transparent background, no-border, and no-shadow styles.
- Preserved accessible keyboard focus using an outline only on focus-visible.
- Kept the large sidebar toggle border styling unchanged.
- Updated UI coverage to assert the compact toggle does not use the outline button class.
- Updated `config.py` version to `0.241.017`.

## Testing Approach

- Python syntax checks for edited Python files.
- Jinja parsing for edited sidebar templates.
- Focused UI test collection for chat sidebar toggle coverage.

## Impact Analysis

Users who choose the compact sidebar toggle now see only the layout-sidebar icon. Users who prefer the large toggle keep the bordered full-width button.

## Validation

Before: compact sidebar toggle rendered with a visible outline/button edge.

After: compact sidebar toggle renders as an icon-only control with no persistent border, background, or shadow.
