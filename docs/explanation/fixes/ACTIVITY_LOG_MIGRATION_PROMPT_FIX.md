# Activity Log Migration Prompt Fix

## Issue

The classic Control Center displayed a recurring activity-log migration banner and made a migration-status request whenever the page loaded. The banner could persist because the check counted legacy `added_to_activity_log` flags rather than checking whether an activity record already existed. Several normal conversation writers do not set that flag, and document processing can fail before its flag is written.

## Root cause

The legacy status endpoint scanned all conversations and document containers across partitions for a missing flag. The page interpreted any missing flag as missing activity logs even though normal application workflows already write activity records. Repeated visits therefore repeated expensive scans and prompted administrators to run a migration that was not necessarily needed.

## Resolution

Implemented in version **0.261.278** (`application/single_app/config.py`):

- Removed the migration banner, confirmation modal, automatic status request, and now-dead migration JavaScript from the classic Control Center.
- Kept the status and backfill APIs for an explicit Data health tool in V2. The status scan now happens only when an administrator chooses Check.
- Made the backfill check for an existing creation record within the corresponding `user_id` partition and workspace type before writing. New backfill records use stable IDs, so overlapping or repeated runs converge rather than adding duplicate events.
- Reports existing records skipped separately from newly migrated records.

## Validation

`functional_tests/test_v2_control_center_foundation.py` checks that the classic UI does not call migration status automatically and that the backfill lookup is resource- and workspace-specific. `ui_tests/test_v2_control_center_data_health.py` verifies that the user must request a check and explicitly confirm a backfill.

## Impact

Opening the classic Control Center no longer triggers four cross-partition count scans or a misleading migration prompt. Administrators retain an explicit diagnostic and recovery path in V2. Existing logs are preserved; the manual backfill skips records that already have matching creation events.

## Update in 0.261.292

The V2 Data health section was removed, and with it the only callers of `GET /api/admin/control-center/migrate/status` and `POST /api/admin/control-center/migrate/all`. Both APIs and the backfill-only `has_activity_log_for_resource` helper were deleted, so neither Control Center offers the backfill any longer. Normal application workflows continue to write activity records, and `build_activity_log_id` still gives idempotent writers stable record IDs. `ui_tests/test_v2_control_center_data_health.py` was replaced by `ui_tests/test_v2_control_center_data_health_removed.py`, and `functional_tests/test_v2_control_center_foundation.py` now checks that the section and APIs stay removed. See [V2 Control Center Cosmos Query Compatibility Fix](V2_CONTROL_CENTER_COSMOS_QUERY_COMPATIBILITY_FIX.md).
