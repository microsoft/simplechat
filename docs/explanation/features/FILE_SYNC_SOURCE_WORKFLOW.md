# File Sync Source Workflow

Implemented in version: **0.241.073**
Azure Files source support implemented in: **0.241.127**
OneDrive source support and selected-path workflow implemented in: **0.241.128**
Global cloud drive connector identities implemented in: **0.241.129**
Cloud connector admin visibility limited in: **0.241.178**

Fixed/Implemented in version: **0.241.178**

## Overview

File Sync source creation and editing uses a modal workflow instead of an inline form. The first step selects the source type, and the second step configures the selected source. Admins can choose whether SMB Share and Azure Files source types are visible in the workflow. OneDrive, SharePoint, and Google Workspace controls remain visible in Admin Settings as coming soon while validation continues.

## Dependencies

- File Sync must be enabled for the current workspace scope.
- Redis Cache must be configured before sync runs are effective.
- SMB sources require the existing `smbprotocol` dependency.
- Azure Files sources require the `azure-storage-file-share` dependency.
- OneDrive source code remains in place for future validation and requires a global File Sync identity with Microsoft Graph application permissions when re-enabled.
- Version was updated in `application/single_app/config.py` to `0.241.178` for the cloud connector admin visibility pause.

## Technical Specifications

- `workspace-file-sync.js` now renders a Bootstrap modal for add and edit source flows.
- The workflow includes a Source Type step and a Configure step.
- Admin Settings includes active `file_sync_visible_source_types` controls for SMB Share and Azure Files. OneDrive, On-prem SharePoint, and Google Workspace are disabled coming-soon controls and are not submitted with the admin settings form.
- The source list table includes a Type column populated from each source's `source_type` field.
- SMB payloads submit `source_type: "smb"`; Azure Files payloads submit `source_type: "azure_files"` with file service URL, share name, and optional directory path fields. OneDrive payload code remains in place but is not admin-enabled while the connector is paused.
- The Configure step includes selected folders/files, Include subfolders, path patterns, file type filters, folder-derived tag behavior, and remote delete policy in a single selection and filters section.
- Source browse APIs let the modal inspect provider folders and files before saving, then store selected paths in the source connection.
- Cloud connector options are shown as coming soon in Admin Settings and are filtered out by server-side source visibility normalization even if submitted manually.
- New source creation and unsaved connection tests reject source types hidden by the admin setting.

## File Structure

- `application/single_app/static/js/workspace/workspace-file-sync.js` - shared modal workflow, source type selection, source type table column, and source-specific configuration forms.
- `functional_tests/test_file_sync_onedrive_personal.py` - static coverage for OneDrive connector, selected paths, and browse route wiring.
- `functional_tests/test_file_sync_azure_files_identity.py` - static coverage for Azure Files connector and identity wiring.
- `functional_tests/test_file_sync_capability.py` - static coverage for workflow strings, source type payloads, and source type table wiring.
- `ui_tests/test_workspace_file_sync_ui.py` - workspace smoke coverage for the source workflow modal.
- `ui_tests/test_admin_file_sync_settings_ui.py` - admin-managed source workflow smoke coverage.

## Usage Instructions

Workspace managers click Add Source, choose SMB Share or Azure Files, and continue to Configure Source. Connection testing, selected folders/files, schedule settings, tag controls, recursive scanning, and remote-delete policy remain in the configuration step.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_capability.py`, `functional_tests/test_file_sync_azure_files_identity.py`, and `functional_tests/test_file_sync_onedrive_personal.py`.
- UI smoke coverage: `ui_tests/test_workspace_file_sync_ui.py` and `ui_tests/test_admin_file_sync_settings_ui.py`.
- JavaScript syntax coverage: `node --check application/single_app/static/js/workspace/workspace-file-sync.js`.

## Known Limitations

- OneDrive, On-prem SharePoint, and Google Workspace are temporarily unavailable from Admin Settings and are shown as coming soon.
- Existing OneDrive code remains in place for future validation before re-enabling the connector.