# Sidebar Menu State Save Fix

Fixed in version: **0.241.027**

## Issue Description

Collapsing the left sidebar sections could fail with `POST /api/user/settings` returning `400 BAD REQUEST`. When that happened, the menu appeared to collapse for the current page only, then reset back to the default expanded state after navigation.

The issue affected persisted menu state for Workspaces, Support, custom external-link menus such as renamed link groups, Admin Settings, Control Center, and Conversations.

## Root Cause Analysis

The settings endpoint required every `sidebarMenuState` entry to use one of the known menu keys and an exact boolean value. If a saved or client-side state object contained a stale key, a string value such as `"false"`, or any other invalid value, the endpoint rejected the entire update instead of saving the valid menu state.

## Technical Details

### Files Modified

*   `application/single_app/static/js/sidebar.js`
*   `application/single_app/route_backend_users.py`
*   `application/single_app/config.py`
*   `ui_tests/test_sidebar_menu_state_preference.py`
*   `docs/explanation/release_notes.md`

### Code Changes Summary

*   Added client-side normalization so the browser only saves supported sidebar menu keys with boolean values.
*   Added backend normalization so stale keys are ignored and string booleans are converted instead of causing a `400 BAD REQUEST`.
*   Preserved the existing per-user settings storage path by continuing to save state under `sidebarMenuState`.
*   Updated `config.py` from `0.241.026` to `0.241.027` for this fix.

### Testing Approach

*   Expanded `ui_tests/test_sidebar_menu_state_preference.py` to seed legacy invalid menu state, verify the settings API accepts and sanitizes it, then confirm collapsed and expanded state survives page navigation.
*   Ran JavaScript parse checks for the touched sidebar scripts.
*   Ran Python compile checks for the touched backend route, config, and UI test.

## Impact Analysis

The fix is limited to sidebar menu display preferences. It does not change authorization, menu visibility rules, or the configured destinations shown inside each menu.

## Validation

### Before

Collapsing a sidebar menu could send a `sidebarMenuState` update that included stale or invalid values, causing `/api/user/settings` to reject the save with `400 BAD REQUEST`.

### After

Sidebar menu state is normalized before saving and again at the API boundary. Valid menu state persists across page navigation, while stale or invalid values are dropped safely.

### User Experience Improvements

Users can collapse or expand sidebar sections and keep that layout as they move around the app, including for Workspaces, Support, and custom-named external link menus.