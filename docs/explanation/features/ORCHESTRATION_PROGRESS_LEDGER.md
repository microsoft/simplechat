# Orchestration progress ledger and step recoveries

Version: **0.261.457**

Implemented in version: **0.261.457**. Off by default.

This is the first part of Phase 3 of the
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

In the 17-18 November run this failure ended 7 of 34 failed or partial runs. Each time a
document analysis had covered every source and reported limitations, and the answer step,
planned before any result existed, had declared it would accept only a complete input.

### Bounds

- Round limit: `chat_orchestration_max_recovery_rounds` (0 to 5, default 2). Zero applies none.
- Stall: the same failure on the same step and producer after a recovery ends the loop.
- More than one admitted recovery is recorded as `ambiguous` and nothing is applied. There
  is no model-chosen recovery yet.
- Cancellation and the step and run time budgets are checked before each further attempt.

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

`scripts/orchestration_scorecard.py` reports them per version under "Step recoveries".

When a run records any entry, its saved result carries `progress_ledger`.

### File structure

- `application/single_app/functions_orchestration_progress.py` (new)
- `application/single_app/functions_orchestration_executor.py`
- `application/single_app/functions_orchestration_result_runtime.py`
- `application/single_app/functions_settings.py`, `admin_settings_fields.py`,
  `route_frontend_admin_settings.py`, `templates/admin/_panes/chat-orchestration.html`
- `scripts/orchestration_scorecard.py`
- `functional_tests/test_orchestration_progress_ledger.py` (new)

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
- Not deployed and not measured against a live model.

### Limitations and not done

- **One recovery.** Only the partial-input refusal is recoverable. Calculation failures
  (15 `result_invalid`, 4 `calculation_program_invalid` in the same run) are not covered here;
  the prepared calculation path has its own correction loop from Phase 1.
- **No plan revision during a run.** Changing the plan means a new run, with new approval
  and admission checks, and is route-level work. It also needs the open decision in the
  proposal: whether a change inside the approved scope needs the user's sign-off.
- **No model-chosen recovery.** Where a failure has more than one valid recovery the choice
  belongs to a model with the results in view. None is defined yet.
- **No strict structured output and no server-derived bindings.** Both remain in Phase 3.
- **A retry of a failed run re-derives its recoveries** rather than reading the earlier
  run's ledger.
