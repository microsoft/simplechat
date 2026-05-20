# Tabular Background Export Scheduler and Worker Recycle Fix

Fixed in version: **0.241.058**

## Issue Description

Large checkpointed tabular generated-output exports could require manual Continue clicks after transient connection failures. Production logs showed the automatic scheduler running, but every scheduler scan failed with a Cosmos DB `BadRequest` before it could pick up queued retry runs. The same log window also showed Gunicorn request-count worker recycling while long exports were active.

## Root Cause Analysis

The scheduler used one broad cross-partition Cosmos SQL query with mixed status predicates, string `CONTAINS` checks, date comparisons, and `ORDER BY`. In production this query failed with `One of the input values is invalid`, so queued retry runs were never automatically claimed. Manual Continue worked because it bypassed that scheduler query and submitted the run directly to the Flask executor.

At the same time, the default Gunicorn `max_requests` recycle could terminate web workers that were hosting long in-process background export work, causing the export to requeue after transient connection errors.

## Version Implemented

Fixed in version: **0.241.058**

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/gunicorn.conf.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_background_generated_exports.py`

### Code Changes Summary

- Replaced the broad scheduler Cosmos query with simple status-specific queries and Python-side due filtering for queued, running, and failed runs.
- Removed scheduler dependence on Cosmos string `CONTAINS`, date comparisons, and `ORDER BY` for retry discovery.
- Added scheduler diagnostics for scanned counts by status and candidate decisions.
- Cleared `next_attempt_at` when a run is claimed and added active-processing-time ETA tracking so paused wall-clock time does not inflate remaining time estimates.
- Made Gunicorn disable request-count recycling by default when `SIMPLECHAT_RUN_BACKGROUND_TASKS` is enabled, with a longer graceful timeout for background-capable workers.

## Testing Approach

- Updated the durable export functional regression to assert the scheduler query shape, Python-side candidate filtering, active-time ETA accounting, and Gunicorn background-task-aware recycle defaults.
- Compiled the modified Python files.

## Impact Analysis

Automatic retries can resume checkpointed generated-output exports without manual hand-holding after transient failures. Long in-process exports are less likely to be interrupted by routine Gunicorn request-count recycling while still preserving explicit environment overrides for deployments that want different worker behavior.

## Validation

### Before

- Scheduler scans repeatedly failed with Cosmos DB `BadRequest`.
- Queued retry runs needed manual Continue to make progress.
- Gunicorn request-count recycling could stop a worker while a long background export was active.
- Estimated remaining time included paused time between attempts.

### After

- Scheduler scans use simpler Cosmos queries and filter retry/stale logic in Python.
- Retryable queued and failed runs can be claimed automatically from checkpoints.
- Background-capable Gunicorn workers do not recycle by request count unless explicitly configured.
- Remaining-time estimates are based on active batch processing time.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.058**.