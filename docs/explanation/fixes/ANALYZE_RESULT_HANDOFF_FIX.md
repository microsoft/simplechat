# Analyze result and presentation handoff

Fixed in version: **0.261.109**, recorded in
`application/single_app/config.py`.

## Issue and root cause

Analyze had several overlapping representations without a consistently selected
final data source. Workflow task context could contain an artifact announcement
instead of findings. CSV extraction could prefer raw window notes, while Markdown
combined the final response with those notes. A JSON-shaped response could become
escaped report text inside a Markdown file.

Repeated model-based collection could change or drop findings. A batch could
also describe other batches' inputs as missing, causing incorrect global
completeness claims. Re-analyzing the generated report improved its presentation
but did not independently recheck the original documents.

## Changes

The existing runner now has an explicit final-result path. Accepted records,
evidence, validation, presentation, and diagnostics remain distinct. Candidate
identity, duplicate replay, conflicts, and coverage are resolved before candidate
values can be used as final data.

Workflow adapters pass the declared final output through the shared durable
result store. Saved chat and orchestration results use real producer identities.
Later explanations read those saved values and retain consumed-result
provenance, rather than rebuilding data from the report.

Reports and exports use accepted values. Both chat interfaces keep the readable
answer visible and expose supporting files as secondary actions. Raw notes stay
separate from the default Markdown report.

Current source-access checks apply to result reading and derived explanation
paths. Publication requires explicit destination intent in addition to valid
output and current permissions; retry receipts prevent blind duplicate copies.

## Before and after

| Before | After |
| --- | --- |
| Artifact summaries could be passed as task data. | A persisted final-output selector identifies the data the consumer actually reads. |
| Raw notes could compete with final values in reports and CSV. | Only accepted records supply final values; diagnostic versions remain separate. |
| Record collection could involve repeated corpus rewrites. | Stable record identities and deterministic collection preserve accepted records. |
| Batch prose could imply global missing sources. | Batch and global coverage use assigned work and source outcomes. |
| Report re-analysis could imply a fresh review of originals. | Saved-result explanations retain provenance and explicitly distinguish reuse from new analysis. |

## Validation

Offline behavioral fixtures cover the real producer, shared store, fresh reload,
authorized readers, chat/workflow handoffs, and publication service. They also
cover partial findings, conflicts, duplicate replay, calculation rounding,
record pages, and revoked-source reads. Browser fixtures exercise both existing
chat interfaces and publication controls.

For the same deterministic ten-source/twenty-window fixture, the legacy path made
33 producer invocation calls and the final-result path made 20. This demonstrates
removal of collection/report model calls for that fixture, not a measured live
deployment speedup.

A live authenticated deployment was unavailable. See
[Saved Analyze results](../features/ANALYZE_RESULTS.md) for usage, implementation
boundaries, and validation limitations.
