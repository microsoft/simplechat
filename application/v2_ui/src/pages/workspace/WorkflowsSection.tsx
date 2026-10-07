// WorkflowsSection.tsx
// Personal and group workflows as a workbench: find a workflow, see where it stands, run it, read
// its runs, and open its editor.
//
// A group section offers each control from the context's workflow hint, the routes' own rule: every
// member may run and cancel, and only the management roles create, edit and delete.
//
// The list used to be a column of rows, each with a strip of icon buttons and its run history
// expanding inside the row, so reading one run pushed every other workflow down the page. It is
// Admin's Model Catalog shape now: one-line rows beside a detail pane whose tabs scroll on their
// own -- Overview, Runs, and for a structured workflow its Flow. The editor is a page of its own
// (WorkflowEditorPage), at the address Edit and Create workflow open.
//
// Links still arrive as `?workflow_id=` (select that workflow) and `&run_id=` (open its Runs tab
// with that run expanded); see workflowRunLink.ts. Each navigation that names a workflow is acted
// on once.

import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { clsx } from 'clsx';
import { AlertTriangle, CircleCheck, Plus, Workflow } from 'lucide-react';
import { EmptyState, GlassButton, Skeleton } from '../../components/ui/primitives';
import { SectionError, SectionIntro, SectionSearch } from '../../components/workspace/primitives';
import { errorMessage, useSectionResource } from '../../components/workspace/useSectionResource';
import { WorkflowStatusChip } from '../../components/workflows/WorkflowStatusChip';
import {
    WorkflowWorkbenchDetail,
    type WorkflowDetailTab,
} from '../../components/workflows/WorkflowWorkbenchDetail';
import {
    cancelScopedWorkflow,
    DEFAULT_WORKFLOW_SCOPE,
    deleteScopedWorkflow,
    fetchScopedWorkflows,
    startScopedWorkflowRun,
    workflowScopeKey,
    type WorkflowDefinition,
    type WorkflowRunStartResponse,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import { readWorkflowRunLink, workflowEditorHref } from '../../lib/workflowRunLink';
import {
    DEFAULT_WORKFLOW_WORKBENCH_FILTERS,
    filterWorkflows,
    workflowFiltersApplied,
    workflowNeedsAttention,
    workflowRowMeta,
    workflowStatusTone,
    WORKFLOW_STATUS_FILTER_LABELS,
    WORKFLOW_TRIGGER_FILTER_LABELS,
    type WorkflowStatusFilter,
    type WorkflowTriggerFilter,
    type WorkflowWorkbenchFilters,
} from '../../lib/workflowWorkbench';

/** Map a run or workflow status onto a pill colour. The File sources sections read it from here. */
export const statusTone = workflowStatusTone;

const filterSelectClass = clsx(
    'min-h-9 min-w-0 max-w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5 text-sm text-text-1',
    'focus:border-accent focus:outline-none',
);

function FilterSelect<T extends string>({ label, value, options, onChange }: {
    label: string;
    value: T;
    options: Readonly<Record<T, string>>;
    onChange: (value: T) => void;
}) {
    // Labelled by reference rather than by wrapping, so the select's name is the label alone and
    // not the label plus the option it shows.
    const id = useId();
    return (
        <div className="flex max-w-full min-w-0 items-center gap-2">
            <label htmlFor={id} className="text-xs font-medium text-text-2">{label}</label>
            <select id={id} className={filterSelectClass} value={value} onChange={(event) => onChange(event.target.value as T)}>
                {(Object.keys(options) as T[]).map((key) => <option key={key} value={key}>{options[key]}</option>)}
            </select>
        </div>
    );
}

function CreateWorkflowButton({ onClick }: { onClick: () => void }) {
    return (
        <GlassButton type="button" variant="primary" size="sm" onClick={onClick}>
            <Plus size={14} aria-hidden="true" />
            Create workflow
        </GlassButton>
    );
}

export function WorkflowsSection({
    scope = DEFAULT_WORKFLOW_SCOPE,
    onDirtyChange,
    onBusyChange,
    allowManage = true,
    interactionDisabled = false,
    operations,
}: {
    scope?: WorkflowScope;
    onDirtyChange?: (dirty: boolean) => void;
    onBusyChange?: (busy: boolean) => void;
    allowManage?: boolean;
    interactionDisabled?: boolean;
    /** The group workflow hint's operations; without one, `allowManage` gates every control. */
    operations?: readonly string[];
}) {
    const offered = Array.isArray(operations) ? new Set(operations) : null;
    const canCreate = offered ? offered.has('create') : allowManage;
    const canEdit = offered ? offered.has('edit') : allowManage;
    const canDelete = offered ? offered.has('delete') : allowManage;
    const canRun = offered ? offered.has('run') : allowManage;
    const canCancel = offered ? offered.has('cancel') : allowManage;
    const scopeKey = workflowScopeKey(scope);
    const location = useLocation();
    const navigate = useNavigate();
    const baseId = useId();
    const loadWorkflows = useCallback((signal?: AbortSignal) => fetchScopedWorkflows(scope, signal), [scopeKey]);
    const { items, loading, error, loadFailed, refresh, setItems, setError } =
        useSectionResource<WorkflowDefinition>(loadWorkflows, 'Failed to load workflows.');

    const [filters, setFilters] = useState<WorkflowWorkbenchFilters>(DEFAULT_WORKFLOW_WORKBENCH_FILTERS);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
    const [tab, setTab] = useState<WorkflowDetailTab>('overview');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [actionError, setActionError] = useState<{ workflowId: string; message: string } | null>(null);
    const [historyRefreshToken, setHistoryRefreshToken] = useState(0);
    const [linkedRun, setLinkedRun] = useState<{
        scopeKey: string;
        workflowId: string;
        runId: string;
        /** The navigation that named the run; a new one remounts the history. */
        navigation: string;
    } | null>(null);
    // A link that selected a workflow moves focus to its title once the detail has drawn it.
    const [focusRequest, setFocusRequest] = useState(0);
    // A row chosen while the detail sits below the list, as on a narrow screen, scrolls it into view.
    const [revealRequest, setRevealRequest] = useState(0);
    const detailHeadingRef = useRef<HTMLHeadingElement>(null);
    // The last navigation whose workflow link was acted on, and the last one that re-read the list
    // because the link named a workflow the list did not have yet.
    const handledNavigation = useRef<string | null>(null);
    const relistedNavigation = useRef<string | null>(null);

    // The workbench never holds an unsaved draft, so it clears any flag an editor left behind.
    useEffect(() => {
        onDirtyChange?.(false);
    }, [onDirtyChange]);

    useEffect(() => {
        onBusyChange?.(busyId !== null);
        return () => onBusyChange?.(false);
    }, [busyId, onBusyChange]);

    const visible = useMemo(() => filterWorkflows(items, filters), [items, filters]);
    const attention = useMemo(() => items.filter(workflowNeedsAttention).length, [items]);
    const filtersApplied = workflowFiltersApplied(filters) + Number(Boolean(filters.query.trim()));
    const selected = visible.find((workflow) => workflow.id === selectedId) ?? null;

    // The detail pane always has something to show while the list does: the first workflow until
    // another is chosen, and the next one along when the selected workflow is filtered out or deleted.
    useEffect(() => {
        if (loading) return;
        if (selectedId && visible.some((workflow) => workflow.id === selectedId)) return;
        setSelectedId(visible.find((workflow) => workflow.id)?.id ?? null);
    }, [loading, visible, selectedId]);

    useEffect(() => {
        const navigation = `${scopeKey}:${location.key}`;
        if (handledNavigation.current === navigation) {
            return;
        }
        const link = readWorkflowRunLink(location.search);
        if (!link) {
            handledNavigation.current = navigation;
            return;
        }
        if (loading) {
            return;
        }
        const workflow = items.find((item) => item.id === link.workflowId);
        if (!workflow && relistedNavigation.current !== navigation) {
            // The list can predate the workflow (one created in another tab); read it once more.
            relistedNavigation.current = navigation;
            void refresh();
            return;
        }
        handledNavigation.current = navigation;
        if (!workflow) {
            return;
        }
        // A filter left on from earlier must not hide the workflow the link came for.
        if (!filterWorkflows([workflow], filters).length) {
            setFilters(DEFAULT_WORKFLOW_WORKBENCH_FILTERS);
        }
        setSelectedId(link.workflowId);
        if (link.runId) {
            setLinkedRun({ scopeKey, workflowId: link.workflowId, runId: link.runId, navigation });
            setTab('runs');
        } else {
            setTab('overview');
        }
        setFocusRequest((count) => count + 1);
    }, [filters, items, loading, location.key, location.search, refresh, scopeKey]);

    useEffect(() => {
        if (!focusRequest) return;
        const frame = requestAnimationFrame(() => detailHeadingRef.current?.focus());
        return () => cancelAnimationFrame(frame);
    }, [focusRequest]);

    useEffect(() => {
        if (!revealRequest) return;
        const heading = detailHeadingRef.current;
        if (!heading) return;
        // Beside the list the detail is already in sight; stacked under it, it opened out of sight.
        const rect = heading.getBoundingClientRect();
        if (rect.top >= 0 && rect.bottom <= window.innerHeight) return;
        const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        heading.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' });
    }, [revealRequest]);

    const setFilter = <K extends keyof WorkflowWorkbenchFilters>(key: K, value: WorkflowWorkbenchFilters[K]) =>
        setFilters((current) => ({ ...current, [key]: value }));

    const reportError = (workflowId: string, message: string) => setActionError({ workflowId, message });

    const onRun = async (workflow: WorkflowDefinition) => {
        if (!workflow.id) {
            setError('This workflow has no stable identifier. Reload before trying again.');
            return;
        }
        if (interactionDisabled || !canRun) {
            reportError(workflow.id, 'You cannot run workflows with the current workspace access.');
            return;
        }
        setBusyId(workflow.id);
        setActionError(null);
        setTab('runs');
        try {
            const response: WorkflowRunStartResponse = await startScopedWorkflowRun(scope, workflow.id);
            const nextWorkflow = response.workflow
                ? response.workflow
                : response.run?.durable_execution === true && response.run.id
                    ? {
                        ...workflow,
                        active_run_id: response.run.id,
                        status: response.run.status ?? 'queued',
                    }
                    : workflow;
            setItems(items.map((item) => item.id === workflow.id ? nextWorkflow : item));
            await refresh();
        } catch (actionFailure) {
            await refresh();
            reportError(workflow.id, errorMessage(actionFailure, 'Could not start the workflow.'));
        } finally {
            setHistoryRefreshToken((value) => value + 1);
            setBusyId(null);
        }
    };

    const onCancel = async (workflow: WorkflowDefinition) => {
        if (!workflow.id) {
            setError('This workflow has no stable identifier. Reload before trying again.');
            return;
        }
        if (interactionDisabled || !canCancel) {
            reportError(workflow.id, 'You cannot change workflows with the current workspace access.');
            return;
        }
        setBusyId(workflow.id);
        setActionError(null);
        try {
            await cancelScopedWorkflow(scope, workflow.id);
            await refresh();
        } catch (actionFailure) {
            await refresh();
            reportError(workflow.id, errorMessage(actionFailure, 'Could not cancel the workflow.'));
        } finally {
            setHistoryRefreshToken((value) => value + 1);
            setBusyId(null);
        }
    };

    const onDelete = async (workflow: WorkflowDefinition) => {
        if (interactionDisabled || !canDelete) {
            if (workflow.id) reportError(workflow.id, 'You cannot delete workflows with the current workspace access.');
            return;
        }
        const previous = items;
        if (!workflow.id) {
            return;
        }
        setBusyId(workflow.id);
        setActionError(null);
        setItems(items.filter((item) => item.id !== workflow.id));
        try {
            await deleteScopedWorkflow(scope, workflow.id);
        } catch (deleteError) {
            setItems(previous);
            setSelectedId(workflow.id);
            setError(errorMessage(deleteError, 'Could not delete the workflow.'));
        } finally {
            setBusyId(null);
        }
    };

    const openEditor = (workflow: WorkflowDefinition | null) => {
        if (workflow && !workflow.id) {
            setError('This workflow has no stable identifier. Reload before trying again.');
            return;
        }
        navigate(workflowEditorHref(scope, workflow?.id ?? null));
    };

    const onListKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            return;
        }
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-workflow-row]'));
        if (!buttons.length) {
            return;
        }
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === 'Home' ? 0
            : event.key === 'End' ? buttons.length - 1
                : event.key === 'ArrowDown' ? Math.min(buttons.length - 1, index + 1)
                    : Math.max(0, index - 1);
        buttons[next]?.focus();
    };

    const tabStopId =
        (focusedRowId && visible.some((workflow) => workflow.id === focusedRowId) && focusedRowId) ||
        (selectedId && visible.some((workflow) => workflow.id === selectedId) && selectedId) ||
        visible.find((workflow) => workflow.id)?.id;

    const clearFilters = () => setFilters(DEFAULT_WORKFLOW_WORKBENCH_FILTERS);
    const showWorkbench = !loadFailed && (loading || items.length > 0);

    return (
        <fieldset disabled={interactionDisabled} className="@container flex min-h-0 min-w-0 flex-1 flex-col gap-3">
            <legend className="sr-only">Workspace workflows</legend>
            <div className="shrink-0 space-y-3">
                <SectionIntro
                    title="Workflows"
                    description="Repeatable tasks that run on their own, using a model or one of your agents. A workflow can run on a schedule or whenever you start it."
                    actions={canCreate ? <CreateWorkflowButton onClick={() => openEditor(null)} /> : undefined}
                />
                <p className="max-w-[72ch] text-xs leading-relaxed text-text-3">
                    Native V2 authoring is available for manual, interval and Monitor File Sync changes workflows, and for their alerts. Publication settings from existing workflows are preserved unchanged.
                    {scope.type === 'group' ? ' Workflow requests stay scoped to this group, even if your active workspace changes elsewhere.' : ''}
                </p>
                {location.state?.workspaceEditorSaved === true ? (
                    <p role="status" className="inline-flex items-center gap-1.5 text-xs text-text-2">
                        <CircleCheck size={13} aria-hidden="true" className="shrink-0 text-ok" />
                        Workflow saved.
                    </p>
                ) : null}
                {error ? (
                    <SectionError
                        message={error}
                        action={loadFailed ? (
                            <GlassButton size="sm" disabled={loading} onClick={() => void refresh()}>Retry workflows</GlassButton>
                        ) : undefined}
                    />
                ) : null}
                {showWorkbench ? (
                    <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                            <div className="min-w-[min(100%,16rem)] flex-1">
                                <SectionSearch value={filters.query} onChange={(query) => setFilter('query', query)} placeholder="Search workflows" />
                            </div>
                            <FilterSelect<WorkflowStatusFilter> label="Status" value={filters.status}
                                options={WORKFLOW_STATUS_FILTER_LABELS} onChange={(value) => setFilter('status', value)} />
                            <FilterSelect<WorkflowTriggerFilter> label="Trigger" value={filters.trigger}
                                options={WORKFLOW_TRIGGER_FILTER_LABELS} onChange={(value) => setFilter('trigger', value)} />
                        </div>
                        {!loading ? (
                            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-3">
                                <span>
                                    <span className="font-semibold text-text-1 tabular-nums">{visible.length}</span>
                                    {' of '}
                                    <span className="tabular-nums">{items.length}</span>
                                    {items.length === 1 ? ' workflow' : ' workflows'}
                                </span>
                                {attention ? (
                                    <span className="inline-flex items-center gap-1 text-text-2">
                                        <AlertTriangle size={12} aria-hidden="true" className="text-warn" />
                                        {attention} {attention === 1 ? 'needs' : 'need'} attention
                                    </span>
                                ) : null}
                                {filtersApplied ? (
                                    <button type="button" className="text-accent underline underline-offset-2" onClick={clearFilters}>
                                        Clear filters ({filtersApplied})
                                    </button>
                                ) : null}
                            </p>
                        ) : null}
                    </div>
                ) : null}
            </div>

            {!loading && !loadFailed && items.length === 0 ? (
                <EmptyState
                    icon={<Workflow size={28} />}
                    title="No workflows yet"
                    description="A workflow repeats a task you would otherwise run by hand."
                    action={canCreate ? <CreateWorkflowButton onClick={() => openEditor(null)} /> : undefined}
                />
            ) : null}

            {showWorkbench ? (
                <div className="min-h-0 flex-1 overflow-y-auto @3xl:overflow-hidden">
                    <div className="grid min-w-0 overflow-hidden rounded-xl border border-edge-strong bg-surface-solid @3xl:h-full @3xl:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
                        <div className="max-h-[24rem] min-h-0 overflow-y-auto border-b border-edge-strong @3xl:max-h-none @3xl:border-r @3xl:border-b-0">
                            <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-edge-strong bg-surface-solid px-3 py-2 text-xs font-semibold text-text-2">
                                <span>Workflow</span>
                                <span>Status</span>
                            </div>
                            {loading && !items.length ? (
                                <div role="status" className="space-y-2 p-3">
                                    <span className="sr-only">Loading workflows</span>
                                    {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-10 w-full" />)}
                                </div>
                            ) : visible.length ? (
                                <ul aria-label="Workflows" onKeyDown={onListKeyDown}>
                                    {visible.map((workflow, index) => {
                                        const workflowId = workflow.id ?? '';
                                        const isSelected = Boolean(workflowId) && workflowId === selectedId;
                                        const metaId = `${baseId}-row-${index}`;
                                        const name = String(workflow.name ?? '') || 'Untitled workflow';
                                        return (
                                            <li key={workflowId || `index-${index}`}>
                                                <button
                                                    type="button"
                                                    data-workflow-row
                                                    aria-pressed={isSelected}
                                                    aria-label={name}
                                                    aria-describedby={metaId}
                                                    disabled={!workflowId}
                                                    title={workflowId ? undefined : 'This workflow has no stable identifier. Reload before trying again.'}
                                                    tabIndex={workflowId && workflowId === tabStopId ? 0 : -1}
                                                    onFocus={() => setFocusedRowId(workflowId)}
                                                    onClick={() => {
                                                        setSelectedId(workflowId);
                                                        setRevealRequest((count) => count + 1);
                                                    }}
                                                    className={clsx(
                                                        'flex w-full items-center gap-2.5 border-b border-edge px-3 py-2.5 text-left transition-colors',
                                                        'disabled:cursor-not-allowed disabled:opacity-60',
                                                        isSelected
                                                            ? 'bg-accent-soft ring-1 ring-accent/40 ring-inset'
                                                            : 'hover:bg-surface-sunken',
                                                    )}
                                                >
                                                    {/* Wraps under the name while the list is stacked; beside the
                                                        detail a row is one line, and the facts give way first. */}
                                                    <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 @3xl:flex-nowrap">
                                                        <span className={clsx(
                                                            'min-w-0 truncate text-sm font-semibold',
                                                            isSelected ? 'text-accent' : 'text-text-1',
                                                        )}>
                                                            {name}
                                                        </span>
                                                        <span id={metaId} className="min-w-0 shrink-[4] truncate text-xs text-text-3">
                                                            {workflowRowMeta(workflow)}
                                                        </span>
                                                    </span>
                                                    <span aria-hidden="true" className="inline-flex shrink-0">
                                                        <WorkflowStatusChip workflow={workflow} compact />
                                                    </span>
                                                </button>
                                            </li>
                                        );
                                    })}
                                </ul>
                            ) : (
                                <div className="space-y-2 px-3 py-6">
                                    <p className="text-sm font-medium text-text-1">
                                        {workflowFiltersApplied(filters) ? 'No workflows match these filters' : 'No workflows match your search'}
                                    </p>
                                    <p className="text-[0.8125rem] leading-relaxed text-text-3">
                                        Try another name or description, or clear the filters.
                                    </p>
                                    <GlassButton type="button" size="sm" variant="subtle" onClick={clearFilters}>Clear filters</GlassButton>
                                </div>
                            )}
                        </div>

                        <div className="@container min-h-0 min-w-0 @3xl:overflow-y-auto">
                            {loading && !items.length ? (
                                <div className="space-y-3 p-5" aria-hidden="true">
                                    <Skeleton className="h-7 w-2/3" />
                                    <Skeleton className="h-4 w-1/3" />
                                    <Skeleton className="h-32 w-full" />
                                </div>
                            ) : selected ? (
                                <WorkflowWorkbenchDetail
                                    key={`${scopeKey}:${selected.id}`}
                                    scope={scope}
                                    workflow={selected}
                                    tab={tab}
                                    onTabChange={setTab}
                                    headingRef={detailHeadingRef}
                                    permissions={{ canRun, canCancel, canEdit, canDelete }}
                                    busy={busyId === selected.id}
                                    actionError={actionError && actionError.workflowId === selected.id ? actionError.message : null}
                                    historyRefreshToken={historyRefreshToken}
                                    linkedRun={linkedRun?.scopeKey === scopeKey && linkedRun.workflowId === selected.id ? linkedRun : null}
                                    onRun={() => void onRun(selected)}
                                    onCancel={() => void onCancel(selected)}
                                    onEdit={() => openEditor(selected)}
                                    onDelete={() => void onDelete(selected)}
                                    onWorkflowRefresh={() => void refresh()}
                                />
                            ) : (
                                <div className="flex h-full min-h-[12rem] flex-col items-center justify-center px-6 py-10 text-center">
                                    <p className="text-sm font-medium text-text-1">No workflow selected</p>
                                    <p className="mt-1 max-w-sm text-[0.8125rem] leading-relaxed text-text-3">
                                        Select a workflow to see where it stands, run it, and read its runs.
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            ) : null}
        </fieldset>
    );
}
