# Tabular LLM Generation Acceleration Phase 7: Independent Batch Retries

Implemented in version: **0.250.143**

Related issue: **microsoft/simplechat#1031**

## Overview

Phase 7 adds opt-in independent retry handling for rolling structured tabular generated exports. When a single batch fails after its model-call attempts, the rolling worker stores a bounded retry record for that batch and continues dispatching unrelated pending batches instead of stopping the whole run immediately.

## Dependencies

- Phase 3 active durable generation plans and plan hashes.
- Phase 5 completion-driven checkpointing.
- Phase 6 rolling worker pool scheduling.
- `enable_tabular_independent_batch_retries` copied into each run's `generation_rollout_settings` snapshot.

## Technical Specifications

Retry records are stored only for failed batches under the existing run prefix:

```text
{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/retry/batch_000001.json
```

Each record contains safe bounded metadata: batch number, source row range, plan hash, lease generation, failure category, safe error code, per-category attempt counts, first/latest failure timestamps, next attempt time, and exhausted/manual-intervention flags. Raw prompts, source rows, model responses, provider error text, and secrets are not persisted in retry records.

The rolling scheduler now maintains a FIFO pending queue and a time-ordered retry heap. Due retries are eligible for dispatch while unrelated pending work continues to fill available model slots. Completed output checkpoints remain authoritative; a committed output deletes stale retry records and completed batches are not regenerated solely because another batch failed.

Repeated model-validation or plan/schema failure signatures open a bounded circuit breaker. The breaker stops new dispatch after repeated safe signatures while allowing in-flight checkpoint work to drain. Rate-limit and transient connection categories do not open the schema circuit breaker.

Manual Continue resets exhausted retry records by clearing their exhausted flag, resetting per-category attempt counts, and setting `next_attempt_at` to the resume time. Completed output checkpoints remain untouched.

## Public Status

The safe public run status includes aggregate retry fields:

- `retry_wait_batch_count`
- `exhausted_batch_count`
- `systemic_failure_circuit_open`
- `systemic_failure_category`
- `systemic_failure_signature`

Running structured exports with pending retry work report a `Running with Retries` status label. Runs stopped by repeated plan/schema signatures report `Needs Review` without exposing raw provider errors.

## Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`

## Testing and Validation

Functional coverage was added to `functional_tests/test_tabular_row_orchestration_scale.py` for:

- Safe retry-ledger metadata and manual Continue reset behavior.
- Independent retry scheduling where one failed rolling batch retries while unrelated batches keep dispatching and checkpointing.
- Existing Phase 5 and Phase 6 checkpoint and rolling-pool behavior after the scheduler change.

Validated with:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "phase_seven" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "phase_five or phase_six or phase_seven" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
```

## Known Limitations

- The retry scheduler remains single-worker and lease-fenced; multi-instance fan-out is intentionally deferred.
- Existing runs keep the retry behavior captured in their run snapshot. Admin setting changes affect new runs unless the run is explicitly resumed under a compatible contract.
- The circuit breaker groups by safe category/code/plan-hash signature, not raw response text.