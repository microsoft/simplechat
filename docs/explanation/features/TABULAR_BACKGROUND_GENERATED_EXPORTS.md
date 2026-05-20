# Tabular Background Generated Exports

Implemented in version: **0.241.046**

Updated through version: **0.241.064**

## Overview

Large tabular generated outputs can now continue outside the chat request when the export is too large to complete safely inline. This keeps chat and workflow requests responsive while a background worker processes structured JSON or CSV output in checkpointed batches.

## Purpose

The feature supports large spreadsheet-driven analysis, including workbooks that reference many supporting documents, by queueing durable generated-output runs when row and batch counts exceed inline thresholds.

## Dependencies

- Azure Cosmos DB container: `tabular_export_runs`, partitioned by `/user_id`
- Azure Blob Storage personal chat artifacts container
- Azure OpenAI or APIM-backed GPT chat completion settings
- Background task scheduler in `background_tasks.py`

## Technical Specifications

### Architecture

- Chat and workflow tabular generated-output requests continue to use the existing inline path for smaller exports.
- Oversized structured exports are queued with `queue_tabular_generated_output_run(...)`.
- Input row batches are staged as a single blob-backed JSON payload.
- Each completed model batch is checkpointed as an output blob.
- Cosmos stores compact run metadata, progress counts, retry state, and final artifact metadata.
- The background scheduler claims queued runs with optimistic status updates and resumes from checkpointed output batches.
- Users can manually continue resumable failed or stale runs from the existing checkpoints without restarting completed batches.
- Queued retry runs whose retry time has already passed are surfaced as resumable so deployments without active scheduler loops still give users a recovery action.
- Run status includes safe user-facing status detail, checkpoint summaries, retry timing, heartbeat state, and continuation availability.

### API Endpoints

- `GET /api/tabular/generated-output/runs/<run_id>` returns the current user's public-safe run status.
- `POST /api/tabular/generated-output/runs/<run_id>/resume` requeues a resumable run for the current user.

### Configuration Options

- `tabular_generated_output_inline_max_rows`
- `tabular_generated_output_inline_max_batches`
- `tabular_generated_output_max_batch_rows`
- `tabular_generated_output_max_batch_chars`
- `tabular_generated_output_batch_concurrency`

If settings are absent, conservative defaults are used.

### File Structure

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/background_tasks.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/static/js/chat/chat-messages.js`

## Usage Instructions

Users continue requesting tabular structured output in chat or workflows. For smaller exports, the file is attached during the response. For larger exports, the assistant message shows a background progress card and the final download appears when processing completes. If a resumable run stops after a transient infrastructure failure, the card shows a Continue action that queues the same run to resume from completed checkpoints.

When a workflow/document analysis request also creates a full generated tabular export, the generated export is presented as the primary deliverable. The analysis layer may still attach a supporting CSV preview, but redundant analysis JSON and Markdown artifacts are suppressed so they do not compete with the full generated export card.

The progress card displays current status, completed checkpoint counts, processed row counts, estimated remaining time, scheduled retry time, retry-due state, transient retry count, manual continuation count, last update time, and heartbeat time when available.

## Testing and Validation

- Functional regression: `functional_tests/test_tabular_background_generated_exports.py`
- Functional regression for workflow/document-action presentation: `functional_tests/test_document_analysis_lossless_artifacts.py`
- UI regression: `ui_tests/test_chat_background_generated_export_status.py`
- Compile validation covers the modified Python modules.

## Performance Considerations

- The request only stages durable input and queues work for oversized exports.
- Phase 3 batch packing compacts generated-export prompt payloads, removes internal tabular helper fields from staged model input, avoids duplicating row-linked document excerpts as synthetic attachment text, and packs rows by configurable row and character budgets.
- Phase 4 bounded concurrency lets the background worker generate a small configurable window of model batches in parallel while checkpointing successful batches and advancing public progress only in contiguous batch order.
- Background processing writes each completed batch before moving on, allowing the run to resume after worker restarts.
- The run status API returns compact metadata only, not source rows or generated batch content.
- User-facing status details are derived from run metadata instead of displaying raw backend errors in the progress card.

## Known Limitations

- Background runs still depend on configured background scheduler capacity and available Azure OpenAI throughput.
- Completion appears through status polling or on the next chat reload; no push notification is added in this version.
- Manual continuation applies to retryable failures, stale running leases, queued retries whose retry time has passed, and stale queued runs; hard validation failures remain terminal.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.057** for queued retry recovery and scheduler scan diagnostics.
- `application/single_app/config.py` was updated to version **0.241.059** for Phase 3 compact batch packing.
- `application/single_app/config.py` was updated to version **0.241.060** for Phase 4 bounded batch concurrency.
- `application/single_app/config.py` was updated to version **0.241.064** for generated export artifact presentation cleanup.
