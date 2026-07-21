# Cosmos Document Total Progress Fix

Fixed in version: **0.250.071**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

The active Cosmos container bar showed only completed and in-flight document
counts. Operators could see activity, but not the source total, remaining
documents, or percentage for a large container.

## Root Cause

The migration intentionally removed a cross-partition `COUNT(1)` query because
raw REST cannot execute the returned SDK query plan. Progress then treated the
total as unavailable even though Cosmos management metadata exposes container
document statistics.

## Technical Details

Modified files:

- `scripts/Migration-Cosmos.ps1`
- `functional_tests/test_cosmos_all_containers_migration.py`
- `functional_tests/test_cosmos_parallel_document_writes.py`
- `docs/explanation/features/COSMOS_DB_MIGRATION.md`
- `application/single_app/config.py`

For each active container, the migration now resolves `statistics[].documentCount`:

1. From the discovered container definition when available.
2. From a single-container Azure PowerShell ARM read.
3. From an Azure CLI ARM read when PowerShell ARM is unavailable.

The lookup is best-effort and does not block data migration. If neither ARM
client is authenticated, progress displays `Total: unavailable`. The
`settings/app_settings` document is subtracted from the migratable settings
total because it remains intentionally excluded.

Known totals use the existing count progress format, including processed,
total, remaining, and percentage values. Parallel retry and in-flight details
remain internal so the progress display stays focused on migration completion.

## Validation

Sequential and parallel functional tests assert exact total and percentage
status values. A live non-destructive validation of the `feedback` container
recorded `ProcessedCount = 28` and `TotalCount = 28` from ARM metadata while
safely skipping all existing destination documents.

All migration regression tests, PowerShell parsing, Python compilation,
diagnostics, and whitespace checks pass.