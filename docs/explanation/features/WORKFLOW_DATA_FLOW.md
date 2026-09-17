# Workflow Data Flow

Implemented in version: **0.261.106**

Version tracking: `application/single_app/config.py`.

## Overview

Analyze-specific finalization, saved-result source access, and chat reuse are
described in [Saved Analyze Results](ANALYZE_RESULTS.md), implemented in
**0.261.109**. The phase-one contract below remains the shared storage and
handoff foundation; its original milestone limitations are not an instruction
to bypass the newer Analyze readers.

Workflow tasks exchange durable results instead of using chat presentation as their data interface. A result identifies its producer, its authoritative final output, its other named representations, and the input references consumed by the next task.

This is useful for extraction followed by synthesis: a task can produce inventory findings, and a later task can explain those findings without uploading the generated file into a workspace or waiting for a search index.

Dependencies are the existing personal/group workflow containers, optional configured Blob storage, the model capability catalog, and the pinned `tiktoken` package. It does not require a second workflow engine or a local memory file.

## Result contract

The contract version is `workflow-result-v1`. A small manifest contains:

| Field | Meaning |
| --- | --- |
| `identity` | Workflow ID, run ID, task ID, and producer attempt. |
| `execution.status` | Producer result state, including known pending, failed, or incomplete document output. |
| `authoritative_output` | The named final section used for the default handoff. |
| `outputs` | Named section kinds and immutable references; values are stored separately. |
| `coverage` and `validation` | Metadata supplied by the producer. No schema validation is invented for a legacy task. |
| `provenance` | Available source identifiers/versions and citation identifiers, without tool-result bodies. |
| `context_budget` | Effective model, limit source, token estimate, response reservation, and budget decision. |
| `consumed_inputs` | Exact producer identity, output selector, manifest reference, and output reference consumed by this task. |

Named sections include final `text`, `records`, or `json`, per-document final results where appropriate, `presentation`, and `diagnostics`. A section envelope carries its producer, output name, kind, and value.

The default handoff never selects a section by length. It loads only the producer's declared authoritative section and sends that value with a consumption receipt and source references. Diagnostic notes and exported Markdown containing those notes are not automatically included.

## Producer integration

The workflow adapter accepts an optional `authoritative_result` on the dispatch result or its nested `analysis_result`:

```json
{
  "authoritative_result": {
    "kind": "records",
    "value": [
      {"item_id": "inventory-1", "quantity": 7}
    ]
  }
}
```

Supported explicit kinds are `records`, `json`, and `text`. The producer must supply its finalized output, not raw intermediate rows chosen by an export helper.

For legacy Analyze results, the final `analysis_reply` is used. Complete JSON is represented structurally when possible; otherwise the final text is retained. The presentation `reply` is used only for ordinary tasks that do not have a separate analysis result.

Per-document Analyze retains a distinct final value for each source document. This representation does not introduce a new general-purpose collection or deduplication operation.

## Persistence and authorized readers

`functions_workflow_result_store.py` exposes:

- `save_workflow_task_result(workflow, run_id, task_id, result, settings=...)`
- `load_workflow_task_result(workflow, run_id, task_id, reference)`
- `read_workflow_task_result_page(workflow, run_id, task_id, reference, offset=..., limit=...)`
- `delete_workflow_run_results(workflow, run_id)`

The reference contains `storage`, `schema_version`, `sha256`, `size_bytes`, and `chunk_count`. The storage schema version is independent of the result contract version. References contain no storage keys, blob paths, or download URLs.

Configured Blob storage is preferred. If the optional Blob client is not configured, the same immutable data is stored in bounded Cosmos chunks. A failure of configured Blob storage does not silently switch backends. Both backends publish a completion manifest after their payload is durable.

Reads bind the content to the authorized personal/group scope, workflow, run, and task. Full loads verify size and SHA-256. Cleanup streams all private result records and run-prefix blobs without applying UI history limits; original Analyze artifacts and published workspace documents are not deleted by this private-result cleanup.

### HTTP endpoints

Personal results:

```text
GET /api/user/workflows/<workflow_id>/runs/<run_id>/tasks/<task_id>/result
```

Group results:

```text
GET /api/group/workflows/<workflow_id>/runs/<run_id>/tasks/<task_id>/result
```

The group route uses the existing authorized group-resolution rules. Each request rechecks current workflow/run access before following a persisted reference.

| Query parameter | Behavior |
| --- | --- |
| `output` | Defaults to `manifest`. Use `authoritative` for the producer-selected final section, or a specific available section such as `records`, `text`, `presentation`, or `diagnostics`. |
| `offset` | Nonnegative offset in canonical serialized JSON bytes. |
| `limit` | Page size from 1 to 65,536 bytes. |

Responses include `content`, `output_name`, `offset`, `next_offset`, `total_bytes`, `sha256`, and integrity information. `complete` means end of the transport stream, not semantic completeness or proof that the caller consumed earlier pages. A partial page does not claim full-result digest verification.

These are transport pages and may split JSON tokens. A model-facing adapter must assemble a complete representation or provide complete-record/token-aware pages; an arbitrary byte fragment or an artifact reference is not a model input by itself. The current task handoff loads the selected final representation and checks its model budget.

Older preview-only runs return an explicit unavailable response instead of a fabricated complete result.

## Model-aware context

The effective task model is resolved after runner overrides. Verified catalog limits and narrower deployment constraints are used independently for total context, input, and output ceilings.

Direct model calls and local Semantic Kernel services check requests at the provider boundary. Tool schemas and accumulated tool results participate in the same budget. The response allowance is applied to the actual request, not merely subtracted from an estimate. Model-default output can use the remaining context, while an explicit response-length choice stays reserved.

Known models without a matching tokenizer use a conservative UTF-8 byte bound. If an OpenAI tokenizer vocabulary cannot be loaded, the audit also identifies the byte-counting fallback. Unknown model capacity is not described as unlimited: the compatibility policy allows an estimated 8,192 input tokens before framing/safety allowance, and reports `limit_source=compatibility_policy`.

When the selected final representation cannot fit, the upstream result remains stored and the dependent task reports a budget error. Select a suitable model, configure verified deployment limits, reduce an explicit response reservation, or use an explicit batching process. This milestone does not automatically summarize exhaustive inputs.

Hosted agents can hide their internal prompts/tools. Their audit is labeled `budget_scope=submitted_messages`; their provider remains responsible for internal context management.

## Usage and boundaries

Existing ordered workflows use the preceding successful task's declared final output. Named bindings to arbitrary earlier tasks, a native V2 designer, general loops/branches, semantic schema validation, and restart-safe execution are not included in this milestone.

Run memory here means persisted results and consumption receipts, not an agent-written file that decides whether work is complete. Producer validation remains explicit, including `not_requested` when no validation was supplied.

Assigned agent knowledge is not an automatic full-text binding. Continue to configure document inputs/actions explicitly where required; shared reference-input and Analyze finalization improvements are separate work.

## Testing and limitations

The functional suite covers production result generation and serialization, both storage backends, reload-to-synthesis without indexing, conflicting diagnostic notes, exact producer/section identity, requests larger than the former 12,000-character cap, context overflow, and real Semantic Kernel tool-round guards.

The store enforces the existing `max_generated_chat_artifact_size_mb` quota per saved section. Byte-range readers keep transport memory bounded; materializing a full final section still requires memory for that section. Large model-facing record pagination belongs in a higher-level adapter.

This contract preserves finalized data that the producer actually returned. It does not repair incorrect extraction, infer completeness from a model's prose, or turn a saved preview into missing historical data.
