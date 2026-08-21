# Mixed-Source Manifest and Evidence Contracts

Implemented in version: **0.250.062**

GitHub issue: [#1056](https://github.com/microsoft/simplechat/issues/1056)

Parent initiative: [#1055](https://github.com/microsoft/simplechat/issues/1055)

## Overview

SimpleChat now has a shared, authorization-safe contract for describing mixed document selections before any processing engine is selected. The ordered manifest classifies each authorized source as tabular, narrative, or unsupported, while sources that cannot be resolved or authorized receive the same scrubbed unresolved shape.

This is Phase 1 of the mixed-source orchestration initiative. It establishes internal contracts and diagnostics without changing Chat, Search, Analyze, Compare, conversation follow-up, or rollout behavior.

## Purpose

The manifest removes the need for later orchestration phases to repeatedly resolve the same document IDs into incompatible shapes. Its pure partition helper also preserves valid tabular and narrative cohorts when another selected source is unsupported or unresolved.

The bounded evidence envelope gives later native engines one JSON-safe result shape without placing exhaustive rows or unbounded content into synthesis context.

## Dependencies

- Existing personal document ownership checks in `functions_documents.get_document_record(...)`
- Existing group membership checks used by `functions_search_service.resolve_document_context(...)`
- Existing public workspace visibility checks in `functions_public_workspaces.py`
- Personal conversation ownership checks for chat-upload message resolution
- Structured telemetry through `functions_appinsights.log_event(...)`

No new authorization model, tabular runner, export subsystem, route, database container, or persisted migration is introduced.

## Technical Specifications

### Architecture

`functions_mixed_source_orchestration.py` provides four internal contracts:

- `resolve_authorized_source_manifest(...)` resolves each unique requested document ID once, preserves first-occurrence order, and ignores caller-supplied scope or identity metadata.
- `partition_source_manifest(...)` returns independent tabular, narrative, unsupported, and unresolved cohorts while preserving order inside each cohort.
- `normalize_selection_mode(...)` validates `selected`, `all`, `history`, and `relevance` modes for later phases.
- `build_evidence_envelope(...)` and `serialize_evidence_envelope(...)` validate engine/status values and enforce deterministic item, string, collection, and serialized-size limits.

Authorized manifest entries include normalized document identity, display/file names, extension, source kind, canonical scope and scope ID, applicable group/public/conversation IDs, source version when available, and authorization status.

Unresolved and unauthorized requests are deliberately indistinguishable. Their entries retain only the caller-requested document ID and return null source metadata with `source_kind` and `authorization_status` set to `unresolved`.

### Authorization Boundaries

- Personal sources are returned only when the current user owns the document or has an existing approved share.
- Group source candidates are restricted to current group memberships before document lookup.
- Public source candidates are restricted to currently visible public workspaces before document lookup.
- Chat-upload metadata is queried only after the personal conversation record is loaded and its owner matches the current user. The manifest query projects identity, filename/title, version, role, and inert artifact capability fields without loading embedded file content, extracted text, vision output, or blob data.
- Requested scope, scope IDs, owner IDs, group IDs, public workspace IDs, and conversation IDs embedded in source payloads are not accepted as authorization decisions.

Current group memberships, public workspace visibility, and chat conversation ownership are resolved once per manifest request and reused for its bounded document lookups. Authorization is still revalidated on every new manifest request.

Manifest diagnostics contain aggregate counts, scope distribution, duplicate count, error count, and resolution duration only. They do not contain document IDs, filenames, content, blob paths, credentials, or raw configuration.

### Evidence Bounds

The evidence envelope has a maximum serialized size of 65,536 bytes. Summary text, error text, collection counts, individual structured values, nesting depth, and coverage metadata are bounded independently. When limits are applied, coverage records `evidence_envelope_truncated`; exhaustive output remains the responsibility of generated artifacts or durable checkpoints.

Source manifests accept at most 100 requested entries. Over-limit requests fail before document resolution and emit count-only diagnostics; sources are never silently truncated.

### API Endpoints

No API endpoints are added or changed in Phase 1.

### Configuration Options

- `enable_mixed_source_manifest`: internal, default-off flag for producing shadow manifests in Chat and workflow requests.

The flag is intentionally not exposed in the admin UI in this phase. Disabling it restores the previous caller path with no data rollback because manifests are request-scoped and not persisted.

### File Structure

- `application/single_app/functions_mixed_source_orchestration.py`
- `application/single_app/functions_search_service.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_chats.py`
- `functional_tests/test_mixed_source_manifest_contracts.py`
- `functional_tests/test_tabular_document_actions_workflow.py`

## Usage Instructions

This phase has no user workflow or UI changes. Internal callers may enable `enable_mixed_source_manifest` to produce authorization-safe shadow manifests for selected Chat or workflow sources while legacy execution remains unchanged.

Later phases can consume the shared partition and evidence contracts instead of resolving document IDs again. They must continue to reauthorize sources at the object boundary and must not treat a persisted manifest as proof of current access.

## Testing and Validation

- Executable functional coverage: `functional_tests/test_mixed_source_manifest_contracts.py`
- Updated workflow regression: `functional_tests/test_tabular_document_actions_workflow.py`
- Coverage includes PDF plus XLSX, DOCX plus CSV in both orders, duplicate IDs, duplicate filenames across scopes, unresolved and unsupported sources among valid sources, personal/group/public/chat authorization, authorization loss, ordering, partitioning, evidence serialization/bounds, selection modes, and privacy-safe diagnostics.
- Python compilation, editor diagnostics, broken-access-control checks, XSS checks, route-policy checks, and whitespace validation are part of the Phase 1 validation gate.

## Performance Considerations

- Duplicate requested IDs are removed before resolution, preserving the first occurrence.
- Each unique requested ID is looked up once within a request-scoped authorization snapshot.
- Requests are capped at 100 source entries before authorization or document reads begin.
- Classification uses normalized metadata and does not read source content.
- Evidence bounding occurs before serialization so synthesis payloads remain predictable.

## Known Limitations

- Phase 1 does not activate document retrieval from explicit Chat selections.
- Phase 1 does not run mixed Analyze engines or synthesize their outputs.
- Phase 1 does not implement cross-format Compare.
- Phase 1 does not persist or reuse source context across follow-up turns.
- Phase 1 does not enumerate an Analyze All Documents catalog.
- Rollout and native-engine behavior changes remain scoped to #1057 through #1061.

## Related Version Updates

- `application/single_app/config.py` was updated from **0.250.061** to **0.250.062** for #1056.