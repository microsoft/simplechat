# Word Comment Request and Budget Size Telemetry Fix

Fixed in version: **0.261.483**

Three faults with a known cause, from the 0.261.482 run.

## 1. A Word comment request with a paging argument ended its step

### Issue

Two prompts in one conversation failed with `document_action_read_failed`. In each, the action's
model asked the accessibility report for the comments of a Word file and also set an argument
that pages or filters a workbook, PDF or presentation inventory: a `native_section` other than
its default, a `native_cursor`, a `sheet_name` or a `cell_range`.

### Root cause

`get_document_accessibility_payload` refused that combination with a plain `ValueError`. The
Document Search function turns any unexpected exception into `{"error": ...}`, and the action
runner ends the step on any error returned by a read of a bound document.

The neighbouring refusal, comments asked of a format that has none, was already a typed
`NativeInspectionRequestError`. The action runner checks for it before any read and returns it
to the action's model once, as a correction. The Word refusal was not part of that check.

### Change

- `native_document_evidence.py`: `validate_native_report_sections` becomes
  `validate_native_report_request` and also takes `native_section`, `native_cursor`,
  `sheet_name` and `cell_range`. A Word comment request that supplies any of them raises
  `NativeInspectionRequestError("native_word_comments_arguments_unsupported")`, which carries
  the refused argument names in `refused_arguments`. An argument that was not supplied is the
  same request as that argument's default.
- `functions_search_service.py`: `get_document_accessibility_payload` calls the shared
  validator with those arguments and no longer raises its own `ValueError`.
- `functions_orchestration_actions.py`: the check that runs before a native report read passes
  the same arguments. The correction returned to the action's model lists them under
  `unsupported_arguments`. As before, one correction is returned for the action; a second
  refused request ends the step with `document_action_read_unsupported`, and nothing is read
  for a refused request.

The request is refused, not silently narrowed, as it was before. No tool description or prompt
text was changed.

Not changed: PDF and PowerPoint inspection still refuses a worksheet filter with a plain
`ValueError` when a retained native source is inspected. That refusal depends on the stored
document, which the check before the read does not see, and it has not been observed.

## 2. The sizes of a request that did not fit were not in telemetry

### Issue

Three prompts ended on a completeness check that could not run because its input did not fit
the model's input budget (`completeness_unavailable`, `WorkflowContextBudgetError`). Version
0.261.478 added the sizes to that log. In three runs since, the log has shown that the fields
were present and never their values.

### Root cause

The sizes were logged under the audit's own names: `input_tokens`, `input_budget_tokens`,
`context_window_tokens` and so on. `_build_logger_extra` in `functions_appinsights.py` treats
any key containing `token` as a credential and logs `<key>_present` in place of the value.
`output_reservation` and `decision` were text under keys that are not on the code allow-list,
so they were recorded as a length. The test added in 0.261.478 asserted the dictionary handed
to the logger and never crossed that boundary.

### Change

- `functions_workflow_policy_errors.py`: `context_budget_log_fields(audit)` returns the audit's
  counts and closed codes under names telemetry keeps.

  | Audit field | Logged as |
  | --- | --- |
  | `input_tokens` | `input_size` |
  | `input_budget_tokens` | `input_budget` |
  | `context_window_tokens` | `context_window` |
  | `effective_context_window_tokens` | `effective_context_window` |
  | `max_input_tokens` | `max_input` |
  | `max_output_tokens` | `max_output` |
  | `output_reserve_tokens` | `output_reserve` |
  | `safety_tokens` | `safety_margin` |
  | `decision` | `budget_decision` |
  | `token_estimator` | `size_estimator` |
  | `limit_source`, `limit_status`, `output_reservation` | unchanged |

  A count is carried only when it is an integer, and a code only when it is a lowercase word.
  A limit drawn from two origins (`catalog+configured`) is logged as `catalog_and_configured`,
  because telemetry keeps a code only when it is one word.
- `functions_task_completeness.py`: the diagnostic of an unavailable check uses that helper.
- `functions_orchestration_composition.py`: an answer step whose own input does not fit
  (`result_input_too_large`) logs the same fields on "Content preparation could not complete".
  It logged none before.
- `functions_appinsights.py`: `output_reservation`, `budget_decision` and `size_estimator` are
  code keys. The filter's treatment of keys containing `token` is unchanged.

`size_estimator` is new information. When the model has no tokenizer known to the application,
the budget counts the request's UTF-8 bytes as an upper bound (`utf8_upper_bound`), which is
several times its token count for ordinary text. Whether that happened in the three failed
checks is not known; the next run will say.

## 3. A background spreadsheet export failed on start

### Issue

One background structured export failed with a `TypeError` before generating any batch.

### Root cause

`process_tabular_generated_output_run` called
`_generate_and_checkpoint_batch_window_entries(run, ..., semantic_checkpoint_run=run)`. That
function takes the run as its first argument and builds the semantic checkpoint context from it;
it has no `semantic_checkpoint_run` parameter. The keyword has been on that call since the
function's sibling gained the parameter. The branch runs only when completion-driven
checkpointing is enabled, and the existing test of the function calls it directly, so no test
made the processor's call.

### Change

- `functions_tabular_generated_exports.py`: the keyword is removed from that call. The function
  already receives the run and uses it for the checkpoint context.

Not changed: the other branch calls `_generate_batch_window_entries`, which has the
`semantic_checkpoint_run` parameter, without passing it, so that branch builds its semantic
checkpoint context from no run. That is a gap in checkpointing, not a failure, and passing the
run there would start reading and writing checkpoints in a path that has run without them.

## Files modified

- `application/single_app/native_document_evidence.py`
- `application/single_app/functions_search_service.py`
- `application/single_app/functions_orchestration_actions.py`
- `application/single_app/functions_workflow_policy_errors.py`
- `application/single_app/functions_task_completeness.py`
- `application/single_app/functions_orchestration_composition.py`
- `application/single_app/functions_appinsights.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_orchestration_document_action_binding.py`
- `functional_tests/test_document_accessibility_report_action.py`
- `functional_tests/test_task_completeness_engine.py`
- `functional_tests/test_orchestration_failure_telemetry.py`
- `functional_tests/test_module_call_signatures.py` (new)
- `functional_tests/cosmos_response_boundaries.json` (nine owners in the two changed modules
  re-reviewed; their bodies are unchanged)
- `docs/reference/logging-tags.md`

## Validation

- `test_word_comments_asked_with_a_paging_argument_are_corrected_once_before_any_read`: through
  the real action runner and Document Search function, each of the four arguments is refused
  before any read, the correction names it, and the corrected request is the only read.
- `test_a_second_refused_word_comment_request_stops_without_reading` and
  `test_an_excel_comment_request_keeps_its_paging_arguments`: the one-correction limit holds and
  a workbook request is unaffected.
- `test_word_comment_request_conflict_is_a_typed_refusal`: the service raises the typed error.
- `test_the_sizes_of_a_request_that_did_not_fit_reach_telemetry`: the audit of a real refused
  request passes through the real `_build_logger_extra`. Under its own names the sizes become
  present flags; under the new names every one is kept.
- `test_a_check_whose_input_does_not_fit_logs_the_budget_numbers`: the completeness diagnostic
  carries the new names and no key containing `token`.
- `test_module_call_signatures.py`: reads every call an application module makes to one of its
  own top-level functions and fails on an argument the function does not take. It reports the
  export call on the previous version and nothing on this one, across every application module.

Before: the Word request ended the step; the sizes were logged as present flags; the export
raised `TypeError`.
After: the Word request is corrected once; the sizes are numbers; the export call binds.

Not run against the deployed application. The export fix is verified by reading the call, not
by running a background export. The one existing test of the checkpointing generator
(`test_phase_five_completion_driven_checkpointing_commits_fast_batch_before_straggler`) fails
before and after this change: its loader lacks a helper the generator calls, and its stand-in
takes fewer arguments than the generator passes. It was not repaired here.
