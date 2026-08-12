# Azure Blob File Sync SSRF and Error Disclosure Fix

Fixed in version: **0.250.068**

Related issue: [#1027](https://github.com/microsoft/simplechat/issues/1027)

Related pull request: [#1088](https://github.com/microsoft/simplechat/pull/1088)

## Issue Description

Azure Blob File Sync accepted any syntactically valid HTTPS account URL before creating a `BlobServiceClient`. A workspace manager could therefore provide an arbitrary host and cause the server to attempt a request outside Azure Blob Storage. File Sync routes and persisted run/item failures also exposed raw exception text to browser responses and history surfaces, which could reveal endpoints, request details, or secret-bearing SDK messages.

## Root Cause Analysis

The initial URL normalizer checked only the HTTPS scheme and presence of a network location. It did not require an Azure-owned Blob service hostname, reject URL credentials or nonstandard ports, or validate endpoints embedded in connection strings. The route exception mapper returned `str(error)` directly, and failed run/item records persisted the same raw exception text for later serialization.

## Technical Details

### Files Modified

- `application/single_app/functions_file_sync.py`
- `application/single_app/route_backend_file_sync.py`
- `application/single_app/config.py`
- `functional_tests/test_file_sync_azure_blob_storage.py`
- Related versioned tests and Azure Blob File Sync documentation

### Code Changes

- Added an allowlist for Azure public, US Government, China, and Germany Storage endpoint suffixes.
- Required a 3-24 character lowercase alphanumeric storage account label and reconstructed a canonical HTTPS Blob service URL after validation.
- Rejected arbitrary hosts, IP literals, loopback/link-local targets, userinfo, explicit ports, query strings, fragments, development storage, HTTP connection strings, and unsupported endpoint suffixes.
- Revalidated stored account URLs and connection strings immediately before `BlobServiceClient` construction.
- Replaced route exception responses with fixed messages for authorization, lookup, validation, and unexpected failures.
- Replaced persisted and serialized run/item exception details with generic public messages.
- Preserved detailed exception type and text only in `log_event`, which applies the repository's structured log sanitization before writing server diagnostics.

## Testing Approach

`functional_tests/test_file_sync_azure_blob_storage.py` now validates accepted Azure cloud endpoints and rejects internal, arbitrary, credential-bearing, port-bearing, query-bearing, and fragment-bearing URLs. It covers safe and unsafe connection strings, checks route source for raw exception serialization, verifies run-history sanitization, and confirms raw item errors are not persisted.

Neighboring Azure Files and OneDrive File Sync regression tests remain part of validation to ensure the source registry and shared identity behavior are unchanged.

## Impact Analysis

Existing sources using standard Azure Blob service hostnames continue to work. Azure Private Endpoint configurations should continue using the standard account Blob hostname with private DNS resolution. Custom domains, Azurite/development storage, Azure Stack endpoints, direct private-link hostnames, and non-Azure Blob-compatible endpoints are intentionally rejected.

## Validation

- Before: arbitrary HTTPS hosts could reach Blob SDK client construction, and raw backend exceptions could be returned or persisted for client-visible history.
- After: only canonical allowlisted Azure Blob endpoints reach the SDK, while client-visible failures are generic and detailed sanitized diagnostics stay server-side.
- The application version was updated to `0.250.068` for this security fix.