# File Sync Source Workflow

Implemented in version: **0.241.073**

Fixed/Implemented in version: **0.241.073**

## Overview

File Sync source creation and editing uses a modal workflow instead of an inline form. The first step selects the source type, and the second step configures the selected source. Admins can choose which source types are visible in the workflow. SMB remains the only enabled connector, while the workflow leaves room for future source types such as on-prem SharePoint and Google Workspace.

## Dependencies

- File Sync must be enabled for the current workspace scope.
- Redis Cache must be configured before sync runs are effective.
- SMB sources require the existing `smbprotocol` dependency.
- Version was updated in `application/single_app/config.py` to `0.241.073`.

## Technical Specifications

- `workspace-file-sync.js` now renders a Bootstrap modal for add and edit source flows.
- The workflow includes a Source Type step and a Configure step.
- Admin Settings includes `file_sync_visible_source_types` controls for SMB Share, On-prem SharePoint, and Google Workspace visibility.
- The source list table includes a Type column populated from each source's `source_type` field.
- SMB payloads continue to submit `source_type: "smb"` to the existing File Sync APIs.
- Future connector options are visible only when admins enable their visibility, and remain disabled until backend support is added.
- New source creation and unsaved connection tests reject source types hidden by the admin setting.

## File Structure

- `application/single_app/static/js/workspace/workspace-file-sync.js` - shared modal workflow, source type selection, source type table column, and SMB configuration form.
- `functional_tests/test_file_sync_capability.py` - static coverage for workflow strings, source type payloads, and source type table wiring.
- `ui_tests/test_workspace_file_sync_ui.py` - workspace smoke coverage for the source workflow modal.
- `ui_tests/test_admin_file_sync_settings_ui.py` - admin-managed source workflow smoke coverage.

## Usage Instructions

Workspace managers click Add Source, choose SMB Share, and continue to Configure Source. Existing SMB configuration fields, connection testing, schedule settings, tag controls, recursive scanning, and remote-delete policy remain in the configuration step.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_capability.py`.
- UI smoke coverage: `ui_tests/test_workspace_file_sync_ui.py` and `ui_tests/test_admin_file_sync_settings_ui.py`.
- JavaScript syntax coverage: `node --check application/single_app/static/js/workspace/workspace-file-sync.js`.

## Known Limitations

- SMB Share is the only enabled source type in this version.
- On-prem SharePoint and Google Workspace options are placeholders and do not submit source payloads.