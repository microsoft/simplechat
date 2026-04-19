# Workflow Activity Realtime And Layout Fix

Fixed in version: **0.241.041**

## Issue Description

The workflow activity page was not reliably reflecting live changes while a workflow was still running. In practice, users could end up refreshing the page to see newly created or updated timeline entries. The page layout also allowed the whole page to scroll, which made the top run summary and the activity detail pane move out of view while watching a live run. A follow-up issue also left the timeline without a usable manual scrollbar and prevented it from reliably auto-following the newest events.

## Root Cause Analysis

- The frontend only opened the SSE connection when no explicit `runId` was present, so a directly opened running run would not subscribe to live updates.
- The activity page relied on full-page scrolling instead of a fixed-height viewport with an internal timeline scroller.
- The timeline container still stretched to its content height because the activity layout row was not forcing the panel to fill the available height.
- The timeline did not reliably follow the newest activity card while the page was in live-follow mode, and it did not expose a dependable manual scrollbar for navigating older entries.

## Technical Details

### Files Modified

- `application/single_app/static/js/workflow/workflow-activity.js`
- `application/single_app/static/css/workflow-activity.css`
- `application/single_app/templates/workflow_activity.html`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/config.py`
- `functional_tests/test_workflow_activity_view_feature.py`

### Code Changes Summary

- The activity page now keeps SSE enabled for running workflow views even when a `runId` is explicitly present.
- The SSE polling cadence was tightened to improve perceived real-time updates.
- The page now uses a fixed-height viewport with an internal timeline scroller.
- The activity layout now stretches the timeline panel to the available viewport height so the internal scroller becomes active.
- The timeline now exposes a visible scrollbar and automatically follows the newest activity while live-follow is active.
- Manual scrolling temporarily releases live-follow until the user returns to the bottom of the timeline.
- The top workflow summary area and the right-side detail pane now stay in place while the timeline scrolls.

## Testing Approach

- Extended `functional_tests/test_workflow_activity_view_feature.py` with a running-snapshot regression case.
- Verified the workflow activity functional test passes after the fix.

## Validation

### Test Results

- `functional_tests/test_workflow_activity_view_feature.py` passes with the added running-state assertion.

### User Experience Improvements

- New workflow activities appear without needing a page refresh.
- Long live runs can be watched from a scrolling timeline that stays anchored to the newest activity.
- The top run summary and right-side detail pane remain visible while monitoring the run.
