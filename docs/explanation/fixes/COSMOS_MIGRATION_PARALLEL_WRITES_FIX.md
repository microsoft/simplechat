# Cosmos Migration Parallel Writes Fix

Fixed in version: **0.250.069**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

Cosmos migration sent one synchronous REST write at a time. Network latency
was therefore paid serially for every document, making containers with many
items substantially slower than the available destination throughput.

## Root Cause

The document feed was streamed correctly, but each item immediately entered a
blocking `Invoke-WebRequest` call. No other document could begin until that
request and any retry delay completed.

## Technical Details

Modified files:

- `scripts/Migration-Cosmos.ps1`
- `functional_tests/test_cosmos_all_containers_migration.py`
- `functional_tests/test_cosmos_parallel_document_writes.py`
- `docs/explanation/features/COSMOS_DB_MIGRATION.md`
- `application/single_app/config.py`

The migration now supports `MaxConcurrentDocuments`, defaulting to 8 and
limited to 1-64. Documents are converted into write work items containing the
serialized body and logical partition-key header, then processed through a
PowerShell 7 runspace pool. Memory remains bounded by batches no larger than
the source page size or four times the concurrency setting.

Each worker independently signs its REST request and handles HTTP 408, 429,
449, 500, and 503 responses. Cosmos `x-ms-retry-after-ms` is honored without
blocking other workers. Differential HTTP 409 responses remain non-destructive
skips, and full mode retains upsert behavior.

Version **0.250.072** hides in-flight and retry details from the progress bar.
Parallelism and retries remain active, and retry totals continue to be stored
in checkpoint results for diagnostics.

Containers themselves remain sequential so checkpoint ownership, schema
updates, and console progress are deterministic. Setting
`MaxConcurrentDocuments` to 1 uses the original sequential path.

## Validation

The dedicated parallel functional test executes differential and full modes
against a deterministic mock API. It validates copied/skipped counts, upsert
headers, an exact 429 retry-after cycle, and that internal concurrency/retry
details are not rendered in progress.

Live validation migrated 28 documents with four workers, then repeated the
same differential migration and safely skipped all 28 existing documents.

A non-destructive local benchmark against those 28 existing documents took
8.45 seconds with one writer and 2.21 seconds with eight writers, a measured
3.82x speedup. Actual improvement depends on document size, partition
distribution, network latency, and available destination RU/s.

All migration regression tests, PowerShell parsing, Python compilation,
diagnostics, and whitespace checks pass.