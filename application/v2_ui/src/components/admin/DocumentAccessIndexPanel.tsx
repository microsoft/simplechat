// DocumentAccessIndexPanel.tsx
// Status of the document access index (DAI) for the DAI Metrics card.
//
// The index replaces expensive cross-partition document access queries and maintains
// itself, so this is mostly a readout: is the projection on, is backfill done, are reads
// served from it or falling back to the source, and is the Redis list cache hitting.
//
// The manual controls -- run one backfill batch, reset the checkpoint -- and the shadow
// validation figures appear only in diagnostics mode, as on the server-rendered page, which
// shows them only while `enable_dai_debug` is set in the settings document.
//
// While a batch is running the status is re-read every few seconds, so the card shows the
// batch finishing instead of a stale "Running".

import { useEffect, useRef, useState } from 'react';
import { Gauge, PlayCircle, RotateCcw } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import type { AdminField } from '../../lib/adminFields';
import {
    describeEnabled,
    describeMaintenanceStatus,
    formatCount,
    formatMetric,
    formatPercent,
    formatTimestamp,
    humanizeStatus,
    type ToneText,
} from '../../lib/scaleFormat';
import {
    DAI_RUNNING_POLL_MS,
    MAINTENANCE_RUN_PAYLOADS,
    backfillStatusFromRun,
    describeAlwaysOn,
    describeBackfillRun,
    describeDaiCache,
    formatCacheEvent,
    formatCountPair,
    formatLatencyWindow,
    formatMetricPair,
    formatReadSample,
    formatSavings,
    formatScopeList,
    formatShadowSamples,
    isBackfillRunning,
    metricWindow,
    type AppMaintenanceRunResult,
} from '../../lib/scaleMaintenance';
import { useFirstVisible } from '../../lib/useFirstVisible';
import { toast } from '../../stores/toastStore';
import { useScaleStatusStore } from '../../stores/scaleStatusStore';
import { ConfirmActionModal } from './ConfirmActionModal';
import {
    OpsButton,
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

const RUN_PATH = '/api/admin/settings/app-maintenance/run';

export function DocumentAccessIndexPanel({ field, diagnostics }: { field: AdminField; diagnostics: boolean }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const seen = useFirstVisible(containerRef);
    const maintenance = useScaleStatusStore((state) => state.maintenance);
    const loadMaintenance = useScaleStatusStore((state) => state.loadMaintenance);
    const mergeMaintenance = useScaleStatusStore((state) => state.mergeMaintenance);

    const [running, setRunning] = useState<'batch' | 'reset' | null>(null);
    const [confirmReset, setConfirmReset] = useState(false);
    const [message, setMessage] = useState<ToneText | null>(null);

    useEffect(() => {
        if (seen) {
            void loadMaintenance();
        }
    }, [seen, loadMaintenance]);

    const dai = maintenance.data?.document_access_index_backfill;
    const backfillRunning = isBackfillRunning(dai);

    useEffect(() => {
        if (!backfillRunning) {
            return;
        }
        const timer = window.setInterval(() => {
            void loadMaintenance({ force: true });
        }, DAI_RUNNING_POLL_MS);
        return () => window.clearInterval(timer);
    }, [backfillRunning, loadMaintenance]);

    const runBatch = async (reset: boolean) => {
        setRunning(reset ? 'reset' : 'batch');
        setMessage({
            text: reset
                ? 'Resetting the backfill checkpoint and running one batch…'
                : 'Running one document access backfill batch…',
            tone: 'info',
        });
        try {
            const result = await api.post<AppMaintenanceRunResult>(
                RUN_PATH,
                reset ? MAINTENANCE_RUN_PAYLOADS.resetBackfill : MAINTENANCE_RUN_PAYLOADS.backfillBatch,
            );
            const current = backfillStatusFromRun(result);
            if (current) {
                mergeMaintenance({ document_access_index_backfill: current });
            }
            const outcome = describeBackfillRun(current);
            setMessage(outcome);
            if (outcome.tone === 'warn') {
                toast.info(outcome.text);
            } else {
                toast.success(outcome.text);
            }
        } catch (error) {
            const payload = error instanceof ApiError ? (error.payload as AppMaintenanceRunResult | null) : null;
            const current = backfillStatusFromRun(payload);
            if (current) {
                mergeMaintenance({ document_access_index_backfill: current });
            }
            const text = error instanceof Error ? error.message : 'Document access index backfill batch failed.';
            setMessage({ text, tone: 'danger' });
            toast.error(text);
        } finally {
            setRunning(null);
            setConfirmReset(false);
        }
    };

    const settings = dai?.settings ?? {};
    const state = dai?.state ?? {};
    const maintenanceState = dai?.maintenance ?? {};
    const shadow = dai?.shadow_validation ?? {};
    const reads = metricWindow(dai?.read_metrics);
    const cache = metricWindow(dai?.cache_metrics);
    const rolling5m = metricWindow(shadow.rolling_metrics, '5m');
    const rolling15m = metricWindow(shadow.rolling_metrics, '15m');
    const controlsDisabled = settings.container_enabled === false;
    const loadError: ToneText | null = maintenance.error ? { text: maintenance.error, tone: 'danger' } : null;

    return (
        <div ref={containerRef}>
            <OpsPanel testId="document-access-index-panel">
                <OpsHeading label={field.label} help={field.help} />
                <OpsToolbar
                    label="Document access index actions"
                    loadedAt={maintenance.loadedAt}
                    loading={maintenance.loading}
                    onRefresh={() => void loadMaintenance({ force: true })}
                    refreshLabel="Refresh status"
                >
                    {diagnostics ? (
                        <>
                            <OpsButton
                                icon={PlayCircle}
                                tone="primary"
                                busy={running === 'batch'}
                                disabled={controlsDisabled || running !== null}
                                onClick={() => void runBatch(false)}
                            >
                                Run one backfill batch
                            </OpsButton>
                            <OpsButton
                                icon={RotateCcw}
                                tone="danger"
                                disabled={controlsDisabled || running !== null}
                                onClick={() => setConfirmReset(true)}
                            >
                                Reset checkpoint
                            </OpsButton>
                        </>
                    ) : null}
                </OpsToolbar>

                <OpsMessage message={message ?? loadError} />
                {diagnostics ? (
                    <OpsNote>
                        Diagnostics are showing because enable_dai_debug is set in the settings document.
                    </OpsNote>
                ) : null}

                {!dai && maintenance.loading ? <ReadoutSkeleton rows={8} /> : null}

                {dai ? (
                    <>
                        <ReadoutGroup title="Projection and maintenance">
                            <ReadoutGrid>
                                <Readout label="Container" state={describeAlwaysOn(settings.container_enabled)} />
                                <Readout label="Write-through" state={describeAlwaysOn(settings.write_through_enabled)} />
                                <Readout label="Read path" state={describeAlwaysOn(settings.reads_enabled)} />
                                <Readout label="Redis list cache" state={describeDaiCache(settings)} />
                                {diagnostics ? (
                                    <Readout
                                        label="Shadow validation"
                                        state={
                                            settings.shadow_validation_enabled
                                                ? { text: 'Enabled', tone: 'warn' }
                                                : { text: 'Disabled', tone: 'neutral' }
                                        }
                                    />
                                ) : null}
                                <Readout
                                    label="Automatic maintenance"
                                    state={describeEnabled(maintenanceState.auto_maintenance_enabled, 'Automatic', 'Disabled')}
                                />
                                <Readout
                                    label="Next maintenance action"
                                    value={humanizeStatus(maintenanceState.next_action || 'monitor')}
                                />
                                <Readout label="More work pending" value={maintenanceState.has_more_work ? 'Yes' : 'No'} />
                                <Readout
                                    label="Active loop interval"
                                    value={formatMetric(maintenanceState.active_interval_seconds, 'sec', 3)}
                                />
                            </ReadoutGrid>
                        </ReadoutGroup>

                        <ReadoutGroup title="Backfill progress">
                            <ReadoutGrid>
                                <Readout label="Backfill state" state={describeMaintenanceStatus(state.status || 'not_started')} />
                                <Readout label="Repair backlog" value={formatCount(dai.repair_required_count)} />
                                <Readout label="Current scope" value={state.current_source_scope || 'None'} />
                                <Readout label="Completed scopes" value={formatScopeList(state.completed_source_scopes)} />
                                <Readout label="Documents processed" value={formatCount(state.total_documents_processed ?? 0)} />
                                <Readout label="Documents failed" value={formatCount(state.total_documents_failed ?? 0)} />
                                <Readout label="Rows upserted" value={formatCount(state.total_rows_upserted ?? 0)} />
                                <Readout label="Rows deleted" value={formatCount(state.total_rows_deleted ?? 0)} />
                                <Readout
                                    label="Last batch completed"
                                    value={formatTimestamp(state.last_completed_at, 'Not completed yet')}
                                    wide
                                />
                                <Readout label="Last error" value={state.last_error || 'None'} wide />
                            </ReadoutGrid>
                        </ReadoutGroup>

                        <ReadoutGroup title="Reads, last 15 minutes">
                            <ReadoutGrid>
                                <Readout label="DAI read attempts" value={formatCount(reads.sample_count ?? 0)} />
                                <Readout label="Served from DAI" value={formatCount(reads.served_from_index_count ?? 0)} />
                                <Readout label="Source fallbacks" value={formatCount(reads.source_fallback_count ?? 0)} />
                                <Readout label="Fallback rate" value={formatPercent(reads.fallback_rate_percent)} />
                                <Readout label="DAI read RU" value={formatMetric(reads.request_charge, 'RU', 3)} />
                                <Readout label="Average / p95 latency" value={formatLatencyWindow(reads)} />
                                <Readout
                                    label="Last fallback reason"
                                    value={formatReadSample(dai.read_metrics?.last_fallback_sample)}
                                    wide
                                />
                                <Readout label="Last DAI read" value={formatReadSample(dai.read_metrics?.last_sample)} wide />
                            </ReadoutGrid>
                        </ReadoutGroup>

                        <ReadoutGroup title="Redis list cache, last 15 minutes">
                            <ReadoutGrid>
                                <Readout label="Hit rate" value={formatPercent(cache.hit_rate_percent)} />
                                <Readout label="Hits / misses" value={formatCountPair(cache.hit_count, cache.miss_count)} />
                                <Readout label="Bypasses / errors" value={formatCountPair(cache.bypass_count, cache.error_count)} />
                                <Readout label="Invalidations" value={formatCount(cache.invalidation_count ?? 0)} />
                                <Readout label="Last cache event" value={formatCacheEvent(dai.cache_metrics?.last_event)} wide />
                            </ReadoutGrid>
                        </ReadoutGroup>

                        {diagnostics ? (
                            <>
                                <ReadoutGroup title="Shadow validation">
                                    <ReadoutGrid>
                                        <Readout
                                            label="Last shadow result"
                                            state={describeMaintenanceStatus(shadow.status || 'not_run', 'Not run')}
                                        />
                                        <Readout
                                            label="Mismatches"
                                            value={`${formatCount(shadow.missing_count ?? 0)} missing / ${formatCount(shadow.extra_count ?? 0)} extra`}
                                        />
                                        <Readout
                                            label="Source / validation RU"
                                            value={formatMetricPair(shadow.source_query_ru, shadow.validation_index_ru, 'RU')}
                                        />
                                        <Readout label="Validation index RU" value={formatMetric(shadow.validation_index_ru, 'RU', 3)} />
                                        <Readout label="Candidate read RU" value={formatMetric(shadow.candidate_read_ru, 'RU', 3)} />
                                        <Readout
                                            label="Estimated Wave 5 savings"
                                            value={formatSavings(shadow.estimated_wave5_ru_savings, 'RU', 'less', 'more')}
                                        />
                                        <Readout
                                            label="Source / candidate latency"
                                            value={formatMetricPair(shadow.source_query_ms, shadow.candidate_read_ms, 'ms')}
                                        />
                                        <Readout
                                            label="Estimated Wave 5 latency"
                                            value={formatSavings(shadow.estimated_wave5_ms_savings, 'ms', 'faster', 'slower')}
                                        />
                                    </ReadoutGrid>
                                </ReadoutGroup>
                                <ReadoutGroup
                                    title="Rolling decision metrics"
                                    description="Shadow-validation samples aggregated over recent windows, to compare source container RU with candidate index RU."
                                >
                                    <ReadoutGrid>
                                        <Readout
                                            label="5m source / candidate RU"
                                            value={formatMetricPair(rolling5m.source_query_ru, rolling5m.candidate_read_ru, 'RU')}
                                        />
                                        <Readout
                                            label="5m estimated savings"
                                            value={formatSavings(rolling5m.estimated_wave5_ru_savings, 'RU', 'less', 'more')}
                                        />
                                        <Readout
                                            label="15m source / candidate RU"
                                            value={formatMetricPair(rolling15m.source_query_ru, rolling15m.candidate_read_ru, 'RU')}
                                        />
                                        <Readout
                                            label="15m estimated savings"
                                            value={formatSavings(rolling15m.estimated_wave5_ru_savings, 'RU', 'less', 'more')}
                                        />
                                        <Readout
                                            label="15m validation overhead"
                                            value={formatMetric(rolling15m.validation_index_ru, 'RU', 3)}
                                        />
                                        <Readout label="15m shadow samples" value={formatShadowSamples(rolling15m)} wide />
                                    </ReadoutGrid>
                                </ReadoutGroup>
                            </>
                        ) : null}

                        <OpsNote icon={Gauge}>
                            Read and cache figures are counted in this app worker only. Application Insights keeps the
                            fleet-wide record of fallback warnings and query failures.
                        </OpsNote>
                    </>
                ) : null}
            </OpsPanel>

            {confirmReset ? (
                <ConfirmActionModal
                    title="Reset document access backfill"
                    confirmLabel="Reset and run batch"
                    tone="danger"
                    busy={running === 'reset'}
                    onConfirm={() => void runBatch(true)}
                    onClose={() => setConfirmReset(false)}
                >
                    <p>
                        The next batch starts again from the first source scope, then one batch runs at the saved
                        size. The work is idempotent, but documents that already have projection rows may be
                        processed again.
                    </p>
                    <p className="text-text-3">
                        Source documents and projection rows are not deleted. Only backfill progress is reset.
                    </p>
                </ConfirmActionModal>
            ) : null}
        </div>
    );
}
