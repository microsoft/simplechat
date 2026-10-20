# Azure Files Token Authentication Fix

Fixed in version: **0.261.358**

## Issue and root cause

Azure Files connection tests using managed identity failed before reaching the
storage service. The common client factory omitted `token_intent`, required by
the pinned `azure-storage-file-share==12.25.0` SDK for every token credential.
Service-principal authentication used the same incomplete construction.

The UI displayed a generic File Sync configuration error because the connection
test wrapped the SDK exception as `ValueError`. Route telemetry retained only
the length of the exception class name. Four supplied UI acceptance attempts
stopped at this connection gate; they did not establish separate failures in
sync, grounding, citation, update, retention, or deletion behavior.

## Technical changes

`application/single_app/functions_file_sync.py` now supplies
`token_intent="backup"` in the shared token-authenticated service client.
The SDK propagates that intent to share, directory, and file clients.
The repair covers connection testing, browsing, sync enumeration, metadata
reads, and staging downloads for personal, group, and public sources in classic
and V2. It is not conditional on a test case, source name, or directory.

Connection-string dispatch, identity authorization, secret storage, approved
endpoint validation, schedules, filters, and remote-delete policy remain
unchanged. Saved sources do not need to be recreated. No permission, resource,
deployment, or harness changes are part of this fix.

### Access semantics

Azure Files OAuth over REST requires backup intent and corresponding RBAC data
actions. For read-only imports, use the minimum necessary scope and read access,
such as **Storage File Data Privileged Reader**. An ordinary SMB reader role
alone does not provide `readFileBackupSemantics`.

Backup semantics bypass file/directory ACLs within the RBAC-granted scope.
They do not bypass RBAC or storage network restrictions. SimpleChat neither
grants these permissions nor switches credentials after a rejected request.
See [Azure Files OAuth over REST](https://learn.microsoft.com/en-us/azure/storage/files/authorize-oauth-rest).

### Safe diagnostics

A small shared operation boundary classifies structured provider evidence as
authentication, authorization, missing resource, transport, SDK availability,
client configuration, or unknown failure. Connection tests and browsing expose
stable, reviewed messages through `FileSyncPublicValidationError`, using the
existing API response envelopes.

The existing `[FILE_SYNC]` tag records `failure_code`, `operation`, `error_type`,
and a valid numeric status through `log_event`. These fields survive the real
Application Insights sanitization boundary without expanding its allowlist.
No raw provider error, traceback chain, credential, endpoint, filename, or
identity is included in the new event. Both debug logging modes retain the
categories. See [logging tags](../../reference/logging-tags.md#azure-files-connector-diagnostics).

Lazy listing failures remain failed operations, not partial successful
inventories. The sync engine must not interpret a failed listing as an empty
source and apply remote deletions. The existing selected-file-not-found to
directory-listing fallback is preserved. Failed downloads remove their partial
temporary file before propagating a safe error.

### Files and documentation

- `application/single_app/functions_file_sync.py`: token intent and diagnostics.
- `application/single_app/config.py`: application patch version `0.261.358`.
- `functional_tests/test_file_sync_azure_files_runtime.py`: real SDK contracts.
- `functional_tests/test_file_sync_azure_files_diagnostics.py`: failure contracts.
- `functional_tests/test_file_sync_ssrf_validation.py`: updated constructor
  keyword expectation without weakening endpoint checks.
- [Azure Files feature](../features/v0.241.127/AZURE_FILES_FILE_SYNC.md),
  [File Sync guide](../../guides/create-a-file-sync.md), and
  [endpoint-validation follow-up](FILE_SYNC_SSRF_ENDPOINT_VALIDATION_FIX.md).

## Validation

Before the repair, an isolated execution of the unchanged production factory
against SDK 12.25.0 failed for both token credential branches:

```text
ValueError: 'token_intent' keyword is required when 'credential' is an TokenCredential.
```

After the repair, offline real-SDK tests construct the client, paginate directory
listings, read file metadata, and download staged content with the required
`x-ms-file-request-intent: backup` header. They cover direct and saved-identity
resolution, workspace scopes, managed-identity selection, connection-string
compatibility, temporary-file cleanup, and normal/optimized Python execution.
SDK construction and request serialization are real; the transport and
credentials are isolated and socket/DNS access is blocked.

Diagnostics tests cover structured and unknown evidence, debug-on/off logging,
safe traceback suppression, selected-directory fallback, partial listing
failure without remote deletion, and saved/unsaved personal, group, and public
Flask error responses. Existing endpoint tests retain hostile-origin rejection
before credential construction.

### Local results

Commands below used an isolated Python environment with the pinned Azure Files
SDK, Flask 3.1.3, and Werkzeug 3.1.6. The shared machine's older Flask installation
was not changed.

| Command | Result |
| --- | --- |
| `python -m pytest -q functional_tests\test_file_sync_azure_files_runtime.py functional_tests\test_file_sync_azure_files_diagnostics.py functional_tests\test_file_sync_azure_files_identity.py functional_tests\test_file_sync_ssrf_validation.py` | 214 passed, including normal/optimized subprocess probes |
| `python -m pytest -q functional_tests\test_file_sync_azure_blob_storage.py functional_tests\test_file_source_credential_round_trip_fix.py functional_tests\test_personal_file_source_apis.py functional_tests\test_group_file_source_apis.py functional_tests\test_public_file_source_apis.py` | 183 passed, 1 pre-existing failure |
| `python -m pytest -q functional_tests\test_file_sync_azure_files_runtime.py -k real_sdk_accepts` | 12 passed, 14 deselected after strengthening saved-identity credential assertions |
| `python functional_tests\test_docs_app_surface_coverage.py` | 7 checks passed; generated inventory unchanged and current |
| `python functional_tests\test_docs_site_quality.py` | 6 checks passed |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Passed |

The pre-existing failure is
`test_file_sync_routes_do_not_disclose_exception_details`. It expects the obsolete
`[FileSync] Request failed.` tag in `route_backend_file_sync.py`; the unchanged
route uses `[FILE_SYNC] Request failed.`. The same assertion was reproduced
against the route read from `HEAD`, whose content matches the working-tree route.
Neither the unrelated test nor the route was modified.

### Live-evidence boundary

Read-only Azure telemetry corroborated four HTTP 400 connection-test requests
with successful Cosmos reads and no recorded Azure Files dependencies. It did
not expose the underlying SDK exception or an immutable deployed revision.
The local defect is reproduced; its attribution to those live failures is
strongly supported rather than independently proven by telemetry.

Offline validation does not prove deployed identity permissions, network
connectivity, fixture contents, ingestion, or later chat/citation outcomes.
No live connection test, sync, source mutation, deployment, or Azure permission
change was performed.
