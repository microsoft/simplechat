# The next attempt is started by the server, not by the page

Fixed in version: **0.261.462**

## Issue

With "Recover From Step Failures" on, a failed run was to be followed by its next attempt
without asking. From 0.261.458 the server decided this and the V2 page started the attempt.
The page started it only for the conversation on screen, in a tab that was streaming nothing
else. A user who sends a request and then opens another conversation, or leaves and comes
back, never got the second attempt. On 19 November 2026 the server offered a next attempt for
two failed runs and no request for either arrived.

The requirement, stated by the project owner the same day: a user must be able to start a
request, move to other conversations or elsewhere, and come back.

## Root cause

Starting work was tied to what a browser tab was showing. A run itself was never tied to the
tab: `_stream_execution` runs it on a server worker that keeps going when the browser
disconnects. Only the step after a failure depended on the page.

## Change

### Server (`route_backend_orchestration.py`)

- `_stream_execution` takes `after`. The worker calls it once the run has been closed and its
  stream ended, whether or not a browser is still attached.
- `_run_saved_plan` passes an `after` when the setting is on. It is bound to the request's
  identity with `copy_current_request_context`, the same way the planning worker runs an Auto
  plan.
- `_continue_failed_run` does the work:
  1. reads the run, waiting up to 10 seconds for the attempt to be released;
  2. applies the same decision as before (`automatic_continuation`): inside the approved
     plan, no external action repeated, no confirmation needed, within the recovery limit,
     not a repeat of the previous failure;
  3. prepares the next attempt with `prepare_retry`, the same fenced code a clicked retry
     uses, and decides again inside its validation;
  4. runs it through `_run_saved_plan`, the same admission every run passes, and reads its
     stream to the end with nobody listening.
- The next attempt carries its own `after`, so attempts chain until the decision is no. The
  recovery limit bounds the chain.
- Anything that fails here is logged and leaves the failed attempt as it was, with its retry
  controls.

No prompt, plan or fence was changed. The retry route still accepts `automatic: true` from a
page that was loaded before this version; only one of the two can create the next attempt,
because `prepare_retry` admits one successor per attempt.

### Page (`application/v2_ui/src/lib/orchestrationController.ts`)

`continueFailedRunAutomatically` no longer asks for a retry. After a run it was following
fails, it reads the saved run until the server's next attempt appears (about 20 seconds at
most), then tracks that attempt with the existing polling (`reconcileOrchestrationRun`). It
shows the attempt's plan only if that conversation is the one open. Which conversation is on
screen no longer affects whether work happens.

A user who was elsewhere finds the result when they return: the next attempt saves its reply
to the conversation as every run does.

## Files modified

- `application/single_app/route_backend_orchestration.py`
- `application/v2_ui/src/lib/orchestrationController.ts`
- `functional_tests/test_orchestration_server_continuation.py` (new)
- `functional_tests/test_orchestration_automatic_continuation.py`
- `functional_tests/cosmos_response_boundaries.json` (module hashes only; no storage call
  changed)
- `application/single_app/config.py`

## Telemetry

- `[ORCHESTRATION_PROGRESS] Progress recorded.`, `stage` `automatic_continuation`,
  `progress_outcome` `applied`: the server prepared the next attempt.
- The same message with `stage` `automatic_continuation_offer` and a reason: why it did not.
- `[ORCHESTRATION_RUNS] The next attempt could not be prepared.` and `... was prepared but
  could not start.` carry the refusal code.
- From 0.261.467 the "could not be prepared" line also says which check refused:
  `reason_code`, `cause_type`, `cause_code`, `validation_rule`, `refusal_stage`,
  `producer_capability_id` and `error_site` (file and line that raised). On 0.261.463, 11 of
  12 next attempts were refused with the shared code `recovery_unavailable` and the log could
  not say why. No run content is logged.
- The scorecard's "Later attempts, by outcome" shows how those attempts ended.

## Validation

- `test_the_server_runs_the_next_attempt_after_the_response_has_ended`: over real HTTP, a run
  fails, the response ends with that failure, and the server then prepares and completes the
  second attempt with no further request.
- `test_the_server_starts_nothing_when_the_setting_is_off`.
- Route, continuation, ledger and answer-check test files: 234 passed before the two tests
  above were moved to their own file; that file: 2 passed.
- The V2 client type-checks.

## Not verified

- **The page was not run in a browser.** That it picks up and shows the server's next attempt
  is unverified. The work itself does not depend on it.
- Not measured against a live model.
- If the application process stops while a next attempt is running, that attempt is left to
  the existing expiry handling, as any run is.
