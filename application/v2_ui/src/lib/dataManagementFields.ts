// dataManagementFields.ts
// How each Backup & Recovery setting is drawn.
//
// The controls themselves are the shared Admin Settings ones (`SettingField`,
// `SecretField`), so these settings read exactly like every other setting on the page. Only
// the descriptions live here, because the data-management document is saved through its
// own API rather than the settings schema.
//
// `key` is prefixed so the controls' element ids cannot collide with a main setting of the
// same name; `dmKey` is the key the value is actually stored under.

import type { AdminField } from './adminFields';
import { DM_NUMBER_BOUNDS, type DmEditableKey } from './dataManagement';

export interface DmFieldDef extends Omit<AdminField, 'key'> {
    dmKey: DmEditableKey;
}

const bounds = (key: DmEditableKey) => {
    const range = DM_NUMBER_BOUNDS[key];
    return range ? { min: range.min, max: range.max, step: range.step ?? 1 } : {};
};

const MANAGED_IDENTITY_OR_CONNECTION_STRING = [
    { value: 'managed_identity', label: 'Managed identity' },
    { value: 'connection_string', label: 'Connection string' },
];

export const DM_FIELDS: Partial<Record<DmEditableKey, DmFieldDef>> = {
    // Schedule
    enabled: {
        dmKey: 'enabled',
        type: 'switch',
        label: 'Scheduled backups',
        help: 'Take full backups on the cadence below, plus daily partial backups when they are on. Off means a backup runs only when someone queues one.',
        default: false,
    },
    full_backup_frequency: {
        dmKey: 'full_backup_frequency',
        type: 'select',
        label: 'Full backup frequency',
        help: 'How often a complete snapshot is taken.',
        default: 'weekly',
        options: [
            { value: 'daily', label: 'Daily' },
            { value: 'weekly', label: 'Weekly' },
            { value: '14_days', label: 'Every 14 days' },
            { value: '30_days', label: 'Every 30 days' },
        ],
    },
    partial_backups_enabled: {
        dmKey: 'partial_backups_enabled',
        type: 'switch',
        label: 'Daily partial backups',
        help: 'Capture changed items every day between full backups. A partial backup restores the latest captured items but does not replay deletions.',
        default: true,
    },
    low_impact_mode: {
        dmKey: 'low_impact_mode',
        type: 'switch',
        label: 'Use low-impact mode for scheduled jobs',
        default: true,
    },
    include_cosmos: {
        dmKey: 'include_cosmos',
        type: 'switch',
        label: 'Cosmos DB records',
        help: 'Settings, users, workspaces, conversations, documents, agents, actions, prompts and identities. Restore and migration need these.',
        default: true,
    },
    include_ai_search: {
        dmKey: 'include_ai_search',
        type: 'switch',
        label: 'AI Search indexes',
        help: 'Index schemas and the retrievable documents in the personal, group and public indexes.',
        default: true,
    },
    include_source_blobs: {
        dmKey: 'include_source_blobs',
        type: 'switch',
        label: 'Source document files',
        help: 'The original files Enhanced Citations keeps.',
        default: true,
    },

    // Storage
    backup_storage_authentication_type: {
        dmKey: 'backup_storage_authentication_type',
        type: 'select',
        label: 'Authentication',
        help: 'How SimpleChat signs in to the backup storage account.',
        default: 'managed_identity',
        options: MANAGED_IDENTITY_OR_CONNECTION_STRING,
    },
    backup_storage_blob_endpoint: {
        dmKey: 'backup_storage_blob_endpoint',
        type: 'text',
        input_type: 'url',
        label: 'Blob endpoint',
        placeholder: 'https://account.blob.core.windows.net',
        default: '',
    },
    backup_storage_connection_string: {
        dmKey: 'backup_storage_connection_string',
        type: 'secret',
        label: 'Connection string',
        placeholder: 'Paste the storage connection string',
        default: '',
    },
    backup_storage_container_name: {
        dmKey: 'backup_storage_container_name',
        type: 'text',
        label: 'Container',
        help: 'Test storage creates it when it does not exist yet.',
        default: 'simplechat-backups',
    },
    backup_storage_path_prefix: {
        dmKey: 'backup_storage_path_prefix',
        type: 'text',
        label: 'Path prefix',
        help: 'The folder inside the container that backups are written under.',
        default: 'simplechat-backups',
    },

    // Encryption
    encryption_enabled: {
        dmKey: 'encryption_enabled',
        type: 'switch',
        label: 'Encrypt backup files',
        help: 'Encrypt every backup artifact with the backup key before it is written to storage.',
        default: true,
    },

    // Backup performance
    backup_max_parallel_operations: {
        dmKey: 'backup_max_parallel_operations',
        type: 'number',
        label: 'Concurrent batch staging',
        help: 'Cosmos batches prepared at once. Higher values finish sooner and put more load on the source database.',
        default: 4,
        ...bounds('backup_max_parallel_operations'),
    },
    backup_retry_count: {
        dmKey: 'backup_retry_count',
        type: 'number',
        label: 'Retry attempts',
        help: 'Times a throttled or failed Cosmos batch is retried before the resource is marked failed.',
        default: 5,
        ...bounds('backup_retry_count'),
    },
    backup_capacity_failure_policy: {
        dmKey: 'backup_capacity_failure_policy',
        type: 'select',
        label: 'If source RU Boost is unavailable',
        help: 'What a backup does when it cannot raise source capacity.',
        default: 'continue_without_boost',
        options: [
            { value: 'continue_without_boost', label: 'Continue without the boost' },
            { value: 'fail', label: 'Stop before exporting' },
        ],
    },
    backup_temporary_source_ru_enabled: {
        dmKey: 'backup_temporary_source_ru_enabled',
        type: 'switch',
        label: 'Source RU Boost for backups',
        help: 'Temporarily raise eligible source Cosmos capacity while a backup runs, then put the original setting back after it completes, fails, is canceled or recovers. This can add Cosmos charges and needs throughput permission on the source account.',
        default: false,
    },
    backup_temporary_source_ru: {
        dmKey: 'backup_temporary_source_ru',
        type: 'number',
        label: 'Source RU Boost target',
        help: 'RU/s to raise eligible targets to, at most 10,000.',
        default: 10000,
        suffix: ' RU/s',
        ...bounds('backup_temporary_source_ru'),
    },
    backup_blob_max_parallel_operations: {
        dmKey: 'backup_blob_max_parallel_operations',
        type: 'number',
        label: 'Concurrent file transfers',
        help: 'Source files copied at once. Throttling lowers this on its own while it lasts.',
        default: 4,
        ...bounds('backup_blob_max_parallel_operations'),
    },
    backup_blob_chunk_size_mib: {
        dmKey: 'backup_blob_chunk_size_mib',
        type: 'number',
        label: 'Transfer chunk size (MiB)',
        help: 'Each file streams through chunks of this size.',
        default: 8,
        ...bounds('backup_blob_chunk_size_mib'),
    },
    backup_blob_retry_count: {
        dmKey: 'backup_blob_retry_count',
        type: 'number',
        label: 'File retry attempts',
        help: 'Times a failed file transfer is retried.',
        default: 5,
        ...bounds('backup_blob_retry_count'),
    },

    // Destination (restore and migration)
    target_cosmos_authentication_type: {
        dmKey: 'target_cosmos_authentication_type',
        type: 'select',
        label: 'Authentication',
        help: 'Managed identity needs Cosmos DB Data Contributor on the destination account and network access to it.',
        default: 'managed_identity',
        options: [
            { value: 'managed_identity', label: 'Managed identity' },
            { value: 'key', label: 'Account key' },
        ],
    },
    target_cosmos_endpoint: {
        dmKey: 'target_cosmos_endpoint',
        type: 'text',
        input_type: 'url',
        label: 'Endpoint',
        placeholder: 'https://account.documents.azure.com:443/',
        default: '',
    },
    target_cosmos_key: {
        dmKey: 'target_cosmos_key',
        type: 'secret',
        label: 'Account key',
        default: '',
    },
    target_ai_search_authentication_type: {
        dmKey: 'target_ai_search_authentication_type',
        type: 'select',
        label: 'Authentication',
        default: 'managed_identity',
        options: [
            { value: 'managed_identity', label: 'Managed identity' },
            { value: 'key', label: 'Admin key' },
        ],
    },
    target_ai_search_endpoint: {
        dmKey: 'target_ai_search_endpoint',
        type: 'text',
        input_type: 'url',
        label: 'Endpoint',
        placeholder: 'https://search-service.search.windows.net',
        default: '',
    },
    target_ai_search_key: {
        dmKey: 'target_ai_search_key',
        type: 'secret',
        label: 'Admin key',
        default: '',
    },
    target_enhanced_citations_storage_authentication_type: {
        dmKey: 'target_enhanced_citations_storage_authentication_type',
        type: 'select',
        label: 'Authentication',
        default: 'managed_identity',
        options: MANAGED_IDENTITY_OR_CONNECTION_STRING,
    },
    target_enhanced_citations_storage_blob_endpoint: {
        dmKey: 'target_enhanced_citations_storage_blob_endpoint',
        type: 'text',
        input_type: 'url',
        label: 'Blob endpoint',
        placeholder: 'https://account.blob.core.windows.net',
        default: '',
    },
    target_enhanced_citations_storage_connection_string: {
        dmKey: 'target_enhanced_citations_storage_connection_string',
        type: 'secret',
        label: 'Connection string',
        placeholder: 'Paste the storage connection string',
        default: '',
    },
    target_cosmos_subscription_id: {
        dmKey: 'target_cosmos_subscription_id',
        type: 'text',
        label: 'Subscription ID',
        help: 'The destination Cosmos account’s subscription. RU Boost needs it to change throughput.',
        placeholder: '00000000-0000-0000-0000-000000000000',
        default: '',
    },
    target_cosmos_resource_group: {
        dmKey: 'target_cosmos_resource_group',
        type: 'text',
        label: 'Resource group',
        help: 'The destination Cosmos account’s resource group. RU Boost needs it to change throughput.',
        default: '',
    },

    // Migration performance
    migration_max_parallel_operations: {
        dmKey: 'migration_max_parallel_operations',
        type: 'number',
        label: 'Concurrent operations',
        default: 8,
        ...bounds('migration_max_parallel_operations'),
    },
    migration_retry_count: {
        dmKey: 'migration_retry_count',
        type: 'number',
        label: 'Retry attempts',
        default: 5,
        ...bounds('migration_retry_count'),
    },
    migration_skip_recent_within_hours: {
        dmKey: 'migration_skip_recent_within_hours',
        type: 'number',
        label: 'Skip items migrated in the last (hours)',
        help: 'Items an earlier run copied successfully within this many hours are skipped. 0 skips nothing.',
        default: 0,
        ...bounds('migration_skip_recent_within_hours'),
    },
    migration_temporary_destination_ru_enabled: {
        dmKey: 'migration_temporary_destination_ru_enabled',
        type: 'switch',
        label: 'Destination RU Boost for this migration',
        help: 'Temporarily raise eligible destination Cosmos capacity, at most 10,000 RU/s, and put it back after the migration completes or fails. This can add Cosmos charges and needs management-plane permission on the destination account.',
        default: false,
    },
    migration_temporary_destination_ru: {
        dmKey: 'migration_temporary_destination_ru',
        type: 'number',
        label: 'Destination RU Boost target',
        default: 10000,
        suffix: ' RU/s',
        ...bounds('migration_temporary_destination_ru'),
    },
};

/** The `AdminField` the shared controls expect, with a collision-free key. */
export function toAdminField(def: DmFieldDef): AdminField {
    const { dmKey, ...rest } = def;
    return { ...rest, key: `data_management_${dmKey}` };
}
