# AI Search Batch Resume Fix

Fixed in version: **0.250.065**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

AI Search migration state recorded only synonym-map and whole-index status.
After an operator cancelled a large active index, rerunning skipped completed
indexes but restarted the active index at page 1. The attempt counter changed,
but the state file had no committed document key or document counters from
which to resume.

## Root Cause

The shared migration state supported resource-level completion but did not
preserve progress inside an active resource. AI Search document batches were
sent safely and idempotently, but successful batch boundaries were not written
to the JSON checkpoint.

## Technical Details

Files modified:

- `scripts/Migration-State.ps1`
- `scripts/Migration-AISearch.ps1`
- `functional_tests/test_ai_search_all_indexes_migration.py`
- `docs/explanation/features/AI_SEARCH_INDEX_MIGRATION.md`
- `application/single_app/config.py`

The shared state helper now preserves an optional `progress` object when a
resource attempt restarts. AI Search updates that object atomically after each
acknowledged destination batch with:

- Key field and keyset-resume capability
- Source document count
- Last committed source key
- Processed, copied, skipped, and batch counts

On restart, a filterable and sortable key resumes source paging with an OData
`key gt lastCommittedKey` filter. State never advances past pending writes. If
a request succeeded but the process stopped before its checkpoint write, that
last batch can be replayed safely. Indexes without keyset support restart from
the beginning, and changed source counts invalidate the active index position.

Existing schema-version-1 files remain compatible. Older files without a
`progress` object restart their active index once and begin recording batch
progress after the first successful batch.

## Validation

The mocked functional test forces a permanent failure after one successful
batch. It verifies that state records the first batch's key and counters, then
confirms attempt 2 retries only the uncommitted document. Differential, full,
completed-index resume, secret exclusion, and atomic state behavior remain
covered.