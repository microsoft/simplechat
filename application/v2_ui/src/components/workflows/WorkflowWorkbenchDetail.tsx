// WorkflowWorkbenchDetail.tsx
// The selected workflow in the Workflows workbench: what it is, what it can do now, and its runs.
//
// Drawn the way Admin's Model Catalog draws a selected profile: a header with the name, a few
// chips and the actions, then tabs that each scroll inside the pane. Overview is a list of facts
// in the Admin field layout; Runs is the run history, unchanged inside; Flow is the saved
// structured definition, for workflows that have one.

import { useId, useRef, type KeyboardEvent, type RefObject } from 'react';
import { clsx } from 'clsx';
import { Ban, Eye, GitBranch, Loader2, Pencil, Play, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { ConfirmAction, Pill } from '../workspace/primitives';
import { WorkflowFlowView } from './WorkflowFlowView';
import { WorkflowRunHistory } from './WorkflowRunHistory';
import { WorkflowStatusChip } from './WorkflowStatusChip';
import { workflowScopeKey, type WorkflowDefinition, type WorkflowScope } from '../../lib/workflowEditor';
import { workflowDetailMeta, workflowOverviewFacts } from '../../lib/workflowWorkbench';

export type WorkflowDetailTab = 'overview' | 'runs' | 'flow';

const TAB_LABELS: Record<WorkflowDetailTab, string> = {
    overview: 'Overview',
    runs: 'Runs',
    flow: 'Flow',
};

/** The tabs a workflow offers: Flow belongs to structured (definition 3) workflows only. */
export function workflowDetailTabs(workflow: WorkflowDefinition): WorkflowDetailTab[] {
    return workflow.definition_version === 3 ? ['overview', 'runs', 'flow'] : ['overview', 'runs'];
}

export interface WorkflowDetailPermissions {
    canRun: boolean;
    canCancel: boolean;
    canEdit: boolean;
    canDelete: boolean;
}

export function WorkflowWorkbenchDetail({
    scope,
    workflow,
    tab,
    onTabChange,
    headingRef,
    permissions,
    busy,
    actionError,
    historyRefreshToken,
    linkedRun,
    onRun,
    onCancel,
    onEdit,
    onDelete,
    onWorkflowRefresh,
}: {
    scope: WorkflowScope;
    workflow: WorkflowDefinition;
    tab: WorkflowDetailTab;
    onTabChange: (tab: WorkflowDetailTab) => void;
    headingRef: RefObject<HTMLHeadingElement>;
    permissions: WorkflowDetailPermissions;
    /** A run, cancel or delete request for this workflow is in flight. */
    busy: boolean;
    actionError: string | null;
    historyRefreshToken: number;
    /** A run a link named, expanded in Runs; `navigation` remounts the history for each new link. */
    linkedRun: { runId: string; navigation: string } | null;
    onRun: () => void;
    onCancel: () => void;
    onEdit: () => void;
    onDelete: () => void;
    onWorkflowRefresh: () => void;
}) {
    const baseId = useId();
    const titleId = `${baseId}-title`;
    const tabs = workflowDetailTabs(workflow);
    const shown = tabs.includes(tab) ? tab : 'overview';
    const tabRefs = useRef<Partial<Record<WorkflowDetailTab, HTMLButtonElement | null>>>({});
    const workflowId = workflow.id ?? '';
    const activeRun = Boolean(workflow.active_run_id);
    const name = String(workflow.name ?? '');
    const description = String(workflow.description ?? '');
    const scopeKey = workflowScopeKey(scope);

    const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const index = tabs.indexOf(shown);
        const next = event.key === 'Home' ? 0
            : event.key === 'End' ? tabs.length - 1
                : event.key === 'ArrowRight' ? (index + 1) % tabs.length
                    : (index - 1 + tabs.length) % tabs.length;
        onTabChange(tabs[next]);
        tabRefs.current[tabs[next]]?.focus();
    };

    return (
        <article aria-labelledby={titleId} data-workflow-detail={workflowId} className="flex min-h-full flex-col">
            <header className="px-4 pt-4 pb-3 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 basis-56">
                        <h3 id={titleId} ref={headingRef} tabIndex={-1}
                            className="text-xl leading-snug font-semibold break-words text-text-1">
                            {name || 'Untitled workflow'}
                        </h3>
                        <p className="mt-1 text-xs text-text-3">{workflowDetailMeta(workflow)}</p>
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            <WorkflowStatusChip workflow={workflow} />
                            {workflow.definition_version === 3 ? <Pill tone="accent">Structured</Pill> : null}
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {activeRun ? (permissions.canCancel ? (
                            <GlassButton type="button" variant="subtle" size="sm" disabled={busy || !workflowId}
                                aria-label={`Cancel ${workflow.name ?? 'workflow'}`} title="Cancel the active run"
                                onClick={onCancel}>
                                {busy ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : <Ban size={14} aria-hidden="true" />}
                                Cancel
                            </GlassButton>
                        ) : null) : permissions.canRun ? (
                            <GlassButton type="button" variant="primary" size="sm" disabled={busy || !workflowId}
                                aria-label={`Run ${workflow.name ?? 'workflow'}`} onClick={onRun}>
                                {busy ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : <Play size={14} aria-hidden="true" />}
                                Run
                            </GlassButton>
                        ) : null}
                        <GlassButton type="button" variant="subtle" size="sm" disabled={activeRun || !workflowId}
                            aria-label={!permissions.canEdit ? `View ${workflow.name || 'workflow'}`
                                : activeRun ? `${workflow.name || 'Workflow'} is running; cancel or wait before editing`
                                    : `Edit ${workflow.name || 'workflow'}`}
                            title={activeRun ? 'Cancel the run or wait for it to finish before editing' : undefined}
                            onClick={onEdit}>
                            {permissions.canEdit ? <Pencil size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
                            {permissions.canEdit ? 'Edit' : 'View'}
                        </GlassButton>
                        {permissions.canDelete ? (
                            <ConfirmAction
                                icon={<Trash2 size={15} />}
                                label={`Delete ${workflow.name ?? 'workflow'}`}
                                confirmLabel="Delete"
                                busy={busy}
                                disabled={!workflowId}
                                onConfirm={onDelete}
                            />
                        ) : null}
                    </div>
                </div>
                {description ? (
                    <p className="mt-3 max-w-[80ch] text-sm leading-relaxed break-words text-text-2">{description}</p>
                ) : null}
                {actionError ? (
                    <p role="alert" className="mt-3 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
                        {actionError}
                    </p>
                ) : null}
            </header>

            <div role="tablist" aria-label="Workflow details" onKeyDown={onTabKeyDown}
                className="sticky top-0 z-10 flex gap-1 overflow-x-auto border-y border-edge-strong bg-surface-solid px-4 sm:px-5">
                {tabs.map((item) => {
                    const selected = item === shown;
                    return (
                        <button
                            key={item}
                            ref={(element) => {
                                tabRefs.current[item] = element;
                            }}
                            id={`${baseId}-tab-${item}`}
                            type="button"
                            role="tab"
                            aria-selected={selected}
                            aria-controls={`${baseId}-panel`}
                            tabIndex={selected ? 0 : -1}
                            onClick={() => onTabChange(item)}
                            className={clsx(
                                '-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors',
                                selected
                                    ? 'border-accent font-semibold text-accent'
                                    : 'border-transparent text-text-2 hover:text-text-1',
                            )}
                        >
                            {item === 'flow' ? <GitBranch size={13} aria-hidden="true" /> : null}
                            {TAB_LABELS[item]}
                        </button>
                    );
                })}
            </div>

            <div
                id={`${baseId}-panel`}
                role="tabpanel"
                aria-labelledby={`${baseId}-tab-${shown}`}
                tabIndex={0}
                className="flex-1 px-4 py-4 sm:px-5"
            >
                {shown === 'overview' ? (
                    <dl className="divide-y divide-edge-strong" aria-label="Workflow overview">
                        {workflowOverviewFacts(workflow).map((fact) => (
                            <div key={fact.label} className="admin-field admin-field-inline py-2.5" data-field-width="wide">
                                <dt className="admin-field-heading text-sm font-semibold text-text-1">{fact.label}</dt>
                                <dd className="admin-field-control text-sm break-words text-text-2">{fact.value}</dd>
                            </div>
                        ))}
                    </dl>
                ) : null}
                {shown === 'runs' && workflowId ? (
                    <div className="-mx-3">
                        <p className="px-3 pb-3 text-[0.8125rem] leading-relaxed text-text-3">
                            The most recent runs. Expand one to read its task results.
                        </p>
                        <WorkflowRunHistory
                            // Following a run link again remounts the history: a fresh read, with
                            // the run expanded again even if it was collapsed since.
                            key={`${scopeKey}:${workflowId}:${linkedRun?.navigation ?? ''}`}
                            scope={scope}
                            workflowId={workflowId}
                            refreshToken={historyRefreshToken}
                            initialRunId={linkedRun?.runId ?? null}
                            onWorkflowRefresh={onWorkflowRefresh}
                        />
                    </div>
                ) : null}
                {shown === 'flow' && workflowId ? (
                    <div className="space-y-3">
                        <p className="text-[0.8125rem] leading-relaxed text-text-3">
                            The current saved structured definition, read without editing it.
                        </p>
                        <WorkflowFlowView key={`${scopeKey}:${workflowId}`} scope={scope}
                            target={{ kind: 'saved', workflowId }} />
                    </div>
                ) : null}
            </div>
        </article>
    );
}
