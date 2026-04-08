# Personal Workspace Tutorial Reposition Fix

Fixed/Implemented in version: **0.239.185**

## Issue Description

The Personal Workspace tutorial could leave its highlight and tutorial card behind after the document search panel closed. The collapse animation moved the table content upward, but the tutorial overlay stayed at its old screen coordinates until the next manual scroll or resize.

## Root Cause Analysis

The workspace tutorial only recalculated overlay placement during initial step render and on global scroll or resize events. Bootstrap collapse transitions and workspace DOM updates changed element positions without firing either path.

## Technical Details

### Files Modified

- `application/single_app/static/js/workspace/workspace-tutorial.js`
- `application/single_app/config.py`
- `functional_tests/test_workspace_tutorial_reposition_fix.py`

### Code Changes Summary

- Added a deferred reposition scheduler so the tutorial recomputes placement after the browser finishes the current layout update.
- Added collapse and tab event listeners so the tutorial resyncs after Bootstrap UI transitions.
- Added temporary resize and mutation observers while the tutorial is active so highlight placement tracks workspace layout changes.
- Added a regression test that verifies the reposition guards remain in place.

### Testing Approach

- Added a focused functional regression test for the workspace tutorial reposition safeguards.

## Validation

### Before

- Closing the document search panel could move the document view controls while the tutorial card and highlight remained in their previous position.

### After

- The workspace tutorial now recomputes its highlight and card placement after filter collapses, tab changes, and layout shifts, so the overlay stays aligned to the active control.