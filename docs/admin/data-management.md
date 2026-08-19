---
layout: page
title: "Backup, Migrate & Restore Settings"
description: "Controls scheduled backup settings and the operational tools for migration, restore, backup inventory, job history, and Cosmos JSON editing."
section: "Administration"
audience: admin
admin_tab: data-management
---

## What this tab controls

Controls scheduled backup settings and the operational tools for migration, restore, backup inventory, job history, and Cosmos JSON editing.

## Why it matters

Backup, migration, restore, and the Cosmos JSON editor are high-impact operations. These controls can preserve a deployment, move it, or damage it. The confirmation fields, collision policies, low-impact mode, retry counts, and RU Boost controls exist because these jobs touch Cosmos DB, AI Search, source blobs, and backup storage.

{% include media.html src="admin/data-management-overview.png" alt="Screenshot of the Backup, Migrate & Restore settings tab showing backup, migrate & restore tab." title="Backup, Migrate & Restore tab" capture="Capture the Backup, Migrate & Restore tab for Backup, Migrate & Restore tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Backup, Migrate & Restore settings walkthrough" poster="video-posters/admin-data-management.png" capture="Recording planned. Walk through every setting on the Backup, Migrate & Restore tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable scheduled backups | Controls how SimpleChat uses enable scheduled backups on this tab. | Off | `data_management_enabled` |
| Full backup frequency | Controls how SimpleChat uses full backup frequency on this tab. | weekly | `data_management_full_frequency` |
| Scheduled time (UTC) | Default is 03:00 UTC. | 03:00 | `data_management_scheduled_time_utc` |
| Delete backups after | Controls how SimpleChat uses delete backups after on this tab. | 30 | `data_management_retention_value` |
| Retention unit | Controls how SimpleChat uses retention unit on this tab. | days | `data_management_retention_unit` |
| Run partial backups daily between full backups | Controls how SimpleChat uses run partial backups daily between full backups on this tab. | On | `data_management_partial_enabled` |
| Use low impact mode for scheduled jobs | Controls how SimpleChat uses use low impact mode for scheduled jobs on this tab. | On | `data_management_low_impact_mode` |
| Include Cosmos DB data | Core application records required for meaningful restore and migration. | On | `data_management_include_cosmos` |
| Include AI Search indexes | Search index schemas and retrievable indexed documents. | On | `data_management_include_ai_search` |
| Include source document blobs | Original source files used by Enhanced Citations. | Off | `data_management_include_source_blobs` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_storage_auth` |
| Blob endpoint | Points SimpleChat to the blob endpoint used by this feature. | Not specified in defaults | `data_management_blob_endpoint` |
| Container | Controls the user-facing copy or name shown for container. | simplechat-backups | `data_management_container_name` |
| Connection string | No connection string saved yet. | Empty | `data_management_connection_string` |
| Blob prefix | Controls how SimpleChat uses blob prefix on this tab. | simplechat-backups | `data_management_path_prefix` |
| Encrypt backup artifacts | Controls how SimpleChat uses encrypt backup artifacts on this tab. | On | `data_management_encryption_enabled` |
| Concurrent blob transfers | Caps or schedules concurrent blob transfers so the feature stays within expected capacity. | 4 | `data_management_backup_blob_max_parallel_operations` |
| Transfer chunk size (MiB) | Caps or schedules transfer chunk size (mib) so the feature stays within expected capacity. | 8 | `data_management_backup_blob_chunk_size_mib` |
| Blob retry attempts | Controls how SimpleChat uses blob retry attempts on this tab. | 5 | `data_management_backup_blob_retry_count` |
| Concurrent batch staging | Caps or schedules concurrent batch staging so the feature stays within expected capacity. | 4 | `data_management_backup_max_parallel_operations` |
| Retry attempts | Controls how SimpleChat uses retry attempts on this tab. | 5 | `data_management_backup_retry_count` |
| If source RU Boost is unavailable | Controls how SimpleChat uses if source ru boost is unavailable on this tab. | continue_without_boost | `data_management_backup_capacity_failure_policy` |
| Enable source RU Boost for backups | Controls how SimpleChat uses enable source ru boost for backups on this tab. | Off | `data_management_backup_temporary_source_ru_enabled` |
| Source RU Boost target | Controls how SimpleChat uses source ru boost target on this tab. | 10000 | `data_management_backup_temporary_source_ru` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_target_cosmos_auth` |
| Endpoint | Points SimpleChat to the endpoint used by this feature. | Not specified in defaults | `data_management_target_cosmos_endpoint` |
| Database | Fixed app contract. | Not specified in defaults | `data_management_target_cosmos_database` |
| Account key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `data_management_target_cosmos_key` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_target_ai_search_auth` |
| Endpoint | Points SimpleChat to the endpoint used by this feature. | N/A (runtime control) | `data_management_target_ai_search_endpoint` |
| Admin key | Provides the secret credential used when the selected authentication mode requires one. | N/A (runtime control) | `data_management_target_ai_search_key` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_target_ec_storage_auth` |
| Blob endpoint | Points SimpleChat to the blob endpoint used by this feature. | Not specified in defaults | `data_management_target_ec_blob_endpoint` |
| Connection string | Provides the secret credential used when the selected authentication mode requires one. | Empty | `data_management_target_ec_connection_string` |
| None Skip users | Controls how SimpleChat uses none skip users on this tab. | Not specified in defaults | `data_management_migration_users_mode_choice` |
| Search users | Narrows the admin list shown for search users. | N/A (runtime control) | `data_management_migration_users_search` |
| Include users' documents | Controls how SimpleChat uses include users' documents on this tab. | Not specified in defaults | `data_management_migration_users_documents` |
| None Skip groups | Controls how SimpleChat uses none skip groups on this tab. | Not specified in defaults | `data_management_migration_groups_mode_choice` |
| Search groups | Narrows the admin list shown for search groups. | N/A (runtime control) | `data_management_migration_groups_search` |
| Include group documents | Controls how SimpleChat uses include group documents on this tab. | Not specified in defaults | `data_management_migration_groups_documents` |
| None Skip public workspaces | Controls how SimpleChat uses none skip public workspaces on this tab. | Not specified in defaults | `data_management_migration_public_workspaces_mode_choice` |
| Search public workspaces | Narrows the admin list shown for search public workspaces. | N/A (runtime control) | `data_management_migration_public_workspaces_search` |
| Include public workspace documents | Controls how SimpleChat uses include public workspace documents on this tab. | Not specified in defaults | `data_management_migration_public_workspaces_documents` |
| Copy missing items only | Controls how SimpleChat uses copy missing items only on this tab. | Not specified in defaults | `data_management_migration_mode` |
| Previous completed migration job ID | Leave blank to let SimpleChat choose the latest compatible completed migration as the starting point for this catch-up run. | Not specified in defaults | `data_management_migration_baseline_job_id` |
| Migrate matching AI Search documents | Narrows the admin list shown for migrate matching ai search documents. | N/A (runtime control) | `data_management_migration_include_ai_search` |
| I confirm external destination AI Search writers are frozen | SimpleChat pauses its own target indexing. Freeze other writers before review. | N/A (runtime control) | `data_management_migration_target_search_writes_frozen` |
| Migrate selected source document blobs | Requires Enhanced Citation storage at both source and destination. | Not specified in defaults | `data_management_migration_include_source_blobs` |
| Concurrent operations | Caps or schedules concurrent operations so the feature stays within expected capacity. | 8 | `data_management_migration_max_parallel_operations` |
| Retry attempts | Controls how SimpleChat uses retry attempts on this tab. | 5 | `data_management_migration_retry_count` |
| Skip prior successes within hours | Controls how SimpleChat uses skip prior successes within hours on this tab. | Setting | `data_management_migration_skip_recent_within_hours` |
| Enable destination RU Boost for this migration | Controls how SimpleChat uses enable destination ru boost for this migration on this tab. | Off | `data_management_migration_temporary_destination_ru_enabled` |
| Destination RU Boost target | Controls how SimpleChat uses destination ru boost target on this tab. | 10000 | `data_management_migration_temporary_destination_ru` |
| Subscription ID | Controls how SimpleChat uses subscription id on this tab. | Not specified in defaults | `data_management_target_cosmos_subscription_id` |
| Resource group | Controls how SimpleChat uses resource group on this tab. | Not specified in defaults | `data_management_target_cosmos_resource_group` |
| Type MAKE DESTINATION MATCH SOURCE to authorize this run | Controls how SimpleChat uses type make destination match source to authorize this run on this tab. | N/A (runtime control) | `data_management_migration_mirror_confirmation_phrase` |
| I reviewed the normalized plan, destination checks, warnings, and operational impact. | Controls how SimpleChat uses i reviewed the normalized plan, destination checks, warnings, and operational impact on this tab. | N/A (runtime control) | `data_management_migration_final_confirmation` |
| Container | Choose a known SimpleChat Cosmos DB container. | Not specified in defaults | `data_management_cosmos_editor_container` |
| Page size | Max 100 per request. | Not specified in defaults | `data_management_cosmos_editor_page_size` |
| SELECT query | Empty query returns only the first 100 documents. Custom SELECT queries can page beyond 100 with Next Page. | Not specified in defaults | `data_management_cosmos_editor_query` |
| Status | Narrows the admin list shown for status. | N/A (runtime control) | `data_management_backup_status_filter` |
| Run type | Narrows the admin list shown for run type. | N/A (runtime control) | `data_management_backup_scheduled_filter` |
| Created from | Controls how SimpleChat uses created from on this tab. | Not specified in defaults | `data_management_backup_created_from` |
| Created through | Controls how SimpleChat uses created through on this tab. | Not specified in defaults | `data_management_backup_created_to` |
| Rows per page | Caps or schedules rows per page so the feature stays within expected capacity. | Not specified in defaults | `data_management_backup_page_size` |
| Collision policy | Create-only is non-destructive and recommended for first restore attempts. | create_only | `data_management_restore_policy` |
| Cosmos DB | Controls how SimpleChat uses cosmos db on this tab. | Not specified in defaults | `data_management_restore_include_cosmos` |
| AI Search | Narrows the admin list shown for ai search. | N/A (runtime control) | `data_management_restore_include_ai_search` |
| Enhanced Citation blobs | Controls how SimpleChat uses enhanced citation blobs on this tab. | Not specified in defaults | `data_management_restore_include_source_blobs` |
| Type the overwrite confirmation phrase | Required phrase: RESTORE WITH OVERWRITE | N/A (runtime control) | `data_management_restore_overwrite_confirmation_phrase` |
| I reviewed the restore target, policy, and preflight result. | Controls how SimpleChat uses i reviewed the restore target, policy, and preflight result on this tab. | N/A (runtime control) | `data_management_restore_final_confirmation` |
| Operation | Narrows the admin list shown for operation. | N/A (runtime control) | `data_management_job_operation_filter` |
| Status | Narrows the admin list shown for status. | N/A (runtime control) | `data_management_job_status_filter` |
| Run type | Narrows the admin list shown for run type. | N/A (runtime control) | `data_management_job_scheduled_filter` |
| Created from | Controls how SimpleChat uses created from on this tab. | Not specified in defaults | `data_management_job_created_from` |
| Created through | Controls how SimpleChat uses created through on this tab. | Not specified in defaults | `data_management_job_created_to` |
| Rows per page | Caps or schedules rows per page so the feature stays within expected capacity. | Not specified in defaults | `data_management_job_page_size` |
| I understand this editor can damage overall system health. | Controls how SimpleChat uses i understand this editor can damage overall system health on this tab. | Not specified in defaults | `data_management_cosmos_editor_danger_accept` |
| Data Management Cosmos Editor Document Json | The editor blocks id and partition key changes. Saves use the ETag from the loaded document. | Not specified in defaults | `data_management_cosmos_editor_document_json` |
| Type the confirmation phrase to enable saving | Required phrase: I understand this can damage system data | N/A (runtime control) | `data_management_cosmos_editor_confirmation_phrase` |

### Migration confirmation

Migration settings include explicit confirmations because copy and mirror modes can affect destination Cosmos records, AI Search documents, and source blobs. Review the normalized plan and freeze destination writers before final authorization.

### Restore collision policy

Create-only restore is safest because it avoids overwriting existing records. Overwrite requires the UI confirmation phrase and should be used only after preflight review confirms the target and backup are correct.

### Cosmos DB JSON editor

The editor is an emergency tool for known SimpleChat containers. It blocks id and partition-key changes and saves with the loaded ETag, but a wrong edit can still damage application data.

## Before you change anything

- Provision backup Blob Storage and choose managed identity or connection-string authentication.
- Confirm the backup container and prefix before enabling scheduled jobs.
- For migration, freeze external destination AI Search writers before running copy or mirror operations.
- Test restore and migration plans outside production before using overwrite or mirror confirmation modes.

## Common tasks

1. **Configure scheduled backups.**
    1. Enable **Enable scheduled backups**.
    2. Set full backup frequency, scheduled time, retention, partial backups, and low-impact mode.
    3. Choose included surfaces: Cosmos DB, AI Search, and source blobs.
    4. Configure storage authentication, container, prefix, encryption, retries, and concurrency.
    Outcome to verify: Scheduled backup jobs have a valid storage target and retention policy.

{% include media.html src="admin/data-management-configure-scheduled-backups.png" alt="Screenshot of the Backup, Migrate & Restore settings tab showing configure scheduled backups." title="Backup, Migrate & Restore: Configure scheduled backups" capture="Capture the Backup, Migrate & Restore tab while performing Configure scheduled backups. Show the relevant controls and redact secrets." %}

2. **Prepare a migration.**
    1. Configure destination Cosmos, AI Search, and enhanced citation storage targets.
    2. Choose users, groups, public workspaces, and document inclusion.
    3. Choose copy or mirror mode.
    4. Run preflight and review warnings before entering final confirmation.
    Outcome to verify: The migration plan is normalized and ready for review.

{% include media.html src="admin/data-management-prepare-a-migration.png" alt="Screenshot of the Backup, Migrate & Restore settings tab showing prepare a migration." title="Backup, Migrate & Restore: Prepare a migration" capture="Capture the Backup, Migrate & Restore tab while performing Prepare a migration. Show the relevant controls and redact secrets." %}

3. **Restore from a backup.**
    1. Select a backup from **Backup Inventory**.
    2. Choose **Collision policy**.
    3. Select Cosmos DB, AI Search, and/or Enhanced Citation blobs.
    4. Run preflight and enter overwrite confirmation only if overwrite is intended.
    Outcome to verify: Restore runs against the selected backup and policy.

{% include media.html src="admin/data-management-restore-from-a-backup.png" alt="Screenshot of the Backup, Migrate & Restore settings tab showing restore from a backup." title="Backup, Migrate & Restore: Restore from a backup" capture="Capture the Backup, Migrate & Restore tab while performing Restore from a backup. Show the relevant controls and redact secrets." %}

4. **Use the Cosmos JSON editor carefully.**
    1. Choose a known SimpleChat container.
    2. Run a bounded SELECT query.
    3. Review the loaded document JSON.
    4. Accept the warning and enter the confirmation phrase only for a known fix.
    Outcome to verify: Only the intended document is saved with its ETag.

{% include media.html src="admin/data-management-use-the-cosmos-json-editor-carefully.png" alt="Screenshot of the Backup, Migrate & Restore settings tab showing use the cosmos json editor carefully." title="Backup, Migrate & Restore: Use the Cosmos JSON editor carefully" capture="Capture the Backup, Migrate & Restore tab while performing Use the Cosmos JSON editor carefully. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Source blobs are unavailable for backup or migration | Enhanced Citation storage is not enabled/configured. | Enable and configure Enhanced Citations before including source blobs. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Scale]({{ '/admin/scale/' | relative_url }})
- [Citations]({{ '/admin/citation/' | relative_url }})
- [Search and Extract]({{ '/admin/search-extract/' | relative_url }})
