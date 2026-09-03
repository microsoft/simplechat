// WorkflowsSection.tsx
// Personal workflows: list, run, cancel, inspect run history and delete.
//
// Designing a workflow -- its tasks, document actions and schedule -- stays in the classic
// interface for now. What is here is the part you return to repeatedly: seeing what ran,
// starting a run, and stopping one that should not continue.

import { useMemo, useState } from 'react';
import { Ban, ChevronDown, ChevronRight, Play, Trash2, Workflow } from 'lucide-react';
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
    cancelWorkflow,
    deleteWorkflow,
    fetchWorkflowRuns,
    fetchWorkflows,
    startWorkflowRun,
} from '../../lib/workspaceApi';
import type { WorkspaceWorkflow, WorkspaceWorkflowRun } from '../../lib/types';

/** Map a run or workflow status onto a pill colour. */
export function statusTone(status: unknown): 'ok' | 'warn' | 'danger' | 'neutral' {
    const value = String(status ?? '').toLowerCase();
    if (['completed', 'succeeded', 'success', 'finished'].includes(value)) {
        return 'ok';
    }
    if (['running', 'queued', 'pending', 'in_progress', 'started'].includes(value)) {
        return 'warn';
    }
    if (['failed', 'error', 'cancelled', 'canceled'].includes(value)) {
        return 'danger';
    }
    return 'neutral';
}

function formatTimestamp(value: unknown): string {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const parsed = new Date(raw);
    return Number.isNaN(parsed.valueOf()) ? raw : parsed.toLocaleString();
}

function RunHistory({ workflowId }: { workflowId: string }) {
    const { items, loading, error } = useSectionResource<WorkspaceWorkflowRun>(
        (signal) => fetchWorkflowRuns(workflowId, signal),
        'Failed to load run history.',
    );

    if (loading) {
        return <p className="px-3 pb-3 text-xs text-text-3">Loading runs…</p>;
    }
    if (error) {
        return <p className="px-3 pb-3 text-xs text-danger">{error}</p>;
    }
    if (items.length === 0) {
        return <p className="px-3 pb-3 text-xs text-text-3">This workflow has not run yet.</p>;
    }

    return (
        <ul className="space-y-1 px-3 pb-3">
            {items.slice(0, 10).map((run) => (
                <li key={run.id} className="flex items-center gap-2 text-xs text-text-3">
                    <Pill tone={statusTone(run.status)}>{String(run.status ?? 'unknown')}</Pill>
                    <span className="truncate">
                        {formatTimestamp(run.started_at) || 'Not started'}
                        {run.completed_at ? ` → ${formatTimestamp(run.completed_at)}` : ''}
                    </span>
                </li>
            ))}
        </ul>
    );
}

export function WorkflowsSection() {
    const { items, loading, error, refresh, setItems, setError } =
        useSectionResource<WorkspaceWorkflow>(fetchWorkflows, 'Failed to load workflows.');

    const [query, setQuery] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [expandedId, setExpandedId] = useState<string | null>(null);

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

    const runAction = async (
        workflow: WorkspaceWorkflow,
        action: (id: string) => Promise<unknown>,
        failure: string,
    ) => {
        setBusyId(workflow.id);
        setError(null);
        try {
            await action(workflow.id);
            await refresh();
        } catch (actionError) {
            setError(errorMessage(actionError, failure));
        } finally {
            setBusyId(null);
        }
    };

    const onDelete = async (workflow: WorkspaceWorkflow) => {
        const previous = items;
        setBusyId(workflow.id);
        setItems(items.filter((item) => item.id !== workflow.id));
        try {
            await deleteWorkflow(workflow.id);
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
            />

            <p className="text-xs text-text-3">
                Designing a workflow is still done in the{' '}
                <a href="/workspace" className="text-accent hover:underline">
                    classic workspace
                </a>
                .
            </p>

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
                getKey={(workflow, index) => String(workflow.id ?? index)}
                renderItem={(workflow) => {
                    const running = Boolean(workflow.active_run_id);
                    const expanded = expandedId === workflow.id;
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
                                                setExpandedId(expanded ? null : workflow.id)
                                            }
                                        />
                                        {running ? (
                                            <RowAction
                                                icon={<Ban size={15} />}
                                                label={`Cancel ${workflow.name ?? 'workflow'}`}
                                                busy={busyId === workflow.id}
                                                onClick={() =>
                                                    void runAction(
                                                        workflow,
                                                        cancelWorkflow,
                                                        'Could not cancel the workflow.',
                                                    )
                                                }
                                            />
                                        ) : (
                                            <RowAction
                                                icon={<Play size={15} />}
                                                label={`Run ${workflow.name ?? 'workflow'}`}
                                                busy={busyId === workflow.id}
                                                onClick={() =>
                                                    void runAction(
                                                        workflow,
                                                        startWorkflowRun,
                                                        'Could not start the workflow.',
                                                    )
                                                }
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
                            {expanded ? <RunHistory workflowId={workflow.id} /> : null}
                        </div>
                    );
                }}
            />
        </div>
    );
}
