# DATA MANAGEMENT SCHEDULER CONTEXT FIX

Fixed in version: **0.250.185**

## Issue Description

The Data Management scheduler emitted repeated backend errors from background task threads: `copy_current_request_context can only be used when a request context is active`.

## Root Cause Analysis

- Background scheduler scans call `submit_data_management_job(app, job_id)` outside a Flask request context.
- That helper used the configured Flask executor whenever available.
- In this app, the executor submission path can copy request context, which is invalid from scheduler threads that do not have an active request.

## Version Implemented

- **0.250.185**

## Files Modified

- `application/single_app/functions_data_management.py`
- `application/single_app/config.py`
- `functional_tests/test_data_management_migration_recovery.py`
- `docs/explanation/release_notes.md`

## Code Changes Summary

- Added an explicit `has_request_context()` guard before using executor submission APIs in `submit_data_management_job()`.
- Preserved executor-backed route submissions when a request context exists.
- Kept the existing worker-thread submission path for scheduler/background submissions.

## Testing Approach

- Added regression coverage proving background submissions without a request context avoid executor APIs and use the worker-thread path.
- Preserved recovery coverage for request-context executor submissions.
- Compiled changed Python files with `py_compile`.

## Impact Analysis

- Data Management scheduler scans no longer repeatedly emit request-context exceptions.
- User-triggered Data Management jobs can still use the configured executor when submitted from routes.
- Existing durable job recovery behavior is preserved.

## Validation

- Before: scheduler scans could call executor APIs from background threads and trigger `copy_current_request_context` errors.
- After: scheduler submissions bypass request-context-copying executor APIs unless a Flask request context is active.
