# Migration Provenance

Implemented in version: **0.250.074**
Updated in version: **0.250.077**

## Overview

Cosmos DB, Azure AI Search, and Azure Storage Account migration scripts now attach durable provenance to successfully migrated items. The provenance makes it possible to recognize a migration run without retaining local copies of the migrated content, and it prevents reprocessing items from the same run or a recent migration window.

## Dependencies

- PowerShell 7.
- Azure Cosmos DB SQL API access for Cosmos migrations.
- Azure AI Search admin keys or Azure resource permissions for Search migrations.
- Az.Accounts and Az.Storage access for Storage migrations. Storage metadata updates use the destination blob metadata object exposed by `Get-AzStorageBlob`.

## Technical Specifications

### Shared Migration Identity

`scripts/Migration-State.ps1` now persists one migration GUID and its start timestamp in each state file. The scripts accept these common parameters:

- `-MigrationId <guid>`: optional. When omitted, the script generates a GUID. Pass the same GUID to the Cosmos, AI Search, and Storage scripts to associate the complete environment migration.
- `-SkipMigratedWithinHours <0-8760>`: defaults to `24`. A value of `0` disables age-based bypassing but continues to bypass successful items associated with the current migration GUID.

Resuming with the same state file preserves its GUID. Supplying a different GUID with an existing state file fails safely unless `-ResetState` is used.

### Metadata Format

All successful migrations record the following values:

| Value | Purpose |
| --- | --- |
| `migrationId` / `simplechatMigrationId` | GUID for the migration run. |
| `migratedAtUtc` / `simplechatMigratedAtUtc` | UTC ISO 8601 migration timestamp. |
| `status` / `simplechatMigrationStatus` | `succeeded` after the target write completes. |

The physical representation is destination-specific:

- Cosmos documents receive a `simplechatMigration` object.
- AI Search indexes receive `simplechatMigrationId`, `simplechatMigratedAtUtc`, and `simplechatMigrationStatus` fields. The fields are filterable and retrievable so the migration can query them safely.
- Storage blobs receive the equivalent values as blob metadata. Existing blob metadata is read and merged before the migration values are written.

The in-app Data Management migration extends this shared identity with source comparison fields in version `0.250.077`: Cosmos source `_ts` plus canonical content SHA-256, AI Search canonical source SHA-256, Blob ETag/last-modified/size plus MD5 when available, and a non-reversible Blob scope hash used to constrain selected-scope mirror deletion. Blob transfers use a `pending` status until source/destination verification succeeds.

### Replay Avoidance

- Cosmos differential migrations retain their existing conflict-based skip behavior. Full migrations query only destination records with successful matching or recent provenance, including their partition-key values, and skip the matching source identities.
- AI Search full migrations query only destination keys with successful matching or recent provenance. Differential migrations retain their existing destination-key skip behavior.
- Storage migrations evaluate destination metadata for every source blob. When all source blobs in a container are marked by the current or recent migration, the entire container bypasses AzCopy. Otherwise, the existing differential or full AzCopy behavior runs and successful destination blobs are stamped afterward.

Failed Cosmos document writes are retained as explicit failure records in the migration state file. A destination item is never stamped `succeeded` unless its target write completed; an item with no durable destination copy remains eligible for a later retry.

## Usage

Generate one GUID before a coordinated migration:

```powershell
$migrationId = [Guid]::NewGuid().ToString("D")
```

Pass it to each migration script:

```powershell
.\scripts\Migration-Cosmos.ps1 -MigrationId $migrationId
.\scripts\Migration-AISearch.ps1 -MigrationId $migrationId
.\scripts\Migration-StorageAccount.ps1 -MigrationId $migrationId
```

To choose a six-hour replay window, include `-SkipMigratedWithinHours 6`. Use `-SkipMigratedWithinHours 0` when only the current migration GUID should bypass already marked items.

## Testing And Validation

- `functional_tests/test_migration_provenance.py`
- `functional_tests/test_cosmos_migration_document_skip_reporting.py`
- `functional_tests/test_ai_search_migration_provenance.py`
- `functional_tests/test_storage_migration_provenance.py`

The coverage verifies GUID persistence, standardized metadata, preservation of existing blob metadata, full-mode Cosmos and AI Search destination bypassing, Storage replay avoidance, and existing error/retry behavior.

## Limitations

- Provenance applies to items successfully written to the destination. A failed write has no target item to tag, so its failure is recorded in migration state rather than as destination metadata.
- Storage container bypassing requires every current source blob to have eligible destination provenance. A container with new or unmarked blobs continues through the existing AzCopy flow, which remains non-destructive in differential mode.

## Version References

- Application implementation extended in `application/single_app/config.py` version `0.250.077`.
- Functional tests and this document use the same implementation version.