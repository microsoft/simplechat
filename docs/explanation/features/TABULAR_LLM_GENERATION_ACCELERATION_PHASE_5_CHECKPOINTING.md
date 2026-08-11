# Tabular LLM Generation Acceleration Phase 5 Checkpointing

Implemented in version: **0.250.141**

Associated issue: **microsoft/simplechat#1031**

## Overview

Phase 5 adds opt-in completion-driven checkpointing for structured tabular generated exports. Within each existing fixed execution window, model calls are consumed with `asyncio.as_completed()`, and every validated result is submitted to checkpoint storage as soon as that model call finishes.

## Purpose

The change narrows crash-loss exposure. A fast batch no longer waits for the slowest model call in the same window before its output blob can become durable. Fixed window boundaries are intentionally retained so checkpoint durability can be validated independently before rolling scheduling is introduced.

## Dependencies

- Backend rollout setting `enable_tabular_completion_driven_checkpointing`
- Backend writer limit `tabular_generation_checkpoint_writer_concurrency`
- Existing structured-export checkpoint helper and metadata validation
- Existing fixed-window structured-export executor
- Existing final CSV, JSON, and XML publication paths

## Technical Specifications

### Completion Stream

When completion-driven checkpointing is enabled, the structured-export window creates the same batch tasks as before, but consumes them through `asyncio.as_completed()`. Successful validated model results are passed immediately to the checkpoint writer path. Model failures are recorded as the first window error while other already-active tasks continue to settle and checkpoint any successful results.

### Bounded Checkpoint Writer

Checkpoint storage remains synchronous, so the Phase 5 path uses `asyncio.to_thread()` behind an `asyncio.Semaphore`. The writer concurrency is resolved from `tabular_generation_checkpoint_writer_concurrency` and clamped to a bounded range. Pending checkpoint tasks are capped at twice the writer concurrency; when that high-water mark is reached, the executor waits for at least one checkpoint to finish before accepting more completed results for publication.

### Durable Completion Semantics

The existing `_checkpoint_generated_batch_results(...)` helper remains the authoritative commit path. It verifies lease ownership before writing, uploads the output blob with overwrite disabled for normal runs, validates a concurrent existing output when necessary, then writes the derived summary blob. A batch only appears in returned window results after its output checkpoint succeeds or a compatible existing checkpoint is validated.

### Resume Scan

Structured runs now build a durable completed set by listing the run output prefix once before the fixed-window loop. The existing batch-window loader uses that set to find candidate output checkpoints, then lazily validates checkpoint metadata and payload shape before treating the batch as complete. Missing summaries are repaired from valid output payloads without another model call.

### Progress and Ordering

Output blobs may commit out of order. Public status already exposes bounded aggregate contract fields such as `completed_batch_count`, `highest_contiguous_batch`, and `checkpointed_row_count`; final publication still depends on contiguous `completed_batches` reaching the planned batch count. Ordered artifact assembly remains unchanged and continues to read output rows by batch number.

## Usage Instructions

No end-user workflow changes are required. Administrators can enable `enable_tabular_completion_driven_checkpointing` after representative validation confirms checkpoint latency and storage throughput are acceptable. The feature applies to new structured-export work in the fixed-window executor and can be disabled for new runs without changing the normalized output blob shape.

## Testing and Validation

Coverage is in `functional_tests/test_tabular_row_orchestration_scale.py`:

- A fast model completion checkpoints before a slower batch in the same fixed window finishes.
- The checkpoint writer path honors the configured bounded writer concurrency.
- Resume builds the completed checkpoint set from one output-prefix listing and ignores malformed, foreign, and out-of-range blobs.

Validation commands:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py::test_phase_five_completion_driven_checkpointing_commits_fast_batch_before_straggler functional_tests/test_tabular_row_orchestration_scale.py::test_phase_five_resume_scan_lists_output_prefix_once -q
```

## Performance Considerations

Checkpoint I/O is bounded separately from model concurrency, so active model calls do not block directly on Blob or Cosmos operations running on the event loop. The writer backlog remains bounded by the configured writer concurrency. Fixed-window model dispatch is preserved, so this phase should not materially reduce existing throughput while proving durability semantics.

## Known Limitations

- Rolling worker scheduling remains deferred to Phase 6; no work launches beyond the current fixed window.
- Independent non-blocking batch retry remains deferred to Phase 7.
- The Phase 5 completion stream is implemented for structured export batches. Combined analysis/export keeps the existing window-level checkpoint barrier until its nested analysis checkpoint contract is separated.

## Related Version Updates

- `application/single_app/config.py` was updated from **0.250.140** to **0.250.141** for Phase 5 completion-driven checkpointing and output-prefix resume scanning.