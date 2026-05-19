# Large Tabular Generated Export Timeout Fix

Fixed in version: **0.241.046**

## Issue Description

Large tabular generated JSON or CSV exports could appear hung and eventually fail when the work exceeded the Flask/Gunicorn request lifetime. A production log sample showed a 3,539-row workbook export split into 1,592 model batches, with the request terminated by a worker timeout while batch 298 was being processed.

## Root Cause Analysis

The generated structured export path ran synchronously inside the chat request. When the batch count was high, the request could spend hours calling the model and only keep progress in process memory. If Gunicorn terminated the worker, the stream ended, progress was lost, and the UI kept showing the last emitted batch state.

## Version Implemented

Fixed in version: **0.241.046**

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/background_tasks.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/config.py`
- `application/single_app/static/js/chat/chat-messages.js`

### Code Changes Summary

- Added a durable export run container partitioned by user.
- Added background queue, status, processing, retry, and checkpoint helpers.
- Added a scheduler loop that claims and processes due export runs.
- Added an explicit user-scoped generated artifact upload helper for background workers.
- Added a chat status API for current-user export progress.
- Added frontend progress rendering and polling for queued background exports.

### Testing Approach

- Added static functional regression coverage for queue/status/UI wiring.
- Added Playwright UI regression coverage for queued progress and completed download state.
- Compiled all modified Python modules.

## Impact Analysis

Large structured exports no longer rely on a single web request staying alive for the entire model-processing workload. Users get clearer progress, and completed batches are preserved so worker restarts can resume instead of restarting from the beginning.

## Validation

### Before

- The chat request could time out mid-export.
- Progress could stall on the last streamed batch message.
- Completed model batches were not durable until the final file was produced.

### After

- Oversized exports queue a durable background run.
- Progress is visible through the chat card and status API.
- Input and per-batch output checkpoints survive worker restarts.
- The final generated artifact is attached to the chat when complete.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.046**.