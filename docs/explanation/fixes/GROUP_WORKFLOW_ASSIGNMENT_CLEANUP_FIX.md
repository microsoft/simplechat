# Group Workflow Assignment Cleanup Fix

Fixed/Implemented in version: **0.241.201**

Related version update:
- `application/single_app/config.py` reports version `0.241.201` for this fix.

## Issue Description

The Admin Settings form could store malformed values in `group_workflow_allowed_group_ids`. Once the hidden group workflow assignment field contained nested escaped JSON or other junk strings, the admin page rendered and resubmitted that inflated payload, eventually making the form data too large to reliably save unrelated settings.

## Root Cause Analysis

The group workflow assignment normalizer accepted any non-empty string as a group ID. When a previously serialized list was stored as a string inside the list, that escaped blob was treated as one valid assignment. The admin JavaScript then loaded the blob into its assignment set and wrote it back to the hidden field as JSON, preserving the bad value instead of shrinking it.

## Technical Details

Files modified:
- `application/single_app/functions_settings.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_group_workflow_assignment_cleanup_fix.py`
- `functional_tests/test_group_workflows_feature.py`

Code changes summary:
- Group workflow assignment IDs now normalize to canonical UUID values only.
- Legacy nested JSON-list strings are recursively unwound so valid group UUIDs can be recovered.
- Malformed escaped payloads, JSON fragments, and arbitrary strings are dropped.
- `get_settings()` persists cleaned group workflow assignment settings back to Cosmos so future admin page loads stay compact.
- `update_settings()` applies the same cleanup before saving settings from any caller.
- Admin Settings JavaScript now performs the same UUID-only cleanup before syncing the hidden form field.

Testing approach:
- Added `functional_tests/test_group_workflow_assignment_cleanup_fix.py` to validate junk removal, nested UUID recovery, idempotent persisted cleanup, UI wiring, and version alignment.
- Updated `functional_tests/test_group_workflows_feature.py` to the current app version.

## Validation

Before:
- A malformed escaped JSON blob could survive as a group workflow assignment ID and keep expanding the hidden Admin Settings payload.

After:
- The hidden Admin Settings field contains only a compact JSON array of valid group UUIDs.
- Valid group assignments survive cleanup, including UUIDs nested in legacy serialized list strings.
- Invalid or malformed values are removed on settings read and before settings save.