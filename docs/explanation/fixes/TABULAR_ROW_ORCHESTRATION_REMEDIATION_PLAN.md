# Tabular Row Orchestration Remediation Plan

Fixed in version: **0.250.060**

UI follow-up implemented in version: **0.250.061**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Per-row tabular analysis could produce a complete export for small files but fail once a query result was split across tool pages. The generated-output selector evaluated each page independently, rejected every partial page, and could then allow the generic assistant-table exporter to save a small summary table as though it were the requested exhaustive CSV.

The durable export runner also staged all input batches in one JSON blob and loaded every output checkpoint into one Python list during finalization. Those two operations prevented a defensible bounded-memory guarantee for 3,000- and 30,000-row exports.

## Root Cause Analysis

- Compatible `query_tabular_data` pages were ranked independently instead of being validated as ordered intervals from one query.
- Large runs could only be queued after all source rows had already been materialized by the chat request.
- Input staging used one aggregate `input_batches.json` payload.
- Final CSV/JSON assembly consolidated all output rows in memory.
- Generated batches had no authoritative source ordinal, persisted output schema, or explicit schema-drift validation.
- Background execution trusted the stored run identity without revalidating current conversation ownership and workspace access.
- The runner had a canceled status constant but no cancellation transition or user control.

## Version Implemented

Fixed in version: **0.250.060**.

`application/single_app/config.py` was updated from `0.250.059` to `0.250.060`.

## Technical Details

### Architecture

The existing durable generated-export subsystem remains the only background execution path. Issue #1031 extends it with two input modes:

1. **Direct rows** for small, complete tool results. Rows are assigned canonical source ordinals and identities before per-batch staging.
2. **Authorized source queries** for incomplete, multi-page, or threshold-large CSV queries. The request resolves an exact blob location and ETag, and the worker revalidates access before replaying the query in bounded CSV chunks.

Both modes converge on the same model batching, retry, checkpoint, progress, cancellation, and final artifact lifecycle.

### Source Contract

Every input row receives:

- `__simplechat_source_row_number`: a canonical one-based ordinal.
- `__simplechat_source_row_identity`: a stable source identifier selected from fields such as Case ID, record ID, comment ID, submission ID, or ID, with the ordinal as fallback.
- `__simplechat_source_row_token`: a deterministic opaque token that the model must echo for the matching row.

Every output row receives authoritative `source_row_number` and `source_row_identity` fields. Model-supplied values for those fields are ignored.

The echoed opaque tokens must match the exact ordered input sequence. A same-length response with swapped rows therefore fails before source identities are attached.

The first successful generated batch establishes the output schema. Later batches must contain exactly the same field set, and finalization validates schema, source ordinal continuity, and total row count before publication.

### Paginated Query Handling

Compatible tabular invocations are grouped by plugin, function, file, worksheet, query, projection, and authorized source parameters while excluding pagination controls. Their intervals are sorted and validated.

The grouping key also includes the server-resolved container, blob path, workspace scope, and ETag. Each page download is conditionally pinned to that ETag. Pages from different blob paths or versions fail explicitly instead of being coalesced.

- Contiguous pages are coalesced in source order.
- Gaps, overlaps, inconsistent totals, and declared/actual page-size mismatches remain incomplete and fail closed.
- Replayable multi-page and incomplete structured queries are queued from an authorized source descriptor instead of sending all rows through model context.

### Bounded Source Staging

Source-backed runs persist the resolved source scope, blob path, ETag, expected match count, query expression, projection, and batch limits. The descriptor is never returned in public run status.

The exact authorized blob path and ETag are captured as server-only invocation metadata on the original query result. Descriptor creation never resolves the file again by filename.

At each worker start or resume:

- Personal conversation ownership is revalidated.
- Personal, group, or public workspace access is revalidated against current authorization state.
- The source ETag is compared with the queued version.
- Foreground CSV pagination and durable replay use the same bounded query engine, numeric-column inference, row-local expression validator, projection, and hidden-reference preservation.
- The row-local expression validator parses a strict grammar of column references, comparisons, boolean operators, arithmetic, constants, and list/tuple membership. Function calls, attributes, subscripting, external variables, aggregations, and other cross-row operations are rejected before queueing.
- Each complete input batch is written to its own blob.
- The physical source row reached, staged batch count, and staged output-row count are checkpointed for resume. Resumed CSV reads use a callable skip predicate, keeping skip state constant-size instead of allocating one entry per skipped row.

A changed source, authorization loss, or result-count mismatch fails explicitly before model processing or final artifact publication.

Authorization runs immediately after claim and before legacy migration, source staging, or checkpoint reads. Manual Continue also reauthorizes before its ETag transition; revoked access returns a forbidden response without submitting work.

### Model Output Checkpoints

The runner processes bounded concurrent windows while forcing the first batch to run alone and establish the schema. Successful batches are checkpointed independently. Existing output checkpoints are reused after transient failures or worker restarts.

Malformed JSON, row-count mismatch, missing fields, unexpected fields, or schema drift fails the batch before it advances contiguous progress.

Each checkpoint also stores a compact bounded summary containing field completeness and limited scalar value counts. These summaries are merged after validation to produce the completed artifact card's compact overall analysis without putting all output rows back into model context.

### Atomic Finalization

Final CSV and JSON assembly reads one ordered checkpoint at a time into a disk-backed spooled stream.

- CSV uses `csv.DictWriter` for quoting and encoding.
- JSON is emitted as one valid ordered array.
- Every row is revalidated for schema and contiguous source ordinal.
- The expected row count must match exactly.
- The configured generated-artifact size limit is enforced before upload.
- A unique final blob is uploaded before its chat artifact message is published.

A validation or upload failure leaves no user-visible completed artifact.

### Progress, Retry, and Cancellation

Existing retry classification, scheduler recovery, leases, progress status, and manual Continue behavior are preserved. The run status now also exposes `can_cancel`.

Every worker claim increments a lease generation. Cosmos state writes are ETag-conditional, stale workers stop on holder/generation mismatch, and generated checkpoint blobs use create-only first-writer-wins semantics for current contracts.

Scheduler status scans stream runs oldest-first, evaluate the real due/stale/retryable predicate, and only then apply the configured candidate limit. Ineligible rows at the front of a status partition therefore cannot starve later recoverable runs.

Users can cancel queued, running, retryable, or failed runs from the generated-output card. Workers check the durable canceled state at source and model checkpoint boundaries and immediately before final publication. Canceled runs retain their checkpoint summary but cannot resume or attach a final artifact.

Status polling is automatic. Version **0.250.061** removed the redundant manual Refresh Status action so running cards show only Cancel; Continue appears only for runs that can genuinely resume.

Final artifact message and blob identities are deterministic per run. A retry after a partial publication reconciles the same artifact instead of creating a duplicate visible file. Cancellation closes before the fenced publication phase begins, and authorization is revalidated again immediately before upload.

Runs queued by the pre-`0.250.060` contract are migrated once: aggregate inputs become deterministic per-batch inputs, progress resets, and legacy outputs are regenerated under token/schema validation.

### Assistant-Table Fallback

A queued source-backed run returns generated tabular output metadata immediately. Because that metadata identifies a CSV export even while queued, running, failed, or canceled, the generic assistant-table exporter cannot save a partial summary table as the requested exhaustive deliverable.

All exhaustive outputs carry a format-independent `suppress_assistant_table_export` contract. Terminal failures are preserved through server and browser normalization even when queue creation never produced a run ID, so failed JSON and CSV requests remain visible and cannot fall through to a summary-table CSV.

## Files Modified

- `application/single_app/config.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/functions_tabular_csv_query.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_tabular_background_generated_exports.py`
- `functional_tests/test_tabular_large_result_pagination.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `functional_tests/test_assistant_table_csv_artifact.py`
- `ui_tests/test_chat_background_generated_export_status.py`
- `docs/explanation/release_notes.md`

## Testing Approach

Focused functional coverage validates:

- Direct 10-row source identity and stable schema behavior.
- Coalescing the 300-row `94 + 95 + 94 + 17` page sequence into ordered rows from `SC-2001` through `SC-2300`.
- Explicit gap and schema-drift rejection.
- Exact opaque-token rejection for swapped model rows.
- Mixed source-path/ETag page rejection.
- Bounded 30,000-row CSV source scanning and resume from physical row 15,000.
- Real plugin CSV pagination through the shared bounded engine without the whole-DataFrame reader.
- Bounded 30,000-row final CSV assembly across 600 checkpoints.
- Source ordinal gap rejection before publication.
- Current personal, group, public workspace, and conversation authorization at worker execution.
- Idempotent durable cancellation.
- ETag/lease-generation fencing for stale workers and deterministic legacy-run migration.
- Eligibility-before-limit scheduler coverage beyond six ineligible rows.
- Retry-idempotent final artifact publication.
- Compact post-run analysis from 600 batch summaries.
- Source-backed routing and assistant-table fallback suppression.

Existing background lifecycle, tabular pagination, assistant-table, Python compile, JavaScript syntax, and Flask route-policy tests are also run.

The authenticated Playwright cancellation workflow is included in `ui_tests/test_chat_background_generated_export_status.py`; it requires `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE`.

## Impact Analysis

### Before

- A paginated 300-row query could be rejected as incomplete even when all pages were present.
- A small assistant summary table could be saved as a misleading CSV.
- Source and final output materialization scaled with the total row count.
- Worker execution did not revalidate current source authorization.

### After

- Compatible pages are treated as one validated ordered result.
- Multi-page and large exhaustive transforms run through durable authorized source replay.
- Input and output memory are bounded by source chunks, model batches, and a disk-backed final stream.
- Completed rows survive model interruptions and worker restarts.
- The final artifact appears only after count, order, schema, source version, authorization, encoding, and size validation.
- Progress, retry, Continue, Cancel, failure details, and compact final analysis remain visible in the chat card.

## Known Limitations

- Source-backed replay currently targets CSV `query_tabular_data` runs. Complete small workbook results continue to use the direct bounded-batch path.
- Query replay supports row-wise pandas query semantics. Operations that require cross-row aggregation should continue using the dedicated aggregate tabular tools rather than per-row orchestration.
