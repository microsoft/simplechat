# Analyze Artifact Phase 7B Correctness Fix

Fixed in version: **0.250.179**

Related issue: **#1233**

## Issue Description

The durable runner could preserve row count, order, schema, and lineage while
still producing values that violated explicit user rules. The deterministic
evaluator existed, but production Search and Analyze requests did not create a
transformation specification unless an internal caller injected output hints.
Semantic fields also had no independent field-level verification or targeted
repair before checkpoint publication.

## Root Cause Analysis

Generation plan version 1 owned only the row-model schema. It did not persist
deterministic or semantic field ownership, did not receive an independent plan
review, and did not update the deliverable contract with the effective public
schema and rule-validation profile. Batch validation therefore proved
structure but not requested value semantics.

## Technical Details

Files modified:

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_tabular_semantic_validation.py`
- `application/single_app/functions_tabular_transformations.py`
- `application/single_app/functions_settings.py`
- `functional_tests/test_tabular_phase7b_production_correctness.py`
- `functional_tests/test_tabular_semantic_validation_phase7b.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `functional_tests/test_tabular_transformations_phase4.py`
- `docs/explanation/features/ANALYZE_DELIVERABLE_CONTRACT.md`
- `docs/explanation/features/TABULAR_TRANSFORMATION_CONTRACT.md`
- `application/single_app/config.py`

New plan version 2 persists a normalized allowlisted transformation graph and
requires a separate review invocation before active execution. Deterministic
fields execute on the server. Semantic fields use an isolated verifier and
bounded targeted repair before canonical output checkpoints. Active planning,
review, verification, or repair exhaustion fails required output closed.

Version 2 requires explicit ownership for every field and an initialized
deliverable contract. Semantic candidates are checkpointed per batch and plan
hash before verification and after each repair attempt, allowing restart-safe
re-verification without regenerating successful fields. Repair values are
bounded by declared type, finite numeric range, nullability, allowed values,
string length, and collection size.
New active runs accepted through legacy direct preflight receive a server-owned
fallback deliverable contract, preserving compatibility while shared planner
adapters remain gated. Existing persisted runs are not reinterpreted.

Version 1 generation plans remain readable and resumable under their recorded
behavior. The new semantic settings are backend-only and default to `off`.

## Validation

- The 200-row financial-review prompt enters through the real shared Search and
  Analyze facade without injected output hints.
- Both actions persist the same nine-field deterministic contract.
- All 200 rows pass exact schema, order, cardinality, and value validation with
  zero mismatches after four durable checkpoints.
- Deterministic-only output requires no row-model-owned fields.
- Planner and reviewer use separate model invocations.
- Semantic verifier, shadow, targeted repair, re-verification, duplicate
  response, invalid repair, and exhaustion policies have executable coverage.
- The cumulative scale suite continues through 30,000-row bounded finalization
  and 100,000-row planning, authorization, cancellation, and manifest checks.

## Impact Analysis

New active generated-output runs can establish and enforce value-level rules
before publication. Existing runs are not reinterpreted. Semantic validation
remains disabled by default until the final rollout phase records canary and
live semantic evidence.
