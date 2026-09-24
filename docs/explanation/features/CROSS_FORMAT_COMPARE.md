# Cross-Format Compare

**Version: 0.261.127**

Implemented in version: **0.250.067**

GitHub issue: [#1059](https://github.com/microsoft/simplechat/issues/1059)

Parent initiative: [#1055](https://github.com/microsoft/simplechat/issues/1055)

Prerequisites: [#1056](https://github.com/microsoft/simplechat/issues/1056), [#1057](https://github.com/microsoft/simplechat/issues/1057), and [#1058](https://github.com/microsoft/simplechat/issues/1058)

## Overview

Phase 4 introduces a default-off cross-format Compare coordinator. It resolves one fresh authorized manifest for the Source and ordered Targets, dispatches narrative sources to document-window analysis and tabular sources to the existing tabular analysis runner, then performs the established one-Source-to-many-Targets pairwise and final reduction using bounded evidence envelopes.

## Configuration

- `enable_cross_format_compare`: default `false`; enables native mixed narrative/tabular Compare.
- `enable_cross_format_compare_one_to_many`: default `false`; permits more than one mixed-format Target after pairwise coverage and performance are verified.

When the main flag is disabled, same-type Compare stays on its established path. A mixed request fails with a clear temporary limitation rather than treating a table as narrative chunks.

## Architecture

- `functions_mixed_source_orchestration.py` remains the sole manifest, partition, authorization, and bounded-envelope contract.
- `functions_workflow_runner.py` reuses `run_document_analysis(...)` for narrative sources and `_maybe_execute_tabular_document_action(...)` for every tabular source.
- `functions_document_comparison.py` retains the existing pairwise and multi-target reduction prompts; `run_evidence_document_comparison(...)` supplies native engine-neutral evidence and keeps failed targets visible.
- Existing citation, token aggregation, ThoughtTracker, generated tabular output, background-export, and comparison artifact flows are retained.

## Security and Coverage

Every enabled execution resolves the source manifest fresh, rechecking personal ownership or exact approved shares, active group membership, public visibility, and chat-upload conversation ownership. Caller-provided scope or metadata is not authorization. Unresolved and unauthorized sources remain scrubbed terminal coverage entries.

The final comparison reports compared targets, failed or partial targets, participating engines, and whether its conclusion is aggregate/narrative. Narrative assertions remain distinct from computed tabular facts. Generated exports remain artifacts rather than comparison prose.

## Testing

`functional_tests/test_cross_format_compare_workflow.py` covers the native coordinator wiring, Source/Target ordering, partial target visibility, engine reporting, staged rollout flags, and rollback limitation. Additional scope, authorization-revocation, source-version, streaming, and UI coverage should remain part of the rollout gate before enabling either flag.

## Limitations

This phase does not add many-to-many Compare, all-document discovery, persisted follow-up source reuse, Phase 5 selection semantics, or Phase 6 broad extraction and rollout completion. Table-to-table row-level assertions require a validated structured table operation; bounded prose evidence alone is not treated as row-level proof.

## Phase 6 Hardening

Version **0.250.070** applies the [#1061](https://github.com/microsoft/simplechat/issues/1061) failure policy: an unprepared Source fails the operation, while a failed Target or pairwise Target reduction remains visible and later valid Targets continue. Mixed Compare citations and generated tabular outputs now survive the outer model and agent return paths with stable deduplication. Cancellation prevents later pairwise work, final reduction, or artifact publication.

## Retained orchestration comparisons

The internal M2 producer contract, implemented in **0.261.127** and tracked with
the application version in `application/single_app/config.py`, relates to #1509.
It is separate from the standalone and workflow Compare behavior above.

For a server-owned orchestration plan, `run_document_comparison(...,
result_version="comparison-v1")` keeps the full text of each completed pairwise
comparison. It records the baseline identity, ordered target identities,
per-source window coverage, per-target completion state, limitations, and safe
failure codes. A failed target does not discard later successful targets.
Failed source preparation or an empty provider response is not a comparison
finding, and a failure explanation cannot turn an all-failed result into
success.

The adapter persists `comparison` (`comparison-v1`) and `coverage`
(`structured-v1`) through `OrchestrationResults`. A genuine consolidated report,
when produced, is retained separately as `report` (`markdown-v1`). A reduction
failure preserves the complete pairwise items but does not substitute an
explanatory paragraph for the missing report. Any incomplete input coverage or
failed target keeps the task and its outputs partial; failed-only comparisons
remain failed and are not readable as accepted findings.

The new path creates no managed downloadable file or workspace document.
Source snapshots come from the authorized manifest, and result writes use the
owning attempt's server-issued guard. Runtime/route admission and mixed/native
compute-only integration are separate: the initial internal adapter accepts
narrative sources and rejects unsupported/native selections rather than
silently using preview rows or legacy file-producing execution.

`functional_tests/test_orchestration_internal_analysis.py` covers complete
per-target text after restart, partial and failed targets, full-report retention,
cancellation, failed result guards, and zero managed uploads. The ordinary
standalone Compare entry point retains its existing default and return shape.