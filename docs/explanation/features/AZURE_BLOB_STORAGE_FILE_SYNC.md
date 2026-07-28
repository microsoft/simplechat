# Azure Blob Storage File Sync

Implemented in version: **0.250.067**

Related issue: [#1027](https://github.com/microsoft/simplechat/issues/1027)

## Overview

Azure Blob Storage is available as an admin-controlled File Sync source for personal, group, and public workspaces. Authorized workspace managers can connect a storage account and container, optionally limit synchronization to a blob-name prefix or selected virtual paths, and use the existing File Sync schedules, filters, tags, delete policies, run history, and workflow triggers.

## Dependencies

- File Sync and the target workspace scope must be enabled in Admin Settings.
- Redis Cache must be configured before File Sync runs are effective.
- The existing `azure-storage-blob==12.24.1` dependency provides Blob service access.
- Managed identity requires an Azure Storage data-plane role such as **Storage Blob Data Reader** on the target account or container.
- Client-secret and connection-string authentication require Azure Key Vault secret storage. Saved Azure Blob sources and reusable identities cannot persist these secrets inline in Cosmos DB records.
- The application version was updated in `application/single_app/config.py` to `0.250.067`.

## Technical Specifications

### Architecture

- The source type is stored as `source_type: "azure_blob"` in the existing personal, group, or public File Sync source container.
- Connection data contains `account_url`, `container_name`, optional `blob_prefix`, and optional `selected_paths`.
- Storage account names are expanded to `https://<account>.blob.core.windows.net`; full HTTPS Blob service and container URLs are also accepted.
- Blob names are presented as virtual folders in the existing source browser. Directory-marker blobs are ignored during synchronization.
- Blob ETags, last-modified timestamps, and content lengths are translated into the shared remote-file contract for change detection.
- Downloads are streamed in chunks into the existing temporary-file ingestion path, preserving file limits, supported-format checks, document processing, tags, and source attribution.
- Existing File Sync ownership, role, scope-assignment, admin-management, scheduling, and remote-delete checks apply without new routes or authorization paths.

### Authentication

- **Managed identity** is the recommended authentication mode.
- **Service principal** authentication uses tenant ID, client ID, and a Key Vault-backed client secret.
- **Connection string** authentication uses a Key Vault-backed storage connection string.
- Reusable workspace identities can declare Azure Blob Storage support for personal, group, or public scopes.
- Unsaved connection tests may use credentials in memory, but saving rejects secret-based credentials that do not resolve through Key Vault.

### Admin Configuration

1. Open **Admin Settings > File Sync**.
2. Enable File Sync globally and enable the required personal, group, or public scopes.
3. Under **Visible Source Types**, turn on **Azure Blob Storage**.
4. Configure workspace assignments or admin-only source management when required.
5. Grant the selected identity least-privilege Blob data access to the target account or container.

Azure Blob Storage is opt-in. Existing installations retain the SMB and Azure Files default source-type visibility until an admin enables Blob Storage and saves settings.

## Usage Instructions

1. Open the **Sync** tab in an enabled personal, group, or public workspace.
2. Select **Add Source**, then choose **Azure Blob Storage**.
3. Enter the Blob service URL or storage account name, container name, and optional blob prefix.
4. Select managed identity or a compatible Key Vault-backed reusable identity. Source-local service-principal and connection-string credentials also require Key Vault.
5. Use **Browse** or **Add Path** to narrow the source, then configure recursion, filters, tags, schedule, and remote-delete behavior.
6. Test the connection before saving, then run the source manually or on its schedule.

## File Structure

- `application/single_app/functions_file_sync.py`: source registration, validation, authentication, connection test, browse, list, metadata, and streamed download adapter.
- `application/single_app/functions_workspace_identities.py`: reusable identity source-type compatibility.
- `application/single_app/templates/admin_settings.html`: admin source-type visibility switch.
- `application/single_app/static/js/workspace/workspace-file-sync.js`: shared source workflow for all workspace scopes.
- `application/single_app/static/js/workspace/workspace-utils.js`: personal workspace source badge.
- `application/single_app/templates/group_workspaces.html`: group workspace source badge.
- `application/single_app/static/js/public/public_workspace.js`: public workspace source badge.
- `functional_tests/test_file_sync_azure_blob_storage.py`: connector behavior and all-scope wiring coverage.
- `ui_tests/test_admin_file_sync_settings_ui.py`: admin switch coverage.
- `ui_tests/test_workspace_file_sync_ui.py`: source workflow coverage.

## Testing and Validation

The functional test executes account and URL normalization, container validation, Key Vault secret enforcement, virtual-path browsing, recursive and non-recursive listing, ETag metadata mapping, streamed downloads, and SHA-256 generation with fake Blob SDK clients. It also verifies the shared source workflow is connected to personal, group, and public workspace roots.

Neighboring Azure Files and OneDrive regression suites confirm that adding Azure Blob Storage does not remove existing source types or compatible identity behavior. Playwright coverage validates the admin switch and Blob-specific source fields.

## Known Limitations

- Blob snapshots, versions, deleted blobs, and soft-deleted records are not synchronized.
- Blob names are shown as virtual folders; Azure Blob Storage does not provide physical directories unless hierarchical namespace features are enabled.
- Secret-based authentication cannot be saved when Azure Key Vault secret storage is disabled. Use managed identity in that configuration.