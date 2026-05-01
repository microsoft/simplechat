# SimpleChat Admin Action Save Fix

Fixed/Implemented in version: **0.241.065**

## Overview

Saving the built-in SimpleChat action from Global Actions could fail in two places: the summary step in the admin modal threw a browser-side `ReferenceError`, and the admin save route could still reject the manifest for a missing `endpoint` even though SimpleChat is an internal built-in action.

## Root Cause

- `plugin_modal_stepper.js` used `isSimpleChatType` inside `getAuthTypeValue()` without defining the local variable first, which broke Step 5 before the form could finish rendering the summary.
- The admin add/edit routes validated the raw manifest with the plugin health checker after only partially applying runtime defaults.
- For built-in action types like SimpleChat, the incoming payload can legitimately include `endpoint: ""`, and `setdefault(...)` does not replace an already-present blank string.

## Files Modified

- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/config.py`
- `functional_tests/test_simplechat_admin_action_save_fix.py`

## Code Changes Summary

1. Defined the missing `isSimpleChatType` local in the summary auth-type helper so Step 5 can render for SimpleChat actions.
2. Updated built-in action runtime defaults to replace blank endpoints, not just absent ones.
3. Applied `apply_plugin_validation_defaults(...)` inside the admin add/edit routes before running manifest health validation so the health checker sees the same normalized manifest as the shared validation endpoint.
4. Added a focused regression covering the summary-step contract and the admin save normalization path.

## Validation

- Functional test: `functional_tests/test_simplechat_admin_action_save_fix.py`

## Impact

- Global Actions can now render the SimpleChat summary step without a browser-side exception.
- Admin saves no longer reject SimpleChat just because the modal sends an empty `endpoint` field for a built-in action.