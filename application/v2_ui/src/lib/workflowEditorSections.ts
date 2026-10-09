// workflowEditorSections.ts
// The workflow editor's cards: which ones a draft shows, and how each reads at a glance.
//
// Kept apart from the editor component for the reason Admin keeps `adminSections.ts` apart from
// its card: whether a card reads as configured, off, or needing attention is easy to get subtly
// wrong and invisible in a screenshot, so it is executed in a test rather than reviewed by eye.
//
// A card's status is guidance only. It never blocks a save -- the editor's validation still
// decides that, and its messages stay listed above the cards -- and it only reports what the
// draft and the editor options already say. The vocabulary is Admin's (`SectionStatus` and its
// presentation), so "Needs configuration" means the same thing on both surfaces.

import type { SectionStatus } from './adminSections';
import {
    workflowAlertConfig,
    workflowAlertRuleErrors,
    WORKFLOW_ALERT_MODE_LABELS,
    type WorkflowAlertMode,
    type WorkflowAlertScope,
} from './workflowAlerts';
import { DEFAULT_FLOW_LIMITS, isLegacyWorkflowBinding } from './workflowFlow';
import { isRecord } from './workspaceAuthoring';
import {
    workflowAgentKey,
    workflowFileSyncConfig,
    workflowPlanReplayTask,
    workflowScheduleLabel,
    WORKFLOW_TASK_INSTRUCTIONS_LIMIT,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowTask,
} from './workflowEditor';

export type WorkflowEditorSectionId =
    | 'basics'
    | 'trigger'
    | 'file-sync'
    | 'execution'
    | 'references'
    | 'limits'
    | 'tasks'
    | 'alerts';

export const WORKFLOW_EDITOR_SECTION_LABELS: Readonly<Record<WorkflowEditorSectionId, string>> = {
    basics: 'Basics',
    trigger: 'Trigger and schedule',
    'file-sync': 'File Sync',
    execution: 'Execution',
    references: 'Shared references',
    limits: 'Limits',
    tasks: 'Tasks',
    alerts: 'Alerts',
};

export interface WorkflowEditorSection {
    id: WorkflowEditorSectionId;
    label: string;
    status: SectionStatus;
    /** One line of facts for the card header. */
    meta: string;
}

export interface WorkflowEditorSectionContext {
    options: Pick<WorkflowEditorOptions, 'agents' | 'models' | 'default_model' | 'schedule'>;
    /** The workspace the workflow belongs to; alert rules are checked against its rules. */
    scopeType: WorkflowAlertScope;
    /** The group File Sync gate once the group's source list has loaded; null when unknown. */
    groupFileSyncEnabled?: boolean | null;
    /** Which surface a structured draft is being edited on, for the task card's title. */
    structuredSurface?: 'list' | 'flow';
    /** The time zones the editor offers, for a calendar schedule's label. */
    scheduleTimezones?: ReadonlySet<string> | null;
}

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`;
}

/**
 * Problems one task shows on itself: inputs that point at a missing or later task, a reference to
 * a removed shared document, and instructions over the authoring limit.
 */
export function workflowTaskValidationErrors(
    task: WorkflowTask,
    index: number,
    tasks: WorkflowTask[],
    workflow: WorkflowDefinition,
): string[] {
    const errors: string[] = [];
    const indexes = new Map(tasks.map((item, position) => [item.id, position]));
    for (const input of task.inputs ?? []) {
        if (workflow.definition_version === 3 || !isLegacyWorkflowBinding(input)) continue;
        const producer = indexes.get(input.task_id);
        if (producer === undefined) {
            errors.push(`${input.name || 'Input'} points to a missing task.`);
        } else if (producer >= index) {
            errors.push(`${input.name || 'Input'} points to a later task.`);
        }
    }
    for (const referenceId of task.reference_ids ?? []) {
        if (!workflow.reference_inputs.some((reference) => reference.id === referenceId)) {
            errors.push('This task references a removed shared document.');
        }
    }
    if (task.instructions.length > WORKFLOW_TASK_INSTRUCTIONS_LIMIT) {
        errors.push('Instructions exceed the workflow authoring limit.');
    }
    return errors;
}

/** The runner a workflow's tasks inherit: the chosen agent, the chosen model, or the app default. */
export function workflowRunnerSummary(
    workflow: WorkflowDefinition,
    options: Pick<WorkflowEditorOptions, 'agents' | 'models'>,
): string {
    if (workflow.runner_type === 'agent') {
        const agent = options.agents.find((item) => workflowAgentKey(item) === workflowAgentKey(workflow.selected_agent));
        return agent?.display_name || agent?.name || 'Agent not selected';
    }
    const model = options.models.find((item) =>
        item.endpoint_id === workflow.model_endpoint_id && item.model_id === workflow.model_id);
    return model?.label || 'App default model';
}

/** Whether File Sync runs for this draft: chosen before each run, or required by the Monitor trigger. */
export function workflowFileSyncInUse(workflow: WorkflowDefinition): boolean {
    return workflow.trigger_type === 'file_sync' || workflowFileSyncConfig(workflow.file_sync).enabled;
}

/** Whether, and how, a workflow syncs files: off, or its sources and when they sync. */
export function workflowFileSyncSummary(workflow: WorkflowDefinition): string {
    if (!workflowFileSyncInUse(workflow)) return 'Runs without syncing first';
    const sources = plural(workflowFileSyncConfig(workflow.file_sync).sources.length, 'source', 'sources');
    return `${sources}${workflow.trigger_type === 'file_sync' ? ' · checked for changes' : ' · synced before each run'}`;
}

/** How many tasks currently show at least one problem of their own. */
export function workflowTasksNeedingAttention(workflow: WorkflowDefinition): number {
    return workflow.tasks.filter((task, index) =>
        workflowTaskValidationErrors(task, index, workflow.tasks, workflow).length > 0).length;
}

function basicsStatus(workflow: WorkflowDefinition, context: WorkflowEditorSectionContext): SectionStatus {
    if (!workflow.name.trim()) return 'incomplete';
    if (workflowPlanReplayTask(workflow)) return 'ready';
    if (workflow.runner_type === 'agent') return workflow.selected_agent ? 'ready' : 'incomplete';
    const explicitModel = Boolean(workflow.model_endpoint_id || workflow.model_id);
    return !explicitModel && context.options.default_model?.valid === false ? 'incomplete' : 'ready';
}

function fileSyncStatus(workflow: WorkflowDefinition, context: WorkflowEditorSectionContext): SectionStatus {
    if (!workflowFileSyncInUse(workflow)) return 'off';
    if (context.groupFileSyncEnabled === false) return 'blocked';
    return workflowFileSyncConfig(workflow.file_sync).sources.length ? 'ready' : 'incomplete';
}

function alertStatus(workflow: WorkflowDefinition, scopeType: WorkflowAlertScope): SectionStatus {
    const config = workflowAlertConfig(workflow);
    if (config.alert_mode === 'off') return 'off';
    if (config.alert_mode !== 'rules') return 'ready';
    if (!config.alert_rules.length) return 'incomplete';
    const errors = workflowAlertRuleErrors(config.alert_rules, workflow.tasks.map((task) => task.id), scopeType);
    return errors.length ? 'incomplete' : 'ready';
}

function limitsMeta(workflow: WorkflowDefinition): string {
    const raw = isRecord(workflow.limits) ? workflow.limits : DEFAULT_FLOW_LIMITS;
    const executions = Number(raw.max_executions);
    const deadline = Number(raw.deadline_seconds);
    if (!Number.isFinite(executions) || !Number.isFinite(deadline)) {
        return 'Execution admissions and elapsed deadline for each run';
    }
    return `Up to ${plural(executions, 'execution admission', 'execution admissions')} · ${deadline.toLocaleString()} second deadline`;
}

/** When a workflow runs, in a few words: manual, its schedule, or the File Sync check. */
export function workflowTriggerSummary(workflow: WorkflowDefinition, timezones: ReadonlySet<string> | null = null): string {
    if (workflow.trigger_type === 'manual') return 'Manual · runs only when started';
    const label = workflowScheduleLabel(workflow.trigger_type, workflow.schedule, timezones);
    if (label) return label;
    return workflow.trigger_type === 'file_sync' ? 'Monitor File Sync changes' : 'Schedule';
}

/** How a workflow handles failure and whether it runs durably. */
export function workflowExecutionSummary(workflow: WorkflowDefinition): string {
    const strategy = workflow.error_handling.strategy === 'continue' ? 'Continue after failure' : 'Halt on failure';
    const retries = plural(workflow.error_handling.retry_count, 'retry', 'retries');
    return `${strategy} · ${retries}${workflow.durable_execution === true ? ' · Durable execution' : ''}`;
}

/** When a workflow alerts, in the alert editor's own words, with its rule count. */
export function workflowAlertsSummary(workflow: WorkflowDefinition): string {
    const config = workflowAlertConfig(workflow);
    const mode = WORKFLOW_ALERT_MODE_LABELS[config.alert_mode as WorkflowAlertMode] ?? config.alert_mode;
    return config.alert_mode === 'rules' || config.alert_rules.length
        ? `${mode} · ${plural(config.alert_rules.length, 'rule', 'rules')}`
        : mode;
}

function tasksLabel(workflow: WorkflowDefinition, context: WorkflowEditorSectionContext): string {
    if (workflow.definition_version !== 3) return WORKFLOW_EDITOR_SECTION_LABELS.tasks;
    return context.structuredSurface === 'flow' ? 'Structured Flow' : 'Structured List';
}

/**
 * The cards a draft shows, in reading order, each with its status and a line of facts.
 *
 * Limits belong to structured (definition 3) drafts only, as their fields do. Every other card is
 * always present: File Sync and Alerts read Off rather than disappearing, so the index still says
 * where to turn them on.
 */
export function workflowEditorSections(
    workflow: WorkflowDefinition,
    context: WorkflowEditorSectionContext,
): WorkflowEditorSection[] {
    const timezones = context.scheduleTimezones ?? null;
    const references = workflow.reference_inputs.length;
    const tasks = workflow.tasks.length;
    const needingAttention = workflowTasksNeedingAttention(workflow);
    const sections: WorkflowEditorSection[] = [
        {
            id: 'basics',
            label: WORKFLOW_EDITOR_SECTION_LABELS.basics,
            status: basicsStatus(workflow, context),
            meta: `Runner: ${workflowRunnerSummary(workflow, context.options)}`,
        },
        {
            id: 'trigger',
            label: WORKFLOW_EDITOR_SECTION_LABELS.trigger,
            status: workflow.is_enabled === false ? 'off' : 'ready',
            meta: workflowTriggerSummary(workflow, timezones),
        },
        {
            id: 'file-sync',
            label: WORKFLOW_EDITOR_SECTION_LABELS['file-sync'],
            status: fileSyncStatus(workflow, context),
            meta: workflowFileSyncSummary(workflow),
        },
        {
            id: 'execution',
            label: WORKFLOW_EDITOR_SECTION_LABELS.execution,
            status: 'none',
            meta: workflowExecutionSummary(workflow),
        },
        {
            id: 'references',
            label: WORKFLOW_EDITOR_SECTION_LABELS.references,
            status: 'none',
            meta: references ? plural(references, 'shared document', 'shared documents') : 'No shared documents',
        },
    ];
    if (workflow.definition_version === 3) {
        sections.push({
            id: 'limits',
            label: WORKFLOW_EDITOR_SECTION_LABELS.limits,
            status: 'none',
            meta: limitsMeta(workflow),
        });
    }
    sections.push(
        {
            id: 'tasks',
            label: tasksLabel(workflow, context),
            status: !tasks || needingAttention ? 'incomplete' : 'ready',
            meta: `${plural(tasks, 'task', 'tasks')}${needingAttention ? ` · ${needingAttention} ${needingAttention === 1 ? 'needs' : 'need'} attention` : ''}`,
        },
        {
            id: 'alerts',
            label: WORKFLOW_EDITOR_SECTION_LABELS.alerts,
            status: alertStatus(workflow, context.scopeType),
            meta: workflowAlertsSummary(workflow),
        },
    );
    return sections;
}
