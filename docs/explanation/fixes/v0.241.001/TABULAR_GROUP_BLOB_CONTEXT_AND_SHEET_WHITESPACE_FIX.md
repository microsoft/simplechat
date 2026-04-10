# Tabular Group Blob Context and Sheet Whitespace Fix

Fixed/Implemented in version: **0.240.031**

Related config.py update: `VERSION = "0.240.031"`

## Issue Description

Some group-scoped tabular analyses could fail on otherwise simple workbook questions.

Two specific failure modes were identified:

- Workbook schema preload could fail when an Excel sheet name contained trailing whitespace, such as `CUI `, but the runtime attempted to resolve it as `CUI`.
- After schema preload successfully resolved a group workbook blob, later analytical tool calls could still fail with `BlobNotFound` if the model omitted `group_id` and the plugin retried against personal workspace or chat paths instead of the already known group blob path.

## Root Cause Analysis

- `_resolve_sheet_selection()` normalized requested worksheet names with `.strip()`, but matched them only against untrimmed workbook sheet names. A real worksheet named `CUI ` therefore failed to resolve even when the workbook metadata had already returned the exact tab.
- `run_tabular_sk_analysis()` pre-resolved the correct blob path during schema preload, but the plugin did not retain that resolved location for later tool calls. When an analytical tool call arrived with `source='group'` and no `group_id`, `_resolve_blob_location_with_fallback()` could not retry the group path and fell back to incorrect workspace/chat candidates.

## Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_group_blob_context_and_sheet_whitespace.py`

## Code Changes Summary

- Added per-analysis resolved blob location overrides so once tabular analysis discovers the correct blob path for a workbook, later analytical tool calls can reuse that location without depending on the model to resend `group_id` or `public_workspace_id`.
- Updated workbook sheet matching so explicit sheet requests tolerate trailing whitespace and case drift while still preserving the exact stored worksheet name.
- Updated tabular schema preload to register the resolved blob location with the plugin before any later analysis calls occur.
- Added regression coverage for both trailing-space sheet names and the group blob context reuse path.

## Testing Approach

- Functional regression: `functional_tests/test_tabular_group_blob_context_and_sheet_whitespace.py`
- Re-ran existing multi-sheet workbook regression coverage to ensure no regression in analytical workbook orchestration.

## Validation

- Workbook-level schema preload now succeeds for sheet inventories that include tabs such as `CUI `.
- Trimmed worksheet requests such as `CUI` now resolve to the actual workbook tab `CUI `.
- Group-scoped analytical tool calls can reuse the correct pre-resolved blob path even when later tool invocations omit `group_id`.