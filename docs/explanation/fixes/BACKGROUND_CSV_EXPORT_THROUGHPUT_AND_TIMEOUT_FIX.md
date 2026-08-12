# Background CSV Export Throughput and Timeout Fix

Fixed in version: **0.250.070**

Related issue: [#1071](https://github.com/microsoft/simplechat/issues/1071)

## Issue

Large structured CSV exports could appear stalled while a long-running model batch
occupied the background worker. The worker processed only two post-schema batches
at once, and an individual model request had no export-specific timeout.

## Root Cause

The first batch must remain serial because it establishes the validated output
schema used by every later batch. Once that schema existed, the background worker
used a conservative default of two concurrent model batches. A slow or hung model
request could hold the worker far longer than the user-facing progress state
suggested.

## Technical Details

- Increased default post-schema batch concurrency from two to three, within the
  existing maximum of five concurrent batches.
- Added a configurable per-batch model timeout with a five-minute default.
- Caps the batch timeout below the stale-worker threshold so a stuck request is
  requeued before stale-worker recovery can create competing execution.
- Treats a timed-out batch as a retryable timeout, preserving existing durable
  checkpoints and idempotent artifact publication.
- Retains serial schema discovery so parallel batches cannot produce incompatible
  CSV schemas.

Modified files:

- `application/single_app/functions_tabular_generated_exports.py`
- `functional_tests/test_tabular_background_generated_exports.py`
- `application/single_app/config.py`

## Validation

- The focused durable-export functional suite passed 7/7 checks.
- The suite now executes a stalled asynchronous model-call case and verifies it
  produces a retryable timeout rather than waiting indefinitely.
- Existing bounded concurrency, checkpointing, scheduler, and UI polling checks
  continue to pass.

## Impact

For a multi-batch export, post-schema work can now use three concurrent model
batches. This reduces the number of execution windows for common six-batch runs
while preserving the validated schema and ordered output guarantees. A genuinely
stuck batch is retried from its last durable checkpoint instead of indefinitely
occupying a background worker.

## Follow-up

Issue #1071 tracks the broader format-neutral job framework, including
forward-progress detection, benchmark gates, and comparable performance behavior
for CSV, Word, and PowerPoint generation.