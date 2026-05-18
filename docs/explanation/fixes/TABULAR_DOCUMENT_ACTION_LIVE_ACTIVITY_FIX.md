# Tabular Document Action Live Activity Fix - v0.241.038

Fixed in version: **0.241.038**

## Issue Description

Chat document-action runs for selected tabular documents could remain visually stuck on the initial queued message, such as `Queued analyze for 1 selected document`, even while the backend was actively running workbook analysis. Logs showed `TabularProcessingPlugin` calls completing successfully, but the chat UI did not transition into the live tabular analysis activity card.

## Root Cause Analysis

- The chat route created a `ThoughtTracker` and live document-action stream callback before dispatching document actions.
- The workflow runner's tabular document-action helper invoked `run_tabular_analysis_with_thought_tracking(...)` without passing either object.
- Because the tabular helper did not receive the tracker or live callback, lifecycle events, tabular tool start/completion activity, and generated-output post-processing thoughts were not persisted or streamed for document-action tabular runs.

## Technical Details

### Files Modified

- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_document_actions_workflow.py`
- `docs/explanation/fixes/TABULAR_DOCUMENT_ACTION_LIVE_ACTIVITY_FIX.md`

### Code Changes Summary

- Added a document-action tabular thought callback bridge that can persist tabular post-processing thoughts and forward them to the existing live stream callback.
- Passed `thought_tracker` and `live_thought_callback` into `run_tabular_analysis_with_thought_tracking(...)` for Analyze and comparison document actions.
- Wired generated tabular output post-processing to publish progress thoughts during export preparation and upload.
- Incremented `config.py` from `0.241.037` to `0.241.038`.

## Validation

### Test Results

- `functional_tests/test_tabular_document_actions_workflow.py` verifies the tabular document-action helper accepts and forwards live thought tracking, and that Analyze/comparison model and agent paths pass the stream callback.

### User Experience Improvements

- Selected workbook analysis now transitions from the queued document-action message into the live tabular analysis activity card.
- Users can see workbook evidence gathering, tool calls, retries, and export post-processing instead of interpreting a quiet UI as a hung run.