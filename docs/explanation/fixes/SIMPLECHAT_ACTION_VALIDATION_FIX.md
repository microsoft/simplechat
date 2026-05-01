# SimpleChat Action Validation Fix

Fixed/Implemented in version: **0.241.023**

## Overview

The workspace Add Action flow could fail when saving the built-in SimpleChat action even though the modal no longer asked for a URL. The browser validation step posted to an admin-only endpoint, and the backend validation path still treated SimpleChat like a generic endpoint-based plugin.

## Root Cause

- Shared browser-side validation in `plugin_common.js` always called `/api/admin/plugins/validate`, which returned `403` for normal workspace users.
- The shared JSON validation helper still enforced a user-provided endpoint for non-SQL plugins unless the calling code had already injected runtime defaults.
- The server-side pre-save validation route did not apply built-in plugin defaults before running manifest health checks.

## Files Modified

- `application/single_app/static/js/plugin_common.js`
- `application/single_app/json_schema_validation.py`
- `application/single_app/plugin_validation_endpoint.py`
- `functional_tests/test_plugin_validation_managed_fields_compatibility.py`
- `ui_tests/test_workspace_simplechat_action_modal.py`

## Code Changes Summary

1. Switched shared browser validation to use a generic authenticated endpoint, `/api/plugins/validate`, instead of the admin-only route.
2. Updated the browser validation helper to treat non-`2xx` validation responses as real validation failures instead of silently proceeding.
3. Added shared plugin-validation defaults for built-in/internal action types, including SimpleChat and internal document search.
4. Applied those defaults before server-side manifest health checks so validation and save use the same rules.
5. Added backend regression coverage for SimpleChat validation without a user-entered endpoint.
6. Extended the workspace SimpleChat modal UI test to cover validation plus save and verify the admin validation route is not used.

## Validation

- Functional test: `functional_tests/test_plugin_validation_managed_fields_compatibility.py`
- UI test: `ui_tests/test_workspace_simplechat_action_modal.py`

## Impact

- Workspace users can now validate and save SimpleChat actions without needing admin permissions.
- Built-in internal actions no longer fail validation just because they do not expose a user-editable endpoint field.
- Shared validation now fails loudly and correctly when the validation endpoint itself rejects a request.