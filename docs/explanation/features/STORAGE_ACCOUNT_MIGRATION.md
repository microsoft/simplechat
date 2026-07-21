# Storage Account Migration

## Overview

The storage account migration script copies the SimpleChat Blob containers
from one Azure Storage account to another. It supports a non-destructive
differential mode and an overwriting full mode, while retaining blobs that
exist only in the destination.

Implemented in version: **0.250.062**

Resumable JSON checkpointing added in version: **0.250.064**

The application version was updated in `application/single_app/config.py` for
this feature.

### Dependencies

- PowerShell 7
- The `Az.Accounts` and `Az.Storage` PowerShell modules
- AzCopy v10 available as the `azcopy` command
- Access to both source and destination Azure subscriptions
- Permission to read source blobs and create/write destination blobs
- Permission to generate user-delegation SAS tokens for both accounts
- Network access to both storage account Blob endpoints

## Technical Specifications

### Architecture

The script performs these steps:

1. Validates account names, subscription IDs, container names, and source and
   destination separation before connecting to Azure.
2. Verifies that all required Azure PowerShell and AzCopy commands are
   available.
3. Creates each connected-account storage context while its corresponding
   subscription is active.
4. Verifies every source container and creates a private destination container
   when it is missing.
5. Generates HTTPS-only user-delegation SAS URLs for each source and
   destination container.
6. Runs AzCopy once per container and stops immediately with container and exit
   code details if a transfer fails.
7. Reports overall container progress and a final migration summary.

### Migration Modes

Differential mode is enabled by default with
`-DifferentialMigration $true`.

- Uses `azcopy sync` recursively.
- Compares blob names and last-modified timestamps.
- Copies new and changed source blobs.
- Never deletes destination-only blobs.

Full mode is selected with `-DifferentialMigration $false`.

- Uses `azcopy copy` recursively with overwrite enabled.
- Replaces destination blobs that share source paths.
- Still does not delete destination-only blobs.

Both modes preserve source blob index tags. Full mode also explicitly preserves
service-to-service blob properties.

### Configuration

The source and destination account names and subscription IDs have editable
placeholder defaults at the top of the script. Replace those placeholders to
run without arguments, or provide any value as a named parameter; supplied
parameters override the corresponding defaults.

The main parameters are:

- `SourceStorageAccount`
- `SourceSubscriptionId`
- `DestinationStorageAccount`
- `DestinationSubscriptionId`
- `Containers`, defaulting to the five SimpleChat Blob containers
- `DifferentialMigration`, defaulting to `$true`
- `ShowProgress`, defaulting to `$true`
- `SasExpiryHours`, defaulting to 48 hours and limited to 1-168 hours
- `StateFilePath`, defaulting to
   `scripts/Migration-StorageAccount.state.json`
- `ResetState`, which discards an existing checkpoint after explicit operator
   selection

The default containers are `user-documents`, `group-documents`,
`public-documents`, `group-chat`, and `personal-chat`.

### Resume State

The script writes an atomic JSON checkpoint for each container. Rerunning the
same command skips containers marked `completed`. A container left
`in_progress` by termination, or marked `failed` after an AzCopy error, is
started again; AzCopy's copy and sync operations remain non-destructive under
the configured migration mode.

State is bound to both accounts, subscriptions, the ordered container list,
and migration mode. A mismatch requires a different `-StateFilePath` or
explicit `-ResetState`. The file stores resource names, timestamps, status,
attempts, and errors, but never SAS URLs. Default state and temporary files are
ignored by Git; custom repository-local paths should be ignored separately.

### Files

- `scripts/Migration-StorageAccount.ps1`
- `scripts/Migration-State.ps1`
- `functional_tests/test_storage_account_migration_differential_mode.py`
- `application/single_app/config.py`

## Usage

After replacing the four placeholders in the script parameter block, run a
differential migration with the configured defaults:

```powershell
.\scripts\Migration-StorageAccount.ps1
```

Override the configured defaults at invocation:

```powershell
.\scripts\Migration-StorageAccount.ps1 `
    -SourceStorageAccount "sourceaccount" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationStorageAccount "destinationaccount" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002"
```

Run a full overwrite migration for selected containers:

```powershell
.\scripts\Migration-StorageAccount.ps1 `
    -SourceStorageAccount "sourceaccount" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationStorageAccount "destinationaccount" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002" `
    -Containers @("user-documents", "group-documents") `
    -DifferentialMigration $false
```

Disable PowerShell progress records for automation:

```powershell
-ShowProgress $false
```

Rerun the same command after interruption to skip completed containers and
restart the active one. Add `-ResetState` only when every configured container
should be transferred again.

## Testing and Validation

The functional test runs the script against mocked Azure PowerShell and AzCopy
commands. It validates parameter overrides, subscription-scoped context
creation, missing destination-container creation, SAS lifetime and HTTPS
settings, progress reporting, differential and full argument contracts, and
nonzero AzCopy exit handling. It also validates atomic, SAS-free state,
completed-container resume behavior, and failed-container recording.

The script migrates Blob containers only. It does not migrate Azure Files,
queues, tables, account-level networking, lifecycle policies, immutability
policies, or other storage-account configuration.