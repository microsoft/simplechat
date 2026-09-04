# Data Management Job Step Status Fix

**Fixed in version: 0.260.003**

Fixes #1272. Related: #1258, #1271, #1276.

## Issue Description

On a finished Data Management job, the details panel misrepresented state in two ways:

1. Timeline entries for steps that had clearly finished — `Cosmos DB export step completed`,
   `AI Search export step completed`, `Source blob export step completed` — still displayed a
   `running` badge.
2. The live metrics grid still showed **Current container: Waiting** on a job that had already
   reached `completed_with_warnings`.

Together these made a completed job look stuck. Admins reported the history reading as
"queued, running, then complete" at the job level while individual steps never advanced past
`running`.

## Root Cause

### Step badges stuck on `running`

`_set_job_progress()` used a single `status` value for two different things: the **job**
document and the **timeline event** it recorded.

```python
def _set_job_progress(job, message, completed_steps, total_steps,
                      current_step=None, status=DATA_MANAGEMENT_STATUS_RUNNING, ...):
    job.update({"status": status, ...})
    saved_job = _save_data_management_job(job)
    _record_data_management_job_event(
        saved_job.get("id"), current_step or "progress", saved_job,
        status=status,          # job status, not step outcome
        ...
    )
```

Every call site that announced a finished step relied on the default `status`, which is
`DATA_MANAGEMENT_STATUS_RUNNING`:

```python
_set_job_progress(job, "Cosmos DB export step completed", 1, total_steps, current_step="cosmos")
```

The event was historically accurate — the *job* was running when the step finished — but the
timeline presents that badge as the *step's* state. There was no way to express "this step is
done, the job is not" because both shared one field.

Four migration events recorded through `_record_data_management_job_event()` had the same
problem: `migration-plan`, `migration-preflight`, `migration-cosmos-{target_type}`, and
`migration-reconciliation` all describe finished work but were stamped
`DATA_MANAGEMENT_STATUS_RUNNING`.

The `queued` half of the report was **not** a defect. Every event call site passes an explicit
status, so the `status=DATA_MANAGEMENT_STATUS_QUEUED` default on
`_record_data_management_job_event()` is never actually stranded on a step. The `queued` and
`*-retry-queued` entries genuinely describe queueing actions.

### Stale "Current container"

`_execute_backup_source_blob_resource` writes its final checkpoint after the worker pool
drains, so `telemetry.current_container` is empty at completion. The frontend rendered its
empty-state label unconditionally:

```javascript
{ label: "Current container", value: telemetry.current_container || "Waiting" }
```

`getMigrationLiveMetrics` had the equivalent problem with a hardcoded
`Liveness: Running - ...` row.

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/functions_data_management.py` | Added `step_status` to `_set_job_progress`; added `_complete_job_step`; moved 15 step-completion call sites onto it; corrected 4 migration outcome events |
| `application/single_app/static/js/admin/admin_data_management.js` | Added `isTerminalJobStatus`; gated live-only telemetry rows |
| `functional_tests/test_data_management_job_step_status.py` | New coverage |
| `application/single_app/config.py` | Version bump |

### Code Changes

Step status is now independent of job status:

```python
def _set_job_progress(job, message, completed_steps, total_steps, current_step=None,
                      status=DATA_MANAGEMENT_STATUS_RUNNING, step_status=None,
                      allow_cancel_requested=False):
    ...
    _record_data_management_job_event(
        saved_job.get("id"), current_step or "progress", saved_job,
        # A finished step stays "completed" even while the job itself keeps running.
        status=step_status or status,
        ...
    )


def _complete_job_step(job, message, completed_steps, total_steps, current_step, **kwargs):
    """Advance job progress and stamp the finished step as completed."""
    return _set_job_progress(
        job, message, completed_steps, total_steps,
        current_step=current_step,
        step_status=DATA_MANAGEMENT_STATUS_COMPLETED,
        **kwargs,
    )
```

`step_status` defaults to `None` and falls back to `status`, so every call site that was not
deliberately migrated keeps its previous behavior. Steps that *start* still report `running`,
and genuinely terminal calls such as `Restore completed` still propagate their terminal status
to both the job and the event.

Resulting lifecycle per step: `running` when the step begins, `completed` when it finishes,
while the job stays `running` until it actually completes.

### Frontend

```javascript
function isTerminalJobStatus(status) {
    return ["completed", "completed_with_warnings", "failed", "canceled"].includes(String(status || ""));
}
```

`getBackupLiveMetrics` only emits **Current container** when the job is not terminal, and
`getMigrationLiveMetrics` only emits **Liveness** when the job is not terminal. Cumulative
metrics (processed, transferred, request units, retries, skipped/failed) are unchanged and
still render on finished jobs.

## Validation

### Test Results

`functional_tests/test_data_management_job_step_status.py` — **18 passed**.

Coverage:

- `test_finished_step_is_completed_while_job_keeps_running` — `_complete_job_step` records
  `completed` while the job document stays `running`.
- `test_in_progress_step_still_reports_running` — started steps are unaffected.
- `test_terminal_job_progress_stamps_terminal_step_status` — an explicit terminal job status
  still reaches the final event.
- `test_step_completions_use_the_completed_step_helper` — parameterized across all 12
  step-completion messages.
- `test_migration_outcome_events_are_not_stamped_running` — the 4 migration outcome events.
- `test_terminal_jobs_hide_live_current_container` — the frontend guard precedes the
  **Current container** row.

Broader suite (`-k data_management`) — **175 passed**, with only the two known pre-existing
issues: the `swagger_wrapper` collection error in `test_admin_endpoint.py` and
`test_backup_recovery_and_admin_progress_are_bounded_and_sanitized`.

### Regression Probe

Reverting `status=step_status or status` back to `status=status` failed
`test_finished_step_is_completed_while_job_keeps_running` with
`AssertionError: assert 'running' == 'completed'`, confirming the test fails for the right
reason. The fix was then restored and all 18 tests passed.

### Before / After

| Timeline entry | Before | After |
|----------------|--------|-------|
| `Cosmos DB export step completed` | `running` | `completed` |
| `AI Search export step completed` | `running` | `completed` |
| `Source blob export step completed` | `running` | `completed` |
| `Migration reconciliation completed` | `running` | `completed` |
| Started step (e.g. `Migrating Cosmos records`) | `running` | `running` |
| Job status while steps complete | `running` | `running` |

| Panel row on a finished job | Before | After |
|------------------------------|--------|-------|
| Current container | `Waiting` | hidden |
| Liveness (migration) | `Running - ...` | hidden |
