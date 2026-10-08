# Orchestration Runs Failing While Their Work Was Still Running Fix

**Version: 0.261.302**

Fixed in version: **0.261.302**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

An orchestrated request that waited on a long tabular analysis replied:

> The request could not be completed.
>
> Saved step inputs changed. Previously completed work will not be repeated.

The plan panel disagreed with that reply. Its header said **The plan could not
complete**, but the analysis step still read **Waiting for results**, the answer
it fed still read **In progress** with a spinner, and the recovery card added
"Required computation is still pending. Its result is not ready to consume." No
**Retry from failed step** button was offered, so the run could never be
recovered. The analysis itself kept running and finished seconds later, with
nothing left to use its result.

Production telemetry for the run, in UTC:

| Time | Event |
| --- | --- |
| 14:24:06 | The native tabular analysis was queued: 1,800 rows in 4 batches. |
| 14:24:07 | The run's request ended with the run **waiting**, as designed. |
| 14:24:27 | All four analysis batches finished; the reduce phase started. |
| 14:24:30.598 | `[COSMOS_THROUGHPUT] Throughput update submitted.` scaled the `settings` container from 1,000 to 2,000 RU. |
| 14:24:30.766 | `[ASC] App settings updated and published successfully.` recorded that scale action in the settings document. |
| 14:24:34.147 | `[ORCHESTRATION_RUNS] Headless execution did not complete.` with `sc_error_type=CheckpointError` and `sc_execution_code=recovery_changed`. |
| about 14:24:36 | The analysis job finished. |

In the previous 14 days, all three `recovery_changed` execution failures in this
deployment came after a settings save, two of them within 6 seconds of it.

## Root cause

### Every settings save looked like a policy change

A saved run binds its checkpoints to the settings its work ran under, so a real
policy change, such as switching a capability off, can't reuse work produced
under the old policy. `functions_orchestration_checkpoints._execution_settings_fingerprint`
hashed the **whole** settings document into the run's `execution_binding` and into
every step's input fingerprint.

That document isn't only configuration:

- The settings store rewrites `_etag`, `_ts` and `_settings_revision` on every
  save.
- Background tasks save their own runtime state into it: the Cosmos DB
  throughput monitor (`cosmos_throughput_*` readings, scale history and
  per-container scale timestamps), semantic search quota warnings
  (`service_health`, saved by searches themselves), Control Center refresh
  times, retention policy run times, the application release check, and the
  log timers that turn debug logging off.

So any save, by an administrator or a background task, changed the fingerprint.
The scheduler continues a waiting run by recomputing its binding with the current
settings. After the 14:24:30 save the binding no longer matched, and
`ContinuationCheckpoints` raised `CheckpointError('recovery_changed')`. The same
mismatch also refused **Retry from failed step** for any failed run once settings
had been saved since it ran.

### An attempt that ended while a step waited was a dead end

The continuation failed as a whole, before it reached any step. Run-level
failures publish the reply without touching the saved steps, so the waiting
analysis step and the answer step behind it stayed `waiting`. Then:

- The V2 plan panel took its step badges and deliverable rows from those step
  states alone, so a failed run still showed **Waiting for results** and
  **In progress**.
- `recovery_projection` reported `result_not_ready` for any `waiting` step, and
  `validate_resume` raised `result_not_ready` when preparing a retry. A failed
  run with a leftover wait could therefore never be retried, although nothing
  would ever finish that wait.

### A retry would have restored the ended attempt's wait

Each checkpoint saves every result its attempt held, including the pending
result of a step that was still waiting. A retry that reused a step completed in
the failed attempt restored that pending result too, so the new attempt saw two
producers for the step it was running again and stopped with `recovery_changed`.

## Fix

### Settings fingerprints ignore storage metadata and runtime state

The new `functions_settings_runtime_state.py` lists what the settings document
holds that is not configuration:

- storage fields: Cosmos DB metadata (`_etag`, `_ts`, `_rid`, `_self`,
  `_attachments`, from `app_settings_store.COSMOS_METADATA_FIELDS`),
  `_settings_revision` and `id`;
- runtime state that background tasks save: `service_health`,
  `control_center_last_refresh`, `retention_policy_last_run`,
  `retention_policy_next_run`, the release-check fields, every
  `functions_logging_timers.LOGGING_TIMERS` key, and the `cosmos_throughput_` and
  `control_center_auto_refresh_` key families.

`_execution_settings_fingerprint` hashes the settings without those keys.
Configuration an administrator saves stays in the fingerprint, so a real policy
change still stops a waiting run and still refuses reuse.

### An ended attempt no longer blocks recovery

- `recovery_projection` reports `result_not_ready` only while the run itself is
  still `waiting` or `running`. In a `failed` or `cancelled` run, a waiting step
  is listed under **Execute on retry**.
- `validate_resume` runs such a step again in the new attempt instead of raising
  `result_not_ready`. A same-attempt continuation is unchanged.
- `restore_context` doesn't restore another run's pending, output-less result or
  its wait. Nothing could have read a pending result, and only its own attempt
  could finish it.

### The plan panel shows what an ended run left unfinished

In the React V2 Run view, when the run has failed, been stopped or been
superseded:

- a step still pending, running or waiting reads **Not finished**, with "The run
  ended before this step finished." in place of its stale progress summary;
- a deliverable whose steps didn't finish reads **Not delivered** with "The run
  ended before this was finished." instead of **In progress**.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_settings_runtime_state.py` | New registry of settings keys that are storage metadata or runtime state. |
| `application/single_app/functions_orchestration_checkpoints.py` | Fingerprints configuration only; doesn't restore another run's pending result. |
| `application/single_app/functions_orchestration_recovery.py` | Ended attempts with a waiting step are retryable. |
| `application/v2_ui/src/lib/orchestrationPlan.ts` | `stepUnfinishedByEndedRun`, and `deliverableRows` takes the run status. |
| `application/v2_ui/src/components/chat/OrchestrationRunView.tsx` | **Not finished** step badges and summaries. |
| `application/v2_ui/src/components/chat/OrchestrationDeliverables.tsx` | Passes the run status to the deliverable rows. |
| `application/single_app/config.py` | Version 0.261.302. |

## Testing

- `functional_tests/test_orchestration_settings_runtime_state_binding.py`
  replays the incident: a waiting run continues after a simulated autoscaler save
  and keeps its binding, while a policy change still stops it with
  `recovery_changed`. It also parses each background settings writer and fails if
  one saves a key the registry doesn't cover.
- `functional_tests/test_orchestration_terminal_wait_retry.py` covers a run that
  failed or was stopped while waiting: retry is offered, the waiting step runs
  again, completed work is reused, and an ended attempt's wait isn't restored in
  either step order. A wait in a run that can still continue keeps blocking a
  retry.
- `ui_tests/test_v2_orchestration_recovery.py` checks **Not finished**,
  **Not delivered** and the retry button in Chromium.

Without the fix, both binding regression tests and five of the terminal-wait tests
fail; the UI test fails without the plan panel changes.

## Impact

| Before | After |
| --- | --- |
| Any settings save, including a Cosmos DB scale action, failed every run waiting at that moment with "Saved step inputs changed". | Background saves don't affect saved runs. Only a configuration change by an administrator does. |
| The same saves refused **Retry from failed step** for earlier failed runs. | Retries reuse saved work unless configuration changed. |
| A failed run with a leftover wait showed **Waiting for results** and **In progress**, and offered no retry. | It shows **Not finished** and **Not delivered**, and offers **Retry from failed step**. |

## Known limitations

- Runs saved before this version carry bindings computed over the whole settings
  document, so they no longer match after the upgrade. Their retry is refused with
  "Saved step inputs changed", as it already was after any settings save. Ask again
  instead.
- When a run fails while its analysis job is still running, the job still runs to
  completion. Its result isn't used, and the retry starts a new job.
