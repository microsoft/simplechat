# Azure Files File Sync

## Overview

Azure Files File Sync adds an Azure Storage file share source type to the existing File Sync workflow. Workspace managers can sync files from an Azure Files share by using a file service URL, share name, and optional directory path instead of an SMB UNC path.

Implemented in version: **0.241.127**

Endpoint validation updated in version: **0.261.312**

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

From version **0.261.312**, the File service URL must use a canonical Azure
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

The managed identity used by the app needs Azure Files data-plane permissions on the target storage account or file share. For SDK-based sync, grant a Storage File Data role that matches the desired read access. For SMB-mounted Azure Files scenarios, use Azure Files SMB managed identity or Kerberos configuration outside SimpleChat and keep using the SMB connector against the mounted/UNC path.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_azure_files_identity.py`
- Endpoint and OneDrive path regression coverage: `functional_tests/test_file_sync_ssrf_validation.py`
- Existing File Sync capability coverage: `functional_tests/test_file_sync_capability.py`
- UI coverage updated for source type visibility and Azure Files source modal rendering

Known limitation: PIV/smart-card authentication is not implemented inside the web app. PIV and smart-card flows belong at the client or domain/Kerberos layer for SMB access; SimpleChat can consume the resulting SMB path through the existing SMB connector.

Known limitation: the pinned Azure Files SDK requires `token_intent` for token
credentials, but the current connector does not supply it. Managed-identity and
service-principal client construction therefore fails before network access.
The endpoint validation change does not repair this separate authentication issue.