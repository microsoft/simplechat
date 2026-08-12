# Azure Blob Storage File Sync

Implemented in version: **0.250.067**
Security hardening in version: **0.250.068**
Container SAS support and credential visibility in version: **0.250.069**
Non-Key-Vault compatibility and List/Read connection validation in version: **0.250.070**

Related issue: [#1027](https://github.com/microsoft/simplechat/issues/1027)

## Overview

Azure Blob Storage is available as an admin-controlled File Sync source for personal, group, and public workspaces. Authorized workspace managers can connect a storage account and container, optionally limit synchronization to a blob-name prefix or selected virtual paths, and use the existing File Sync schedules, filters, tags, delete policies, run history, and workflow triggers.

## Dependencies

- File Sync and the target workspace scope must be enabled in Admin Settings.
- Redis Cache must be configured before File Sync runs are effective.
- The existing `azure-storage-blob==12.24.1` dependency provides Blob service access.
- Managed identity requires an Azure Storage data-plane role such as **Storage Blob Data Reader** on the target account or container.
- Client-secret and Blob credential authentication use Azure Key Vault when secret storage is enabled. When it is disabled, they use the existing File Sync source or reusable-identity credential persistence and remain redacted from browser responses.
- The application version was updated in `application/single_app/config.py` to `0.250.070` for non-Key-Vault compatibility and List/Read-only connection validation.

## Technical Specifications

### Architecture

- The source type is stored as `source_type: "azure_blob"` in the existing personal, group, or public File Sync source container.
- Connection data contains `account_url`, `container_name`, optional `blob_prefix`, and optional `selected_paths`.
- Storage account names are expanded to `https://<account>.blob.core.windows.net`. Full service and container URLs are accepted only when their host is a valid Azure Blob endpoint in the supported public, US Government, China, or Germany cloud suffixes.
- Blob service URLs and connection-string endpoints are validated again immediately before SDK client construction. Loopback, link-local, arbitrary custom, development-storage, userinfo, nonstandard-port, query-string, and fragment endpoints are rejected.
- Blob names are presented as virtual folders in the existing source browser. Directory-marker blobs are ignored during synchronization.
- Blob ETags, last-modified timestamps, and content lengths are translated into the shared remote-file contract for change detection.
- Downloads are streamed in chunks into the existing temporary-file ingestion path, preserving file limits, supported-format checks, document processing, tags, and source attribution.
- Existing File Sync ownership, role, scope-assignment, admin-management, scheduling, and remote-delete checks apply without new routes or authorization paths.

### Authentication

- **Managed identity** is the recommended authentication mode.
- **Service principal** authentication uses tenant ID, client ID, and a client secret. Key Vault is used when configured.
- **Blob credential** authentication accepts a storage connection string, full container SAS URL, or standalone SAS token. Key Vault is used when configured.
- The Blob credential field accepts three Azure-provided formats: a storage connection string, a full container SAS URL, or a standalone SAS token. A standalone token uses the Blob service URL and container entered in the source form.
- **Container SAS** is the recommended secret-based option for a source that syncs one container. It must grant **Read** (`r`) and **List** (`l`) and require HTTPS. Write, Create, Add, Delete, tag, move, ownership, and policy permissions are not required; they are accepted but shown as least-privilege warnings.
- **Account SAS** and storage account keys are accepted for compatibility but are identified as broader than a single-container source needs. Account SAS must include the Blob service, Container and Object resource types, and Read and List permissions.
- **Blob/object SAS** is rejected because File Sync must list the selected container before reading blobs.
- Reusable workspace identities can declare Azure Blob Storage support for personal, group, or public scopes.
- Unsaved connection tests use credentials in memory. Saving stores secret material through Key Vault when enabled or through existing File Sync credential persistence when Key Vault is disabled.
- Detailed SDK and network failures are written through sanitized server logging. API responses, run history, activity records, and failed item records use fixed public messages instead of returning exception text.

Each File Sync source targets one container. To synchronize multiple containers, create one source per container. Account-wide container discovery is not performed by this feature.

SAS scope, non-secret permission letters, start time, expiry, HTTPS status, optional IP range, and least-privilege warnings are stored as non-secret metadata. The source list shows the credential scope, named permissions, exact expiry, and days remaining without exposing the SAS token.

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
	- Alternatively, paste the full container SAS URL into either **Blob service URL or account name** or **Blob connection string, SAS URL, or SAS token**. The form derives the non-secret Blob service URL, container, and default source name, switches to Blob credential authentication, and stores the SAS through the configured File Sync secret-storage path.
4. Select managed identity or a compatible reusable identity. Source-local service-principal and Blob credentials work with or without Key Vault; Key Vault is preferred when available.
	- For a container SAS connection string, use `BlobEndpoint=https://<account>.blob.core.windows.net/<container>` plus `SharedAccessSignature=<token>`.
	- A full SAS URL uses `https://<account>.blob.core.windows.net/<container>?<token>`. A standalone token begins with `?` or the first SAS parameter and requires the account/container fields above.
	- Select **Read** and **List**, set **Allowed protocols** to HTTPS only, and choose an expiry that covers the intended schedule and rotation window.
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

The functional test executes account and URL normalization, container validation, optional Key Vault and non-Key-Vault secret persistence, virtual-path browsing, recursive and non-recursive listing, ETag metadata mapping, streamed downloads, and SHA-256 generation with fake Blob SDK clients. It also verifies the shared source workflow is connected to personal, group, and public workspace roots.

Security coverage rejects non-Azure and internal endpoints in direct URLs and connection strings, verifies HTTPS-only Azure cloud suffixes, and confirms backend exception details never cross API, run-history, activity, or item-response boundaries.

Container SAS coverage validates endpoint/container matching, required Read and List permissions, extra-permission warnings, account-SAS breadth warnings, object-SAS rejection, expiry and start times, stored access policies, non-secret metadata serialization, and direct container-client construction.

Credential-format coverage verifies storage connection strings, full SAS URLs, and standalone SAS tokens. A SAS URL pasted into the account or credential field is promoted into the configured File Sync secret-storage path; only its canonical account and container remain in source connection metadata.

Neighboring Azure Files and OneDrive regression suites confirm that adding Azure Blob Storage does not remove existing source types or compatible identity behavior. Playwright coverage validates the admin switch and Blob-specific source fields.

## Known Limitations

- Blob snapshots, versions, deleted blobs, and soft-deleted records are not synchronized.
- Blob names are shown as virtual folders; Azure Blob Storage does not provide physical directories unless hierarchical namespace features are enabled.
- Without Key Vault, secret material remains in the existing File Sync source or identity credential record. Enable Key Vault or use managed identity when stronger secret isolation is required.
- Custom domains, Azurite/development storage, Azure Stack endpoints, and direct private-link hostnames are not accepted. Use the standard Azure Blob service hostname; Azure Private Endpoint DNS can resolve that hostname privately.
- SAS tokens using a stored access policy may omit explicit permissions or expiry. File Sync reports that these values are policy-controlled, validates List and Read through the connection test when blobs are available, and cannot display the policy's expiry without querying Azure control data.
- A connection test can verify List immediately. Read is verified against the first available blob; an empty source reports that Read could not be exercised.
- SAS IP restrictions must include the App Service outbound address that performs sync. An administrator should account for all active outbound addresses and deployment slots.
- Avoid setting a SAS start time exactly to the current time because clock skew can delay usability. Omit it or set it several minutes in the past.
- SAS credentials do not rotate automatically. Replace the source or reusable-identity secret before expiry; the source list shows remaining days to support this process.