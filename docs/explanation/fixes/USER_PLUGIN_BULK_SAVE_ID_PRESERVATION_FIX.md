# USER_PLUGIN_BULK_SAVE_ID_PRESERVATION_FIX.md

## User Plugin Bulk Save ID Preservation Fix (v0.240.019)

Fixed/Implemented in version: **0.240.019**

### Issue Description

Bulk saves to `/api/user/plugins` could drop the persisted action `id` before the route finished
its bookkeeping. When a user renamed an existing personal plugin from the workspace UI, the
 request still included the existing `id`, but the route removed it before save and delete logic.

### Root Cause Analysis

`set_user_plugins()` stripped all storage-managed fields directly from the working plugin dict,
including `id`. Later in the same request, the route relied on `plugin.get('id')` to populate
`new_plugin_ids` and decide which existing personal actions should be retained. Because the
 identifier had already been removed, rename flows looked like delete-and-recreate operations.

### Technical Details

Files modified:
- `application/single_app/route_backend_plugins.py`
- `application/single_app/config.py`
- `functional_tests/test_user_plugin_bulk_save_id_preservation.py`

Code changes summary:
- Updated the user bulk-save route to work on a copy of each incoming plugin payload.
- Continued stripping storage-managed audit fields before validation and persistence.
- Preserved `id` so existing personal actions can be matched during rename flows.
- Bumped the application version and added a route-level regression test.

Testing approach:
- Added `functional_tests/test_user_plugin_bulk_save_id_preservation.py` to load the route module
  with isolated stubs and verify that rename payloads keep the original `id`, skip deletion, and
  do not leak storage-managed audit fields into validation/save operations.

Impact analysis:
- Prevents renamed personal plugins from being deleted and recreated with new IDs.
- Keeps route bookkeeping aligned with the persisted record identity sent by the client.
- Maintains existing sanitization for storage-managed audit fields during bulk saves.

### Validation

Before:
- The route removed `id` before validation and delete bookkeeping.
- Renaming a personal plugin could generate a new action ID and delete the existing action.

After:
- The route preserves `id` while still stripping the other storage-managed fields.
- Renamed personal plugins update in place and are no longer misidentified as deletions.