# Tabular Character-Aware Batch Balance Fix

Fixed in version: **0.250.152**

Related issue: **microsoft/simplechat#1031**

## Issue Description

A 300-row generated CSV run completed in approximately 47 minutes. It used seven batches with configured model concurrency four, but effective concurrency averaged two and durable throughput was 22.66 rows per minute. Several long batches approached or exceeded the five-minute model timeout, causing repeated worker lease generations and manual continuation.

## Root Cause

Queue-time planning considered model token-derived row and character ceilings independently but did not estimate which ceiling would constrain the actual source rows. It also allowed an uneven final concurrency wave. For the observed source, the model row limit was 88 rows, while serialized source size caused the character limit to split batches at roughly 58 rows. Six post-probe batches therefore ran as a four-batch wave followed by an uneven two-batch wave, leaving a long straggler.

Completion-driven checkpointing was available but disabled by default, so successful sibling batches were not persisted until the entire window, including a timeout, finished.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `functional_tests/test_tabular_background_generated_exports.py`
- `functional_tests/test_tabular_large_result_pagination.py`

### Code Changes

- Direct CSV and workbook source resolution captures up to five representative rows and stores only the largest compact serialized row length in the backend-only source descriptor.
- Queue planning derives character-limited row capacity from that sample and chooses the tighter of token row capacity and character capacity.
- Uneven multi-wave plans are rebalanced to fill the same number of configured concurrency waves evenly.
- Balanced batching and completion-driven checkpointing default to enabled for new canary runs, while control cohorts remain on legacy behavior and rollout assignment remains snapshotted for deterministic resume behavior.
- Initial handoff summaries no longer claim an exact batch count before source staging can apply character constraints.

For the observed 300-row fixture, the bounded sample measured 1,851 characters per row. With a 104,856-character batch budget, capacity resolves to 56 rows. Balancing six post-probe batches across two four-worker waves produces eight batches of approximately 37 rows plus the five-row schema probe, for nine total batches.

## Validation

Regression coverage verifies:

- the observed 300-row inputs resolve to a 37-row balanced limit;
- a 200-row one-wave plan remains at its existing row capacity;
- disabling balanced batches preserves the original capacity;
- CSV and Excel source sampling use the same backend-only descriptor field;
- queue metadata records token, character, and balanced row limits;
- completion-driven checkpointing is enabled by default while control cohorts remain legacy.

## Known Limitation

This change reduces timeout risk and concurrency imbalance but does not guarantee a fixed completion time. Model latency, provider availability, requested output verbosity, and retry behavior still affect duration.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.151** to **0.250.152** for character-aware balanced batching and immediate completion checkpointing.