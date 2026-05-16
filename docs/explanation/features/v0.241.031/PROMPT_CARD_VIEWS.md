# Prompt Card Views

## Overview

Prompt card views add a card/list display switcher to prompt tabs across personal, group, and public workspaces. The card layout gives prompts the same scannable treatment already used by workspace documents while keeping the existing table/list workflow available.

## Implemented In Version

Implemented in version: **0.241.031**

This feature uses the application version tracked in `application/single_app/config.py`.

## Dependencies

- Bootstrap 5 tabs, buttons, cards, dropdowns, and modals
- Bootstrap Icons for list, card, prompt, run, activity, history, edit, and delete actions
- Existing prompt APIs for personal, group, and public workspace scopes
- Existing shared personal workspace modal helper for personal prompt quick view

## Technical Specifications

### Architecture Overview

- Personal prompt list/card switching is handled in `application/single_app/static/js/workspace/workspace-prompts.js` using the shared workspace view helper pattern.
- Group prompt cards are rendered by inline group workspace JavaScript in `application/single_app/templates/group_workspaces.html` because that page owns its prompt UI locally.
- Public prompt cards are rendered by `application/single_app/static/js/public/public_workspace.js` and use a dedicated public prompt details modal.
- Shared prompt card sizing and preview styles live in `application/single_app/static/css/workspace-responsive.css`.

### User Interface Behavior

- Prompt tabs now expose list and card toggle controls in personal, group, and public workspaces.
- Prompt cards show prompt name, a short content preview, and action buttons.
- Clicking a prompt card body opens prompt details.
- Prompt action buttons stop card-click propagation so view, edit, and delete commands remain explicit.
- Workflow cards now open the edit modal when the card body is clicked or activated from the keyboard.
- Workflow cards show Run and Activity as primary actions, with Run, Activity, History, Edit, and Delete in a three-dot overflow menu.

### API Endpoints

The feature uses existing endpoints:

- `GET /api/prompts`
- `GET /api/prompts/<prompt_id>`
- `GET /api/group_prompts`
- `GET /api/group_prompts/<prompt_id>`
- `GET /api/public_prompts`
- `GET /api/public_prompts/<prompt_id>`

## Usage Instructions

1. Open a personal, group, or public workspace.
2. Select the Prompts tab.
3. Use the list/card toggle to switch views.
4. Click a prompt card body to inspect the prompt details.
5. Use the card action buttons to view, edit, or delete prompts when permitted by the current workspace role.
6. In personal Workflows, switch to card view, click a workflow card body to edit it, or use the visible Run/Activity buttons and overflow menu for other actions.

## Testing And Validation

### Test Coverage

- `ui_tests/test_workspace_workflow_prompt_ui_refresh.py` validates personal prompt card rendering, prompt quick view, workflow card primary actions, the workflow overflow menu, and card-click edit behavior.
- `ui_tests/test_workspace_prompt_card_views.py` validates group and public prompt card rendering plus card-open prompt detail behavior.

### Validation Results

- JavaScript syntax checks passed for updated personal prompt, personal workflow, and public workspace scripts.
- Python compile checks passed for updated UI tests.
- Targeted UI tests were executed and skipped because `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` were not configured in the local environment.

### Known Limitations

- Browser-level visual validation requires an authenticated Playwright storage state and a running SimpleChat instance.
- Group prompt rendering remains inline with the existing group workspace template architecture.
