# Automatic continuation never started

Fixed in version: **0.261.459**

## Issue

With "Recover From Step Failures" on, no failed run was followed by a second attempt. On
0.261.458, 73 runs were logged after the setting was turned on (18 November 2026, 19:28 UTC).
Every one was a first attempt, and no `automatic_continuation` line was logged, although at
least eight of the failures (`result_invalid`, `completeness_incomplete`) were of a kind the
server would normally allow to run again. Step recovery inside a run was not affected: it
fired twice and both runs completed.

## Root cause

The server decides; the V2 client starts the attempt. Two things in the client could drop the
start without any message. Neither was confirmed in a browser; both were found by reading the
code, which is why the server now records what it offered (below).

1. **The decision was read through a loader that can return nothing.**
   `loadOrchestrationRecovery` stores what it reads and returns `null` when another reader of
   the same run stored its copy first. When a run fails, the recovery notice and the plan
   panel read the same run at the same moment, so the continuation's read could lose and the
   decision was treated as "no".
2. **The retry was asked for while the conversation was still busy.** The continuation is
   started from the failed run's terminal frame. `retryOrchestrationRun` refuses while the
   chat is streaming or a run of that conversation is still tracked, and the failed run's own
   stream is still closing at that point. The refusal message was then replaced by the
   message shown before, so nothing was visible.

## Files modified

- `application/v2_ui/src/lib/orchestrationController.ts`: `continueFailedRunAutomatically`
  reads the run with `fetchOrchestrationRun` directly, waits up to about 18 seconds for the
  conversation to be idle, and asks at most twice. It stops if the user moves to another
  conversation.
- `application/single_app/functions_orchestration_progress.py`: `log_continuation_offer`.
- `application/single_app/route_backend_orchestration.py`: the run detail route calls it.
- `functional_tests/test_orchestration_automatic_continuation.py`
- `functional_tests/cosmos_response_boundaries.json` (module hash of the route file only)
- `application/single_app/config.py`

## What the server now records

The run detail route logs `[ORCHESTRATION_PROGRESS] Progress recorded.` with `stage`
`automatic_continuation_offer`, once per run and answer per worker:

- `progress_outcome` `offered` and the `recovery` it offered, or
- the reason it did not (`not_eligible`, `confirmation_required`, `external_effect`,
  `round_limit`, `stalled`), with `recovery_reason` holding the recovery projection's own
  reason code.

A run that is still live, a run that did not fail, and a setting that is off are not logged.
`offered` without a later `applied` for the same failure means the client did not start the
attempt. The scorecard lists these lines under "Step recoveries".

## Validation

- `functional_tests/test_orchestration_automatic_continuation.py` and
  `test_orchestration_progress_ledger.py`: 27 passed.
- The V2 client type-checks.
- Not run in a browser and not measured against a live model. The next deployed run decides
  whether the cause is fixed: it should show `offered` lines, and `applied` lines after them.
