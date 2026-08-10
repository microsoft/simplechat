# Tabular LLM Generation Acceleration Phase 8: Scale, Chaos, and Rollout

Implemented in version: **0.250.144**

Related issue: **microsoft/simplechat#1031**

## Overview

Phase 8 adds the activation and validation layer for the completed tabular generation acceleration pipeline. New runs receive a deterministic canary or control assignment, keep that assignment across resume, expose explicit execution modes, reclaim stale workers promptly, revalidate source versions immediately before publication, and retain a bounded terminal performance summary.

This phase also extends the deterministic scale harness across rollout, crash recovery, source authorization/version checks, and performance reporting. It does not claim that the live 30,000-row LLM throughput gate has passed; that result requires provisioned target-model capacity and an authenticated deployment observation window.

## Dependencies

- Phase 3 immutable generation plans and plan hashes.
- Phase 4 compact row response protocol.
- Phase 5 completion-driven checkpoints.
- Phase 6 rolling worker pool.
- Phase 7 independent per-batch retries.
- Existing conversation ownership, group membership, public workspace visibility, source ETag, lease fencing, and cancellation checks.

## Technical Specifications

### Stable Rollout Assignment

`tabular_generation_rollout_percentage` accepts values from 0 through 100 and defaults to 100 to preserve existing behavior. At queue time, the server hashes the rollout contract version, user ID, conversation ID, and generated run ID into a stable bucket from 1 through 100.

- A bucket within the configured percentage receives the `canary` cohort and the configured effective acceleration settings.
- A bucket outside the configured percentage receives the `control` cohort and legacy handoff, planner, protocol, checkpoint, executor, and retry behavior.
- The percentage, bucket, cohort, hash version, and effective settings are persisted in `generation_rollout_settings`.
- Resume reads the persisted snapshot instead of current administrator settings.

Each run also records `plan_mode`, `executor_mode`, `response_protocol_version`, and `retry_mode`. Independent batch retry is recorded as `independent-batch-v1`; fixed-window or non-independent execution uses `run-level-v1`.

### Recovery and Publication

New runs snapshot `tabular_generation_stale_seconds`, which defaults to 120 seconds and is bounded from 60 through 900 seconds. Phase 7 and older snapshots that do not contain this setting retain the previous 900-second stale interval.

Before a structured export or analysis artifact is uploaded, the worker repeats conversation and workspace authorization and verifies that a source-backed run still references the queued Blob ETag. A changed or deleted source stops publication.

Committed output Blobs remain authoritative after an ambiguous failure. If a worker exits after the output commit but before summary or Cosmos progress updates, resume rebuilds the derived summary and schedules only missing batches without another LLM call for the committed batch.

### Performance Summary

Terminal run records contain a bounded `performance_summary` with:

- Queue, planning, generation, and end-to-end elapsed seconds.
- Durable rows per minute.
- Configured and effective concurrency.
- Retry and transient failure counts.
- Expected and completed row and batch counts.
- Rollout cohort, planner mode, executor mode, response protocol, and retry mode.

The summary contains no prompts, source rows, file paths, provider errors, credentials, or lease holder IDs. Existing per-batch telemetry supplies model/checkpoint latency and token measurements for percentile analysis.

## Rollout Instructions

1. Configure the desired acceleration flags while keeping `tabular_generation_rollout_percentage` at 0 for control-only new runs.
2. Advance new-run assignment through explicit observation windows such as 5, 25, 50, and 100 percent.
3. Compare control and canary completion, retry, throughput, latency, and exact-coverage results by persisted cohort.
4. Roll back by setting the percentage to 0 or disabling an affected capability. Existing runs continue with their saved modes; new runs receive control behavior.

## Testing and Validation

The deterministic functional suite covers:

- Stable canary/control assignment and resume isolation from later setting changes.
- Explicit retry modes and two-minute stale-worker detection for new runs.
- Legacy stale-timeout compatibility.
- Source ETag revalidation before structured and analysis publication.
- Recovery when output commit succeeds but summary and Cosmos progress do not.
- Bounded, content-free performance summaries.
- Existing 300, 3,000, 30,000, and 100,000-row planning, finalization, source authorization, cancellation, checkpoint, and manifest contracts.

Validated locally with:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py application/single_app/functions_settings.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "phase_eight" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
```

## Security and Privacy

- Rollout controls remain backend-only and are removed from sanitized non-admin settings payloads.
- Conversation ownership, group membership, and public workspace visibility are revalidated before artifact publication.
- Source-backed runs revalidate the exact queued ETag before upload.
- Public run status exposes safe modes and aggregate progress only; it does not expose rollout hashes, prompts, row data, provider errors, credentials, or lease identities.

## Known Limitations

- One application worker still owns a run at a time; Phase 8 does not distribute one run across instances.
- Live 30,000-row LLM throughput, connection-pool wait, provider queueing, and model slot utilization require deployment telemetry and are not established by the deterministic local suite.
- The 1,500 durable rows-per-minute and approximately 20-minute stretch targets remain rollout gates, not correctness promises.
- Percentage assignment is per run, so one user may create both control and canary runs during a partial rollout.

## Related Version Update

`application/single_app/config.py` was updated to version **0.250.144** for Phase 8 stable rollout cohorts, stale-worker reclaim, source-version publication checks, deterministic chaos recovery, and bounded performance reporting.