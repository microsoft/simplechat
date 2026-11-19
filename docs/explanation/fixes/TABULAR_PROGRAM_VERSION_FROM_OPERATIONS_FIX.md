# Calculation program rejected for its version field

Fixed in version: **0.261.460**

## Issue

On 0.261.458, five runs failed at the calculation step with `result_invalid`. The native
diagnostic was `relational_spec_invalid`, check `version_operations`: the calculation program
the model wrote at run time named one format version and used the operations of the other.

## Root cause

A prepared calculation (`calculation_mode: prepared-v1`) has its program written by the model
during the run. The program schema offers two versions, `tabular-relate-v1` and
`tabular-relate-v2`, and the normalizer requires that the second is named exactly when the
program uses `allocate` or `cumulative_sum`. The version therefore has one valid value for any
given set of operations. The author was asked to restate it, and a wrong restatement failed
an otherwise valid program.

## Change

- `functions_tabular_relational.py`: new `with_operation_version(program)`. It returns the
  program with the version its operations determine, and the version the author wrote.
- `functions_orchestration_native_results.py`: the prepared path calls it on the model's
  program before normalization. Everything else about the program is still validated as
  before.
- `normalize_relational_spec` is unchanged and still rejects a mismatch. The plan-time path,
  whose schema admits only the first format and removes the two newer operations, is not
  relaxed.
- With debug logging on, `[ORCHESTRATION_NATIVE] Calculation program version set from its
  operations.` is logged when the authored version differed (`program_version`,
  `authored_version_valid`). No program content is logged.

No prompt was changed.

## Files modified

- `application/single_app/functions_tabular_relational.py`
- `application/single_app/functions_orchestration_native_results.py`
- `functional_tests/test_tabular_relational_calculations.py`
- `functional_tests/test_orchestration_relational_results.py`
- `application/single_app/config.py`

## Validation

- `test_the_operations_determine_the_program_version`: the derivation, that the input is not
  changed in place, and that the normalizer still rejects a mismatch.
- `test_prepared_relational_owner_uses_complete_input_and_checkpoints_program[authored_version]`:
  a program naming the wrong version completes in one model call, with no correction, and the
  saved program carries the derived version.
- Not measured against a live model. Before: 5 of 35 runs on 0.261.458 failed this check.
  The other calculation failures (missing column, ambiguous join, empty numeric values) are
  different causes and are not addressed here.
