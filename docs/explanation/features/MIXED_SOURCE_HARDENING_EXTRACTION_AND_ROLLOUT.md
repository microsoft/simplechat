# Mixed-Source Hardening, Extraction, and Rollout

Implemented in version: **0.250.070**

GitHub issue: [#1061](https://github.com/microsoft/simplechat/issues/1061)

Parent initiative: [#1055](https://github.com/microsoft/simplechat/issues/1055)

Prerequisites: [#1056](https://github.com/microsoft/simplechat/issues/1056), [#1057](https://github.com/microsoft/simplechat/issues/1057), [#1058](https://github.com/microsoft/simplechat/issues/1058), [#1059](https://github.com/microsoft/simplechat/issues/1059), and [#1060](https://github.com/microsoft/simplechat/issues/1060)

## Overview

Phase 6 consolidates the Phase 1-5 mixed-source contracts into one manifest-aligned terminal coverage ledger and applies consistent partial-failure, cancellation, finalization, reference, and observability rules to Chat, workflow Search, Analyze, Compare, and conversation continuity.

The change does not replace the existing authorization resolver, narrative window engine, tabular runner, comparison engine, generated-output system, citation storage, ThoughtTracker, or token accounting. All mixed-source behavior flags remain independently default off.

## Architecture

### Terminal coverage ledger

`functions_mixed_source_orchestration.py` now aligns exactly one terminal entry to every fresh manifest source. Each entry preserves:

- Document ID
- Canonical scope and scope ID
- Source version
- Source kind
- Source or Target role
- Original request order
- `completed`, `partial`, `failed`, or `skipped` status
- A bounded non-sensitive reason for non-success

Evidence is filtered, deduplicated, and reordered against the fresh manifest before synthesis. Unrelated or duplicate terminal evidence fails closed, duplicate filenames remain distinct by canonical identity, unresolved source IDs are scrubbed from the model-facing handoff, and skipped or compacted evidence makes coverage partial.

### Mode failure policy

- **Chat** answers from available native evidence and carries explicit terminal omissions into synthesis.
- **Search** keeps bounded available results when one native cohort fails. Narrative retrieval failure can coexist with successful table evidence.
- **Analyze** reduces only when at least one source succeeds. Zero-success requests fail before reduction.
- **Compare** fails when the Source cannot be prepared. Failed Target preparation or pairwise reduction remains visible while later valid Targets continue.

A failed native table never falls back to generic narrative processing.

### Cancellation and finalization

One `MixedSourceCancellationError` and optional cancellation predicate now span manifest resolution, narrative window calls and reductions, tabular source calls, comparison pairs and reduction, generated export queue/upload, and final response publication.

Cancellation is checked after blocking model/tool calls so returned content is discarded when cancellation arrives in flight. Newly queued background exports use the existing cancellation API. Newly uploaded generated artifacts and citation records are rolled back by exact stored identity. No final reduction, completed progress event, citation artifact, generated output, or assistant message is published after accepted cancellation.

Every previously authorized contributing source is resolved again before standard or streaming Chat and document-action publication. Canonical scope and source version must still match. Sources that were already unresolved remain explicit partial coverage and do not become evidence.

### Bounded Analyze All

The existing `enable_mixed_source_analyze_all` subordinate flag now has a backend contract:

1. The ready document access index enumerates current candidates with a `configured limit + 1` query.
2. Any catalog above the configured Analyze limit is rejected without truncation.
3. Group memberships and public visibility are refreshed before enumeration.
4. Every candidate ID is resolved again through `resolve_authorized_source_manifest(...)` before native execution.

The flag remains default off. The workflow selector is not newly exposed in this phase; activation requires deliberate staged rollout after access-index readiness and production latency/error review.

### Bounded extraction

`get_new_plugin_invocations(...)` moved from `route_backend_chats.py` to `functions_tabular_analysis.py`. The route retains the original symbol as a compatibility shim, while the reusable implementation no longer imports the route at runtime. No second tabular runner or broad route-to-service rewrite was introduced.

## Security

- The existing authorized source manifest remains the sole source resolver and authorization model.
- Personal ownership and exact approved shares, group membership, public workspace visibility, and chat-upload conversation ownership are rechecked at execution and finalization boundaries.
- Caller scope, active settings, selected metadata, and continuity records remain untrusted hints.
- Continuity status, version, coverage, role, and order survive normalization. Partial, failed, truncated, changed, or revoked history forces fresh native work even if the history assessor would otherwise reuse an earlier answer.
- Foundry `include_document_context=false` filtering remains unchanged and continues to remove mixed-source evidence and file inputs.
- No raw settings, evidence, prompts, filenames, document IDs, blob paths, or authorization snapshots are added to frontend responses or telemetry.

## Observability

`enable_mixed_source_development_telemetry` is independent and default off. When enabled, an internal UUID correlation ID links manifest, native branches, terminal coverage, reduction, continuity decisions, cancellation phase, and background export/artifact counts.

The emitter accepts only allowlisted aggregate counts, finite latency/token metrics, and bounded categorical dimensions. Source-shaped or other non-allowlisted fields are rejected.

## Rollout And Rollback

The following flags remain independently default off:

- `enable_mixed_source_manifest`
- `enable_mixed_source_chat_search`
- `enable_mixed_source_analyze`
- `enable_cross_format_compare`
- `enable_mixed_source_conversation_continuity`

Subordinate stages also remain off:

- `enable_mixed_source_relevance_candidates`
- `enable_mixed_source_analyze_all`
- `enable_cross_format_compare_one_to_many`
- `enable_mixed_source_development_telemetry`

No mixed-source mode is made default on. Production rollout still requires error, omission, and latency evidence plus explicit approval.

## Testing And Validation

Primary behavior coverage is in `functional_tests/test_mixed_source_hardening.py`, with Phase 1-5 regression suites retained. Coverage includes manifest-aligned identity, mixed scopes and duplicate filenames, native table failure, mode-specific partial failures, failed Compare Source and Target behavior, continuity precedence, bounded Analyze All, cancellation across lifecycle phases, exact artifact rollback, finalization authorization/version loss, reference deduplication, and telemetry privacy.

The release validation also includes Python compilation, Pylance/editor diagnostics, route policy tests when route code changes, broken-access-control and XSS scans, token/artifact/progress regressions, and CRLF-aware whitespace checks.

## Known Limitations

- Many-to-many Compare and automatic Target discovery remain out of scope.
- Chat and Search catalog processing remains relevance bounded.
- Analyze All remains a staged backend capability and is not default on or newly exposed in the selector.
- Richer relational joins and persistent computed evidence caches remain future work.
- Production telemetry evidence and explicit approval are still required before enabling mixed-source behavior by default.
