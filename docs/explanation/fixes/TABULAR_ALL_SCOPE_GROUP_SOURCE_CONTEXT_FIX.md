# Tabular All-Scope Group Source Context Fix

Fixed/Implemented in version: **0.240.032**

Related config.py update: `VERSION = "0.240.032"`

## Issue Description

Tabular analysis could fail on group or public workbook files when chat document scope was set to `all`, even though the documents were present in search results and visible in blob storage.

The failure showed up as `BlobNotFound` during workbook schema preload for files that were actually stored under group or public blob prefixes.

## Root Cause Analysis

- Hybrid search results already carried per-document `group_id` and `public_workspace_id`, but `collect_workspace_tabular_filenames()` reduced those results to a bare filename set.
- The tabular analysis runner then applied one batch-wide `source_hint`, which resolves to `workspace` whenever `document_scope='all'`.
- As a result, group and public workbook hits discovered in all-scope search were preloaded from the personal workspace container instead of their real blob locations.

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_all_scope_group_source_context.py`

## Code Changes Summary

- Added per-file tabular source-context helpers so search hits and selected documents keep their original `group_id` or `public_workspace_id` metadata.
- Updated both chat and streaming tabular-analysis paths to pass per-file source contexts into `run_tabular_sk_analysis()` instead of relying on one shared `source_hint` for the whole batch.
- Updated schema-preload prompt context so each workbook advertises its own `source_context` metadata to later tool calls.
- Preserved `public_workspace_id` alongside `group_id` on combined search documents so mixed-scope tabular analysis has the metadata it needs.

## Testing Approach

- Functional regression: `functional_tests/test_tabular_all_scope_group_source_context.py`

## Validation

- All-scope tabular search results now preserve group/public source metadata per file.
- Group and public workbook hits found during `document_scope='all'` analysis preload against the correct blob container instead of defaulting to personal workspace storage.
- Explicit selected tabular documents in `all` scope can now resolve from group and public Cosmos containers as well.