# Workflow Activity Current Tab Navigation Fix

Fixed in version: **0.241.189**

Related version update:
- `application/single_app/config.py` reports version `0.241.189`.

## Issue Description

Clicking the workflow `Activity` button could open the activity view in a new tab and also navigate the current workspace tab to the same activity view. Users lost the workflow list context even though the action was intended to preserve it.

## Root Cause Analysis

The workflow Activity click handler called `window.open(activityState.url, "_blank", "noopener")` and then used `window.location.href = activityState.url` when the returned window handle was falsy. Some browsers can return a null handle when `noopener` is used even though the new tab opens successfully. That made the fallback run and changed the current tab too.

## Technical Details

Files modified:
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/config.py`
- `functional_tests/test_workflow_activity_new_tab_navigation.py`
- `ui_tests/test_workspace_workflows_tab.py`

Code changes summary:
- Activity opens `about:blank` synchronously in a new tab.
- The new tab clears `opener` and then navigates to the workflow activity URL.
- The current-tab `window.location.href` fallback was removed.
- If pop-ups are blocked, the UI shows a warning toast instead of navigating the current workspace tab.

Testing approach:
- Added a focused functional contract test that rejects `window.location.href = activityState.url` in the workflow Activity handler.
- Extended the personal workflows UI test to assert the Activity action opens a new tab while the original page remains on the workspace URL.

## Validation

Before:
- Activity could open `/workflow-activity` in both a new tab and the current workspace tab.

After:
- Activity opens only in a new tab.
- Current workspace context remains unchanged.
- Blocked pop-ups show an actionable warning toast.

User experience improvement:
- Users can inspect workflow activity while keeping the workflow list available in the original tab.
