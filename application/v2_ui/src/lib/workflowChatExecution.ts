// workflowChatExecution.ts
// Readouts shared by workflow defaults, task overrides, and change history.

import type { WorkflowChatExecution, WorkflowDefinition, WorkflowEditorOptions, WorkflowTask } from './workflowEditor';

export const WORKFLOW_CHAT_MODE_LABELS = {
    orchestration: 'Orchestration (automatic)',
    selected: 'Selected capabilities',
    off: 'Off',
} as const;

export function workflowChatExecutionSummary(
    value: WorkflowChatExecution | undefined,
    legacyEnabled = false,
    options?: Pick<WorkflowEditorOptions, 'chat_execution'>,
): string {
    if (!value) return legacyEnabled ? 'Legacy core capabilities (unchanged)' : 'Legacy plain model execution (unchanged)';
    const label = WORKFLOW_CHAT_MODE_LABELS[value.mode];
    if (value.mode !== 'selected') return label;
    const choices = [...(options?.chat_execution?.capabilities ?? []), ...(options?.chat_execution?.visual_requirements ?? [])];
    const required = [...value.required_capabilities, ...value.visual_requirements]
        .map((id) => choices.find((choice) => choice.id === id)?.label || id);
    return `${label} · ${required.join(', ') || 'Choose at least one requirement'}`;
}

export function effectiveTaskChatExecution(workflow: WorkflowDefinition, task: WorkflowTask): WorkflowChatExecution | undefined {
    return task.chat_execution ?? workflow.chat_execution;
}

export function workflowResultsSummary(workflow: WorkflowDefinition): string {
    const delivery = workflow.results_delivery;
    if (!delivery) return 'Existing delivery behavior (unchanged)';
    if (delivery.mode === 'history') return 'Run history only';
    if (delivery.mode === 'task') return 'Delivered by a task/agent';
    if (delivery.conversation_type === 'personal') return 'Private personal results conversation';
    if (delivery.conversation_type === 'group') return 'Private results in this group';
    if (delivery.all_group_members) return 'Shared with all current group members';
    const count = delivery.recipient_ids.length;
    return `Shared ${delivery.conversation_type === 'group_shared' ? 'in this group' : 'personal results'} · ${count} named recipient${count === 1 ? '' : 's'}`;
}
