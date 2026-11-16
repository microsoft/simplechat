// DataManagementBackupRuns.tsx
// Backup: queue a backup now and tune backup performance.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Archive, ArchiveRestore, ExternalLink } from 'lucide-react';
import { ApiError } from '../../../lib/apiClient';
import { queueJob, type BackupRow, type BackupType } from '../../../lib/dataManagement';
import {
    asFlag,
    blobBufferEstimateMib,
    DM_SECTION_IDS,
    formatBackupType,
    formatDateTime,
    isBackupStorageConfigured,
    readDmValues,
} from '../../../lib/dataManagementLogic';
import {
    currentEpoch,
    isCurrentEpoch,
    useDataManagementStore,
    useDmDirtyCount,
    useDmValues,
} from '../../../stores/dataManagementStore';
import { toast } from '../../../stores/toastStore';
import { GlassButton, Skeleton } from '../../ui/primitives';
import { DmField, useDmValue } from './DmField';
import type { DmCardProps } from './DmShared';
import { DmDisclosure, DmIntro, DmNotice, DmStatusPill, useVisibleOnce } from './DmShared';
import { DataManagementGuideDialog } from './DataManagementGuides';
import { useBackupSummary } from './useBackupSummary';
import { useSaveFirst } from './useSaveFirst';

interface QueueResult {
    jobId: string;
    backupType: BackupType;
}

function backupLine(label: string, backup: BackupRow | null | undefined) {
    if (!backup) {
        return (
            <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2">
                <dt className="text-xs text-text-3">{label}</dt>
                <dd className="mt-1 text-sm text-text-2">None yet</dd>
            </div>
        );
    }
    const completedAt = backup.completed_at || backup.created_at;
    return (
        <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2">
            <dt className="text-xs text-text-3">{label}</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-2">
                <DmStatusPill status={backup.status ?? 'completed'} />
                <span className="min-w-0 break-words">completed {formatDateTime(completedAt)}</span>
            </dd>
        </div>
    );
}

export function DataManagementBackupRuns({ help, onNavigate, disabled }: DmCardProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const visible = useVisibleOnce(rootRef);
    const values = useDmValues();
    const dirtyCount = useDmDirtyCount();
    const sourceRuEnabled = asFlag(useDmValue('backup_temporary_source_ru_enabled'));
    const storageConfigured = isBackupStorageConfigured(values);
    const { summary, loading, failure } = useBackupSummary(visible);
    const { ensure, dialog } = useSaveFirst();
    const [queueing, setQueueing] = useState<BackupType | null>(null);
    const [result, setResult] = useState<QueueResult | null>(null);
    const [actionError, setActionError] = useState('');
    const [guideOpen, setGuideOpen] = useState(false);

    useEffect(() => {
        void useDataManagementStore.getState().ensureLoaded();
    }, []);

    const bufferEstimate = useMemo(() => blobBufferEstimateMib(values), [values]);
    const queueDisabled = Boolean(disabled || queueing || !storageConfigured);

    const queueBackup = async (backupType: BackupType) => {
        setActionError('');
        setResult(null);
        if (!(await ensure('queue-backup'))) return;

        const state = useDataManagementStore.getState();
        const freshValues = readDmValues(state.settings, state.draft);
        const options = {
            include_cosmos: Boolean(freshValues.include_cosmos),
            include_ai_search: Boolean(freshValues.include_ai_search),
            include_source_blobs: Boolean(freshValues.include_source_blobs),
        };

        const token = currentEpoch();
        setQueueing(backupType);
        try {
            const job = await state.trackRequest(queueJob('backup', backupType, options));
            if (!isCurrentEpoch(token)) return;
            toast.success(`${formatBackupType(backupType)} backup queued.`);
            useDataManagementStore.getState().notifyJobsChanged();
            useDataManagementStore.getState().notifyBackupsChanged();
            setResult({ jobId: job.id, backupType });
        } catch (error: unknown) {
            if (!isCurrentEpoch(token)) return;
            if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                setActionError(error.message || 'Backup could not be queued.');
                return;
            }
            setActionError(
                'The request may not have reached the server. Check Job history before queueing another backup.',
            );
            useDataManagementStore.getState().notifyJobsChanged();
        } finally {
            if (isCurrentEpoch(token)) setQueueing(null);
        }
    };

    return (
        <div ref={rootRef} data-testid="dm-backup-runs" className="@container space-y-4">
            <DmIntro>
                {help ??
                    'Queue an immediate backup with the saved Backup & Recovery settings, then tune source Cosmos and source file transfer performance.'}
            </DmIntro>

            {!storageConfigured ? (
                <DmNotice
                    tone="warning"
                    title="Backup storage is not configured"
                    action={
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            onClick={() => onNavigate(DM_SECTION_IDS.storage)}
                        >
                            Open storage
                        </GlassButton>
                    }
                >
                    Configure a dedicated backup storage account before queueing full or partial backups.
                </DmNotice>
            ) : null}

            <section
                className="rounded-xl border border-edge-strong bg-surface-solid p-3"
                aria-labelledby="dm-run-backup-now"
            >
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 basis-64">
                        <h3 id="dm-run-backup-now" className="text-sm font-semibold text-text-1">
                            Run a backup now
                        </h3>
                        <p className="mt-0.5 max-w-[68ch] text-xs leading-relaxed text-text-3">
                            Queue an immediate full or partial backup. Jobs use Cosmos-backed leases so
                            scaled-out App Service instances do not run the same backup twice.
                        </p>
                        {dirtyCount > 0 ? (
                            <p className="mt-2 text-xs text-text-2">
                                Pending Backup & Recovery settings are saved first.
                            </p>
                        ) : null}
                    </div>
                    <div className="flex min-w-0 flex-wrap gap-2">
                        <GlassButton
                            type="button"
                            variant="primary"
                            disabled={queueDisabled}
                            onClick={() => void queueBackup('full')}
                        >
                            <Archive size={15} aria-hidden="true" />
                            {dirtyCount > 0 ? 'Save and queue full backup' : 'Queue full backup'}
                        </GlassButton>
                        <GlassButton
                            type="button"
                            variant="subtle"
                            disabled={queueDisabled}
                            onClick={() => void queueBackup('partial')}
                        >
                            <ArchiveRestore size={15} aria-hidden="true" />
                            {dirtyCount > 0 ? 'Save and queue partial backup' : 'Queue partial backup'}
                        </GlassButton>
                    </div>
                </div>

                {queueing ? (
                    <p role="status" aria-live="polite" className="mt-3 text-xs text-text-3">
                        Queueing {formatBackupType(queueing).toLowerCase()} backup…
                    </p>
                ) : null}

                {actionError ? (
                    <DmNotice tone="danger" title="Backup was not queued" role="alert" className="mt-3">
                        {actionError}
                    </DmNotice>
                ) : null}

                {result ? (
                    <DmNotice
                        tone="success"
                        title={`${formatBackupType(result.backupType)} backup queued`}
                        role="status"
                        className="mt-3"
                        action={
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                disabled={!result.jobId}
                                onClick={() => {
                                    useDataManagementStore.getState().focusJob(result.jobId);
                                    onNavigate(DM_SECTION_IDS.jobs);
                                }}
                            >
                                <ExternalLink size={13} aria-hidden="true" />
                                View in Job history
                            </GlassButton>
                        }
                    >
                        Follow its progress in Job history.
                    </DmNotice>
                ) : null}
            </section>

            <section aria-labelledby="dm-latest-backups">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h3 id="dm-latest-backups" className="text-sm font-semibold text-text-1">
                        Latest results
                    </h3>
                    {loading ? (
                        <span role="status" aria-live="polite" className="text-xs text-text-3">
                            Loading latest backups…
                        </span>
                    ) : null}
                </div>
                {loading && !summary ? (
                    <div className="grid gap-2 @xl:grid-cols-2">
                        <Skeleton className="h-16 w-full" />
                        <Skeleton className="h-16 w-full" />
                    </div>
                ) : (
                    <dl className="grid gap-2 @xl:grid-cols-2">
                        {backupLine('Latest full backup', summary?.latest_full)}
                        {backupLine('Latest partial backup', summary?.latest_partial)}
                    </dl>
                )}
                {failure ? (
                    <DmNotice
                        tone={failure.maintenanceRequired ? 'warning' : 'danger'}
                        title="Latest backups unavailable"
                        role="alert"
                        className="mt-3"
                    >
                        {failure.message}
                    </DmNotice>
                ) : null}
            </section>

            <DmDisclosure
                title="Cosmos backup performance"
                summary="Concurrency, retries, and source RU Boost"
            >
                <div className="space-y-3 pt-3">
                    <p className="text-xs leading-relaxed text-text-3">
                        Backups stream checkpointed Cosmos batches and commit verified work. Higher
                        concurrency can finish sooner and can also increase source Cosmos pressure.
                    </p>
                    <div className="grid gap-3 @2xl:grid-cols-2">
                        <DmField dmKey="backup_max_parallel_operations" disabled={disabled} />
                        <DmField dmKey="backup_retry_count" disabled={disabled} />
                        <DmField dmKey="backup_capacity_failure_policy" disabled={disabled} />
                    </div>
                    <DmField
                        dmKey="backup_temporary_source_ru_enabled"
                        disabled={disabled}
                        emphasis="primary"
                        after={
                            <div className="mt-2">
                                <GlassButton
                                    type="button"
                                    variant="subtle"
                                    size="sm"
                                    onClick={() => setGuideOpen(true)}
                                >
                                    About RU Boost
                                </GlassButton>
                            </div>
                        }
                    />
                    {sourceRuEnabled ? (
                        <DmField
                            dmKey="backup_temporary_source_ru"
                            disabled={disabled}
                            emphasis="dependent"
                        />
                    ) : null}
                </div>
            </DmDisclosure>

            <DmDisclosure
                title="Source file transfer performance"
                summary={`${bufferEstimate} MiB peak file buffer`}
            >
                <div className="space-y-3 pt-3">
                    <p className="text-xs leading-relaxed text-text-3">
                        Source files stream through bounded chunks and durable per-file checkpoints.
                    </p>
                    <div className="grid gap-3 @2xl:grid-cols-3">
                        <DmField dmKey="backup_blob_max_parallel_operations" disabled={disabled} />
                        <DmField dmKey="backup_blob_chunk_size_mib" disabled={disabled} />
                        <DmField dmKey="backup_blob_retry_count" disabled={disabled} />
                    </div>
                    <p className="rounded-lg border border-edge bg-surface-1 px-3 py-2 text-xs leading-relaxed text-text-3">
                        About {bufferEstimate} MiB of file data can be buffered at once at most, excluding
                        Azure SDK overhead. Throttling temporarily lowers active transfers.
                    </p>
                </div>
            </DmDisclosure>

            {guideOpen ? (
                <DataManagementGuideDialog guide="ru-boost" onClose={() => setGuideOpen(false)} />
            ) : null}
            {dialog}
        </div>
    );
}
