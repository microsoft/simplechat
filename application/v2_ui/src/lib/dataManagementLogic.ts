// dataManagementLogic.ts
// Pure decisions behind Admin Settings > Backup & Recovery.
//
// Kept apart from the components because these are the parts worth executing in a test:
// what a save sends, which edits count as unsaved, whether a review still describes what
// would run, when a destructive action may proceed, and what a job's telemetry says. Each
// is invisible in a screenshot and each has a server contract on the other side of it.

import type { SectionStatus } from './adminSections';
import {
    COSMOS_EDITOR_MAX_QUERY_LENGTH,
    DM_DEFAULTS,
    DM_EDITABLE_KEYS,
    DM_NUMBER_BOUNDS,
    HISTORY_MAX_RANGE_DAYS,
    MIGRATION_MAX_SELECTED_IDS,
    MIGRATION_TARGET_TYPES,
    MIRROR_CONFIRMATION_PHRASE,
    RESTORE_OVERWRITE_PHRASE,
    RETENTION_MAX_DAYS,
    RETENTION_UNIT_DAYS,
    TARGET_COSMOS_DATABASE_NAME,
    TERMINAL_JOB_STATUSES,
    ACTIVE_JOB_STATUSES,
    type BackupGlobalSummary,
    type CatalogItem,
    type DataManagementJob,
    type DmDraft,
    type DmEditableKey,
    type DmSettings,
    type JsonRecord,
    type MigrationMode,
    type MigrationPlan,
    type MigrationReview,
    type MigrationScopeMode,
    type MigrationTargetType,
    type RestorePlan,
    type RestorePolicy,
    type RestoreReview,
    type RetentionUnit,
    type ReviewCheck,
} from './dataManagement';

// ---------------------------------------------------------------------------------------
// Section ids (from admin_settings_nav.py, group "backup-recovery")
// ---------------------------------------------------------------------------------------

export const DM_SECTION_IDS = {
    readiness: 'data-management-readiness-section',
    backup: 'data-management-backup-section',
    schedule: 'data-management-schedule-section',
    storage: 'data-management-storage-section',
    encryption: 'data-management-encryption-section',
    migration: 'data-management-migration-section',
    inventory: 'data-management-backup-inventory-section',
    cosmosEditor: 'data-management-cosmos-editor-section',
    jobs: 'data-management-jobs-section',
} as const;

/** Main settings sections the Backup & Recovery cards link to. */
export const LINKED_SECTION_IDS = {
    keyVault: 'keyvault-section',
    enhancedCitations: 'enhanced-citations-section',
} as const;

/**
 * Main settings keys the data-management save is validated against.
 *
 * The server refuses backup storage that matches the Enhanced Citations account, and reads
 * those keys from the *saved* settings document. Saving backup settings while one of these
 * has an unsaved edit would validate against a value that is about to change.
 */
export const DM_DEPENDENT_MAIN_KEYS: readonly string[] = [
    'enable_enhanced_citations',
    'office_docs_storage_account_url',
    'office_docs_storage_account_blob_endpoint',
];

/** Key generation stores the key in Key Vault when these say so, read from saved settings. */
export const KEY_GENERATION_DEPENDENT_MAIN_KEYS: readonly string[] = [
    'enable_key_vault_secret_storage',
    'key_vault_name',
];

// ---------------------------------------------------------------------------------------
// Values
// ---------------------------------------------------------------------------------------

export type DmValues = Record<DmEditableKey, unknown>;

/** Current value of every editable key: the unsaved edit, else the saved value, else the default. */
export function readDmValues(settings: DmSettings | null | undefined, draft: DmDraft): DmValues {
    const values = {} as DmValues;
    for (const key of DM_EDITABLE_KEYS) {
        if (Object.prototype.hasOwnProperty.call(draft, key)) {
            values[key] = draft[key];
        } else if (settings && settings[key] !== undefined && settings[key] !== null) {
            values[key] = settings[key];
        } else {
            values[key] = DM_DEFAULTS[key];
        }
    }
    return values;
}

export function asText(value: unknown, fallback = ''): string {
    if (value === undefined || value === null) return fallback;
    return typeof value === 'string' ? value : String(value);
}

export function asFlag(value: unknown): boolean {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') return ['true', 'on', 'yes', '1'].includes(value.trim().toLowerCase());
    return Boolean(value);
}

export function asCount(value: unknown, fallback = 0): number {
    const parsed = typeof value === 'number' ? value : Number.parseFloat(asText(value));
    return Number.isFinite(parsed) ? parsed : fallback;
}

// ---------------------------------------------------------------------------------------
// Retention
// ---------------------------------------------------------------------------------------

export function retentionUnitDays(unit: unknown): number {
    const key = asText(unit) as RetentionUnit;
    return RETENTION_UNIT_DAYS[key] ?? RETENTION_UNIT_DAYS.days;
}

/** The largest value the unit allows, so the derived day count stays within the server's cap. */
export function retentionMaxValue(unit: unknown): number {
    return Math.max(1, Math.floor(RETENTION_MAX_DAYS / retentionUnitDays(unit)));
}

/** Days a value and unit come to, clamped exactly as the classic page clamps them. */
export function computeRetentionDays(value: unknown, unit: unknown): number {
    const amount = Math.trunc(asCount(value, 30));
    return Math.max(1, Math.min(RETENTION_MAX_DAYS, amount * retentionUnitDays(unit)));
}

// ---------------------------------------------------------------------------------------
// Save payload and unsaved edits
// ---------------------------------------------------------------------------------------

/**
 * The object a save sends.
 *
 * Mirrors `collectSettings()` on the classic page: every editable key, the derived day
 * count, the fixed destination database, and only the credential that belongs to the
 * selected authentication mode. A credential still holding the placeholder is sent as the
 * placeholder, which the server reads as "keep the stored value".
 */
export function buildDmSettingsPayload(values: DmValues): Record<DmEditableKey, unknown> {
    const backupAuth =
        asText(values.backup_storage_authentication_type, 'managed_identity') || 'managed_identity';
    const targetStorageAuth =
        asText(values.target_enhanced_citations_storage_authentication_type, 'managed_identity') ||
        'managed_identity';
    const number = (key: DmEditableKey) => Math.trunc(asCount(values[key], asCount(DM_DEFAULTS[key])));

    return {
        enabled: asFlag(values.enabled),
        full_backup_frequency: asText(values.full_backup_frequency) || 'weekly',
        scheduled_time_utc: asText(values.scheduled_time_utc) || '03:00',
        retention_value: number('retention_value'),
        retention_unit: asText(values.retention_unit) || 'days',
        retention_days: computeRetentionDays(values.retention_value, values.retention_unit),
        partial_backups_enabled: asFlag(values.partial_backups_enabled),
        low_impact_mode: asFlag(values.low_impact_mode),
        include_cosmos: asFlag(values.include_cosmos),
        include_ai_search: asFlag(values.include_ai_search),
        include_source_blobs: asFlag(values.include_source_blobs),
        backup_storage_authentication_type: backupAuth,
        backup_storage_blob_endpoint:
            backupAuth === 'managed_identity' ? asText(values.backup_storage_blob_endpoint).trim() : '',
        backup_storage_container_name:
            asText(values.backup_storage_container_name).trim() || 'simplechat-backups',
        backup_storage_connection_string:
            backupAuth === 'connection_string' ? asText(values.backup_storage_connection_string) : '',
        backup_storage_path_prefix: asText(values.backup_storage_path_prefix).trim() || 'simplechat-backups',
        encryption_enabled: asFlag(values.encryption_enabled),
        backup_max_parallel_operations: number('backup_max_parallel_operations'),
        backup_retry_count: number('backup_retry_count'),
        backup_blob_max_parallel_operations: number('backup_blob_max_parallel_operations'),
        backup_blob_chunk_size_mib: number('backup_blob_chunk_size_mib'),
        backup_blob_retry_count: number('backup_blob_retry_count'),
        backup_capacity_failure_policy:
            asText(values.backup_capacity_failure_policy) || 'continue_without_boost',
        backup_temporary_source_ru_enabled: asFlag(values.backup_temporary_source_ru_enabled),
        backup_temporary_source_ru: number('backup_temporary_source_ru'),
        target_cosmos_authentication_type:
            asText(values.target_cosmos_authentication_type) || 'managed_identity',
        target_cosmos_endpoint: asText(values.target_cosmos_endpoint).trim(),
        target_cosmos_database_name: TARGET_COSMOS_DATABASE_NAME,
        target_cosmos_key: asText(values.target_cosmos_key),
        target_cosmos_subscription_id: asText(values.target_cosmos_subscription_id).trim(),
        target_cosmos_resource_group: asText(values.target_cosmos_resource_group).trim(),
        target_ai_search_authentication_type:
            asText(values.target_ai_search_authentication_type) || 'managed_identity',
        target_ai_search_endpoint: asText(values.target_ai_search_endpoint).trim(),
        target_ai_search_key: asText(values.target_ai_search_key),
        target_enhanced_citations_storage_authentication_type: targetStorageAuth,
        target_enhanced_citations_storage_blob_endpoint:
            targetStorageAuth === 'managed_identity'
                ? asText(values.target_enhanced_citations_storage_blob_endpoint).trim()
                : '',
        target_enhanced_citations_storage_connection_string:
            targetStorageAuth === 'connection_string'
                ? asText(values.target_enhanced_citations_storage_connection_string)
                : '',
        migration_max_parallel_operations: number('migration_max_parallel_operations'),
        migration_retry_count: number('migration_retry_count'),
        migration_skip_recent_within_hours: number('migration_skip_recent_within_hours'),
        migration_temporary_destination_ru_enabled: asFlag(values.migration_temporary_destination_ru_enabled),
        migration_temporary_destination_ru: number('migration_temporary_destination_ru'),
    };
}

function comparable(key: DmEditableKey, value: unknown): string {
    const fallback = DM_DEFAULTS[key];
    if (typeof fallback === 'boolean') return String(asFlag(value));
    if (typeof fallback === 'number') return String(asCount(value, fallback));
    return asText(value).trim();
}

/**
 * Keys whose unsaved edit differs from the saved value.
 *
 * An edit that was typed and then typed back is not a change, so the Save bar does not
 * count it. Derived keys never count on their own.
 */
export function dmDirtyKeys(settings: DmSettings | null | undefined, draft: DmDraft): DmEditableKey[] {
    const saved = readDmValues(settings, {});
    return DM_EDITABLE_KEYS.filter(
        (key) =>
            Object.prototype.hasOwnProperty.call(draft, key) &&
            key !== 'retention_days' &&
            key !== 'target_cosmos_database_name' &&
            comparable(key, draft[key]) !== comparable(key, saved[key]),
    );
}

const TIME_PATTERN = /^([01]\d|2[0-3]):([0-5]\d)$/;
const GUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidGuid(value: string): boolean {
    return GUID_PATTERN.test(value.trim());
}

/**
 * Problems the browser can see before a save is sent, keyed by settings key.
 *
 * The server clamps out-of-range numbers rather than refusing them, which would silently
 * save a different value than the one on screen. Catching them here keeps what is saved and
 * what was typed the same.
 */
export function validateDmValues(values: DmValues): Partial<Record<DmEditableKey, string>> {
    const errors: Partial<Record<DmEditableKey, string>> = {};
    if (!TIME_PATTERN.test(asText(values.scheduled_time_utc))) {
        errors.scheduled_time_utc = 'Enter a time as HH:MM in 24-hour UTC.';
    }
    const retention = asCount(values.retention_value, Number.NaN);
    const retentionMax = retentionMaxValue(values.retention_unit);
    if (!Number.isInteger(retention) || retention < 1 || retention > retentionMax) {
        errors.retention_value = `Enter a whole number from 1 to ${retentionMax}.`;
    }
    for (const [key, bounds] of Object.entries(DM_NUMBER_BOUNDS) as [
        DmEditableKey,
        { min: number; max: number; step?: number },
    ][]) {
        const value = asCount(values[key], Number.NaN);
        if (!Number.isInteger(value) || value < bounds.min || value > bounds.max) {
            errors[key] =
                `Enter a whole number from ${bounds.min.toLocaleString()} to ${bounds.max.toLocaleString()}.`;
        } else if (bounds.step && (value - bounds.min) % bounds.step !== 0) {
            errors[key] = `Use steps of ${bounds.step.toLocaleString()}.`;
        }
    }
    if (!asText(values.backup_storage_container_name).trim()) {
        errors.backup_storage_container_name = 'A container name is required.';
    }
    return errors;
}

// ---------------------------------------------------------------------------------------
// Configuration state, section status and readiness
// ---------------------------------------------------------------------------------------

export function isSecretSet(value: unknown): boolean {
    return asText(value).length > 0;
}

/** Whether backups have somewhere to go, judged from the current (possibly unsaved) values. */
export function isBackupStorageConfigured(values: DmValues): boolean {
    return asText(values.backup_storage_authentication_type) === 'connection_string'
        ? isSecretSet(values.backup_storage_connection_string)
        : asText(values.backup_storage_blob_endpoint).trim().length > 0;
}

export type KeyStorage = 'key_vault' | 'settings' | 'not_configured';

export function readKeyStorage(settings: DmSettings | null | undefined): KeyStorage {
    const value = asText(settings?.encryption_key_storage);
    return value === 'key_vault' || value === 'settings' ? value : 'not_configured';
}

export function keyStorageLabel(storage: KeyStorage): string {
    if (storage === 'key_vault') return 'Key Vault';
    if (storage === 'settings') return 'Backup settings document';
    return 'Not generated';
}

export function isDestinationConfigured(values: DmValues): boolean {
    return asText(values.target_cosmos_endpoint).trim().length > 0;
}

/**
 * The status chip each Backup & Recovery card shows, where it has one to show.
 *
 * Cards that are workbenches rather than configuration -- the inventory, jobs, the editor --
 * have no configured/unconfigured state, and claiming one would be noise.
 */
export function dmSectionStatuses(
    settings: DmSettings | null | undefined,
    draft: DmDraft,
): Partial<Record<string, SectionStatus>> {
    if (!settings) return {};
    const values = readDmValues(settings, draft);
    const storageReady = isBackupStorageConfigured(values);
    const encryptionOn = asFlag(values.encryption_enabled);
    const keyReady = readKeyStorage(settings) !== 'not_configured';
    return {
        [DM_SECTION_IDS.schedule]: asFlag(values.enabled) ? 'ready' : 'off',
        [DM_SECTION_IDS.storage]: storageReady ? 'ready' : 'incomplete',
        [DM_SECTION_IDS.encryption]: !encryptionOn ? 'off' : keyReady ? 'ready' : 'incomplete',
        [DM_SECTION_IDS.backup]: storageReady ? 'none' : 'blocked',
    };
}

export type ReadinessState = 'ok' | 'attention' | 'off';

export interface ReadinessItem {
    id: string;
    label: string;
    state: ReadinessState;
    detail: string;
    /** The card that resolves this item. */
    sectionId: string;
}

/**
 * The Start Here checklist, built only from what the server reported.
 *
 * Nothing here is inferred from a test the browser ran earlier: a storage test proves a
 * connection at one moment, and showing it as a lasting fact would outlive the proof.
 */
export function buildReadinessChecklist(
    settings: DmSettings | null | undefined,
    draft: DmDraft,
    summary: BackupGlobalSummary | null | undefined,
): ReadinessItem[] {
    const values = readDmValues(settings, draft);
    const keyStorage = readKeyStorage(settings);
    const encryptionOn = asFlag(values.encryption_enabled);
    const scheduled = asFlag(values.enabled);
    const latestFull = summary?.latest_full ?? null;

    return [
        {
            id: 'storage',
            label: 'Backup storage',
            state: isBackupStorageConfigured(values) ? 'ok' : 'attention',
            detail: isBackupStorageConfigured(values)
                ? `${asText(values.backup_storage_authentication_type) === 'connection_string' ? 'Connection string' : 'Managed identity'} · container ${asText(values.backup_storage_container_name)}`
                : 'Choose a dedicated storage account before running a backup.',
            sectionId: DM_SECTION_IDS.storage,
        },
        {
            id: 'encryption',
            label: 'Encryption key',
            state: !encryptionOn
                ? 'off'
                : keyStorage === 'not_configured'
                  ? 'attention'
                  : keyStorage === 'settings'
                    ? 'attention'
                    : 'ok',
            detail: !encryptionOn
                ? 'Backup artifacts are written unencrypted.'
                : keyStorage === 'not_configured'
                  ? 'Generate a key before the first encrypted backup.'
                  : keyStorage === 'settings'
                    ? 'Stored in the backup settings document. Key Vault is recommended.'
                    : 'Stored in Key Vault.',
            sectionId: DM_SECTION_IDS.encryption,
        },
        {
            id: 'schedule',
            label: 'Schedule',
            state: scheduled ? 'ok' : 'off',
            detail: scheduled
                ? settings?.next_full_backup_run_at
                    ? `Next full backup ${formatDateTime(settings.next_full_backup_run_at)}`
                    : 'Scheduled backups are on.'
                : 'Backups run only when queued by hand.',
            sectionId: DM_SECTION_IDS.schedule,
        },
        {
            id: 'latest-full',
            label: 'Latest full backup',
            state: latestFull ? 'ok' : 'attention',
            detail: latestFull
                ? `Completed ${formatDateTime(latestFull.completed_at || latestFull.created_at)}`
                : summary
                  ? 'No completed full backup yet. Restore needs one.'
                  : 'Backup history has not loaded yet.',
            sectionId: DM_SECTION_IDS.inventory,
        },
        {
            id: 'destination',
            label: 'Restore and migration destination',
            state: isDestinationConfigured(values) ? 'ok' : 'off',
            detail: isDestinationConfigured(values)
                ? `Cosmos DB ${endpointHost(values.target_cosmos_endpoint)}`
                : 'Needed only to restore or migrate. Set it in Migration.',
            sectionId: DM_SECTION_IDS.migration,
        },
    ];
}

/** The host part of an endpoint, for summaries that should not repeat a whole URL. */
export function endpointHost(endpoint: unknown): string {
    const text = asText(endpoint).trim();
    if (!text) return '';
    try {
        return new URL(text.includes('://') ? text : `https://${text}`).host || text;
    } catch {
        return text;
    }
}

/** Peak bytes the source-file transfer can buffer: concurrent transfers times chunk size. */
export function blobBufferEstimateMib(values: DmValues): number {
    return (
        Math.max(1, Math.trunc(asCount(values.backup_blob_max_parallel_operations, 4))) *
        Math.max(1, Math.trunc(asCount(values.backup_blob_chunk_size_mib, 8)))
    );
}

// ---------------------------------------------------------------------------------------
// History lists
// ---------------------------------------------------------------------------------------

/**
 * Continuation-token paging with a way back.
 *
 * The API pages forward only. Previous works by remembering the token each earlier page was
 * fetched with, which is also what the classic page does.
 */
export interface PagerState {
    current: string | null;
    previous: Array<string | null>;
    next: string | null;
}

export const FIRST_PAGE: PagerState = { current: null, previous: [], next: null };

export function pagerAfterLoad(state: PagerState, nextToken: string | null | undefined): PagerState {
    return { ...state, next: nextToken || null };
}

export function pagerForward(state: PagerState): PagerState {
    if (!state.next) return state;
    return { current: state.next, previous: [...state.previous, state.current], next: null };
}

export function pagerBack(state: PagerState): PagerState {
    if (!state.previous.length) return state;
    const previous = [...state.previous];
    const current = previous.pop() ?? null;
    return { current, previous, next: null };
}

export function pagerPageNumber(state: PagerState): number {
    return state.previous.length + 1;
}

/**
 * Whether a created-date filter can be sent.
 *
 * The server needs both dates or neither, the end after the start, and no more than a year
 * between them. Saying so beside the inputs beats a 400 from the list.
 */
export function validateHistoryDateRange(createdFrom: string, createdTo: string): string | null {
    if (!createdFrom && !createdTo) return null;
    if (!createdFrom || !createdTo) return 'Choose both a start and an end date.';
    const start = Date.parse(`${createdFrom}T00:00:00Z`);
    const end = Date.parse(`${createdTo}T00:00:00Z`);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return 'Enter valid dates.';
    if (end < start) return 'The end date must be on or after the start date.';
    // The end date is inclusive, so the window is one day longer than the difference.
    if ((end - start) / 86_400_000 + 1 > HISTORY_MAX_RANGE_DAYS) {
        return `Choose a range of ${HISTORY_MAX_RANGE_DAYS} days or less.`;
    }
    return null;
}

// ---------------------------------------------------------------------------------------
// Review evidence
// ---------------------------------------------------------------------------------------

export type CheckTone = 'pass' | 'warning' | 'block';

export interface ReviewCheckView {
    id: string;
    label: string;
    tone: CheckTone;
    message: string;
    /** Migration only: the wizard step that fixes this check. */
    workflowStep?: string;
}

/**
 * One shape for both review payloads.
 *
 * Restore says `warn` and `message`; migration says `warning` and `summary`. An unknown
 * status reads as a blocker, which is the conservative choice when a check cannot be
 * understood.
 */
export function normalizeReviewChecks(checks: ReviewCheck[] | undefined | null): ReviewCheckView[] {
    if (!Array.isArray(checks)) return [];
    return checks.map((check, index) => {
        const status = asText(check?.status).toLowerCase();
        const tone: CheckTone =
            status === 'pass' || status === 'passed'
                ? 'pass'
                : status === 'warn' || status === 'warning'
                  ? 'warning'
                  : 'block';
        return {
            id: asText(check?.id) || `check-${index}`,
            label: asText(check?.label) || asText(check?.id) || 'Review check',
            tone,
            message: asText(check?.message) || asText(check?.summary) || 'No details were returned.',
            workflowStep: asText(check?.workflow_step) || undefined,
        };
    });
}

export interface ReviewHeadline {
    tone: 'ready' | 'warning' | 'blocked' | 'stale' | 'none';
    text: string;
}

export function reviewHeadline(
    review: { ready?: boolean; blocker_count?: number; warning_count?: number } | null | undefined,
    stale: boolean,
): ReviewHeadline {
    if (!review) return { tone: 'none', text: 'Not reviewed' };
    if (stale) return { tone: 'stale', text: 'Review is out of date' };
    if (review.ready) {
        const warnings = asCount(review.warning_count);
        return warnings
            ? { tone: 'warning', text: `Ready with ${warnings} warning${warnings === 1 ? '' : 's'}` }
            : { tone: 'ready', text: 'Ready' };
    }
    const blockers = asCount(review.blocker_count);
    return { tone: 'blocked', text: `${blockers || 'Has'} blocker${blockers === 1 ? '' : 's'}` };
}

/** Seconds until a review authorization lapses, or null when the review carries none. */
export function secondsUntil(expiresAt: string | undefined | null, now: number): number | null {
    if (!expiresAt) return null;
    const expiry = Date.parse(expiresAt);
    return Number.isFinite(expiry) ? Math.max(0, Math.floor((expiry - now) / 1000)) : null;
}

/** A stable string for a value, with object keys sorted, to compare review inputs. */
export function stableStringify(value: unknown): string {
    if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
    if (value && typeof value === 'object') {
        const entries = Object.entries(value as Record<string, unknown>)
            .filter(([, entry]) => entry !== undefined)
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
        return `{${entries.map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`).join(',')}}`;
    }
    return JSON.stringify(value ?? null);
}

// ---------------------------------------------------------------------------------------
// Restore
// ---------------------------------------------------------------------------------------

export interface RestoreDraft {
    policy: RestorePolicy;
    includeCosmos: boolean;
    includeAiSearch: boolean;
    includeSourceBlobs: boolean;
    overwritePhrase: string;
    acknowledged: boolean;
}

/** Every time the restore dialog opens it starts here, as the classic modal does. */
export function initialRestoreDraft(): RestoreDraft {
    return {
        policy: 'create_only',
        includeCosmos: true,
        includeAiSearch: true,
        includeSourceBlobs: true,
        overwritePhrase: '',
        acknowledged: false,
    };
}

export function buildRestorePlan(backupId: string, draft: RestoreDraft): RestorePlan {
    const overwrite = draft.policy === 'overwrite_existing';
    return {
        source_backup_id: backupId,
        restore_policy: draft.policy,
        include_cosmos: draft.includeCosmos,
        include_ai_search: draft.includeAiSearch,
        include_source_blobs: draft.includeSourceBlobs,
        overwrite_confirmed: overwrite,
        overwrite_confirmation_phrase: overwrite ? draft.overwritePhrase : '',
    };
}

/** Destination settings the restore review fingerprint binds to. */
export const RESTORE_FINGERPRINT_SETTINGS: readonly DmEditableKey[] = [
    'target_cosmos_authentication_type',
    'target_cosmos_endpoint',
    'target_ai_search_authentication_type',
    'target_ai_search_endpoint',
    'target_enhanced_citations_storage_authentication_type',
    'target_enhanced_citations_storage_blob_endpoint',
];

/**
 * What a restore review was run against.
 *
 * The typed phrase and the acknowledgement are left out: neither changes what the server
 * reviewed, so typing them must not throw the review away.
 */
export function restoreReviewKey(backupId: string, draft: RestoreDraft, values: DmValues): string {
    const plan = buildRestorePlan(backupId, draft);
    return stableStringify({
        plan: { ...plan, overwrite_confirmation_phrase: undefined },
        settings: Object.fromEntries(
            RESTORE_FINGERPRINT_SETTINGS.map((key) => [key, asText(values[key]).trim()]),
        ),
    });
}

export function restoreSurfaceSelected(draft: RestoreDraft): boolean {
    return draft.includeCosmos || draft.includeAiSearch || draft.includeSourceBlobs;
}

export function canQueueRestore(input: {
    review: RestoreReview | null;
    reviewCurrent: boolean;
    draft: RestoreDraft;
    expiresInSeconds: number | null;
    busy: boolean;
}): boolean {
    const { review, reviewCurrent, draft, expiresInSeconds, busy } = input;
    const phraseOk =
        draft.policy !== 'overwrite_existing' || draft.overwritePhrase === RESTORE_OVERWRITE_PHRASE;
    return Boolean(
        review?.ready === true &&
        reviewCurrent &&
        review.authorization_token &&
        (expiresInSeconds === null || expiresInSeconds > 0) &&
        draft.acknowledged &&
        phraseOk &&
        !busy,
    );
}

// ---------------------------------------------------------------------------------------
// Migration
// ---------------------------------------------------------------------------------------

/** Step ids match the server's `workflow_step` values, so a check can point back at one. */
export const MIGRATION_STEPS = ['target', 'scope', 'options', 'review', 'confirm', 'progress'] as const;
export type MigrationStep = (typeof MIGRATION_STEPS)[number];

export const MIGRATION_STEP_LABELS: Record<MigrationStep, string> = {
    target: 'Destination',
    scope: 'Scope',
    options: 'What moves',
    review: 'Review',
    confirm: 'Confirm',
    progress: 'Progress',
};

export function isMigrationStep(value: string): value is MigrationStep {
    return (MIGRATION_STEPS as readonly string[]).includes(value);
}

export const MIGRATION_MODE_LABELS: Record<MigrationMode, string> = {
    new_only: 'Copy missing items only',
    delta_upsert: 'Catch up changed items',
    mirror_with_deletions: 'Make destination match source',
};

export const MIGRATION_TARGET_LABELS: Record<MigrationTargetType, { singular: string; plural: string }> = {
    users: { singular: 'user', plural: 'Users' },
    groups: { singular: 'group', plural: 'Groups' },
    public_workspaces: { singular: 'public workspace', plural: 'Public workspaces' },
};

export interface MigrationScopeState {
    mode: MigrationScopeMode;
    /** Chosen records, kept with their labels so the selection reads back across pages. */
    selected: CatalogItem[];
    includeDocuments: boolean;
}

export type SubmissionState = 'idle' | 'submitting' | 'accepted' | 'uncertain';

export interface MigrationWizardState {
    step: MigrationStep;
    /** Highest step index reached; the rail allows going back to any of these. */
    reached: number;
    scopes: Record<MigrationTargetType, MigrationScopeState>;
    includeAiSearch: boolean;
    searchWritesFrozen: boolean;
    includeSourceBlobs: boolean;
    mode: MigrationMode;
    baselineJobId: string;
    mirrorPhrase: string;
    acknowledged: boolean;
    review: MigrationReview | null;
    /** `migrationReviewKey` at the moment the review ran. */
    reviewKey: string | null;
    reviewError: string | null;
    submission: SubmissionState;
    jobId: string | null;
}

export function initialMigrationState(): MigrationWizardState {
    const scope = (): MigrationScopeState => ({ mode: 'none', selected: [], includeDocuments: false });
    return {
        step: 'target',
        reached: 0,
        scopes: { users: scope(), groups: scope(), public_workspaces: scope() },
        includeAiSearch: true,
        searchWritesFrozen: false,
        includeSourceBlobs: false,
        mode: 'new_only',
        baselineJobId: '',
        mirrorPhrase: '',
        acknowledged: false,
        review: null,
        reviewKey: null,
        reviewError: null,
        submission: 'idle',
        jobId: null,
    };
}

/** The plan the API expects, built exactly as the classic page builds it. */
export function buildMigrationPlan(state: MigrationWizardState): MigrationPlan {
    const selection = (type: MigrationTargetType) => {
        const scope = state.scopes[type];
        return {
            mode: scope.mode,
            ids: scope.mode === 'selected' ? scope.selected.map((item) => item.id) : [],
            include_documents: scope.mode !== 'none' && scope.includeDocuments,
        };
    };
    return {
        users: selection('users'),
        groups: selection('groups'),
        public_workspaces: selection('public_workspaces'),
        include_ai_search: state.includeAiSearch,
        target_ai_search_writes_frozen: state.includeAiSearch && state.searchWritesFrozen,
        include_source_blobs: state.includeSourceBlobs,
        migration_mode: state.mode,
        baseline_job_id: state.mode === 'new_only' ? '' : state.baselineJobId.trim(),
        mirror_confirmation: state.mode === 'mirror_with_deletions' ? state.mirrorPhrase : '',
    };
}

/** Settings the migration review fingerprint covers (`_migration_review_fingerprint`). */
export const MIGRATION_FINGERPRINT_SETTINGS: readonly DmEditableKey[] = [
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
];

/**
 * What a migration review was run against.
 *
 * The mirror phrase is excluded because the server excludes it from its own fingerprint:
 * it authorizes the run rather than changing it, so typing it on the Confirm step must not
 * make the review stale.
 */
export function migrationReviewKey(state: MigrationWizardState, values: DmValues): string {
    const payload = buildDmSettingsPayload(values);
    const plan = buildMigrationPlan(state);
    return stableStringify({
        plan: { ...plan, mirror_confirmation: undefined },
        settings: Object.fromEntries(MIGRATION_FINGERPRINT_SETTINGS.map((key) => [key, payload[key]])),
    });
}

export function isMigrationReviewCurrent(state: MigrationWizardState, values: DmValues): boolean {
    return Boolean(state.review && state.reviewKey && state.reviewKey === migrationReviewKey(state, values));
}

export function selectedScopeCount(state: MigrationWizardState): number {
    return MIGRATION_TARGET_TYPES.filter((type) => {
        const scope = state.scopes[type];
        return scope.mode === 'all' || (scope.mode === 'selected' && scope.selected.length > 0);
    }).length;
}

/**
 * Why the wizard cannot move past a step, or null when it can.
 *
 * These mirror the classic gates and add the two checks the server would otherwise only
 * report after a review round trip: a malformed baseline id, and RU Boost without the
 * subscription and resource group it needs.
 */
export function migrationStepIssue(
    step: MigrationStep,
    state: MigrationWizardState,
    values: DmValues,
): string | null {
    if (step === 'target') {
        return isDestinationConfigured(values) ? null : 'Add the destination Cosmos DB endpoint to continue.';
    }
    if (step === 'scope') {
        for (const type of MIGRATION_TARGET_TYPES) {
            if (state.scopes[type].selected.length > MIGRATION_MAX_SELECTED_IDS) {
                return `Choose at most ${MIGRATION_MAX_SELECTED_IDS.toLocaleString()} ${MIGRATION_TARGET_LABELS[type].plural.toLowerCase()}, or choose All.`;
            }
        }
        return selectedScopeCount(state) > 0 ? null : 'Choose at least one user, group, or public workspace.';
    }
    if (step === 'options') {
        if (state.includeAiSearch && !state.searchWritesFrozen) {
            return 'Confirm that other writers to the destination AI Search are frozen, or leave AI Search out.';
        }
        if (state.mode !== 'new_only' && state.baselineJobId.trim() && !isValidGuid(state.baselineJobId)) {
            return 'The previous migration job ID must be a job GUID, or left blank.';
        }
        if (
            asFlag(values.migration_temporary_destination_ru_enabled) &&
            (!asText(values.target_cosmos_subscription_id).trim() ||
                !asText(values.target_cosmos_resource_group).trim())
        ) {
            return 'Destination RU Boost needs the subscription ID and resource group.';
        }
        return null;
    }
    if (step === 'review') {
        if (!state.review) return 'Run the preflight review to continue.';
        if (!isMigrationReviewCurrent(state, values)) return 'Inputs changed after the review. Run it again.';
        return state.review.ready ? null : 'Resolve the blockers, then run the review again.';
    }
    return null;
}

/** The furthest step the wizard can open now, given every earlier gate. */
export function furthestOpenStep(state: MigrationWizardState, values: DmValues): number {
    let index = 0;
    while (index < MIGRATION_STEPS.length - 1 && !migrationStepIssue(MIGRATION_STEPS[index], state, values)) {
        index += 1;
    }
    return index;
}

export function canExecuteMigration(state: MigrationWizardState, values: DmValues, now: number): boolean {
    const review = state.review;
    const expires = secondsUntil(review?.authorization_expires_at, now);
    const mirrorOk =
        state.mode !== 'mirror_with_deletions' || state.mirrorPhrase === MIRROR_CONFIRMATION_PHRASE;
    return Boolean(
        review?.ready === true &&
        review.authorization_token &&
        isMigrationReviewCurrent(state, values) &&
        (expires === null || expires > 0) &&
        state.acknowledged &&
        mirrorOk &&
        state.submission === 'idle',
    );
}

// ---------------------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------------------

export function isActiveJob(status: unknown): boolean {
    return ACTIVE_JOB_STATUSES.has(asText(status));
}

export function isTerminalJob(status: unknown): boolean {
    return TERMINAL_JOB_STATUSES.has(asText(status));
}

export function progressPercent(progress: JsonRecord | undefined | null): number {
    const percent = Number.parseInt(asText(progress?.percent_complete), 10);
    return Number.isNaN(percent) ? 0 : Math.max(0, Math.min(100, percent));
}

export type StatusTone = 'ok' | 'warn' | 'danger' | 'active' | 'neutral';

export function jobStatusTone(status: unknown): StatusTone {
    const value = asText(status);
    if (value === 'completed') return 'ok';
    if (value === 'completed_with_warnings') return 'warn';
    if (value === 'failed' || value === 'canceled') return 'danger';
    if (value === 'running') return 'active';
    return 'neutral';
}

/** `completed_with_warnings` → `Completed with warnings`. */
export function humanizeToken(value: unknown): string {
    const text = asText(value).trim();
    if (!text) return '';
    if (text in MIGRATION_MODE_LABELS) return MIGRATION_MODE_LABELS[text as MigrationMode];
    const words = text.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
    return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatBackupType(value: unknown): string {
    const text = asText(value);
    if (text === 'full') return 'Full';
    if (text === 'partial') return 'Partial';
    return humanizeToken(text || 'backup');
}

export function formatOperation(operation: unknown, backupType?: unknown): string {
    const op = asText(operation);
    if (op === 'backup') return `${formatBackupType(backupType || 'manual')} backup`;
    if (op === 'restore') return 'Restore';
    if (op === 'migration') return 'Migration';
    if (op === 'dry_run') return 'Dry run';
    return humanizeToken(op || 'job');
}

/** The retry label the classic page uses, which says what retrying will actually do. */
export function retryLabel(job: DataManagementJob): string {
    if (asText(job.status) === 'running') return 'Resume';
    return asText(job.operation) === 'backup' ? 'Retry failures' : 'Retry';
}

export function formatNumber(value: unknown): string {
    const number = asCount(value, 0);
    return Number.isFinite(number) ? number.toLocaleString() : '0';
}

export function formatBytes(value: unknown): string {
    let size = asCount(value, 0);
    if (!Number.isFinite(size) || size <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit += 1;
    }
    return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatDateTime(value: unknown): string {
    const text = asText(value);
    if (!text) return '';
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? text : parsed.toLocaleString();
}

export function timestampAgeSeconds(value: unknown, now: number): number {
    const timestamp = Date.parse(asText(value));
    return Number.isFinite(timestamp)
        ? Math.max(0, Math.floor((now - timestamp) / 1000))
        : Number.POSITIVE_INFINITY;
}

export function formatAge(value: unknown, now: number): string {
    const age = timestampAgeSeconds(value, now);
    if (!Number.isFinite(age)) return '';
    if (age < 60) return `${age}s ago`;
    if (age < 3600) return `${Math.floor(age / 60)}m ago`;
    return `${Math.floor(age / 3600)}h ago`;
}

export interface Metric {
    label: string;
    value: string;
}

function record(value: unknown): JsonRecord {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : {};
}

/** Live migration telemetry, as the classic progress view reports it. */
export function migrationLiveMetrics(job: DataManagementJob, now: number): Metric[] {
    const state = record(job.migration_state);
    if (!Object.keys(state).length) return [];
    const totals = record(state.totals);
    const resources = Object.values(record(state.resources)).map(record);
    const active = resources.find((resource) => resource.status === 'in_progress') ?? {};
    const activeMetrics = Object.keys(record(active.progress)).length
        ? record(active.progress)
        : record(active.result);
    const capacity = record(state.capacity);
    const metrics: Metric[] = [
        { label: 'Processed', value: formatNumber(totals.processed_count) },
        { label: 'Transferred', value: formatBytes(totals.bytes) },
        {
            label: 'Copied / skipped',
            value: `${formatNumber(totals.copied_count)} / ${formatNumber(totals.skipped_count)}`,
        },
        { label: 'Failures', value: formatNumber(totals.failed_count) },
        { label: 'Collisions', value: formatNumber(totals.collision_count) },
    ];
    if (activeMetrics.observed_bytes !== undefined) {
        metrics.push({ label: 'Observed transferred', value: formatBytes(activeMetrics.observed_bytes) });
    }
    if (activeMetrics.items_per_second !== undefined) {
        metrics.push({ label: 'Items per second', value: formatNumber(activeMetrics.items_per_second) });
    }
    const rate = activeMetrics.observed_bytes_per_second ?? activeMetrics.bytes_per_second;
    if (rate !== undefined) metrics.push({ label: 'Transfer rate', value: `${formatBytes(rate)}/s` });
    if (activeMetrics.request_units_per_second !== undefined) {
        metrics.push({ label: 'RU per second', value: formatNumber(activeMetrics.request_units_per_second) });
    }
    if (capacity.status)
        metrics.push({ label: 'Destination capacity', value: humanizeToken(capacity.status) });
    const heartbeat = formatAge(job.last_heartbeat_at, now);
    const progressAt = job.last_progress_at || asText(state.last_progress_at);
    const progressAge = formatAge(progressAt, now);
    if (heartbeat) metrics.push({ label: 'Last heartbeat', value: heartbeat });
    if (progressAge) metrics.push({ label: 'Last progress', value: progressAge });
    if (heartbeat && !isTerminalJob(job.status)) {
        metrics.push({
            label: 'Liveness',
            value:
                timestampAgeSeconds(progressAt, now) <= 10
                    ? 'Running, progress active'
                    : 'Running, alive with no recent progress',
        });
    }
    return metrics;
}

/** Live backup telemetry, as the classic progress view reports it. */
export function backupLiveMetrics(job: DataManagementJob): Metric[] {
    const state = record(job.backup_state);
    if (!Object.keys(state).length) return [];
    const totals = record(state.totals);
    const telemetry = record(state.telemetry);
    const capacity = record(state.source_capacity);
    const metrics: Metric[] = [];
    if (!isTerminalJob(job.status)) {
        metrics.push({ label: 'Current container', value: asText(telemetry.current_container) || 'Waiting' });
    }
    metrics.push(
        {
            label: 'Checkpoint position',
            value: formatNumber(telemetry.checkpoint_position ?? totals.checkpoint_count),
        },
        { label: 'Processed', value: formatNumber(telemetry.records_processed ?? totals.processed_count) },
        { label: 'Transferred', value: formatBytes(telemetry.bytes ?? totals.bytes) },
        { label: 'Request units', value: formatNumber(telemetry.request_units ?? totals.request_units) },
        {
            label: 'Retries / throttles',
            value: `${formatNumber(telemetry.retries ?? totals.retry_attempt_count)} / ${formatNumber(telemetry.throttles ?? totals.throttle_count)}`,
        },
        {
            label: 'Skipped / failed',
            value: `${formatNumber(totals.skipped_count)} / ${formatNumber(totals.failed_count)}`,
        },
    );
    const elapsed = telemetry.elapsed_seconds ?? totals.elapsed_seconds;
    if (elapsed !== undefined) metrics.push({ label: 'Elapsed', value: `${formatNumber(elapsed)}s` });
    if (telemetry.records_per_second !== undefined) {
        metrics.push({ label: 'Records per second', value: formatNumber(telemetry.records_per_second) });
    }
    if (telemetry.request_units_per_second !== undefined) {
        metrics.push({ label: 'RU per second', value: formatNumber(telemetry.request_units_per_second) });
    }
    if (capacity.status) metrics.push({ label: 'Source capacity', value: humanizeToken(capacity.status) });
    if (capacity.restore_pending) metrics.push({ label: 'Capacity restore', value: 'Pending recovery' });
    return metrics;
}

/** Live restore telemetry, as the classic progress view reports it. */
export function restoreLiveMetrics(job: DataManagementJob, now: number): Metric[] {
    const state = record(job.restore_state);
    if (!Object.keys(state).length) return [];
    const totals = record(state.totals);
    const resources = Object.values(record(state.resources)).map(record);
    const active = record((resources.find((resource) => resource.status === 'in_progress') ?? {}).progress);
    const metrics: Metric[] = [
        { label: 'Processed', value: formatNumber(totals.processed_count) },
        { label: 'Copied', value: formatNumber(totals.copied_count) },
        {
            label: 'Created / updated',
            value: `${formatNumber(totals.created_count)} / ${formatNumber(totals.updated_count)}`,
        },
        {
            label: 'Skipped / failed',
            value: `${formatNumber(totals.skipped_count)} / ${formatNumber(totals.failed_count)}`,
        },
        { label: 'Collisions', value: formatNumber(totals.collision_count) },
        { label: 'Transferred', value: formatBytes(totals.bytes) },
    ];
    const target = asText(active.container_name) || asText(active.index_name);
    if (target) metrics.push({ label: 'Current target', value: target });
    const progressAge = formatAge(job.last_progress_at || asText(state.last_progress_at), now);
    if (progressAge) metrics.push({ label: 'Last progress', value: progressAge });
    return metrics;
}

export function liveMetrics(job: DataManagementJob, now: number): Metric[] {
    const operation = asText(job.operation);
    if (operation === 'migration') return migrationLiveMetrics(job, now);
    if (operation === 'backup') return backupLiveMetrics(job);
    if (operation === 'restore') return restoreLiveMetrics(job, now);
    return [];
}

/** Artifacts a job recorded: on its result, or failing that on an export timeline item. */
export function jobArtifacts(
    job: DataManagementJob,
    items: Array<{ details?: JsonRecord | null }>,
): JsonRecord[] {
    const fromResult = record(job.result).artifacts;
    if (Array.isArray(fromResult) && fromResult.length) return fromResult.map(record);
    const exportItem = items.find((item) => Array.isArray(record(item.details).artifacts));
    const fromItem = exportItem ? record(exportItem.details).artifacts : [];
    return Array.isArray(fromItem) ? fromItem.map(record) : [];
}

/** Job-level warnings plus each artifact's own, in that order. */
export function jobWarnings(job: DataManagementJob, artifacts: JsonRecord[]): string[] {
    const warnings = (Array.isArray(job.warnings) ? job.warnings : [])
        .map((warning) => asText(warning))
        .filter(Boolean);
    for (const artifact of artifacts) {
        if (artifact.warning) {
            warnings.push(
                `${asText(artifact.name) || asText(artifact.type) || 'Artifact'}: ${asText(artifact.warning)}`,
            );
        }
    }
    return warnings;
}

function isPresent(value: unknown): boolean {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string') return value.trim() !== '';
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value as object).length > 0;
    return true;
}

export function formatDetailValue(value: unknown): string {
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return formatNumber(value);
    if (value === null || value === undefined || value === '') return 'N/A';
    const text = String(value);
    return text.length > 96 ? `${text.slice(0, 60)}…${text.slice(-24)}` : text;
}

/** Flatten a structured details object into labelled chips, at most `limit` of them. */
export function flattenDetails(value: unknown, limit = 12, prefix = ''): Metric[] {
    const entries: Metric[] = [];
    for (const [key, detail] of Object.entries(record(value))) {
        if (!isPresent(detail)) continue;
        const label = prefix ? `${prefix} ${humanizeToken(key).toLowerCase()}` : humanizeToken(key);
        if (key === 'artifacts' && Array.isArray(detail)) {
            entries.push({ label, value: `${formatNumber(detail.length)} recorded` });
        } else if (Array.isArray(detail)) {
            const primitive = detail.every(
                (item) => item === null || ['string', 'number', 'boolean'].includes(typeof item),
            );
            entries.push({
                label,
                value: primitive
                    ? detail.slice(0, 4).map(formatDetailValue).join(', ')
                    : `${formatNumber(detail.length)} items`,
            });
        } else if (typeof detail === 'object') {
            entries.push(...flattenDetails(detail, limit, label));
        } else {
            entries.push({ label, value: formatDetailValue(detail) });
        }
        if (entries.length >= limit) break;
    }
    return entries.slice(0, limit);
}

// ---------------------------------------------------------------------------------------
// Cosmos editor
// ---------------------------------------------------------------------------------------

/**
 * Why a query cannot be run, or null when it can.
 *
 * The server enforces the same rules; checking here turns a refused request into guidance
 * beside the box.
 */
export function validateCosmosQuery(query: string): string | null {
    const text = query.trim();
    if (!text) return null;
    if (text.length > COSMOS_EDITOR_MAX_QUERY_LENGTH) {
        return `Queries are limited to ${COSMOS_EDITOR_MAX_QUERY_LENGTH.toLocaleString()} characters.`;
    }
    if (text.includes(';')) return 'Run one SELECT query at a time, without semicolons.';
    if (!/^SELECT\b/i.test(text)) return 'Queries must start with SELECT.';
    return null;
}

/** Read a dotted path such as `/user_id` or `/a/b` out of a document. */
export function readPartitionValue(document: unknown, partitionKeyPath: string | undefined): unknown {
    const segments = asText(partitionKeyPath).split('/').filter(Boolean);
    let node: unknown = document;
    for (const segment of segments) {
        if (!node || typeof node !== 'object' || Array.isArray(node)) return undefined;
        node = (node as JsonRecord)[segment];
    }
    return node;
}

export type CosmosEditCheck = { ok: true; document: JsonRecord } | { ok: false; error: string };

/**
 * Whether edited JSON can be saved over the opened document.
 *
 * The id and partition key cannot change, because the save replaces the document at the
 * address it was opened from; the server refuses both, and saying so before the typed
 * confirmation saves an administrator a round trip.
 */
export function checkCosmosEdit(
    text: string,
    original: { id: string; partitionKey: unknown; partitionKeyPath?: string },
): CosmosEditCheck {
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch (error) {
        return {
            ok: false,
            error: `This is not valid JSON: ${error instanceof Error ? error.message : 'parse error'}.`,
        };
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { ok: false, error: 'A Cosmos DB document must be a JSON object.' };
    }
    const document = parsed as JsonRecord;
    if (asText(document.id) !== original.id) {
        return { ok: false, error: 'The id cannot be changed here. Restore it to save.' };
    }
    const partition = readPartitionValue(document, original.partitionKeyPath);
    if (stableStringify(partition) !== stableStringify(original.partitionKey)) {
        return { ok: false, error: 'The partition key value cannot be changed here. Restore it to save.' };
    }
    return { ok: true, document };
}

/**
 * Pretty-print a document for editing.
 *
 * System fields (`_etag`, `_ts` and the rest) stay in view, as on the classic page. The
 * server ignores them when comparing and strips them before writing.
 */
export function formatCosmosDocument(document: JsonRecord): string {
    return JSON.stringify(document, null, 2);
}

export interface CosmosChangeSummary {
    changedPaths: string[];
    addedCount: number;
    removedCount: number;
    updatedCount: number;
}

/**
 * What an edit changes, shown before the typed confirmation.
 *
 * The same walk the server records after saving: system fields are skipped, and a key
 * added or removed counts once rather than once per nested value.
 */
export function summarizeCosmosChanges(original: unknown, updated: unknown): CosmosChangeSummary {
    const summary: CosmosChangeSummary = {
        changedPaths: [],
        addedCount: 0,
        removedCount: 0,
        updatedCount: 0,
    };
    const isObject = (value: unknown): value is JsonRecord =>
        Boolean(value) && typeof value === 'object' && !Array.isArray(value);

    const compare = (before: unknown, after: unknown, path: string) => {
        if (isObject(before) && isObject(after)) {
            const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)])).sort();
            for (const key of keys) {
                if (key.startsWith('_')) continue;
                const childPath = path ? `${path}.${key}` : key;
                if (!Object.prototype.hasOwnProperty.call(before, key)) {
                    summary.addedCount += 1;
                    summary.changedPaths.push(childPath);
                } else if (!Object.prototype.hasOwnProperty.call(after, key)) {
                    summary.removedCount += 1;
                    summary.changedPaths.push(childPath);
                } else {
                    compare(before[key], after[key], childPath);
                }
            }
            return;
        }
        if (stableStringify(before) !== stableStringify(after)) {
            summary.updatedCount += 1;
            summary.changedPaths.push(path);
        }
    };

    compare(original ?? {}, updated ?? {}, '');
    return summary;
}
