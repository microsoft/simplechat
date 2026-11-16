# Tabular Background Generated Exports

Implemented in version: **0.241.046**

Updated through version: **0.261.127**

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
- Background handoff metadata derives its requested row count from the safe public run status so accepted durable runs cannot terminate the foreground stream while constructing the status card payload.
- Object-protocol model responses can recover from hidden source-token echo mismatches when row count and any explicit source row number or identity markers preserve the requested source order.
- Fixed-window runs use a timeout-aware stale threshold so normal long model calls are not shown as stale while only rolling-pool runs use the short heartbeat interval. Retry status text includes safe reason categories such as model output validation or transient provider interruption.
- Object-protocol responses that wrap one generated CSV row inside a `csv` property are expanded before schema inference so final artifacts use the requested generated columns instead of a nested CSV column.
- Direct durable artifact routing accepts every configured tabular input format (`csv`, `xlsx`, `xls`, and `xlsm`) through one version-pinned replay contract. Multi-sheet workbooks replay worksheets in workbook order.
- Recognized exhaustive artifact requests never fall back to dumping generated rows into the assistant response when source preparation fails. The chat receives a concise artifact handoff or safe failure status instead.
- Shadow schema planning is deferred off the production critical path. Unplanned source-backed runs checkpoint a small first batch before opening normal batch concurrency, and the status card identifies source preparation, active planning, or initial checkpoint generation before row progress appears.
- Running background cards keep the status badge, progress bar, and available actions visible by default. File/source metadata, checkpoint counts, remaining work, throughput, concurrency, timestamps, and previews are grouped under a collapsed `View details` disclosure.
- Completed structured artifacts show only the generated filename, total row count, and `Download`, `View`, and `Add to Workspace` actions. `View` opens a bounded validated preview in a modal, and the stale background handoff prose is hidden after completion.
- New source-backed runs estimate serialized row size from a bounded source sample, apply the tighter of row and character capacity, and rebalance uneven multi-wave work across configured model concurrency. Completion-driven checkpointing is enabled by default so successful batches become durable while slower siblings are still running.

### Internal computation without file publication

Implemented in version: **0.261.127**. This producer/service boundary supports the
orchestration work in [#1509](https://github.com/microsoft/simplechat/issues/1509).
It does not by itself enable orchestration routing or change existing chat and
workflow publication.

`functions_tabular_analysis.build_native_tabular_compute_callback(...)` binds an
initialized native engine to a server-owned user, conversation, producer, source
manifest, and selected model. It does not import a Flask route or construct an
application to execute a query. The producer contains `user_id`,
`conversation_id`, `run_id`, `attempt_index`, `step_id`, `capability_id`, and
`contract_version`; it must identify an enabled step in the owning orchestration
run. Browser or model arguments must not supply this identity.

Call the returned callback with `plan` and `user_question`, or pass it as
`durable_execution_callback` to `execute_tabular_plan` with
`execution_policy="data_only"`. The planner's data-only result is in
`native_compute_result`, never `generated_output_metadata`. A foreground plan
is executed rather than returned as successful planning metadata. Admission
uses the native model/character-aware batch budget and existing inline
thresholds; larger work returns an owned job for the existing native scheduler.

Both execution modes run the same version-pinned CSV/workbook query replay,
transformations, batch validation, and checkpoints. Query samples only estimate
batch size; they are never used as the complete result. The service supports one
replayable authorized CSV or workbook source. Multiple/mixed sources are refused
before query/model execution or submission. A foreground row transformation
requires an executable transformation specification or declared output schema.
An explicit query additionally requires `native_operation="query"`,
`query_expression`, and a declared schema. Analysis-only work uses
`native_operation="analysis"` or a hierarchical-analysis plan. A bare foreground
aggregate/prose plan is not silently replaced by source rows.

The returned state is `pending`, `completed`, or `failed`; cancellation detected
before submission returns `cancelled` without a handle. Lost ownership, deleted
owners, cancellation of an existing owner, source access loss, and screening
holds refuse access rather than returning usable output. Pending and failed
states have no reader. An opaque handle contains only `version`, `job_id`, and
`request_fingerprint`. Persist that handle, not callback or reader objects.
Deterministic producer identity and atomic creation prevent duplicate jobs;
changing the executable request or source within the same producer attempt is
rejected.

After a restart, `open_native_tabular_result(user_id=..., conversation_id=...,
handle=..., producer=...)` opens the private result without resubmitting work.
Completion requires `computation_state="complete"` and a validated native result
manifest, independently of artifact publication. `reader` is the primary output;
`readers["records"]` and `readers["analysis"]` expose applicable outputs, including
both for combined work. A reader exposes `kind`, ordered `columns` and `schema`,
`item_count`, exact `sources`, `coverage`, and `completeness`. Records use
`iter_records()`; the bounded analysis value uses `read_value(max_bytes=...)` or
`iter_value_bytes()`. Consumers must exhaust a record iterator before retaining
it as complete: final count, byte size, and digest checks occur at exhaustion.
Zero-row records retain their declared schema.

Reads recheck current ACLs, screening, and producer ownership at batch boundaries.
By default, completed readers allow an authorized historical source snapshot;
`require_current_sources=True` also requires the original document revision and
blob ETag. New work and worker continuation always require current sources.
Cancellation, deletion, changed attempts, and stale worker leases fence further
checkpointing. Invalid or incomplete output is not computation-ready.

The data-only policy and producer/source binding are persisted in the native
job and checkpoint metadata. Resume cannot fall back to file publication:
structured, analysis-only, and combined completion create no managed user files,
artifact-set commits, upload calls, or artifact cards. Private native input,
output, and final-summary blobs remain necessary for durable execution.
Standalone and workflow callers retain the default `execution_policy="publish"`
behavior. There is no new scheduler, deployment service, or render-registry
dependency. Native semantic outputs retain the native model's limitations; a
complete checkpoint is not an independent factual or mathematical review.

### Retaining native computation for orchestration

Implemented in version: **0.261.127** (`application/single_app/config.py`).
`functions_orchestration_native_results.py` bridges the native service to the
initialized orchestration result store. It does not register a capability,
modify an adapter, construct a route context, or schedule continuation; those
remain parent integration work for #1509.

Create a server-owned binding with `build_native_orchestration_bridge`:

```python
bridge = build_native_orchestration_bridge(
    native_operation="transform",
    task_type="structured_export",
    source_policy="current",
)
```

The default builder is the production `build_native_orchestration_request`.
It calls the existing `plan_tabular_request` service, then constructs the native
deliverable contract from the explicitly approved mode and schema. It preserves
source-order, one-result-per-matching-row validation and transformation rules;
file-intent heuristics cannot replace the declared schema or request publication.
The existing native engine performs the actual query, deterministic transforms,
semantic/hybrid row work, and hierarchical/combined model work.

Server metadata can use `native_orchestration_arguments_schema()` and must also
apply `validate_native_orchestration_arguments(arguments)`, which reuses the
native row-local query validator and bounded transformation DSL validator.
The production bridge performs both checks before model selection or work.

| Argument | Contract |
|---|---|
| `question` | Required nonblank instructions, at most 24,000 characters; not executable query syntax. |
| `document_ids` | Required list containing exactly the authorized source document ID. |
| `native_operation` | Required `query`, `transform`, or `analysis`. There is no question-only default. |
| `task_type` | Defaults to `structured_export` for query/transform and `hierarchical_analysis` for analysis. Transform also supports `combined`. |
| `query_expression` | Required for query; optional row filter for transform/analysis. Uses the existing bounded row-local native grammar. |
| `columns` | Required for query/transform; 1–50 ordered, unique public column names. Forbidden for analysis. |
| `transformation_spec` | Optional existing `tabular-transform-v1`/`tabular-transform-v2` spec for transform/combined. Its fields must match `columns`. Without a spec, declared row fields use existing semantic/model processing. |
| `selected_sheet` | Optional explicit workbook worksheet. CSV requests cannot supply a worksheet. |

Unknown arguments, internal lineage columns, mismatched fields, invalid DSL
expressions, and operation/task/schema contradictions are refused, not ignored.
Each request is bounded to 64 KiB of canonical argument JSON. For example:

```python
arguments = {
    "document_ids": ["approved-document-id"],
    "question": "Return matching rows and count all matches.",
    "native_operation": "query",
    "query_expression": "amount >= 100",
    "columns": ["Item_ID", "amount"],
}
```

Query returns the complete filtered records, and its exact matching-row count is
`coverage.outputs.records.actual_count`, checked against `expected_count` after
full consumption. Zero matches produce zero records and count zero. Native
replay queries do **not** implement global `sum`, `mean`, grouped reductions, or
arbitrary Python expressions; those expressions fail before execution. The
legacy plugin's standalone aggregate methods are not silently invoked as an
uncheckpointed substitute. Explicit analysis mode can perform existing
model-supported analysis over the full selected cohort, with its native model
limitations preserved; it is not advertised as a deterministic aggregation.

For specialized server callers, an optional
`request_builder(step, context, *, settings, user_id, source_manifest,
native_operation, task_type, cancel_requested)` returns
`NativeOrchestrationRequest(plan, user_question)`. It may use an existing trusted
model-request builder; the default bridge does not guess executable queries or translate
an aggregate into unmodified source rows. Unsupported multiple/mixed selections
are refused before this callback or model selection runs. This binding consumes
one original replayable tabular document, not named retained-result inputs:
declare `inputs={}`. A nonempty input binding is refused rather than ignored or
silently replaced with rows from the original document.

By default, model selection uses the already captured `context.gpt_model` and
`context.model_context`. An optional trusted
`model_resolver(step, context, *, settings, user_id)` instead returns
`{"gpt_model": ..., "model_context": ...}`. These runtime dependencies never enter
the persisted wait handle. The bridge neither imports a Flask route nor creates
an application/client to select a model.

`bridge.execute(step, context, *, settings, user_id, emit=None,
cancel_requested=None)` and
`bridge.resume(step, context, pending_result, *, settings, user_id, emit=None,
cancel_requested=None)` have adapter/resolver signatures. The equivalent module
functions are `execute_native_orchestration_step` and
`resume_native_orchestration_step`, with an additional explicit `binding=bridge`
keyword. Missing bindings fail closed.

The context must supply the real v2 `result_producer(step)`, initialized
`result_service`, actual `result_guard_token_for_step(step_id)`, full authorized
single-source `source_manifest`, and matching user/conversation/run/attempt
identity. A producer's `contract_version` is its server-selected string result
contract, not the integer plan version. The bridge prepares the existing result
fence using the supplied token; it never manufactures a token.

`native_orchestration_output_specs(native_operation, *, task_type=None)` returns
the exact required `OutputSpec` tuple for server metadata and step declarations:

| Native operation and task | Required named outputs |
|---|---|
| `query` or `transform`, `structured_export` | `records` (`records-v1`), `coverage` (`structured-v1`) |
| `analysis`, `hierarchical_analysis` | `analysis` (`structured-v1`), `coverage` (`structured-v1`) |
| `transform`, `combined` | `records` (`records-v1`), `analysis` (`structured-v1`), `coverage` (`structured-v1`) |

`task_type` defaults to hierarchical analysis for `analysis`, otherwise structured
export. Declarations that omit an output, invent an output, or advertise records
for analysis-only work are rejected. Every actual native reader is retained;
record iterators pass directly into `NamedOutput` and the guarded generic store.
Large record collections are not materialized. Native analysis JSON is bounded
by `max_analysis_bytes` (default and maximum 8 MiB). Its full summary stays in
the retained analysis value; the step summary is only a presentation of that
validated result. Coverage contains exact snapshots and native validation
metadata, not a count inferred from a preview. These are not `analyze-final-v1`
or `SavedAnalysisInput` conversions.

Pending execution returns a real `StepResult` with status `waiting`,
`TaskResult(producer, "reason", "pending", ())`, and exactly:

```python
{"kind": "native_tabular_compute", "handle": native_result["handle"]}
```

Pass that original typed pending step result to `resume`; decode its `TaskResult`
through the existing checkpoint codec after a restart. M4 stores the typed task
and wait separately; the resolver can pass this envelope without generating
another task or attempt:

```python
pending_result = {
    "status": "waiting",
    "task_result": context.task_results[step["step_id"]],
    "wait": context.pending_results[step["step_id"]],
}
```

Resume validates the same producer/run/attempt, opens the handle once, and never calls the request builder,
model resolver, native callback factory, or queue. It has no polling loop.
Repeated pending reads remain waiting with no output. The native scheduler can
compute while the parent is `waiting`; before retaining a completed result, the
parent must reactivate the same attempt as `running` and supply its current real
write guard. An already retained complete task in `context.task_results` is
reauthorized and reused without another result write.

The default `source_policy="current"` requires current source snapshots.
`source_policy="snapshot"` permits explicitly retained historical data only when
the context still names the original trusted snapshot and current ACL/screening
checks allow it. It does not authorize changed inputs as equivalent. Parent
checkpoint validation must verify the original declared-input fingerprint before
resume. The optional trusted `input_fingerprint_for_step(step, context)` binding
forwards that exact fingerprint as `persist_task_result(input_fingerprint=...)`;
it is validated before planning and never recomputed by the bridge. Omitting the
hook preserves the existing receipt-free retention path. Pending tasks never
commit a completion receipt. With that
binding, resume also calls the facade's existing `recover_task_result` after
opening the original completed native handle, so a committed result can be
reauthorized and reused after restart even without an in-memory task cache.
The facade fully verifies the stored outputs. The bridge invents neither a
substitute hash nor a producer-completion recovery algorithm. Recovery before
adapter dispatch and parent continuation scheduling remain runtime responsibilities.
Recovery exceptions terminate the resume; only an actually absent receipt permits
new retention. A failed verification is never treated as an absent result.

Native validation and verified access failures are terminal, with
repository-standard safe messages and bounded
`failure.native_code`/`failure.retryable=False` metadata. Revocation, corrupt
output, invalid handles, canceled/deleted owners, and lost guards are not
downgraded into previews or indefinite waiting. Native computation and retention
run under the no-user-files policy; only private native/result-store writes are
allowed. Rendering uses the parent's existing authorized export-source bridge
later, with explicit public-column selection.

Operational uncertainty is different from a verified denial. The bridge and its
v2 callers use `raise_native_orchestration_infrastructure_failure(error)` before
converting failures into step results. It lazily reuses the shared output-read
classification: non-hold screening/source-authority and external authority or
configuration exceptions retain their original identity and public metadata.
Known transport, Azure, checkpoint-storage and unavailable retained-backend
failures surface as the existing safe `OutputStorageError`. Explicit causes
behind authorization wrappers are checked, but an ordinary calculation or
validation cause is not promoted to infrastructure failure. An unavailable poll,
receipt read or retention write does not produce a terminal native task, invent
a successful poll, replace the producer, or clear its original wait. The owning
runtime retains responsibility for bounded continuation and failure handling.

`functional_tests/test_orchestration_native_results.py` exercises real native
calculation, full reader retention and the existing export bridge over 30,000
derived records, analysis-only/combined naming, same-attempt waiting/resumption,
source and guard fences, corruption refusal, and normal/optimized cold imports.
Production-default tests also cover native query/counting, deterministic,
semantic and hybrid transforms, analysis and combined execution, exact schema
despite file-intent wording, and invalid argument refusal before work. Combined
requests with entirely deterministic output fields now explicitly tell the
native model that its structured-row field list is empty; schema discovery
without a declared schema retains its previous prompt.
`functional_tests/test_orchestration_native_infrastructure_failures.py` injects
direct and authorization-wrapped failures into actual job polls, source checks,
receipt reads and foreground/background retention. It verifies unchanged
pending identity and guards, complete transformed rows after storage recovery
without resubmission or publication, genuine-denial/validation controls, and
lazy classification in network-blocked normal/optimized processes.

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
- `application/single_app/functions_native_tabular_compute.py`
- `application/single_app/functions_native_analysis_results.py`
- `application/single_app/functions_tabular_analysis.py`
- `application/single_app/functions_tabular_orchestration.py`
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

- Offline native computation, complete 30,000-row derived output, empty schema-preserving output, foreground/durable equivalence, semantic and combined completion, restart-ready readers, ownership/source revocation, stale workers, atomic submission, and zero-publication regression: `functional_tests/test_native_tabular_compute_service.py`. Provider and storage I/O are doubled; the real query, transformation, validation, and checkpoint engine executes.
- Functional regression: `functional_tests/test_tabular_background_generated_exports.py`
- Scale and performance regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 3 immutable plan, recovery, shadow comparison, active schema, and checkpoint-integrity regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 4 compact protocol selection, prompt, validation, row-key, plan-hash, and normalized-output equivalence regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 5 completion-driven checkpoint timing and output-prefix resume scan regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 6 rolling scheduling, heartbeat, backpressure, and straggler regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 7 independent retry, durable retry-ledger, and circuit-breaker regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Phase 8 stable cohort, stale reclaim, source-version publication, crash recovery, and performance-summary regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Background metadata streaming regression for export, analysis, and combined modes: `functional_tests/test_tabular_row_orchestration_scale.py`
- Source-token echo recovery regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Fixed-window stale heartbeat regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Nested CSV output recovery regression: `functional_tests/test_tabular_row_orchestration_scale.py`
- Generic CSV and workbook durable routing regressions: `functional_tests/test_tabular_row_orchestration_scale.py`
- Artifact-only failure and fast-start regressions: `functional_tests/test_tabular_row_orchestration_scale.py`
- Collapsed background status detail regressions: `functional_tests/test_tabular_background_generated_exports.py` and `ui_tests/test_chat_background_generated_export_status.py`
- Completed artifact card and bounded modal regressions: `functional_tests/test_tabular_background_generated_exports.py` and `ui_tests/test_chat_generated_tabular_output_card.py`
- Character-aware balanced batch and completion-checkpoint regressions: `functional_tests/test_tabular_row_orchestration_scale.py`
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

- The internal native data-only service is documented against `application/single_app/config.py` version **0.261.127**. The parent orchestration integration owns its release/version normalization.
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
- `application/single_app/config.py` was updated to version **0.250.145** to prevent accepted background-run metadata from terminating the foreground stream with an undefined row-count variable.
- `application/single_app/config.py` was updated to version **0.250.146** to recover object-protocol model responses that preserve row order but fail to echo hidden source-row tokens.
- `application/single_app/config.py` was updated to version **0.250.147** to prevent fixed-window runs from being falsely marked stale during normal long model calls and to show safe retry-reason details in the status card.
- `application/single_app/config.py` was updated to version **0.250.148** to flatten single-row nested CSV model outputs before generated-export schema inference.
- `application/single_app/config.py` was updated to version **0.250.149** to route every supported tabular input through artifact-only durable generation and reduce time to the first visible checkpoint.
- `application/single_app/config.py` was updated to version **0.250.150** to simplify background export cards while preserving expandable operational detail.
- `application/single_app/config.py` was updated to version **0.250.151** to simplify completed artifact cards and add bounded on-demand previews.
- `application/single_app/config.py` was updated to version **0.250.152** to normalize JSON/XML completed cards and reduce durable export stragglers with character-aware balanced batches.
