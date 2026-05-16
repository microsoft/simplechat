# Prompt Chat Buttons

## Overview

Prompt Chat buttons let users jump from workspace prompt management directly into Chats with the selected prompt already active. The behavior is available for personal, group, and public workspace prompts.

## Implemented In Version

Implemented in version: **0.241.032**

This feature uses the application version tracked in `application/single_app/config.py`.

## Dependencies

- Existing personal, group, and public prompt APIs
- Existing Chats prompt selector and prompt catalog injected by `route_frontend_chats.py`
- Bootstrap buttons, cards, and modals
- Existing workspace prompt list/card rendering

## Technical Specifications

### Architecture Overview

- Personal prompts build Chat links in `application/single_app/static/js/workspace/workspace-prompts.js`.
- Group prompts build scoped Chat links in `application/single_app/templates/group_workspaces.html` using the active group id.
- Public prompts build scoped Chat links in `application/single_app/static/js/public/public_workspace.js` using the active public workspace id.
- Chats consumes `prompt_id`, `prompt_scope`, and optional `prompt_scope_id`, `group_id`, or `workspace_id` query parameters in `application/single_app/static/js/chat/chat-onload.js`.
- Prompt selection is performed by `selectPromptById(...)` in `application/single_app/static/js/chat/chat-prompts.js`.

### Query Parameters

Prompt Chat links use these parameters:

- `prompt_id`: selected prompt id
- `prompt_scope`: `personal`, `group`, or `public`
- `prompt_scope_id`: group id or public workspace id when applicable
- `group_id`: group workspace id for group prompt links
- `workspace_id`: public workspace id for public prompt links
- `openPrompt=1`: indicates that the prompt picker should open on the Chats page

## Usage Instructions

1. Open a personal, group, or public workspace.
2. Go to the Prompts tab.
3. Select Chat from a prompt row, prompt card, or prompt details modal.
4. The Chats page opens with the prompt picker visible and the originating prompt selected.
5. Send the prompt as-is or add extra text before sending.

## Testing And Validation

### Test Coverage

- `ui_tests/test_workspace_workflow_prompt_ui_refresh.py` validates the personal prompt Chat button in list, card, and details modal surfaces and verifies the generated Chat URL contains the prompt selection parameters.
- `ui_tests/test_workspace_prompt_card_views.py` validates group and public prompt Chat buttons in list, card, and details modal surfaces.

### Validation Results

- JavaScript syntax checks cover the changed prompt, public workspace, and chat initialization modules.
- UI tests are included for the browser surfaces that expose the new prompt Chat action.

### Known Limitations

- Browser execution of the full Chats deep-link selection requires an authenticated Playwright storage state and a running SimpleChat instance with matching prompt catalog data.
