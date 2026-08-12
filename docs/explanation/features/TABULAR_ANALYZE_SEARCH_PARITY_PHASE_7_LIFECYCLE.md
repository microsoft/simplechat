# Tabular Analyze/Search Parity Phase 7 Lifecycle Coverage

Implemented in version: **0.250.163**

## Overview

Phase 7 starts lifecycle hardening for the shared tabular Analyze/Search parity path. It makes durable generated-output lifecycle state explicit in planner coverage, mixed-source evidence ledgers, and generated-output public metadata so pending, canceled, completed, failed, and partial evidence cannot be confused during deferred composition.

This phase reuses the existing durable tabular generated-output runner, source authorization checks, cancellation API, rollback helper, and artifact UI. It does not introduce a second runner, source resolver, or card renderer.

## Dependencies

- Shared tabular planner in `application/single_app/functions_tabular_orchestration.py`
- Mixed-source evidence ledger in `application/single_app/functions_mixed_source_orchestration.py`
- Durable tabular generated-output runner in `application/single_app/functions_tabular_generated_exports.py`
- Deferred mixed-source workflow coordination in `application/single_app/functions_workflow_runner.py`
- Current application version from `application/single_app/config.py`: **0.250.163**

## Technical Specifications

Planner source coverage now starts each replayable tabular source as planned, pending, nonterminal evidence. The coverage entry includes:

- `coverage_state`
- `execution_state`
- `evidence_status`
- `terminal`
- `required_for_composition`
- `safe_reason_code`
- `generated_reference_present`

The mixed-source coverage ledger now treats `canceled` as a first-class terminal evidence status. Canceled evidence:

- increments `canceled_source_count`
- marks aggregate coverage as partial/incomplete
- receives the safe reason `durable_work_canceled`
- remains terminal, unlike pending generated-output work
- does not count as completed or successful factual evidence

Generated-output public status metadata now includes normalized lifecycle fields for queued, retrying, running, finalizing, completed, failed, and canceled states. These fields let downstream coverage and deferred-composition code inspect `lifecycle_state`, `execution_state`, `evidence_status`, `terminal`, `required_for_composition`, and `safe_reason_code` without inferring lifecycle behavior from presentation labels.

## Rollout Controls

The lifecycle fields are additive and safe for existing generated-output records. Existing runs without newer planner or composition fields still load through the same public status builder and retain their recorded durable runner behavior.

Rollback for new parity assignment remains controlled by the existing backend gates, including:

- `tabular_request_planner_mode`
- `enable_tabular_search_shared_preflight`
- `enable_tabular_analyze_durable_preflight`
- `enable_tabular_mixed_deferred_composition`
- `enable_tabular_multifile_durable_preflight`

The lifecycle readers must remain in place while any accepted generated-output run or deferred composition descriptor can still reference them.

## Usage Instructions

Operators can use the existing generated-output status API and artifact card metadata to distinguish pending work from canceled or completed work. Canceled durable tabular work should be treated as terminal but incomplete evidence. Pending durable tabular work should continue to block collective mixed-source conclusions that require it.

## Testing and Validation

Functional coverage is in `functional_tests/test_tabular_phase7_lifecycle_coverage.py`.

The test validates:

- planner source coverage begins as planned pending nonterminal evidence
- canceled durable tabular evidence is terminal but incomplete
- canceled sources are counted separately from pending and completed sources
- all-canceled required evidence produces a canceled mode outcome instead of a generic failed outcome
- generated-output public status exposes queued, retrying, finalizing, and canceled lifecycle metadata

Adjacent regression coverage includes:

- `functional_tests/test_mixed_source_deferred_composition_phase5.py`
- `functional_tests/test_tabular_shared_request_planner.py`

## Known Limitations

This phase establishes explicit lifecycle status and coverage semantics. Broader restart recovery, terminal notification replay, and full deferred-composition continuation execution still rely on subsequent lifecycle work and existing durable worker recovery paths.
