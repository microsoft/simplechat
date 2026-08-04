# Cosmos Migration JSON Property, Skip Reporting, and Throttling Recovery Fix

Fixed in version: **0.250.064**

## Issue

The Cosmos DB migration stopped while parsing a document-feed response when a
source document contained a JSON property whose name was an empty string.
PowerShell's default `ConvertFrom-Json` object conversion rejects that valid
JSON shape. Any individual destination write failure also stopped the entire
migration without leaving a durable document-level audit record. A sustained
Cosmos DB HTTP 429 response similarly ended the run after its request retry
budget was exhausted, requiring an administrator to restart it manually.

## Root Cause

Cosmos document responses and writable document clones were converted to
`PSCustomObject`. That representation cannot preserve empty or case-distinct
JSON property names. Parallel write failures were emitted as events, but the
parent migration treated every failed event as fatal.

## Technical Details

- Document feeds and document write responses use
  `ConvertFrom-Json -AsHashtable`, preserving empty, nested-empty, and
  case-distinct property names.
- Writable document clones use the same ordered hash-table representation and
  remove only Cosmos-managed properties before serialization.
- Document preparation failures and document-scoped HTTP 400, 409, 413, and
  422 write failures are skipped without stopping later documents.
- Authentication, connectivity, exhausted transient retries, feed failures,
  and other systemic errors remain fatal.
- Exhausted HTTP 429 document writes enter bounded automatic recovery. The
  script pauses with a per-second progress countdown, then retries only the
  throttled documents. `MaxThrottleRecoveryPauses` defaults to `5`, and
  `ThrottleRecoveryPauseSeconds` defaults to `60`. Once the pause budget is
  exhausted, the failure explains the affected container/document count and
  recommends lowering `MaxConcurrentDocuments`, increasing destination RU
  capacity, or rerunning with the same state file.
- Each affected container records `ErrorSkippedCount` and structured
  `SkippedDocuments` entries in the migration state JSON. Completed containers
  store them under `result`; interrupted or failed containers retain the latest
  audit under `progress`.
- The final summary records the aggregate count and prints an admin warning
  with the state path. If a later systemic error stops the run, the ordinary
  migration failure message and an admin review warning are shown, while any
  earlier document skips remain in the failed container's
  `progress.SkippedDocuments` list.

Files modified:

- `scripts/Migration-Cosmos.ps1`
- `functional_tests/test_cosmos_migration_document_skip_reporting.py`
- `application/single_app/config.py`

## Validation

The focused functional test runs the bounded parallel-write path against a
mock Cosmos REST API. It verifies that a document containing empty and
case-distinct property names is copied unchanged, a rejected document is
recorded, a later document still copies, the state counts are correct, and the
completion output directs the admin to the audit details.

The application version in `application/single_app/config.py` was updated to
`0.250.064` with this fix.