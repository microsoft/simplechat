# Cosmos Progress Simplification Fix

Fixed in version: **0.250.072**

The application version was updated in `application/single_app/config.py` for
this fix.

## Issue

The Cosmos active-container progress line displayed source totals together
with in-flight worker and retry counters. Those implementation details made the
line harder to scan even though operators only needed migration completion.

## Technical Details

Parallel document writes remain enabled through `MaxConcurrentDocuments`, and
workers continue independently handling HTTP 408, 429, 449, 500, and 503 with
Cosmos retry-after delays. The progress display now focuses on:

- Processed and total documents.
- Remaining documents and percentage.
- Current document result.
- Cumulative copied and skipped counts.

In-flight and retry counters are no longer displayed. Retry totals remain in
the container checkpoint result for diagnostics.

## Validation

The parallel functional test forces an HTTP 429 response, verifies the retry
occurs exactly once and is recorded in state, and asserts that no in-flight or
retry details appear in progress. The full migration regression suite passes.