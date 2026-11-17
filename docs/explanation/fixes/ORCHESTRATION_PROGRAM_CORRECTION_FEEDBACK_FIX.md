# Orchestration program correction feedback

Version: **0.261.452**

Fixed/Implemented in version: **0.261.452** (`application/single_app/config.py`).

This is Phase 1 of the [reactive loop proposal](../features/ORCHESTRATION_REACTIVE_LOOP_PROPOSAL.md),
applied to the prepared tabular calculation path added in 0.261.446.

## Issue description

A prepared cross-file calculation asks a model to author the relational program when the
step runs, and allows a correction when the program has an authoring fault. Three things
limited that correction:

1. The model was told only a closed category, a check name and a step index. For a missing
   column it was not told which column was missing or which columns exist.
2. One correction was allowed (two model calls in total).
3. A fault on the first authoring call could not be corrected in the same execution when
   `functions_orchestration_execution` could not be imported from inside the exception
   handler: the `ImportError` replaced the fault being handled. No test exercised a fault and
   its correction within one execution.

## Root cause

- `TabularRelationalError` keeps only closed tokens and counts so that names and values never
  reach logs. The same stripped detail was reused as the model's correction feedback, although
  that model wrote the program and already holds the prepared headers.
- `_safe_program_correction` forwarded three of the available detail fields.
- The ceiling was a literal `2` in five places in the bridge and two in checkpoint validation.
- The handler imported `HarnessExecutionError` lazily inside `except`.

## Technical details

Files modified:

- `application/single_app/functions_tabular_relational.py`
  - `TabularRelationalError` accepts `feedback`, a model-only dictionary. It is not part of
    `detail` and is not read by `native_error_diagnostics`, so it cannot reach telemetry.
  - A missing-column failure supplies `missing_columns` and `available_columns`, each capped
    at 200 names.
- `application/single_app/functions_orchestration_native_results.py`
  - A correction now carries `location` (the remaining closed detail: role, step operation,
    category, counts) and `feedback` when present. The correction prompt includes them as
    `rejection`.
  - `LOWERING_MAX_CALLS = 3`: one authoring call and up to two corrections.
  - The handler reads `HarnessExecutionError` from the already-loaded module instead of
    importing it.
- `application/single_app/functions_orchestration_checkpoints.py`
  - `LOWERING_STATE_MAX_CALLS = 3` in lowering-state validation.
- `functional_tests/test_orchestration_relational_results.py`
  - New cases: two faulty programs followed by a valid one complete with three calls and each
    correction prompt names the missing and available columns; three faulty programs stop at
    the ceiling and retain nothing; the names never appear in logged diagnostics.
- `functional_tests/cosmos_response_boundaries.json` renewed for the checkpoint module.

Unchanged by design:

- Which failures may be corrected. Only authoring faults are: a missing column, an invalid
  spec or expression, an unused source. Data faults such as an ambiguous match, an interval
  overlap or an invalid number are not rewritten, because loosening a program to make data
  pass could produce wrong totals. `test_program_correction_never_repairs_genuine_interval_or_numeric_faults`
  still holds.
- Durable call accounting, source fences and the approved question, sources and outputs.

## Not covered

- A planner-authored `relate` program (not `calculation_mode: prepared-v1`) still has no
  correction at run time.
- `action_invoke` document read failures, the largest run failure in the baseline, are
  untouched.
- Data faults still end the step; they are not yet reported to the user as findings.
- Not deployed and not measured with the scorecard.

## Validation

- `functional_tests/test_orchestration_relational_results.py`: 28 passed.
- `functional_tests/test_tabular_relational_calculations.py`: passed with the suite above
  before the new cases were added (119 passed across both files).
- Fourteen orchestration suites together (relational results, relational calculations,
  harness execution, checkpoint error mapping, dependency recovery and runtime, failure
  telemetry, crash diagnostics and the six native suites): 1,277 passed.
- Cosmos boundary inventory: 0 review gaps.
- `functional_tests/test_tabular_relational_analysis_helpers.py` cannot be collected in this
  environment (it requires a Cosmos credential).
