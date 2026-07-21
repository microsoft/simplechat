# Cosmos REST Container Migration Fix

Fixed in version: **0.250.067**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

Cosmos migration could create the destination database but fail while creating
its first container with HTTP 400 and `One of the specified inputs is invalid`.
After container creation was corrected, raw REST could also fail on the source
document count with a gateway message stating that the cross-partition query
required newer SDK handling.

## Root Cause

Container read responses were copied too broadly into create requests. Cosmos
returns management and service metadata that is not writable, including
backup/statistics fields and nested partition-key metadata. The recursive JSON
conversion also collapsed single-item indexing arrays into objects.

Document progress depended on a cross-partition `COUNT(1)` query. Cosmos SDKs
can consume the returned query plan and execute it across physical partitions,
but this migration intentionally uses raw REST and had no SDK query engine.

## Technical Details

Modified files:

- `scripts/Migration-Cosmos.ps1`
- `functional_tests/test_cosmos_all_containers_migration.py`
- `docs/explanation/features/COSMOS_DB_MIGRATION.md`
- `application/single_app/config.py`

The migration now:

- Builds container writes from an explicit allowlist of supported properties.
- Recursively removes null policy fields while preserving JSON arrays.
- Omits read-only container and partition-key response metadata.
- Uses the paged `GET .../docs` read feed instead of aggregate/query-plan REST
  calls.
- Discards `settings/app_settings` before destination document writes.
- Reports indeterminate active-container document progress until the feed is
  complete while retaining percentage-based overall container progress.

## Validation

The mocked functional test covers realistic container response metadata,
single-item and empty indexing arrays, read-feed continuation, admin-settings
omission, full and differential writes, selective containers, and checkpoint
resume behavior.

Live validation against the previously failing empty source container
successfully created the destination container, verified its compatible
partition key, read the source document feed, and completed with zero copied
documents.

Before the fix, container creation returned HTTP 400. After the fix, the same
container completed successfully through the raw REST migration path.