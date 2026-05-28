# Chat File Upload Access Control

## Overview

Chat file uploads can now be enabled or disabled independently from workspace document uploads. Admins can also require the `ChatFileUploadUser` Enterprise App role before users can upload files directly into chat conversations.

Version implemented: **0.241.098**

Implemented in version: **0.241.098**

Related config.py version update: `application/single_app/config.py` was incremented to `0.241.098`.

## Dependencies

- Entra Enterprise App role value: `ChatFileUploadUser`
- App settings: `enable_chat_file_uploads` and `require_member_of_chat_file_upload_user`
- Existing chat upload route: `POST /upload`
- Existing per-user file upload restrictions still apply through `file_upload_required`

## Technical Specifications

### Architecture

- `enable_chat_file_uploads` globally controls new files uploaded directly into chat.
- `require_member_of_chat_file_upload_user` optionally requires the authenticated session role claim to include `ChatFileUploadUser`.
- The chat page receives an effective `enable_chat_file_uploads` value after evaluating global enablement and the current user's role claims.
- The chat template serializes that effective value to `window.appSettings.enable_chat_file_uploads` so selected, pasted, and dropped files use the same client-side gate.
- The frontend hides the paperclip controls when the effective setting is disabled and guards paste/drag-and-drop upload flows.
- The backend rejects unauthorized `POST /upload` requests before processing or storing the uploaded file.

### API Endpoints

- `POST /upload` returns `403` when chat file uploads are globally disabled.
- `POST /upload` returns `403` when the app role requirement is enabled and the current user does not have `ChatFileUploadUser`.

### Configuration Options

- `enable_chat_file_uploads`: Enables or disables new chat file uploads across personal, group, and multi-user chat surfaces.
- `require_member_of_chat_file_upload_user`: Requires the `ChatFileUploadUser` Enterprise App role when enabled.

### File Structure

- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-input-actions.js`
- `deployers/azurecli/appRegistrationRoles.json`
- `deployers/terraform/main.tf`

## Usage Instructions

1. Open Admin Settings.
2. Open the Workspaces tab.
3. Use Chat File Uploads to enable or disable new chat uploads.
4. Optionally turn on Require ChatFileUploadUser App Role.
5. Assign the `ChatFileUploadUser` Enterprise App role to users or groups that should upload files into chat.

Existing chat attachments remain visible after the feature is disabled. Workspace document uploads, file sync, and generated artifacts remain governed by their own existing controls.

## Testing and Validation

Functional coverage: `functional_tests/test_chat_file_upload_access_control.py` validates settings defaults, admin persistence, backend enforcement, UI gating snippets, deployment role definitions, documentation, and version tracking.

UI coverage: `ui_tests/test_chat_file_upload_access_control.py` validates that the chat toolbar file controls match the effective server-rendered setting for the authenticated test user.

Related fix: `docs/explanation/fixes/CHAT_FILE_UPLOAD_CLIENT_FLAG_FIX.md` documents the client app settings serialization regression fixed in version `0.241.110`.

Known limitation: Users must refresh their sign-in token after role assignment changes before the new `ChatFileUploadUser` claim appears in the session.