# Source-authorized workflow result readers

Implemented in version: **0.261.107**, recorded in
`application/single_app/config.py`.

Workflow authoring/runtime integration was added in **0.261.108**.

## Purpose and dependencies

This incremental foundation extends the existing `workflow-result-v1` store.
Tasks can select a named final output without receiving a display summary or
diagnostic notes in its place. Contributing sources remain attached to derived
results so that losing access to a source also prevents later result reuse.

It uses `functions_workflow_results.py`, `functions_analysis_access.py`, the
existing source resolver, and `functions_workflow_result_store.py`. No new
database container or execution engine is required.

## Authorized input interface

`load_workflow_task_input(workflow, run_id, task_id, reference, *,
output_name="authoritative", allow_partial=False, reader_user_id=None,
load_result=..., source_resolver=None)` returns `(prompt, receipt)`.

The workflow, run, task, and reference must come from an authorized server-side
lookup. The reader additionally verifies producer identity, immutable section
identity, and current access to every direct or transitively consumed source.
`reader_user_id` identifies the actual reader when it differs from the workflow
owner.

`output_name` may select `authoritative`, `text`, `records`, `json`, or
`documents`. Only an existing named final section is readable as task input.
Presentation, evidence-only sections, diagnostics, and unknown names cannot
be bound as final output.

The receipt records the producer, output name, manifest reference, and exact
output reference. Consumers must retain it on their resulting manifest.

Workflow task-result HTTP reads, run history, and activity now use this source
authorization boundary. `authorize_workflow_run_read` checks all stored task
references without applying a UI history-page limit. Generic
`workflow_validation` requirements are enforced independently of the producer's
Analyze validation; neither an invalid requirement report nor a pending producer
can be bypassed by requesting partial output.

## Partial and invalid results

By default, partial results are not eligible as complete downstream input.
`allow_partial=True` permits accepted findings from a completed result marked
partial and retains its coverage and limitations.

Pending, invalid, failed, or canceled results remain blocked regardless of
`allow_partial`. This permission does not authorize publication, imply complete
source coverage, or claim independent factual validation. Ordinary legacy
results retain their explicit unvalidated status.

## Contributor metadata

Use `build_analysis_access(sources=(), *, inherited=())` to normalize trusted,
already resolved contributors and merge existing source-access policies.

Source fields are `document_id`, `scope` (or `scope_type`), `scope_id`,
`source_version`, and optional `source_revision` and `content_sha256`.
The returned policy is
`{"version": "analysis-source-access-v1", "sources": [...]}`, or `None`
when there are no contributors.

Attach the policy as `execution_result["analysis_access"]` before building the
workflow task result. This also applies to a raw-model task that consumes
shared reference documents without running Analyze.

The builder normalizes metadata; it does not authorize a read. Reference
loaders must still check current source permissions and validate any reused
content snapshot. A retained content hash is not proof that current content
was fetched or verified.

## Storage and large outputs

Existing workflow reference shapes and namespaces remain compatible. The
same store also supports genuine chat and orchestration identities; those
adapters must prove their owning context rather than fabricate workflow IDs.

Modern record/evidence collections can use immutable complete-record pages.
`read_result_records` and `iter_result_records` reconstruct those pages with
identity and integrity checks. Byte-range transport remains distinct from
semantic record pages.

Whole-result materialization is bounded and fails explicitly if the result
needs batching. This first foundation does not include automatic model-facing
report batching or a general workflow binding/execution engine.

## Validation and integration boundary

The foundation's functional coverage includes named sections and receipts,
explicit partial eligibility, pending/invalid rejection, current contributor
access, record-page reconstruction, and Blob/Cosmos identity and integrity.
Tests use the real result implementations with isolated SDK doubles.

The broader Analyze UI, native-engine adapters, and live work-unit retry
integration are separate changes. An authenticated live deployment was not
configured for this foundation; no live deployment or latency claim is made.
