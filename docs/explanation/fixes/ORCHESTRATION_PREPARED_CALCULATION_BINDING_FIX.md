# Orchestration: multi-file calculations planned without their preparation step

Version: **0.261.456**

Fixed/Implemented in version: **0.261.456** (`application/single_app/config.py`).

## Issue description

In the test run of 17-18 November 2026 (deployed as 0.261.450, 90 requests), 10 of the 34
failed or partial runs ended at the calculation step with `native_inputs_unsupported` before
any work was done. In each failing conversation the plan had two steps: one `tabular_analyze`
calculation over 3, 7 or 8 files, then the answer.

## Root cause

Three parts of the system disagreed about what a multi-file calculation looks like.

1. The `tabular_analyze` capability description requires two steps: `native_operation=prepare`,
   then `native_operation=relate` with `calculation_mode=prepared-v1` bound to that
   preparation, with no `relational_spec`.
2. The planner prompt still described the earlier design: one `relate` step carrying a
   complete `tabular-relate-v1` `relational_spec`.
3. Planning checked only that a multi-file `relate` step declared `prepared-v1`. It did not
   check that a preparation was bound, so the mistake was first caught when the run started,
   where the planner can no longer correct it.

The defect predates the reactive loop work. It was not visible earlier because every plan of
this kind crashed in planning (see `ORCHESTRATION_PREPARED_RELATE_PLANNING_CRASH_FIX.md`).

The failing check itself is not recorded in telemetry: `native_inputs_unsupported` covers
about ten conditions. The missing preparation is inferred from the two-step plan shape and
the code.

## Technical details

Files modified:

- `application/single_app/functions_orchestration_planner.py`
  - The tabular prompt section now describes the two steps the capability requires, in the
    capability's own terms, and states that a CSV dataset names no sheet, table, range or
    header row.
- `application/single_app/functions_orchestration_schema.py`
  - `validate_generated_plan_tabular_admission` rejects a `prepared-v1` calculation unless its
    only input, named `preparation`, binds the `context` output of an enabled `tabular_analyze`
    step with `native_operation=prepare` over the same `document_ids` in the same order. Rule
    `prepared_calculation_binding_required`.
  - The rejection logs which condition failed (`binding_problem`, a closed code) and returns
    the required two-step shape to the planner. That shape is server vocabulary only.
  - `prepared_calculation_required` now returns the same shape.
- `application/single_app/functions_appinsights.py`
  - `binding_problem`, `misplaced_argument`, `recovery` and `progress_outcome` are kept as
    code tokens in telemetry. Text that is not a code token is still dropped.
- `functional_tests/test_orchestration_prepared_calculation_binding_fix.py` (new).

## Not done

- The run-time check still reports one code for all its conditions.
- Whether the planner now writes a usable `preparation_request` (exact headers in
  `context_columns` and `key_profiles`) is not known until the scenarios are rerun.

## Validation

- New test file: 14 passed. It covers the production shape, each binding the run would
  refuse, the legacy explicit program, the prompt text, and the correction message.
- Not deployed. Before and after:

| Case | Before | After |
| --- | --- | --- |
| One calculation step over several files, no preparation | Accepted; run fails at that step | Rejected in planning with the required shape |
| Prompt guidance for multi-file calculations | Write a complete relational program | Prepare, then calculate from the prepared context |
