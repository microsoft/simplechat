# Microsoft Graph Pending Actions

Implemented in version: **0.241.179**

## Overview

Microsoft Graph mail sends and calendar invite creation can now run in three delivery modes: manual review, delayed send, or auto-send. Manual and delayed modes create a user-owned pending action so the chat and workflow activity views can show review controls, countdowns, consent prompts, and terminal status without exposing stored Graph request payloads to the browser.

The Microsoft Graph action configuration nests delivery options directly under the related capability. Enabling **Send mail** exposes the email delivery mode and delayed-send slider. Enabling **Create calendar invites** exposes the calendar invite delivery mode and delayed-send slider.

## Dependencies

- Microsoft Graph delegated permissions through the signed-in user.
- Cosmos DB container `msgraph_pending_actions`, partitioned by `/user_id`.
- Existing Microsoft Graph plugin configuration and agent citation flow.

## Technical Specifications

### Architecture

- `functions_msgraph_pending_actions.py` stores, sanitizes, approves, cancels, and auto-commits pending Microsoft Graph actions.
- `route_backend_msgraph_pending_actions.py` exposes user-scoped API routes for listing, status lookup, send-now, approve, and cancel operations.
- `semantic_kernel_plugins/msgraph_plugin.py` creates pending actions for manual or delayed mail/calendar operations and returns sanitized `pending_action` metadata in plugin results.
- `functions_workflow_activity.py` merges pending Microsoft Graph actions into workflow activity snapshots.
- `chat-messages.js` and `workflow-activity.js` render send/cancel controls and countdowns from sanitized pending action metadata.
- Consent or interactive-auth errors render a friendly Microsoft 365 grant-access card for Outlook email, Calendar, OneDrive, and SharePoint access. The card opens the generated Microsoft identity prompt in a popup, then offers a test-access button that verifies silent access after consent and clears the prompt.

### API Endpoints

- `GET /api/msgraph/pending-actions`
- `GET /api/msgraph/pending-actions/<action_id>`
- `POST /api/msgraph/pending-actions/<action_id>/approve`
- `POST /api/msgraph/pending-actions/<action_id>/send-now`
- `POST /api/msgraph/pending-actions/<action_id>/cancel`
- `POST /api/msgraph/test-access`

### Configuration

Microsoft Graph plugin settings support:

- `msgraph_mail_send_mode`: `draft_manual`, `draft_delayed`, or `auto_send`.
- `msgraph_mail_delay_seconds`: 5 to 600 seconds.
- `msgraph_calendar_send_mode`: `draft_manual`, `draft_delayed`, or `auto_send`.
- `msgraph_calendar_delay_seconds`: 5 to 600 seconds.

Calendar invite delivery defaults to `auto_send` to preserve existing behavior.

## Usage Instructions

Configure a Microsoft Graph action in the workspace action modal, enable the required mail or calendar capability, and choose the nested delivery mode. For delayed delivery, use the 5 to 600 second slider under the capability. When an agent uses manual or delayed delivery, the chat response shows a pending action card. Workflow activity also shows a Microsoft 365 activity row for the pending mail or calendar action.

Delayed actions show a countdown and can be sent immediately or cancelled before the timer completes. Manual actions wait for the user to send or cancel them.

## Testing and Validation

- `functional_tests/test_msgraph_plugin_operations.py` validates plugin-level pending mail behavior.
- `functional_tests/test_msgraph_pending_actions.py` validates helper-layer send, cancel, sanitization, and filtering behavior.
- `functional_tests/test_msgraph_access_test_route.py` validates post-consent access checks and unsupported scope rejection.
- `functional_tests/test_workflow_activity_view_feature.py` validates workflow activity snapshot rows for pending Graph actions.
- `ui_tests/test_workspace_msgraph_action_modal.py` validates the Microsoft Graph modal nested mail/calendar delivery sliders when Playwright is available.
- `ui_tests/test_chat_inline_export_action_buttons.py` validates that Graph pending and Microsoft 365 consent contexts suppress the generic local email button.

Known limitations:

- Delayed auto-send uses an in-process timer with the current delegated token for the configured 5 to 600 second window. A future durable scheduler would be needed for restart-proof delayed delivery.
- Workflow activity now shows and controls pending Graph actions, but the workflow runner is not yet a durable resumable dependency graph. A future workflow orchestration change would be needed to pause and resume dependent branches while allowing independent branches to continue.
