// scaleMaintenance.ts
// Shapes and wording for the three cards fed by the app maintenance status.
//
// The document access index (DAI), the conversation cache and Cosmos maintenance all
// report through one endpoint, `/api/admin/settings/app-maintenance/status`, exactly as on
// the server-rendered page, which refreshes the three together. Manual runs go through
// `/api/admin/settings/app-maintenance/run` and return per-step results; the helpers here
// pick the step a card cares about out of that list.

import {
    NOT_AVAILABLE,
    formatCount,
    formatMetric,
    humanizeStatus,
    maintenanceStatusTone,
    type ToneText,
} from './scaleFormat';

/** One rolling window of counters, as the server aggregates them. */
export interface MetricWindow {
    sample_count?: number;
    served_from_index_count?: number;
    source_fallback_count?: number;
    fallback_rate_percent?: number | null;
    request_charge?: number | null;
    elapsed_ms_avg?: number | null;
    elapsed_ms_p95?: number | null;
    hit_rate_percent?: number | null;
    hit_count?: number;
    miss_count?: number;
    bypass_count?: number;
    error_count?: number;
    write_count?: number;
    invalidation_count?: number;
    operation_counts?: Record<string, number>;
    source_query_ru?: number | null;
    candidate_read_ru?: number | null;
    validation_index_ru?: number | null;
    estimated_wave5_ru_savings?: number | null;
    comparable_sample_count?: number;
    matched_count?: number;
    mismatch_count?: number;
}

/** The most recent event of a kind, kept for "Last fallback" and similar readouts. */
export interface MetricSample {
    status?: string;
    operation?: string;
    source_scope?: string;
    event_type?: string;
    reason?: string;
}

export interface DocumentAccessIndexStatus {
    state?: {
        status?: string;
        current_source_scope?: string | null;
        completed_source_scopes?: string[];
        total_documents_processed?: number;
        total_documents_failed?: number;
        total_rows_upserted?: number;
        total_rows_deleted?: number;
        last_completed_at?: string | null;
        last_error?: string | null;
    };
    settings?: {
        container_enabled?: boolean;
        write_through_enabled?: boolean;
        reads_enabled?: boolean;
        cache_enabled?: boolean;
        cache_ttl_seconds?: number;
        shadow_validation_enabled?: boolean;
    };
    shadow_validation?: {
        status?: string;
        missing_count?: number;
        extra_count?: number;
        source_query_ru?: number | null;
        validation_index_ru?: number | null;
        candidate_read_ru?: number | null;
        estimated_wave5_ru_savings?: number | null;
        source_query_ms?: number | null;
        candidate_read_ms?: number | null;
        estimated_wave5_ms_savings?: number | null;
        rolling_metrics?: { windows?: Record<string, MetricWindow> };
    };
    maintenance?: {
        auto_maintenance_enabled?: boolean;
        next_action?: string;
        has_more_work?: boolean;
        active_interval_seconds?: number | null;
    };
    read_metrics?: {
        windows?: Record<string, MetricWindow>;
        last_sample?: MetricSample | null;
        last_fallback_sample?: MetricSample | null;
    };
    cache_metrics?: {
        windows?: Record<string, MetricWindow>;
        last_event?: MetricSample | null;
    };
    repair_required_count?: number | null;
}

export interface ConversationCacheStatus {
    settings?: { enabled?: boolean; ttl_seconds?: number };
    metrics?: {
        windows?: Record<string, MetricWindow>;
        last_event?: MetricSample | null;
        last_invalidation?: MetricSample | null;
    };
}

export interface CosmosIndexingPolicyStatus {
    mode?: string;
    container_count?: number;
    containers_missing_expected_indexes?: number;
    updated_container_count?: number;
    failed_container_count?: number;
    evaluated_at?: string | null;
}

export interface StaleCacheCleanupCategory {
    category?: string;
    candidate_count?: number;
    deleted_count?: number;
    failed_count?: number;
}

export interface StaleCacheCleanupStatus {
    status?: string;
    mode?: string;
    candidate_count?: number;
    deleted_count?: number;
    failed_count?: number;
    has_more_candidates?: boolean;
    categories?: StaleCacheCleanupCategory[];
    evaluated_at?: string | null;
}

export interface AppMaintenanceStatus {
    success?: boolean;
    document_access_index_backfill?: DocumentAccessIndexStatus;
    conversation_cache?: ConversationCacheStatus;
    cosmos_indexing_policies?: CosmosIndexingPolicyStatus;
    stale_cache_cleanup?: StaleCacheCleanupStatus;
}

export interface AppMaintenanceRunStep {
    name?: string;
    results?: Record<string, unknown> | null;
}

export interface AppMaintenanceRunResult {
    success?: boolean;
    error?: string;
    steps?: AppMaintenanceRunStep[];
}

/** Request bodies for the manual runs each card offers, matching the classic page. */
export const MAINTENANCE_RUN_PAYLOADS = {
    staleCleanupDryRun: {
        apply_cosmos_indexing_policies: false,
        run_document_access_index_backfill: false,
        run_stale_cache_cleanup: true,
        apply_stale_cache_cleanup: false,
    },
    staleCleanupApply: {
        apply_cosmos_indexing_policies: false,
        run_document_access_index_backfill: false,
        run_stale_cache_cleanup: true,
        apply_stale_cache_cleanup: true,
    },
    applyIndexes: {
        apply_cosmos_indexing_policies: true,
        run_document_access_index_backfill: false,
        run_stale_cache_cleanup: false,
    },
    backfillBatch: {
        apply_cosmos_indexing_policies: false,
        run_document_access_index_backfill: true,
        reset_document_access_index_backfill: false,
    },
    resetBackfill: {
        apply_cosmos_indexing_policies: false,
        run_document_access_index_backfill: true,
        reset_document_access_index_backfill: true,
    },
} as const;

/** How often the DAI card re-reads status while a backfill batch is running. */
export const DAI_RUNNING_POLL_MS = 7500;

export function metricWindow(
    metrics: { windows?: Record<string, MetricWindow> } | null | undefined,
    key = '15m',
): MetricWindow {
    return metrics?.windows?.[key] ?? {};
}

/** Two counts side by side, such as hits and misses. */
export function formatCountPair(first: unknown, second: unknown): string {
    return `${formatCount(first ?? 0)} / ${formatCount(second ?? 0)}`;
}

export function formatOperationCounts(counts: Record<string, number> | null | undefined): string {
    const entries = Object.entries(counts ?? {})
        .filter(([, count]) => Number(count || 0) > 0)
        .sort(([left], [right]) => left.localeCompare(right));
    if (!entries.length) {
        return 'No samples';
    }
    return entries
        .map(([operation, count]) => `${humanizeStatus(operation)}: ${formatCount(count)}`)
        .join(', ');
}

/** "Served From Index (List Documents / personal)". */
export function formatReadSample(sample: MetricSample | null | undefined): string {
    if (!sample) {
        return 'No samples';
    }
    const scope = sample.source_scope ? ` / ${sample.source_scope}` : '';
    return `${humanizeStatus(sample.status || 'unknown')} (${humanizeStatus(sample.operation || 'read')}${scope})`;
}

export function formatCacheEvent(sample: MetricSample | null | undefined): string {
    if (!sample) {
        return 'No cache events';
    }
    const reason = sample.reason ? ` / ${humanizeStatus(sample.reason)}` : '';
    return `${humanizeStatus(sample.event_type || 'unknown')} (${humanizeStatus(sample.operation || 'cache')}${reason})`;
}

/** Average and p95 latency, or "Not available" when neither was recorded. */
export function formatLatencyWindow(window: MetricWindow): string {
    const average = formatMetric(window.elapsed_ms_avg, 'ms', 3);
    const p95 = formatMetric(window.elapsed_ms_p95, 'ms', 3);
    if (average === NOT_AVAILABLE && p95 === NOT_AVAILABLE) {
        return NOT_AVAILABLE;
    }
    return `${average} / ${p95}`;
}

/** A source value beside its index counterpart, only when both exist. */
export function formatMetricPair(source: unknown, candidate: unknown, unit: string): string {
    const first = formatMetric(source, unit, 3);
    const second = formatMetric(candidate, unit, 3);
    if (first === NOT_AVAILABLE || second === NOT_AVAILABLE) {
        return NOT_AVAILABLE;
    }
    return `${first} / ${second}`;
}

/** A signed difference stated as "12 RU less" or "3 ms slower". */
export function formatSavings(value: unknown, unit: string, positive: string, negative: string): string {
    const numeric = typeof value === 'number' ? value : Number(value);
    if (value === null || value === undefined || value === '' || !Number.isFinite(numeric)) {
        return NOT_AVAILABLE;
    }
    if (Math.abs(numeric) < 0.001) {
        return `0 ${unit} difference`;
    }
    return `${formatMetric(Math.abs(numeric), unit, 3)} ${numeric > 0 ? positive : negative}`;
}

export function formatShadowSamples(window: MetricWindow): string {
    if (!window || Number(window.sample_count || 0) === 0) {
        return 'No samples';
    }
    return (
        `${formatCount(window.sample_count || 0)} samples (` +
        `${formatCount(window.comparable_sample_count || 0)} comparable, ` +
        `${formatCount(window.matched_count || 0)} matched, ` +
        `${formatCount(window.mismatch_count || 0)} mismatch, ` +
        `${formatCount(window.error_count || 0)} error)`
    );
}

export function formatScopeList(items: string[] | null | undefined): string {
    const values = (items ?? []).map((item) => String(item || '').trim()).filter(Boolean);
    return values.length ? values.join(', ') : 'None';
}

/** Whether the conversation cache is reading and writing, and for how long it keeps entries. */
export function describeConversationCacheRuntime(
    settings: ConversationCacheStatus['settings'],
): ToneText {
    if (settings?.enabled === false) {
        return { text: 'Disabled', tone: 'neutral' };
    }
    const ttl = Number(settings?.ttl_seconds ?? 120);
    return ttl > 0
        ? { text: `Enabled / ${formatMetric(ttl, 'sec', 3)}`, tone: 'ok' }
        : { text: 'Enabled / Writes disabled', tone: 'ok' };
}

/** The Redis list cache as the DAI status reports it. */
export function describeDaiCache(settings: DocumentAccessIndexStatus['settings']): ToneText {
    return settings?.cache_enabled
        ? { text: `Enabled / ${formatMetric(settings.cache_ttl_seconds, 'sec', 3)}`, tone: 'ok' }
        : { text: 'Disabled', tone: 'neutral' };
}

/** A flag the server forces on, which the classic page shows as a locked checkbox. */
export function describeAlwaysOn(value: unknown): ToneText {
    return value === false
        ? { text: 'Disabled', tone: 'warn' }
        : { text: 'Always on', tone: 'ok' };
}

/** Index policy health, derived the way the classic page derives it. */
export function indexingPolicyStatus(policy: CosmosIndexingPolicyStatus | null | undefined): string {
    if (!policy || !Object.keys(policy).length) {
        return 'not_loaded';
    }
    if (Number(policy.failed_container_count || 0) > 0) {
        return 'failed';
    }
    if (Number(policy.containers_missing_expected_indexes || 0) > 0) {
        return 'missing_expected_indexes';
    }
    return 'aligned';
}

/** The results a manual run reported for one of its steps. */
export function findRunStep(
    result: AppMaintenanceRunResult | null | undefined,
    name: string,
): Record<string, unknown> | null {
    const step = (result?.steps ?? []).find((candidate) => candidate?.name === name);
    return step?.results && typeof step.results === 'object' ? step.results : null;
}

/** The DAI status a backfill run returned, which it nests under `current_status`. */
export function backfillStatusFromRun(
    result: AppMaintenanceRunResult | null | undefined,
): DocumentAccessIndexStatus | null {
    const results = findRunStep(result, 'document_access_index_backfill');
    const current = results?.current_status;
    return current && typeof current === 'object' ? (current as DocumentAccessIndexStatus) : null;
}

export function isBackfillRunning(status: DocumentAccessIndexStatus | null | undefined): boolean {
    return String(status?.state?.status || '').trim().toLowerCase() === 'running';
}

/** What to say after a manual backfill batch, by the state it left behind. */
export function describeBackfillRun(status: DocumentAccessIndexStatus | null | undefined): ToneText {
    const state = String(status?.state?.status || 'completed').trim().toLowerCase();
    if (state === 'running') {
        return {
            text: 'The backfill batch is still running. Status refreshes automatically.',
            tone: 'info',
        };
    }
    if (state === 'in_progress') {
        return {
            text: 'The batch finished and more documents remain. Run another batch, or let maintenance continue on its schedule.',
            tone: 'info',
        };
    }
    const tone = maintenanceStatusTone(state);
    if (tone === 'danger' || tone === 'warn') {
        return {
            text: 'The batch finished with errors. Review the repair backlog and the last error.',
            tone: 'warn',
        };
    }
    return { text: 'Document access index backfill batch completed.', tone: 'ok' };
}

/** What to say after a stale cleanup run, dry or real. */
export function describeCleanupRun(cleanup: StaleCacheCleanupStatus | null, applied: boolean): ToneText {
    const candidates = formatCount(cleanup?.candidate_count ?? 0);
    const deleted = formatCount(cleanup?.deleted_count ?? 0);
    const text = applied
        ? `Stale cache cleanup deleted ${deleted} document(s) from ${candidates} candidate(s).`
        : `Stale cache cleanup dry run found ${candidates} candidate document(s).`;
    return { text, tone: cleanup?.has_more_candidates ? 'warn' : 'ok' };
}

/** What to say after applying missing indexes. */
export function describeIndexApply(policy: CosmosIndexingPolicyStatus | null): ToneText {
    const updated = Number(policy?.updated_container_count || 0);
    if (updated > 0) {
        return {
            text: `Index updates were submitted for ${formatCount(updated)} container(s). Cosmos may keep transforming indexes for a while; refresh later to follow it.`,
            tone: 'ok',
        };
    }
    return {
        text: `Indexing policies are already aligned. Missing expected indexes: ${formatCount(policy?.containers_missing_expected_indexes ?? 0)}.`,
        tone: 'ok',
    };
}
