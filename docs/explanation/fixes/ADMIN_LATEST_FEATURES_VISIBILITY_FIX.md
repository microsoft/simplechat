# Admin Latest Features Visibility Fix

Fixed/Implemented in version: **0.261.489**

## Issue

Turning on **Enable Latest Features Destination** did not show the checklist on the User-Facing Latest Features tab until the page was reloaded.

## Root cause

Two elements shared the ID `support_latest_features_settings`. `getElementById` returns only the first, so the toggle updated the Support Menu hint and never the checklist.

## Changes

- `templates/admin/_panes/support-menu.html`: the hint is now `support_latest_features_hint`.
- `templates/admin/_panes/user-facing-latest-features.html`: keeps `support_latest_features_settings`; initial state uses `d-none`.
- `static/js/admin/admin_settings.js`: the toggle updates both elements with `d-none`.

## Validation

`functional_tests/test_admin_latest_features_visibility_toggle.py` checks the IDs and the toggle wiring.
