# File Sync Source Type Badges (v0.241.088)

## Overview

File Sync synced-document indicators now render as source-type badges instead of a generic synced label. SMB sources display an `SMB` badge, Azure Files sources display an `Azure Files` badge, and the mapping is ready for future connectors such as Microsoft 365 SharePoint, OneDrive, Google Workspace, and on-prem SharePoint.

Implemented in version: **0.241.088**

Related version update: `application/single_app/config.py` was incremented to `0.241.088` for this feature update.

## Dependencies

- Bootstrap badge classes and Bootstrap Icons.
- Synced document metadata in `doc.file_sync`.
- File Sync source metadata from `application/single_app/functions_file_sync.py`.

## Technical Specifications

### Architecture

Synced document badges are driven by `doc.file_sync.source_type`. New File Sync documents persist `source_type` into the document metadata, and existing synced documents without this value fall back to `smb` so the UI remains backward compatible.

### Badge Mapping

| Source type | Badge label | Badge color |
| --- | --- | --- |
| `smb` | `SMB` | Primary |
| `azure_files` | `Azure Files` | Info |
| `m365sp` / `m365_sp` / `m365_sharepoint` / `sharepoint_online` | `M365SP` | Info |
| `onedrive` / `one_drive` | `OneDrive` | Dark |
| `google` / `google_workspace` | `Google` | Warning |
| `spo` / `sharepoint_on_prem` | `SPO` | Success |

Unknown source types render as uppercase labels with a secondary badge.

### Files Updated

- `application/single_app/functions_file_sync.py`
- `application/single_app/static/js/workspace/workspace-utils.js`
- `application/single_app/static/js/public/public_workspace.js`
- `application/single_app/templates/group_workspaces.html`

## Usage Instructions

No administrator action is required. Synced files in personal, group, and public workspaces show the source-type badge anywhere the synced indicator is rendered.

Future sync connectors should set `doc.file_sync.source_type` to one of the mapped values to receive the appropriate badge label and color.

## Testing and Validation

Coverage was updated in:

- `functional_tests/test_file_sync_capability.py`
- `functional_tests/test_file_sync_azure_files_identity.py`
- `ui_tests/test_workspace_file_sync_ui.py`

Validation checks confirm that synced document metadata includes `source_type`, the UI mapping includes current and planned source labels, and personal workspace UI tests expect the `SMB` badge instead of a generic synced badge.