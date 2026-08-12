# Tabular Transformation Contract

Implemented in version: **0.250.174**

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

## Validation

Functional coverage is in `functional_tests/test_tabular_transformations_phase4.py`.

The test verifies:

- all 200 financial-review fixture rows match the independent oracle
- unsafe operations, reserved fields, cycles, and unknown source fields are rejected
- deliverable contracts persist and round-trip `transformation_spec`
- deterministic-only specs produce no model-owned public fields

## Limitations

The first implementation accepts transformation specifications supplied through server-side requested output hints. It does not yet infer a full transformation graph from arbitrary prompt text. Semantic field verification and targeted repair remain later Phase 4 follow-up work.
