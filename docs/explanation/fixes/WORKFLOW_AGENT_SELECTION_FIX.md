# Workflow Agent Selection Fix (v0.241.024)

Fixed/Implemented in version: **0.241.024**

## Issue Summary

The Personal Workflows modal could show `No agents available` even when the user already had personal agents available in the workspace.

## Root Cause

- The workflow modal expected `/api/user/agents` to return a wrapped payload shaped like `{ "agents": [...] }`.
- The existing user-agents API returns a bare JSON array instead.
- The modal also cached failed or empty agent loads for the rest of the page session, so a temporary failure or earlier empty response could persist until a full page refresh.

## Files Modified

- `application/single_app/static/js/workspace/workspace_workflows.js`
- `ui_tests/test_workspace_workflows_tab.py`
- `functional_tests/test_workflow_agent_selection_fix.py`
- `application/single_app/config.py`

## Code Changes Summary

1. Updated workflow agent loading to accept both a bare array response and a wrapped `agents` response.
2. Changed failed agent loads to remain retryable instead of permanently caching an empty result.
3. Forced the workflow modal to refresh the agent list whenever it opens.
4. Updated the workflow UI test stub to use the real bare-array user agents response shape.

## Validation

- Added `functional_tests/test_workflow_agent_selection_fix.py` to verify the response-shape handling and modal refresh behavior.
- Updated `ui_tests/test_workspace_workflows_tab.py` so the workflow modal regression test reflects the actual `/api/user/agents` payload format.

## Impact

- Users with existing personal agents can now select them while creating or editing workflows.
- Reopening the workflow modal after a transient load failure or after creating agents on the same page can repopulate the dropdown without requiring a full reload.