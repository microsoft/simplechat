# Tabular Enhanced Citations Schema Summary Fix (v0.240.023)

Fixed/Implemented in version: **0.240.023**

## Overview

Enhanced-citation tabular uploads are supposed to store the original file in blob storage and index a single compact schema-summary chunk for discovery. A regression path in `process_tabular()` still allowed any schema-summary error to silently fall back to legacy row-by-row chunking, which made large CSV and workbook uploads look like standard citations again.

## Root Cause

The enhanced-citation branch built a schema summary inside a broad `try/except`. If any part of that summary generation or indexing path failed, the code logged a warning and continued into the standard row-chunking branch.

For large or wide tabular files this meant:

- the upload created thousands of indexed chunks instead of a single schema summary
- `number_of_pages` reflected legacy chunk counts again
- the workspace experience no longer matched the intended enhanced-citation tabular workflow

## Technical Details

### Files Modified

| File | Change |
| --- | --- |
| `application/single_app/functions_documents.py` | Added bounded schema-summary helpers for tabular files, compact fallback summary generation, and a guard that prevents enhanced-citation uploads from silently reverting to row chunking |
| `application/single_app/config.py` | Bumped version from `0.240.022` to `0.240.023` |
| `functional_tests/test_tabular_enhanced_citations_schema_summary_fix.py` | Added regression coverage for bounded schema summaries, the no-row-fallback guard, and the version bump |

### Code Changes Summary

- Added compact tabular schema-summary helpers that limit sheet count, column count, preview rows, and individual cell length.
- Added a minimal summary fallback that still preserves blob-backed tabular analysis when a richer schema summary cannot be built.
- Changed `process_tabular()` so row-by-row chunking only runs when enhanced citations is disabled.
- Replaced the previous silent fallback behavior with explicit enhanced-citation summary retry/error handling.

## Testing and Validation

- Added `functional_tests/test_tabular_enhanced_citations_schema_summary_fix.py`.
- Verified the helper-generated CSV schema summary stays compact for wide tabular data.
- Verified the tabular processor source now guards row chunking with `not enable_enhanced_citations`.
- Verified the config version was updated to `0.240.023`.

## Impact

- Large enhanced-citation tabular uploads remain in schema-summary mode instead of reverting to legacy chunk indexing.
- Workspace page/chunk counts now stay aligned with the intended enhanced-citation tabular flow.
- Blob-backed tabular analysis remains available even when the richer schema summary needs to be reduced to a compact fallback.

## Related References

- Related config version update: `application/single_app/config.py`
- Related functional test: `functional_tests/test_tabular_enhanced_citations_schema_summary_fix.py`