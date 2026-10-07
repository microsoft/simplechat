# Azure Files File Sync Managed Identity Fix

Fixed in version: **0.261.294**

Related issue: [#1697](https://github.com/microsoft/simplechat/issues/1697)

## Issue Description

Azure Files File Sync sources that authenticated with a managed identity or a service principal never worked. Every connection test and sync run failed with the generic message "Azure Files connection test failed. Verify the file endpoint, share, and identity permissions." Only sources that used a storage connection string could sync.

When a run failed, nobody was told. The run history showed a generic failure, and neither the source's managers nor administrators got a notification.

The documentation said to "grant a Storage File Data role that matches the desired read access", which doesn't name the role that Azure Files OAuth actually requires.

## Root Cause

`functions_file_sync._get_azure_files_service_client` built `ShareServiceClient(account_url=..., credential=<TokenCredential>)` without a `token_intent`. Azure Files OAuth over REST requires backup intent. `azure-storage-file-share` 12.25.0 raises `ValueError("'token_intent' keyword is required when 'credential' is an TokenCredential.")` from the client constructor, and the connection test and the run swallowed that error into their generic messages.

## Technical Details

### Files Modified

- `application/single_app/functions_file_sync.py`
  - Passes `token_intent="backup"` (`AZURE_FILES_TOKEN_INTENT`) when building token-credential clients. Share, directory, and file clients derived from them inherit the intent. The connection-string path is unchanged.
  - Adds `classify_azure_files_error`, which maps storage error codes, HTTP status, and credential failures to four reviewed categories:
    - permission denied, with Storage File Data Privileged Reader guidance;
    - authentication failed;
    - share or directory not found;
    - network blocked.
  - The connection test raises `FileSyncPublicValidationError` with the category message, so the reason is actionable without returning raw SDK text. Diagnostics (error code, status, request ID, and auth kind) are logged with `[FILE_SYNC]`.
  - Failed runs store `error_category`. `sanitize_file_sync_run` returns the reviewed category message for known categories and the generic message otherwise.
  - `_notify_file_sync_run_failed` notifies the source's current managers:
    - **Personal:** the owner.
    - **Group:** the owner, admins, and document managers.
    - **Public:** the owner, admins, and document managers.

    Each manager gets at most one notification per source per day (an idempotent `file_sync_run_failed` notification). Permission and authentication failures also notify app administrators.
- `application/single_app/functions_notifications.py`: registers `file_sync_run_failed`.
- `application/single_app/static/js/workspace/workspace-file-sync.js` (V1): adds an Azure Files authentication notice naming the role and explaining that synced files bypass NTFS permissions.
- `application/v2_ui/src/lib/fileSourceFields.ts` and `application/v2_ui/src/components/fileSources/FileSourceEditorDialog.tsx` (V2): add the same notice for group file sources.
- `application/v2_ui/src/lib/notifications.ts`: labels the new notification type.
- `docs/explanation/features/v0.241.127/AZURE_FILES_FILE_SYNC.md` and `docs/admin/knowledge.md`: name the required role and the NTFS bypass.
- Deployers (`deployers/` 1.0.34): optional role grants on existing storage accounts (`azureFilesStorageAccountResourceIds` in Bicep, with matching Azure CLI and Terraform inputs).

### Testing

- `functional_tests/test_file_sync_azure_files_token_intent.py`:
  - Proves the pinned SDK rejects token credentials without intent.
  - Builds real managed identity and service principal clients and checks that the derived share and file clients carry backup intent.
  - Confirms connection strings are unaffected.
  - Covers error classification, actionable connection-test messages without raw SDK text, run sanitization, daily manager and admin notifications, recipient roles, and the V1 and V2 guidance text.
- `functional_tests/test_file_sync_azure_files_identity.py` still passes, so the existing wiring is unchanged.

### Impact

Managed identity and service principal Azure Files sources now sync once the identity holds Storage File Data Privileged Reader. That role reads every file in the share regardless of NTFS permissions, and synced documents are visible to the whole workspace. To keep per-file permissions, use the Azure Files Search action instead (see `docs/explanation/features/AZURE_FILES_SEARCH_ACTION.md`).

## Validation

- Before: an Azure Files source with a managed identity failed the connection test with a generic error, and the SDK rejected the client before any request was sent.
- After: the same source lists and syncs files. Live validation listed the test share and read file security descriptors with OAuth backup intent. When the role is missing, the connection test says to assign Storage File Data Privileged Reader.
