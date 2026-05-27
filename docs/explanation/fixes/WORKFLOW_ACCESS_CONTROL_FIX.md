# Workflow Access Control Fix

Fixed in version: **0.241.106**

Related config.py version update: `application/single_app/config.py` was incremented to `0.241.106`.

## Issue Description

Personal workflows were exposed to any signed-in user whenever the workflow UI was present. The admin toggle existed in the settings page, but the setting was not persisted in the Admin Settings POST payload and there was no optional app role gate for organizations that need tighter workflow access control.

## Root Cause Analysis

- `allow_user_workflows` defaulted to enabled and several code paths treated a missing setting as enabled.
- Admin Settings rendered the workflow toggle but did not save it into the app settings document.
- Workflow routes only checked the global feature setting and did not evaluate a per-user role requirement.
- Workspace and chat templates rendered workflow affordances from the raw public setting instead of the effective user policy.

## Technical Details

Files modified:
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_frontend_workspace.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/background_tasks.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/chats.html`
- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/_sidebar_short_nav.html`
- `application/single_app/static/css/sidebar.css`
- `deployers/azurecli/appRegistrationRoles.json`
- `deployers/terraform/main.tf`
- `deployers/version.txt`

Code changes summary:
- Added shared `WorkflowUser` role detection and effective workflow access helpers.
- Added `workflow_user_required` and applied it to every personal workflow API route and the workflow activity page.
- Changed workflow defaults and missing-setting fallbacks to disabled unless explicitly enabled.
- Added a dedicated Admin Settings `Workflow` section with `Enable Personal Workflows` and `Require WorkflowUser App Role` toggles.
- Updated workspace/chat rendering to hide workflow controls when the current user lacks effective access.
- Added `WorkflowUser` to deployer app role definitions and bumped deployer version tracking.

## Validation

Test coverage:
- `functional_tests/test_workflow_access_controls.py`
- `functional_tests/test_personal_workflows_feature.py`
- `ui_tests/test_admin_workflow_settings_access.py`

Before the fix, users could see and call workflow endpoints whenever the feature surface was available. After the fix, personal workflows must be explicitly enabled and, when configured, require the `WorkflowUser` Enterprise App role at both UI and API boundaries.