# Cosmos DB Migration

## Overview

The Cosmos DB migration script copies every container definition and document
from one Azure Cosmos DB for NoSQL database to another. Containers are
discovered from the source database at runtime, so new SimpleChat containers
are included without maintaining a static allowlist.

The admin application settings document is intentionally excluded in every
migration mode. The destination `settings/app_settings` document remains
unchanged so environment-specific endpoints, credentials, authentication, and
feature configuration are not copied from the source deployment. Other
documents in the `settings` container are migrated normally.

Implemented in version: **0.250.063**

Resumable JSON checkpointing added in version: **0.250.064**

Selective one-or-more container migration added in version: **0.250.066**

REST container payload and document-feed compatibility fixed in version:
**0.250.067**

Per-document console progress added in version: **0.250.068**

Bounded parallel document writes added in version: **0.250.069**

Backpressured page-by-page copying added in version: **0.250.070**

Exact source document totals in progress added in version: **0.250.071**

Simplified parallel progress added in version: **0.250.072**

The application version was updated in `application/single_app/config.py` for
this feature.

### Dependencies

- PowerShell 7
- The `Az.Accounts` PowerShell module when account keys are resolved
  automatically
- Source and destination Azure Cosmos DB for NoSQL accounts
- Permission to list keys for both accounts, or both primary keys supplied
- Network access to both Cosmos DB data-plane endpoints
- Sufficient provisioned or serverless capacity in the destination account

## Technical Specifications

### Architecture

The script uses the Cosmos DB data-plane REST API to:

1. Validate account, subscription, database, and endpoint configuration.
2. Resolve account primary keys through Azure Resource Manager when keys are
   not supplied explicitly.
3. Verify the source database and create the destination database when it is
   missing.
4. Read every source and destination container definition through paged
   container feeds.
5. Create missing destination containers or update compatible definitions,
   depending on the migration mode.
6. Stream source documents through the raw REST read feed and continuation
  tokens without requiring SDK query-plan execution.
7. Remove Cosmos-managed document properties and derive partition-key headers
   from each container definition, including nested and hierarchical paths.
8. Retry transient HTTP 408, 429, 449, 500, and 503 responses, honoring the
   Cosmos DB retry delay when provided.
9. Report overall container progress plus the current document ID, processed
  count, result, and copied/skipped totals for the active container.

Container definitions are rebuilt from an allowlist of writable, non-null
properties. Read-response metadata such as `backupPolicy`, `statistics`,
`etag`, `rid`, `ts`, and `partitionKey.systemKey` is omitted. JSON array shapes
inside indexing policies are retained. The script also strips document
properties such as `_rid`, `_self`, `_etag`, `_attachments`, and `_ts` before
destination writes. User-defined fields, including item-level `ttl`, remain
intact.

### Admin Settings Exclusion

The `settings` container is read through the same paged document feed as other
containers. A document whose ID is exactly `app_settings` is discarded before
it enters the destination write path. This exclusion cannot be disabled with
a script parameter.

User preferences in the `user_settings` container and non-admin operational
documents in the `settings` container are still migrated.

### Migration Modes

Differential mode is enabled by default with
`-DifferentialMigration $true`.

- Missing destination databases and containers are created.
- Existing destination container definitions are retained.
- Documents are sent as create-only operations.
- A document conflict is counted as skipped, so existing destination content
  is not overwritten.
- Destination-only containers and documents are never deleted.

Full mode is selected with `-DifferentialMigration $false`.

- Missing destination databases and containers are created.
- Existing compatible container definitions are updated from the source.
- Source documents are upserted, replacing destination documents with the
  same ID and logical partition key.
- Destination-only containers and documents are still not deleted.
- `settings/app_settings` is still excluded and remains unchanged.

Cosmos DB partition keys are immutable. The script compares source and
destination partition-key definitions before writing an existing container
and stops with an actionable error when they are incompatible.

### APIs

- Cosmos DB data plane: `2020-07-15` by default
- Cosmos DB management plane: `2025-04-15` by default
- Database read/create operations
- Container list, create, and replace operations
- Paged document read-feed and create/upsert operations
- Azure Resource Manager `listKeys` operation

### Configuration

Source and destination identity values have editable placeholder defaults at
the top of `scripts/Migration-Cosmos.ps1`. Replace them to run without
arguments, or provide named parameters at invocation.

The main parameters are:

- Source account, resource group, subscription ID, and database name
- Destination account, resource group, subscription ID, and database name
- `Containers`, accepting one or more source container names and defaulting to
  all discovered source containers when omitted or empty
- `DifferentialMigration`, defaulting to `$true`
- `ShowProgress`, defaulting to `$true`
- `ProgressUpdateInterval`, defaulting to every 100 documents
- `PageSize`, defaulting to 100 containers or documents per source page
- `MaxConcurrentDocuments`, defaulting to 8 and limited to 1-64
- `MaxRetryCount`, defaulting to 5
- `CosmosDnsSuffix`, configurable for sovereign Azure clouds
- `SourcePrimaryKey` and `DestinationPrimaryKey`, optional alternatives to ARM
  key resolution
- `StateFilePath`, defaulting to `scripts/Migration-Cosmos.state.json`
- `ResetState`, which discards an existing checkpoint after explicit operator
  selection

Account keys should normally be resolved automatically rather than placed in
the script or shell history.

### Resume State

The script writes an atomic JSON checkpoint after starting and completing each
container. Rerunning the same command automatically skips containers marked
`completed`. A container left `in_progress` by termination, or marked `failed`
after a handled error, is replayed from its beginning; document writes are
safe to repeat in both migration modes.

The state file is bound to the source, destination, selected container set,
selection mode, migration mode, API version, and admin-settings exclusion. A
mismatch stops the run instead of applying an old checkpoint to different
resources. Use a separate `-StateFilePath` for a different migration, or pass
`-ResetState` to deliberately start over.

State includes resource names, timestamps, status, attempts, counts, and error
text. Account keys and document contents are never persisted. The default
state file and atomic temporary files are ignored by Git. A custom path should
also be excluded when it is placed inside the repository.

### Console Progress

Progress uses two PowerShell bars:

- The overall bar shows completed containers, total containers, remaining
  containers, and percentage complete.
- The active-container bar uses Cosmos management metadata to show processed
  documents, source total, remaining documents, and percentage. Before each
  write, it shows `Copying document N: '<id>'`; after the write, it shows
  whether the document was copied or skipped plus cumulative counts.

The total lookup first uses statistics already present on the container,
then tries Azure PowerShell ARM and Azure CLI ARM. It is best-effort: if no
management authentication is available, migration continues and reports
`Total: unavailable` rather than failing.

`ProgressUpdateInterval` defaults to `100` to limit terminal rendering
overhead. Set it to `1` when every document ID and result should be visible.
Parallel concurrency and transient retries remain active but are intentionally
not displayed. Retry counts remain available in the container checkpoint
result for diagnostics.

### Files

- `scripts/Migration-Cosmos.ps1`
- `scripts/Migration-State.ps1`
- `functional_tests/test_cosmos_all_containers_migration.py`
- `functional_tests/test_cosmos_parallel_document_writes.py`
- `application/single_app/config.py`

## Usage

After replacing the source and destination placeholders in the parameter
block, run the default differential migration:

```powershell
.\scripts\Migration-Cosmos.ps1
```

Run a differential migration with invocation-time values:

```powershell
.\scripts\Migration-Cosmos.ps1 `
    -SourceCosmosAccount "source-cosmos" `
    -SourceResourceGroup "source-rg" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -SourceDatabaseName "SimpleChat" `
    -DestinationCosmosAccount "destination-cosmos" `
    -DestinationResourceGroup "destination-rg" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002" `
    -DestinationDatabaseName "SimpleChat"
```

Run a full overwrite-by-source migration:

```powershell
.\scripts\Migration-Cosmos.ps1 `
    -SourceCosmosAccount "source-cosmos" `
    -SourceResourceGroup "source-rg" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationCosmosAccount "destination-cosmos" `
    -DestinationResourceGroup "destination-rg" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002" `
    -DifferentialMigration $false
```

  Migrate one container:

  ```powershell
  .\scripts\Migration-Cosmos.ps1 `
    -SourceCosmosAccount "source-cosmos" `
    -SourceResourceGroup "source-rg" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationCosmosAccount "destination-cosmos" `
    -DestinationResourceGroup "destination-rg" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002" `
    -Containers "documents"
  ```

  Migrate multiple containers:

  ```powershell
  .\scripts\Migration-Cosmos.ps1 `
    -SourceCosmosAccount "source-cosmos" `
    -SourceResourceGroup "source-rg" `
    -SourceSubscriptionId "00000000-0000-0000-0000-000000000001" `
    -DestinationCosmosAccount "destination-cosmos" `
    -DestinationResourceGroup "destination-rg" `
    -DestinationSubscriptionId "00000000-0000-0000-0000-000000000002" `
    -Containers @("documents", "group_documents", "public_documents")
  ```

  Container names are case-sensitive. Empty, duplicate, invalid, or missing
  source names stop the migration before destination database or container
  writes. Omitting `-Containers` retains the all-container behavior.

Disable interactive progress records for automation:

```powershell
-ShowProgress $false
```

For Azure Government, set the appropriate Cosmos DB DNS suffix:

```powershell
-CosmosDnsSuffix "documents.azure.us"
```

If a run is interrupted, rerun the same command to resume from the JSON state.
To intentionally repeat every container, add `-ResetState`.

Use the default eight concurrent document writes:

```powershell
.\scripts\Migration-Cosmos.ps1 -MaxConcurrentDocuments 8
```

Use the original sequential write path:

```powershell
.\scripts\Migration-Cosmos.ps1 -MaxConcurrentDocuments 1
```

If HTTP 429 retries are frequent, lower concurrency. Raise it cautiously only
when the destination has enough RU/s and the migration host has sufficient
CPU and network capacity.

## Testing and Validation

The functional test executes differential and full migration against mocked
Cosmos DB and Azure Resource Manager APIs. It validates:

- Source container discovery and continuation-token paging
- Missing database and container creation
- Differential create-only writes and conflict skips
- Full container updates and document upserts
- Permanent exclusion of `settings/app_settings`
- Preservation of destination-only documents
- Source document read-feed continuation paging
- Page-one destination writes before requesting the next source continuation
  page, preventing whole-container buffering
- Container response-metadata removal, indexing-policy JSON array retention,
  document system-property removal, and nested partition-key extraction
- HTTP 429 retry behavior and progress reporting
- Automatic account-key resolution paths
- Atomic, secret-free state creation and completed-container resume behavior
- Single and multiple container selection, normalized checkpoint scope, and
  rejection of missing or changed selections
- Per-document pre-write IDs, post-write results, and cumulative copied/skipped
  progress
- Bounded parallel differential creates/conflicts, full upserts, hidden
  internal concurrency/retry details, and independent HTTP 429 retry-after
  handling

Run the focused test with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q functional_tests\test_cosmos_all_containers_migration.py
```

### Performance Considerations

- Documents are streamed page by page and written in bounded parallel batches
  rather than loaded into memory as one database-sized collection. A batch is
  limited to the smaller of `PageSize` and four times the concurrency setting.
- `Invoke-WebRequest` must finish downloading one JSON page before PowerShell
  can parse its documents. Lower `PageSize` to start writes sooner and reduce
  per-page memory, or raise it to reduce source read requests.
- Raw REST does not issue a cross-partition aggregate solely to determine a
  total. A lightweight ARM container metadata read supplies `documentCount`
  without scanning document content or delaying the read feed. Current IDs and
  counts update at the configured progress interval.
- Containers remain sequential so one parent owns checkpoint and schema state.
  Within a container, up to `MaxConcurrentDocuments` REST writes run in a
  PowerShell runspace pool. Each write retains its own partition-key header.
- Transient writes retry independently. One worker honoring a 429 retry-after
  delay does not block successful writes in other workers.
- Differential mode avoids a destination-wide key scan. Existing identities
  are rejected by Cosmos DB with HTTP 409 and counted as skipped.
- Source data should be quiesced for a strict point-in-time copy because
  read-feed paging does not create a database snapshot.
- Lower `PageSize` when containers hold documents near the Cosmos DB item-size
  limit or when the migration host has constrained memory.

### Known Limitations

- Account-level settings, networking, firewall rules, private endpoints,
  consistency policy, regions, backup policy, and managed identities are not
  migrated.
- Provisioned throughput and autoscale settings are not copied. Configure
  destination capacity before migration when the target is not serverless or
  does not already use shared database throughput.
- Stored procedures, triggers, user-defined functions, conflicts, users,
  permissions, and legacy attachments are not copied.
- Existing destination containers must use the same partition-key definition
  as the source. Recreate an incompatible destination container separately
  before migration.
- Both accounts must expose the Azure Cosmos DB for NoSQL REST API and support
  the source container features.