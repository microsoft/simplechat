# Cosmos Throughput Refresh Logging Fix

Fixed/Implemented in version: **0.241.149**

## Issue Description

The Admin Settings Scale tab could appear stuck on `Loading Cosmos throughput status...` without visible backend logs showing where the refresh request was waiting.

## Root Cause Analysis

The status endpoint and helper only logged failures after an exception. Long waits during token acquisition, ARM throughput reads, container throughput scans, or Azure Monitor metrics queries had no start or phase-completion logs.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_refresh_logging.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Added route-level logs when an admin status refresh starts, completes, or fails.
- Added a `refresh_id` correlation value so logs from one browser Refresh click can be followed through backend phases.
- Added ARM request start/completion logs with method, resource kind, status code, elapsed time, and credential acquisition time.
- Added container-list, container-throughput-scan, Azure Monitor metrics, and overall status refresh timing logs.

## Validation

Test results:

- Python syntax validation for changed backend modules.
- Functional source regression test verifies refresh logging markers and correlation fields are present.
- Existing Cosmos throughput autoscale functional regression test still passes.

Before/after comparison:

- Before: the UI could sit on Loading while the backend emitted no useful status until an exception occurred.
- After: each refresh emits traceable backend logs showing the active phase and elapsed timing.

Related config.py version update:

- Application version updated to `0.241.149` in `application/single_app/config.py`.
