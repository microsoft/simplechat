// scaleRedis.ts
// Shapes and wording for the Redis Metrics card and the Redis Explorer.
//
// Both read the existing admin APIs (`/api/admin/settings/redis-monitoring/status` and
// `/api/admin/settings/redis-explorer/*`) that the server-rendered page uses, so the types
// describe what those return. Azure Managed Redis runs the Redis Enterprise engine, which
// omits several INFO fields; every reader therefore tolerates a missing value and says
// "Not available" rather than inventing one.

import {
    NOT_AVAILABLE,
    formatMetric,
    formatPercent,
    humanizeStatus,
    type ReadoutTone,
    type ToneText,
} from './scaleFormat';

export interface RedisMonitoringStatus {
    checked_at?: string | null;
    configuration?: {
        enabled?: boolean;
        configured?: boolean;
        auth_type?: string;
        service_type?: string | null;
        service_type_source?: string | null;
        port?: number | null;
    };
    runtime?: {
        app_cache_using_redis?: boolean;
        session_using_redis?: boolean;
        monitoring_source?: string;
        client_available?: boolean;
    };
    health?: {
        status?: string;
        ping_success?: boolean;
        ping_latency_ms?: number | null;
        last_error?: string | null;
    };
    memory?: {
        used_memory?: number | null;
        used_memory_human?: string | null;
        maxmemory?: number | null;
        maxmemory_human?: string | null;
        maxmemory_policy?: string | null;
        usage_percent?: number | null;
        mem_fragmentation_ratio?: number | null;
    };
    clients?: { connected_clients?: number | null };
    stats?: {
        instantaneous_ops_per_sec?: number | null;
        keyspace_hit_rate_percent?: number | null;
        expired_keys?: number | null;
        evicted_keys?: number | null;
        rejected_connections?: number | null;
        total_error_replies?: number | null;
    };
    keyspace?: { total_keys?: number | null };
    server?: { redis_version?: string | null };
    dai_cache?: {
        version_marker_count?: number | null;
        version_marker_no_expiry_count?: number | null;
        payload_key_count?: number | null;
        version_marker_ttl_seconds?: number | null;
    };
}

/** What SimpleChat recognised a Redis key to be. */
export interface RedisKeyResolution {
    kind?: string;
    label?: string;
    resolved?: boolean;
    resolution_status?: string;
    entity_type?: string;
    entity_name?: string;
    entity_id?: string;
    entity_status?: string;
    row_count?: number | null;
    scope_key?: string;
    cache_hash?: string;
    scope_hash?: string;
    note?: string;
}

export interface RedisExplorerKey {
    key: string;
    type?: string;
    ttl_seconds?: number | null;
    memory_usage_bytes?: number | null;
    preview_restricted?: boolean;
    resolution?: RedisKeyResolution | null;
}

export interface RedisExplorerKeysResponse {
    success?: boolean;
    status?: string;
    keys?: RedisExplorerKey[];
    next_cursor?: string;
    has_more?: boolean;
    error?: string;
    last_error?: string | null;
}

export interface RedisExplorerValueResponse {
    success?: boolean;
    status?: string;
    key?: string;
    type?: string;
    ttl_seconds?: number | null;
    memory_usage_bytes?: number | null;
    preview_restricted?: boolean;
    redacted?: boolean;
    truncated?: boolean;
    preview?: string;
    error?: string;
    last_error?: string | null;
    resolution?: RedisKeyResolution | null;
}

/** Fields an explorer failure may explain itself in, after `error`. */
export type RedisExplorerDetailField = 'last_error' | 'preview';

/**
 * The sentence to show for a failed explorer request, read in the classic page's order.
 *
 * `error` comes first. Without it, the key page explains an unreachable Redis in
 * `last_error`, and a preview explains a key that no longer exists in `preview`, sent with a
 * 404. Anything else gets the caller's fallback rather than a bare status code.
 */
export function readRedisExplorerError(
    payload: unknown,
    detailFields: readonly RedisExplorerDetailField[],
    fallback: string,
): string {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
        const record = payload as Record<string, unknown>;
        for (const field of ['error', ...detailFields]) {
            const value = record[field];
            if (typeof value === 'string' && value.trim()) {
                return value;
            }
        }
    }
    return fallback;
}

export const REDIS_EXPLORER_PAGE_SIZES = [10, 25, 50, 100] as const;

/** Health codes reported by `functions_redis_monitoring.py`. */
export function redisHealthTone(value: unknown): ReadoutTone {
    const status = String(value ?? '').trim().toLowerCase();
    if (status === 'healthy' || status === 'active') {
        return 'ok';
    }
    if (['degraded', 'not_configured', 'unavailable'].includes(status)) {
        return 'warn';
    }
    if (status === 'error') {
        return 'danger';
    }
    return 'neutral';
}

export function describeRedisHealth(value: unknown): ToneText {
    return { text: humanizeStatus(value), tone: redisHealthTone(value) };
}

/** Whether Redis is on and has a host, which is what the classic Configuration badge says. */
export function describeRedisConfiguration(
    configuration: RedisMonitoringStatus['configuration'],
): ToneText {
    if (configuration?.enabled && configuration?.configured) {
        return { text: 'Enabled', tone: 'ok' };
    }
    if (configuration?.enabled) {
        return { text: 'Needs host', tone: 'warn' };
    }
    return { text: 'Disabled', tone: 'neutral' };
}

/** Whether a runtime path (app cache or sessions) is using Redis right now. */
export function describeRedisRuntime(active: unknown): ToneText {
    return active ? { text: 'Active', tone: 'ok' } : { text: 'Inactive', tone: 'neutral' };
}

export function formatRedisServiceType(value: unknown): string {
    const service = String(value ?? '').trim();
    if (service === 'azure_managed_redis') {
        return 'Azure Managed Redis';
    }
    if (service === 'azure_cache_for_redis') {
        return 'Azure Cache for Redis';
    }
    return NOT_AVAILABLE;
}

/** The port in use and whether an administrator chose it or it was derived. */
export function describeRedisPort(configuration: RedisMonitoringStatus['configuration']): string {
    if (!configuration?.port) {
        return `Port: ${NOT_AVAILABLE}`;
    }
    const source = configuration.service_type_source === 'setting' ? 'set by admin' : 'detected';
    return `Port ${configuration.port} (${source})`;
}

/** Used memory against the limit, as "12 MB / 1 GB (1.2%)". */
export function formatRedisMemoryUsage(memory: RedisMonitoringStatus['memory']): string {
    const used = memory?.used_memory_human || formatMetric(memory?.used_memory, 'bytes');
    const max = memory?.maxmemory_human || formatMetric(memory?.maxmemory, 'bytes');
    const percent = formatPercent(memory?.usage_percent);

    if (used === NOT_AVAILABLE) {
        return NOT_AVAILABLE;
    }
    if (max === NOT_AVAILABLE || Number(memory?.maxmemory || 0) === 0) {
        return `${used} / no maxmemory limit`;
    }
    if (percent === NOT_AVAILABLE) {
        return `${used} / ${max}`;
    }
    return `${used} / ${max} (${percent})`;
}

/** The line shown after a refresh, matching the classic page's message. */
export function describeRedisRefresh(status: RedisMonitoringStatus): ToneText {
    const health = status.health ?? {};
    if (health.status === 'healthy') {
        return { text: 'Redis monitoring status loaded.', tone: 'ok' };
    }
    if (health.last_error) {
        return { text: health.last_error, tone: health.status === 'error' ? 'danger' : 'warn' };
    }
    return { text: 'Redis monitoring status loaded.', tone: 'info' };
}

/** One line naming what a key belongs to, for the key list. */
export function describeResolutionLabel(resolution: RedisKeyResolution | null | undefined): string {
    if (!resolution) {
        return '';
    }
    if (resolution.resolved && resolution.entity_type) {
        const entity = resolution.entity_name || resolution.entity_id || 'Unknown';
        return `${resolution.label || 'SimpleChat entity'}: ${humanizeStatus(resolution.entity_type)} - ${entity}`;
    }
    return resolution.label || '';
}

/** The resolved entity's details, for the preview's resolution card. */
export function describeResolutionEntity(resolution: RedisKeyResolution | null | undefined): string {
    if (!resolution) {
        return 'Not resolved';
    }
    if (!resolution.resolved) {
        return humanizeStatus(resolution.resolution_status || 'unresolved');
    }
    const parts: string[] = [];
    if (resolution.entity_type) {
        parts.push(`Entity: ${humanizeStatus(resolution.entity_type)}`);
    }
    if (resolution.entity_name) {
        parts.push(`Name: ${resolution.entity_name}`);
    }
    if (resolution.entity_status) {
        parts.push(`Status: ${humanizeStatus(resolution.entity_status)}`);
    }
    if (typeof resolution.row_count === 'number' && Number.isFinite(resolution.row_count)) {
        parts.push(`DAI rows: ${resolution.row_count.toLocaleString()}`);
    }
    return parts.join(' | ') || 'Resolved';
}

/** How much of a value the preview withholds. */
export function describePreviewSanitization(value: RedisExplorerValueResponse): string {
    if (value.preview_restricted) {
        return 'Restricted';
    }
    return value.redacted ? 'Redacted' : 'Sanitized';
}
