# Partial answers: second check in the same run, and one plain sentence

Fixed in version: **0.261.461**

## Issue

Two things were reported from live conversations on 0.261.460 (19 November 2026):

1. A reply that looked complete ended with a block of server text:
   "The request was only partially completed. / The answer still needs an adjustment after
   checking. Your progress is saved. / Check the run details for saved progress and retry
   availability." The page also drew its own notice for the same run with different words, so
   the same condition was shown two ways.
2. Those runs were never followed by a second attempt, although the setting was on.

On that build 18 of 20 runs completed. Both partial runs were `compose:
completeness_incomplete`: the answer was written, the answer check asked for a change, and
the check's two corrections did not satisfy it.

## Root cause

- **The text block.** `failure_explanation` in `functions_orchestration_schema.py` builds a
  heading, every failure message and a closing line, and both reply builders append it to the
  saved message whenever a run is failed, including when the message already holds an answer.
- **No second attempt.** The automatic next attempt (0.261.458) is decided by the server and
  started by the browser page. The log added in 0.261.459 shows the server offered it for both
  runs (`automatic_continuation_offer`, `offered`) and no retry request arrived. The page only
  starts one for the conversation on screen, in a tab that is not streaming anything else;
  with several conversations running that is rarely the case. Not reproduced in a browser.

## Change

### The answer check is run again inside the run

`functions_orchestration_progress.py` gains the recovery `recheck_answer` for
`completeness_incomplete` and `completeness_unavailable`. It is admitted when the step's
answer was prepared and only the check did not pass. The executor's existing recovery loop
then runs the step again, and `adapter_compose` treats the saved check as it already treats
the retained check of a new attempt: the same answer, checked again, with a new allowance of
corrections. Nothing is written again from scratch, no new run is created, and no page is
involved.

It is bounded as every recovery is: the same failure after the recovery is a stall, and
`chat_orchestration_max_recovery_rounds` caps the rounds. It runs only when
`enable_chat_orchestration_reactive_loop` is on.

The browser-started next attempt is unchanged and still applies to other failures.

### One sentence in the reply

When a failed run's reply already holds an answer, `failure_explanation` returns one
sentence: "Part of this request could not be completed, so this answer may be incomplete."
The reasons and the retry controls stay in the run's notice on the page. A reply with no
answer, and a stopped run, keep the full explanation.

The sentence is kept, not removed, so that an export or the older chat view, which do not
draw the notice, still say the answer may be incomplete.

## Files modified

- `application/single_app/functions_orchestration_progress.py`
- `application/single_app/functions_orchestration_composition.py`
- `application/single_app/functions_orchestration_schema.py`
- `application/single_app/functions_orchestration_execution.py`
- `application/single_app/functions_orchestration_executor.py`
- `functional_tests/test_task_completeness_runtime.py`
- `functional_tests/test_orchestration_progress_ledger.py`
- `functional_tests/test_orchestration_action_chart_delivery.py`
- `application/single_app/config.py`

## Telemetry

`[ORCHESTRATION_PROGRESS] Progress recorded.` with `recovery` `recheck_answer` and
`progress_outcome` `applied`, then `recovered` or `not_recovered`. The scorecard lists them
under "Step recoveries".

## Validation

- `test_a_failed_answer_check_is_run_again_inside_the_same_run`: the run completes as its
  first attempt, and the answer is written once.
- `test_an_answer_that_still_fails_its_second_check_ends_the_run_once`: no third check.
- `test_a_prepared_answer_that_failed_its_check_is_checked_again` and
  `test_a_reply_that_holds_an_answer_carries_one_plain_sentence`.
- Not measured against a live model, and the page was not checked in a browser.

## Not done

- Whether the answer check is too strict in the two reported runs was not examined; that
  needs the saved runs.
- The page still draws its notice in addition to the sentence in the reply.
- Starting the general next attempt on the server, without the page, is not built.
