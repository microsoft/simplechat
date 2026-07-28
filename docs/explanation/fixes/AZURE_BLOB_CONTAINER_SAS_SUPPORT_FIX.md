# Azure Blob Container SAS Support Fix

Fixed in version: **0.250.069**

Related issue: [#1027](https://github.com/microsoft/simplechat/issues/1027)

Related pull request: [#1088](https://github.com/microsoft/simplechat/pull/1088)

## Issue Description

Azure Blob File Sync accepted service/account connection strings but rejected container SAS credentials when Azure supplied either a container path in `BlobEndpoint` or a full container SAS URL. A standalone SAS token was also not recognized. Users could not see the SAS scope, required permissions, expiry, or whether a broader credential granted unnecessary access.

## Root Cause Analysis

The SSRF-hardened connection-string validator required `BlobEndpoint` to be a service URL with no path. A container SAS legitimately uses a canonical Azure Blob endpoint followed by one container segment. The connector also treated connection strings as opaque secrets, so it could not safely surface non-secret SAS metadata or validate least privilege before SDK calls.

## Technical Details

### Files Modified

- `application/single_app/functions_file_sync.py`
- `application/single_app/static/js/workspace/workspace-file-sync.js`
- `application/single_app/config.py`
- `functional_tests/test_file_sync_azure_blob_storage.py`
- `ui_tests/test_workspace_file_sync_ui.py`
- Azure Blob File Sync feature documentation and release notes

### Code Changes

- Parses `BlobEndpoint` and `SharedAccessSignature` separately while preserving the SAS token only in Key Vault-backed authentication data.
- Accepts storage connection strings, full container SAS URLs, and standalone SAS tokens.
- Derives the canonical service URL, selected container, and default source name when a full SAS URL is pasted into either Blob field; the form selects Blob credential authentication, the token is promoted to secret storage, and it is not persisted in source connection fields.
- Allows exactly one canonical container path and requires it to match the source's selected container.
- Constructs `ContainerClient` directly for SAS credentials, preventing container SAS from being treated as an account-level service client.
- Requires Read (`r`) and List (`l`) for explicit container SAS permissions.
- Requires account SAS to include Blob service plus Container and Object resource types.
- Rejects blob/object SAS because it cannot enumerate a container.
- Requires HTTPS-only SAS protocol and rejects expired or not-yet-valid tokens outside a small clock-skew tolerance.
- Accepts extra permissions but emits named least-privilege warnings. Account SAS and account keys are identified as broader than required.
- Stores and returns only non-secret metadata: credential type, scope, permission letters, validity window, expiry, HTTPS state, IP range, resource scope, and warnings.
- Shows credential scope, named permissions, exact expiry, days remaining, and warnings in the source workflow and source list.

## Validation

- Container SAS with matching endpoint, HTTPS, Read, and List is accepted.
- Full container SAS URLs and standalone SAS tokens are accepted. A token with Read but without List receives explicit regeneration guidance.
- Endpoint/container mismatch, object SAS, missing Read/List, HTTP-capable SAS, expired SAS, and future-not-valid SAS are rejected.
- Extra Write/Delete permissions are accepted with a warning.
- Account SAS remains accepted with breadth and extra-permission warnings.
- SAS tokens and signatures are not included in credential metadata or browser responses.
- Connection tests validate List and, when a blob exists, Read access.

## Operational Guidance

- Each File Sync source synchronizes one container. Use one source per container.
- Prefer managed identity. When SAS is required, prefer a container SAS with only Read and List.
- Set expiry far enough ahead for scheduled runs and rotate the Key Vault secret before expiry.
- Stored access policies hide effective permission and expiry details from the token; confirm the policy grants Read and List.
- Ensure SAS IP restrictions include all App Service outbound addresses that may execute sync.
- Avoid a start time equal to the current time because clock skew can make a new SAS temporarily unusable.