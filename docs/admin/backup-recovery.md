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

## Backup {#backup}

### Start Here {#data-management-readiness-section}

The Start Here section belongs to the Backup tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Backup {#data-management-backup-section}

The Backup section belongs to the Backup tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Schedule {#data-management-schedule-section}

The Schedule section belongs to the Backup tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Storage {#data-management-storage-section}

The Storage section belongs to the Backup tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Encryption {#data-management-encryption-section}

The Encryption section belongs to the Backup tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable scheduled backups | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `data_management_enabled` |
| Full backup frequency | Defines behavior for the related admin workflow; verify the affected feature after saving. | weekly | `data_management_full_frequency` |
| Scheduled time (UTC) | Default is 03:00 UTC. | 03:00 | `data_management_scheduled_time_utc` |
| Delete backups after | Defines behavior for the related admin workflow; verify the affected feature after saving. | 30 | `data_management_retention_value` |
| Retention unit | Defines behavior for the related admin workflow; verify the affected feature after saving. | days | `data_management_retention_unit` |
| Run partial backups daily between full backups | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `data_management_partial_enabled` |
| Include Cosmos DB data | Core application records required for meaningful restore and migration. | On | `data_management_include_cosmos` |
| Include AI Search indexes | Search index schemas and retrievable indexed documents. | On | `data_management_include_ai_search` |
| Include source document blobs | Original source files used by Enhanced Citations. | Off | `data_management_include_source_blobs` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_storage_auth` |
| Blob endpoint | Provides the endpoint or route SimpleChat uses for this service. | Not specified in defaults | `data_management_blob_endpoint` |
| Container | Provides displayed text that users see in the affected interface. | simplechat-backups | `data_management_container_name` |
| Connection string | No connection string saved yet. | Empty | `data_management_connection_string` |
| Blob prefix | Defines behavior for the related admin workflow; verify the affected feature after saving. | simplechat-backups | `data_management_path_prefix` |
| Encrypt backup artifacts | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `data_management_encryption_enabled` |
| Concurrent blob transfers | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 4 | `data_management_backup_blob_max_parallel_operations` |
| Transfer chunk size (MiB) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 8 | `data_management_backup_blob_chunk_size_mib` |
| Blob retry attempts | Defines behavior for the related admin workflow; verify the affected feature after saving. | 5 | `data_management_backup_blob_retry_count` |
| Concurrent batch staging | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 4 | `data_management_backup_max_parallel_operations` |
| Retry attempts | Defines behavior for the related admin workflow; verify the affected feature after saving. | 5 | `data_management_backup_retry_count` |
| If source RU Boost is unavailable | Defines behavior for the related admin workflow; verify the affected feature after saving. | continue_without_boost | `data_management_backup_capacity_failure_policy` |
| Enable source RU Boost for backups | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `data_management_backup_temporary_source_ru_enabled` |
| Source RU Boost target | Defines behavior for the related admin workflow; verify the affected feature after saving. | 10000 | `data_management_backup_temporary_source_ru` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_target_cosmos_auth` |
| Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Not specified in defaults | `data_management_target_cosmos_endpoint` |
| Database | Fixed app contract. | Not specified in defaults | `data_management_target_cosmos_database` |
| Account key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `data_management_target_cosmos_key` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_target_ai_search_auth` |
| Endpoint | Provides the endpoint or route SimpleChat uses for this service. | N/A (runtime control) | `data_management_target_ai_search_endpoint` |
| Admin key | Provides the secret credential used when the selected authentication mode requires one. | N/A (runtime control) | `data_management_target_ai_search_key` |
| Authentication | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | managed_identity | `data_management_target_ec_storage_auth` |
| Blob endpoint | Provides the endpoint or route SimpleChat uses for this service. | Not specified in defaults | `data_management_target_ec_blob_endpoint` |
| Connection string | Provides the secret credential used when the selected authentication mode requires one. | Empty | `data_management_target_ec_connection_string` |
| Subscription ID | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_target_cosmos_subscription_id` |
| Resource group | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_target_cosmos_resource_group` |
| Status | Narrows the admin list shown for status. | N/A (runtime control) | `data_management_backup_status_filter` |
| Run type | Narrows the admin list shown for run type. | N/A (runtime control) | `data_management_backup_scheduled_filter` |
| Created from | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_backup_created_from` |
| Created through | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_backup_created_to` |
| Rows per page | Defines a capacity or timing boundary that keeps the feature inside supported limits. | Not specified in defaults | `data_management_backup_page_size` |

## Migrate {#migrate}

### Migration {#data-management-migration-section}

The Migration section belongs to the Migrate tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| None Skip users | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_users_mode_choice` |
| Search users | Narrows the admin list shown for search users. | N/A (runtime control) | `data_management_migration_users_search` |
| Include users' documents | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_users_documents` |
| None Skip groups | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_groups_mode_choice` |
| Search groups | Narrows the admin list shown for search groups. | N/A (runtime control) | `data_management_migration_groups_search` |
| Include group documents | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_groups_documents` |
| None Skip public workspaces | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_public_workspaces_mode_choice` |
| Search public workspaces | Narrows the admin list shown for search public workspaces. | N/A (runtime control) | `data_management_migration_public_workspaces_search` |
| Include public workspace documents | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_public_workspaces_documents` |
| Copy missing items only | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_migration_mode` |
| Previous completed migration job ID | Leave blank to let SimpleChat choose the latest compatible completed migration as the starting point for this catch-up run. | Not specified in defaults | `data_management_migration_baseline_job_id` |
| Migrate matching AI Search documents | Narrows the admin list shown for migrate matching ai search documents. | N/A (runtime control) | `data_management_migration_include_ai_search` |
| I confirm external destination AI Search writers are frozen | SimpleChat pauses its own target indexing. Freeze other writers before review. | N/A (runtime control) | `data_management_migration_target_search_writes_frozen` |
| Migrate selected source document blobs | Requires Enhanced Citation storage at both source and destination. | Not specified in defaults | `data_management_migration_include_source_blobs` |
| Concurrent operations | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 8 | `data_management_migration_max_parallel_operations` |
| Retry attempts | Defines behavior for the related admin workflow; verify the affected feature after saving. | 5 | `data_management_migration_retry_count` |
| Skip prior successes within hours | Defines behavior for the related admin workflow; verify the affected feature after saving. | Setting | `data_management_migration_skip_recent_within_hours` |
| Enable destination RU Boost for this migration | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `data_management_migration_temporary_destination_ru_enabled` |
| Destination RU Boost target | Defines behavior for the related admin workflow; verify the affected feature after saving. | 10000 | `data_management_migration_temporary_destination_ru` |
| Type MAKE DESTINATION MATCH SOURCE to authorize this run | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | `data_management_migration_mirror_confirmation_phrase` |
| I reviewed the normalized plan, destination checks, warnings, and operational impact. | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | `data_management_migration_final_confirmation` |

## Restore {#restore}

### Backup Inventory & Restore {#data-management-backup-inventory-section}

The Backup Inventory & Restore section belongs to the Restore tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Collision policy | Create-only is non-destructive and recommended for first restore attempts. | create_only | `data_management_restore_policy` |
| Cosmos DB | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_restore_include_cosmos` |
| AI Search | Narrows the admin list shown for ai search. | N/A (runtime control) | `data_management_restore_include_ai_search` |
| Enhanced Citation blobs | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_restore_include_source_blobs` |
| Type the overwrite confirmation phrase | Required phrase: RESTORE WITH OVERWRITE | N/A (runtime control) | `data_management_restore_overwrite_confirmation_phrase` |
| I reviewed the restore target, policy, and preflight result. | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | `data_management_restore_final_confirmation` |

## Cosmos Editor {#cosmos-editor}

### Cosmos Editor {#data-management-cosmos-editor-section}

The Cosmos Editor section belongs to the Cosmos Editor tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Container | Choose a known SimpleChat Cosmos DB container. | Not specified in defaults | `data_management_cosmos_editor_container` |
| Page size | Max 100 per request. | Not specified in defaults | `data_management_cosmos_editor_page_size` |
| SELECT query | Empty query returns only the first 100 documents. Custom SELECT queries can page beyond 100 with Next Page. | Not specified in defaults | `data_management_cosmos_editor_query` |
| I understand this editor can damage overall system health. | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_cosmos_editor_danger_accept` |
| Data Management Cosmos Editor Document Json | The editor blocks id and partition key changes. Saves use the ETag from the loaded document. | Not specified in defaults | `data_management_cosmos_editor_document_json` |
| Type the confirmation phrase to enable saving | Required phrase: I understand this can damage system data | N/A (runtime control) | `data_management_cosmos_editor_confirmation_phrase` |

## Jobs {#jobs}

### Jobs {#data-management-jobs-section}

The Jobs section belongs to the Jobs tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use low impact mode for scheduled jobs | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `data_management_low_impact_mode` |
| Operation | Narrows the admin list shown for operation. | N/A (runtime control) | `data_management_job_operation_filter` |
| Status | Narrows the admin list shown for status. | N/A (runtime control) | `data_management_job_status_filter` |
| Run type | Narrows the admin list shown for run type. | N/A (runtime control) | `data_management_job_scheduled_filter` |
| Created from | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_job_created_from` |
| Created through | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `data_management_job_created_to` |
| Rows per page | Defines a capacity or timing boundary that keeps the feature inside supported limits. | Not specified in defaults | `data_management_job_page_size` |

## Common tasks

1. **Prepare scheduled backups.** Configure backup, schedule, storage, and encryption, then queue a small backup. Outcome to verify: A backup artifact appears in inventory.
2. **Run restore preflight.** Select a backup, choose restore policy, and run review before queueing. Outcome to verify: Preflight reports target access and collision behavior.
3. **Use Cosmos Editor safely.** Query the target document and review the change summary before saving. Outcome to verify: The intended document updates with ETag protection.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A restore cannot be queued | Preflight found target access, manifest, or collision-policy problems. | Resolve the reported check before queueing. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Scale settings]({{ '/admin/scale/' | relative_url }})
- [Data Lifecycle settings]({{ '/admin/data-lifecycle/' | relative_url }})
