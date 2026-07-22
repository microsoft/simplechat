# Mixed-Source Analyze

Implemented in version: **0.250.066**

GitHub issue: [#1058](https://github.com/microsoft/simplechat/issues/1058)

Parent initiative: [#1055](https://github.com/microsoft/simplechat/issues/1055)

Prerequisites: [#1056](https://github.com/microsoft/simplechat/issues/1056) and [#1057](https://github.com/microsoft/simplechat/issues/1057)

## Overview

Phase 3 adds a default-off mixed-source combined Analyze coordinator for explicit document selections. It resolves one fresh authorized manifest, partitions it by native capability, and keeps the existing engines responsible for their own source types:

- Narrative documents are sent only to `run_document_analysis(...)`, preserving document windows, retries, progress, citations, and narrative artifacts.
- Tabular documents are sent one at a time to the existing tabular document-action runner, preserving tool-backed results, CSV/JSON generated outputs, background-export summary handoff, and assistant-table fallback suppression.
- One bounded Phase 1 evidence handoff is reduced once into a collective answer that distinguishes computed table facts from narrative excerpts and declares terminal coverage gaps.

No separate authorization model, manifest resolver, tabular runner, evidence contract, route, or persisted source-context mechanism was added.

## Rollout

- `enable_mixed_source_analyze`: default `false`. Enables selected combined Analyze only.
- `enable_mixed_source_analyze_all`: default `false`. Reserved for a later independently staged exhaustive Analyze All catalog implementation after preflight-limit and performance validation.

With the main flag off, the legacy execution remains available. It does not silently fall back to treating a mixed table as narrative evidence.

## Execution And Coverage

The coordinator publishes these stages through existing document-action activity plumbing:

1. Resolving sources
2. Analyzing narrative documents
3. Analyzing tabular documents
4. Combining findings
5. Complete or partial terminal coverage

Coverage is built from every fresh manifest entry. Unresolved and unsupported entries remain terminal failures in the bounded handoff without exposing their metadata. Engine/status totals are retained alongside the existing coverage fields.

If narrative or tabular execution fails, completed evidence from the other branch remains available to the one reduction. The reduction is explicitly instructed not to claim coverage for omitted, failed, unresolved, unsupported, or unprocessed sources.

Per-document Analyze remains unchanged: each document is executed separately through its native engine, and no collective reduction is added.

## Security

The coordinator uses `resolve_authorized_source_manifest(...)` for every enabled combined request. That reauthorizes personal ownership or exact approved shares, current group membership, public visibility, and chat-upload conversation ownership at the object boundary. Caller-provided scope, workspace, ownership, and selected metadata remain untrusted hints.

The existing request-scoped tabular runner continues validating authorized source context. Evidence envelopes and aggregate diagnostics are bounded, and the orchestration does not log source identifiers, names, content, locations, prompts, credentials, or raw settings.

## Validation

- `functional_tests/test_mixed_source_analyze_workflow.py`
- `functional_tests/test_tabular_document_actions_workflow.py`
- Python compilation for changed modules and tests

The focused coverage verifies native partitioning, bounded collective reduction instructions, partial failure coverage, default-off rollout behavior, per-document exclusion, and tabular artifact/citation propagation.

## Limitations

This Phase 3 increment does not enable Analyze All Documents. The current action contract exposes selected and recent targets only, so enabling an `all` mode before a dedicated exhaustive authorized catalog enumerator exists would violate the Analyze contract. The separate `enable_mixed_source_analyze_all` flag remains disabled until that enumerator, count preflight rejection, object-boundary reauthorization, and performance validation are delivered.

This phase does not implement cross-format Compare (#1059), persisted follow-up source reuse, Phase 5 conversation-selection semantics, or Phase 6 route extraction and rollout completion.