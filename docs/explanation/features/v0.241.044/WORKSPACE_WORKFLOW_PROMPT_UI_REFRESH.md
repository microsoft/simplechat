# Workspace Workflow And Prompt UI Refresh

Implemented in version: **0.241.044**

## Overview

The personal workspace now uses a more consistent action language across workflows, prompts, and agents. Workflows gained the same list or grid presentation pattern already used by agents and actions, workflow actions now use clearer button roles, prompts gained a read-only quick-view action, and agent chat actions now use the filled chat treatment used elsewhere in the app.

## Dependencies

- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/static/js/workspace/workspace-prompts.js`
- `application/single_app/static/js/workspace/workspace_agents.js`
- `application/single_app/static/js/workspace/view-utils.js`

## Technical Specifications

### Workflow workspace updates

- Removed the redundant workflows heading inside the tab while keeping the descriptive helper text.
- Moved the `New Workflow` button to the left side of the toolbar.
- Added list and grid view controls so workflows match the agents and actions presentation model.
- Refreshed workflow actions so `Run` is the filled primary action, `History` and `Activity` are labeled secondary actions, and `Edit` and `Delete` use icon-only controls.
- Added optimistic running-state rendering so the `Activity` button appears as soon as a workflow run enters the running state in the workspace UI.

### Prompt updates

- Replaced the prompt row's text-heavy action buttons with icon-only `View`, `Edit`, and `Delete` controls.
- Added a read-only prompt details view that opens in the shared item details modal using a smaller dialog size than the agent or action detail view.

### Agent updates

- Updated the personal workspace agent chat action to use the filled chat icon treatment so it matches the button language used elsewhere in the workspace.

## Usage Instructions

1. Open `Your Workflows` from the workspace sidebar.
2. Use the list or grid toggle in the workflow toolbar to switch layouts.
3. Run a workflow with the filled `Run` button, then open `Activity` or `History` from the same action group.
4. Open `Your Prompts` and use the eye button to preview a prompt without entering edit mode.

## Testing And Validation

- Added `functional_tests/test_workspace_workflow_prompt_ui_refresh.py` to verify the template and JavaScript contract for the refreshed workflows and prompts UI.
- Added `ui_tests/test_workspace_workflow_prompt_ui_refresh.py` to validate the refreshed workflow toolbar, workflow action buttons, workflow grid view, and prompt details modal in a browser workflow.
- The browser UI test requires `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` in an authenticated environment.
