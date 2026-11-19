# Orchestration progress ledger, step recoveries and automatic continuation

Version: **0.261.461**

Implemented in version: **0.261.457** (ledger and step recovery), **0.261.458** (automatic
continuation). Off by default.

This is the first and second part of Phase 3 of the
[reactive loop proposal](ORCHESTRATION_REACTIVE_LOOP_PROPOSAL.md). It is not the whole of
Phase 3: see "Not done".

Dependencies: the dependency plan executor (`functions_orchestration_executor.py`), the
capability registry, Application Insights logging.

## Overview

Before this change a required step that failed, failed the run. With the setting on, a step
that fails with a typed failure is checked against the recoveries the server defines for that
failure. If exactly one applies, it is applied and the step runs again. The run records what
happened in a progress ledger.

The approved plan is never changed. Each run is fenced to its exact plan (plan binding, step
fingerprints, checkpoints), so a recovery changes how a step is attempted, not what the plan
says. A recovery adds no capability, source or external action.

## Technical specifications

### Architecture

- `functions_orchestration_progress.py`
  - `RECOVERIES`: failure code to the recoveries defined for it. Each recovery has an
    admission policy, read from the capability registry, and an application function.
  - `ProgressLedger`: one run's entries. `recover` applies the single admitted recovery or
    returns nothing; `settle` records whether the step then completed.
- `functions_orchestration_executor.py`: after a step fails, and after the existing transient
  retry, the executor asks the ledger for a recovery and runs the step again while one applies.
- `functions_orchestration_result_runtime.py`: `resolve_step_inputs` opens an input as partial
  when the ledger accepted it for that step and producer.

### Recoveries defined

| Failure | Recovery | Admitted when | Effect |
| --- | --- | --- | --- |
| `input_partial_not_accepted` | `accept_partial_input` | The consuming capability declares `partial_inputs_supported` (today: `compose`) and the partial producer is known | The step reads the partial result. Its own result is partial and carries the producer's limitations, the same as a plan that declared the input partial |

| `completeness_incomplete`, `completeness_unavailable` | `recheck_answer` (0.261.461) | The answer itself was prepared (`preparation_status` `prepared`); only its check did not pass or could not finish | The retained answer is checked again in the same run with a new allowance of corrections, exactly as the retained check of a new attempt is. The answer is not written again |

`recheck_answer` exists because the automatic next attempt below is started by the browser
page, and on 19 November 2026 the server offered it for two such runs and the page started
neither. A recovery inside the run needs no page. See
`docs/explanation/fixes/ORCHESTRATION_PARTIAL_ANSWER_NOTICE_FIX.md`.

In the 17-18 November run the partial-input failure ended 7 of 34 failed or partial runs. Each time a
document analysis had covered every source and reported limitations, and the answer step,
planned before any result existed, had declared it would accept only a complete input.

### Automatic continuation (0.261.458)

A run that still ends failed can be followed by its next attempt without the user's sign-off.
The decision was the project owner's (18 November 2026): a change that stays inside what the
user approved continues by itself; anything else waits for the user.

The next attempt is one of the two successors the server already defined for a failed attempt,
which until now needed a click:

| Successor | What changes | Ledger code |
| --- | --- | --- |
| The same plan, run again from its failed step | Nothing in the plan. Completed steps are reused from their checkpoints | `continue_attempt` |
| The server-derived plan that answers from what was retrieved | Only the failed answer steps, which may now read partial inputs and must state the limits | `continue_available_information` |

Neither adds a capability or a source, so both are inside the approved plan by construction.
`automatic_continuation` in `functions_orchestration_progress.py` admits one only when all of
these hold:

- the setting is on and the attempt is failed, not cancelled and not stopped by the user;
- the server's recovery projection says that successor is eligible;
- no confirmation is required, and no step that would run again can act outside the plan
  (`external_effects` in the capability registry);
- the attempt number is within the recovery limit;
- the attempt did not fail the same steps for the same reasons as the attempt before it
  (a stall). History that cannot be read counts as a stall.

How it runs:

1. The run detail route adds `recovery.auto_continue` (`kind`: `retry` or
   `available_information`) when the decision is yes.
2. The V2 client, for an attempt that ended while that tab was following it, reads the
   detail and calls the existing retry route with `automatic: true`. Opening an old
   conversation never starts work.
3. The retry route makes the decision again for an `automatic` request and refuses with
   `automatic_continuation_unavailable` when it is no. A clicked retry is not held to this
   rule. The flag is removed before the shared retry preparation, so both kinds are prepared
   and fenced by the same code.
4. The new attempt runs as any retry does: new run, new binding, inherited checkpoints.

### Bounds

- Round limit: `chat_orchestration_max_recovery_rounds` (0 to 5, default 2). Zero applies none.
- Stall: the same failure on the same step and producer after a recovery ends the loop.
- More than one admitted recovery is recorded as `ambiguous` and nothing is applied. There
  is no model-chosen recovery yet.
- Cancellation and the step and run time budgets are checked before each further attempt.
- The same limit bounds automatic attempts: with the default of 2, a request has at most its
  first attempt and two that follow without asking.

### Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `enable_chat_orchestration_reactive_loop` | `false` | Apply defined recoveries to failed steps |
| `chat_orchestration_max_recovery_rounds` | `2` | Recoveries one run may apply |

Both are in Admin Settings, Chat Orchestration ("Recover From Step Failures", "Maximum Step
Recoveries"): in the classic settings page and in the settings field registry
(`admin_settings_fields.py`). The existing "Maximum Retained Runtime Hints" setting is
unchanged and does not bound recoveries.

### Telemetry

`[ORCHESTRATION_PROGRESS] Progress recorded.` with `failure_code`, `recovery`,
`progress_outcome` (`applied`, `recovered`, `not_recovered`, `stalled`, `round_limit`,
`ambiguous`), `round`, `round_limit`, `capability_id`, `producer_capability_id` and the hashed
run, conversation and step identifiers. All values are server codes.

An automatic continuation logs the same message with `stage` `automatic_continuation`,
`recovery` (`continue_attempt` or `continue_available_information`), `progress_outcome`
`applied`, and the failure code of the attempt it follows. A refused automatic request logs
the reason as `progress_outcome`.

`scripts/orchestration_scorecard.py` reports them per version under "Step recoveries", and
reports how attempts after the first ended under "Later attempts, by outcome". The completion
column counts every attempt as a run, so a failed attempt followed by a completed one shows as
one of two completed.

When a run records any entry, its saved result carries `progress_ledger`.

### File structure

- `application/single_app/functions_orchestration_progress.py` (new)
- `application/single_app/functions_orchestration_executor.py`
- `application/single_app/functions_orchestration_result_runtime.py`
- `application/single_app/functions_settings.py`, `admin_settings_fields.py`,
  `route_frontend_admin_settings.py`, `templates/admin/_panes/chat-orchestration.html`
- `scripts/orchestration_scorecard.py`
- `functional_tests/test_orchestration_progress_ledger.py` (new)
- `application/single_app/route_backend_orchestration.py` (run detail and retry routes)
- `application/v2_ui/src/lib/orchestration.ts`, `orchestrationController.ts`
- `functional_tests/test_orchestration_automatic_continuation.py` (new)

## Usage instructions

1. Admin Settings, Chat Orchestration: turn on "Recover From Step Failures".
2. Run requests as usual. A recovered step shows a progress line saying earlier work finished
   with limitations and the answer will state them.
3. Compare versions or periods with:

```
python scripts\orchestration_scorecard.py --app <app-insights-name> --resource-group <rg> --days 2
```

To measure the change, run the same scenarios with the setting off and then on.

## Testing and validation

- `functional_tests/test_orchestration_progress_ledger.py`: 8 passed.
  - Setting off: the refusal is unchanged and no ledger is recorded.
  - Setting on: the answer step completes from the partial input, the plan is byte-for-byte
    unchanged, and the result equals that of a plan which declared the input partial.
  - Round limit zero, stall detection, registry admission, bounded settings, and that no
    source text reaches the ledger or its logs.
- `functional_tests/test_orchestration_automatic_continuation.py`: 17 passed. Each condition
  above, the limit, the stall rule, the log line, the scorecard, that a click is not held to
  the rule, and that only the controller starts a continuation.
- The V2 client type-checks. Its script tests were not run: this checkout has no installed
  client packages.
- Not deployed, not run in a browser and not measured against a live model.

### Limitations and not done

- **Two recoveries.** The partial-input refusal and a failed answer check. Calculation failures
  (15 `result_invalid`, 4 `calculation_program_invalid` in the same run) are not covered here;
  the prepared calculation path has its own correction loop from Phase 1.
- **No model-written plan revision.** The automatic successors are server-defined: the same
  plan, or the one derived plan change. A plan the model rewrites after seeing a failure is
  not built. It needs a third kind of successor in the retry fences (today a successor's plan
  must equal its parent's, or the one the server derives from it), a planner call that keeps
  completed steps fixed, and a scope check on capabilities, sources and deliverables. That
  work should be tested against a live model as it is built.
- **A repeat that cannot succeed costs one attempt.** A failure whose cause is fixed in the
  plan fails the same way once more before the stall rule stops it.
- **No model-chosen recovery.** Where a failure has more than one valid recovery the choice
  belongs to a model with the results in view. None is defined yet.
- **No strict structured output and no server-derived bindings.** Both remain in Phase 3.
- **A retry of a failed run re-derives its recoveries** rather than reading the earlier
  run's ledger.
