# Tabular Source Token Echo Recovery Fix

Fixed in version: **0.250.146**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Large background tabular generated exports could appear to stall after the first schema-discovery batch. Production logs showed full durable runs were accepted, for example `row_count=300`, `batch_count=6` and `row_count=3000`, `batch_count=52`, but later object-protocol batches were repeatedly rejected with:

```text
Generated source row token mismatch at row 1
```

For the 300-row run, the first 50-row batch completed, then the worker repeatedly scheduled batches 2 through 5 because the fixed-window concurrency was 4. Those batches returned the expected 50 generated objects but failed validation because the model did not echo the hidden `__simplechat_source_row_token` value exactly.

## Root Cause

The object response protocol asked the model to copy a hidden source token into each output row. Some live responses preserved row count and visible row order but invented, omitted, or mutated that hidden token. The server treated that token mismatch as a hard validation error, retried the same batches, and did not advance completed row progress.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Code Changes

The low-level `_normalize_generated_batch_entries(...)` function remains strict and still rejects token mismatches. Model response normalization now uses a wrapper that:

- first attempts strict token validation;
- recovers only from source-token mismatch errors;
- requires the parsed generated row count to already match the source row count;
- rejects recovery when the model includes an explicit source row number or identity that conflicts with the source row at that position;
- reattaches source row number and source identity server-side after recovery;
- logs a safe recovery event without row data or prompt content.

Compact row protocol behavior is unchanged because compact responses already use batch-local row keys and do not ask the model to echo source tokens.

## Validation

Functional coverage verifies that direct strict normalization still rejects swapped source tokens, while model-response normalization can recover token echo mismatches only when row order is preserved and explicit source markers do not conflict.

Validated with:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "token_echo_recovery or background_metadata or phase_two" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
```

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.145** to **0.250.146** for this source-token echo recovery fix.