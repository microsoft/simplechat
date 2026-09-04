# Analyze Artifact Phase 7A Stabilization Fix

Fixed in version: **0.250.178**

Related issue: **#1233**

## Issue Description

The Analyze artifact integration branch had three stabilization failures after
the first seven implementation slices:

- Word/DOCX requests that explicitly serialized authorized current-turn action
  results created a document but silently omitted the structured rows.
- The Phase 7 lifecycle test stub did not expose the ordered artifact-format
  API required by the shared planner.
- The cumulative scale harness omitted schema, transformation, and projection
  dependencies added to production helpers in later phases.

## Root Cause Analysis

The DOCX intent detector accepted both `word` and `docx`, while the guarded
passthrough serializer accepted only `docx`. The test harnesses intentionally
load narrow function slices, but their dependency inventories had not been
updated when the production functions gained public-schema, lineage,
transformation, action-mode, and artifact-set projection dependencies.

## Technical Details

Files modified:

- `application/single_app/functions_generated_file_exports.py`
- `functional_tests/test_assistant_table_csv_artifact.py`
- `functional_tests/test_tabular_phase7_lifecycle_coverage.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/ANALYZE_DELIVERABLE_CONTRACT.md`
- `application/single_app/config.py`

The serializer now treats `word` as the same explicit format-conversion alias
as `docx`. Derived-output detection still runs before serialization, tabular
plugin results remain excluded, and sensitive function-result fields continue
to be removed by the existing authorization and projection path.

The isolated lifecycle and scale harnesses now load the same ordered artifact
format, schema, lineage, transformation, stream projection, and route-neutral
task-classifier dependencies used by production.

## Validation

- DOCX/PDF function-result serialization includes authorized structured rows.
- Derived Word requests do not publish untransformed function rows.
- The complete Phase 7 lifecycle coverage suite passes.
- The cumulative scale suite passes through 100,000-row planning, 30,000-row
  bounded streaming finalization, authorization revalidation, cancellation,
  restart, lease fencing, artifact projection, and legacy migration checks.

## Impact Analysis

Users regain the documented Word export behavior for explicit action-result
serialization. No new source or authorization path is introduced, and the fix
does not activate unfinished transformation planning, semantic repair,
multi-format publication, or legacy retirement work.
