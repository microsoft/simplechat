# TABULAR DOCUMENT ACTION LIVE PROGRESS FIX

Fixed in version: **0.241.138**

## Issue Description

Tabular document actions launched from chat Analyze and compare could sit on the initial queued badge for the full duration of the workbook run. The backend was still doing work, but the user did not see the existing tabular lifecycle or tool-progress thoughts, which made the request look stuck.

## Root Cause Analysis

- The shared `_maybe_execute_tabular_document_action(...)` helper in `functions_workflow_runner.py` called `run_tabular_analysis_with_thought_tracking(...)` without the active `thought_tracker`.
- The same helper also dropped the live stream callback, so streamed chat requests never received tabular lifecycle or tool updates after the initial queued message.
- The document-action stream callback in `route_backend_chats.py` only translated legacy analysis/comparison activity events and did not forward preformatted tabular thought payloads.

## Version Implemented

- **0.241.138**

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_document_actions_workflow.py`

## Code Changes Summary

- Added passthrough support for preformatted streamed thought payloads in the document-action chat callback.
- Threaded the active `thought_tracker` and live stream callback through the shared tabular document-action helper.
- Updated the document analysis and comparison workflow branches so tabular workbook analysis emits the same live progress thoughts as the main chat tabular path.
- Added a focused regression test that verifies the live-thought plumbing remains in place.

## Testing Approach

- Ran `pytest functional_tests/test_tabular_document_actions_workflow.py`
- Planned narrow Python syntax validation on the touched backend files

## Impact Analysis

- Long-running tabular Analyze and compare requests now show ongoing lifecycle and tool activity instead of a static queued badge.
- Users can tell the request is still active while workbook evidence is being gathered.
- The fix only changes progress/thought plumbing for tabular document actions; the underlying analysis and comparison logic is unchanged.

## Validation

- Before: tabular document actions could remain on `Queued analysis...` or `Queued comparison...` with no visible progress during workbook analysis.
- After: tabular lifecycle and tool thoughts stream through the existing chat progress renderer, so users see active progress until the final response is ready.