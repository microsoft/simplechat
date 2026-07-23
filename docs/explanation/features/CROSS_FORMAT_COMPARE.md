# Cross-Format Compare

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