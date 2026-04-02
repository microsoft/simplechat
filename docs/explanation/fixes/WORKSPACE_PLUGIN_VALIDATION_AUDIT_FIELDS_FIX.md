# Workspace Plugin Validation Audit Fields Fix

Fixed/Implemented in version: **0.240.011**

## Issue Description

Saving a new personal workspace action could fail with a generic `Failed to save action` message even when the new manifest itself was valid. In the reported case, this surfaced while saving a new Microsoft Graph action.

## Root Cause Analysis

- The personal workspace action editor reloads the full existing action list and posts that list back to `/api/user/plugins` on save.
- Persisted action documents include storage-managed audit fields such as `created_by`, `modified_by`, and `modified_at`.
- `validate_plugin()` only stripped a narrow set of Cosmos metadata fields, so those audit fields caused validation to fail before the new action was saved.
- The workspace and admin modal save handlers also collapsed backend errors into a generic message, which hid the real failure reason from the user.

## Technical Details

### Files Modified

- `application/single_app/json_schema_validation.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/static/js/plugin_common.js`
- `application/single_app/static/js/workspace/workspace_plugins.js`
- `application/single_app/static/js/workspace/workspace_plugins_new.js`
- `application/single_app/static/js/admin/admin_plugins.js`
- `application/single_app/static/js/admin/admin_plugins_new.js`
- `application/single_app/config.py`
- `functional_tests/test_plugin_validation_managed_fields_compatibility.py`

### Code Changes Summary

- Expanded plugin validation sanitization to ignore storage-managed action fields in addition to Cosmos system metadata.
- Updated the user action save route to strip those same storage-managed fields before validating and persisting the posted action list.
- Added a shared client helper to extract backend error messages from failed save responses.
- Updated workspace and admin action modal save flows to respect `validation.valid === false` and show actual backend save errors instead of a generic failure string.
- Added a regression test that covers persisted Microsoft Graph and SQL action validation with audit fields present.

### Testing Approach

- Functional regression: `functional_tests/test_plugin_validation_managed_fields_compatibility.py`

## Validation

### Before

- Any existing persisted personal action containing audit fields could block saving a new action.
- The modal typically showed only `Failed to save action`, which obscured the real validation failure.

### After

- Persisted plugin audit fields no longer break validation during workspace action saves.
- New Microsoft Graph actions can be saved without unrelated existing actions causing validation failures.
- If a save does fail, the modal now shows the backend-provided error message.