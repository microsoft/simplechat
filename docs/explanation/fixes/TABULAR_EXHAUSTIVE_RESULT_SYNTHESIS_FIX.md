# Tabular Exhaustive Result Synthesis Fix

Fixed/Implemented in version: **0.241.006**

## Issue Description

For exhaustive tabular questions such as "list out all of the security controls," the tabular analysis workflow could successfully execute an analytical tool call that returned the full matching result set, but the inner synthesis step could still answer as though it only had workbook schema samples.

## Root Cause Analysis

The main tabular retry guardrails in [route_backend_chats.py](application/single_app/route_backend_chats.py) only treated this kind of bad synthesis as retry-worthy in entity-lookup mode. General analytical requests could therefore accept a response that claimed only sample rows or workbook metadata were available even after a successful `query_tabular_data` call had returned the full result set.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `functional_tests/test_tabular_exhaustive_result_synthesis_fix.py`
- `application/single_app/config.py`

### Code Changes Summary

- Expanded the access-limited synthesis detector to catch responses that say the data only includes sample rows, workbook metadata, or not the full list.
- Added result-coverage helpers that distinguish between full and partial analytical result slices.
- Reused those coverage signals in the primary tabular analysis loop so successful analytical calls can trigger a retry for general analysis mode, not just entity lookup.
- Added prompt guidance telling the tabular synthesis model to treat `returned_rows == total_matches` and `returned_values == distinct_count` as full result availability.

### Testing Approach

- Added a regression test covering full-result exhaustive list retries.
- Added a regression test covering partial-result exhaustive list reruns.

## Validation

### Expected Improvement

- Exhaustive list questions no longer stop at a synthesis response that wrongly claims only schema samples are available after successful analytical tool calls.
- When only a partial slice is returned, the workflow now has explicit retry guidance to rerun the relevant analytical call with a higher limit before answering.

### Related Version Update

- `application/single_app/config.py` updated to `0.241.006`.