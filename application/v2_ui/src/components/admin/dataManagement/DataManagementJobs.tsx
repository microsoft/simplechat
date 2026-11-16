// DataManagementJobs.tsx
// Jobs is the operator workbench for long-running Backup & Recovery history: it keeps the list lazy, the filters server-backed, and the selected job detail live.

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import { RotateCw } from 'lucide-react';
import {
    HISTORY_PAGE_SIZES,
    listJobs,
    readHistoryFailure,
    type DataManagementJob,
    type HistoryFailure,
    type JobFilters,
    type JobPage,
} from '../../../lib/dataManagement';
import {
    FIRST_PAGE,
    formatDateTime,
    formatOperation,
    isActiveJob,
    pagerAfterLoad,
    pagerBack,
    pagerForward,
    pagerPageNumber,
    progressPercent,
    validateHistoryDateRange,
} from '../../../lib/dataManagementLogic';
import { currentEpoch, isCurrentEpoch, useDataManagementStore } from '../../../stores/dataManagementStore';
import { GlassButton } from '../../ui/primitives';
import {
    DmCardProps,
    DmDateFilter,
    DmEmpty,
    DmFilterSelect,
    DmIntro,
    DmNotice,
    DmPager,
    DmStatusPill,
    DmWorkbench,
    isStacked,
    useVisibleOnce,
} from './DmShared';
import { DataManagementJobDetail } from './DataManagementJobDetail';

const OPERATION_OPTIONS: ReadonlyArray<readonly [string, string]> = [
    ['', 'All operations'],
    ['backup', 'Backup'],
    ['migration', 'Migration'],
    ['restore', 'Restore'],
    ['dry_run', 'Dry run'],
];

const STATUS_OPTIONS: ReadonlyArray<readonly [string, string]> = [
    ['', 'All statuses'],
    ['queued', 'Queued'],
    ['running', 'Running'],
    ['completed', 'Completed'],
    ['completed_with_warnings', 'Completed with warnings'],
    ['failed', 'Failed'],
    ['canceled', 'Canceled'],
];

const RUN_TYPE_OPTIONS: ReadonlyArray<readonly [string, string]> = [
    ['all', 'Scheduled and manual'],
    ['scheduled', 'Scheduled'],
    ['manual', 'Manual'],
];

const PAGE_SIZE_OPTIONS: ReadonlyArray<readonly [string, string]> = HISTORY_PAGE_SIZES.map(
    (size) => [String(size), String(size)] as const,
);

function selectedRequester(job: DataManagementJob): string {
    if (job.scheduled) return 'Scheduled';
    return job.requested_by_email || 'Manual';
}

function formatNumberForStatus(value: unknown): string {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : '0';
}

function errorNotice(failure: HistoryFailure, retry: () => void) {
    const retryable = failure.retryable || !failure.maintenanceRequired;
    return (
        <DmNotice
            tone={failure.maintenanceRequired ? 'warning' : 'danger'}
            role="alert"
            title={
                failure.maintenanceRequired ? 'Job history needs maintenance' : 'Job history could not load'
            }
            action={
                retryable ? (
                    <GlassButton type="button" variant="subtle" size="sm" onClick={retry}>
                        Retry
                    </GlassButton>
                ) : null
            }
        >
            {failure.message}
        </DmNotice>
    );
}

export function DataManagementJobs({ help, disabled = false }: DmCardProps) {
    const rootRef = useRef<HTMLDivElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const detailRef = useRef<HTMLDivElement>(null);
    const visible = useVisibleOnce(rootRef);
    const filters = useDataManagementStore((state) => state.jobs.filters);
    const pager = useDataManagementStore((state) => state.jobs.pager);
    const selectedId = useDataManagementStore((state) => state.jobs.selectedId);
    const jobsRevision = useDataManagementStore((state) => state.jobsRevision);
    const focusJobId = useDataManagementStore((state) => state.focusJobId);
    const updateJobs = useDataManagementStore((state) => state.updateJobs);
    const focusJob = useDataManagementStore((state) => state.focusJob);
    const [rows, setRows] = useState<DataManagementJob[]>([]);
    const [pagination, setPagination] = useState<JobPage['pagination']>({});
    const [loading, setLoading] = useState(false);
    const [failure, setFailure] = useState<HistoryFailure | null>(null);
    const [refreshVersion, setRefreshVersion] = useState(0);
    const controllerRef = useRef<AbortController | null>(null);
    const requestRef = useRef(0);
    const emptyPageFallbackUsed = useRef(false);

    const dateError = useMemo(
        () => validateHistoryDateRange(filters.createdFrom || '', filters.createdTo || ''),
        [filters.createdFrom, filters.createdTo],
    );

    const selectedJob = useMemo(() => rows.find((job) => job.id === selectedId) ?? null, [rows, selectedId]);

    const load = useCallback(() => {
        setRefreshVersion((current) => current + 1);
    }, []);

    // Keeps the list row in step with the open job. A row that already matches is left as
    // it is, so a refresh that changed nothing does not re-render the list.
    const mergeJobRow = useCallback((job: DataManagementJob) => {
        setRows((current) => {
            const index = current.findIndex((row) => row.id === job.id);
            if (index < 0) return current;
            const row = current[index];
            const changed = (Object.keys(job) as (keyof DataManagementJob)[]).some(
                (key) => JSON.stringify(row[key]) !== JSON.stringify(job[key]),
            );
            if (!changed) return current;
            const next = [...current];
            next[index] = { ...row, ...job };
            return next;
        });
    }, []);

    useEffect(() => {
        if (!focusJobId) return;
        updateJobs({ selectedId: focusJobId });
        focusJob(null);
        detailRef.current?.scrollIntoView({ block: 'nearest' });
    }, [focusJob, focusJobId, updateJobs]);

    useEffect(() => {
        if (!visible || dateError) {
            controllerRef.current?.abort();
            setLoading(false);
            return;
        }
        controllerRef.current?.abort();
        const controller = new AbortController();
        controllerRef.current = controller;
        const request = requestRef.current + 1;
        requestRef.current = request;
        const epoch = currentEpoch();
        setLoading(true);
        setFailure(null);
        void listJobs(filters as JobFilters, pager.current, controller.signal)
            .then((page) => {
                if (controller.signal.aborted || requestRef.current !== request || !isCurrentEpoch(epoch))
                    return;
                if (
                    !emptyPageFallbackUsed.current &&
                    pager.current !== null &&
                    pager.previous.length > 0 &&
                    !page.jobs.length &&
                    !page.pagination.next_token
                ) {
                    emptyPageFallbackUsed.current = true;
                    updateJobs((state) =>
                        state.pager.current === pager.current
                            ? { ...state, pager: pagerBack(state.pager), selectedId: null }
                            : state,
                    );
                    return;
                }
                if (pager.current === null || page.jobs.length || page.pagination.next_token) {
                    emptyPageFallbackUsed.current = false;
                }
                setRows(page.jobs);
                setPagination(page.pagination);
                updateJobs((state) => {
                    if (state.pager.current !== pager.current) return state;
                    return { ...state, pager: pagerAfterLoad(state.pager, page.pagination.next_token) };
                });
            })
            .catch((error) => {
                if (controller.signal.aborted || requestRef.current !== request) return;
                setRows([]);
                setPagination({});
                setFailure(readHistoryFailure(error, 'Job history could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted && requestRef.current === request) {
                    setLoading(false);
                }
            });
        return () => controller.abort();
    }, [dateError, filters, jobsRevision, pager.current, refreshVersion, updateJobs, visible]);

    const setFilter = <K extends keyof JobFilters>(key: K, value: JobFilters[K]) => {
        emptyPageFallbackUsed.current = false;
        updateJobs((state) => ({
            ...state,
            filters: { ...state.filters, [key]: value },
            pager: FIRST_PAGE,
            selectedId: null,
        }));
    };

    const selectJob = (jobId: string) => {
        updateJobs({ selectedId: jobId });
        requestAnimationFrame(() => {
            if (isStacked(listRef.current, detailRef.current)) {
                detailRef.current?.scrollIntoView({ block: 'start' });
            }
        });
    };

    const moveFocus = (index: number) => {
        const clamped = Math.max(0, Math.min(rows.length - 1, index));
        const id = rows[clamped]?.id;
        if (!id) return;
        document.getElementById(`dm-job-row-${id}`)?.focus();
    };

    const onRowKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            moveFocus(index + 1);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            moveFocus(index - 1);
        } else if (event.key === 'Home') {
            event.preventDefault();
            moveFocus(0);
        } else if (event.key === 'End') {
            event.preventDefault();
            moveFocus(rows.length - 1);
        }
    };

    const locked = disabled || loading;
    const pageNumber = pagerPageNumber(pager);
    const pageStatus = loading
        ? `Page ${pageNumber} · Loading jobs`
        : `Page ${pageNumber} · ${formatNumberForStatus(pagination.returned_count ?? rows.length)} jobs`;

    return (
        <div ref={rootRef} data-testid="dm-jobs" className="@container min-w-0 py-1">
            <DmIntro>
                {help ||
                    'Review backup, restore, migration, and dry-run jobs. Open a job to inspect progress, warnings, artifacts, and safe recovery actions.'}
            </DmIntro>

            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-text-3">Newest jobs first.</p>
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    disabled={locked || Boolean(dateError)}
                    onClick={load}
                >
                    <RotateCw size={14} aria-hidden="true" className={loading ? 'animate-spin' : undefined} />
                    Refresh
                </GlassButton>
            </div>

            <fieldset disabled={disabled} className="mt-4 min-w-0">
                <legend className="sr-only">Job history filters</legend>
                <div className="grid min-w-0 gap-3 @2xl:grid-cols-3 @5xl:grid-cols-6">
                    <DmFilterSelect
                        label="Operation"
                        value={filters.operation || ''}
                        options={OPERATION_OPTIONS}
                        onChange={(value) => setFilter('operation', value as JobFilters['operation'])}
                    />
                    <DmFilterSelect
                        label="Status"
                        value={filters.status || ''}
                        options={STATUS_OPTIONS}
                        onChange={(value) => setFilter('status', value)}
                    />
                    <DmFilterSelect
                        label="Run type"
                        value={filters.scheduled || 'all'}
                        options={RUN_TYPE_OPTIONS}
                        onChange={(value) => setFilter('scheduled', value as JobFilters['scheduled'])}
                    />
                    <DmDateFilter
                        label="Created from"
                        value={filters.createdFrom || ''}
                        invalid={Boolean(dateError)}
                        onChange={(value) => setFilter('createdFrom', value)}
                    />
                    <DmDateFilter
                        label="Created through"
                        value={filters.createdTo || ''}
                        invalid={Boolean(dateError)}
                        onChange={(value) => setFilter('createdTo', value)}
                    />
                    <DmFilterSelect
                        label="Rows per page"
                        value={String(filters.pageSize || 25)}
                        options={PAGE_SIZE_OPTIONS}
                        onChange={(value) => setFilter('pageSize', Number(value))}
                    />
                </div>
                {dateError ? (
                    <p className="mt-2 text-xs text-danger" role="alert">
                        {dateError}
                    </p>
                ) : null}
            </fieldset>

            <div className="mt-3 space-y-3">
                {failure ? errorNotice(failure, load) : null}
                {!visible ? (
                    <DmNotice tone="info">Job history will load when this card scrolls into view.</DmNotice>
                ) : null}
            </div>

            <DmWorkbench
                listLabel="Job list"
                detailRef={detailRef}
                list={
                    <div ref={listRef} className="min-w-0">
                        {loading && !rows.length ? (
                            <p className="p-4 text-sm text-text-3">Loading jobs…</p>
                        ) : null}
                        {!loading && !failure && visible && !rows.length ? (
                            <DmEmpty title="No jobs match these filters">
                                Adjust the filters or refresh after queueing a data-management job.
                            </DmEmpty>
                        ) : null}
                        <div role="list" aria-label="Jobs" className="divide-y divide-edge">
                            {rows.map((job, index) => {
                                const selected = job.id === selectedId;
                                return (
                                    <div key={job.id} role="listitem">
                                        <button
                                            id={`dm-job-row-${job.id}`}
                                            type="button"
                                            aria-pressed={selected}
                                            className={clsx(
                                                'block w-full min-w-0 px-3 py-3 text-left transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                                                selected && 'bg-accent-soft',
                                            )}
                                            onClick={() => selectJob(job.id)}
                                            onKeyDown={(event) => onRowKeyDown(event, index)}
                                        >
                                            <div className="flex min-w-0 items-start justify-between gap-2">
                                                <div className="min-w-0">
                                                    <p className="text-sm font-semibold break-words text-text-1">
                                                        {formatOperation(
                                                            job.operation || 'job',
                                                            job.backup_type || '',
                                                        )}
                                                    </p>
                                                    <p className="mt-1 text-xs text-text-3">
                                                        {formatDateTime(job.created_at) ||
                                                            'Created time not recorded'}
                                                    </p>
                                                </div>
                                                <DmStatusPill status={job.status || 'unknown'} />
                                            </div>
                                            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-text-3">
                                                <span className="min-w-0 break-all">
                                                    {selectedRequester(job)}
                                                </span>
                                                {isActiveJob(job.status) ? (
                                                    <span className="font-medium text-accent">
                                                        {progressPercent(job.progress)}%
                                                    </span>
                                                ) : null}
                                            </div>
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                        <DmPager
                            label="Job history pagination"
                            className="px-3 pb-3"
                            page={pageNumber}
                            hasPrevious={pager.previous.length > 0}
                            hasNext={Boolean(pager.next)}
                            loading={loading}
                            status={pageStatus}
                            onPrevious={() => {
                                emptyPageFallbackUsed.current = false;
                                updateJobs((state) => ({ ...state, pager: pagerBack(state.pager) }));
                            }}
                            onNext={() => {
                                emptyPageFallbackUsed.current = false;
                                updateJobs((state) => ({ ...state, pager: pagerForward(state.pager) }));
                            }}
                        />
                    </div>
                }
                detail={
                    <DataManagementJobDetail
                        jobId={selectedId}
                        initialJob={selectedJob}
                        disabled={disabled}
                        onJobUpdated={mergeJobRow}
                    />
                }
            />
        </div>
    );
}
