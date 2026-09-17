// WorkflowsSection.tsx
// Personal and group workflows: list, author, run, cancel, inspect history and delete.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Ban, ChevronDown, ChevronRight, Edit3, Play, Plus, Trash2, Workflow } from 'lucide-react';
import { WorkflowEditorDialog } from '../../components/workflows/WorkflowEditorDialog';
import { WorkflowRunHistory } from '../../components/workflows/WorkflowRunHistory';
import {
    ConfirmAction,
    Pill,
    ResourceRow,
    RowAction,
    SectionIntro,
    SectionList,
    SectionSearch,
} from '../../components/workspace/primitives';
import {
    errorMessage,
    useSectionResource,
} from '../../components/workspace/useSectionResource';
import {
    cancelScopedWorkflow,
    DEFAULT_WORKFLOW_SCOPE,
    deleteScopedWorkflow,
    fetchScopedWorkflows,
    fetchWorkflowEditorOptions,
    startScopedWorkflowRun,
    workflowErrorMessage,
    workflowScopeKey,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowRunStartResponse,
    type WorkflowScope,
} from '../../lib/workflowEditor';

/** Map a run or workflow status onto a pill colour. */
export function statusTone(status: unknown): 'ok' | 'warn' | 'danger' | 'neutral' {
    const value = String(status ?? '').toLowerCase();
    if (['completed', 'succeeded', 'success', 'finished'].includes(value)) {
        return 'ok';
    }
    if (['running', 'queued', 'pending', 'in_progress', 'started', 'completed_partial'].includes(value)) {
        return 'warn';
    }
    if (['failed', 'error', 'cancelled', 'canceled'].includes(value)) {
        return 'danger';
    }
    return 'neutral';
}

export function WorkflowsSection({
    scope = DEFAULT_WORKFLOW_SCOPE,
    onDirtyChange,
}: {
    scope?: WorkflowScope;
    onDirtyChange?: (dirty: boolean) => void;
}) {
    const scopeKey = workflowScopeKey(scope);
    const loadWorkflows = useCallback((signal?: AbortSignal) => fetchScopedWorkflows(scope, signal), [scopeKey]);
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkflowDefinition>(loadWorkflows, 'Failed to load workflows.');

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [expandedId, setExpandedId] = useState<string | null>(null);
    const [historyRefreshToken, setHistoryRefreshToken] = useState(0);
    const [editing, setEditing] = useState<WorkflowDefinition | null | 'new'>(null);
    const [options, setOptions] = useState<WorkflowEditorOptions | null>(null);
    const [optionsLoading, setOptionsLoading] = useState(false);
    const [optionsError, setOptionsError] = useState('');
    const [editorDirty, setEditorDirty] = useState(false);
    const consumedInitialTargets = useRef(new Set<string>());

    useEffect(() => {
        onDirtyChange?.(editorDirty);
        return () => onDirtyChange?.(false);
    }, [editorDirty, onDirtyChange]);

    const visible = useMemo(() => {
        const needle = query.trim().toLowerCase();
        if (!needle) {
            return items;
        }
        return items.filter((workflow) =>
            `${workflow.name ?? ''} ${workflow.description ?? ''}`
                .toLowerCase()
                .includes(needle),
        );
    }, [items, query]);

    const openEditor = useCallback(async (workflow: WorkflowDefinition | 'new') => {
        if (workflow !== 'new' && workflow.active_run_id) {
            setOptionsError('This workflow has an active run. Cancel it or wait for it to finish before editing.');
            return;
        }
        setOptionsLoading(true);
        setOptionsError('');
        try {
            setOptions(await fetchWorkflowEditorOptions(scope));
            setEditing(workflow);
        } catch (cause) {
            setOptionsError(workflowErrorMessage(cause, 'Could not load workflow editor options.'));
        } finally {
            setOptionsLoading(false);
        }
    }, [scopeKey]);

    useEffect(() => {
        const target = new URLSearchParams(window.location.search).get('workflow_id');
        if (!target || loading || editing || optionsLoading || consumedInitialTargets.current.has(target)) {
            return;
        }
        const workflow = items.find((item) => item.id === target);
        if (workflow) {
            consumedInitialTargets.current.add(target);
            void openEditor(workflow);
        }
    }, [editing, items, loading, openEditor, optionsLoading]);

    const runAction = async (
        workflow: WorkflowDefinition,
        action: (id: string) => Promise<unknown>,
        failure: string,
    ) => {
        if (!workflow.id) {
            setError('This workflow has no stable identifier. Reload before trying again.');
            return;
        }
        setBusyId(workflow.id);
        setError(null);
        try {
            await action(workflow.id);
            await refresh();
        } catch (actionError) {
            setExpandedId(workflow.id);
            await refresh();
            setError(errorMessage(actionError, failure));
        } finally {
            setHistoryRefreshToken((value) => value + 1);
            setBusyId(null);
        }
    };

    const onRun = async (workflow: WorkflowDefinition) => {
        if (!workflow.id) {
            setError('This workflow has no stable identifier. Reload before trying again.');
            return;
        }
        setBusyId(workflow.id);
        setError(null);
        setExpandedId(workflow.id);
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
        } catch (actionError) {
            setExpandedId(workflow.id);
            await refresh();
            setError(errorMessage(actionError, 'Could not start the workflow.'));
        } finally {
            setHistoryRefreshToken((value) => value + 1);
            setBusyId(null);
        }
    };

    const onDelete = async (workflow: WorkflowDefinition) => {
        const previous = items;
        if (!workflow.id) {
            return;
        }
        setBusyId(workflow.id);
        setItems(items.filter((item) => item.id !== workflow.id));
        try {
            await deleteScopedWorkflow(scope, workflow.id);
        } catch (deleteError) {
            setItems(previous);
            setError(errorMessage(deleteError, 'Could not delete the workflow.'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="space-y-4">
            <SectionIntro
                title="Workflows"
                description="Repeatable tasks that run on their own, using a model or one of your agents. A workflow can run on a schedule or whenever you start it."
                actions={
                    <GlassCreateButton
                        busy={optionsLoading}
                        onClick={() => void openEditor('new')}
                    />
                }
            />

            <p className="text-xs text-text-3">
                Native V2 authoring is available for manual and interval workflows. File sync,
                alert and publication settings from existing workflows are preserved unchanged.
            </p>
            {scope.type === 'group' ? (
                <p className="text-xs text-text-3">Requests are scoped to group_id {scope.groupId}; selecting this page does not change your active group.</p>
            ) : null}
            {optionsError ? <p role="alert" className="text-sm text-danger">{optionsError}</p> : null}

            <SectionSearch value={query} onChange={setQuery} placeholder="Search workflows" />

            <SectionList
                items={visible}
                loading={loading}
                error={error}
                emptyIcon={<Workflow size={28} />}
                emptyTitle={
                    items.length === 0 ? 'No workflows yet' : 'No workflows match your search'
                }
                emptyDescription={
                    items.length === 0
                        ? 'A workflow repeats a task you would otherwise run by hand.'
                        : undefined
                }
                emptyAction={<GlassCreateButton busy={optionsLoading} onClick={() => void openEditor('new')} />}
                getKey={(workflow, index) => String(workflow.id ?? index)}
                renderItem={(workflow) => {
                    const running = Boolean(workflow.active_run_id);
                    const workflowId = workflow.id ?? '';
                    const expanded = expandedId === workflowId;
                    return (
                        <div>
                            <ResourceRow
                                icon={<Workflow size={17} />}
                                title={String(workflow.name ?? 'Untitled workflow')}
                                subtitle={String(workflow.description ?? '')}
                                meta={
                                    workflow.status ? (
                                        <Pill tone={statusTone(workflow.status)}>
                                            {String(workflow.status)}
                                        </Pill>
                                    ) : undefined
                                }
                                actions={
                                    <>
                                        <RowAction
                                            icon={<Edit3 size={15} />}
                                            label={running ? `${workflow.name || 'Workflow'} is running; cancel or wait before editing` : `Edit ${workflow.name || 'workflow'}`}
                                            disabled={optionsLoading || running}
                                            busy={optionsLoading && editing === workflow}
                                            onClick={() => void openEditor(workflow)}
                                        />
                                        <RowAction
                                            icon={
                                                expanded ? (
                                                    <ChevronDown size={15} />
                                                ) : (
                                                    <ChevronRight size={15} />
                                                )
                                            }
                                            label={
                                                expanded
                                                    ? 'Hide run history'
                                                    : 'Show run history'
                                            }
                                            onClick={() =>
                                                setExpandedId(expanded ? null : workflowId)
                                            }
                                            disabled={!workflowId}
                                        />
                                        {running ? (
                                            <RowAction
                                                icon={<Ban size={15} />}
                                                label={`Cancel ${workflow.name ?? 'workflow'}`}
                                                busy={busyId === workflow.id}
                                                onClick={() =>
                                                    void runAction(
                                                        workflow,
                                                        (id) => cancelScopedWorkflow(scope, id),
                                                        'Could not cancel the workflow.',
                                                    )
                                                }
                                            />
                                        ) : (
                                            <RowAction
                                                icon={<Play size={15} />}
                                                label={`Run ${workflow.name ?? 'workflow'}`}
                                                busy={busyId === workflow.id}
                                                onClick={() => void onRun(workflow)}
                                            />
                                        )}
                                        <ConfirmAction
                                            icon={<Trash2 size={15} />}
                                            label={`Delete ${workflow.name ?? 'workflow'}`}
                                            confirmLabel="Delete"
                                            busy={busyId === workflow.id}
                                            onConfirm={() => void onDelete(workflow)}
                                        />
                                    </>
                                }
                            />
                            {expanded && workflowId ? (
                                <WorkflowRunHistory
                                    key={workflowId}
                                    scope={scope}
                                    workflowId={workflowId}
                                    refreshToken={historyRefreshToken}
                                    onWorkflowRefresh={() => void refresh()}
                                />
                            ) : null}
                        </div>
                    );
                }}
            />
            {editing && options ? (
                <WorkflowEditorDialog
                    key={`${scopeKey}:${editing === 'new' ? 'new' : editing.id}`}
                    scope={scope}
                    workflow={editing === 'new' ? null : editing}
                    options={options}
                    onDirtyChange={setEditorDirty}
                    onClose={() => {
                        setEditing(null);
                        setEditorDirty(false);
                    }}
                    onSaved={(workflow) => {
                        const index = items.findIndex((item) => item.id === workflow.id);
                        setItems(index < 0
                            ? [workflow, ...items]
                            : items.map((item, itemIndex) => itemIndex === index ? workflow : item));
                        setEditing(null);
                        setEditorDirty(false);
                        void refresh();
                    }}
                />
            ) : null}
        </div>
    );
}

function GlassCreateButton({ busy, onClick }: { busy: boolean; onClick: () => void }) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={busy}
            className="inline-flex h-8 items-center gap-1.5 rounded-xl bg-accent px-3 text-sm font-medium text-on-accent shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
            <Plus size={14} />
            {busy ? 'Loading…' : 'Create workflow'}
        </button>
    );
}
