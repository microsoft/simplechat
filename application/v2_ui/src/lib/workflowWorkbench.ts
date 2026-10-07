// workflowWorkbench.ts
// What the Workflows workbench says about each workflow, and which workflows its filters keep.
//
// The workbench lists every workflow in a workspace as a one-line row beside a detail pane, the
// way Admin's Model Catalog lists profiles. These are the decisions it makes about each row --
// how a status reads, whether a workflow needs attention, what the Overview lists -- kept apart
// from the component so they run in a test. Everything here reads the workflow record the list
// API returns; nothing is inferred beyond it.

import { workflowFileSyncConfig, workflowScheduleLabel, type WorkflowDefinition } from './workflowEditor';
import {
    workflowAlertsSummary,
    workflowExecutionSummary,
    workflowFileSyncSummary,
    workflowTriggerSummary,
} from './workflowEditorSections';

export type WorkflowStatusTone = 'ok' | 'warn' | 'danger' | 'neutral';

/** Map a run or workflow status onto a tone. */
export function workflowStatusTone(status: unknown): WorkflowStatusTone {
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

/** Readable names for the statuses whose stored spelling would not read as a sentence. */
const STATUS_LABELS: Readonly<Record<string, string>> = {
    completed: 'Completed',
    succeeded: 'Completed',
    success: 'Completed',
    finished: 'Completed',
    completed_partial: 'Completed with task errors',
    running: 'Running',
    started: 'Running',
    in_progress: 'Running',
    queued: 'Queued',
    pending: 'Queued',
    cancelling: 'Cancelling',
    failed: 'Failed',
    error: 'Failed',
    cancelled: 'Cancelled',
    canceled: 'Cancelled',
};

/** A stored status as words, such as `awaiting_approval` as "Awaiting approval". */
export function workflowStatusLabel(status: unknown): string {
    const value = String(status ?? '').trim();
    if (!value) return '';
    const known = STATUS_LABELS[value.toLowerCase()];
    if (known) return known;
    const words = value.replace(/[_-]+/g, ' ').trim().toLowerCase();
    return words ? `${words[0].toUpperCase()}${words.slice(1)}` : '';
}

const IN_PROGRESS_STATUSES = ['running', 'queued', 'pending', 'in_progress', 'started', 'cancelling'];
/** A run paused until a person acts on it: an approval, a sign-in, a decision. */
const WAITING_STATUS = /^(awaiting|waiting)_/;

function normalizedStatus(value: unknown): string {
    return String(value ?? '').trim().toLowerCase();
}

/**
 * How the latest finished run ended, or '' when nothing says. The server keeps a workflow's
 * `status` for the run in progress -- running, or waiting on a person -- and sets it back to idle
 * when the run ends, recording the outcome in `last_run_status`. An older record may still hold
 * the outcome in `status` itself.
 */
export function workflowLastOutcome(workflow: WorkflowDefinition): string {
    const last = normalizedStatus(workflow.last_run_status);
    if (last) return last;
    const status = normalizedStatus(workflow.status);
    return status && status !== 'idle' && !IN_PROGRESS_STATUSES.includes(status) && !WAITING_STATUS.test(status)
        ? status : '';
}

/**
 * What a workflow's chip says: the run in progress when there is one, else how the last run
 * ended. Null when the record says neither, rather than guessing that it has never run.
 */
export function workflowRunState(workflow: WorkflowDefinition): { label: string; tone: WorkflowStatusTone; status: string } | null {
    const status = normalizedStatus(workflow.status);
    if (WAITING_STATUS.test(status)) {
        return { label: workflowStatusLabel(status), tone: 'warn', status };
    }
    if (workflow.active_run_id || IN_PROGRESS_STATUSES.includes(status)) {
        // The stored status can still describe the previous run, so only an in-progress one names this run.
        return IN_PROGRESS_STATUSES.includes(status)
            ? { label: workflowStatusLabel(status), tone: 'warn', status }
            : { label: 'Running', tone: 'warn', status: 'running' };
    }
    const outcome = workflowLastOutcome(workflow);
    return outcome ? { label: workflowStatusLabel(outcome), tone: workflowStatusTone(outcome), status: outcome } : null;
}

export function workflowIsRunning(workflow: WorkflowDefinition): boolean {
    const status = normalizedStatus(workflow.status);
    return Boolean(workflow.active_run_id) || IN_PROGRESS_STATUSES.includes(status) || WAITING_STATUS.test(status);
}

/**
 * A workflow waiting on a person, or whose last run failed, was cancelled or completed with task
 * errors and that is not running again.
 */
export function workflowNeedsAttention(workflow: WorkflowDefinition): boolean {
    if (WAITING_STATUS.test(normalizedStatus(workflow.status))) return true;
    if (workflowIsRunning(workflow)) return false;
    const outcome = workflowLastOutcome(workflow);
    return outcome === 'completed_partial' || workflowStatusTone(outcome) === 'danger';
}

export type WorkflowStatusFilter = 'all' | 'running' | 'attention' | 'completed' | 'disabled';
export type WorkflowTriggerFilter = 'all' | 'manual' | 'interval' | 'file_sync';

export interface WorkflowWorkbenchFilters {
    query: string;
    status: WorkflowStatusFilter;
    trigger: WorkflowTriggerFilter;
}

export const DEFAULT_WORKFLOW_WORKBENCH_FILTERS: WorkflowWorkbenchFilters = {
    query: '',
    status: 'all',
    trigger: 'all',
};

export const WORKFLOW_STATUS_FILTER_LABELS: Readonly<Record<WorkflowStatusFilter, string>> = {
    all: 'All statuses',
    running: 'Running',
    attention: 'Needs attention',
    completed: 'Completed',
    disabled: 'Disabled',
};

export const WORKFLOW_TRIGGER_LABELS: Readonly<Record<Exclude<WorkflowTriggerFilter, 'all'>, string>> = {
    manual: 'Manual',
    interval: 'Schedule',
    file_sync: 'Monitor File Sync changes',
};

export const WORKFLOW_TRIGGER_FILTER_LABELS: Readonly<Record<WorkflowTriggerFilter, string>> = {
    all: 'All triggers',
    ...WORKFLOW_TRIGGER_LABELS,
};

/** How many filters other than the search narrow the list. */
export function workflowFiltersApplied(filters: WorkflowWorkbenchFilters): number {
    return Number(filters.status !== 'all') + Number(filters.trigger !== 'all');
}

/** The workflows a search and the filters keep, in the list's order. */
export function filterWorkflows(items: readonly WorkflowDefinition[], filters: WorkflowWorkbenchFilters): WorkflowDefinition[] {
    const needle = filters.query.trim().toLowerCase();
    return items.filter((workflow) => {
        if (needle && !`${workflow.name ?? ''} ${workflow.description ?? ''}`.toLowerCase().includes(needle)) {
            return false;
        }
        if (filters.trigger !== 'all' && workflow.trigger_type !== filters.trigger) {
            return false;
        }
        switch (filters.status) {
            case 'running':
                return workflowIsRunning(workflow);
            case 'attention':
                return workflowNeedsAttention(workflow);
            case 'completed':
                return !workflowIsRunning(workflow) && workflowStatusTone(workflowLastOutcome(workflow)) === 'ok';
            case 'disabled':
                return workflow.is_enabled === false;
            default:
                return true;
        }
    });
}

/**
 * What a row says beside its name: how the workflow stands, then its trigger in a word or two and
 * whether it is switched off. Whether something ran is what the list is opened for, so the status
 * leads and survives when a narrow row cuts the line short. The detail says it all in full.
 */
export function workflowRowMeta(workflow: WorkflowDefinition): string {
    const trigger = workflow.trigger_type === 'manual'
        ? 'Manual'
        : workflowScheduleLabel(workflow.trigger_type, workflow.schedule)
            || WORKFLOW_TRIGGER_LABELS[workflow.trigger_type === 'file_sync' ? 'file_sync' : 'interval'];
    return [workflowRunState(workflow)?.label, trigger, workflow.is_enabled === false ? 'Disabled' : '']
        .filter(Boolean).join(' · ');
}

/** The detail's line under the title: when it runs, in full, and whether it is switched off. */
export function workflowDetailMeta(workflow: WorkflowDefinition): string {
    const trigger = workflowTriggerSummary(workflow);
    return workflow.is_enabled === false ? `${trigger} · Disabled` : trigger;
}

function runnerFact(workflow: WorkflowDefinition): string {
    if (workflow.runner_type === 'agent') {
        const agent = workflow.selected_agent;
        return `Agent · ${agent?.display_name || agent?.name || 'Not selected'}`;
    }
    return `Model · ${workflow.model_id || 'App default model'}`;
}

export interface WorkflowOverviewFact {
    label: string;
    value: string;
}

/** When the last finished run ended and how, in the reader's locale, as the run history shows it. */
function lastRunFact(workflow: WorkflowDefinition): string {
    const outcome = workflowLastOutcome(workflow);
    const raw = String(workflow.last_run_at ?? '').trim();
    const parsed = raw ? new Date(raw) : null;
    const when = parsed && !Number.isNaN(parsed.valueOf()) ? parsed.toLocaleString() : '';
    return [outcome ? workflowStatusLabel(outcome) : '', when].filter(Boolean).join(' · ') || 'Not run yet';
}

/**
 * The facts the Overview tab lists: when it last ran, then its settings in the order the
 * editor's cards present them.
 */
export function workflowOverviewFacts(workflow: WorkflowDefinition): WorkflowOverviewFact[] {
    const references = workflow.reference_inputs.length;
    const tasks = workflow.tasks.length;
    const facts: WorkflowOverviewFact[] = [
        { label: 'Last run', value: lastRunFact(workflow) },
        { label: 'Runner', value: runnerFact(workflow) },
    ];
    if (workflow.m365_run_as_user_id) {
        facts.push({ label: 'Microsoft 365 Run as', value: 'Account selected' });
    }
    facts.push(
        { label: 'Workflow enabled', value: workflow.is_enabled === false ? 'Off' : 'On' },
        { label: 'Trigger and schedule', value: workflowTriggerSummary(workflow) },
        {
            label: 'File Sync',
            value: workflowFileSyncConfig(workflow.file_sync).enabled || workflow.trigger_type === 'file_sync'
                ? workflowFileSyncSummary(workflow) : 'Off',
        },
        { label: 'Execution', value: workflowExecutionSummary(workflow) },
        {
            label: 'Shared references',
            value: references ? `${references} ${references === 1 ? 'document' : 'documents'}` : 'None',
        },
        {
            label: workflow.definition_version === 3 ? 'Structured tasks' : 'Tasks',
            value: `${tasks} ${tasks === 1 ? 'task' : 'tasks'}`,
        },
        { label: 'Alerts', value: workflowAlertsSummary(workflow) },
    );
    return facts;
}
