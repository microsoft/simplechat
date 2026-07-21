# Cosmos Document Progress Fix

Fixed in version: **0.250.068**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

The active-container progress bar updated after the first document and then at
the configured 100-document interval. A container with fewer than 100
documents could therefore appear stalled until it completed, even while REST
writes were succeeding.

## Root Cause

`ProgressUpdateInterval` defaulted to 100, and progress was emitted only after
a document write. The display did not identify the document currently being
sent, so a slow REST request also provided no visible context.

## Technical Details

Modified files:

- `scripts/Migration-Cosmos.ps1`
- `functional_tests/test_cosmos_all_containers_migration.py`
- `docs/explanation/features/COSMOS_DB_MIGRATION.md`
- `application/single_app/config.py`

The migration now defaults `ProgressUpdateInterval` to one document. For each
checkpoint it updates the active-container bar immediately before the REST
write with the current document number and ID, then updates it after the write
with copied/skipped result and cumulative counts. Long IDs are truncated only
for display; the complete document is still written unchanged.

Operators can raise `ProgressUpdateInterval` to reduce terminal rendering
overhead during very large migrations.

Version **0.250.069** sets the operational default to 100 while adding bounded
parallel writes. Set `-ProgressUpdateInterval 1` to retain per-document display
for an interactive run.

## Validation

The functional test verifies that every source document appears in a pre-send
progress record and that post-send records include the result plus cumulative
copied/skipped counts. The full migration regression suite remains green.

The currently running PowerShell process must finish or be resumed before it
can load this updated progress behavior; modifying the script does not change
code already loaded by that process.