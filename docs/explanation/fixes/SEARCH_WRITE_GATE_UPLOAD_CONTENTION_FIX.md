# Search Write Gate Upload Contention Fix

Fixed in version: **0.261.004**

## Issue

Large uploads of many small Markdown, JSON, or YAML files could partially fail while processing chunks for Azure AI Search in personal, group, or public workspaces. The user-facing error reported that the Data Management Search write gate changed too often to reserve a write slot. Concurrent Markdown uploads could also intermittently fail with `OrderedDict mutated during iteration` while processing different files in different environments.

## Root Cause

Document chunk writes and Data Management migrations share a Cosmos-backed write gate so migrations can safely freeze target Azure AI Search writes. This gate is used before writes to the personal, group, and public workspace Search indexes. Under high upload fan-in, many small files can attempt to reserve writer slots against the same gate document at once. The previous reservation path gave up after 12 rapid optimistic-concurrency conflicts, and the first retry fix still allowed worker-local upload threads to stampede the same gate document. Markdown processing also wrote one chunk at a time, multiplying gate reservations for a single file.

## Technical Details

Files modified:

- `application/single_app/functions_data_management_search_write_fence.py`
- `application/single_app/functions_documents.py`
- `functional_tests/test_data_management_search_write_fence.py`
- `functional_tests/test_markdown_processing_batches_search_writes.py`
- `application/single_app/config.py`

The write-slot reservation loop now waits until the existing request timeout budget is exhausted, sleeps briefly after each ETag conflict, and serializes Search writes inside each worker process. Markdown processing now collects non-empty chunks and sends them through `save_chunks_batch`, matching the existing batched processors and reducing both Search write gate mutations and embedding/Search client churn.

## Validation

Added regression coverage for repeated transient write-gate conflicts before a successful reservation, worker-local Search write serialization, and Markdown use of the batch chunk writer. Validated the concurrency scenarios with direct Python execution because `pytest` was not installed in the selected environment, and compiled the touched Python files successfully.
