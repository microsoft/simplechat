# Group Auth Helper Binding Fix

Fixed/Implemented in version: **0.241.100**

## Issue Description

Group workspace actions could fail after startup with `name 'get_current_user_info' is not defined` or `name 'get_current_user_id' is not defined`.

This broke three visible flows:

- Creating a new group workspace.
- Changing the active group workspace.
- Uploading files to a group workspace after the active-group switch failed.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.100"`.

## Root Cause Analysis

- `application/single_app/functions_group.py` imported auth and settings helpers with star imports.
- During the full Flask app import path, that star import could capture a partial snapshot of `functions_authentication` before `get_current_user_id` and `get_current_user_info` were defined.
- The same import-order issue also left `update_user_settings` unavailable from the settings snapshot used by the active-group path.
- Later group operations looked up those missing names inside `functions_group.py`, which raised `NameError` and caused downstream group upload attempts to fail because no active group was persisted.

## Technical Details

Files modified:

- `application/single_app/functions_group.py`
- `application/single_app/config.py`
- `functional_tests/test_group_auth_helper_import_order_fix.py`

Code changes summary:

- Replaced the brittle star-import dependencies in `functions_group.py` with runtime access through the live `functions_authentication` and `functions_settings` module objects.
- Updated `create_group(...)`, `update_active_group_for_user(...)`, and `require_active_group(...)` to resolve auth and settings helpers at call time.
- Added a regression test that imports the full app and verifies both helper binding and the create/set-active flows under a request context.

Testing approach:

- Reproduced the failure by importing `app.py` and confirming the auth helper names were missing inside `functions_group.py`.
- Re-ran the same app-import validation after the fix to confirm the helpers remained available.
- Added a focused functional test for the import-order regression.

## Validation

Before:

- Group creation could return a 400 with an error message showing `get_current_user_info` was undefined.
- Active-group changes could fail with a 500 because `get_current_user_id` was undefined.
- Group file uploads could remain queued or fail after the active-group update never completed.

After:

- Group creation resolves the current session user correctly.
- Active-group changes resolve the session user correctly and can persist `activeGroupOid`.
- Group uploads no longer inherit the broken state caused by the failed active-group update.

Related functional tests:

- `functional_tests/test_group_auth_helper_import_order_fix.py`