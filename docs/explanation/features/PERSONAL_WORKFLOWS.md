# Personal Workflows

Implemented in version: **0.241.024**
Enhanced in versions: **0.241.029**, **0.241.033**, **0.241.034**, **0.241.035**, **0.241.036**, **0.241.106**, **0.241.179**, **0.241.193**, **0.241.194**

Implemented in version: **0.241.106** for workflow access governance.

## Overview

Personal Workflows add an optional workspace capability that lets a user save repeatable tasks and run them either manually or on an interval schedule. Each workflow can target either a personal or merged global agent, or run directly against the configured default model or a specific personal/global model endpoint.

Fixed/Implemented in version: **0.241.193** for configurable workflow agent action limits.
Enhanced in version: **0.241.194** with admin capacity guidance for high action limits.

Related version updates:
- `application/single_app/config.py` reported version `0.241.106` for workflow access governance.
- `application/single_app/config.py` reported version `0.241.193` for workflow action limit configuration.
- `application/single_app/config.py` now reports version `0.241.194` for workflow action limit capacity guidance.

Dependencies:
- `application/single_app/functions_personal_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/functions_settings.py`
- `application/single_app/background_tasks.py`
- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `deployers/azurecli/appRegistrationRoles.json`
- `deployers/terraform/main.tf`

## Technical Specifications

Architecture overview:
- Workflow definitions are stored in the personal workflows Cosmos container.
- Workflow run history is stored in a dedicated personal workflow runs Cosmos container.
- The workspace UI exposes a `Personal Workflows` tab and a matching workspace section entry.
- Scheduled workflows are processed by the background task scheduler through a dedicated polling loop.
- Each run writes into a dedicated workflow conversation so users can review accumulated prompts and responses later.

Runtime behavior:
- Trigger types supported in this first phase: `manual` and `interval`.
- Interval units supported: `seconds`, `minutes`, and `hours`.
- Runner types supported: `agent` and `model`.
- Model workflows can use the default app model or an explicit enabled endpoint/model pair.
- Agent workflows validate that the selected agent is still available for the user at save time.
- Workflow conversations stay in the same personal conversations container and are split into a dedicated `Workflows` section in the chat sidebar by `chat_type='workflow'`.
- The standard `Conversations` section excludes workflow chats, while the `Workflows` section shows five items by default and can expand to reveal the rest.
- The `Workflows` section now mirrors the main sidebar behavior with the same header styling as `Conversations`, no extra divider, and its own scrollable list body.
- Workflow run history now includes direct links to the dedicated workflow conversation for the overall workflow and for each individual run event.
- Workflow UI and API access are hidden or blocked unless the effective user policy allows personal workflows.
- Admins can optionally require the `WorkflowUser` Enterprise App role before a user can open, create, update, delete, run, or inspect personal workflows.

Configuration options:
- Admins can enable or disable the feature with the `allow_user_workflows` setting in the Admin Settings `Workflow` section.
- `allow_user_workflows` defaults to `False` so new deployments must explicitly enable personal workflows.
- `require_member_of_workflow_user` defaults to `False`; when enabled, the signed-in user's role claims must include `WorkflowUser`.
- `workflow_max_auto_invoke_attempts` defaults to `60` and can be raised in Admin Settings for large workflow runs that need more agent tool or action calls.
- Values above `100` should be treated as capacity-sensitive. Admins should enable Cosmos DB Throughput automation in SimpleChat so the app can monitor RU pressure and scale up Cosmos when needed, while also watching Azure OpenAI throttling, App Service CPU and memory, and downstream service latency.
- Scheduled workflows can be paused without deleting the workflow definition.
- Users can assign a workflow alert priority of `high`, `medium`, `low`, or `none` for global pop-up notifications after each run.
- Users can create, edit, delete, manually run, and inspect run history from the workspace tab.

File structure:
- Backend storage and validation: `application/single_app/functions_personal_workflows.py`
- Workflow execution: `application/single_app/functions_workflow_runner.py`
- API routes: `application/single_app/route_backend_workflows.py`
- Scheduler polling: `application/single_app/background_tasks.py`
- Workspace UI: `application/single_app/templates/workspace.html`
- Browser behavior: `application/single_app/static/js/workspace/workspace_workflows.js`

## Usage Instructions

How to enable/configure:
1. Open Admin Settings.
2. Go to the `Workspaces` tab.
3. Open the `Workflow` section.
4. Enable `Enable Personal Workflows`.
5. Set `Workflow Agent Action Limit` when large workflows need more than the default 60 automatic tool or action calls. For values above 100, enable Cosmos DB Throughput automation in SimpleChat and monitor service capacity.
6. Optionally enable `Require WorkflowUser App Role` and assign `WorkflowUser` in the Enterprise App.

User workflow:
1. Open `Personal Workspace`.
2. Select `Personal Workflows` from the workspace section menu or the tab strip.
3. Choose `New Personal Workflow`.
4. Enter a name, optional description, and task prompt.
5. Pick either an agent runner or a model runner.
6. Choose a workflow alert priority when you want the run to generate a global pop-up alert modal.
7. Choose `Manual` or `Interval Schedule` and configure the interval when needed.
8. Save the workflow and use `Run` to trigger it immediately or let the scheduler pick it up.

Integration points:
- Manual runs call `POST /api/user/workflows/<workflow_id>/run`.
- Run history is read from `GET /api/user/workflows/<workflow_id>/runs`.
- Scheduler execution uses the same runner path as manual execution.

## Testing And Validation

Functional coverage:
- `functional_tests/test_personal_workflows_feature.py` verifies backend wiring, scheduler integration, workspace UI references, and admin toggle presence.
- `functional_tests/test_workflow_access_controls.py` verifies workflow defaults, role helpers, route decorators, UI gating snippets, app role deployment definitions, and documentation.
- `functional_tests/test_workflow_auto_invoke_attempt_settings.py` verifies workflow action limit defaults, admin save wiring, Semantic Kernel loader wiring, and workflow runner scoping.

UI coverage:
- `ui_tests/test_workspace_workflows_tab.py` validates desktop and mobile rendering, workflow history modal behavior, and new workflow submission from the workspace modal.
- `ui_tests/test_workflow_priority_alert_modal.py` validates the global workflow alert modal and mark-read flow.
- `ui_tests/test_admin_workflow_settings_access.py` validates the Admin Settings workflow action limit control.

Performance and limitations:
- Group workflow support is available separately through the `Group Workflows` feature.
- Scheduling currently supports interval execution only; calendar-style recurrence is not included.
- Personal workflow configuration and execution remain user-scoped even when group workflows are enabled.
- Users must sign out and back in after app role assignment changes so the `WorkflowUser` claim appears in their session.