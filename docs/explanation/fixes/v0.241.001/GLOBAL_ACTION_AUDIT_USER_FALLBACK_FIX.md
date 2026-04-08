# Global Action Audit User Fallback Fix

## Fix Title
Global Action Save Path Defaults Missing Audit User IDs

## Issue Description
`save_global_action()` accepted an optional `user_id`, but callers that omitted it could persist `created_by` and `modified_by` as `null`. This affected flows such as plugin validation repair, which saves plugin manifests through the global action helper without explicitly passing a user ID.

## Root Cause Analysis
- `save_global_action()` never mirrored the existing `save_global_agent()` behavior that resolves `user_id` through `get_current_user_id()` when the caller passes `None`.
- The helper wrote audit fields directly from the unresolved `user_id`, so create operations stored `null` values.
- Update operations preserved an existing `created_by` value even when it was already `null`, which meant previously corrupted audit data could survive indefinitely.

## Version Implemented
Fixed in version: **0.239.103**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/functions_global_actions.py` | Default missing `user_id` from `get_current_user_id()`, fall back to `system`, and repair null `created_by` on update |
| `functional_tests/test_global_action_user_audit_fallback.py` | Added regression coverage for create and update audit-field fallback behavior |
| `application/single_app/config.py` | Version bump to 0.239.103 |

## Code Changes Summary
- Imported `get_current_user_id()` into `functions_global_actions.py`.
- When `user_id` is `None`, the helper now resolves the current authenticated user.
- If no authenticated user is available, the helper falls back to `system` so audit fields remain non-null.
- Existing actions with `created_by=None` are repaired on save by substituting the resolved fallback value.

## Testing Approach
- Added `functional_tests/test_global_action_user_audit_fallback.py`.
- The test stubs the config, authentication, and Key Vault dependencies so it can exercise `save_global_action()` directly.
- Coverage verifies both:
  - Create flow uses `get_current_user_id()` when `user_id` is omitted.
  - Update flow repairs a previously null `created_by` and falls back to `system` when no current user exists.

## Impact Analysis
- Global plugin/action saves now produce stable audit metadata even for internal or repair flows that do not pass a user ID explicitly.
- Existing global actions with missing `created_by` values are corrected the next time they are saved.
- No route or payload contract changes were introduced.

## Validation
- Regression test: `functional_tests/test_global_action_user_audit_fallback.py`
- Before: `created_by` and `modified_by` could be stored as `null`.
- After: both fields resolve to the current user ID or `system`.