---
layout: page
title: "Backup & Recovery settings"
description: "Backup & Recovery contains backup readiness, scheduled backups, migration, restore, backup inventory, job history, and Cosmos JSON repair tools."
section: "Administration"
audience: admin
admin_tab: backup-recovery
redirect_from:
  - /admin/data-management/
---


# Backup & Recovery settings

## What this group controls

Backup & Recovery contains backup readiness, scheduled backups, migration, restore, backup inventory, job history, and Cosmos JSON repair tools.

## Why it matters

These settings protect the data plane during maintenance and incidents. A backup configuration is useful only when storage, encryption, restore policy, and job visibility are tested before an emergency.

{% include media.html src="admin/backup-recovery-overview.png" alt="Screenshot placeholder for the Backup & Recovery group in Admin Settings." title="Backup & Recovery settings" capture="Capture the Backup & Recovery group in Admin Settings showing its tabs." %}

{% include media.html type="video" title="Backup & Recovery settings walkthrough" poster="video-posters/admin-backup-recovery.png" capture="Recording planned. Walk through each tab in the Backup & Recovery group and explain when to change each setting." %}

## Before you change anything

- Prepare storage and encryption values before scheduling backups.
- Review restore collision policy with data owners.
- Limit Cosmos editor use to operators who understand partition keys and ETags.

## How saving works

Backup & Recovery settings are kept in their own settings document, separate from the rest of Admin Settings. In the V2 admin experience they still share the page's Save bar: an edit in any Backup & Recovery card counts as an unsaved change, **Save changes** saves the other Admin Settings first and then the Backup & Recovery settings, and **Discard** drops both.

Several actions run against the saved settings, because the server reads them again and checks review fingerprints against them. Queueing a backup, running retention cleanup, reviewing or queueing a restore, and starting a migration save pending Backup & Recovery changes first, and their buttons say so, for example **Save and queue full backup**. Retrying or resuming a job never saves settings: a backup resumes into the storage it started with, and is refused if the saved storage settings have since moved it somewhere else.

Backup storage is validated against the saved Enhanced Citations storage, and a new encryption key is stored where the saved Key Vault settings say. When one of those settings has an unsaved edit, the action asks to **Save all and continue** instead of checking against a value that is about to change. Leaving the page with unsaved changes, or while a Backup & Recovery request is still being sent, asks for confirmation first.

## Backup {#backup}

### Start Here {#data-management-readiness-section}

Start Here is the readiness view for the whole group. It checks backup storage, the encryption key, the schedule, the latest full backup, and the restore and migration destination, and each item opens the section that resolves it. It also holds short guides to setup, backups, migration, restore, and RU Boost permissions.

### Backup {#data-management-backup-section}

Queue a full or partial backup on demand and see the latest completed full and partial backups. A backup runs against the saved settings, so unsaved Backup & Recovery changes are saved before it is queued.

The performance settings set how many Cosmos DB batches and source-file transfers run in parallel, the transfer chunk size, and how many times a failed operation is retried. Source RU Boost temporarily raises eligible throughput on the source Cosmos DB account, up to 10,000 RU/s, and restores the original setting after the backup completes, fails, is canceled, or recovers. It can increase Azure charges and needs Azure Resource Manager permission on the source account.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Concurrent batch staging | Controls how many Cosmos DB export batches are prepared at the same time. Raise it only when the source account has enough RU headroom; the server clamps it to 1-16. | 4 | `data_management_backup_max_parallel_operations` |
| Retry attempts | Retries throttled or failed Cosmos DB and AI Search backup work before the resource is recorded as failed. Use a higher value for noisy maintenance windows; the server clamps it to 1-10. | 5 | `data_management_backup_retry_count` |
| If source RU Boost is unavailable | Chooses whether a backup that asked for source RU Boost should keep running at the current throughput or stop before exporting. | Continue without the boost | `data_management_backup_capacity_failure_policy` |
| Source RU Boost for backups | Temporarily raises eligible source Cosmos DB throughput for backup jobs, then restores the original throughput when the job completes, fails, is canceled, or recovers. Leave it off unless the source account can absorb the extra cost and the app identity can manage throughput. | Off | `data_management_backup_temporary_source_ru_enabled` |
| Source RU Boost target | Target throughput for eligible source Cosmos DB targets while backup RU Boost is on. The server clamps the value to 1,000-10,000 RU/s. | 10,000 RU/s | `data_management_backup_temporary_source_ru` |
| Concurrent file transfers | Copies Enhanced Citation source files in parallel. Increase it for faster file backups only when storage throttling is not a problem; the server clamps it to 1-8 and can temporarily lower active transfers while throttled. | 4 | `data_management_backup_blob_max_parallel_operations` |
| Transfer chunk size (MiB) | Streams each source file through chunks of this size. Larger chunks can improve throughput but increase memory pressure; the server clamps it to 1-16 MiB. | 8 MiB | `data_management_backup_blob_chunk_size_mib` |
| File retry attempts | Retries failed source-file transfers before the file is marked failed. Use a higher value when storage is transiently throttled; the server clamps it to 1-10. | 5 | `data_management_backup_blob_retry_count` |

### Schedule {#data-management-schedule-section}

Scheduled backups take a full backup at the chosen frequency and UTC start time, with optional daily partial backups in between. A partial backup captures changed items; restoring one brings back the latest captured state and does not replay deletions.

The retention window sets how long backups are kept. Retention cleanup deletes finished backups older than the window but, by default, keeps the newest successful full backup, and each run deletes at most 25 backups. While scheduled backups are on, cleanup also runs on its own. The backup scope chooses what each backup includes: Cosmos DB, AI Search, and Enhanced Citation source files.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Scheduled backups | Lets SimpleChat queue full backups on the selected cadence and daily partial backups when they are enabled. Keep it off when backups should run only from an admin's manual queue action. | Off | `data_management_enabled` |
| Full backup frequency | Chooses how often a complete backup snapshot is scheduled: daily, weekly, every 14 days, or every 30 days. | Weekly | `data_management_full_frequency` |
| Start time (UTC) | Schedules backup jobs at this UTC time. Invalid or out-of-range values are normalized back to 03:00; valid times are 00:00 through 23:59. | 03:00 | `data_management_scheduled_time_utc` |
| Keep backups for | Number used with the retention unit to compute the retention window. Cleanup deletes completed backups older than that window and, by default, keeps the newest successful full backup; the derived value is capped at 3,650 days. | 30 | `data_management_retention_value` |
| Retention unit | Unit for the retention value. The server accepts days, weeks, months, and years, using 1, 7, 30, and 365 days respectively, and clamps the value so the final window stays within 3,650 days. | Days | `data_management_retention_unit` |
| Daily partial backups | Captures changed items each day between full backups. Use it when recovery point freshness matters, knowing a partial restore does not replay deletions. | On | `data_management_partial_enabled` |
| Use low-impact mode for scheduled jobs | Saves the operator preference alongside the schedule. The current backend stores this value but does not use it to change backup, restore, or migration behavior. | On | `data_management_low_impact_mode` |
| Cosmos DB records | Includes the Cosmos DB artifact containers defined for data management, covering settings plus workspace, conversation, document, agent, action, prompt, and identity categories. Restore and migration are only meaningful when this surface is included. | On | `data_management_include_cosmos` |
| AI Search indexes | Includes AI Search index schemas and retrievable indexed documents for personal, group, and public workspaces. Leave it on when restored or migrated chat search should work without rebuilding indexes. | On | `data_management_include_ai_search` |
| Source document files | Includes original Enhanced Citation source files. The stored default is On, but the server forces it Off and V2 locks the control while Enhanced Citations is disabled. | On when Enhanced Citations is enabled; Off otherwise | `data_management_include_source_blobs` |

### Storage {#data-management-storage-section}

Backups are written to a container in an Azure Storage account dedicated to backups, under the path prefix. SimpleChat signs in with managed identity or a connection string. While Enhanced Citations is on, saving is refused if backup storage uses the same connection string or Blob endpoint as Enhanced Citations storage.

Test storage checks the values on screen without saving them, and creates the container when it does not exist. Each backup records the container, path prefix, and storage identity it was written with, and restore review rejects a backup when those no longer match.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Authentication | Selects how SimpleChat reaches the backup storage account. Managed identity uses the Blob endpoint; connection string uses the secret and clears the endpoint when saved. | Managed identity | `data_management_storage_auth` |
| Blob endpoint | Backup storage account endpoint used with managed identity, for example `https://account.blob.core.windows.net`. Use a storage account dedicated to backups, not the Enhanced Citations account. | Empty | `data_management_blob_endpoint` |
| Connection string | Backup storage connection string used only when Authentication is Connection string. The server clears it when managed identity is selected and redacts stored values in the admin API. | Empty | `data_management_connection_string` |
| Container | Container that holds backup artifacts. Test storage creates it if it is missing, and restore review checks older backups against the container recorded when they were written. | `simplechat-backups` | `data_management_container_name` |
| Path prefix | Folder-like prefix inside the container for backup artifacts. Leading and trailing slashes are stripped, and an empty value is normalized to the default. | `simplechat-backups` | `data_management_path_prefix` |

### Encryption {#data-management-encryption-section}

Backup artifacts are encrypted with a generated backup key before they are written. The key is stored in Key Vault when Key Vault secret storage is configured, and otherwise in the Backup & Recovery settings. Restore review checks each backup against the encryption mode and key it was written with: turning encryption on or off, or replacing a key stored in settings, makes earlier backups fail review until the settings match again. Backups encrypted with a Key Vault key keep the secret version they used.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Encrypt backup files | Encrypts every backup artifact before it is written to backup storage. Keep it on unless you are deliberately testing unencrypted artifacts in an isolated environment. | On | `data_management_encryption_enabled` |

## Migrate {#migrate}

### Migration {#data-management-migration-section}

Migration copies selected users, groups, and public workspaces, and optionally their documents, into another SimpleChat environment. It runs in six steps: connect the destination Cosmos DB, AI Search, and Enhanced Citation storage; choose the scope; choose the run mode, optional surfaces, and performance limits; run the server preflight review; confirm; and follow progress.

There are three run modes. **Copy missing items only** never updates or deletes existing destination data. **Catch up changed items** also updates changed items that an earlier migration created, and keeps data that exists only in the destination. **Make destination match source** additionally deletes destination items that earlier migrations created and the source no longer has, and requires typing `MAKE DESTINATION MATCH SOURCE`. A migration starts only from a current review: changing the plan or the destination settings afterwards means running the review again. Restore writes into the same destination.

Choosing **All** for users, groups, or public workspaces asks the server for that scope's count and shows it in the Scope step and header. If a count cannot load, **Retry count** asks again; the wizard can still continue, because the server review counts the records itself. When every included scope has been counted and the total is 0, the Scope step blocks review until at least one user, group, or public workspace is included. The Confirm step shows the server-normalized review plan: principal scopes, included documents, synchronization mode, creates and updates, deletes, and conflicts.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Destination Cosmos DB authentication | Chooses managed identity or an account key for the destination Cosmos DB account. Managed identity needs Cosmos DB Data Contributor and network access to the destination. | Managed identity | `data_management_target_cosmos_auth` |
| Destination Cosmos DB endpoint | Destination account endpoint used by migration and restore reviews. Leave it empty until a target SimpleChat environment is ready. | Empty | `data_management_target_cosmos_endpoint` |
| Destination Cosmos DB database | Fixed database name SimpleChat writes to in the destination environment. It is shown for review but is not editable. | `SimpleChat` | `data_management_target_cosmos_database` |
| Destination Cosmos DB account key | Secret used only when Destination Cosmos DB authentication is Account key. The server clears it when managed identity is selected and redacts stored values in the admin API. | Empty | `data_management_target_cosmos_key` |
| Destination AI Search authentication | Chooses managed identity or an admin key for destination AI Search. Managed identity needs permission to inspect and write the expected indexes. | Managed identity | `data_management_target_ai_search_auth` |
| Destination AI Search endpoint | Search service endpoint used when AI Search documents are included in a migration or restore review. | Empty | `data_management_target_ai_search_endpoint` |
| Destination AI Search admin key | Secret used only when Destination AI Search authentication is Admin key. The server clears it when managed identity is selected and redacts stored values in the admin API. | Empty | `data_management_target_ai_search_key` |
| Destination Enhanced Citation storage authentication | Chooses managed identity or a connection string for the destination storage account that receives selected source document files. | Managed identity | `data_management_target_ec_storage_auth` |
| Destination Enhanced Citation storage Blob endpoint | Destination storage Blob endpoint used with managed identity when source document files are included. | Empty | `data_management_target_ec_blob_endpoint` |
| Destination Enhanced Citation storage connection string | Secret used only when destination Enhanced Citation storage authentication is Connection string. The server clears it when managed identity is selected and redacts stored values in the admin API. | Empty | `data_management_target_ec_connection_string` |
| Destination Cosmos subscription ID | Azure subscription for the destination Cosmos DB account. It is required only when testing or using destination RU Boost. | Empty | `data_management_target_cosmos_subscription_id` |
| Destination Cosmos resource group | Azure resource group for the destination Cosmos DB account. It is required only when testing or using destination RU Boost. | Empty | `data_management_target_cosmos_resource_group` |
| User migration scope | Runtime choice for skipping users, selecting users from the catalog, or migrating all users. It is part of the reviewed migration plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_users_mode_choice` |
| Search users | Filters the server catalog while choosing selected users. The search text is not saved with Backup & Recovery settings. | N/A (runtime control) | `data_management_migration_users_search` |
| Include users' documents | Adds the selected users' personal document records when the user scope is not skipped. It is reviewed with the migration plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_users_documents` |
| Group migration scope | Runtime choice for skipping groups, selecting groups from the catalog, or migrating all groups. It is part of the reviewed migration plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_groups_mode_choice` |
| Search groups | Filters the server catalog while choosing selected groups. The search text is not saved with Backup & Recovery settings. | N/A (runtime control) | `data_management_migration_groups_search` |
| Include group documents | Adds document records for the selected groups when the group scope is not skipped. It is reviewed with the migration plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_groups_documents` |
| Public workspace migration scope | Runtime choice for skipping public workspaces, selecting workspaces from the catalog, or migrating all public workspaces. It is part of the reviewed migration plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_public_workspaces_mode_choice` |
| Search public workspaces | Filters the server catalog while choosing selected public workspaces. The search text is not saved with Backup & Recovery settings. | N/A (runtime control) | `data_management_migration_public_workspaces_search` |
| Include public workspace documents | Adds document records for selected public workspaces when that scope is not skipped. It is reviewed with the migration plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_public_workspaces_documents` |
| Migration mode | Runtime choice for copying only missing items, catching up changed items, or making the destination match the source. The wizard starts on Copy missing items only and the selected mode is reviewed before execution. | N/A (runtime control) | `data_management_migration_mode` |
| Previous completed migration job ID | Optional baseline for catch-up and mirror runs. Leaving it blank lets SimpleChat choose the latest compatible completed migration. | N/A (runtime control) | `data_management_migration_baseline_job_id` |
| Migrate matching AI Search documents | Adds destination AI Search reconciliation for records that match the selected migration scopes. This is part of the reviewed plan and is not saved as a setting. | N/A (runtime control) | `data_management_migration_include_ai_search` |
| I confirm external destination AI Search writers are frozen | Required acknowledgement when AI Search documents are included. SimpleChat pauses its own target indexing, but admins must freeze other destination writers before review. | N/A (runtime control) | `data_management_migration_target_search_writes_frozen` |
| Migrate the selected source document files | Copies source document files for the selected scopes. Use it only when Enhanced Citation storage is configured for both source and destination. | N/A (runtime control) | `data_management_migration_include_source_blobs` |
| Concurrent operations | Limits how many migration operations run at once. Raise it for faster migrations only when the destination can handle the load; the server clamps it to 1-32. | 8 | `data_management_migration_max_parallel_operations` |
| Retry attempts | Retries failed migration operations before recording them as failed. Increase it for transient destination throttling; the server clamps it to 1-10. | 5 | `data_management_migration_retry_count` |
| Skip items migrated in the last (hours) | Skips items an earlier run copied successfully within this window. Use it to avoid reprocessing recent successes during resume-style runs; 0 skips nothing, and the server clamps the value to 0-8,760 hours. | 0 | `data_management_migration_skip_recent_within_hours` |
| Destination RU Boost for this migration | Temporarily raises eligible destination Cosmos DB throughput during migration and restores it after completion or failure. Use only when the destination account can accept the extra cost and the app identity can manage throughput. | Off | `data_management_migration_temporary_destination_ru_enabled` |
| Destination RU Boost target | Target throughput for eligible destination Cosmos DB targets while migration RU Boost is on. The server clamps the value to 1,000-10,000 RU/s. | 10,000 RU/s | `data_management_migration_temporary_destination_ru` |
| Type MAKE DESTINATION MATCH SOURCE to authorize this run | Required phrase for mirror migrations because that mode can delete destination items created by earlier migrations when they no longer exist in the source. | N/A (runtime control) | `data_management_migration_mirror_confirmation_phrase` |
| I reviewed the normalized plan, destination checks, warnings, and operational impact. | Final acknowledgement that enables execution after a current migration review. It is cleared when the plan or destination settings change. | N/A (runtime control) | `data_management_migration_final_confirmation` |

## Restore {#restore}

### Backup Inventory & Restore {#data-management-backup-inventory-section}

Backup Inventory lists backups with their type, contents, warnings, and encryption, filtered by status, run type, and creation date. Selecting a backup shows its manifest and storage details, and the Restore and Delete actions. **Run retention cleanup** applies the retention window on demand.

Restore writes into the destination configured in Migration and is available for completed backups that recorded a manifest. **Create only** never replaces destination data: the review blocks the restore when the destination Cosmos DB containers or AI Search indexes already hold data, and source files that already exist are skipped and reported as collisions. **Overwrite existing** can replace destination data and requires typing `RESTORE WITH OVERWRITE`. A restore is queued only after a passing review that is still current and an acknowledgement; the review authorization expires after 15 minutes.

The destination is required only for the surfaces selected in the Restore dialog. Cosmos DB restores require the destination Cosmos DB endpoint, AI Search restores require the destination AI Search endpoint, and file restores require either the destination Enhanced Citation storage Blob endpoint for managed identity or its connection string for connection-string sign-in. The dialog names any selected surface whose destination is missing before review or queueing.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Status | Filters the backup inventory by availability or job status. The inventory opens on Available so admins see restorable backups first. | N/A (runtime control) | `data_management_backup_status_filter` |
| Run type | Filters the backup inventory to scheduled backups, manual backups, or both. | N/A (runtime control) | `data_management_backup_scheduled_filter` |
| Created from | Start date for the backup inventory created-date filter. Leave both dates blank, or choose both dates; an incomplete range, invalid date, end date before the start date, or inclusive range over 366 days pauses loading until corrected. | N/A (runtime control) | `data_management_backup_created_from` |
| Created through | End date for the backup inventory created-date filter. When both dates are valid, the request sends `created_from` and `created_to` together. | N/A (runtime control) | `data_management_backup_created_to` |
| Rows per page | Controls backup inventory paging. Available choices are 10, 25, 50, and 100 rows, and the workbench opens at 25. | N/A (runtime control) | `data_management_backup_page_size` |
| Collision policy | Restore dialog policy for existing destination data. Each dialog opens on Create only; Overwrite existing requires a passing review and the exact overwrite phrase. | N/A (runtime control) | `data_management_restore_policy` |
| Cosmos DB | Includes Cosmos DB records from the selected backup in the restore plan. The dialog opens with this surface selected, and the choice is reviewed before queueing. | N/A (runtime control) | `data_management_restore_include_cosmos` |
| AI Search | Includes AI Search artifacts from the selected backup in the restore plan. The dialog opens with this surface selected, and the choice is reviewed before queueing. | N/A (runtime control) | `data_management_restore_include_ai_search` |
| Enhanced Citation files | Includes source document files from the selected backup in the restore plan. The dialog opens with this surface selected, and the choice is reviewed before queueing. | N/A (runtime control) | `data_management_restore_include_source_blobs` |
| Type the overwrite confirmation phrase | Required phrase for Overwrite existing restores: `RESTORE WITH OVERWRITE`. It is not part of the review fingerprint, but queueing requires it for destructive restores. | N/A (runtime control) | `data_management_restore_overwrite_confirmation_phrase` |
| I reviewed the restore target, policy, and preflight result. | Final restore acknowledgement. It is cleared when restore inputs change and is required before queueing a reviewed restore. | N/A (runtime control) | `data_management_restore_final_confirmation` |

## Cosmos Editor {#cosmos-editor}

### Cosmos Editor {#data-management-cosmos-editor-section}

The Cosmos Editor repairs one document at a time in a known SimpleChat Cosmos DB container. It stays locked until an administrator acknowledges the risk, and the acknowledgement, queries, document opens, and saves are recorded in activity logs. A blank query browses the first 100 documents; a custom `SELECT` query can page further. The editor refuses changes to a document's id or partition key, and a save requires typing `I understand this can damage system data`. Saves use the ETag from when the document was opened, so a document changed by someone else in the meantime is not overwritten.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Container | Runtime choice of a known SimpleChat Cosmos DB container. Changing containers closes any open JSON draft so edits cannot be applied to the wrong container. | N/A (runtime control) | `data_management_cosmos_editor_container` |
| Page size | Limits query results per request. The editor starts at 100, and V2 clamps edits to 1-100 before querying. | N/A (runtime control) | `data_management_cosmos_editor_page_size` |
| SELECT query | Blank browse lists up to the first 100 document summaries. Custom queries must be `SELECT` statements, are limited to 4,000 characters, and can use Next Page when Cosmos returns a continuation token. | N/A (runtime control) | `data_management_cosmos_editor_query` |
| I understand this editor can damage overall system health. | Unlock acknowledgement for the page session. The server records it in activity logs before live queries are enabled. | N/A (runtime control) | `data_management_cosmos_editor_danger_accept` |
| Document JSON | Editable JSON for the opened document. Saves are guarded by the document's ETag and are rejected if the id or partition key is changed. | N/A (runtime control) | `data_management_cosmos_editor_document_json` |
| Type the confirmation phrase to enable saving | Required phrase for saving a JSON edit: `I understand this can damage system data`. It protects the direct production write path. | N/A (runtime control) | `data_management_cosmos_editor_confirmation_phrase` |

## Jobs {#jobs}

### Jobs {#data-management-jobs-section}

Jobs is the history of backup, restore, migration, and dry-run jobs, newest first, filtered by operation, status, run type, and creation date. Opening a job shows its progress, timeline, artifacts, manifest, and warnings, and follows a running job until it finishes. Retry and Resume continue from durable checkpoints. Cancellation is cooperative: the worker stops at its next durable checkpoint. Migration jobs also offer their manifest, and a manifest of only the failed, missing, and colliding items, for download.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Operation | Filters job history to backup, migration, restore, dry run, or all operations. | N/A (runtime control) | `data_management_job_operation_filter` |
| Status | Filters job history by queued, running, completed, completed with warnings, failed, or canceled status. | N/A (runtime control) | `data_management_job_status_filter` |
| Run type | Filters job history to scheduled jobs, manual jobs, or both. | N/A (runtime control) | `data_management_job_scheduled_filter` |
| Created from | Start date for the job-history created-date filter. Leave both dates blank, or choose both dates; an incomplete range, invalid date, end date before the start date, or inclusive range over 366 days pauses loading until corrected. | N/A (runtime control) | `data_management_job_created_from` |
| Created through | End date for the job-history created-date filter. When both dates are valid, the request sends `created_from` and `created_to` together. | N/A (runtime control) | `data_management_job_created_to` |
| Rows per page | Controls job-history paging. Available choices are 10, 25, 50, and 100 rows, and the workbench opens at 25. | N/A (runtime control) | `data_management_job_page_size` |

## Common tasks

1. **Prepare scheduled backups.** Configure backup, schedule, storage, and encryption, then queue a small backup. Outcome to verify: A backup artifact appears in inventory.
2. **Run restore preflight.** Select a backup, choose restore policy, and run review before queueing. Outcome to verify: Preflight reports target access and collision behavior.
3. **Use Cosmos Editor safely.** Query the target document and review the change summary before saving. Outcome to verify: The intended document updates with ETag protection.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A restore cannot be queued | Preflight found target access, manifest, or collision-policy problems. | Resolve the reported check before queueing. |
| Restore says a destination is missing | One of the selected restore surfaces does not have its matching destination setting configured in Migration. | Set only the destination the selected surface needs, then rerun the review. |
| Saving reports that backup storage must use a dedicated Azure Storage account | Enhanced Citations is on and backup storage uses its connection string or Blob endpoint. | Point backup storage at a separate storage account. |
| An action asks to **Save all and continue** | Enhanced Citations storage or Key Vault settings have unsaved edits that the action is checked against. | Save all changes, or discard those edits, then run the action. |
| Restore review rejects an older backup | The backup storage container, path prefix, storage identity, encryption mode, or a settings-stored key changed after the backup was written. | Change the settings back, or restore from a backup written with the current settings. |
| **Start migration** is unavailable, or returns to the Review step | The plan or destination settings changed after the review, or the review's 15-minute authorization expired. | Run the preflight review again, then confirm. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Scale settings]({{ '/admin/scale/' | relative_url }})
- [Data Lifecycle settings]({{ '/admin/data-lifecycle/' | relative_url }})
