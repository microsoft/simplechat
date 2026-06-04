# File Sync Source Workflow

Implemented in version: **0.241.073**
Azure Files source support implemented in: **0.241.127**
OneDrive source support and selected-path workflow implemented in: **0.241.128**
Global cloud drive connector identities implemented in: **0.241.129**

Fixed/Implemented in version: **0.241.073**

## Overview

File Sync source creation and editing uses a modal workflow instead of an inline form. The first step selects the source type, and the second step configures the selected source. Admins can choose which source types are visible in the workflow. SMB, Azure Files, and personal OneDrive are enabled connectors, while the workflow leaves room for future source types such as on-prem SharePoint and Google Workspace.

## Dependencies

- File Sync must be enabled for the current workspace scope.
- Redis Cache must be configured before sync runs are effective.
- SMB sources require the existing `smbprotocol` dependency.
- Azure Files sources require the `azure-storage-file-share` dependency.
- OneDrive sources require a global File Sync identity with Microsoft Graph application permissions.
- Version was updated in `application/single_app/config.py` to `0.241.129` for global cloud drive connector identity management.

## Technical Specifications

- `workspace-file-sync.js` now renders a Bootstrap modal for add and edit source flows.
- The workflow includes a Source Type step and a Configure step.
- Admin Settings includes `file_sync_visible_source_types` controls for SMB Share, Azure Files, OneDrive, On-prem SharePoint, and Google Workspace visibility.
- The source list table includes a Type column populated from each source's `source_type` field.
- SMB payloads submit `source_type: "smb"`; Azure Files payloads submit `source_type: "azure_files"` with file service URL, share name, and optional directory path fields; OneDrive payloads submit `source_type: "onedrive"` for personal workspaces only.
- The Configure step includes selected folders/files, Include subfolders, path patterns, file type filters, folder-derived tag behavior, and remote delete policy in a single selection and filters section.
- Source browse APIs let the modal inspect provider folders and files before saving, then store selected paths in the source connection.
- Future connector options are visible only when admins enable their visibility, and remain disabled until backend support is added.
- New source creation and unsaved connection tests reject source types hidden by the admin setting.

## File Structure

- `application/single_app/static/js/workspace/workspace-file-sync.js` - shared modal workflow, source type selection, source type table column, and source-specific configuration forms.
- `functional_tests/test_file_sync_onedrive_personal.py` - static coverage for OneDrive connector, selected paths, and browse route wiring.
- `functional_tests/test_file_sync_azure_files_identity.py` - static coverage for Azure Files connector and identity wiring.
- `functional_tests/test_file_sync_capability.py` - static coverage for workflow strings, source type payloads, and source type table wiring.
- `ui_tests/test_workspace_file_sync_ui.py` - workspace smoke coverage for the source workflow modal.
- `ui_tests/test_admin_file_sync_settings_ui.py` - admin-managed source workflow smoke coverage.

## Usage Instructions

Workspace managers click Add Source, choose SMB Share, Azure Files, or OneDrive in a personal workspace, and continue to Configure Source. Connection testing, selected folders/files, schedule settings, tag controls, recursive scanning, and remote-delete policy remain in the configuration step.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_capability.py`, `functional_tests/test_file_sync_azure_files_identity.py`, and `functional_tests/test_file_sync_onedrive_personal.py`.
- UI smoke coverage: `ui_tests/test_workspace_file_sync_ui.py` and `ui_tests/test_admin_file_sync_settings_ui.py`.
- JavaScript syntax coverage: `node --check application/single_app/static/js/workspace/workspace-file-sync.js`.

## Known Limitations

- On-prem SharePoint and Google Workspace options are placeholders and do not submit source payloads.
- OneDrive is limited to personal workspaces.