// dataManagement.ts
// Types, constants and API calls for Admin Settings > Backup & Recovery.
//
// Backup, restore, migration, the Cosmos editor and job history all talk to the classic
// admin API under `/api/admin/data-management`. Every route there is admin-only and
// already returns sanitized payloads, so the V2 surface reuses it rather than adding a
// second set of endpoints that could drift from the first.
//
// The data-management settings are not part of the main settings document. They live in
// their own Cosmos document and are saved as one whole object, which is why this module
// carries its own list of editable keys (`DM_EDITABLE_KEYS`): it mirrors what the classic
// page sends, so a save never writes read-only status fields back into the document.

import { api, apiUrl, ApiError } from './apiClient';
import { SECRET_PLACEHOLDER } from './adminFields';

export const DM_API = '/api/admin/data-management';

/** Typed phrases the server checks verbatim. Mirrors `functions_data_management.py`. */
export const RESTORE_OVERWRITE_PHRASE = 'RESTORE WITH OVERWRITE';
export const MIRROR_CONFIRMATION_PHRASE = 'MAKE DESTINATION MATCH SOURCE';
export const COSMOS_EDITOR_SAVE_PHRASE = 'I understand this can damage system data';

/** The redaction placeholder the data-management API uses, the same one admin settings uses. */
export const DM_REDACTED = SECRET_PLACEHOLDER;

/** Live job views refresh this often while a job is queued or running. */
export const JOB_POLL_INTERVAL_MS = 2000;

export const TARGET_COSMOS_DATABASE_NAME = 'SimpleChat';
export const MIGRATION_MAX_SELECTED_IDS = 2000;
export const MIGRATION_CATALOG_PAGE_SIZE = 25;
export const COSMOS_EDITOR_MAX_PAGE_SIZE = 100;
export const COSMOS_EDITOR_MAX_QUERY_LENGTH = 4000;
export const HISTORY_MAX_RANGE_DAYS = 366;
export const HISTORY_PAGE_SIZES = [10, 25, 50, 100] as const;
export const RETENTION_MAX_DAYS = 3650;
export const RETENTION_UNIT_DAYS = { days: 1, weeks: 7, months: 30, years: 365 } as const;
export type RetentionUnit = keyof typeof RETENTION_UNIT_DAYS;

/** Statuses the failure-only manifest download asks for, as the classic page does. */
export const MANIFEST_FAILURE_STATUSES = 'failed,missing,collision';

export const ACTIVE_JOB_STATUSES: ReadonlySet<string> = new Set(['queued', 'running']);
export const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
    'completed',
    'completed_with_warnings',
    'failed',
    'canceled',
]);

export type JobOperation = 'backup' | 'restore' | 'migration' | 'dry_run';
export type BackupType = 'full' | 'partial';
export type JobStatus =
    'queued' | 'running' | 'completed' | 'completed_with_warnings' | 'failed' | 'canceled';

export const MIGRATION_TARGET_TYPES = ['users', 'groups', 'public_workspaces'] as const;
export type MigrationTargetType = (typeof MIGRATION_TARGET_TYPES)[number];
export type MigrationScopeMode = 'none' | 'selected' | 'all';
export type MigrationMode = 'new_only' | 'delta_upsert' | 'mirror_with_deletions';
export type RestorePolicy = 'create_only' | 'overwrite_existing';

// ---------------------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------------------

/**
 * Every key the classic page sends on save, in the same order (`collectSettings()` in
 * `admin_data_management.js`). The parity test reads both lists and fails if they drift.
 */
export const DM_EDITABLE_KEYS = [
    'enabled',
    'full_backup_frequency',
    'scheduled_time_utc',
    'retention_value',
    'retention_unit',
    'retention_days',
    'partial_backups_enabled',
    'low_impact_mode',
    'include_cosmos',
    'include_ai_search',
    'include_source_blobs',
    'backup_storage_authentication_type',
    'backup_storage_blob_endpoint',
    'backup_storage_container_name',
    'backup_storage_connection_string',
    'backup_storage_path_prefix',
    'encryption_enabled',
    'backup_max_parallel_operations',
    'backup_retry_count',
    'backup_blob_max_parallel_operations',
    'backup_blob_chunk_size_mib',
    'backup_blob_retry_count',
    'backup_capacity_failure_policy',
    'backup_temporary_source_ru_enabled',
    'backup_temporary_source_ru',
    'target_cosmos_authentication_type',
    'target_cosmos_endpoint',
    'target_cosmos_database_name',
    'target_cosmos_key',
    'target_cosmos_subscription_id',
    'target_cosmos_resource_group',
    'target_ai_search_authentication_type',
    'target_ai_search_endpoint',
    'target_ai_search_key',
    'target_enhanced_citations_storage_authentication_type',
    'target_enhanced_citations_storage_blob_endpoint',
    'target_enhanced_citations_storage_connection_string',
    'migration_max_parallel_operations',
    'migration_retry_count',
    'migration_skip_recent_within_hours',
    'migration_temporary_destination_ru_enabled',
    'migration_temporary_destination_ru',
] as const;

export type DmEditableKey = (typeof DM_EDITABLE_KEYS)[number];

/** Editable credentials. Sent back as the placeholder when untouched, which keeps them. */
export const DM_SECRET_KEYS: readonly DmEditableKey[] = [
    'backup_storage_connection_string',
    'target_cosmos_key',
    'target_ai_search_key',
    'target_enhanced_citations_storage_connection_string',
];

/** Keys derived from others rather than edited directly. */
export const DM_DERIVED_KEYS: readonly DmEditableKey[] = ['retention_days', 'target_cosmos_database_name'];

/** Mirrors `DATA_MANAGEMENT_DEFAULT_SETTINGS` for the editable keys. */
export const DM_DEFAULTS: Record<DmEditableKey, string | number | boolean> = {
    enabled: false,
    full_backup_frequency: 'weekly',
    scheduled_time_utc: '03:00',
    retention_value: 30,
    retention_unit: 'days',
    retention_days: 30,
    partial_backups_enabled: true,
    low_impact_mode: true,
    include_cosmos: true,
    include_ai_search: true,
    include_source_blobs: true,
    backup_storage_authentication_type: 'managed_identity',
    backup_storage_blob_endpoint: '',
    backup_storage_container_name: 'simplechat-backups',
    backup_storage_connection_string: '',
    backup_storage_path_prefix: 'simplechat-backups',
    encryption_enabled: true,
    backup_max_parallel_operations: 4,
    backup_retry_count: 5,
    backup_blob_max_parallel_operations: 4,
    backup_blob_chunk_size_mib: 8,
    backup_blob_retry_count: 5,
    backup_capacity_failure_policy: 'continue_without_boost',
    backup_temporary_source_ru_enabled: false,
    backup_temporary_source_ru: 10000,
    target_cosmos_authentication_type: 'managed_identity',
    target_cosmos_endpoint: '',
    target_cosmos_database_name: TARGET_COSMOS_DATABASE_NAME,
    target_cosmos_key: '',
    target_cosmos_subscription_id: '',
    target_cosmos_resource_group: '',
    target_ai_search_authentication_type: 'managed_identity',
    target_ai_search_endpoint: '',
    target_ai_search_key: '',
    target_enhanced_citations_storage_authentication_type: 'managed_identity',
    target_enhanced_citations_storage_blob_endpoint: '',
    target_enhanced_citations_storage_connection_string: '',
    migration_max_parallel_operations: 8,
    migration_retry_count: 5,
    migration_skip_recent_within_hours: 0,
    migration_temporary_destination_ru_enabled: false,
    migration_temporary_destination_ru: 10000,
};

/** Inclusive bounds the classic controls enforce, matching the server's clamps. */
export const DM_NUMBER_BOUNDS: Partial<Record<DmEditableKey, { min: number; max: number; step?: number }>> = {
    backup_max_parallel_operations: { min: 1, max: 16 },
    backup_retry_count: { min: 1, max: 10 },
    backup_blob_max_parallel_operations: { min: 1, max: 8 },
    backup_blob_chunk_size_mib: { min: 1, max: 16 },
    backup_blob_retry_count: { min: 1, max: 10 },
    backup_temporary_source_ru: { min: 1000, max: 10000, step: 1000 },
    migration_max_parallel_operations: { min: 1, max: 32 },
    migration_retry_count: { min: 1, max: 10 },
    migration_skip_recent_within_hours: { min: 0, max: 8760 },
    migration_temporary_destination_ru: { min: 1000, max: 10000, step: 1000 },
};

/**
 * The sanitized settings document the API returns.
 *
 * Besides the editable keys it carries read-only status (`next_*`, `last_*`), the key
 * storage mode, the redacted key reference, and feature context the server resolves from
 * the main settings (`enhanced_citations_enabled`, the Key Vault flags).
 */
export interface DmSettings extends Partial<Record<DmEditableKey, unknown>> {
    encryption_key_reference?: string;
    encryption_key_storage?: 'key_vault' | 'settings' | 'not_configured' | string;
    next_full_backup_run_at?: string | null;
    next_partial_backup_run_at?: string | null;
    last_full_backup_completed_at?: string | null;
    last_partial_backup_completed_at?: string | null;
    last_settings_update_at?: string | null;
    backup_retention_cleanup_last_run_at?: string | null;
    retention_keep_latest_full?: boolean;
    enhanced_citations_enabled?: boolean;
    key_vault_secret_storage_enabled?: boolean;
    key_vault_name_configured?: boolean;
    include_source_blobs_manageable?: boolean;
    operational_business_hours_warning?: string;
    default_scheduled_time_utc?: string;
    partial_backup_frequency_label?: string;
    [key: string]: unknown;
}

export type DmDraft = Partial<Record<DmEditableKey, unknown>>;

interface SettingsResponse {
    success?: boolean;
    settings: DmSettings;
}

export function loadDataManagementSettings(signal?: AbortSignal): Promise<DmSettings> {
    return api
        .get<SettingsResponse>(`${DM_API}/settings`, signal)
        .then((response) => response.settings ?? {});
}

/** Save the whole editable object. The response is the normalized, re-redacted document. */
export function saveDataManagementSettings(payload: Record<string, unknown>): Promise<DmSettings> {
    return api
        .put<SettingsResponse>(`${DM_API}/settings`, payload)
        .then((response) => response.settings ?? {});
}

/** Generate a new backup encryption key. Returns the sanitized settings with the new key metadata. */
export function generateEncryptionKey(): Promise<DmSettings> {
    return api
        .post<SettingsResponse>(`${DM_API}/encryption-key`, {})
        .then((response) => response.settings ?? {});
}

// ---------------------------------------------------------------------------------------
// Connection tests
// ---------------------------------------------------------------------------------------

export interface StorageTestResult {
    success: boolean;
    container_name?: string;
    container_exists?: boolean;
    container_created?: boolean;
    authentication_type?: string;
}

export function testBackupStorage(settings: Record<string, unknown>): Promise<StorageTestResult> {
    // The classic page always asks for the container to be created when it is missing,
    // and says so in its result. Kept identical so both interfaces leave storage the same.
    return api.post<StorageTestResult>(`${DM_API}/storage/test`, { settings, create_container: true });
}

export interface TargetCosmosTestResult {
    success: boolean;
    database_name?: string;
    authentication_type?: string;
    migration_access?: { container_count?: number } | null;
}

export function testTargetCosmos(
    settings: Record<string, unknown>,
    migrationPlan: MigrationPlan,
): Promise<TargetCosmosTestResult> {
    return api.post<TargetCosmosTestResult>(`${DM_API}/target/cosmos/test`, {
        settings,
        migration_plan: migrationPlan,
    });
}

export interface RuBoostTestResult {
    success: boolean;
    target_ru?: number;
    database_mode?: string;
    database_current_ru?: number;
    targets?: Array<{ scope?: string; container_name?: string; mode?: string; current_ru?: number }>;
}

export function testTargetCosmosRuBoost(
    settings: Record<string, unknown>,
    migrationPlan: MigrationPlan,
): Promise<RuBoostTestResult> {
    return api.post<RuBoostTestResult>(`${DM_API}/target/cosmos/ru-boost/test`, {
        settings,
        migration_plan: migrationPlan,
    });
}

export interface TargetSearchTestResult {
    success: boolean;
    expected_indexes?: string[];
    existing_indexes?: string[];
    missing_indexes?: string[];
}

export function testTargetSearch(settings: Record<string, unknown>): Promise<TargetSearchTestResult> {
    return api.post<TargetSearchTestResult>(`${DM_API}/target/search/test`, { settings });
}

export interface TargetStorageTestResult {
    success: boolean;
    containers?: Array<{ container_name?: string; container_exists?: boolean; container_created?: boolean }>;
}

export function testTargetEnhancedCitationStorage(
    settings: Record<string, unknown>,
): Promise<TargetStorageTestResult> {
    return api.post<TargetStorageTestResult>(`${DM_API}/target/enhanced-citation-storage/test`, {
        settings,
        create_containers: true,
    });
}

// ---------------------------------------------------------------------------------------
// History (backups and jobs)
// ---------------------------------------------------------------------------------------

export interface HistoryPagination {
    page_size?: number;
    returned_count?: number;
    has_more?: boolean;
    next_token?: string | null;
}

export interface HistoryFilters {
    status?: string;
    scheduled?: 'all' | 'scheduled' | 'manual';
    createdFrom?: string;
    createdTo?: string;
    pageSize?: number;
}

export interface BackupFilters extends HistoryFilters {
    backupType?: '' | BackupType;
}

export interface JobFilters extends HistoryFilters {
    operation?: '' | JobOperation;
}

/** One row of the backup inventory, as `sanitize_data_management_backup_for_admin` builds it. */
export interface BackupRow {
    id: string;
    backup_type?: BackupType | string | null;
    status?: JobStatus | string;
    created_at?: string | null;
    completed_at?: string | null;
    scheduled?: boolean;
    manifest_path?: string | null;
    base_prefix?: string | null;
    artifact_count?: number;
    bytes?: number;
    record_count?: number;
    blob_count?: number;
    warning_count?: number;
    encrypted?: boolean;
    last_message?: string | null;
    can_delete?: boolean;
}

export interface BackupGlobalSummary {
    full?: number;
    partial?: number;
    available?: number;
    running?: number;
    failed?: number;
    total?: number;
    latest_full?: BackupRow | null;
    latest_partial?: BackupRow | null;
}

export interface BackupPage {
    summary: BackupGlobalSummary;
    backups: BackupRow[];
    pagination: HistoryPagination;
}

/**
 * Why a history list could not load.
 *
 * The server distinguishes a missing Cosmos index (an operator has to run maintenance) from
 * a throttled or transient read (worth retrying), and the message it sends is already safe
 * to show.
 */
export interface HistoryFailure {
    message: string;
    maintenanceRequired: boolean;
    retryable: boolean;
}

export function readHistoryFailure(error: unknown, fallback: string): HistoryFailure {
    if (error instanceof ApiError) {
        const payload = (error.payload && typeof error.payload === 'object' ? error.payload : {}) as Record<
            string,
            unknown
        >;
        return {
            message: error.message || fallback,
            maintenanceRequired: payload.maintenance_required === true,
            retryable: payload.retryable === true,
        };
    }
    return {
        message: error instanceof Error && error.message ? error.message : fallback,
        maintenanceRequired: false,
        retryable: false,
    };
}

function historyQuery(filters: HistoryFilters, token: string | null, extra: Record<string, string>): string {
    const params = new URLSearchParams();
    params.set('page_size', String(filters.pageSize ?? 25));
    if (filters.status) params.set('status', filters.status);
    params.set('scheduled', filters.scheduled ?? 'all');
    if (filters.createdFrom && filters.createdTo) {
        params.set('created_from', filters.createdFrom);
        params.set('created_to', filters.createdTo);
    }
    for (const [key, value] of Object.entries(extra)) {
        if (value) params.set(key, value);
    }
    if (token) params.set('continuation_token', token);
    return params.toString();
}

export function listBackups(
    filters: BackupFilters,
    token: string | null,
    signal?: AbortSignal,
): Promise<BackupPage> {
    const query = historyQuery(filters, token, { backup_type: filters.backupType ?? '' });
    return api
        .get<BackupPage & { success?: boolean }>(`${DM_API}/backups?${query}`, signal)
        .then((response) => ({
            summary: response.summary ?? {},
            backups: Array.isArray(response.backups) ? response.backups : [],
            pagination: response.pagination ?? {},
        }));
}

export interface RetentionCleanupResult {
    success?: boolean;
    manual_execution?: boolean;
    cutoff_at?: string;
    retention_days?: number;
    retention_value?: number;
    retention_unit?: string;
    protected_latest_full_backup_id?: string;
    candidate_count?: number;
    deleted_count?: number;
    errors?: Array<{ job_id?: string; error?: string }>;
}

/**
 * Run retention cleanup now.
 *
 * A cleanup that deleted some backups but failed on others answers 400 with the partial
 * result attached, so that case is read off the error rather than lost.
 */
export async function runRetentionCleanup(): Promise<RetentionCleanupResult> {
    try {
        const response = await api.post<{ cleanup?: RetentionCleanupResult }>(
            `${DM_API}/backups/retention/cleanup`,
            {},
        );
        return response.cleanup ?? {};
    } catch (error) {
        if (error instanceof ApiError && error.payload && typeof error.payload === 'object') {
            const cleanup = (error.payload as { cleanup?: RetentionCleanupResult }).cleanup;
            if (cleanup) {
                return { ...cleanup, success: false };
            }
        }
        throw error;
    }
}

export interface DeleteBackupResult {
    job_id?: string;
    backup_type?: string;
    deleted_blob_count?: number;
    job_item_deleted_count?: number;
    latest_item_state_deleted_count?: number;
}

export function deleteBackup(backupId: string): Promise<DeleteBackupResult> {
    return api
        .delete<{ cleanup?: DeleteBackupResult }>(`${DM_API}/backups/${encodeURIComponent(backupId)}`, {
            reason: 'manual',
        })
        .then((response) => response.cleanup ?? {});
}

export type JsonRecord = Record<string, unknown>;

export interface JobProgress {
    current_step?: string;
    percent_complete?: number | string;
    completed_steps?: number;
    total_steps?: number;
    [key: string]: unknown;
}

/** A job as `sanitize_data_management_job_for_admin` returns it. */
export interface DataManagementJob {
    id: string;
    operation?: JobOperation | string;
    backup_type?: string | null;
    status?: JobStatus | string;
    created_at?: string | null;
    updated_at?: string | null;
    started_at?: string | null;
    completed_at?: string | null;
    last_heartbeat_at?: string | null;
    last_progress_at?: string | null;
    last_message?: string | null;
    last_error?: string | null;
    cancel_requested_at?: string | null;
    requested_by_email?: string | null;
    scheduled?: boolean;
    progress?: JobProgress;
    warnings?: string[];
    result?: JsonRecord;
    migration_state?: JsonRecord | null;
    backup_state?: JsonRecord | null;
    restore_state?: JsonRecord | null;
    can_retry?: boolean;
    can_cancel?: boolean;
    submitted_to_executor?: boolean;
}

export interface JobItem {
    id?: string;
    job_id?: string;
    step_name?: string;
    status?: string;
    message?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
    details?: JsonRecord | null;
}

export interface JobPage {
    jobs: DataManagementJob[];
    pagination: HistoryPagination;
}

export function listJobs(filters: JobFilters, token: string | null, signal?: AbortSignal): Promise<JobPage> {
    const query = historyQuery(filters, token, { operation: filters.operation ?? '' });
    return api.get<JobPage & { success?: boolean }>(`${DM_API}/jobs?${query}`, signal).then((response) => ({
        jobs: Array.isArray(response.jobs) ? response.jobs : [],
        pagination: response.pagination ?? {},
    }));
}

export interface JobDetail {
    job: DataManagementJob;
    items: JobItem[];
}

export function getJobDetail(jobId: string, signal?: AbortSignal): Promise<JobDetail> {
    return api
        .get<{ job?: DataManagementJob; items?: JobItem[] }>(
            `${DM_API}/jobs/${encodeURIComponent(jobId)}`,
            signal,
        )
        .then((response) => ({
            job: response.job ?? { id: jobId },
            items: Array.isArray(response.items) ? response.items : [],
        }));
}

export function getJobProgress(jobId: string, signal?: AbortSignal): Promise<DataManagementJob> {
    return api
        .get<{ job?: DataManagementJob }>(`${DM_API}/jobs/${encodeURIComponent(jobId)}/progress`, signal)
        .then((response) => response.job ?? { id: jobId });
}

export function retryJob(jobId: string): Promise<DataManagementJob> {
    return api
        .post<{ job?: DataManagementJob }>(`${DM_API}/jobs/${encodeURIComponent(jobId)}/retry`, {})
        .then((response) => response.job ?? { id: jobId });
}

export function cancelJob(jobId: string, reason: string): Promise<DataManagementJob> {
    return api
        .post<{ job?: DataManagementJob }>(`${DM_API}/jobs/${encodeURIComponent(jobId)}/cancel`, { reason })
        .then((response) => response.job ?? { id: jobId });
}

/**
 * Where a migration's manifest downloads from.
 *
 * Built from a literal same-origin prefix and an encoded job id, which is what keeps the
 * value safe to put in an `href`. `failuresOnly` asks for the failed, missing and colliding
 * entries only.
 */
export function migrationManifestUrl(jobId: string, failuresOnly = false): string {
    const query = failuresOnly ? `?statuses=${encodeURIComponent(MANIFEST_FAILURE_STATUSES)}` : '';
    return apiUrl(`${DM_API}/jobs/${encodeURIComponent(jobId)}/migration-manifest${query}`);
}

/** Queue a backup, restore, migration or dry run. Answers 202 with the queued job. */
export function queueJob(
    operation: JobOperation,
    backupType: BackupType | null,
    options: JsonRecord,
): Promise<DataManagementJob> {
    return api
        .post<{ job?: DataManagementJob }>(`${DM_API}/jobs`, {
            operation,
            backup_type: backupType,
            options,
        })
        .then((response) => response.job ?? { id: '' });
}

/** The workflow step a rejected review or submission points back to, when the server names one. */
export function readWorkflowStep(error: unknown): string {
    if (error instanceof ApiError && error.payload && typeof error.payload === 'object') {
        const step = (error.payload as { workflow_step?: unknown }).workflow_step;
        return typeof step === 'string' ? step : '';
    }
    return '';
}

// ---------------------------------------------------------------------------------------
// Restore
// ---------------------------------------------------------------------------------------

export interface RestorePlan {
    source_backup_id: string;
    restore_policy: RestorePolicy;
    include_cosmos: boolean;
    include_ai_search: boolean;
    include_source_blobs: boolean;
    overwrite_confirmed: boolean;
    overwrite_confirmation_phrase: string;
}

export interface ReviewCheck {
    id?: string;
    label?: string;
    status?: string;
    message?: string;
    summary?: string;
    workflow_step?: string;
    details?: JsonRecord;
}

export interface RestoreReview {
    ready?: boolean;
    blocker_count?: number;
    warning_count?: number;
    blockers?: string[];
    warnings?: string[];
    checks?: ReviewCheck[];
    review_fingerprint?: string;
    authorization_token?: string;
    authorization_expires_at?: string;
    summary?: {
        backup_id?: string;
        backup_type?: string;
        completed_at?: string;
        artifact_count?: number;
        service_counts?: { cosmos?: number; ai_search?: number; source_blobs?: number };
        warnings?: number;
        failed_resource_names?: string[];
        differential_mode?: string;
        deletion_policy?: string;
    };
    restore_plan?: JsonRecord;
}

export function reviewRestore(
    settings: Record<string, unknown>,
    restorePlan: RestorePlan,
): Promise<RestoreReview> {
    return api
        .post<{ review?: RestoreReview }>(`${DM_API}/restore/review`, { settings, restore_plan: restorePlan })
        .then((response) => response.review ?? {});
}

// ---------------------------------------------------------------------------------------
// Migration
// ---------------------------------------------------------------------------------------

export interface MigrationSelection {
    mode: MigrationScopeMode;
    ids: string[];
    include_documents: boolean;
}

export interface MigrationPlan {
    users: MigrationSelection;
    groups: MigrationSelection;
    public_workspaces: MigrationSelection;
    include_ai_search: boolean;
    target_ai_search_writes_frozen: boolean;
    include_source_blobs: boolean;
    migration_mode: MigrationMode;
    baseline_job_id: string;
    mirror_confirmation: string;
}

export interface CatalogItem {
    id: string;
    label?: string;
    description?: string;
    document_count?: number;
}

export interface CatalogPage {
    type?: string;
    items: CatalogItem[];
    total_count: number;
    page_size?: number;
    has_more: boolean;
    continuation_token: string;
}

export function listMigrationCatalog(
    targetType: MigrationTargetType,
    search: string,
    token: string,
    signal?: AbortSignal,
): Promise<CatalogPage> {
    const params = new URLSearchParams({ search, page_size: String(MIGRATION_CATALOG_PAGE_SIZE) });
    if (token) params.set('continuation_token', token);
    return api
        .get<Partial<CatalogPage>>(
            `${DM_API}/migration/catalog/${encodeURIComponent(targetType)}?${params.toString()}`,
            signal,
        )
        .then((response) => ({
            type: response.type,
            items: Array.isArray(response.items) ? response.items : [],
            total_count: Number(response.total_count ?? 0) || 0,
            page_size: response.page_size,
            has_more: response.has_more === true,
            continuation_token:
                typeof response.continuation_token === 'string' ? response.continuation_token : '',
        }));
}

export interface MigrationScopeSummary {
    mode?: MigrationScopeMode;
    count?: number;
    document_count?: number;
    include_documents?: boolean;
    ids?: string[];
    ids_truncated?: boolean;
}

export interface MigrationReview {
    reviewed_at?: string;
    review_fingerprint?: string;
    ready?: boolean;
    blocker_count?: number;
    warning_count?: number;
    summary?: Partial<Record<MigrationTargetType, MigrationScopeSummary>> & {
        include_ai_search?: boolean;
        include_source_blobs?: boolean;
        target_ai_search_writes_frozen?: boolean;
        migration_mode?: MigrationMode;
        baseline_job_id?: string;
    };
    preview?: {
        captured_at?: string;
        baseline_job_id?: string;
        estimated_outcomes?: Partial<
            Record<
                | 'create_count'
                | 'update_count'
                | 'unchanged_count'
                | 'delete_count'
                | 'not_applicable_count'
                | 'missing_count'
                | 'conflict_count',
                number
            >
        >;
        [key: string]: unknown;
    } | null;
    checks?: ReviewCheck[];
    execution?: JsonRecord;
    authorization_token?: string;
    authorization_expires_at?: string;
}

export function reviewMigration(
    settings: Record<string, unknown>,
    migrationPlan: MigrationPlan,
): Promise<MigrationReview> {
    return api
        .post<{ review?: MigrationReview }>(`${DM_API}/migration/review`, {
            settings,
            migration_plan: migrationPlan,
        })
        .then((response) => response.review ?? {});
}

// ---------------------------------------------------------------------------------------
// Cosmos editor
// ---------------------------------------------------------------------------------------

export interface CosmosContainer {
    id: string;
    name: string;
    display_name?: string;
    category?: string;
    partition_key_path?: string;
    partition_key_field?: string;
    max_page_size?: number;
    empty_query_limit?: number;
    editable?: boolean;
}

export interface CosmosQueryItem {
    id: string | null;
    partition_key: unknown;
    etag?: string | null;
    timestamp?: number | null;
    selectable?: boolean;
    preview?: string;
}

export interface CosmosQueryResult {
    container?: CosmosContainer;
    query?: { mode?: 'empty' | 'custom'; page_size?: number; empty_query_limit_applied?: boolean };
    items: CosmosQueryItem[];
    count?: number;
    continuation_token?: string | null;
    has_more?: boolean;
    duration_ms?: number;
}

export interface CosmosDocumentResult {
    container?: CosmosContainer;
    document: JsonRecord;
    id: string;
    partition_key: unknown;
    etag?: string | null;
    change_summary?: {
        changed_paths?: string[];
        changed_count?: number;
        added_count?: number;
        removed_count?: number;
        updated_count?: number;
        truncated?: boolean;
    };
}

export function listCosmosContainers(signal?: AbortSignal): Promise<CosmosContainer[]> {
    return api
        .get<{ containers?: CosmosContainer[] }>(`${DM_API}/cosmos-editor/containers`, signal)
        .then((response) => (Array.isArray(response.containers) ? response.containers : []));
}

/** Record that an administrator accepted the editor's danger prompt. The server logs it. */
export function acknowledgeCosmosDanger(): Promise<void> {
    return api.post<unknown>(`${DM_API}/cosmos-editor/danger-acknowledgement`, {}).then(() => undefined);
}

export function queryCosmos(
    container: string,
    query: string,
    pageSize: number,
    continuationToken: string | null,
    signal?: AbortSignal,
): Promise<CosmosQueryResult> {
    return api
        .post<Partial<CosmosQueryResult>>(
            `${DM_API}/cosmos-editor/query`,
            { container, query, page_size: pageSize, continuation_token: continuationToken },
            signal,
        )
        .then((response) => ({ ...response, items: Array.isArray(response.items) ? response.items : [] }));
}

export function openCosmosDocument(
    container: string,
    id: string,
    partitionKey: unknown,
    signal?: AbortSignal,
): Promise<CosmosDocumentResult> {
    return api.post<CosmosDocumentResult>(
        `${DM_API}/cosmos-editor/document`,
        { container, id, partition_key: partitionKey },
        signal,
    );
}

export function saveCosmosDocument(input: {
    container: string;
    id: string;
    partitionKey: unknown;
    etag: string;
    document: JsonRecord;
    confirmationPhrase: string;
}): Promise<CosmosDocumentResult> {
    return api.put<CosmosDocumentResult>(`${DM_API}/cosmos-editor/document`, {
        container: input.container,
        id: input.id,
        partition_key: input.partitionKey,
        etag: input.etag,
        document: input.document,
        confirmation_accepted: true,
        confirmation_phrase: input.confirmationPhrase,
    });
}

/** A readable message for any failure, preferring the server's own sanitized text. */
export function errorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError || error instanceof Error) {
        return error.message || fallback;
    }
    return fallback;
}
