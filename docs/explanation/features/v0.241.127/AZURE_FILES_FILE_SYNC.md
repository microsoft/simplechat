# Azure Files File Sync

## Overview

Azure Files File Sync adds an Azure Storage file share source type to the existing File Sync workflow. Workspace managers can sync files from an Azure Files share by using a file service URL, share name, and optional directory path instead of an SMB UNC path.

Implemented in version: **0.241.127**

Endpoint validation updated in version: **0.261.314**

Token authentication and safe diagnostics fixed in version: **0.261.358**

## Dependencies

- `azure-storage-file-share==12.25.0`
- Existing workspace identity storage and Key Vault secret handling
- Existing File Sync Redis readiness, schedule, filter, tag, and delete-policy controls

## Technical Specifications

The connector stores `source_type: "azure_files"` and a connection payload with `account_url`, `share_name`, `directory_path`, and `share_url`. Sync runs list files through the Azure Files SDK, stage downloads into the same temporary-file pipeline as SMB sync, and persist synced document metadata with the Azure Files source type.

Supported reusable workspace identity authentication methods for Azure Files are:

- Managed identity
- Service principal client secret
- Azure Storage connection string

SMB sources continue to support username/password and anonymous authentication for UNC paths.

### Approved endpoints

From version **0.261.314**, the File service URL must use a canonical Azure
Files hostname: `account.file.core.windows.net`,
`account.file.core.usgovcloudapi.net`, `account.file.core.chinacloudapi.cn`, or
`account.file.core.cloudapi.de`. A share URL such as
`https://account.file.core.windows.net/documents/team` supplies the share and
optional directory when those fields are not already provided.

The server rejects arbitrary hosts, IP addresses, embedded credentials,
explicit ports, queries, and fragments, and revalidates saved account URLs
before token-authenticated SDK construction. Private endpoints should use the
canonical account hostname with private DNS. Custom domains, direct private-link
hostnames, and emulator URLs are not accepted in the URL field.
Connection-string credential dispatch is unchanged.

See [File Sync SSRF endpoint validation](../../fixes/FILE_SYNC_SSRF_ENDPOINT_VALIDATION_FIX.md)
for the security boundary and compatibility details.

## Usage Instructions

Admins can enable Azure Files in Admin Settings under File Sync source type visibility. Workspace managers then choose Azure Files in the Add Source workflow, enter the file service or share URL, share name, and directory path, and select a compatible reusable identity or source-local Azure Files credential.

### Token authentication and permissions

From **0.261.358**, the shared SDK client supplies the required
`token_intent="backup"` for managed identity and service-principal authentication.
The SDK propagates this intent to directory listings, file properties, and
downloads. This applies to saved identities and direct credentials, personal,
group, and public workspaces, and classic and V2 entry points. Connection-string
dispatch is unchanged; saved sources do not need to be recreated.

The identity needs Azure Files OAuth-over-REST read permissions, including the
`readFileBackupSemantics` data action. **Storage File Data Privileged Reader**
is a built-in read-only role for this purpose; scope access to the required
share or account. An ordinary SMB reader role alone does not supply the required
backup-semantics permission.

Backup intent bypasses file and directory ACLs within the RBAC-granted scope.
It does not bypass Azure RBAC or storage network restrictions. SimpleChat does
not grant permissions automatically. See
[Azure Files OAuth over REST](https://learn.microsoft.com/en-us/azure/storage/files/authorize-oauth-rest)
before choosing the identity's access scope.

For SMB-mounted Azure Files scenarios, configure SMB/Kerberos outside SimpleChat
and use the SMB connector against the mounted/UNC path instead.

### Failure diagnostics

Connection tests and browsing return stable messages distinguishing
authentication, authorization, missing resources, transport, SDK availability,
and client-initialization failures where structured evidence supports them.
Unknown errors remain generic; a denied request does not prove a particular
missing role or firewall rule.

The shared connector records safe failure categories under `[FILE_SYNC]`,
including listing and download failures during sync. No credential, endpoint,
path, raw provider message, or provider traceback is added to these diagnostics.
Use the request's existing OperationId with the
[logging reference](../../../reference/logging-tags.md#azure-files-connector-diagnostics).
Failed listings remain failed runs, not empty successful inventories.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_azure_files_identity.py`
- Real pinned-SDK pagination, properties, download, and token-intent coverage:
  `functional_tests/test_file_sync_azure_files_runtime.py`
- Provider classification, safe logging/API responses, partial listing failures,
  and download cleanup: `functional_tests/test_file_sync_azure_files_diagnostics.py`
- Endpoint and OneDrive path regression coverage: `functional_tests/test_file_sync_ssrf_validation.py`
- Existing File Sync capability coverage: `functional_tests/test_file_sync_capability.py`
- UI coverage updated for source type visibility and Azure Files source modal rendering

Known limitation: PIV/smart-card authentication is not implemented inside the web app. PIV and smart-card flows belong at the client or domain/Kerberos layer for SMB access; SimpleChat can consume the resulting SMB path through the existing SMB connector.

The offline SDK tests do not establish deployed RBAC permissions, network
connectivity, remote fixture availability, ingestion, or chat/citation outcomes.
See the [token authentication fix](../../fixes/AZURE_FILES_TOKEN_AUTHENTICATION_FIX.md)
for the original failure and validation boundary.