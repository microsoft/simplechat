# Tabular Fixed-Window Stale Heartbeat Fix

Fixed in version: **0.250.147**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Large background generated CSV runs could show `Needs Attention` with `Worker heartbeat is stale. Continue will resume from the last checkpoint.` while the worker was still inside a long fixed-window model call. This made the front end look like the run had errored and required manual Continue even when no persisted backend error existed. When a real retry was scheduled, the status text also lacked a safe category explaining why.

The issue affected 300, 3,000, and 30,000-row runs that were still using `fixed-window-v1`. Logs showed accepted full runs such as `row_count=3000`, `batch_count=52`, but the status card exposed stale-heartbeat state after the worker spent more than the Phase 8 two-minute stale interval waiting for the model.

## Root Cause

Phase 8 introduced a short `tabular_generation_stale_seconds` default of 120 seconds for faster rolling-pool recovery. Rolling-pool execution has a heartbeat loop, so that threshold is appropriate there. Fixed-window execution does not heartbeat while awaiting long model calls, and live calls commonly take more than 120 seconds. The shared stale detector therefore marked healthy fixed-window work as stale.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Code Changes

`_is_stale_running_run(...)` now uses the short snapshotted stale interval for rolling-pool runs only. Fixed-window runs use a timeout-aware threshold of at least the configured batch timeout plus a 60-second grace period. This prevents the public status API from surfacing stale-heartbeat recovery while a fixed-window worker is legitimately waiting for the model.

The public status detail now also includes safe retry reason categories, such as model output validation failure or transient provider/connection interruption, without exposing raw provider errors or generated row content.

## Validation

Functional coverage verifies that:

- rolling-pool runs are stale after the short Phase 8 heartbeat window;
- fixed-window runs are not stale during a normal 300-second model timeout window;
- fixed-window runs become stale after the timeout-aware grace period;
- legacy snapshots continue to avoid premature stale detection.
- retry status text exposes safe reason categories without raw error text.

Validated with:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "phase_eight_retry_and_stale or retry_status_detail or token_echo_recovery or background_metadata" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
```

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.146** to **0.250.147** for this false stale-heartbeat status fix and safe retry-reason status text.