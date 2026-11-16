// WorkflowChatExecutionFields.tsx

import { useId } from 'react';
import type { WorkflowChatExecution, WorkflowDefinition, WorkflowEditorOptions } from '../../lib/workflowEditor';
import { WORKFLOW_CHAT_MODE_LABELS, workflowChatExecutionSummary } from '../../lib/workflowChatExecution';
import { WorkflowField, WorkflowFieldList, workflowFieldInputClass } from './WorkflowField';

export function WorkflowChatExecutionFields({
    value, workflow, options, task = false, onChange,
}: {
    value?: WorkflowChatExecution;
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    task?: boolean;
    onChange: (value: WorkflowChatExecution | undefined) => void;
}) {
    const id = useId();
    const catalog = options.chat_execution;
    const selected = task && !value ? 'inherit' : value?.mode ?? 'legacy';
    const effective = value ?? (task ? workflow.chat_execution : undefined);
    const modes = Object.entries(WORKFLOW_CHAT_MODE_LABELS);
    const unavailableMode = effective && catalog?.modes.find((mode) => mode.id === effective.mode)?.available === false;
    const choices = [
        ...(catalog?.capabilities ?? []).map((choice) => ({ ...choice, visual: false })),
        ...(catalog?.visual_requirements ?? []).map((choice) => ({ ...choice, visual: true })),
    ];
    const missingChoices = effective?.mode === 'selected'
        ? [...effective.required_capabilities, ...effective.visual_requirements].filter((key) => !choices.some((choice) => choice.id === key))
        : [];
    const label = task ? 'Task chat capabilities' : 'Chat capabilities';

    return (
        <WorkflowFieldList>
            <WorkflowField label={label} htmlFor={id} width="wide"
                help={task ? 'An override replaces the workflow selection for this task only.'
                    : 'Automatic plans each task using available chat tools. Selected capabilities must actually be used, not just considered.'}>
                <select id={id} aria-label={label} className={workflowFieldInputClass} value={selected}
                    onChange={(event) => {
                        const mode = event.target.value;
                        if (mode === 'inherit') { onChange(undefined); return; }
                        if (mode === 'legacy') return;
                        onChange({
                            version: 1, mode: mode as WorkflowChatExecution['mode'],
                            required_capabilities: mode === 'selected' ? value?.required_capabilities ?? [] : [],
                            visual_requirements: mode === 'selected' ? value?.visual_requirements ?? [] : [],
                        });
                    }}>
                    {task ? <option value="inherit">Use workflow settings</option> : null}
                    {!task && !value ? <option value="legacy">{workflowChatExecutionSummary(undefined, workflow.chat_capabilities_enabled)}</option> : null}
                    {modes.map(([mode, modeLabel]) => {
                        const option = catalog?.modes.find((item) => item.id === mode);
                        const available = option?.available ?? mode === 'off';
                        return <option key={mode} value={mode} disabled={!available}>
                            {modeLabel}{!available ? ' · unavailable' : ''}
                        </option>;
                    })}
                </select>
                <p className="mt-2 break-words text-xs text-text-2" aria-live="polite">
                    {task && !value ? 'Inherited: ' : 'Effective: '}
                    {workflowChatExecutionSummary(effective, workflow.chat_capabilities_enabled, options)}
                </p>
                {unavailableMode ? <p role="alert" className="mt-2 text-xs text-danger">
                    {catalog?.modes.find((mode) => mode.id === effective.mode)?.reason || 'This mode is unavailable. Choose an available mode before saving.'}
                </p> : null}
                {!catalog?.modes.find((mode) => mode.id === 'orchestration')?.available ? (
                    <p className="mt-2 text-xs text-text-3">
                        {catalog?.modes.find((mode) => mode.id === 'orchestration')?.reason || 'Orchestration is not available in this workspace.'}
                    </p>
                ) : null}
            </WorkflowField>
            {value?.mode === 'selected' ? <WorkflowField label="Required capabilities and outputs" labelId={`${id}-requirements`} group width="full"
                help="Select tools and outputs this task must produce. Include needed URLs, source documents, and output formats in the task instructions.">
                <div className="grid gap-2 sm:grid-cols-2">
                    {choices.map((choice) => {
                        const list: string[] = choice.visual ? value.visual_requirements : value.required_capabilities;
                        const checked = list.includes(choice.id);
                        return <label key={choice.id} className="flex min-w-0 items-start gap-2 py-1 text-sm text-text-2">
                            <input type="checkbox" className="mt-1 accent-accent" checked={checked}
                                disabled={!choice.available && !checked}
                                onChange={(event) => {
                                    const next = event.target.checked ? [...list, choice.id] : list.filter((key) => key !== choice.id);
                                    onChange(choice.visual
                                        ? { ...value, visual_requirements: next as WorkflowChatExecution['visual_requirements'] }
                                        : { ...value, required_capabilities: next });
                                }} />
                            <span className="min-w-0 break-words">{choice.label}
                                {!choice.available ? <span className="mt-0.5 block text-xs text-warn">{choice.reason || 'Unavailable in this workspace'}</span> : null}
                            </span>
                        </label>;
                    })}
                </div>
                {missingChoices.map((key) => <label key={key} className="mt-2 flex items-center gap-2 text-sm text-warn">
                    <input type="checkbox" checked onChange={() => onChange({
                        ...value,
                        required_capabilities: value.required_capabilities.filter((item) => item !== key),
                        visual_requirements: value.visual_requirements.filter((item) => item !== key),
                    })} />
                    {key} · no longer available; uncheck to remove
                </label>)}
                {!value.required_capabilities.length && !value.visual_requirements.length ? (
                    <p role="alert" className="mt-2 text-xs text-danger">Choose at least one required capability or output before saving.</p>
                ) : null}
            </WorkflowField> : null}
        </WorkflowFieldList>
    );
}
