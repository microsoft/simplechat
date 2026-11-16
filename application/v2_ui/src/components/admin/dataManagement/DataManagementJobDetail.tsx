// DataManagementJobDetail.tsx
// Job detail is a standalone pane so the Jobs workbench and other Backup & Recovery cards can open the same recovery view without recreating the long-running job logic.

import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Download, Loader2, RotateCw, StopCircle } from 'lucide-react';
import {
    JOB_POLL_INTERVAL_MS,
    cancelJob,
    getJobDetail,
    getJobProgress,
    migrationManifestUrl,
    retryJob,
    type DataManagementJob,
    type JobDetail,
    type JobItem,
    type JsonRecord,
} from '../../../lib/dataManagement';
import {
    flattenDetails,
    formatBackupType,
    formatBytes,
    formatDateTime,
    formatNumber,
    formatOperation,
    humanizeToken,
    isActiveJob,
    liveMetrics,
    progressPercent,
    retryLabel,
    jobArtifacts,
    jobWarnings,
} from '../../../lib/dataManagementLogic';
import { currentEpoch, isCurrentEpoch, useDataManagementStore } from '../../../stores/dataManagementStore';
import { toast } from '../../../stores/toastStore';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { GlassButton } from '../../ui/primitives';
import { inputClass } from '../fields';
import { DmChip, DmEmpty, DmMetricGrid, DmNotice, DmStatusPill, useInterval, useNow } from './DmShared';

export interface DataManagementJobDetailProps {
    /** The job to show. A null value renders the operator-facing empty state. */
    jobId: string | null;
    /** Optional list row data, shown immediately while the server detail is loading. */
    initialJob?: DataManagementJob | null;
    /** Locks action buttons while the parent settings page is saving. */
    disabled?: boolean;
    /** Called after retry, cancellation, polling or a full reload returns a newer job. */
    onJobUpdated?: (job: DataManagementJob) => void;
}

type ActionKind = 'retry' | 'cancel' | null;

interface NoticeState {
    tone: 'danger' | 'info';
    message: string;
}

interface DetailMetric {
    label: string;
    value: ReactNode;
}

function asRecord(value: unknown): JsonRecord {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function asText(value: unknown): string {
    return value === null || value === undefined ? '' : String(value);
}

function asNumber(value: unknown): number {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
}

function isPresent(value: unknown): boolean {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string') return value.trim() !== '';
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') return Object.keys(value).length > 0;
    return true;
}

function metricValue(value: unknown): string {
    if (typeof value === 'number') return formatNumber(value);
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    const text = asText(value);
    return text || 'N/A';
}

function artifactTitle(artifact: JsonRecord): string {
    return (
        asText(artifact.name) ||
        asText(artifact.index_name) ||
        asText(artifact.container_name) ||
        'Unnamed artifact'
    );
}

function artifactSubtitle(artifact: JsonRecord): string {
    return (
        [artifact.type, artifact.category || artifact.index_name]
            .filter(isPresent)
            .map(humanizeToken)
            .join(' / ') || 'Artifact'
    );
}

function artifactTotals(artifacts: JsonRecord[]) {
    return artifacts.reduce<{ artifactCount: number; recordCount: number; blobCount: number; bytes: number }>(
        (totals, artifact) => ({
            artifactCount: totals.artifactCount + 1,
            recordCount:
                totals.recordCount +
                asNumber(artifact.record_count ?? artifact.item_count ?? artifact.copied_count),
            blobCount: totals.blobCount + asNumber(artifact.blob_count),
            bytes: totals.bytes + asNumber(artifact.bytes),
        }),
        { artifactCount: 0, recordCount: 0, blobCount: 0, bytes: 0 },
    );
}

function summaryMetrics(job: DataManagementJob, artifacts: JsonRecord[]): DetailMetric[] {
    const result = asRecord(job.result);
    const migrationState = asRecord(job.migration_state);
    const migrationTotals = asRecord(migrationState.totals);
    const totals = artifactTotals(artifacts);
    const metrics: DetailMetric[] = [
        { label: 'Status', value: <DmStatusPill status={job.status || 'unknown'} /> },
        { label: 'Progress', value: `${progressPercent(job.progress)}%` },
        { label: 'Operation', value: formatOperation(job.operation || 'job', job.backup_type || '') },
        { label: 'Backup type', value: job.backup_type ? formatBackupType(job.backup_type) : 'N/A' },
        { label: 'Requested by', value: job.requested_by_email || (job.scheduled ? 'Scheduled' : 'Unknown') },
        { label: 'Created', value: formatDateTime(job.created_at) || 'N/A' },
        { label: 'Started', value: formatDateTime(job.started_at) || 'N/A' },
        { label: 'Completed', value: formatDateTime(job.completed_at) || 'N/A' },
        { label: 'Artifacts', value: formatNumber(result.artifact_count ?? totals.artifactCount) },
    ];
    if (job.operation === 'migration') {
        metrics.push(
            { label: 'Migration id', value: asText(migrationState.migration_id) || job.id || 'N/A' },
            { label: 'Processed', value: formatNumber(migrationTotals.processed_count) },
            { label: 'Transferred', value: formatBytes(migrationTotals.bytes) },
            { label: 'Request units', value: formatNumber(migrationTotals.request_units) },
        );
    }
    return metrics;
}

function artifactCountMetrics(artifact: JsonRecord): DetailMetric[] {
    const metrics: DetailMetric[] = [
        { label: 'Copied', value: formatNumber(artifact.copied_count ?? artifact.item_count) },
        { label: 'Created', value: formatNumber(artifact.created_count) },
        { label: 'Updated', value: formatNumber(artifact.updated_count) },
        { label: 'Unchanged', value: formatNumber(artifact.unchanged_count) },
        { label: 'Skipped', value: formatNumber(artifact.skipped_count) },
        { label: 'Failed', value: formatNumber(artifact.failed_count) },
        { label: 'Collisions', value: formatNumber(artifact.collision_count) },
        { label: 'Blobs', value: formatNumber(artifact.blob_count) },
        { label: 'Size', value: formatBytes(artifact.bytes) },
    ];
    if (artifact.type === 'migration_reconciliation') {
        metrics.push(
            { label: 'Readiness', value: humanizeToken(artifact.readiness) || 'Unknown' },
            { label: 'Deleted', value: formatNumber(artifact.deleted_count) },
            { label: 'Delete candidates', value: formatNumber(artifact.delete_candidate_count) },
        );
    }
    if (artifact.items_per_second !== undefined || artifact.bytes_per_second !== undefined) {
        metrics.push(
            { label: 'Items / second', value: formatNumber(artifact.items_per_second) },
            { label: 'Transfer rate', value: `${formatBytes(artifact.bytes_per_second)}/s` },
        );
    }
    return metrics;
}

function artifactNotes(
    artifact: JsonRecord,
): Array<{ label: string; value: unknown; tone?: 'ok' | 'warn' | 'neutral' }> {
    const notes: Array<{ label: string; value: unknown; tone?: 'ok' | 'warn' | 'neutral' }> = [
        { label: 'Container', value: artifact.container_name },
        { label: 'Partition key', value: artifact.partition_key_path },
        { label: 'Index', value: artifact.index_name },
        { label: 'Partial since', value: artifact.partial_since_epoch },
        { label: 'Filter', value: artifact.partial_filter },
        { label: 'Request units', value: artifact.request_units },
        { label: 'RU per second', value: artifact.request_units_per_second },
        { label: 'Workers', value: artifact.parallel_operations },
        { label: 'Retries', value: artifact.retry_count },
        { label: 'Retry delays', value: artifact.retry_attempt_count },
        { label: 'Prior failures', value: artifact.prior_failed_count },
        { label: 'Checkpoints', value: artifact.checkpoint_count },
        {
            label: 'Readiness',
            value: artifact.readiness,
            tone: artifact.readiness === 'ready' ? 'ok' : 'warn',
        },
        { label: 'Deletion', value: artifact.deletion_status },
        { label: 'Remaining owned extras', value: artifact.remaining_destination_only_owned_count },
        { label: 'Unowned extras', value: artifact.destination_only_unowned_count },
        { label: 'Unresolved scope', value: artifact.unresolved_scope_count },
        { label: 'Stale', value: artifact.stale_count },
        {
            label: 'Deletion blockers',
            value: Array.isArray(artifact.deletion_blockers)
                ? artifact.deletion_blockers.join('; ')
                : artifact.deletion_blockers,
            tone: 'warn',
        },
        { label: 'Prior migration skips', value: artifact.destination_provenance_skip_count },
        { label: 'Missing blobs', value: artifact.missing_count },
        { label: 'No source blob', value: artifact.not_applicable_count },
        { label: 'Collisions', value: artifact.collision_count },
        { label: 'Warning', value: artifact.warning, tone: 'warn' },
    ];
    return notes.filter((note) => isPresent(note.value));
}

function DetailChips({
    details,
    empty = 'No structured details recorded.',
}: {
    details: unknown;
    empty?: string;
}) {
    const entries = flattenDetails(details);
    if (!entries.length) {
        return <p className="text-xs text-text-3">{empty}</p>;
    }
    return (
        <div className="flex flex-wrap gap-1.5">
            {entries.map((entry) => (
                <DmChip key={`${entry.label}-${entry.value}`}>
                    {entry.label}: {entry.value}
                </DmChip>
            ))}
        </div>
    );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
    return (
        <section className="min-w-0 rounded-xl border border-edge bg-surface-1 p-3">
            <h4 className="text-sm font-semibold text-text-1">{title}</h4>
            <div className="mt-3 min-w-0">{children}</div>
        </section>
    );
}

function ProgressPanel({ job }: { job: DataManagementJob }) {
    const progress = job.progress ?? {};
    const percent = progressPercent(progress);
    const completed = asNumber(progress.completed_steps);
    const total = asNumber(progress.total_steps);
    const migrationActive = job.operation === 'migration' && isActiveJob(job.status);
    const displayedStage = migrationActive ? Math.min(total || 1, completed + 1) : completed;
    const stepText =
        job.operation === 'migration'
            ? total > 0
                ? `Stage ${formatNumber(displayedStage)} of ${formatNumber(total)}`
                : 'Waiting for stage details'
            : total > 0
              ? `${formatNumber(completed)} of ${formatNumber(total)} steps complete`
              : 'Waiting for step details';
    const message = job.last_message || job.last_error || 'No job message has been recorded yet.';
    return (
        <Section title={humanizeToken(progress.current_step) || 'Job progress'}>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-text-3">{stepText}</p>
                <p className="text-xs font-medium text-text-2">
                    {migrationActive ? 'Active stage' : `${percent}%`}
                </p>
            </div>
            <div
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={migrationActive ? undefined : percent}
                aria-valuetext={
                    migrationActive
                        ? 'Migration stage is active; measured throughput is shown below.'
                        : undefined
                }
                className="mt-2 h-3 overflow-hidden rounded-full bg-surface-sunken"
            >
                <div
                    className={clsx(
                        'h-full rounded-full transition-[width] duration-300',
                        migrationActive
                            ? 'w-full animate-pulse bg-accent'
                            : job.status === 'failed' || job.status === 'canceled'
                              ? 'bg-danger'
                              : 'bg-accent',
                    )}
                    style={migrationActive ? undefined : { width: `${percent}%` }}
                />
            </div>
            <p
                className={clsx(
                    'mt-2 text-xs leading-relaxed',
                    job.last_error ? 'text-danger' : 'text-text-3',
                )}
            >
                {message}
            </p>
        </Section>
    );
}

function LiveMetricsPanel({ job }: { job: DataManagementJob }) {
    const now = useNow(1000, isActiveJob(job.status));
    const metrics = liveMetrics(job, now);
    if (!metrics.length) return null;
    return <DmMetricGrid label="Live job metrics" items={metrics} />;
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
    if (!warnings.length) {
        return <p className="text-sm text-text-3">No warnings recorded for this job.</p>;
    }
    return (
        <ul className="space-y-2">
            {warnings.map((warning, index) => (
                <li
                    key={`${warning}-${index}`}
                    className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-xs leading-relaxed text-warn"
                >
                    {warning}
                </li>
            ))}
        </ul>
    );
}

function ArtifactsPanel({ artifacts }: { artifacts: JsonRecord[] }) {
    if (!artifacts.length) {
        return <p className="text-sm text-text-3">No backup artifacts recorded for this job.</p>;
    }
    return (
        <div className="space-y-3">
            {artifacts.map((artifact, index) => (
                <article
                    key={`${artifactTitle(artifact)}-${index}`}
                    className="min-w-0 rounded-xl border border-edge bg-surface-solid p-3"
                >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                            <h5 className="text-sm font-semibold break-words text-text-1">
                                {artifactTitle(artifact)}
                            </h5>
                            <p className="mt-0.5 text-xs text-text-3">{artifactSubtitle(artifact)}</p>
                        </div>
                        <div className="flex flex-wrap gap-1">
                            <DmChip tone={artifact.status === 'warning' ? 'warn' : 'neutral'}>
                                {humanizeToken(artifact.status) || 'Recorded'}
                            </DmChip>
                            {artifact.encrypted ? <DmChip tone="ok">Encrypted</DmChip> : null}
                        </div>
                    </div>
                    <DmMetricGrid
                        className="mt-3"
                        label="Artifact counts"
                        items={artifactCountMetrics(artifact)}
                    />
                    <div className="mt-3">
                        <p className="text-xs text-text-3">Location</p>
                        <p className="mt-0.5 text-sm font-medium break-all text-text-1">
                            {asText(artifact.path || artifact.prefix) || 'Not recorded'}
                        </p>
                    </div>
                    {artifactNotes(artifact).length ? (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                            {artifactNotes(artifact).map((note) => (
                                <DmChip key={note.label} tone={note.tone ?? 'neutral'}>
                                    {note.label}: {metricValue(note.value)}
                                </DmChip>
                            ))}
                        </div>
                    ) : null}
                    {isPresent(artifact.preview_actual_divergence) ? (
                        <div className="mt-3">
                            <p className="mb-1 text-xs text-text-3">Preview versus actual</p>
                            <DetailChips details={artifact.preview_actual_divergence} />
                        </div>
                    ) : null}
                </article>
            ))}
        </div>
    );
}

function ManifestPanel({ job, artifacts }: { job: DataManagementJob; artifacts: JsonRecord[] }) {
    const result = asRecord(job.result);
    const totals = artifactTotals(artifacts);
    return (
        <div className="space-y-3">
            <div>
                <p className="text-xs text-text-3">Manifest path</p>
                <p className="mt-0.5 text-sm font-medium break-all text-text-1">
                    {asText(result.manifest_path) || 'Not recorded'}
                </p>
            </div>
            <div>
                <p className="text-xs text-text-3">Storage prefix</p>
                <p className="mt-0.5 text-sm font-medium break-all text-text-1">
                    {asText(result.base_prefix) || 'Not recorded'}
                </p>
            </div>
            <DmMetricGrid
                label="Manifest totals"
                items={[
                    {
                        label: 'Artifacts',
                        value: formatNumber(result.artifact_count ?? totals.artifactCount),
                    },
                    { label: 'Records', value: formatNumber(totals.recordCount) },
                    { label: 'Blobs', value: formatNumber(totals.blobCount) },
                    { label: 'Total size', value: formatBytes(totals.bytes) },
                ]}
            />
        </div>
    );
}

function TimelinePanel({ items }: { items: JobItem[] }) {
    if (!items.length) {
        return <p className="text-sm text-text-3">No timeline events recorded for this job.</p>;
    }
    return (
        <ol className="space-y-2">
            {items.map((item, index) => (
                <li
                    key={item.id || item.job_id || `${item.step_name}-${index}`}
                    className="rounded-xl border border-edge bg-surface-solid p-3"
                >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                            <p className="text-sm font-semibold text-text-1">
                                {humanizeToken(item.step_name || 'event')}
                            </p>
                            <p className="mt-0.5 text-xs text-text-3">
                                {formatDateTime(item.created_at) || 'Time not recorded'}
                            </p>
                        </div>
                        <DmStatusPill status={item.status || 'unknown'} />
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-text-2">
                        {item.message || 'No message recorded.'}
                    </p>
                    <div className="mt-2">
                        <DetailChips details={item.details} />
                    </div>
                </li>
            ))}
        </ol>
    );
}

export function DataManagementJobDetail({
    jobId,
    initialJob,
    disabled = false,
    onJobUpdated,
}: DataManagementJobDetailProps) {
    const cancelReasonId = useId();
    const [detail, setDetail] = useState<JobDetail | null>(() =>
        initialJob ? { job: initialJob, items: [] } : null,
    );
    const [loading, setLoading] = useState(false);
    const [notice, setNotice] = useState<NoticeState | null>(null);
    const [liveMessage, setLiveMessage] = useState('');
    const [livePaused, setLivePaused] = useState(false);
    const [actionBusy, setActionBusy] = useState<ActionKind>(null);
    const [cancelOpen, setCancelOpen] = useState(false);
    const [cancelReason, setCancelReason] = useState('');
    const controllerRef = useRef<AbortController | null>(null);
    const initialJobRef = useRef<DataManagementJob | null | undefined>(initialJob);
    // Held in a ref so a parent that passes a new callback each render does not make the
    // loaders change identity, which would re-run the load effect on every render.
    const onJobUpdatedRef = useRef(onJobUpdated);
    const jobIdRef = useRef<string | null | undefined>(jobId);
    const requestRef = useRef(0);
    const pollInFlightRef = useRef(false);
    const pollGenerationRef = useRef(0);
    const pollControllerRef = useRef<AbortController | null>(null);
    const mountedRef = useRef(true);

    useEffect(() => {
        initialJobRef.current = initialJob;
    }, [initialJob]);

    useEffect(() => {
        onJobUpdatedRef.current = onJobUpdated;
    }, [onJobUpdated]);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            controllerRef.current?.abort();
        };
    }, []);

    const loadDetail = useCallback(
        async (id: string, options: { silent?: boolean; terminal?: boolean } = {}) => {
            controllerRef.current?.abort();
            const controller = new AbortController();
            controllerRef.current = controller;
            const request = requestRef.current + 1;
            requestRef.current = request;
            const epoch = currentEpoch();
            if (!options.silent) {
                setLoading(true);
            }
            setNotice(null);
            try {
                const next = await getJobDetail(id, controller.signal);
                if (
                    controller.signal.aborted ||
                    requestRef.current !== request ||
                    !isCurrentEpoch(epoch) ||
                    !mountedRef.current ||
                    jobIdRef.current !== id
                )
                    return;
                setDetail(next);
                setLivePaused(false);
                setLiveMessage(
                    isActiveJob(next.job.status)
                        ? `Live updates on · last refreshed ${new Date().toLocaleTimeString()}`
                        : `Job is ${humanizeToken(next.job.status || 'unknown')} · last refreshed ${new Date().toLocaleTimeString()}`,
                );
                onJobUpdatedRef.current?.(next.job);
                if (options.terminal) {
                    const store = useDataManagementStore.getState();
                    store.notifyJobsChanged();
                    store.notifyBackupsChanged();
                }
            } catch (error) {
                if (controller.signal.aborted || requestRef.current !== request || !mountedRef.current)
                    return;
                const message =
                    error instanceof Error && error.message
                        ? error.message
                        : 'Job details could not be loaded.';
                setNotice({ tone: 'danger', message });
            } finally {
                if (!controller.signal.aborted && requestRef.current === request && mountedRef.current) {
                    setLoading(false);
                }
            }
        },
        [],
    );

    const stopPolling = () => {
        pollGenerationRef.current += 1;
        pollControllerRef.current?.abort();
        pollControllerRef.current = null;
        pollInFlightRef.current = false;
    };

    useEffect(() => {
        jobIdRef.current = jobId;
        stopPolling();
        setLivePaused(false);
        setCancelOpen(false);
        setCancelReason('');
        setNotice(null);
        if (!jobId) {
            controllerRef.current?.abort();
            setDetail(null);
            setLiveMessage('');
            setLoading(false);
            return;
        }
        const previewJob = initialJobRef.current;
        // Never leave the previous job on screen under the new selection.
        setDetail(previewJob && previewJob.id === jobId ? { job: previewJob, items: [] } : null);
        setLiveMessage('');
        void loadDetail(jobId);
    }, [jobId, loadDetail]);

    useEffect(() => () => stopPolling(), []);

    const poll = useCallback(async () => {
        const id = jobIdRef.current;
        if (!id || detail?.job.id !== id || pollInFlightRef.current) return;
        pollInFlightRef.current = true;
        const generation = pollGenerationRef.current + 1;
        pollGenerationRef.current = generation;
        const controller = new AbortController();
        pollControllerRef.current = controller;
        const epoch = currentEpoch();
        // A response is applied only while the same job is still selected.
        const stillCurrent = () =>
            mountedRef.current &&
            pollGenerationRef.current === generation &&
            jobIdRef.current === id &&
            isCurrentEpoch(epoch);
        try {
            const job = await getJobProgress(id, controller.signal);
            if (!stillCurrent() || (job.id && job.id !== id)) return;
            setDetail((current) =>
                current && current.job.id === id
                    ? {
                          ...current,
                          job: { ...current.job, ...job, progress: job.progress ?? current.job.progress },
                      }
                    : current,
            );
            setLiveMessage(`Live updates on · last refreshed ${new Date().toLocaleTimeString()}`);
            onJobUpdatedRef.current?.({ ...job, id });
            if (!isActiveJob(job.status)) {
                await loadDetail(id, { silent: true, terminal: true });
            }
        } catch {
            if (stillCurrent()) {
                setLivePaused(true);
                setLiveMessage('Live updates paused');
            }
        } finally {
            if (pollGenerationRef.current === generation) {
                pollInFlightRef.current = false;
                pollControllerRef.current = null;
            }
        }
    }, [detail?.job.id, loadDetail]);

    const job = detail?.job ?? null;
    const active = job ? isActiveJob(job.status) : false;
    useInterval(() => void poll(), job && active && !livePaused ? JOB_POLL_INTERVAL_MS : null);

    const artifacts = useMemo(
        () => (job ? jobArtifacts(job, detail?.items ?? []) : []),
        [detail?.items, job],
    );
    const warnings = useMemo(() => (job ? jobWarnings(job, artifacts) : []), [artifacts, job]);
    const locked = disabled || loading || actionBusy !== null;

    const runRetry = async () => {
        if (!job?.id || locked) return;
        const epoch = currentEpoch();
        setActionBusy('retry');
        setNotice(null);
        try {
            const retried = await useDataManagementStore.getState().trackRequest(retryJob(job.id));
            if (!isCurrentEpoch(epoch) || !mountedRef.current) return;
            toast.success(
                `${formatOperation(retried.operation || job.operation || 'job', retried.backup_type || job.backup_type || '')} retry queued from durable checkpoints.`,
            );
            useDataManagementStore.getState().notifyJobsChanged();
            onJobUpdatedRef.current?.(retried);
            if (jobIdRef.current === job.id) await loadDetail(job.id, { silent: true });
        } catch (error) {
            if (!isCurrentEpoch(epoch) || !mountedRef.current) return;
            const message =
                error instanceof Error && error.message
                    ? error.message
                    : 'Data Management job retry could not be queued.';
            setNotice({ tone: 'danger', message });
            toast.error(message);
        } finally {
            if (mountedRef.current) setActionBusy(null);
        }
    };

    const runCancel = async () => {
        if (!job?.id || locked) return;
        const epoch = currentEpoch();
        setActionBusy('cancel');
        setNotice(null);
        try {
            const cancelled = await useDataManagementStore
                .getState()
                .trackRequest(cancelJob(job.id, cancelReason.trim()));
            if (!isCurrentEpoch(epoch) || !mountedRef.current) return;
            const canceledImmediately = cancelled.status === 'canceled';
            toast.success(
                canceledImmediately
                    ? 'Job canceled before execution started.'
                    : 'Job cancellation requested.',
            );
            useDataManagementStore.getState().notifyJobsChanged();
            setCancelOpen(false);
            setCancelReason('');
            onJobUpdatedRef.current?.(cancelled);
            if (jobIdRef.current === job.id) await loadDetail(job.id, { silent: true });
        } catch (error) {
            if (!isCurrentEpoch(epoch) || !mountedRef.current) return;
            const message =
                error instanceof Error && error.message
                    ? error.message
                    : 'Data Management job cancellation could not be requested.';
            setNotice({ tone: 'danger', message });
            toast.error(message);
        } finally {
            if (mountedRef.current) setActionBusy(null);
        }
    };

    if (!jobId) {
        return (
            <DmEmpty title="Select a job">
                Choose a job to inspect progress, artifacts, warnings, and recovery actions.
            </DmEmpty>
        );
    }

    if (!job && loading) {
        return <div className="p-4 text-sm text-text-3">Loading job details…</div>;
    }

    if (!job) {
        return (
            <div className="p-4">
                {notice ? (
                    <DmNotice tone="danger" role="alert">
                        {notice.message}
                    </DmNotice>
                ) : null}
            </div>
        );
    }

    return (
        <div className="flex h-full min-w-0 flex-col gap-4 p-3 @xl:p-4" data-testid="dm-job-detail">
            <header className="min-w-0 border-b border-edge pb-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                        <h3 className="text-base font-semibold text-text-1">
                            {formatOperation(job.operation || 'job', job.backup_type || '')}
                        </h3>
                        <p className="mt-1 text-xs break-all text-text-3">Job ID: {job.id}</p>
                        <p aria-live="polite" className="mt-1 text-xs text-text-3">
                            {liveMessage}
                        </p>
                    </div>
                    <DmStatusPill status={job.status || 'unknown'} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2" aria-label="Job actions">
                    {job.operation === 'migration' ? (
                        <>
                            <a
                                href={migrationManifestUrl(job.id)}
                                download
                                className="inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-sm font-medium glass-flat text-text-1 hover:bg-surface-2"
                            >
                                <Download size={14} aria-hidden="true" />
                                Download manifest
                            </a>
                            <a
                                href={migrationManifestUrl(job.id, true)}
                                download
                                className="inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-sm font-medium glass-flat text-text-1 hover:bg-surface-2"
                            >
                                <Download size={14} aria-hidden="true" />
                                Download failures
                            </a>
                        </>
                    ) : null}
                    {job.can_retry ? (
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            disabled={locked}
                            onClick={() => void runRetry()}
                        >
                            {actionBusy === 'retry' ? (
                                <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                            ) : (
                                <RotateCw size={14} aria-hidden="true" />
                            )}
                            {retryLabel(job)}
                        </GlassButton>
                    ) : null}
                    {job.can_cancel ? (
                        <GlassButton
                            type="button"
                            variant="danger"
                            size="sm"
                            disabled={locked}
                            onClick={() => setCancelOpen(true)}
                        >
                            <StopCircle size={14} aria-hidden="true" />
                            Cancel
                        </GlassButton>
                    ) : null}
                    {livePaused && active ? (
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            onClick={() => {
                                setLivePaused(false);
                                void poll();
                            }}
                        >
                            Resume live updates
                        </GlassButton>
                    ) : null}
                </div>
                {notice ? (
                    <DmNotice className="mt-3" tone={notice.tone} role="alert">
                        {notice.message}
                    </DmNotice>
                ) : null}
            </header>

            <DmMetricGrid label="Job summary" items={summaryMetrics(job, artifacts)} />
            <ProgressPanel job={job} />
            <LiveMetricsPanel job={job} />

            <div className="grid min-w-0 gap-4 @4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <Section title="Timeline">
                    <TimelinePanel items={detail?.items ?? []} />
                </Section>
                <Section title="Artifacts">
                    <ArtifactsPanel artifacts={artifacts} />
                </Section>
                <Section title="Storage and manifest">
                    <ManifestPanel job={job} artifacts={artifacts} />
                </Section>
                <Section title="Warnings">
                    <WarningsPanel warnings={warnings} />
                </Section>
            </div>

            {cancelOpen ? (
                <ConfirmDialog
                    title="Request job cancellation"
                    description="Cancellation is cooperative. The worker stops at its next durable checkpoint, and verified checkpoints stay available so the job can be retried or resumed later."
                    confirmLabel="Request cancellation"
                    cancelLabel="Keep running"
                    tone="danger"
                    busy={actionBusy === 'cancel'}
                    onClose={() => {
                        if (actionBusy !== 'cancel') setCancelOpen(false);
                    }}
                    onConfirm={() => void runCancel()}
                >
                    <div className="space-y-3">
                        <p className="text-xs leading-relaxed text-text-2">
                            Request cancellation for{' '}
                            {formatOperation(job.operation || 'job', job.backup_type || '')}{' '}
                            <span className="break-all font-semibold text-text-1">{job.id}</span>?
                        </p>
                        <div>
                            <label htmlFor={cancelReasonId} className="text-xs font-medium text-text-2">
                                Reason (optional)
                            </label>
                            <textarea
                                id={cancelReasonId}
                                className={clsx(inputClass, 'mt-1 min-h-20 resize-y')}
                                value={cancelReason}
                                disabled={actionBusy === 'cancel'}
                                onChange={(event) => setCancelReason(event.target.value)}
                            />
                        </div>
                    </div>
                </ConfirmDialog>
            ) : null}
        </div>
    );
}
