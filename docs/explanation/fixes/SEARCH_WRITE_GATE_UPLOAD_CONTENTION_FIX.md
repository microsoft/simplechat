# Search Write Gate Upload Contention Fix

Fixed in version: **0.261.003**

## Issue

Large uploads of many small Markdown, JSON, or YAML files could partially fail while processing chunks for Azure AI Search in personal, group, or public workspaces. The user-facing error reported that the Data Management Search write gate changed too often to reserve a write slot.

## Root Cause

Document chunk writes and Data Management migrations share a Cosmos-backed write gate so migrations can safely freeze target Azure AI Search writes. This gate is used before writes to the personal, group, and public workspace Search indexes. Under high upload fan-in, many small files can attempt to reserve writer slots against the same gate document at once. The previous reservation path gave up after 12 rapid optimistic-concurrency conflicts, which could happen during normal burst uploads even when no migration was active.

## Technical Details

Files modified:

- `application/single_app/functions_data_management_search_write_fence.py`
- `functional_tests/test_data_management_search_write_fence.py`
- `application/single_app/config.py`

The write-slot reservation loop now waits until the existing request timeout budget is exhausted and sleeps briefly after each ETag conflict. This keeps migration safety intact while allowing normal document ingestion bursts in personal, group, and public workspaces to settle instead of failing immediately.

## Validation

Added regression coverage for repeated transient write-gate conflicts before a successful reservation. Validated the scenario with a direct Python execution because `pytest` was not installed in the selected environment, and compiled the touched Python files successfully.
