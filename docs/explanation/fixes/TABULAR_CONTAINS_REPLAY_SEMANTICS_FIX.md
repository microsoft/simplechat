# Tabular Contains Replay Semantics Fix

Fixed/Implemented in version: **0.250.155**

Related work: Fixes #1197

## Issue

Durable tabular CSV replay descriptors for `filter_rows` could select a different row cohort than the foreground `filter_rows` call when the `contains` value included regex-sensitive characters such as `A.*`.

## Root Cause

The foreground filter path used pandas `Series.str.contains(value, case=False, na=False)`, where `value` is interpreted as a regular expression by default. The durable replay descriptor emitted `.str.contains(value, case=False, regex=False, na=False)`, which treats the same value as a literal string. Because the bounded CSV replay engine intentionally allowlists literal string methods, the mismatch could make replayed exports disagree with the preview row set.

## Technical Details

### Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_large_result_pagination.py`
- `docs/explanation/release_notes.md`

### Code Changes

- Updated foreground `contains` filtering to use `regex=False`, matching the durable replay descriptor and the bounded CSV query validator.
- Added a regression case where the filter value `A.*` must match literal `A.*` values case-insensitively without matching unrelated `A`-prefixed rows.
- Updated the application version from `0.250.154` to `0.250.155`.

## Impact Analysis

- `filter_rows` preview results and durable generated export replay now use the same literal containment semantics.
- Regex-shaped user input is no longer accidentally treated as a regular expression by `filter_rows` containment matching.
- The bounded CSV replay evaluator remains restricted to side-effect-free literal string operations.

## Validation

- `python functional_tests\test_tabular_large_result_pagination.py`

## Before and After

Before, filtering for `A.*` could match a broader regex cohort in the foreground preview while durable replay matched only literal `A.*` rows. After this fix, both paths match the same literal rows and report the same expected row count.