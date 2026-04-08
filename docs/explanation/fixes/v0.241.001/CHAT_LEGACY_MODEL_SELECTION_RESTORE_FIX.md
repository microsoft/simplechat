# Chat Legacy Model Selection Restore Fix

Fixed/Implemented in version: **0.240.010**

## Issue Description

The chats page could save a user's preferred legacy GPT deployment to user settings, but returning to the chats page reset the visible model selector back to the first configured model instead of restoring the saved selection.

## Root Cause Analysis

- The chat startup flow still loaded `preferredModelDeployment` from user settings and passed it into the shared model selector.
- The shared selector returned early whenever multi-endpoint mode was disabled.
- That early return refreshed the searchable selector UI without first applying the saved legacy deployment value to the hidden `#model-select` element.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-model-selector.js`
- `functional_tests/test_reasoning_effort_initial_sync.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a legacy-only restore helper in the shared chat model selector to apply `preferredModelDeployment` before refreshing the searchable selector UI.
- Left the multi-endpoint selection-key logic unchanged.
- Updated the focused startup regression test to verify the shared selector now restores legacy deployments before reasoning initialization.

### Testing Approach

- Functional regression: `functional_tests/test_reasoning_effort_initial_sync.py`

## Validation

### Before

- Legacy chats saved the preferred deployment successfully.
- Reloading or returning to the chats page showed the first configured model instead of the saved one.

### After

- Legacy chats restore the saved preferred deployment through the shared selector logic before the selector UI refreshes.
- The multi-endpoint restore path remains untouched.