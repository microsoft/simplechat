# Orchestration planning crash on prepared multi-file calculations

Version: **0.261.454**

Fixed/Implemented in version: **0.261.454** (`application/single_app/config.py`).

## Issue description

Planning ended with "Planning failed" and no plan for requests that calculate across more
than one tabular file. In the overnight test of Phase 2, deployed as 0.261.449 before renumbering (17 November 2026, 03:00 to 12:27
UTC) 18 of 40 planning requests ended this way:

| Crash | Count |
| --- | --- |
| `KeyError` in `validate_plan_native_source_schemas` | 17 |
| `NameError` in `_validate_tabular_composition_requirements` | 1 |

The same `KeyError` appears under 0.261.444, and is the likely cause of the earlier
unidentified crash in conversation `d38474f4`. It was found through the crash site logging
added in 0.261.451.

## Root cause

Both defects predate the reactive loop work.

1. Evidence-first calculations (`391a86f95`) made a newly planned multi-file
   `tabular_analyze` step use `calculation_mode=prepared-v1` and omit `relational_spec`: the
   program is authored at run time. `validate_plan_native_source_schemas` still read
   `arguments['relational_spec']['datasets']` for every `relate` step, so every valid plan of
   this kind raised `KeyError` after it had passed validation.
2. `_validate_tabular_composition_requirements` compares a producer with
   `CAPABILITY_DOCUMENT_SEARCH`, which the module never imported. The line runs only for a
   compose step that names a Word provenance input, so it raised `NameError` only then.

Neither was caught by tests: no test planned a prepared calculation through the header check,
and no test reached the provenance comparison with a real module import.

## Technical details

Files modified:

- `application/single_app/functions_orchestration_schema.py`
  - `validate_plan_native_source_schemas` skips a `relate` step that carries no program.
    The run checks the authored program against the real table.
  - `CAPABILITY_DOCUMENT_SEARCH` imported from the registry.
  - `step_shape_invalid` diagnostics now record the number of unknown step fields, the
    capability, and any unknown field that is one of that capability's own argument names
    (`misplaced_arguments`). Names the planner invented are counted, not recorded.
- `application/single_app/functions_orchestration_execution.py`
  - A run-level failure log now carries the exception class and application code location
    (`exception_log_fields`). The overnight `recovery_changed` failure recorded neither a rule
    nor a location and could not be traced.
- `functional_tests/test_orchestration_prepared_relate_planning_crash_fix.py` (new)
  - A prepared calculation passes the header check.
  - No orchestration module reads a name it never binds. This check would have caught the
    `NameError` and covers all `functions_orchestration*.py` files and the route.
  - The step shape diagnostics record a misplaced argument and only count an invented field.
- `application/single_app/config.py`: version 0.261.454.

## Overnight result for Phase 2 (deployed as 0.261.449)

| Measure | 9-16 Nov baseline | Overnight |
| --- | --- | --- |
| Planning requests | 181 | 40 |
| Planning crashes | not identifiable | 18 |
| Correction rounds | 64 | 8 |
| Runs with an outcome | 138 | 14 |
| Completed | 82 (59%) | 10 (71%) |

- The sample is small and the crash removed most multi-file calculation requests before they
  ran, so the completion rate is not comparable and Phase 1 (program correction) was not
  exercised.
- Rejection rules no longer seen: `unknown_argument`, `argument_schema_invalid`,
  `tabular_complete_policy_required`, `outputs_list_required`, `relational_spec_invalid`.
  The complete-tabular policy was derived by the server six times instead.
- Still seen: `step_shape_invalid` six times, always on the second step, twice needing a
  second correction although the field was named; `selected_documents_missing` twice.
- Run failures: `document_inspect: document_transform_invalid`,
  `compose: input_partial_not_accepted` (a document analysis with six limitations),
  `run: recovery_changed` after a waiting run.

## Validation

- New test file: 4 passed. With the derivation and failure telemetry files: 70 passed.
- Eleven further orchestration test files that exercise the changed functions and the run
  failure log: 317 passed, none failing that passed before.
- Not deployed. The overnight scenarios have not been rerun against this version.
