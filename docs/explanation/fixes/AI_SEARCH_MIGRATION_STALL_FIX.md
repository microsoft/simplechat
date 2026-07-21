# AI Search Migration Stall Fix

Fixed in version: **0.250.063**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

Large AI Search migrations could remain at zero processed documents after
creating the destination index. The console showed no page activity, timeout,
or transfer logs, making a slow request indistinguishable from a stalled
process. Whitespace accidentally included in a configured service name could
also produce an invalid hostname.

## Root Cause

The document reader returned all pages through a PowerShell `foreach`
collection expression. PowerShell completed that producer before the copy loop
processed its first item, buffering a potentially large index in memory.
Additionally, the default Search page contained up to 1,000 full documents;
vector-bearing documents can make that first response expensive to download
and deserialize. REST requests had no explicit timeout, and configured endpoint
components were interpolated without normalization.

## Technical Details

Files modified:

- `scripts/Migration-AISearch.ps1`
- `functional_tests/test_ai_search_all_indexes_migration.py`
- `docs/explanation/features/AI_SEARCH_INDEX_MIGRATION.md`
- `application/single_app/config.py`

The migration now:

- Streams reader output through `ForEach-Object`, allowing destination batches
  to be written before the next source page is requested.
- Defaults source pages to 100 documents while retaining a configurable range
  up to the Search limit of 1,000.
- Displays page number, page size, and timeout before every page request.
- Logs elapsed time for the first, every tenth, and final page.
- Applies a configurable five-minute request timeout and retries timeouts using
  the existing exponential-backoff policy.
- Trims configured names, IDs, suffixes, API versions, and keys before building
  endpoints or ARM paths.
- Validates Search service names and generated absolute endpoint URIs before
  making data-plane calls.

## Validation

The mocked functional test verifies:

- Whitespace-padded parameters resolve to valid source and destination URIs.
- Source page reads and destination writes interleave instead of buffering the
  entire index.
- The configured timeout reaches every REST request.
- Page request details appear in progress records before a fetch begins.
- Differential, full, retry, paging, progress, and ARM key-resolution behavior
  remain intact.

An interrupted migration can be rerun safely. Differential mode copies keys
that remain absent, and full mode uploads all source documents again. Neither
mode deletes destination-only documents.