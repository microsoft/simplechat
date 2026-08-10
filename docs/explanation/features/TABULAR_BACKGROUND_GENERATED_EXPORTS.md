# Tabular Background Generated Exports

Implemented in version: **0.241.046**

Updated through version: **0.250.144**

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
- Version-pinned CSV sources are replayed into bounded per-batch input checkpoints without model pagination.
- Each completed model batch is checkpointed as an output blob.
- Cosmos stores compact run metadata, progress counts, retry state, and final artifact metadata.
- The background scheduler claims queued runs with optimistic status updates and resumes from checkpointed output batches.
- Users can manually continue resumable failed or stale runs from the existing checkpoints without restarting completed batches.
- Queued retry runs whose retry time has already passed are surfaced as resumable so deployments without active scheduler loops still give users a recovery action.
- Run status includes safe user-facing status detail, checkpoint summaries, retry timing, heartbeat state, and continuation availability.
- Phase 1 acceleration groundwork adds additive generation contract fields, legacy-off rollout gates, safe batch latency/token telemetry, and deterministic fake model/storage harnesses without changing fixed-window execution behavior.
- Phase 2 foreground handoff uses server-composed acknowledgment text for accepted background export, analysis, and combined runs, so the assistant response describes the complete queued work instead of narrating preview limitations.
- Phase 3 creates one bounded LLM schema plan after source staging, stores it as an immutable hashed blob, and binds planned output checkpoints to that plan and source ETag.
- Phase 4 adds an active-plan compact row response protocol for structured exports. The model emits one short batch-local row key plus positional LLM values, while the server reattaches source metadata and checkpoints the same object-shaped rows as before.
- Phase 5 adds opt-in completion-driven checkpointing for structured exports. Validated model results are submitted to a bounded checkpoint writer as soon as each task completes while the executor still preserves fixed window boundaries.
- Phase 6 adds an opt-in rolling worker pool that replaces completed model slots without waiting for a fixed window barrier.
- Phase 7 adds durable per-batch retry records and a delayed retry heap so one retrying batch does not pause healthy pending work.
- Phase 8 assigns new runs to deterministic rollout cohorts, records explicit planner/executor/protocol/retry modes, reclaims new-run workers after a snapshotted two-minute stale interval, and revalidates source ETags before final publication.

### API Endpoints

- `GET /api/tabular/generated-output/runs/<run_id>` returns the current user's public-safe run status.
- `POST /api/tabular/generated-output/runs/<run_id>/resume` requeues a resumable run for the current user.

### Configuration Options

- `tabular_generated_output_inline_max_rows`
- `tabular_generated_output_inline_max_batches`
- `tabular_generated_output_max_batch_rows`
- `tabular_generated_output_max_batch_chars`
- `tabular_generated_output_batch_concurrency`
- `tabular_generated_output_input_token_ratio`
- `tabular_generated_output_large_context_input_token_ratio`
- `tabular_generated_output_input_token_soft_cap`
- `tabular_generated_output_output_token_ratio`
- `tabular_generated_output_output_expansion_ratio`
- `tabular_generation_rollout_percentage`
- `tabular_background_handoff_mode`
- `enable_tabular_generation_plan`
- `tabular_generation_plan_mode`
- `enable_tabular_compact_response_protocol`
- `enable_tabular_completion_driven_checkpointing`
- `enable_tabular_rolling_worker_pool`
- `enable_tabular_independent_batch_retries`
- `tabular_generation_checkpoint_writer_concurrency`
- `tabular_generation_heartbeat_seconds`
- `tabular_generation_stale_seconds`
- `tabular_generation_systemic_failure_threshold`

If a fixed concurrency is not configured, runs use up to 4, 16, 64, or 128 concurrent model calls according to the actual staged batch count. Model-aware source batching uses selected-model metadata, local `model_capabilities.json` token-limit fields when present, and bounded fallback limits otherwise.
Phase 3 enables generation planning in output-neutral `shadow` mode for new runs. Shadow mode preserves first-batch schema discovery and records agreement metrics only. `active` mode is available as an explicit administrator rollout choice and removes the first-batch schema barrier. Rollout settings are copied into new run records, and backend-only settings are filtered from sanitized non-admin frontend settings payloads.
Phase 8 applies the configured acceleration settings only to new runs whose deterministic bucket is within `tabular_generation_rollout_percentage`. The percentage defaults to 100 to preserve existing behavior. A control run stores legacy effective modes, while a canary run stores the configured effective modes; later setting changes cannot switch either run during resume.

### File Structure

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/background_tasks.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/static/js/chat/chat-messages.js`

## Usage Instructions

Users continue requesting tabular structured output in chat or workflows. For smaller exports, the file is attached during the response. For larger exports, the assistant message shows a background progress card and the final download appears when processing completes. If a resumable run stops after a transient infrastructure failure, the card shows a Continue action that queues the same run to resume from completed checkpoints.

When a background run is accepted, the immediate assistant response acknowledges the complete requested row count and deliverable. Any visible rows are identified as a sample or preview, while mutable progress remains in the status card and the completed file or analysis appears in the chat when ready.

When a workflow/document analysis request also creates a full generated tabular export, the generated export is presented as the primary deliverable. The analysis layer may still attach a supporting CSV preview, but redundant analysis JSON and Markdown artifacts are suppressed so they do not compete with the full generated export card.

The progress card displays current status, completed checkpoint counts, processed row counts, wall-clock rows per minute, model concurrency, estimated remaining time, scheduled retry time, retry-due state, transient retry count, manual continuation count, last update time, and heartbeat time when available.

## Testing and Validation

- Functional regression: `functional_tests/test_tabular_background_generated_exports.py`
- Scale and performance regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 3 immutable plan, recovery, shadow comparison, active schema, and checkpoint-integrity regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 4 compact protocol selection, prompt, validation, row-key, plan-hash, and normalized-output equivalence regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 5 completion-driven checkpoint timing and output-prefix resume scan regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 6 rolling scheduling, heartbeat, backpressure, and straggler regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 7 independent retry, durable retry-ledger, and circuit-breaker regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 8 stable cohort, stale reclaim, source-version publication, crash recovery, and performance-summary regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 2 handoff regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 1 baseline and fake harness coverage: `functional_tests/test_tabular_row_orchestration_scale.py`
- Functional regression for workflow/document-action presentation: `functional_tests/test_document_analysis_lossless_artifacts.py`
- UI regression: `ui_tests/test_chat_background_generated_export_status.py`
- Compile validation covers the modified Python modules.

## Performance Considerations

- The request only stages durable input and queues work for oversized exports.
- Phase 3 batch packing compacts generated-export prompt payloads, removes internal tabular helper fields from staged model input, avoids duplicating row-linked document excerpts as synthetic attachment text, and packs rows by configurable row and character budgets.
- Model-aware packing targets 50% of ordinary model input capacity and 60% of output capacity. Context windows above 500,000 tokens use a lower 30% input ratio and a default 180,000-token soft input cap.
- Adaptive concurrency uses up to 4 calls for small runs, 16 for medium runs, 64 for large runs, and 128 for runs with at least 256 staged batches. An explicit administrator setting overrides the adaptive tier.
- Each parallel window checkpoints successful output batches before advancing public progress in contiguous order.
- Progress is persisted once per completed parallel window. ETA uses recent wall-clock rows per minute rather than summing concurrent model-call durations as serial work.
- Phase 1 telemetry separates safe model-call, validation, and checkpoint timing metrics where the current executor can observe them. Validation mismatch logs record counts and timings only, not generated response previews.
- Phase 3 planning reads at most five staged rows from at most two input checkpoints and sends only column metadata plus redacted value shapes, so planner input remains bounded independently of source row count.
- Phase 4 compact responses reduce repeated generated field names and avoid model-emitted long source tokens for active planned structured exports. Compact responses are normalized before checkpointing, so final CSV, JSON, and XML serialization remains unchanged.
- Phase 5 completion-driven checkpointing offloads synchronous Blob/Cosmos checkpoint work from the event loop through a bounded writer backlog. A fast validated batch can commit its output blob before a slower batch in the same fixed window finishes.
- Phase 6 rolling execution keeps eligible slots occupied as individual tasks complete, subject to checkpoint backpressure.
- Phase 7 delayed per-batch retries leave unrelated pending batches eligible for dispatch.
- Phase 8 stores a bounded terminal performance summary with queue, planning, generation, end-to-end, throughput, concurrency, retry, and rollout dimensions. Detailed latency percentiles remain available from the existing per-batch telemetry events.
- Background processing writes each completed batch before moving on, allowing the run to resume after worker restarts.
- The run status API returns compact metadata only, not source rows or generated batch content.
- User-facing status details are derived from run metadata instead of displaying raw backend errors in the progress card.

## Known Limitations

- Background runs still depend on configured background scheduler capacity and available Azure OpenAI throughput.
- One durable run is still claimed by one application worker; App Service scale-out does not shard a single run across workers.
- Completion time remains proportional to LLM-generated output volume and model generation speed. Higher batching and concurrency improve throughput but do not guarantee a fixed completion time.
- Completion appears through status polling or on the next chat reload; no push notification is added in this version.
- Manual continuation applies to retryable failures, stale running leases, queued retries whose retry time has passed, and stale queued runs; hard validation failures remain terminal.
- Shadow mode does not remove the first-batch schema barrier. Administrators should move new runs to `active` only after representative shadow comparisons preserve every requested field.
- Compact row responses apply only to new active planned structured exports. Existing runs, shadow runs, fallback runs, passthrough rows, analysis-only runs, and combined analysis/export runs remain on `object-v1`.
- Percentage rollback affects new runs only. Existing runs resume with their persisted cohort, effective settings, executor, response protocol, and retry mode.
- The 30,000-row live LLM throughput target remains dependent on provisioned model throughput and must be measured in the target environment before 100% activation.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.241.057** for queued retry recovery and scheduler scan diagnostics.
- `application/single_app/config.py` was updated to version **0.241.059** for Phase 3 compact batch packing.
- `application/single_app/config.py` was updated to version **0.241.060** for Phase 4 bounded batch concurrency.
- `application/single_app/config.py` was updated to version **0.241.064** for generated export artifact presentation cleanup.
- `application/single_app/config.py` was updated to version **0.250.136** for model-aware batch sizing, adaptive LLM concurrency, and parallel wall-clock ETA.
- `application/single_app/config.py` was updated to version **0.250.137** for Phase 1 acceleration baseline contracts, rollout controls, privacy-safe telemetry, and fake model/storage harnesses.
- `application/single_app/config.py` was updated to version **0.250.138** for Phase 2 truthful foreground handoff wording and metadata.
- `application/single_app/config.py` was updated to version **0.250.139** for Phase 3 immutable LLM schema planning, shadow comparison, active scheduling, and checkpoint integrity.
- `application/single_app/config.py` was updated to version **0.250.140** for Phase 4 compact row response protocol validation and normalized checkpoint compatibility.
- `application/single_app/config.py` was updated to version **0.250.141** for Phase 5 completion-driven checkpointing and output-prefix resume scanning.
- `application/single_app/config.py` was updated to version **0.250.142** for Phase 6 rolling worker pool scheduling.
- `application/single_app/config.py` was updated to version **0.250.143** for Phase 7 independent batch retries.
- `application/single_app/config.py` was updated to version **0.250.144** for Phase 8 stable rollout cohorts, stale reclaim, source-version publication checks, chaos recovery coverage, and bounded performance summaries.
