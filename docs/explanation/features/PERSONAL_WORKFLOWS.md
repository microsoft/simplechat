# Personal Workflows

Implemented in version: **0.241.024**
Enhanced in versions: **0.241.029**, **0.241.033**, **0.241.034**, **0.241.035**, **0.241.036**

## Overview

Personal Workflows add a new workspace capability that lets a user save repeatable tasks and run them either manually or on an interval schedule. Each workflow can target either a personal or merged global agent, or run directly against the configured default model or a specific personal/global model endpoint.

Related version update:
- `application/single_app/config.py` now reports version `0.241.036`.

Dependencies:
- `application/single_app/functions_personal_workflows.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/background_tasks.py`
- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`

## Technical Specifications

Architecture overview:
- Workflow definitions are stored in the personal workflows Cosmos container.
- Workflow run history is stored in a dedicated personal workflow runs Cosmos container.
- The workspace UI exposes a new `Your Workflows` tab and a matching left-hand navigation entry.
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

Configuration options:
- Admins can enable or disable the feature with the `allow_user_workflows` setting in Personal Workspaces.
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
3. Enable `Allow User Workflows` under `Personal Workspaces`.

User workflow:
1. Open `Personal Workspace`.
2. Select `Your Workflows` from the left-hand workspace menu or the tab strip.
3. Choose `New Workflow`.
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

UI coverage:
- `ui_tests/test_workspace_workflows_tab.py` validates desktop and mobile rendering, workflow history modal behavior, and new workflow submission from the workspace modal.
- `ui_tests/test_workflow_priority_alert_modal.py` validates the global workflow alert modal and mark-read flow.

Performance and limitations:
- Phase 1 is limited to personal workflows only.
- Scheduling currently supports interval execution only; calendar-style recurrence is not included.
- Group workflows are intentionally deferred for a later phase.