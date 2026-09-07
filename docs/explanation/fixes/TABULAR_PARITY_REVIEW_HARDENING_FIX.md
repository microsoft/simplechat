# Tabular Parity Review Hardening Fix (0.250.167)

Fixed in version: **0.250.167**

Related version update: `application/single_app/config.py` reports `0.250.167`.

## Issue Description

The aggregate Tabular Analyze/Search parity review found that canary assignment was recorded but not enforced, source versions were absent from planner fingerprints, and some failed or canceled durable outputs could be summarized as completed evidence. Two backend controls also implied multi-file durable execution and automatic deferred composition even though those lifecycle implementations were not present.

## Root Cause

The shared executor did not check the planner rollout assignment before invoking its durable callback. Planner source coverage omitted the authorized source version used by idempotency fingerprints. Mixed-source and per-document aggregation handled pending work but did not preserve every terminal unsuccessful state. The direct queue helper also used a Search telemetry mode for calls delegated by Analyze.

Multi-file fan-out requires grouped run persistence, partial-queue rollback, and aggregate status handling. Automatic deferred composition requires restart-safe continuation registration, authorization and source-version revalidation, terminal-run coordination, idempotent model synthesis, and duplicate-publication protection. Those primitives do not yet exist in the durable runner.

## Technical Details

- Enforced `rollout_assignment.assigned` before durable callback invocation.
- Added authorized source versions to request and execution-unit fingerprints.
- Preserved failed and canceled durable outputs as terminal incomplete evidence.
- Preserved an all-canceled per-document cohort as canceled at the aggregate level.
- Derived direct preflight telemetry mode from planner metadata.
- Renamed the incomplete controls to `enable_tabular_multifile_execution_unit_planning` and `enable_tabular_mixed_deferred_composition_planning`.
- Marked multi-file durable fan-out and automatic deferred continuation as unavailable while retaining planning metadata and all working single-source and per-document paths.

## Validation

Focused functional coverage validates planner rollout exclusion, source-version fingerprint changes, planning-only metadata sanitization, failed and canceled mixed-source evidence, all-canceled per-document aggregation, and route-neutral telemetry. The full tabular scale suite validates source authorization, source-version publication checks, cancellation, retry, idempotent publication, and 100,000-row execution contracts.

References: PR #1219, #1031, #1055, #1058.
