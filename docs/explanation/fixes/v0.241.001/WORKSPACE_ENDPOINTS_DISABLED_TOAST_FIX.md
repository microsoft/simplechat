# WORKSPACE_ENDPOINTS_DISABLED_TOAST_FIX

Fixed in version: **0.240.005**

## Issue Description

The personal and group workspace pages always loaded the endpoint-management JavaScript module, even when custom endpoints or multi-endpoint support were intentionally disabled by the administrator.

## Root Cause Analysis

The endpoints tab markup was correctly gated in the templates, but the shared workspace endpoint module was still included unconditionally in the page scripts. That module immediately called the disabled endpoint API and surfaced the backend `Allow User Custom Endpoints is disabled.` error as a toast.

## Technical Details

Files modified:

- `application/single_app/static/js/workspace/workspace_model_endpoints.js`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_workspace_endpoint_disabled_state_quiet.py`
- `ui_tests/test_workspace_page_endpoint_disabled_quiet.py`

Code changes summary:

- Added a DOM guard so the workspace endpoint module skips initialization when the endpoints UI is not rendered.
- Added disabled-feature detection so a stale or race-condition `custom endpoints is disabled` response is handled quietly instead of showing a user-facing error toast.
- Gated the workspace and group endpoint module include behind the same template conditions that render the endpoints tabs.

Testing approach:

- Added a functional regression test that verifies the JS guard and template gating.
- Added a UI regression test that confirms the workspace page does not request the disabled endpoints API or emit the disabled-feature error when the tab is absent.

## Validation

Before:

- Workspace pages without endpoint management still requested `/api/user/model-endpoints`.
- Users saw a red toast saying custom endpoints were disabled, even though the feature was intentionally off.

After:

- The endpoint module only initializes when the endpoints UI is present.
- Disabled configurations stay quiet and do not show the endpoint error toast to end users.