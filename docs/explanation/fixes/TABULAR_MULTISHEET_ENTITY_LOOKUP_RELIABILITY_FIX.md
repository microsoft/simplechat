# Tabular Multi-Sheet Entity Lookup Reliability Fix (v0.240.009)

Fixed/Implemented in version: **0.240.009**

## Issue Description

Multi-sheet Excel workbooks could intermittently fail during tabular chat analysis even though the workbook was loaded successfully from blob storage and the tabular plugin was enabled. In the failing path, the mini Semantic Kernel tabular pass returned narrative-only retries without invoking analytical tools, so the outer chat flow fell back to schema-only context instead of computed results.

## Root Cause Analysis

- Legacy single-endpoint mode was not the blocker. The logs showed the application loading the legacy Azure OpenAI client, initializing the tabular plugin, and pre-loading workbook sheets successfully.
- The brittle path was specific to `entity_lookup` orchestration for multi-sheet workbooks. The prompt required explicit `sheet_name` guidance too early, before the model had identified the right starting worksheet or used the plugin's existing cross-sheet discovery capabilities.
- Sheet ranking for entity lookups could overvalue downstream record sheets such as `Notices` or `Audits` instead of the primary entity worksheet such as `Taxpayers`, which made the first analytical step less obvious.
- For analytical queries, unsupported `query_tabular_data` expressions on multi-sheet workbooks could collapse into a misleading explicit-sheet error instead of returning a direct query-expression failure, making retries less reliable.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_entity_lookup_mode.py`
- `functional_tests/test_tabular_multisheet_workbook_support.py`

### Code Changes Summary

- Added entity-anchor worksheet scoring so multi-sheet entity lookups prioritize the primary entity worksheet more reliably.
- Updated the entity-lookup mini-agent prompt to allow an initial cross-sheet `filter_rows` or `query_tabular_data` discovery step when the starting worksheet is unclear.
- Added prompt guidance to prefer row-retrieval tools before aggregates for entity lookups and to avoid fragile `DataFrame.query()` patterns.
- Improved cross-sheet `query_tabular_data` error reporting so expressions that fail on every worksheet return a direct query error instead of a misleading sheet-selection message.
- Added regression coverage for entity-sheet hinting, cross-sheet discovery prompt guidance, and direct multi-sheet query-error reporting.

### Testing Approach

- Functional regression: `functional_tests/test_tabular_entity_lookup_mode.py`
- Functional regression: `functional_tests/test_tabular_multisheet_workbook_support.py`
- Functional regression: `functional_tests/test_tabular_retry_sheet_recovery.py`

## Validation

### Before

- Multi-sheet entity lookup questions could pre-load workbook data successfully but still complete the tabular mini-agent pass without any analytical tool calls.
- Some multi-sheet analytical retries surfaced a sheet-selection error even when the underlying problem was an invalid or unsupported query expression.

### After

- Multi-sheet entity lookup questions have a clearer first discovery step and stronger primary-sheet guidance.
- Cross-sheet analytical discovery is explicitly supported in the prompt before the follow-up sheet-specific calls.
- Invalid cross-sheet query expressions return a direct query failure, improving retry quality and reducing misleading multi-sheet errors.
- The application version in `config.py` was updated from `0.240.008` to `0.240.009` for this fix.