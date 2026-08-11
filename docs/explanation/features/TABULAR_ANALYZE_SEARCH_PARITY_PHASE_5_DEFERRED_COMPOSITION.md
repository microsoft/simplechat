# Tabular Analyze/Search Parity Phase 5 Deferred Composition

Implemented in version: **0.250.161**

## Overview

Phase 5 starts the mixed-source deferred composition contract for Analyze. When a mixed narrative-plus-tabular Analyze request produces full-source generated-output metadata for a tabular source, the tabular source is represented as pending evidence instead of completed factual evidence. The workflow preserves completed narrative and bounded evidence, returns an interim handoff, and skips collective mixed-source reduction until required tabular work can be treated as terminal evidence.

The behavior prevents queued or running generated-output cards from being interpreted as completed analysis. It also keeps the generic generated-output card behavior unchanged, so users can still see background tabular progress through the existing artifact UI.

## Dependencies

- Mixed-source manifest and evidence contracts in `application/single_app/functions_mixed_source_orchestration.py`
- Mixed-source Analyze workflow coordination in `application/single_app/functions_workflow_runner.py`
- Existing durable tabular generated-output runner in `application/single_app/functions_tabular_generated_exports.py`
- Backend settings defaults and frontend sanitization in `application/single_app/functions_settings.py`
- Current application version from `application/single_app/config.py`: **0.250.161**

## Technical Specifications

The shared mixed-source ledger now counts `pending` as a first-class nonterminal evidence state. Pending evidence:

- increments `pending_source_count`
- marks aggregate coverage as partial/incomplete
- receives the safe reason `pending_durable_evidence`
- blocks mixed-source reduction with `pending_required_evidence`
- is not counted as successful completed factual evidence

The mixed Analyze workflow inspects tabular generated-output metadata returned from the tabular document-action helper. Queued, running, retrying, or finalizing tabular generated-output metadata builds a pending tabular evidence envelope with `coverage.terminal = false`. The workflow then returns an interim response and a compact deferred-composition descriptor containing source/run identities and a manifest fingerprint. It does not include source rows, generated row payloads, credentials, raw prompts, or unsanitized errors.

The document-analysis artifact finalizer leaves pending deferred-composition replies intact instead of replacing them with the generic generated-output summary text.

## Rollout Controls

Phase 5 adds the backend-only setting:

- `enable_tabular_mixed_deferred_composition`: default `False`

When the setting is disabled, mixed Analyze still refuses to run a collective answer from incomplete tabular evidence. The response states that deferred composition is disabled and that no collective conclusion was generated from pending table evidence.

The setting is included in the backend settings denylist used by `sanitize_settings_for_user(...)`, so non-admin frontend routes do not receive it.

## Usage Instructions

Operators can keep the setting disabled to preserve honest gate-off behavior while validating pending-source telemetry and generated-output handoff behavior. Enabling the setting marks new pending descriptors as continuation-eligible for later lifecycle processing.

Rollback for new requests is immediate: set `enable_tabular_mixed_deferred_composition` to `False`. Existing generated-output runs continue under their recorded durable runner contract.

## Testing and Validation

Functional coverage is in `functional_tests/test_mixed_source_deferred_composition_phase5.py`.

The test validates:

- pending tabular evidence blocks mixed-source Analyze reduction
- pending sources are counted separately from completed, partial, failed, and skipped sources
- pending ledger entries receive the safe nonterminal reason
- the workflow runner branches on pending generated-output metadata before reduction
- the artifact finalizer preserves pending deferred-composition replies
- the Phase 5 rollout setting defaults off and remains backend-only

## Known Limitations

This phase creates the nonterminal evidence contract and interim handoff behavior. Terminal notification, persisted continuation execution after generated-output completion, restart recovery, and broader lifecycle hardening are reserved for subsequent Phase 5 hardening and Phase 7 coverage. Per-document and multi-table Analyze remain separate Phase 6 scope.
