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
- Current application version from `application/single_app/config.py`: **0.250.167**

## Technical Specifications

The shared mixed-source ledger now counts `pending` as a first-class nonterminal evidence state. Pending evidence:

- increments `pending_source_count`
- marks aggregate coverage as partial/incomplete
- receives the safe reason `pending_durable_evidence`
- blocks mixed-source reduction with `pending_required_evidence`
- is not counted as successful completed factual evidence

The mixed Analyze workflow inspects tabular generated-output metadata returned from the tabular document-action helper. Queued, running, retrying, or finalizing tabular generated-output metadata builds a pending tabular evidence envelope with `coverage.terminal = false`. The workflow then returns an interim response and a compact deferred-composition planning descriptor containing source/run identities and a manifest fingerprint. It does not include source rows, generated row payloads, credentials, raw prompts, or unsanitized errors.

Automatic continuation is not implemented. The descriptor reports `status = continuation_unavailable`, `enabled = false`, and `continuation_available = false`. Individual generated-output runs continue normally, but their completion does not invoke a later collective model synthesis.

The document-analysis artifact finalizer leaves pending deferred-composition replies intact instead of replacing them with the generic generated-output summary text.

## Rollout Controls

Phase 5 adds the backend-only planning setting:

- `enable_tabular_mixed_deferred_composition_planning`: default `False`

The setting records planning metadata only. It does not register a continuation, resume a workflow, or publish a later collective answer. Mixed Analyze always refuses to run a collective answer from incomplete tabular evidence.

The setting is included in the backend settings denylist used by `sanitize_settings_for_user(...)`, so non-admin frontend routes do not receive it.

## Usage Instructions

Operators can keep the setting disabled or enable it to inspect planning metadata while validating pending-source telemetry and generated-output handoff behavior. Enabling it does not make descriptors continuation-eligible.

Rollback for planning metadata is immediate: set `enable_tabular_mixed_deferred_composition_planning` to `False`. Existing generated-output runs continue under their recorded durable runner contract.

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

This phase creates the nonterminal evidence contract and interim handoff behavior. Terminal notification, persisted continuation execution after generated-output completion, restart recovery, and idempotent collective publication are not implemented. Per-document processing remains available independently; grouped multi-file durable execution requires separate fan-out and aggregation work.
