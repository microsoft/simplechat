# Group Workflows

Implemented in version: **0.241.179**
Enhanced in version: **0.241.193** for configurable workflow agent action limits.
Enhanced in version: **0.241.194** with admin capacity guidance for high action limits.

Fixed/Implemented in version: **0.241.193**

Related version updates:
- `application/single_app/config.py` reported version `0.241.179` when group workflows were implemented.
- `application/single_app/config.py` reported version `0.241.193` for workflow action limit configuration.
- `application/single_app/config.py` now reports version `0.241.194` for workflow action limit capacity guidance.

## Overview

Group Workflows extend the existing personal workflow system to group workspaces. A permitted group member can save repeatable tasks, run them manually, run them on an interval schedule, or trigger them after group File Sync changes.

Dependencies:
- `application/single_app/functions_group_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/functions_settings.py`
- `application/single_app/background_tasks.py`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/static/js/workflow/workflow-activity.js`

## Technical Specifications

Architecture overview:
- Group workflow definitions are stored in the `group_workflows` Cosmos container partitioned by `group_id`.
- Group workflow run history is stored in the `group_workflow_runs` Cosmos container partitioned by `group_id`.
- Per-document run items are stored in the `group_workflow_run_items` Cosmos container partitioned by `run_id`.
- The existing workflow runner is scope-aware and handles personal and group workflow execution through shared logic.
- Group workflow conversations are created as hidden group conversations with `workspace_type='group'` and the active `group_id`.
- Scheduled group workflows are picked up by the background scheduler through `get_due_group_workflows()` and assignment gating.

API endpoints:
- `GET /api/group/workflows`
- `POST /api/group/workflows`
- `GET /api/group/workflows/agents`
- `GET /api/group/workflows/file-sync-sources`
- `GET /api/group/workflows/<workflow_id>/runs`
- `POST /api/group/workflows/<workflow_id>/run`
- `POST /api/group/workflows/<workflow_id>/runs/<run_id>/resume-failed`
- `DELETE /api/group/workflows/<workflow_id>`
- `GET /api/group/workflows/activity`
- `GET /api/group/workflows/activity/stream`

Configuration options:
- `allow_group_workflows` enables the group workflow feature.
- `require_group_assignment_for_group_workflows` limits use to groups selected in the Admin Settings assignment modal.
- `group_workflow_allowed_group_ids` stores the assigned group IDs.
- `require_owner_for_group_agent_management` is now labeled as `Require Owner to Manage Group Agents, Actions and Workflows` and also governs group workflow authoring roles.
- `enable_file_sync_group` gates group File Sync sources for workflow pre-run sync and File Sync monitor triggers.
- `workflow_max_auto_invoke_attempts` controls the maximum automatic tool or action calls an agent can make during one workflow run and defaults to `60`.
- Values above `100` should be treated as capacity-sensitive. Admins should enable Cosmos DB Throughput automation in SimpleChat so the app can monitor RU pressure and scale up Cosmos when needed, while also watching Azure OpenAI throttling, App Service CPU and memory, and downstream service latency.

Permission model:
- Runtime access is allowed for group Owners, Admins, Document Managers, and Users when the group workflow feature is enabled for that group.
- Authoring and deletion are allowed for Owners and Admins by default.
- When owner-only management is enabled, only Owners can create, update, or delete group workflows.
- All group workflow API routes revalidate group membership and feature assignment before reading or mutating data.

File Sync behavior:
- Group workflows accept only group-scoped File Sync sources for the active group.
- File Sync-triggered group workflows reuse the personal workflow run-item tracking and resume-failed behavior.
- Changed files can be used as dynamic Analyze targets when the workflow File Sync configuration allows it.

## Usage Instructions

How to enable/configure:
1. Open Admin Settings.
2. Go to the Workspaces tab.
3. Open the Workflow section.
4. Enable `Enable Group Workflows`.
5. Optionally enable `Require Group Assignment to Use Workflow` and choose groups with `Manage Groups`.
6. Set `Workflow Agent Action Limit` when large group workflows need more than the default 60 automatic tool or action calls. For values above 100, enable Cosmos DB Throughput automation in SimpleChat and monitor service capacity.
7. Optionally enable `Require Owner to Manage Group Agents, Actions and Workflows` to limit workflow authoring to group Owners.

Group workflow:
1. Open Group Workspaces.
2. Select an active group.
3. Open `Group Workflows`.
4. Choose `New Group Workflow`.
5. Enter a name, description, task prompt, runner, document action, alert priority, and trigger.
6. Save and run the workflow manually, or let the scheduler run interval and File Sync monitor workflows.

Integration points:
- Group agents and merged global agents are available in the group workflow agent picker.
- Group model endpoints and merged global endpoints are available for direct model workflows.
- Group workflow activity links open the shared workflow activity page with `scope=group` and `group_id` context.

## Testing And Validation

Functional coverage:
- `functional_tests/test_group_workflows_feature.py` verifies static contracts for storage, settings, routes, scheduler, runner scope, activity deep links, admin UI settings, and group workspace UI wiring.
- `functional_tests/test_workflow_auto_invoke_attempt_settings.py` verifies workflow action limit defaults, admin save wiring, Semantic Kernel loader wiring, and workflow runner scoping.

UI coverage:
- `ui_tests/test_admin_workflow_settings_access.py` verifies the Admin Settings workflow section exposes the group workflow enablement, assignment, owner-only management controls, and workflow action limit control.

Performance and limitations:
- Group workflow runtime uses the same scheduler polling cadence and runner path as personal workflows.
- Group workflow activity pages require the user to remain a member of the referenced group.
- Group File Sync sources are available only when group File Sync is enabled for the active group.