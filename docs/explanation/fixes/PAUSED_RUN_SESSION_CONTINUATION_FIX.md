# Paused Run Session Continuation Fix

Fixed in version: **0.261.482**

## Issue

In the 0.261.477 and 0.261.478 runs, prompts failed after a pause with `context_unavailable` or
`result_unavailable`, reason `external_identity_session_unavailable`. In 0.261.478 it was two
of 66 prompts. One of the two was eligible for an automatic next attempt and never got one.

What the telemetry shows for each:

1. The run paused (`waiting`) right after a spreadsheet calculation step whose computation was
   still pending, and the request that started it ended.
2. Fifteen to thirty seconds later the background scheduler resumed it.
3. The scheduler was refused when it authorized a retained result, and the run failed.

A paused run whose results came only from workspace documents resumed and completed in the
same test.

## Root cause

A retained result that names an external source (an agent, an action, memory, the web) is
authorized against the signed-in user's session roles on every read. That is deliberate. The
scheduler has no session, so for such a run its resume could only fail: the result is read
again before the next step and again before the answer is published.

The next attempt of a failed run is started by a hook bound to the request that started the
run. A run that fails on the scheduler never reaches that hook.

## Change

### A paused run records whether its results need a session

`HarnessExecution._finalize` saves `continuation_requires_session` when it saves a run as
`waiting`. It is true when a finished result of the run, or a result it was prepared from,
names an external source (`OrchestrationResults.lineage_names_external_source`). The check
reads result manifests only: no content is read and nothing is authorized against a session.
A lineage that cannot be read is treated as needing a session, because a signed-in
continuation can do everything the scheduler can and the reverse is not true.

### The scheduler leaves such a run alone

`_process_run` in `functions_orchestration_scheduler.py` defers a waiting run with that marker
(`session_required`) instead of claiming it. It still enforces the run's deadline: a marked
run past its deadline is closed as `run_timeout` as before.

### The request that started the run continues it

`_continue_waiting_run` in `route_backend_orchestration.py` runs on the run's own worker after
its stream ends, inside the copy of the request context that already starts next attempts. For
a marked run it makes the same claim the scheduler makes, restores the same saved-wait
checkpoints, and runs the rest with the identity the request holds. It tries again while the
pending work is not ready, with a pause that grows from 5 to 30 seconds, and stops when the
run is no longer paused, is cancelled, or passes its deadline. It does not need the page to
stay open.

Because the continued run ends on that worker, a failure after the pause now reaches the
existing hook and is followed by its next attempt when it is eligible.

## What this does not change

- The session requirement. Conversation ownership, access and the user's settings are checked
  again on every read, by the same code.
- A paused run whose results need no session: the scheduler resumes it as before.
- A wait for credentials or for the user's answer: those are continued by their own signed-in
  requests, as before.
- A run that fails on the scheduler for another reason still gets no automatic next attempt.

## Limits

- The identity is the request's, as captured when the run started. A role removed during the
  pause is not seen by the continuation. The automatic next attempt has the same property.
- If the worker is lost during the pause (a restart), nothing continues the run and it is
  closed at its deadline. A signed-in continue route for the browser is the follow-up for that
  case; the client is a separate build and is not changed here.
- Not verified end to end offline. The pieces are tested separately; the proof is a deployed
  run with an action step followed by a spreadsheet calculation.

## Files modified

- `application/single_app/functions_orchestration_results.py`
- `application/single_app/functions_orchestration_execution.py`
- `application/single_app/functions_orchestration_scheduler.py`
- `application/single_app/route_backend_orchestration.py`
- `application/single_app/config.py`
- `functional_tests/test_orchestration_external_results.py`
- `functional_tests/test_orchestration_harness_scheduler.py`
- `functional_tests/test_orchestration_harness_routes.py`

## Validation

- `test_a_result_prepared_from_an_external_source_is_known_without_a_session`: a result that
  names an external source, and one prepared from it, are recognized by a service with no
  catalog and no authorizer; nothing is authorized; reading the same result's content there is
  still refused.
- `test_scheduler_leaves_a_paused_run_that_needs_a_session_to_its_request`: a real paused run
  is saved with the marker false; with the marker true the scheduler defers it, claims nothing
  and opens nothing; any other value is continued as before; past its deadline the marked run
  is closed as `run_timeout`.
- `test_a_pause_is_marked_from_the_results_the_run_holds`: finished and partial results are
  asked about, pending ones are not, and an unreadable lineage counts as needing a session.
- `test_only_a_paused_run_that_needs_this_session_is_continued_by_its_request`: ten states
  that are not continued.
- `test_the_request_continues_its_own_paused_run_until_it_is_no_longer_paused`: the claim,
  the identity and checkpoints passed to the execution, the growing pause, and the three ways
  it stops.
- `test_the_request_hook_continues_a_paused_run_before_following_a_failed_one`.

Before: paused, resumed by the scheduler without a session, failed, no next attempt.
After: paused, left by the scheduler, continued by its own request.

Not run against the deployed application.
