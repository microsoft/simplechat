# Tabular Background Export Transient Resume Fix

Fixed in version: **0.241.048**

## Issue Description

Durable tabular generated-output runs could still become failed when the background worker hit a transient Azure OpenAI connection interruption during a long export. A production run for `cftc-comments.xlsx` reached batch 183 of 1,592 and then failed after Gunicorn began recycling the worker process.

## Root Cause Analysis

The export was properly checkpointing completed batches, but the runner treated any exception from Semantic Kernel or Azure OpenAI as terminal. During worker recycle, the in-process background thread received an `APIConnectionError('Connection error.')`; the run was marked `failed` even though the completed batch blobs were durable and the next scheduler pass could safely resume.

## Version Implemented

Fixed in version: **0.241.048**

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_background_generated_exports.py`

### Code Changes Summary

- Added retryable error classification for OpenAI/Semantic Kernel connection, timeout, rate-limit, and transient service errors.
- Requeue retryable failures with bounded backoff instead of marking them terminal.
- Let the scheduler reclaim retryable failed runs based on their persisted `last_error` so already-failed checkpointed runs can resume.
- Preserve hard validation failures as terminal failures.

### Testing Approach

- Updated the durable export functional regression to assert transient resume markers are present.
- Compiled the modified Python files.

## Impact Analysis

Long-running generated exports can now survive transient model-service interruptions and Gunicorn worker recycling. The next scheduler pass resumes from completed output checkpoints instead of restarting from the beginning or leaving the run failed.

## Validation

### Before

- `APIConnectionError('Connection error.')` during a background batch marked the entire run `failed`.
- The progress card stopped at the last completed checkpoint.

### After

- Retryable connection failures move the run back to `queued` with a short backoff.
- Retryable failed runs are eligible for scheduler pickup.
- Completed batches remain preserved and the next attempt resumes at the next batch.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.048**.