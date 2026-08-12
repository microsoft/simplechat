# Analyze Deliverable Contract

Implemented in version: **0.250.171**

Phase 2 updated in version: **0.250.172**

Phase 3 updated in version: **0.250.173**

Phase 5 updated in version: **0.250.175**

## Overview

The Analyze deliverable contract defines a server-owned, versioned plan for analysis artifacts before production routing changes are made. It records whether an action requires a primary Markdown analysis artifact, which sibling artifacts were explicitly requested, the public structured schema, row cardinality, ordering, transformation mode, validation profile, and publication policy.

Phase 2 keeps the contract additive, but begins enforcing intent admission for shared tabular planning and bounded document Analyze finalization. Successful bounded Analyze results now publish a primary Markdown artifact. Explicit JSON, XML, or CSV requests are represented as ordered sibling artifacts, and Analyze plus structured output can no longer silently downgrade to structured-only export work when analysis is required.

Phase 3 separates public structured schemas from internal checkpoint lineage. Durable tabular checkpoints still retain source row number and identity for validation, retries, audit, and restart, but final CSV, JSON, XML, preview rows, and preview columns are projected through the persisted public schema. Raw source or function rows are no longer accepted as a derived generated-output artifact unless the request is an explicit unchanged copy, serialization, or format conversion and the rows satisfy the public schema contract.

Phase 5 adds a versioned durable artifact-set manifest for tabular generated-output runs. Combined Analyze runs can stage a requested structured sibling while hierarchical reduction continues, but public status withholds generated artifacts until every required member is validated and the set lifecycle reaches `completed`. New completed combined runs project Markdown as the primary artifact and requested structured files as ordered siblings.

## Dependencies

- `application/single_app/functions_analysis_deliverables.py` for contract construction, artifact-set validation, structured-row validation, and gated shadow telemetry.
- `application/single_app/functions_generated_file_exports.py` for ordered, negation-aware requested artifact format detection.
- `application/single_app/functions_tabular_orchestration.py` for attaching the contract to shared tabular planner results and selecting Analyze-safe execution contracts.
- `application/single_app/functions_tabular_generated_exports.py` for durable checkpoint lineage, public projection, and final artifact serialization.
- `application/single_app/functions_workflow_runner.py` for bounded Analyze Markdown artifact finalization.
- `functional_tests/test_analyze_deliverable_contract.py` for the executable regression oracle.
- `functional_tests/test_tabular_phase3_public_schema_projection.py` for public schema projection and passthrough guard coverage.
- `functional_tests/test_tabular_phase5_artifact_set_lifecycle.py` for durable artifact-set lifecycle and public projection coverage.
- `functional_tests/test_document_analysis_lossless_artifacts.py` for document-analysis artifact finalizer behavior.
- `application/single_app/config.py` version `0.250.175`.

## Technical Specifications

### Contract Fields

- `contract_version`: currently `analysis-deliverables-v3`.
- `action_mode`: normalized caller action such as `analyze` or `search`.
- `analysis_required`: true for Analyze by server policy.
- `requested_artifacts`: ordered artifact descriptors with role, format, required state, and request order.
- `primary_artifact_role`: `primary_analysis` when Analyze requires Markdown.
- `public_output_schema`: ordered public fields for a requested structured output.
- `internal_checkpoint_schema`: lineage fields followed by public fields for durable validation and resume.
- `lineage_schema`: server-owned row lineage fields such as `source_row_number` and `source_row_identity`.
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

### Public Schema Projection

Durable structured export checkpoints keep the internal schema required by the runner:

```text
source_row_number, source_row_identity, <public fields...>
```

Published artifacts and browser metadata use only `public_output_schema`:

- CSV headers and row values
- JSON object fields and order
- XML row elements and escaped text
- preview rows and preview columns
- generated artifact summaries consumed by the chat UI

Reserved fields such as `source_row_number`, `source_row_identity`, and `__simplechat_*` cannot be requested as public output fields. Legacy runs that only have `output_schema` are interpreted by filtering reserved lineage fields at publication time; old checkpoints are not rewritten.

### Passthrough Eligibility

Raw source or function rows can satisfy a generated file request only when the request is explicitly an unchanged copy, serialization, or format conversion, and any supplied public schema matches the row fields. Derived requests are refused instead of publishing source-shaped output.

Refusal reason codes include:

- `derived_output_requires_transform`
- `source_result_incomplete`
- `schema_not_satisfied`
- `no_explicit_passthrough_contract`

Allowed passthrough reason codes include:

- `explicit_unchanged_copy`
- `explicit_format_conversion`

### Validation

Pure validators report safe counts and reason codes for:

- missing, extra, invalid, or wrongly-role artifacts
- wrong primary artifact role
- row count, schema, and schema-order mismatches
- internal lineage fields such as `source_row_number`, `source_row_identity`, and `__simplechat_*`
- duplicate or reordered row identities when an identity field is supplied
- deterministic value mismatches when an oracle is supplied

Validation reports intentionally omit prompts, row values, storage paths, credentials, and provider errors.

### Artifact-Set Publication

Durable tabular generated-output runs now persist an `artifact_set_manifest` with contract version `tabular-artifact-set-v1`. The manifest records:

- set, run, conversation, user, source, and request identifiers
- ordered member descriptors with role, format, required state, request order, and idempotency key
- member lifecycle state, validation state, and staged artifact metadata
- set lifecycle state, validation state, publication generation, rollback state, and primary artifact id

Member lifecycle states include `planned`, `generating`, `staged`, `validated`, `publishing`, `published`, `failed`, `canceled`, and `rolled_back`. Set lifecycle states include `planned`, `generating`, `validating`, `ready_to_publish`, `publishing`, `completed`, `failed`, `canceled`, `rollback_required`, and `rolled_back`.

Public generated-output status treats `generated_artifacts` as the authoritative ordered projection. A member appears there only when the full set lifecycle is `completed` and the member lifecycle is `published`. For new combined Analyze runs, the primary member is the Markdown analysis artifact and requested structured outputs follow as siblings. Singular compatibility fields are derived from the same primary projection and do not expose staged or invalid members.

If a required member remains missing or unpublished, the set validation state becomes `invalid`, the lifecycle becomes `rollback_required`, and no generated artifact is projected as a completed request.

## Usage

Shared tabular planning attaches a `deliverable_contract` field to planner results. When `enable_analysis_deliverable_contract_telemetry` is true and `analysis_deliverable_contract_mode` is `observe` or `shadow`, the planner emits debug-only `[ANALYSIS_DELIVERABLE_CONTRACT]` events with safe dimensions.

The planner preserves explicit requested artifact order and direct negation. For example, Analyze with CSV plans Markdown first and CSV second. Analyze with JSON and XML preserves both requested siblings in order, but declines durable tabular execution until multi-artifact publication is available. Search can request Markdown as a normal requested output, but Search does not receive automatic primary Markdown.

When Analyze requests a structured tabular artifact, the shared planner selects `combined` only when hierarchical analysis is enabled. If the required analysis capability is disabled, the request is declined before durable execution rather than being reinterpreted as `structured_export`.

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
- Analyze plus CSV maps to Markdown plus CSV and selects `combined` when hierarchical analysis is enabled.
- Analyze plus JSON and XML preserves both requested siblings in order and fails before unsupported multi-artifact durable execution.
- Analyze plus structured output does not silently downgrade to `structured_export` when the hierarchical capability is disabled.
- Bounded document Analyze publishes Markdown, and explicit JSON is a sibling rather than a replacement.
- JSON serialization round trips and unknown additive fields are ignored for forward compatibility.
- The source-shaped Analyze failure is rejected.
- The Search-shaped output with `source_row_number`, `source_row_identity`, and five known rule mismatches is rejected.
- Safe telemetry excludes prompt text, row values, file names, and storage paths.

`functional_tests/test_tabular_phase3_public_schema_projection.py` verifies:

- Contract version `analysis-deliverables-v2` persists distinct public, internal checkpoint, and lineage schemas.
- Reserved lineage fields are rejected in public schemas.
- Durable CSV, JSON, XML, and preview metadata expose only public fields in order.
- XML output escapes projected values without leaking lineage fields.
- Generic generated-file finalizers refuse raw function rows for derived requests but allow explicit serialization.

`functional_tests/test_tabular_phase5_artifact_set_lifecycle.py` verifies:

- A staged structured sibling in a running combined Analyze set is not public.
- A completed combined set publishes Markdown first and the requested structured sibling second.
- An invalid required set fails closed with `rollback_required` and no public generated artifacts.

## Known Limitations

Phase 5 introduces manifest-backed atomic visibility for the existing durable tabular publication path. It does not yet add full cleanup sweepers for abandoned staged members, expand durable execution to every requested format, or render every plural artifact in the browser completion card; those remain later-phase work.
