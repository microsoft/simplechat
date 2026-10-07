// DataManagementBackupInventory.tsx
// Backup Inventory & Restore: the workbench keeps the risky restore and cleanup actions beside
// the backup evidence that makes them safe to choose.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import {
    BriefcaseBusiness,
    CalendarClock,
    DatabaseBackup,
    FileArchive,
    Lock,
    RefreshCw,
    RotateCcw,
    Trash2,
} from 'lucide-react';
import {
    deleteBackup,
    errorMessage,
    HISTORY_PAGE_SIZES,
    listBackups,
    readHistoryFailure,
    runRetentionCleanup,
    type BackupGlobalSummary,
    type BackupPage,
    type BackupRow,
    type HistoryFailure,
    type RetentionCleanupResult,
} from '../../../lib/dataManagement';
import {
    computeRetentionDays,
    DM_SECTION_IDS,
    FIRST_PAGE,
    formatBackupType,
    formatBytes,
    formatDateTime,
    formatNumber,
    pagerAfterLoad,
    pagerBack,
    pagerForward,
    pagerPageNumber,
    readDmValues,
    validateHistoryDateRange,
} from '../../../lib/dataManagementLogic';
import { currentEpoch, isCurrentEpoch, useDataManagementStore } from '../../../stores/dataManagementStore';
import { toast } from '../../../stores/toastStore';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { GlassButton, Skeleton } from '../../ui/primitives';
import {
    DmChip,
    DmDateFilter,
    DmEmpty,
    DmFilterSelect,
    DmIntro,
    DmMetricGrid,
    DmNotice,
    DmPager,
    DmStatusPill,
    DmWorkbench,
    useVisibleOnce,
    type DmCardProps,
} from './DmShared';
import { useSaveFirst } from './useSaveFirst';
import { DataManagementRestoreDialog } from './DataManagementRestoreDialog';

const STATUS_OPTIONS = [
    ['available', 'Available'],
    ['', 'All statuses'],
    ['completed', 'Completed'],
    ['completed_with_warnings', 'Completed with warnings'],
    ['queued', 'Queued'],
    ['running', 'Running'],
    ['failed', 'Failed'],
    ['canceled', 'Canceled'],
] as const;

const RUN_TYPE_OPTIONS = [
    ['all', 'Scheduled and manual'],
    ['scheduled', 'Scheduled'],
    ['manual', 'Manual'],
] as const;

const PAGE_SIZE_OPTIONS = HISTORY_PAGE_SIZES.map((size) => [String(size), String(size)] as const);

function count(value: unknown): number {
    const number = Number(value ?? 0);
    return Number.isFinite(number) ? number : 0;
}

function text(value: unknown, fallback = ''): string {
    return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function runType(backup: BackupRow): string {
    return backup.scheduled ? 'Scheduled' : 'Manual';
}

function contentsLabel(backup: BackupRow): string {
    return `${formatNumber(backup.record_count)} records / ${formatNumber(backup.blob_count)} blobs`;
}

function warningLabel(backup: BackupRow): string {
    const warnings = count(backup.warning_count);
    return warnings ? `${formatNumber(warnings)} warning${warnings === 1 ? '' : 's'}` : 'No warnings';
}

function canRestore(backup: BackupRow | null): boolean {
    return Boolean(
        backup?.id &&
        backup.manifest_path &&
        (backup.status === 'completed' || backup.status === 'completed_with_warnings'),
    );
}

function isStacked(list: HTMLElement | null, detail: HTMLElement | null): boolean {
    if (!list || !detail) return false;
    return Math.abs(list.getBoundingClientRect().top - detail.getBoundingClientRect().top) > 16;
}

function cleanupResultMessage(result: RetentionCleanupResult): string {
    const deleted = count(result.deleted_count);
    return deleted
        ? `Deleted ${formatNumber(deleted)} expired backup${deleted === 1 ? '' : 's'}.`
        : 'No expired backups were deleted.';
}

function SummaryTile({
    label,
    description,
    value,
    active,
    icon,
    onClick,
}: {
    label: string;
    description: string;
    value: unknown;
    active: boolean;
    icon: JSX.Element;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            aria-pressed={active}
            onClick={onClick}
            className={clsx(
                'min-w-0 rounded-xl border px-4 py-3 text-left transition-colors',
                active
                    ? 'border-accent/50 bg-accent-soft text-accent ring-1 ring-accent/30'
                    : 'border-edge bg-surface-1 text-text-1 hover:bg-surface-sunken',
            )}
        >
            <span className="flex items-center gap-2 text-xs font-medium">
                {icon}
                {label}
            </span>
            <span className="mt-1 block text-2xl font-semibold tabular-nums">{formatNumber(value)}</span>
            <span
                className={clsx('mt-1 block text-xs leading-relaxed', active ? 'text-accent' : 'text-text-3')}
            >
                {description}
            </span>
        </button>
    );
}

export function DataManagementBackupInventory({ help, onNavigate, disabled }: DmCardProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const detailRef = useRef<HTMLDivElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const visible = useVisibleOnce(rootRef);
    const { ensure, dialog } = useSaveFirst();

    const inventory = useDataManagementStore((state) => state.inventory);
    const backupsRevision = useDataManagementStore((state) => state.backupsRevision);
    const updateInventory = useDataManagementStore((state) => state.updateInventory);

    const [page, setPage] = useState<BackupPage>({ summary: {}, backups: [], pagination: {} });
    const [loading, setLoading] = useState(false);
    const [failure, setFailure] = useState<HistoryFailure | null>(null);
    const [refreshNonce, setRefreshNonce] = useState(0);
    const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
    const [cleanupConfirm, setCleanupConfirm] = useState<{ retentionDays: number } | null>(null);
    const [cleanupBusy, setCleanupBusy] = useState(false);
    const [cleanupOutcome, setCleanupOutcome] = useState<RetentionCleanupResult | null>(null);
    const [deleteTarget, setDeleteTarget] = useState<BackupRow | null>(null);
    const [deleteBusy, setDeleteBusy] = useState(false);
    const [deleteError, setDeleteError] = useState<string | null>(null);
    const [restoreTarget, setRestoreTarget] = useState<BackupRow | null>(null);
    const generation = useRef(0);

    const dateRangeError = validateHistoryDateRange(
        inventory.filters.createdFrom,
        inventory.filters.createdTo,
    );
    const selected = page.backups.find((backup) => backup.id === inventory.selectedId) ?? null;
    const hasPrevious = inventory.pager.previous.length > 0;
    const hasNext = Boolean(page.pagination.has_more && inventory.pager.next);

    const setFilters = (update: Partial<typeof inventory.filters>) => {
        updateInventory((state) => ({
            ...state,
            filters: { ...state.filters, ...update },
            pager: FIRST_PAGE,
            selectedId: null,
        }));
        setFocusedRowId(null);
        setCleanupOutcome(null);
    };

    const selectBackup = (backupId: string) => {
        updateInventory({ selectedId: backupId });
        requestAnimationFrame(() => {
            if (isStacked(listRef.current, detailRef.current)) {
                detailRef.current?.scrollIntoView({ block: 'start' });
            }
        });
    };

    const onListKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        const buttons = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-backup-row]'),
        );
        if (!buttons.length) return;
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next =
            event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? buttons.length - 1
                  : event.key === 'ArrowDown'
                    ? Math.min(buttons.length - 1, index + 1)
                    : Math.max(0, index - 1);
        buttons[next]?.focus();
    };

    useEffect(() => {
        if (!visible || dateRangeError) return undefined;
        const controller = new AbortController();
        const requestGeneration = generation.current + 1;
        generation.current = requestGeneration;
        setLoading(true);
        setFailure(null);
        const filters = inventory.filters;
        const token = inventory.pager.current;

        listBackups(filters, token, controller.signal)
            .then((nextPage) => {
                if (controller.signal.aborted || generation.current !== requestGeneration) return;
                setPage(nextPage);
                updateInventory((state) => ({
                    ...state,
                    pager:
                        state.pager.current === token
                            ? pagerAfterLoad(state.pager, nextPage.pagination.next_token)
                            : state.pager,
                    selectedId:
                        state.selectedId && nextPage.backups.some((backup) => backup.id === state.selectedId)
                            ? state.selectedId
                            : null,
                }));
            })
            .catch((error: unknown) => {
                if (controller.signal.aborted || generation.current !== requestGeneration) return;
                setFailure(readHistoryFailure(error, 'Backup inventory could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted && generation.current === requestGeneration) setLoading(false);
            });

        return () => controller.abort();
    }, [
        visible,
        dateRangeError,
        inventory.filters.status,
        inventory.filters.scheduled,
        inventory.filters.pageSize,
        inventory.filters.backupType,
        inventory.filters.createdFrom,
        inventory.filters.createdTo,
        inventory.pager.current,
        backupsRevision,
        refreshNonce,
        updateInventory,
    ]);

    const tabStopId =
        (focusedRowId && page.backups.some((backup) => backup.id === focusedRowId) && focusedRowId) ||
        (inventory.selectedId &&
            page.backups.some((backup) => backup.id === inventory.selectedId) &&
            inventory.selectedId) ||
        page.backups[0]?.id;

    const summary: BackupGlobalSummary = page.summary ?? {};

    const runCleanup = async () => {
        const epoch = currentEpoch();
        setCleanupBusy(true);
        setCleanupOutcome(null);
        try {
            const result = await useDataManagementStore.getState().trackRequest(runRetentionCleanup());
            if (!isCurrentEpoch(epoch)) return;
            setCleanupOutcome(result);
            useDataManagementStore.getState().notifyBackupsChanged();
            useDataManagementStore.getState().notifyJobsChanged();
            if (count(result.errors?.length)) {
                toast.error('Retention cleanup completed with errors.');
            } else {
                toast.success(cleanupResultMessage(result));
            }
            setCleanupConfirm(null);
        } catch (error) {
            if (!isCurrentEpoch(epoch)) return;
            toast.error(errorMessage(error, 'Backup retention cleanup could not be completed.'));
        } finally {
            if (isCurrentEpoch(epoch)) setCleanupBusy(false);
        }
    };

    const confirmCleanup = async () => {
        const epoch = currentEpoch();
        if (!(await ensure('retention-cleanup')) || !isCurrentEpoch(epoch)) return;
        const state = useDataManagementStore.getState();
        const freshValues = readDmValues(state.settings, state.draft);
        setCleanupConfirm({
            retentionDays: computeRetentionDays(freshValues.retention_value, freshValues.retention_unit),
        });
    };

    const runDelete = async () => {
        if (!deleteTarget?.id) return;
        const epoch = currentEpoch();
        setDeleteBusy(true);
        setDeleteError(null);
        try {
            const result = await useDataManagementStore
                .getState()
                .trackRequest(deleteBackup(deleteTarget.id));
            if (!isCurrentEpoch(epoch)) return;
            toast.success(
                `Deleted ${formatBackupType(deleteTarget.backup_type)} backup and ${formatNumber(result.deleted_blob_count)} stored artifact${count(result.deleted_blob_count) === 1 ? '' : 's'}.`,
            );
            useDataManagementStore.getState().notifyBackupsChanged();
            useDataManagementStore.getState().notifyJobsChanged();
            updateInventory({ selectedId: null });
            setDeleteTarget(null);
        } catch (error) {
            if (!isCurrentEpoch(epoch)) return;
            setDeleteError(errorMessage(error, 'Backup could not be deleted.'));
        } finally {
            if (isCurrentEpoch(epoch)) setDeleteBusy(false);
        }
    };

    const list = (
        <div ref={listRef} className="min-h-full">
            {loading && !page.backups.length ? (
                <div className="space-y-2 p-3" aria-label="Loading backups">
                    <Skeleton className="h-16" />
                    <Skeleton className="h-16" />
                    <Skeleton className="h-16" />
                </div>
            ) : page.backups.length ? (
                <ul aria-label="Backup inventory" onKeyDown={onListKeyDown}>
                    {page.backups.map((backup) => {
                        const isSelected = backup.id === inventory.selectedId;
                        const warnings = count(backup.warning_count);
                        const metaId = `dm-backup-row-${backup.id}`;
                        return (
                            <li key={backup.id}>
                                <button
                                    type="button"
                                    data-backup-row
                                    aria-pressed={isSelected}
                                    aria-describedby={metaId}
                                    tabIndex={backup.id === tabStopId ? 0 : -1}
                                    onFocus={() => setFocusedRowId(backup.id)}
                                    onClick={() => selectBackup(backup.id)}
                                    className={clsx(
                                        'flex w-full min-w-0 flex-col gap-2 border-b border-edge px-3 py-2.5 text-left transition-colors',
                                        isSelected
                                            ? 'bg-accent-soft ring-1 ring-accent/40 ring-inset'
                                            : 'hover:bg-surface-sunken',
                                    )}
                                >
                                    <span className="flex min-w-0 items-center justify-between gap-2">
                                        <span className="flex min-w-0 items-center gap-2">
                                            <DmChip
                                                tone={backup.backup_type === 'full' ? 'active' : 'neutral'}
                                            >
                                                {formatBackupType(backup.backup_type)}
                                            </DmChip>
                                            <DmStatusPill status={backup.status} />
                                        </span>
                                        {backup.encrypted ? (
                                            <span className="inline-flex items-center text-ok">
                                                <Lock size={13} aria-hidden="true" />
                                                <span className="sr-only">Encrypted backup</span>
                                            </span>
                                        ) : null}
                                    </span>
                                    <span id={metaId} className="grid gap-1 text-xs text-text-3">
                                        <span>
                                            {formatDateTime(backup.completed_at || backup.created_at) ||
                                                'Time not recorded'}
                                        </span>
                                        <span>{contentsLabel(backup)}</span>
                                        <span className={warnings ? 'text-warn' : undefined}>
                                            {warningLabel(backup)}
                                        </span>
                                    </span>
                                </button>
                            </li>
                        );
                    })}
                </ul>
            ) : (
                <DmEmpty
                    title={visible ? 'No backups match these filters' : 'Backup inventory has not loaded yet'}
                >
                    {visible
                        ? 'Change the filters or refresh after a backup job finishes.'
                        : 'The list loads when this card is visible.'}
                </DmEmpty>
            )}
        </div>
    );

    const detail = selected ? (
        <div className="space-y-4 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="text-sm font-semibold text-text-1">
                        {formatBackupType(selected.backup_type)} backup
                    </p>
                    <p className="mt-0.5 break-all text-xs text-text-3">{selected.id}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                    <DmStatusPill status={selected.status} />
                    <DmChip>{runType(selected)}</DmChip>
                </div>
            </div>

            <DmMetricGrid
                label="Backup details"
                items={[
                    { label: 'ID', value: <span className="break-all">{selected.id}</span> },
                    { label: 'Type', value: formatBackupType(selected.backup_type) },
                    { label: 'Status', value: <DmStatusPill status={selected.status} /> },
                    { label: 'Run type', value: runType(selected) },
                    { label: 'Created', value: formatDateTime(selected.created_at) || 'Not recorded' },
                    { label: 'Completed', value: formatDateTime(selected.completed_at) || 'Not recorded' },
                    { label: 'Contents', value: contentsLabel(selected) },
                    { label: 'Size', value: formatBytes(selected.bytes) },
                    { label: 'Artifacts', value: formatNumber(selected.artifact_count) },
                    { label: 'Protection', value: selected.encrypted ? 'Encrypted' : 'Not encrypted' },
                    { label: 'Warnings', value: warningLabel(selected) },
                    { label: 'Manifest', value: selected.manifest_path ? 'Recorded' : 'Missing' },
                    {
                        label: 'Storage prefix',
                        value: (
                            <span className="break-all">{text(selected.base_prefix, 'Not recorded')}</span>
                        ),
                    },
                ]}
            />

            {selected.last_message ? <DmNotice title="Last message">{selected.last_message}</DmNotice> : null}

            <div className="flex flex-wrap gap-2">
                <GlassButton
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={disabled || !canRestore(selected)}
                    onClick={() => setRestoreTarget(selected)}
                >
                    <RotateCcw size={14} aria-hidden="true" />
                    Restore…
                </GlassButton>
                {selected.can_delete ? (
                    <GlassButton
                        type="button"
                        variant="danger"
                        size="sm"
                        disabled={disabled}
                        onClick={() => {
                            setDeleteError(null);
                            setDeleteTarget(selected);
                        }}
                    >
                        <Trash2 size={14} aria-hidden="true" />
                        Delete…
                    </GlassButton>
                ) : null}
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => {
                        useDataManagementStore.getState().focusJob(selected.id);
                        onNavigate(DM_SECTION_IDS.jobs);
                    }}
                >
                    <BriefcaseBusiness size={14} aria-hidden="true" />
                    View job
                </GlassButton>
            </div>

            {!canRestore(selected) ? (
                <p className="text-xs text-text-3">
                    Restore is available only for completed backups with a recorded manifest.
                </p>
            ) : null}
        </div>
    ) : (
        <DmEmpty title="No backup selected">
            Choose a backup row to inspect its manifest, storage and restore actions.
        </DmEmpty>
    );

    return (
        <div ref={rootRef} data-testid="dm-backup-inventory" className="@container min-w-0 py-1">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <DmIntro>
                    {help ??
                        'Track completed full and partial backups, review their contents, and restore or delete them deliberately.'}
                </DmIntro>
                <div className="flex flex-wrap gap-2">
                    <GlassButton
                        type="button"
                        variant="danger"
                        size="sm"
                        disabled={disabled || cleanupBusy}
                        onClick={() => void confirmCleanup()}
                    >
                        <Trash2 size={14} aria-hidden="true" />
                        Run retention cleanup
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        disabled={loading}
                        onClick={() => setRefreshNonce((value) => value + 1)}
                    >
                        <RefreshCw size={14} aria-hidden="true" className={clsx(loading && 'animate-spin')} />
                        Refresh
                    </GlassButton>
                </div>
            </div>

            <div
                className="grid gap-3 @2xl:grid-cols-3"
                role="group"
                aria-label="Backup inventory summary filters"
            >
                <SummaryTile
                    label="Available backups"
                    description="Completed backups ready to inspect or restore later."
                    value={summary.available}
                    active={inventory.filters.backupType === ''}
                    icon={<DatabaseBackup size={14} aria-hidden="true" />}
                    onClick={() => setFilters({ backupType: '' })}
                />
                <SummaryTile
                    label="Full backups"
                    description="Complete snapshots across the selected backup surfaces."
                    value={summary.full}
                    active={inventory.filters.backupType === 'full'}
                    icon={<FileArchive size={14} aria-hidden="true" />}
                    onClick={() => setFilters({ backupType: 'full' })}
                />
                <SummaryTile
                    label="Partial backups"
                    description="Daily change captures between full backup windows."
                    value={summary.partial}
                    active={inventory.filters.backupType === 'partial'}
                    icon={<CalendarClock size={14} aria-hidden="true" />}
                    onClick={() => setFilters({ backupType: 'partial' })}
                />
            </div>

            <fieldset disabled={disabled} className="mt-3 grid gap-3 @2xl:grid-cols-3 @5xl:grid-cols-5">
                <DmFilterSelect
                    label="Status"
                    value={inventory.filters.status}
                    options={STATUS_OPTIONS}
                    onChange={(status) => setFilters({ status })}
                />
                <DmFilterSelect
                    label="Run type"
                    value={inventory.filters.scheduled}
                    options={RUN_TYPE_OPTIONS}
                    onChange={(scheduled) =>
                        setFilters({ scheduled: scheduled as typeof inventory.filters.scheduled })
                    }
                />
                <DmDateFilter
                    label="Created from"
                    value={inventory.filters.createdFrom}
                    invalid={Boolean(dateRangeError)}
                    onChange={(createdFrom) => setFilters({ createdFrom })}
                />
                <DmDateFilter
                    label="Created through"
                    value={inventory.filters.createdTo}
                    invalid={Boolean(dateRangeError)}
                    onChange={(createdTo) => setFilters({ createdTo })}
                />
                <DmFilterSelect
                    label="Rows per page"
                    value={String(inventory.filters.pageSize)}
                    options={PAGE_SIZE_OPTIONS}
                    onChange={(pageSize) => setFilters({ pageSize: Number(pageSize) })}
                />
            </fieldset>

            {dateRangeError ? (
                <DmNotice tone="warning" className="mt-3" role="alert">
                    {dateRangeError}
                </DmNotice>
            ) : null}

            {failure ? (
                <DmNotice
                    tone={failure.maintenanceRequired ? 'warning' : 'danger'}
                    title={
                        failure.maintenanceRequired
                            ? 'Backup history needs maintenance'
                            : 'Backup inventory did not load'
                    }
                    role="alert"
                    className="mt-3"
                    action={
                        failure.retryable ? (
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                onClick={() => setRefreshNonce((value) => value + 1)}
                            >
                                Retry
                            </GlassButton>
                        ) : null
                    }
                >
                    {failure.message}
                </DmNotice>
            ) : null}

            {cleanupOutcome ? (
                <DmNotice
                    tone={count(cleanupOutcome.errors?.length) ? 'warning' : 'success'}
                    title="Retention cleanup result"
                    role="status"
                    className="mt-3"
                >
                    <span>
                        {cleanupResultMessage(cleanupOutcome)} Candidates:{' '}
                        {formatNumber(cleanupOutcome.candidate_count)}. Errors:{' '}
                        {formatNumber(cleanupOutcome.errors?.length)}. Cutoff:{' '}
                        {formatDateTime(cleanupOutcome.cutoff_at) || 'not returned'}.
                    </span>
                </DmNotice>
            ) : null}

            <DmWorkbench
                list={list}
                detail={detail}
                listLabel="Backup inventory list"
                detailRef={detailRef}
            />

            <DmPager
                label="Backup inventory pagination"
                page={pagerPageNumber(inventory.pager)}
                hasPrevious={hasPrevious}
                hasNext={hasNext}
                loading={loading}
                status={`Page ${pagerPageNumber(inventory.pager)} · ${formatNumber(page.pagination.returned_count ?? page.backups.length)} backups returned`}
                onPrevious={() =>
                    updateInventory((state) => ({
                        ...state,
                        pager: pagerBack(state.pager),
                        selectedId: null,
                    }))
                }
                onNext={() =>
                    updateInventory((state) => ({
                        ...state,
                        pager: pagerForward(state.pager),
                        selectedId: null,
                    }))
                }
            />

            {cleanupConfirm ? (
                <ConfirmDialog
                    title="Run retention cleanup?"
                    description={`This permanently deletes eligible backups older than the configured retention period (${cleanupConfirm.retentionDays} days) and removes their stored files.`}
                    confirmLabel="Run cleanup"
                    confirmIcon={<Trash2 size={14} aria-hidden="true" />}
                    tone="danger"
                    busy={cleanupBusy}
                    onConfirm={() => void runCleanup()}
                    onClose={() => {
                        if (!cleanupBusy) setCleanupConfirm(null);
                    }}
                >
                    <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed text-text-2">
                        <li>Only finished backups are eligible; queued or running jobs are skipped.</li>
                        <li>The newest successful full backup is kept, even when it is past the cutoff.</li>
                        <li>Each run deletes at most 25 backups, so large cleanups may need several runs.</li>
                        <li>
                            While scheduled backups are on, cleanup also runs on its own. Finding nothing to
                            delete is normal.
                        </li>
                    </ul>
                </ConfirmDialog>
            ) : null}

            {deleteTarget ? (
                <ConfirmDialog
                    title="Delete backup?"
                    description={`Delete ${formatBackupType(deleteTarget.backup_type)} backup ${deleteTarget.id}?`}
                    confirmLabel="Delete backup"
                    confirmIcon={<Trash2 size={14} aria-hidden="true" />}
                    tone="danger"
                    busy={deleteBusy}
                    onConfirm={() => void runDelete()}
                    onClose={() => {
                        if (!deleteBusy) setDeleteTarget(null);
                    }}
                >
                    <div className="space-y-2 text-xs leading-relaxed text-text-2">
                        <p>
                            Deleting removes the stored backup files, the job&apos;s timeline records and the
                            partial-backup state kept for it.
                        </p>
                        <p>
                            Future partial backups re-export the unchanged items this backup covered. This
                            cannot be undone.
                        </p>
                        {deleteError ? (
                            <p role="alert" className="text-danger">
                                {deleteError}
                            </p>
                        ) : null}
                    </div>
                </ConfirmDialog>
            ) : null}

            {restoreTarget ? (
                <DataManagementRestoreDialog
                    backup={restoreTarget}
                    onClose={() => setRestoreTarget(null)}
                    onNavigate={onNavigate}
                />
            ) : null}

            {dialog}
        </div>
    );
}
