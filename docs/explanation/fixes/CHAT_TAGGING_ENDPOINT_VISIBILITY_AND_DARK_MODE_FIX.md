# Chat Tagging Endpoint Visibility And Dark Mode Fix

Fixed/Implemented in version: **0.239.167**

## Issue Description

Three related UI regressions needed correction:

- Unsupported `new_foundry` model endpoints were still visible in user-facing multi-endpoint flows.
- Personal conversations displayed visible tags, while group conversation labels were inconsistent between the active header and sidebar, and some group-agent conversations failed to surface a group tag.
- The upload user agreement content became unreadable in dark mode because its light background styling bypassed the shared dark-mode override.

## Root Cause Analysis

- Frontend endpoint sanitization removed secrets but did not filter unsupported providers before rendering workspace, group, and chat endpoint views.
- Endpoint saves merged only the visible payload, so hiding unsupported providers on read alone would have risked deleting previously stored hidden endpoints.
- The streaming chat path saved conversation metadata without the selected agent details, which prevented group-agent conversations from consistently preserving primary group context.
- The sidebar conversation renderer emitted visible `personal` badges and hard-coded `group` text instead of using the group name.
- The active conversation header and details formatter shortened group labels when the full group name should have been shown in the primary chat view.
- The upload agreement modal used an inline `background-color: var(--bs-light)` style, which bypassed the existing `[data-bs-theme="dark"] .bg-light` override.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/templates/_multiendpoint_modal.html`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/route_backend_chats.py`
- `application/single_app/templates/base.html`
- `application/single_app/config.py`
- `functional_tests/test_chat_tagging_and_endpoint_provider_visibility.py`
- `ui_tests/test_model_endpoint_request_uses_endpoint_id.py`
- `ui_tests/test_upload_agreement_dark_mode.py`

### Code Changes Summary

- Added shared provider visibility filtering so only `aoai` and `aifoundry` are exposed in frontend endpoint payloads.
- Preserved stored hidden endpoints during merge/save flows so unsupported `new_foundry` entries remain in data even though they are no longer shown in the UI.
- Removed the New Foundry option from the multi-endpoint provider selector and added APIM provider guidance under the field.
- Updated conversation tag rendering so personal conversations show no visible badge, the active conversation header shows the full group name, and the sidebar shows a short group tag using the first 8 characters of the group name.
- Updated the conversation details formatter to show the full group name.
- Fixed the streaming chat path to pass selected agent metadata into conversation metadata collection so group-agent conversations retain group context.
- Swapped the upload agreement content container to the shared `bg-light` class so the existing dark-mode override applies.

### Testing Approach

- Functional regression: `functional_tests/test_chat_tagging_and_endpoint_provider_visibility.py`
- UI regression: `ui_tests/test_model_endpoint_request_uses_endpoint_id.py`
- UI regression: `ui_tests/test_upload_agreement_dark_mode.py`

## Validation

### Before

- Users could still see unsupported New Foundry endpoint options in user-facing multi-endpoint workflows.
- Personal conversations displayed visible `personal` badges in the sidebar.
- Group conversations showed inconsistent labels between the active header and the sidebar.
- Group-agent conversations could lose their group tag when saved through the streaming path.
- The upload agreement content could render as light text on a light surface in dark mode.

### After

- Only Azure OpenAI and Foundry (classic) are exposed in the visible multi-endpoint provider UI.
- Existing hidden unsupported endpoints are preserved in storage.
- Personal conversations no longer render a visible tag.
- The active conversation header and details view show the full group name.
- Sidebar group conversations render a short badge using the first 8 characters of the group name.
- Streaming group-agent conversations retain group metadata for tag display and related filtering.
- The upload agreement content uses the shared dark-mode-safe light surface styling.