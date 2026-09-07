# Tabular Transformation Contract

Implemented in version: **0.250.174**

Production planning and semantic validation updated in version: **0.250.179**

## Overview

The tabular transformation contract adds a versioned, server-owned specification for row-local generated outputs. When a tabular Search or Analyze request includes a supported deterministic transformation specification, SimpleChat can compute those public fields on the server instead of asking the model to reproduce rule-based values.

Analyze still uses the deliverable contract introduced by the artifact-output roadmap. The transformation contract is an additive child contract used by generated tabular artifacts when exact row rules are representable without arbitrary code.

## Dependencies

- `application/single_app/functions_analysis_deliverables.py`
- `application/single_app/functions_tabular_transformations.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_tabular_orchestration.py`

## Technical Specifications

The contract version is `tabular-transform-v1`. It is persisted inside the analysis deliverable contract as `transformation_spec` and normalized before a durable generated-output run is stored.

Initial supported operations are deliberately bounded:

- source field copy
- literal values
- ordered `case` branches
- equality and ordered comparisons
- ISO date comparisons
- numeric arithmetic with bounded `Decimal` values
- null coalescing
- boolean `all`, `any`, and `not`
- membership checks
- references to previously derived deterministic fields

Unsupported operations fail during planning or normalization. The evaluator does not use `eval`, `exec`, dynamic imports, reflection, filesystem access, network access, database access, process access, or environment access.

## Execution Behavior

For deterministic-only structured exports, the durable runner checkpoints generated rows directly from the evaluator and does not call the model for row generation. For hybrid runs, deterministic fields are removed from the model-owned output schema, the model generates only remaining semantic fields, and the server merges deterministic values back into the full checkpoint schema.

Combined Analyze plus structured-output runs still use the model for analysis summaries. Deterministic structured fields are computed by the same server evaluator before publication.

## Production Planning And Review

Generated-output plan version 2 asks the existing bounded planner for exact
field order and a `tabular-transform-v1` graph. Planner output is treated as
untrusted data and normalized through the same source-field, dependency,
cycle, depth, branch, list, string, and numeric limits used by direct
server-supplied contracts.

A separate model invocation reviews the normalized plan before persistence.
It must account for every requested field in order and reject missing rules,
changed precedence or boundaries, unknown source fields, unsupported rules,
unrequested inference, invalid deterministic ownership, and semantic fields
that could be represented as direct copies or deterministic rules. Active
planning or review failure stops required output instead of falling back to
unchecked row generation.

Version 1 generation plans remain readable and resumable. They are not
upgraded or reinterpreted as version 2 contracts.

## Semantic Verification And Repair

Semantic and hybrid fields are verified independently after deterministic
fields are merged and before canonical output checkpoints are written. The
verifier returns an exact field-level contract with status, a bounded reason
code, and source evidence field names. It does not return hidden reasoning.

Active mode repairs only failed or uncertain row-field pairs, enforces field
types, nullability, and allowed values, and re-verifies each repaired candidate.
Repeated responses, unsupported required fields, row-budget overflow, or
attempt exhaustion fail the batch closed. Shadow mode records safe aggregate
counts without changing output.

Repair values are bounded by type, finite numeric range, string length,
collection size, serialized collection size, nullability, and allowed values.
Candidates are checkpointed under the run, batch, and immutable plan hash
before verification and after each repair attempt so restarts do not regenerate
already-successful fields.

## Validation

Functional coverage is in `functional_tests/test_tabular_transformations_phase4.py`.

The test verifies:

- all 200 financial-review fixture rows match the independent oracle
- unsafe operations, reserved fields, cycles, and unknown source fields are rejected
- deliverable contracts persist and round-trip `transformation_spec`
- deterministic-only specs produce no model-owned public fields

## Limitations

The production planner can now produce the bounded transformation graph from user instructions after source schema staging. Arbitrary executable code, unsupported expression operations, subjective deterministic claims, and unreviewed active plans remain prohibited. Semantic model verification is evidence-based but is not represented as deterministic proof.
