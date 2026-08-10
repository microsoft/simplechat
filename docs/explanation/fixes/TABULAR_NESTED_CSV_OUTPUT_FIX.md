# Tabular Nested CSV Output Fix

Fixed in version: **0.250.148**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Some completed background generated CSV exports contained the expected number of source rows but had the wrong output shape. Instead of separate generated columns such as `transaction_summary`, `counterparty_classification`, and `risk_prioritization`, the final file contained columns like:

```text
source_row_number,source_row_identity,transaction_id,csv
```

Each `csv` cell then contained a complete mini CSV payload for that source row. This made the artifact technically complete by source row count but not usable as the requested flat CSV dataset.

## Root Cause

The object response protocol accepts a JSON object per source row. When the model returned one object containing a `csv` property with a single generated CSV row, the server inferred that object shape as the run schema. Finalization then faithfully serialized the nested `csv` field instead of expanding the generated columns.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Code Changes

Model response normalization now detects generated objects whose only meaningful model output is a `csv` field. When that field parses as exactly one CSV data row, the server expands it before schema inference and then applies the existing row count, source identity, source token recovery, and schema validation contracts.

The recovery is deliberately narrow:

- it applies only to single-row nested CSV payloads;
- it does not accept multi-row nested CSV content inside one generated row;
- it does not bypass source row order or schema validation;
- compact row protocol behavior is unchanged.

## Validation

Functional coverage creates object-protocol model output with a nested `csv` property and verifies the normalized entries flatten into generated columns with no residual `csv` field.

Validated with:

```bash
python -m py_compile application/single_app/functions_tabular_generated_exports.py application/single_app/config.py functional_tests/test_tabular_row_orchestration_scale.py
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -k "nested_csv or token_echo_recovery or background_metadata" -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
```

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.147** to **0.250.148** for this nested CSV output-shape fix.