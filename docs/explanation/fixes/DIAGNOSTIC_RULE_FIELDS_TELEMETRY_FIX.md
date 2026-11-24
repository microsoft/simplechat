# Diagnostic Rule Fields Telemetry Fix

Fixed in version: **0.261.480** (additions in 0.261.481)

## Issue

Version 0.261.478 added closed-code fields to several failure logs so that the next run would
say which check stopped a step: `failure_rule` on a stopped action, `execution_rule` and
`calculation_cause` on a failed calculation, `error_code` on a refused table selection, and
`limit_source` / `limit_status` on an unavailable completeness check.

In the 0.261.478 run none of these fields reached Application Insights. The refused table
selections (254 records) showed a choice count and no code, and the one failed action read
showed no rule.

Two further gaps showed in the same run:

- The refused selections all logged `operation` as `_sync_work`, the worker closure the
  plugin functions run their file work in, so the log did not say which function was running.
- The failed action read was a `ValueError` inside the accessibility report, logged by
  "Document inspection action failed" with the class name only.

## Root cause

`_build_logger_extra` in `functions_appinsights.py` keeps a text value only when its key is on
an allow-list; any other text is recorded as a length. The new keys were not added to
`LOGGER_WORKFLOW_CODE_KEYS`. The tests added in 0.261.478 replaced `log_event` with a recorder
and asserted the dictionary passed to it, so they never crossed that boundary.

## Change

- `functions_appinsights.py`: `failure_rule`, `execution_rule`, `error_code`,
  `calculation_cause`, `limit_source` and `limit_status` are code keys. Like every code key,
  a value is kept only when it is a lower-case snake token of at most 80 characters.
- `tabular_processing_plugin.py`: `operation` is the plugin function, taken from the caller's
  qualified name, not the worker closure.
- `document_search_plugin.py`: "Document inspection action failed" logs the class and the
  application frames that raised (`exception_log_fields`). The message is never read.

## Files modified

- `application/single_app/functions_appinsights.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/semantic_kernel_plugins/document_search_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_orchestration_failure_telemetry.py`
- `functional_tests/test_orchestration_relational_results.py`

## Validation

- `test_the_rule_and_code_fields_added_for_troubleshooting_reach_telemetry`: each field passes
  through the real `_build_logger_extra`, and free text under the same keys is dropped.
- `test_a_refused_table_selection_logs_its_rule_and_operation`: a failure raised inside a
  worker closure names the enclosing plugin function.

Before: the fields were logged and dropped; `operation` was `_sync_work`.
After: the fields are kept as closed tokens; `operation` names the function.

Not run against the deployed application.

## Added in 0.261.481

From the same run, two changes to the calculation authoring loop
(`functions_orchestration_native_results.py`):

- **A cell that is not a date in the column a cumulative sum is ordered by is returned to the
  author** (`relational_date_invalid`, check `cumulative_order`). One calculation ended on it
  with two of its three authoring calls unused. The author named that column as the date to
  order on, as it names an effective-date column, whose finding was already returned. An
  invalid cumulative value is still not returned.
- **The record of a returned finding says where it is and whether it is the same again.**
  "Calculation program returned to its author" gains the step index, operation, role and
  indices of the finding, and `correction_repeated`: true when the author held the same
  finding at the same place when it wrote this program. One run was told
  `numeric_value_is_invalid` three times; the earlier record could not say whether that was
  one place or three.

Tests: `test_program_correction_never_repairs_genuine_interval_or_numeric_faults`.
