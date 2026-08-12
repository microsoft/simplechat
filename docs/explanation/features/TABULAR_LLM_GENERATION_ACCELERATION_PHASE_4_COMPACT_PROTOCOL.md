# Tabular LLM Generation Acceleration Phase 4 Compact Protocol

Implemented in version: **0.250.140**

Associated issue: **microsoft/simplechat#1031**

## Overview

Phase 4 adds `compact-row-array-v1`, a persisted response protocol for new active planned structured tabular exports. Instead of asking the model to repeat JSON object field names and copy long source-row tokens for every row, each batch prompt assigns short keys such as `r1` and the model returns positional arrays keyed by those values.

## Purpose

The compact protocol reduces generated structural text and removes source-token copying from the model output while preserving the existing public artifact contract. The server validates compact rows, maps each key back to the authoritative staged source row, reattaches source metadata, and stores the same normalized object-shaped output checkpoints used by `object-v1`.

## Dependencies

- Durable Phase 3 generation plans in `application/single_app/functions_tabular_generated_exports.py`
- Backend rollout setting `enable_tabular_compact_response_protocol`
- Active planner mode `tabular_generation_plan_mode=active`
- Existing checkpoint metadata validation for plan hash and source ETag
- Existing CSV, JSON, and XML finalizers

## Technical Specifications

### Protocol Selection

New run records snapshot `response_protocol_version` at creation. The compact protocol is selected only when all of these are true:

- `enable_tabular_compact_response_protocol` is enabled.
- `tabular_generation_plan_mode` resolves to `active`.
- The task type is structured export.
- The run is not using passthrough input rows.

All existing runs, shadow runs, fallback runs, analysis-only runs, combined analysis/export runs, and passthrough runs remain on `object-v1`.

### Compact Prompt Shape

For compact batches, prompts include the stable user instructions, plan field order, plan hash prefix, protocol rules, expected row keys, and source rows with `__simplechat_batch_row_key`. Internal source-row tokens, source row numbers, and source identities are not included in compact prompt rows.

The model must return one JSON object:

```json
{"p":"planhashpref","rows":[["r1","answer","low"],["r2","answer",null]]}
```

Position 0 is the batch-local row key. Positions 1 through N correspond to the LLM-owned fields from the active plan in exact order. Field names, source tokens, source row numbers, source identities, markdown, and explanations are invalid in the response.

### Validation and Normalization

Server validation requires:

- The top-level object contains only `p` and `rows`.
- The plan hash prefix matches the immutable active plan.
- Every expected key appears exactly once.
- Unknown, duplicate, or missing keys fail validation.
- Every row array has exactly `1 + len(plan LLM fields)` positions.
- Non-null values match the plan field type where practical.
- Nullable fields may return `null`; non-nullable fields may not.

After validation, rows are normalized by key back to source order. The server adds the staged source token only long enough to reuse the existing source-token normalizer, then checkpoints object-shaped rows with `source_row_number`, `source_row_identity`, and the LLM-owned fields.

## Usage Instructions

No end-user workflow changes are required. Administrators can enable `enable_tabular_compact_response_protocol` after Phase 3 active planning is ready for the target environment. Because the selected protocol is copied into each run, later administrator setting changes affect only new runs.

## Testing and Validation

Coverage is in `functional_tests/test_tabular_row_orchestration_scale.py`:

- Compact protocol is selected only for active planned structured exports.
- Compact plans persist and validate the recorded response protocol.
- Compact prompts omit long source-row tokens.
- Reordered compact responses normalize back to source order.
- Normalized compact entries match the existing object-shaped checkpoint schema.
- Duplicate, missing, unknown, malformed-width, plan-hash-mismatched, null non-nullable, and wrong-type values fail validation.

Validation command:

```bash
python functional_tests/test_tabular_row_orchestration_scale.py
```

## Performance Considerations

Compact responses are intended to lower output tokens and response characters for multi-field row generation by removing repeated field names and long source-token values from model output. Phase 4 preserves the existing fixed-window executor and checkpoint timing so compact output can be measured independently before completion-driven checkpointing or rolling scheduling changes.

## Known Limitations

- The protocol is implemented for structured export batches only. Combined analysis/export keeps `object-v1` until its nested analysis payload can be measured separately.
- Provider-side structured output schemas are not required for this phase; server-side validation remains authoritative.
- Live token and latency measurement gates still need to be captured with representative deployments before broad activation.

## Related Version Updates

- `application/single_app/config.py` was updated from **0.250.139** to **0.250.140** for Phase 4 compact row response protocol validation and normalized checkpoint compatibility.