# Analyze Deliverable Contract

Implemented in version: **0.250.171**

## Overview

The Analyze deliverable contract defines a server-owned, versioned plan for analysis artifacts before production routing changes are made. It records whether an action requires a primary Markdown analysis artifact, which sibling artifacts were explicitly requested, the public structured schema, row cardinality, ordering, transformation mode, validation profile, and publication policy.

The Phase 1 contract is additive and observation-focused. It does not switch Analyze execution behavior or repair generated values.

## Dependencies

- `application/single_app/functions_analysis_deliverables.py` for contract construction, artifact-set validation, structured-row validation, and gated shadow telemetry.
- `application/single_app/functions_tabular_orchestration.py` for attaching the contract to shared tabular planner results.
- `functional_tests/test_analyze_deliverable_contract.py` for the executable regression oracle.
- `application/single_app/config.py` version `0.250.171`.

## Technical Specifications

### Contract Fields

- `contract_version`: currently `analysis-deliverables-v1`.
- `action_mode`: normalized caller action such as `analyze` or `search`.
- `analysis_required`: true for Analyze by server policy.
- `requested_artifacts`: ordered artifact descriptors with role, format, required state, and request order.
- `primary_artifact_role`: `primary_analysis` when Analyze requires Markdown.
- `public_output_schema`: ordered public fields for a requested structured output.
- `row_cardinality` and `ordering`: row coverage expectations for structured deliverables.
- `transformation_mode`: `passthrough`, `deterministic`, `semantic`, or `hybrid`.
- `validation_profile`: artifact-only, exact row/schema, or exact row/schema/rule validation.
- `publication_policy`: whether all required artifacts must be valid before publication.
- `source_fingerprint` and `request_fingerprint`: bounded hashes used for correlation without logging row values or prompt text.

### Artifact Roles

- `primary_analysis`: the Markdown artifact required by successful Analyze actions.
- `requested_output`: a file explicitly requested by the user, such as CSV, JSON, XML, workbook, DOCX, or PDF.
- `supporting_output`: optional server-generated supporting material.

Roles are product semantics, not formats. A Search-requested Markdown file is `requested_output`; an Analyze-required Markdown file is `primary_analysis`.

### Validation

Pure validators report safe counts and reason codes for:

- missing, extra, invalid, or wrongly-role artifacts
- wrong primary artifact role
- row count, schema, and schema-order mismatches
- internal lineage fields such as `source_row_number`, `source_row_identity`, and `__simplechat_*`
- duplicate or reordered row identities when an identity field is supplied
- deterministic value mismatches when an oracle is supplied

Validation reports intentionally omit prompts, row values, storage paths, credentials, and provider errors.

## Usage

Shared tabular planning attaches a `deliverable_contract` field to planner results. When `enable_analysis_deliverable_contract_telemetry` is true and `analysis_deliverable_contract_mode` is `observe` or `shadow`, the planner emits debug-only `[ANALYSIS_DELIVERABLE_CONTRACT]` events with safe dimensions.

The default settings keep telemetry off:

```python
enable_analysis_deliverable_contract_telemetry = False
analysis_deliverable_contract_mode = "off"
```

## Testing and Validation

The committed 200-row fixture builder in `functional_tests/test_support/analyze_deliverable_contract_fixture.py` includes the exact nine requested output columns, source-order requirements, assessment-date boundaries, 30-day due-soon boundary cases, and dependencies between concern fields and `Overall_Attention`.

`functional_tests/test_analyze_deliverable_contract.py` verifies:

- Analyze requires Markdown while Search does not receive automatic Markdown.
- The requested structured contract is shared across Search and Analyze.
- JSON serialization round trips and unknown additive fields are ignored for forward compatibility.
- The source-shaped Analyze failure is rejected.
- The Search-shaped output with `source_row_number`, `source_row_identity`, and five known rule mismatches is rejected.
- Safe telemetry excludes prompt text, row values, file names, and storage paths.

## Known Limitations

Phase 1 defines and observes the contract only. Later phases make Analyze Markdown admission mandatory, separate public schema from lineage, add deterministic and semantic repair, publish atomic artifact sets, and update the plural artifact UI.
