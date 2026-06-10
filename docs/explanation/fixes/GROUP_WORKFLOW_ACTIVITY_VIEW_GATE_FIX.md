# Group Workflow Activity View Gate Fix

Fixed/Implemented in version: **0.241.179**

Related version update:
- `application/single_app/config.py` reports version `0.241.179` for this fix.

## Issue Description

Group workflow activity links opened the shared `/workflow-activity` page with `scope=group`, but the frontend route was still protected by the personal workflow feature gate. When personal workflows were disabled, the page returned an error before the group workflow activity API could load.

## Root Cause Analysis

The workflow activity page is shared by personal and group workflows, but its Flask route used `@enabled_required('allow_user_workflows')` and `@workflow_user_required`. Those decorators are correct for personal workflow pages and APIs, but they blocked group workflow activity views even when group workflows were enabled and the user had valid group access.

## Technical Details

Files modified:
- `application/single_app/route_frontend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_group_workflow_activity_view_gate.py`
- `functional_tests/test_group_workflows_feature.py`
- `docs/explanation/features/GROUP_WORKFLOWS.md`
- `docs/explanation/features/PERSONAL_WORKFLOWS.md`
- `ui_tests/test_admin_workflow_settings_access.py`

Code changes summary:
- Replaced the personal-only decorators on `/workflow-activity` with scope-aware route authorization.
- Preserved personal workflow checks for personal activity links.
- Added group workflow checks for group activity links, including group workspaces enabled, group workflows enabled, group assignment gating, and current membership validation.
- Kept the group activity API path isolated through `/api/group/workflows/activity` and `/api/group/workflows/activity/stream`.

Testing approach:
- Added `functional_tests/test_group_workflow_activity_view_gate.py` to assert the shared activity page route no longer depends on the personal workflow decorators for group scope.
- Updated `functional_tests/test_group_workflows_feature.py` version assertions to the current app version.

## Validation

Before:
- Group workflow activity links could fail with `Allow User Workflows is disabled.` when personal workflows were disabled.

After:
- Group workflow activity links render the shared activity page under group-specific authorization and then load group activity data from group workflow APIs.
- Personal workflow activity links still require personal workflows and the WorkflowUser role policy when configured.