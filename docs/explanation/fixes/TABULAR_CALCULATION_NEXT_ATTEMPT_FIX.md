# Tabular Calculation Next Attempt Fix

Fixed in version: **0.261.478**

## Issue

In the 0.261.477 run of the 28 scenarios (22 November 2026), 51 of 62 prompts completed. Seven
of the 8 partial prompts were tabular calculations. What ended them:

| What ended the calculation | Times | Reported as |
|---|---|---|
| The model call failed (`model_failed`) | 4 | `result_invalid` |
| A finished result was refused when retained (`result_schema_invalid`) | 3 | `result_invalid` |
| The authoring calls ran out, attempt after attempt, on findings already given | 2 prompts | `calculation_program_invalid`, `result_invalid` |
| An allocation's event key was invalid (`relational_key_invalid`) | 1 | `calculation_program_invalid` |

## Root causes

1. **A cut-off reply was never asked again.** The authoring loop has a branch for a reply that
   ends before the program is complete: it spends the call and asks again. The branch tested
   `exc.rule`. The harness error keeps its rule in `validation_rule` and has no `rule`
   attribute, so the test was never true and the step failed on the first such reply. The
   existing test of that branch used a stand-in error, not the harness's own.

   The four `model_failed` runs each made no "returned to its author" record and no "request
   failed" warning, and took about as long as one long model call. That fits a reply that was
   cut off or empty. It is not proven: until this version a `model_failed` did not say which
   kind it was.

2. **An output field that does not declare `nullable` could hold an empty value the result
   contract refused.** The evaluator stops an empty value only for a field that declares
   `nullable: false`. The result column was declared non-nullable whenever `nullable` was
   absent. So a program whose output field came back empty for some row (an unmatched row of a
   left join, for example) evaluated without a finding and was then refused when the result was
   retained. Its author was told nothing, and the step had already used its calls.
   Reproduced offline.

3. **A next attempt started from nothing.** Each attempt is a new run with its own checkpoint
   partition, so the new attempt's first call saw neither the last program nor what it had been
   told. Authors repeated the same faults across attempts (`relational_column_missing` was
   returned 12 times in the run, `relational_spec_invalid` 24 times).

4. **An invalid key cell was not returned.** A key column whose cell is empty or is not text
   or a number (`event_key`, `detail_key`, `cumulative_partition`) ended the run. The author
   named that column, and the finding says which role and which row.

## Change

### The loop reads the rule the error carries (`functions_orchestration_native_results.py`)

- `_failure_rule` reads `rule` or `validation_rule`.
- A reply with no whole program (`generation_incomplete`: cut off; `reply_empty`: no choice or
  no text) spends the call and the author is asked again while calls remain. It is recorded as
  "returned to its author" with check `complete_generation` or `reply_empty`.
- A finding the author already holds is kept across such a reply. Before, it was replaced, so
  the next call lost the last program and what was wrong with it. The author is told that the
  reply in between held no program.
- A refused reply (`reply_refused`) and a request the provider failed (`request_failed`) are
  not asked again.
- The failure record gains `execution_rule`.

### Every `model_failed` names what came back (`functions_orchestration_execution.py`)

`request_failed`, `reply_empty`, `reply_refused`, alongside the existing
`generation_incomplete` and `incomplete_completion`. Closed values only; no model or provider
text.

### The result column says what the records hold (`functions_tabular_relational.py`)

An output field that declares `nullable` keeps its declaration. One that does not is nullable
exactly when a record holds an empty value for it. A field that declares `nullable: false`
and evaluates to empty is still stopped by the evaluator and returned to the author.

### A next attempt is given the last program and its finding

- `CheckpointStore` takes `prior_run_id` (the run this one retries), set by
  `checkpoint_store` from `retry_of_run_id`.
- `load_prior_attempt_lowering(step_id)` reads the previous attempt's saved authoring state for
  the same step. It returns the program and the finding only when the record belongs to the
  same user, conversation and turn, is valid saved state, and ended on a finding with a
  confirmed program. Anything else returns nothing.
- When an attempt starts with no saved state of its own, the first authoring call is given
  that program as rejected, with its finding, and is told both are from the previous attempt.
  It uses none of this attempt's calls.
- The carried program is model input only. It is never run, never saved as this run's state,
  and passes the same check as a correction read back from saved state.
- A failure to read it is not a failure of the attempt: the attempt starts as before.
- Logged as "Calculation program carried from the previous attempt" with the category and
  check, no content.

### An invalid key cell is returned

`relational_key_invalid` for `event_key`, `detail_key` and `cumulative_partition` is returned
to the author. Because it is returned, an attempt that ends on it may have a next attempt.

## Diagnostics for the causes this version does not fix

Logging only. Closed codes and counts, no content.

| Cause | What the existing log already says | Added in 0.261.478 |
|---|---|---|
| Completeness check unavailable | The check's input exceeds the model's input budget (`WorkflowContextBudgetError`) | `input_tokens`, `input_budget_tokens`, `context_window_tokens`, `max_input_tokens`, `max_output_tokens`, `output_reserve_tokens`, `limit_source`, `limit_status` on "Task completeness verification unavailable" |
| Action step stopped | The stage and error type; for a refused read, its code and rule | `failure_rule` on "Direct action execution failed" and on the read checkpoint: `read_document_unselected`, `read_document_missing`, `search_document_unselected`, `function_not_document_reader`, `action_changed`, `document_binding_unavailable`, `document_binding_ambiguous`, `action_function_raised`. "Action function failed" now carries the run and the call index |
| `context_unavailable` after a wait | The reason and the call site (`external_identity_session_unavailable`) | Nothing needed |
| Planning refusal | The validation code and rule on each try | Nothing needed |
| Direct-chat tabular selection refused | The exception type | `error_code`, `operation` (the plugin function) and `choice_count` on "Tabular operation could not complete" |
| Document analysis with stated gaps | Nothing for a complete analysis | "A complete document analysis stated gaps": the count, and the count per scope |

## What this does not do

- It does not raise the completion budget. If replies are cut off because the program does not
  fit the output budget, asking again will fail the same way, and the attempt ends as
  `generation_incomplete`, which has no next attempt. The new `execution_rule` will show
  whether that is what happens.
- The carried finding is the previous attempt's. If a source changed between attempts, the
  column names in it can be stale. The prompt always holds the current headers, and the
  program is authored and checked again.
- Only the last program is carried, not the earlier ones of that attempt.
- A next attempt after `result_invalid` on an evaluation finding (an empty date cell, a
  comparison of mismatched types) is unchanged; what changes is what its first call is given.
- `completeness_unavailable`, the action-step failures, `context_unavailable` after waiting
  and the planning refusals from the same run are not touched.

## Files modified

- `application/single_app/functions_orchestration_native_results.py`
- `application/single_app/functions_orchestration_execution.py`
- `application/single_app/functions_orchestration_checkpoints.py`
- `application/single_app/functions_orchestration_recovery.py`
- `application/single_app/functions_tabular_relational.py`
- `application/single_app/config.py`
- `functional_tests/test_orchestration_relational_results.py`
- `functional_tests/test_orchestration_harness_execution.py`
- `functional_tests/test_tabular_relational_calculations.py`
- `application/single_app/functions_task_completeness.py`
- `application/single_app/functions_orchestration_actions.py`
- `application/single_app/functions_orchestration_adapters.py`
- `application/single_app/functions_orchestration_analysis_results.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `functional_tests/cosmos_response_boundaries.json`
- `functional_tests/test_orchestration_document_action_binding.py`
- `functional_tests/test_task_completeness_engine.py`
- `functional_tests/test_orchestration_server_continuation.py`

## Validation

- `test_prepared_relational_owner_uses_complete_input_and_checkpoints_program`, six new cases:
  - `prior_attempt`: the first call holds the previous attempt's program and finding and
    completes in one call.
  - `prior_attempt_other_turn`, `prior_attempt_completed`: a record of another turn, or one
    that did not end on a finding, carries nothing.
  - `reply_cut_off_after_finding`: a finding, then a cut-off reply, then a third call that
    still holds the finding and its program.
  - `reply_empty_exhausted`: three empty replies use three calls and end as
    `generation_incomplete`.
  - `reply_refused`: one call, not asked again, logged with its rule.
- `test_required_complete_generation_accepts_only_provider_stop` now asserts that the owner
  reads the rule from the harness's own error class.
- `test_a_model_failure_names_what_came_back`: the four other ways a call returns nothing.
- `test_result_columns_say_whether_an_output_field_holds_an_empty_value`: the empty output
  value that was refused is now retained, and a declared `nullable: false` still stops.
- `test_program_correction_never_repairs_genuine_interval_or_numeric_faults`: the three key
  checks are returned and make the attempt revisable; the same code without a check is not.

- Logging: `test_a_check_whose_input_does_not_fit_logs_the_budget_numbers`,
  `test_unselected_documents_are_rejected_before_source_io` (the rule),
  `test_a_refused_table_selection_logs_its_rule_and_operation`,
  `test_a_complete_analysis_logs_how_many_gaps_it_stated`.

Before: a cut-off reply ended the step on its first occurrence; an empty output value ended
it after evaluation with no finding; a next attempt started with nothing.
After: both are handled inside the loop, and a next attempt starts from the last program and
what was wrong with it.

Not run against the deployed application.
