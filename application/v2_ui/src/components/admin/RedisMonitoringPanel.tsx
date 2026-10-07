// RedisMonitoringPanel.tsx
// Live Redis health and capacity for the Redis Metrics card.
//
// Reads `/api/admin/settings/redis-monitoring/status`, which pings the Redis connection the
// running application actually uses and reads its INFO metrics. It is fetched when the card
// first scrolls into view rather than with the page, refreshed on request, and refreshed
// again after a successful connection test, as the server-rendered page does.
//
// The readouts are grouped by the question they answer -- is it reachable, is it running
// out of room, is the cache earning its keep, what is in it -- rather than listed as the
// INFO command returns them. The Redis Explorer sits beneath them, closed until needed.

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../lib/apiClient';
import type { AdminField } from '../../lib/adminFields';
import {
    formatCount,
    formatMetric,
    formatPercent,
    formatTimestamp,
    formatTtl,
    humanizeStatus,
    type ToneText,
} from '../../lib/scaleFormat';
import {
    describeRedisConfiguration,
    describeRedisHealth,
    describeRedisPort,
    describeRedisRefresh,
    describeRedisRuntime,
    formatRedisMemoryUsage,
    formatRedisServiceType,
    type RedisMonitoringStatus,
} from '../../lib/scaleRedis';
import { useFirstVisible } from '../../lib/useFirstVisible';
import { useScaleStatusStore } from '../../stores/scaleStatusStore';
import {
    OpsEmptyState,
    OpsHeading,
    OpsMessage,
    OpsNote,
    OpsPanel,
    OpsToolbar,
    Readout,
    ReadoutGrid,
    ReadoutGroup,
    ReadoutSkeleton,
} from './OperationalReadouts';
import { RedisExplorer } from './RedisExplorer';

const STATUS_PATH = '/api/admin/settings/redis-monitoring/status';

export function RedisMonitoringPanel({ field, redisEnabled }: { field: AdminField; redisEnabled: boolean }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const seen = useFirstVisible(containerRef, redisEnabled);
    const refreshRevision = useScaleStatusStore((state) => state.redisRefreshRevision);

    const [status, setStatus] = useState<RedisMonitoringStatus | null>(null);
    const [loading, setLoading] = useState(false);
    const [loadedAt, setLoadedAt] = useState<number | null>(null);
    const [message, setMessage] = useState<ToneText | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const next = await api.get<RedisMonitoringStatus>(STATUS_PATH);
            setStatus(next);
            setLoadedAt(Date.now());
            // A healthy reading needs no sentence; the timestamp already says it worked.
            const outcome = describeRedisRefresh(next);
            setMessage(outcome.tone === 'warn' || outcome.tone === 'danger' ? outcome : null);
        } catch (error) {
            setMessage({
                text: error instanceof Error ? error.message : 'Failed to load Redis monitoring status.',
                tone: 'danger',
            });
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (seen && redisEnabled) {
            void load();
        }
    }, [seen, redisEnabled, load]);

    // A connection test that succeeded is a reason to look again, but only once there is a
    // reading on screen to update.
    const lastRevision = useRef(refreshRevision);
    useEffect(() => {
        if (refreshRevision !== lastRevision.current) {
            lastRevision.current = refreshRevision;
            if (loadedAt !== null) {
                void load();
            }
        }
    }, [refreshRevision, loadedAt, load]);

    const health = status?.health ?? {};
    const memory = status?.memory ?? {};
    const stats = status?.stats ?? {};
    const dai = status?.dai_cache ?? {};
    const lastError: ToneText | null = health.last_error ? { text: health.last_error, tone: 'danger' } : null;

    return (
        <div ref={containerRef}>
            <OpsPanel testId="redis-monitoring-panel">
                <OpsHeading label={field.label} help={field.help} />

                {!redisEnabled ? (
                    <OpsEmptyState title="Nothing to monitor yet">
                        Redis Cache is off for the running application. Metrics appear here once it is
                        enabled and saved, and every worker has restarted.
                    </OpsEmptyState>
                ) : (
                    <>
                        <OpsToolbar
                            label="Redis monitoring actions"
                            loadedAt={loadedAt}
                            loading={loading}
                            onRefresh={() => void load()}
                            refreshLabel="Refresh status"
                        />
                        <OpsMessage message={message} />

                        {!status && loading ? <ReadoutSkeleton rows={4} /> : null}

                        {status ? (
                            <>
                                <ReadoutGrid>
                                    <Readout label="Configuration" state={describeRedisConfiguration(status.configuration)} />
                                    <Readout label="Health" state={describeRedisHealth(health.status)} />
                                    <Readout
                                        label="App cache runtime"
                                        state={describeRedisRuntime(status.runtime?.app_cache_using_redis)}
                                    />
                                    <Readout
                                        label="Session runtime"
                                        state={describeRedisRuntime(status.runtime?.session_using_redis)}
                                    />
                                </ReadoutGrid>

                                <ReadoutGroup title="Connection">
                                    <ReadoutGrid>
                                        <Readout
                                            label="Redis service"
                                            value={formatRedisServiceType(status.configuration?.service_type)}
                                            detail={describeRedisPort(status.configuration)}
                                        />
                                        <Readout label="Ping latency" value={formatMetric(health.ping_latency_ms, 'ms')} />
                                        <Readout label="Redis version" value={status.server?.redis_version || 'Not available'} />
                                        <Readout
                                            label="Monitoring source"
                                            value={humanizeStatus(status.runtime?.monitoring_source)}
                                        />
                                        <Readout label="Last checked" value={formatTimestamp(status.checked_at)} wide />
                                    </ReadoutGrid>
                                    {lastError ? <OpsMessage message={lastError} /> : null}
                                </ReadoutGroup>

                                <ReadoutGroup title="Capacity">
                                    <ReadoutGrid>
                                        <Readout
                                            label="Memory usage"
                                            value={formatRedisMemoryUsage(memory)}
                                            detail={memory.maxmemory_policy ? `Policy: ${memory.maxmemory_policy}` : 'Policy: Not available'}
                                            wide
                                        />
                                        <Readout label="Fragmentation ratio" value={formatCount(memory.mem_fragmentation_ratio)} />
                                        <Readout label="Connected clients" value={formatCount(status.clients?.connected_clients)} />
                                        <Readout label="Rejected connections" value={formatCount(stats.rejected_connections)} />
                                    </ReadoutGrid>
                                </ReadoutGroup>

                                <ReadoutGroup title="Traffic">
                                    <ReadoutGrid>
                                        <Readout label="Operations per second" value={formatCount(stats.instantaneous_ops_per_sec)} />
                                        <Readout label="Keyspace hit rate" value={formatPercent(stats.keyspace_hit_rate_percent)} />
                                        <Readout label="Error replies" value={formatCount(stats.total_error_replies)} />
                                        <Readout
                                            label="Expired / evicted keys"
                                            value={`${formatCount(stats.expired_keys)} / ${formatCount(stats.evicted_keys)}`}
                                        />
                                    </ReadoutGrid>
                                </ReadoutGroup>

                                <ReadoutGroup title="Keys">
                                    <ReadoutGrid>
                                        <Readout label="Tracked keys" value={formatCount(status.keyspace?.total_keys)} />
                                        <Readout
                                            label="DAI version markers"
                                            value={formatCount(dai.version_marker_count)}
                                            detail={`${formatCount(dai.version_marker_no_expiry_count)} without an expiry`}
                                        />
                                        <Readout
                                            label="DAI cache payloads"
                                            value={formatCount(dai.payload_key_count)}
                                            detail={`Version TTL: ${formatTtl(dai.version_marker_ttl_seconds)}`}
                                        />
                                    </ReadoutGrid>
                                </ReadoutGroup>

                                <OpsNote>
                                    Azure Managed Redis runs the Redis Enterprise engine, which leaves out some INFO
                                    fields, so they read Not available. That is expected; Health and ping latency
                                    show whether the connection works.
                                </OpsNote>
                            </>
                        ) : null}

                        <ReadoutGroup title="Redis Explorer" defaultOpen={false}>
                            <RedisExplorer />
                        </ReadoutGroup>
                    </>
                )}
            </OpsPanel>
        </div>
    );
}
