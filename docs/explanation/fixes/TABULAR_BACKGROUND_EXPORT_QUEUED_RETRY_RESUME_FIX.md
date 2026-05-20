# Tabular Background Export Queued Retry Resume Fix

Fixed in version: **0.241.057**

## Issue Description

Checkpointed tabular generated-output exports could remain in `queued` after a transient retry window passed when the deployment had web-process background tasks disabled. The progress card showed the saved checkpoint counts and transient retry count, but did not expose Continue after `next_attempt_at` was in the past.

## Root Cause Analysis

The original chat request submitted the export to the Flask executor, so the first processing attempt could run even when scheduler loops were disabled. After an `APIConnectionError`, the runner correctly requeued the run with `next_attempt_at`, but no scheduler was active to pick it up later. Public status only treated queued runs as manually resumable while they were still waiting for a future retry, so once the retry time passed the UI returned to plain Queued with no recovery action.

## Version Implemented

Fixed in version: **0.241.057**

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_background_generated_exports.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Code Changes Summary

- Added queued retry-due detection so a retryable queued run becomes manually resumable after `next_attempt_at` has passed.
- Added stale queued-run detection so a queued run that sits longer than the configured stale threshold can be resubmitted from checkpoints.
- Added a `retry_due` public status field and clearer Needs Attention status details for overdue queued retries.
- Increased the default scheduler scan limit from 1 to 5 to reduce candidate starvation.
- Added debug-only scheduler scan result logging with processed and skipped candidates.

### Testing Approach

- Updated the durable export functional regression to assert queued retry recovery, stale queued recovery, scheduler scan diagnostics, and the new version header.
- Compiled the modified Python files.

## Impact Analysis

Users can now kick a checkpointed queued retry forward from the progress card even when the automatic scheduler is not running in the web process. The scheduler also has better scan breadth and logging when it is enabled, making future production investigations clearer.

## Validation

### Before

- A run requeued after a transient connection error could sit as Queued after the retry time passed.
- The progress card showed Refresh Status but no Continue button.
- Logs did not show scheduler candidate decisions when no run was processed.

### After

- Overdue queued retries return `can_resume: true` and `status_label: Needs Attention`.
- Stale queued runs can be continued from completed checkpoints.
- Scheduler scans record candidate, processed, and skipped counts in debug logs.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.057**.