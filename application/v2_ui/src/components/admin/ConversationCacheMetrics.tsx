// ConversationCacheMetrics.tsx
// Conversation cache activity for the Conversation Cache card.
//
// Hits, misses, bypasses and invalidations over the last 15 minutes, which is what tells an
// administrator whether the cache is earning its keep or quietly bypassing itself -- for
// example because Redis is unavailable. The counters are kept in-process by each worker, so
// they describe this worker only; the note says so rather than letting them pass for a
// fleet-wide figure.
//
// Shares the app maintenance status with DAI Metrics and Cosmos Maintenance.

import { useEffect, useRef } from 'react';
import { Gauge } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';
import { formatPercent } from '../../lib/scaleFormat';
import {
    describeConversationCacheRuntime,
    formatCacheEvent,
    formatCountPair,
    formatOperationCounts,
    metricWindow,
} from '../../lib/scaleMaintenance';
import { useFirstVisible } from '../../lib/useFirstVisible';
import { useScaleStatusStore } from '../../stores/scaleStatusStore';
import {
    OpsHeading,
    OpsMessage,
    OpsNote,
    OpsPanel,
    OpsToolbar,
    Readout,
    ReadoutGrid,
    ReadoutSkeleton,
} from './OperationalReadouts';

export function ConversationCacheMetrics({ field }: { field: AdminField }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const seen = useFirstVisible(containerRef);
    const maintenance = useScaleStatusStore((state) => state.maintenance);
    const loadMaintenance = useScaleStatusStore((state) => state.loadMaintenance);

    useEffect(() => {
        if (seen) {
            void loadMaintenance();
        }
    }, [seen, loadMaintenance]);

    const cache = maintenance.data?.conversation_cache;
    const recent = metricWindow(cache?.metrics);

    return (
        <div ref={containerRef}>
            <OpsPanel testId="conversation-cache-metrics">
                <OpsHeading label={field.label} help={field.help} />
                <OpsToolbar
                    label="Conversation cache actions"
                    loadedAt={maintenance.loadedAt}
                    loading={maintenance.loading}
                    onRefresh={() => void loadMaintenance({ force: true })}
                    refreshLabel="Refresh metrics"
                />
                <OpsMessage message={maintenance.error ? { text: maintenance.error, tone: 'danger' } : null} />

                {!cache && maintenance.loading ? <ReadoutSkeleton rows={4} /> : null}

                {cache ? (
                    <>
                        <ReadoutGrid>
                            <Readout label="Runtime status" state={describeConversationCacheRuntime(cache.settings)} />
                            <Readout label="Hit rate" value={formatPercent(recent.hit_rate_percent)} />
                            <Readout label="Hits / misses" value={formatCountPair(recent.hit_count, recent.miss_count)} />
                            <Readout
                                label="Bypasses / errors"
                                value={formatCountPair(recent.bypass_count, recent.error_count)}
                            />
                            <Readout
                                label="Writes / invalidations"
                                value={formatCountPair(recent.write_count, recent.invalidation_count)}
                            />
                            <Readout label="Operation mix" value={formatOperationCounts(recent.operation_counts)} wide />
                            <Readout label="Last cache event" value={formatCacheEvent(cache.metrics?.last_event)} />
                            <Readout label="Last invalidation" value={formatCacheEvent(cache.metrics?.last_invalidation)} wide />
                        </ReadoutGrid>
                        <OpsNote icon={Gauge}>
                            Counted over the last 15 minutes in this app worker only. Application Insights keeps the
                            fleet-wide record of cache warnings and fallbacks.
                        </OpsNote>
                    </>
                ) : null}
            </OpsPanel>
        </div>
    );
}
