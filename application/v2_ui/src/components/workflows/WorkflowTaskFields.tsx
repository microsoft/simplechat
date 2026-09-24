// WorkflowTaskFields.tsx
// Shared task fields and runner pickers for native workflow authoring.

import { useState } from 'react';
import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react';
import { GlassButton, GlassPanel, Toggle } from '../ui/primitives';
import { Pill } from '../workspace/primitives';
import { WorkflowDocumentPicker } from './WorkflowDocumentPicker';
import { WorkflowConditionEditor, WorkflowDecisionFields, WorkflowFlowInputs } from './WorkflowConditionEditor';
import { useWorkflowFieldDrafts, type WorkflowFieldDraftOwner } from './WorkflowFieldDrafts';
import {
    defaultFlowPredicate,
    enclosingFlowLoopControls,
    enclosingFlowLoops,
    isFlowBinding,
    isLegacyWorkflowBinding,
    type WorkflowTaskNode,
    type WorkflowForEachNode,
} from '../../lib/workflowFlow';
import {
    comparisonActionFromSelection,
    documentActionFromSelection,
    findWorkflowAgent,
    isWorkflowPublicationCompletionPolicy,
    isWorkflowPublicationSourceKind,
    safeWorkflowAlias,
    savedOutputPublicationFormats,
    workflowFileSyncProvidesAnalyzeTargets,
    workflowInputProcessingErrors,
    WORKFLOW_APPROVAL_MESSAGE_LIMIT,
    workflowSchemaErrors,
    workflowAgentKey,
    WORKFLOW_COUNT_KINDS,
    WORKFLOW_OUTPUT_KINDS,
    WORKFLOW_SCHEMA_LIMIT,
    WORKFLOW_TASK_INSTRUCTIONS_LIMIT,
    WORKFLOW_PUBLICATION_COMPLETION_LABELS,
    type WorkflowDefinition,
    type WorkflowDocumentAction,
    type WorkflowEditorOptions,
    type WorkflowAgentReference,
    type WorkflowInputBinding,
    type WorkflowInputOutput,
    type WorkflowOutputContract,
    type WorkflowOutputKind,
    type WorkflowScope,
    type WorkflowTask,
    type WorkflowTaskRunner,
    type WorkflowReferenceInput,
    type WorkflowPublication,
} from '../../lib/workflowEditor';
import { isRecord } from '../../lib/workspaceAuthoring';

const inputClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';
const textareaClass = `${inputClass} min-h-24`;
const outputOptions: WorkflowInputOutput[] = ['authoritative', 'text', 'records', 'json', 'documents'];

function fieldLabel(name: string, required = false) {
    return `${name}${required ? ' *' : ''}`;
}

function taskInputMode(task: WorkflowTask): 'auto' | 'none' | 'custom' {
    if (task.inputs == null) {
        return 'auto';
    }
    return task.inputs?.length ? 'custom' : 'none';
}

function taskReferenceMode(task: WorkflowTask): 'all' | 'none' | 'custom' {
    if (task.reference_ids == null) {
        return 'all';
    }
    return task.reference_ids?.length ? 'custom' : 'none';
}

function runnerLabel(runner: WorkflowTaskRunner): string {
    if (runner.type === 'inherit') {
        return 'Inherit workflow runner';
    }
    return runner.type === 'agent' ? 'Specific agent' : 'Specific model';
}

function taskValidationErrors(
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

export function WorkflowAgentPicker({
    value,
    options,
    onChange,
    label = 'Agent',
    localOnly = false,
}: {
    value?: WorkflowAgentReference;
    options: WorkflowEditorOptions;
    onChange: (value: WorkflowAgentReference | undefined) => void;
    label?: string;
    localOnly?: boolean;
}) {
    const selectedKey = workflowAgentKey(value);
    return (
        <label className="text-sm text-text-2">
            {label}
            <select
                className={`${inputClass} mt-1`}
                aria-label={label}
                value={selectedKey}
                onChange={(event) => onChange(findWorkflowAgent(options, event.target.value))}
            >
                <option value="">Select an agent</option>
                {options.agents.map((agent) => (
                    <option key={workflowAgentKey(agent)} value={workflowAgentKey(agent)} disabled={localOnly && agent.loop_eligible !== true}>
                        {agent.display_name || agent.name}
                        {agent.is_global ? ' · Provided' : agent.is_group ? ' · Group' : ''}
                        {localOnly && agent.loop_eligible !== true ? ' · unavailable for locally metered work' : ''}
                    </option>
                ))}
            </select>
        </label>
    );
}

export function WorkflowModelPicker({
    endpointId,
    modelId,
    options,
    onChange,
    label = 'Model',
    localOnly = false,
}: {
    endpointId?: string;
    modelId?: string;
    options: WorkflowEditorOptions;
    onChange: (endpointId: string, modelId: string) => void;
    label?: string;
    localOnly?: boolean;
}) {
    const selected = options.models.findIndex((model) =>
        model.endpoint_id === (endpointId ?? '') && model.model_id === (modelId ?? ''));
    const selectedKey = selected >= 0 ? String(selected) : '';
    const defaultLabel = options.default_model?.label || 'App default model';
    const defaultInvalid = options.default_model?.valid === false;
    return (
        <label className="text-sm text-text-2">
            {label}
            <select
                className={`${inputClass} mt-1`}
                aria-label={label}
                value={selectedKey}
                onChange={(event) => {
                    const model = options.models[Number(event.target.value)];
                    onChange(model?.endpoint_id ?? '', model?.model_id ?? '');
                }}
            >
                <option value="" disabled={localOnly && options.default_model?.loop_eligible === false}>
                    {defaultInvalid || localOnly && options.default_model?.loop_eligible === false ? `${defaultLabel} · unavailable` : defaultLabel}
                </option>
                {options.models.map((model, index) => (
                    <option key={`${index}:${model.endpoint_id}:${model.model_id}`} value={String(index)} disabled={localOnly && model.loop_eligible === false}>
                        {model.label} · {model.provider}
                        {localOnly && model.loop_eligible === false ? ' · unavailable for locally metered work' : ''}
                    </option>
                ))}
            </select>
            {defaultInvalid && !endpointId && !modelId ? (
                <span className="mt-1 block text-xs text-warn">
                    The default model is not valid here. Choose an explicit authorized model before saving.
                </span>
            ) : null}
        </label>
    );
}

function OutputContractFields({
    owner,
    contract,
    onChange,
}: {
    owner: WorkflowFieldDraftOwner;
    contract: WorkflowOutputContract;
    onChange: (contract: WorkflowOutputContract) => void;
}) {
    const drafts = useWorkflowFieldDrafts();
    const schema = drafts.field(owner, ['output', 'schema'], contract.schema ? JSON.stringify(contract.schema, null, 2) : '');

    const updateSchema = (value: string) => {
        if (!value.trim()) {
            const next = { ...contract };
            delete next.schema;
            schema.setValue(value);
            onChange(next);
            return;
        }
        try {
            const parsed = JSON.parse(value) as unknown;
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                const errors = workflowSchemaErrors(parsed);
                schema.setValue(value, errors[0] ?? '');
                onChange({ ...contract, schema: parsed as Record<string, unknown> });
            } else {
                schema.setValue(value, 'JSON schema must be an object.');
            }
        } catch {
            schema.setValue(value, 'JSON schema must be valid JSON.');
        }
    };

    return (
        <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
                <label className="text-sm text-text-2">
                    Expected output kind
                    <select
                        className={`${inputClass} mt-1`}
                        aria-label="Expected output kind"
                        value={contract.kind}
                        onChange={(event) => onChange({ ...contract, kind: event.target.value as WorkflowOutputKind })}
                    >
                        {WORKFLOW_OUTPUT_KINDS.map((kind) => (
                            <option key={kind} value={kind}>{kind.replace(/_/g, ' ')}</option>
                        ))}
                    </select>
                </label>
                <label className="text-sm text-text-2">
                    Expected count
                    <input
                        className={`${inputClass} mt-1`}
                        type="number"
                        min={0}
                        aria-label="Expected count"
                        value={contract.expected_count ?? ''}
                        onChange={(event) => {
                            const value = event.target.value;
                            const next = { ...contract };
                            if (value === '') {
                                delete next.expected_count;
                            } else {
                                next.expected_count = Number(value);
                            }
                            onChange(next);
                        }}
                    />
                    {!WORKFLOW_COUNT_KINDS.has(contract.kind) ? (
                        <span className="mt-1 block text-xs text-warn">
                            Expected count is saved only for records, JSON, and document results.
                        </span>
                    ) : null}
                </label>
                <label className="text-sm text-text-2 md:col-span-2">
                    Identity field
                    <input
                        className={`${inputClass} mt-1`}
                        aria-label="Identity field"
                        value={contract.identity_field ?? ''}
                        onChange={(event) => onChange({ ...contract, identity_field: event.target.value })}
                        placeholder="For example: id"
                    />
                    {contract.kind !== 'records' ? (
                        <span className="mt-1 block text-xs text-warn">
                            Identity field is valid only for records output.
                        </span>
                    ) : null}
                </label>
            </div>
            <Toggle
                label="Require complete coverage"
                checked={contract.require_complete_coverage}
                onChange={(checked) => onChange({ ...contract, require_complete_coverage: checked })}
                description="Ask validation to flag missing expected records or documents."
            />
            <Toggle
                label="Allow partial result"
                checked={contract.allow_partial}
                onChange={(checked) => onChange({ ...contract, allow_partial: checked })}
                description="Partial remains visible as partial in run inspection; it is not treated as a fully complete answer."
            />
            <details className="rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-medium text-text-1">Optional JSON schema</summary>
                <p className="mt-2 text-xs text-text-3">
                    The schema describes the entire final value. Passing schema validation
                    does not prove the workflow result is factually correct. V2 accepts a
                    bounded Draft 2020-12 subset up to {WORKFLOW_SCHEMA_LIMIT / 1024} KiB;
                    $ref, pattern, allOf and oneOf are intentionally not supported.
                </p>
                <textarea
                    className={`${textareaClass} mt-2 font-mono text-xs`}
                    aria-label="Optional JSON schema"
                    value={schema.value}
                    onChange={(event) => updateSchema(event.target.value)}
                    onBlur={() => updateSchema(schema.value)}
                />
                {schema.error ? <p role="alert" className="mt-1 text-xs text-danger">{schema.error}</p> : null}
            </details>
        </div>
    );
}

function TaskInputs({
    task,
    previousTasks,
    onChange,
}: {
    task: WorkflowTask;
    previousTasks: WorkflowTask[];
    onChange: (task: WorkflowTask) => void;
}) {
    const mode = taskInputMode(task);
    const inputs = (task.inputs ?? []).filter(isLegacyWorkflowBinding);
    const updateInput = (taskId: string, update: Partial<WorkflowInputBinding>) => {
        onChange({
            ...task,
            inputs: inputs.map((input) => input.task_id === taskId ? { ...input, ...update } : input),
        });
    };
    const toggle = (producer: WorkflowTask, checked: boolean) => {
        if (checked) {
            onChange({
                ...task,
                inputs: [
                    ...inputs,
                    {
                        name: safeWorkflowAlias(producer.name, 'input'),
                        task_id: producer.id,
                        output: 'authoritative',
                        required: true,
                        expected_kind: producer.output_contract?.kind ?? 'any',
                    },
                ],
            });
        } else {
            onChange({ ...task, inputs: inputs.filter((input) => input.task_id !== producer.id) });
        }
    };

    return (
        <div className="space-y-3">
            <label className="text-sm text-text-2">
                Previous-task inputs
                <select
                    className={`${inputClass} mt-1`}
                    aria-label={`Previous-task inputs for ${task.name}`}
                    value={mode}
                    onChange={(event) => {
                        if (event.target.value === 'auto') {
                            const next = { ...task };
                            delete next.inputs;
                            onChange(next);
                        } else if (event.target.value === 'none') {
                            onChange({ ...task, inputs: [] });
                        } else {
                            const firstProducer = previousTasks[0];
                            onChange({
                                ...task,
                                inputs: inputs.length || !firstProducer ? inputs : [{
                                    name: safeWorkflowAlias(firstProducer.name, 'input'),
                                    task_id: firstProducer.id,
                                    output: 'authoritative',
                                    required: true,
                                    expected_kind: firstProducer.output_contract?.kind ?? 'any',
                                }],
                            });
                        }
                    }}
                >
                    <option value="auto">Automatic previous successful result</option>
                    <option value="none">No previous-task inputs</option>
                    <option value="custom">Bind selected earlier tasks</option>
                </select>
            </label>
            {mode === 'auto' ? (
                <p className="text-xs text-text-3">
                    Omitted inputs keep legacy behavior: the runner can pass the previous
                    successful task result automatically.
                </p>
            ) : null}
            {mode === 'none' ? (
                <p className="text-xs text-text-3">An explicit empty input list means this task consumes no previous task result.</p>
            ) : null}
            {mode === 'custom' ? (
                <div className="space-y-2">
                    {!previousTasks.length ? <p className="text-xs text-text-3">There are no earlier tasks to bind.</p> : null}
                    {previousTasks.map((producer) => {
                        const input = inputs.find((item) => item.task_id === producer.id);
                        return (
                            <div key={producer.id} className="space-y-2 rounded-xl border border-edge p-3">
                                <label className="flex items-center gap-2 text-sm text-text-2">
                                    <input
                                        type="checkbox"
                                        aria-label={`Bind ${producer.name} to ${task.name}`}
                                        checked={Boolean(input)}
                                        onChange={(event) => toggle(producer, event.target.checked)}
                                    />
                                    {producer.name}
                                </label>
                                {input ? (
                                    <div className="grid gap-2 md:grid-cols-2">
                                        <label className="text-xs text-text-2">
                                            Input alias
                                            <input
                                                className={`${inputClass} mt-1 text-xs`}
                                                aria-label="Input alias"
                                                value={input.name}
                                                pattern="[A-Za-z][A-Za-z0-9_-]{0,63}"
                                                onChange={(event) => updateInput(producer.id, { name: safeWorkflowAlias(event.target.value, input.name || 'input') })}
                                            />
                                            <span className="mt-1 block text-[11px] text-text-3">
                                                Stable alias: start with a letter; use letters, numbers, underscores or dashes, max 64.
                                            </span>
                                        </label>
                                        <label className="text-xs text-text-2">
                                            Output
                                            <select
                                                className={`${inputClass} mt-1 text-xs`}
                                                aria-label="Output"
                                                value={input.output}
                                                onChange={(event) => updateInput(producer.id, { output: event.target.value as WorkflowInputOutput })}
                                            >
                                                {outputOptions.map((output) => (
                                                    <option key={output} value={output}>{output}</option>
                                                ))}
                                            </select>
                                        </label>
                                        <label className="text-xs text-text-2">
                                            Expected kind
                                            <select
                                                className={`${inputClass} mt-1 text-xs`}
                                                aria-label="Expected kind"
                                                value={input.expected_kind}
                                                onChange={(event) => updateInput(producer.id, { expected_kind: event.target.value as WorkflowOutputKind })}
                                            >
                                                {WORKFLOW_OUTPUT_KINDS.map((kind) => (
                                                    <option key={kind} value={kind}>{kind.replace(/_/g, ' ')}</option>
                                                ))}
                                            </select>
                                        </label>
                                        <label className="flex items-center gap-2 text-xs text-text-2">
                                            <input
                                                type="checkbox"
                                                checked={input.required}
                                                onChange={(event) => updateInput(producer.id, { required: event.target.checked })}
                                            />
                                            Required
                                        </label>
                                    </div>
                                ) : null}
                            </div>
                        );
                    })}
                </div>
            ) : null}
        </div>
    );
}

function TaskReferences({
    task,
    workflow,
    onChange,
}: {
    task: WorkflowTask;
    workflow: WorkflowDefinition;
    onChange: (task: WorkflowTask) => void;
}) {
    const mode = taskReferenceMode(task);
    const selected = new Set(task.reference_ids ?? []);
    const toggle = (referenceId: string, checked: boolean) => {
        const next = checked
            ? [...selected, referenceId]
            : [...selected].filter((id) => id !== referenceId);
        onChange({ ...task, reference_ids: next });
    };
    return (
        <div className="space-y-3">
            <label className="text-sm text-text-2">
                Shared reference use
                <select
                    className={`${inputClass} mt-1`}
                    aria-label="Shared reference use"
                    value={mode}
                    onChange={(event) => {
                        if (event.target.value === 'all') {
                            const next = { ...task };
                            delete next.reference_ids;
                            onChange(next);
                        } else if (event.target.value === 'none') {
                            onChange({ ...task, reference_ids: [] });
                        } else {
                            onChange({ ...task, reference_ids: task.reference_ids ?? [] });
                        }
                    }}
                >
                    <option value="all">All shared references</option>
                    <option value="none">No shared references</option>
                    <option value="custom">Only selected references</option>
                </select>
            </label>
            {mode === 'custom' ? (
                <div className="space-y-2">
                    {!workflow.reference_inputs.length ? <p className="text-xs text-text-3">Add shared references before selecting a subset.</p> : null}
                    {workflow.reference_inputs.map((reference) => (
                        <label key={reference.id} className="flex items-center gap-2 text-sm text-text-2">
                            <input
                                type="checkbox"
                                checked={selected.has(reference.id)}
                                onChange={(event) => toggle(reference.id, event.target.checked)}
                            />
                            {reference.name} <Pill>{reference.scope_type}</Pill>
                        </label>
                    ))}
                </div>
            ) : null}
        </div>
    );
}

function TaskRunnerFields({
    runner,
    options,
    onChange,
    localOnly = false,
}: {
    runner: WorkflowTaskRunner;
    options: WorkflowEditorOptions;
    onChange: (runner: WorkflowTaskRunner) => void;
    localOnly?: boolean;
}) {
    return (
        <div className="space-y-3">
            <label className="text-sm text-text-2">
                Task runner
                <select
                    className={`${inputClass} mt-1`}
                    aria-label="Task runner"
                    value={runner.type}
                    onChange={(event) => onChange({ type: event.target.value as WorkflowTaskRunner['type'] })}
                >
                    <option value="inherit">Inherit workflow runner</option>
                    <option value="agent">Specific agent</option>
                    <option value="model">Specific model</option>
                </select>
            </label>
            {runner.type === 'agent' ? (
                <WorkflowAgentPicker
                    label="Task agent"
                    value={runner.selected_agent}
                    options={options}
                    localOnly={localOnly}
                    onChange={(selectedAgent) => onChange({ type: 'agent', selected_agent: selectedAgent })}
                />
            ) : null}
            {runner.type === 'model' ? (
                <WorkflowModelPicker
                    label="Task model"
                    endpointId={runner.model_endpoint_id}
                    modelId={runner.model_id}
                    options={options}
                    localOnly={localOnly}
                    onChange={(endpointId, modelId) => onChange({ type: 'model', model_endpoint_id: endpointId, model_id: modelId })}
                />
            ) : null}
            {localOnly ? <p className="text-xs text-text-3">Loops and saved-record reports require locally metered models or eligible local agents. Hosted agents are unavailable; model context limits are checked per task, not a total-run token cap.</p> : null}
        </div>
    );
}

function TaskInputProcessingFields({ task, workflow, options, onChange }: {
    task: WorkflowTask;
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    onChange: (task: WorkflowTask) => void;
}) {
    const errors = workflowInputProcessingErrors(workflow, task, options);
    return (
        <div className="space-y-2 rounded-xl border border-edge p-3">
            <label className="block text-sm text-text-2">
                Large saved inputs
                <select className={`${inputClass} mt-1`} aria-label="Large saved inputs" value={task.input_processing ?? 'full'}
                    onChange={(event) => {
                        const mode = event.target.value === 'saved_record_report' ? 'saved_record_report' : 'full';
                        if (mode === 'full' && task.input_processing === undefined) return;
                        onChange({
                            ...task, input_processing: mode,
                            ...(mode === 'saved_record_report' && task.document_action === undefined
                                ? { document_action: { type: 'none' as const } } : {}),
                        });
                    }}>
                    {task.input_processing !== undefined && !['full', 'saved_record_report'].includes(task.input_processing)
                        ? <option value={task.input_processing}>Unsupported saved processing mode</option> : null}
                    <option value="full">Require full input</option>
                    <option value="saved_record_report" disabled={workflow.definition_version !== 3 ||
                        !options.supported_input_processing_modes?.includes('saved_record_report')}>Saved-record report (bounded batches)</option>
                </select>
            </label>
            <p className="text-xs text-text-3">
                Require full input keeps normal task behavior; unsafe oversized requests pause rather than lose data.
                Saved-record report reads all records in bounded batches, retains the originals, and produces a qualitative,
                source-linked explanation. It cannot silently replace arbitrary transforms or quantitative tasks; keep those in Require full input.
            </p>
            {task.input_processing === 'saved_record_report' ? <p className="text-xs text-text-3">
                Requires a text output contract, at least one saved records or document-results input, No document action,
                no publication, and a locally metered runner. This is an explicit processing choice, not a promise of exact arithmetic or a total-run spending cap.
            </p> : null}
            {task.input_processing === 'saved_record_report' && task.document_action === undefined ? (
                <GlassButton size="sm" onClick={() => onChange({ ...task, document_action: { type: 'none' } })}>
                    Use no document action
                </GlassButton>
            ) : null}
            {errors.length ? <ul role="alert" className="space-y-1 rounded-lg bg-danger-soft p-3 text-xs text-danger">
                {errors.map((error) => <li key={error}>{error}</li>)}
            </ul> : null}
        </div>
    );
}

function TaskApprovalFields({
    task,
    durableExecution,
    onNeedsDurable,
    onChange,
}: {
    task: WorkflowTask;
    durableExecution: boolean;
    onNeedsDurable: () => void;
    onChange: (task: WorkflowTask) => void;
}) {
    const approval = task.approval;
    const required = approval?.required === true;
    const message = approval?.message ?? '';

    const setRequired = (checked: boolean) => {
        if (!checked) {
            const next = { ...task };
            delete next.approval;
            onChange(next);
            return;
        }
        if (!durableExecution) {
            onNeedsDurable();
        }
        onChange({
            ...task,
            approval: {
                required: true,
                ...(message ? { message } : {}),
            },
        });
    };

    const setMessage = (value: string) => {
        onChange({
            ...task,
            approval: {
                required: true,
                ...(value ? { message: value } : {}),
            },
        });
    };

    return (
        <div className="space-y-3 rounded-xl border border-edge p-3">
            <Toggle
                label="Require approval before this task"
                checked={required}
                onChange={setRequired}
                description="Pause durable execution before this task so an approver can review the checkpoint and decide whether to continue."
            />
            {required && !durableExecution ? (
                <p role="alert" className="text-xs text-danger">
                    Task approval requires durable execution. Enable durable execution or remove this approval gate before saving.
                </p>
            ) : null}
            {required ? (
                <label className="block text-sm text-text-2">
                    Approval message
                    <textarea
                        className={`${textareaClass} mt-1`}
                        aria-label={`Approval message for ${task.name || 'task'}`}
                        maxLength={WORKFLOW_APPROVAL_MESSAGE_LIMIT}
                        value={message}
                        onChange={(event) => setMessage(event.target.value)}
                        placeholder="Optional context shown to the approver before this task runs."
                    />
                    <span className="mt-1 block text-xs text-text-3">
                        {message.length.toLocaleString()} / {WORKFLOW_APPROVAL_MESSAGE_LIMIT.toLocaleString()} characters
                    </span>
                </label>
            ) : null}
        </div>
    );
}

function evidenceFromAction(action: WorkflowDocumentAction | undefined): WorkflowReferenceInput[] {
    const ids = Array.isArray(action?.document_ids)
        ? action.document_ids.filter((item): item is string => typeof item === 'string' && Boolean(item))
        : [];
    const scopeType = ['personal', 'group', 'public'].includes(String(action?.doc_scope))
        ? action?.doc_scope as WorkflowReferenceInput['scope_type']
        : 'personal';
    const scopeId = scopeType === 'group'
        ? String(action?.active_group_ids?.[0] ?? '')
        : scopeType === 'public'
            ? String(action?.active_public_workspace_id?.[0] ?? '')
            : '';
    return ids.map((id) => ({
        id: `${scopeType}:${scopeId}:${id}`,
        name: safeWorkflowAlias(id, 'evidence'),
        document_id: id,
        scope_type: scopeType,
        scope_id: scopeId,
    }));
}

function actionMode(action: WorkflowDocumentAction | undefined): string {
    if (!action || action.type === 'none') {
        return 'none';
    }
    if (action.type === 'analyze') {
        return action.target_mode === 'current_item' ? 'current_item' : 'analyze';
    }
    if (action.type === 'comparison') {
        return 'comparison';
    }
    if (action.type === 'search') {
        return Array.isArray(action.document_ids) && action.document_ids.length
            ? 'search_selected'
            : 'search_relevance';
    }
    return 'preserve';
}

function splitComparisonEvidence(
    action: WorkflowDocumentAction | undefined,
    evidence: WorkflowReferenceInput[],
): { left: WorkflowReferenceInput | null; right: WorkflowReferenceInput[] } {
    const left = evidence.find((item) => item.document_id === action?.left_document_id) ?? evidence[0] ?? null;
    const rightIds = new Set(action?.right_document_ids ?? []);
    const right = evidence.filter((item) => rightIds.size
        ? rightIds.has(item.document_id)
        : item.document_id !== left?.document_id);
    return { left, right };
}

function DocumentActionFields({
    scope,
    task,
    onChange,
    loops = [],
    changedFileTargets = false,
}: {
    scope: WorkflowScope;
    task: WorkflowTask;
    onChange: (task: WorkflowTask) => void;
    loops?: WorkflowForEachNode[];
    /** File Sync supplies the changed files, so Analyze may run without selected evidence. */
    changedFileTargets?: boolean;
}) {
    const [mode, setMode] = useState(() => actionMode(task.document_action));
    const [evidence, setEvidence] = useState(() => evidenceFromAction(task.document_action));
    const [analysisMode, setAnalysisMode] = useState<'combined' | 'per_document'>(() =>
        task.document_action?.analysis_mode === 'per_document' ? 'per_document' : 'combined');
    const comparison = splitComparisonEvidence(task.document_action, evidence);

    const writeAction = (
        nextMode: string,
        nextEvidence = evidence,
        nextAnalysisMode = analysisMode,
        nextLeft = comparison.left,
        nextRight = comparison.right,
    ) => {
        if (nextMode === 'none') {
            onChange({ ...task, document_action: { type: 'none' } });
        } else if (nextMode === 'search_relevance') {
            onChange({ ...task, document_action: documentActionFromSelection('search', [], { mode: 'relevance', analysisMode: nextAnalysisMode }) });
        } else if (nextMode === 'search_selected') {
            onChange({ ...task, document_action: documentActionFromSelection('search', nextEvidence, { mode: 'selected', analysisMode: nextAnalysisMode }) });
        } else if (nextMode === 'analyze') {
            onChange({ ...task, document_action: documentActionFromSelection('analyze', nextEvidence, { mode: 'selected', analysisMode: nextAnalysisMode }) });
        } else if (nextMode === 'current_item') {
            const loopId = loops.some((loop) => loop.id === task.document_action?.loop_id)
                ? task.document_action?.loop_id : loops[loops.length - 1]?.id ?? '';
            onChange({ ...task, document_action: { type: 'analyze', target_mode: 'current_item', loop_id: loopId, analysis_mode: 'combined' } });
        } else if (nextMode === 'comparison') {
            onChange({ ...task, document_action: comparisonActionFromSelection(nextLeft, nextRight) });
        }
    };

    const updateEvidence = (next: WorkflowReferenceInput[]) => {
        setEvidence(next);
        const nextComparison = splitComparisonEvidence(task.document_action, next);
        writeAction(mode, next, analysisMode, nextComparison.left, nextComparison.right);
    };

    const setComparisonLeft = (documentId: string) => {
        const left = evidence.find((item) => item.document_id === documentId) ?? null;
        const right = comparison.right.filter((item) => item.document_id !== documentId);
        writeAction('comparison', evidence, analysisMode, left, right);
    };

    const setComparisonRight = (documentId: string, checked: boolean) => {
        const selected = evidence.find((item) => item.document_id === documentId);
        if (!selected || selected.document_id === comparison.left?.document_id) {
            return;
        }
        const right = checked
            ? [...comparison.right, selected]
            : comparison.right.filter((item) => item.document_id !== documentId);
        writeAction('comparison', evidence, analysisMode, comparison.left, right);
    };

    const needsSelectedEvidence = ['analyze', 'search_selected', 'comparison'].includes(mode);
    const syncedAnalyzeTargets = mode === 'analyze' && changedFileTargets && evidence.length === 0;
    const missingEvidence = needsSelectedEvidence && evidence.length === 0 && !syncedAnalyzeTargets;
    const missingComparison = mode === 'comparison' && (!comparison.left || comparison.right.length === 0);

    return (
        <div className="space-y-3">
            <label className="text-sm text-text-2">
                Document action
                <select
                    className={`${inputClass} mt-1`}
                    aria-label="Document action"
                    value={mode}
                    onChange={(event) => {
                        const nextMode = event.target.value;
                        setMode(nextMode);
                        writeAction(nextMode);
                    }}
                >
                    <option value="none">No document action</option>
                    <option value="analyze">Analyze selected evidence</option>
                    {loops.length || mode === 'current_item' ? <option value="current_item">Analyze current loop document</option> : null}
                    <option value="search_selected">Search selected evidence</option>
                    <option value="search_relevance">Search by relevance</option>
                    <option value="comparison">Compare source and target documents</option>
                    {mode === 'preserve' ? <option value="preserve">Existing advanced action (preserved)</option> : null}
                </select>
            </label>
            {mode === 'preserve' ? (
                <p className="rounded-xl bg-warn-soft p-3 text-xs text-warn">
                    This existing document action uses advanced options that V2 does not edit.
                    It will be preserved unless you choose a different document action.
                </p>
            ) : null}
            {mode === 'current_item' ? (
                <label className="block text-sm text-text-2">
                    Current document loop
                    <select className={`${inputClass} mt-1`} aria-label="Current document loop" value={task.document_action?.loop_id ?? ''}
                        onChange={(event) => onChange({ ...task, document_action: {
                            type: 'analyze', target_mode: 'current_item', loop_id: event.target.value, analysis_mode: 'combined',
                        } })}>
                        {!loops.some((loop) => loop.id === task.document_action?.loop_id)
                            ? <option value={task.document_action?.loop_id ?? ''}>Unavailable document loop (retained)</option> : null}
                        {loops.map((loop) => <option key={loop.id} value={loop.id}>{loop.id}</option>)}
                    </select>
                    <span className="mt-1 block text-xs text-text-3">Analyzes only this visit's authorized frozen document, with combined analysis. It never repeats the whole selection or trusts a record's document ID.</span>
                </label>
            ) : null}
            {mode !== 'none' && mode !== 'preserve' && mode !== 'current_item' ? (
                <label className="text-sm text-text-2">
                    Analysis mode
                    <select
                        className={`${inputClass} mt-1`}
                        aria-label="Analysis mode"
                        value={analysisMode}
                        onChange={(event) => {
                            const next = event.target.value === 'per_document' ? 'per_document' : 'combined';
                            setAnalysisMode(next);
                            writeAction(mode, evidence, next);
                        }}
                    >
                        <option value="combined">Combined</option>
                        <option value="per_document">Per document</option>
                    </select>
                </label>
            ) : null}
            {mode === 'search_relevance' ? (
                <p className="rounded-xl border border-edge p-3 text-xs text-text-3">
                    Search by relevance lets the runner choose matching documents from the
                    authorized scope. No fixed document IDs are posted.
                </p>
            ) : null}
            {needsSelectedEvidence ? (
                <WorkflowDocumentPicker
                    scope={scope}
                    references={evidence}
                    onChange={updateEvidence}
                    title="Task evidence"
                    selectedLabel={`Selected evidence for ${task.name || 'task'}`}
                    availableLabel={`Available evidence for ${task.name || 'task'}`}
                    hideAliasFields
                    emptyDescription="Select evidence documents for this task action."
                    description="Task evidence is separate from shared workflow references and is posted as document_action document IDs."
                />
            ) : null}
            {missingEvidence ? (
                <p role="alert" className="text-xs text-danger">Select at least one evidence document for this document action.</p>
            ) : null}
            {syncedAnalyzeTargets ? (
                <p className="text-xs text-text-3">No evidence is selected, so this task analyzes the files each File Sync run changed.</p>
            ) : null}
            {mode === 'comparison' && evidence.length ? (
                <div className="space-y-3 rounded-xl border border-edge p-3">
                    <label className="text-sm text-text-2">
                        Comparison source
                        <select
                            className={`${inputClass} mt-1`}
                            aria-label="Comparison source"
                            value={comparison.left?.document_id ?? ''}
                            onChange={(event) => setComparisonLeft(event.target.value)}
                        >
                            <option value="">Choose source document</option>
                            {evidence.map((item) => (
                                <option key={item.id} value={item.document_id}>{item.name}</option>
                            ))}
                        </select>
                    </label>
                    <div className="space-y-2">
                        <p className="text-sm text-text-2">Comparison targets</p>
                        {evidence.filter((item) => item.document_id !== comparison.left?.document_id).map((item) => (
                            <label key={item.id} className="flex items-center gap-2 text-sm text-text-2">
                                <input
                                    type="checkbox"
                                    checked={comparison.right.some((right) => right.document_id === item.document_id)}
                                    onChange={(event) => setComparisonRight(item.document_id, event.target.checked)}
                                />
                                {item.name}
                            </label>
                        ))}
                    </div>
                </div>
            ) : null}
            {missingComparison ? (
                <p role="alert" className="text-xs text-danger">Choose one source and at least one target document for comparison.</p>
            ) : null}
        </div>
    );
}

export function WorkflowTaskFields({
    scope,
    task,
    index,
    workflow,
    options,
    onChange,
    onMove,
    onRemove,
    durableExecution,
    onNeedsDurable,
    structuredNode,
    onStructuredNodeChange,
}: {
    scope: WorkflowScope;
    task: WorkflowTask;
    index: number;
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    onChange: (task: WorkflowTask) => void;
    onMove?: (direction: -1 | 1) => void;
    onRemove?: () => void;
    durableExecution: boolean;
    onNeedsDurable: () => void;
    structuredNode?: WorkflowTaskNode;
    onStructuredNodeChange?: (node: WorkflowTaskNode) => void;
}) {
    const previousTasks = workflow.tasks.slice(0, index);
    const errors = taskValidationErrors(task, index, workflow.tasks, workflow);
    const drafts = useWorkflowFieldDrafts();
    const draftOwner: WorkflowFieldDraftOwner = ['task', task.id];
    const defaultOutputContract = (kind: WorkflowOutputKind): WorkflowOutputContract => ({
        kind,
        require_complete_coverage: false,
        allow_partial: false,
    });

    return (
        <div data-workflow-history-kind="task" data-workflow-history-owner={task.id}>
        <GlassPanel elevation="flat" className="space-y-4 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <p className="text-sm font-semibold text-text-1">{task.name || `Task ${index + 1}`}</p>
                    <p className="text-xs text-text-3">
                        {runnerLabel(task.runner)} · {taskInputMode(task) === 'auto' ? 'automatic input' : `${task.inputs?.length ?? 0} bound inputs`}
                    </p>
                </div>
                {!structuredNode && onMove && onRemove ? <div className="flex flex-wrap gap-2">
                    <GlassButton size="sm" disabled={index === 0} onClick={() => onMove(-1)} aria-label={`Move ${task.name || `Task ${index + 1}`} up`}>
                        <ArrowUp size={14} /> Up
                    </GlassButton>
                    <GlassButton size="sm" disabled={index >= workflow.tasks.length - 1} onClick={() => onMove(1)} aria-label={`Move ${task.name || `Task ${index + 1}`} down`}>
                        <ArrowDown size={14} /> Down
                    </GlassButton>
                    <GlassButton size="sm" variant="danger" disabled={workflow.tasks.length <= 1} onClick={onRemove} aria-label={`Remove ${task.name || `Task ${index + 1}`}`}>
                        <Trash2 size={14} /> Remove
                    </GlassButton>
                </div> : null}
            </div>
            {errors.length ? (
                <div role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
                    {errors.map((error) => <p key={error}>{error}</p>)}
                </div>
            ) : null}
            <div className="grid gap-3 md:grid-cols-2">
                <label className="text-sm text-text-2">
                    {fieldLabel('Task name', true)}
                    <input
                        className={`${inputClass} mt-1`}
                        aria-label="Task name"
                        value={task.name}
                        required
                        onChange={(event) => onChange({ ...task, name: event.target.value })}
                    />
                </label>
            </div>
            <label className="block text-sm text-text-2">
                {fieldLabel('Instructions', true)}
                <textarea
                    className={`${textareaClass} mt-1`}
                    maxLength={WORKFLOW_TASK_INSTRUCTIONS_LIMIT}
                    aria-label="Instructions"
                    value={task.instructions}
                    required
                    onChange={(event) => onChange({ ...task, instructions: event.target.value })}
                />
                <span className="mt-1 block text-xs text-text-3">
                    {task.instructions.length.toLocaleString()} / {WORKFLOW_TASK_INSTRUCTIONS_LIMIT.toLocaleString()} characters
                </span>
            </label>
            {structuredNode && onStructuredNodeChange ? (
                <div className="space-y-3">
                    <Toggle label="Run when" checked={structuredNode.run_when !== undefined}
                        description="False intentionally skips this task before approval or execution. A skipped task produces no output."
                        onChange={(checked) => {
                            const next = { ...structuredNode };
                            if (checked) next.run_when = defaultFlowPredicate(task.inputs?.[0]?.name ?? '');
                            else delete next.run_when;
                            onStructuredNodeChange(next);
                        }} />
                    {structuredNode.run_when ? (
                        <WorkflowConditionEditor workflow={workflow} bindings={(task.inputs ?? []).filter(isFlowBinding)}
                            value={structuredNode.run_when} label={`Run when for ${task.name}`}
                            onChange={(condition) => onStructuredNodeChange({ ...structuredNode, run_when: condition })} />
                    ) : null}
                </div>
            ) : null}
            <details className="rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-medium text-text-1">Runner, inputs, references and outputs</summary>
                <div className="mt-4 space-y-5">
                    {structuredNode ? <TaskPublicationFields task={task} options={options}
                        durableExecution={durableExecution} onChange={(next) => {
                            if (next.output_contract !== task.output_contract) drafts.clear(draftOwner, ['output']);
                            onChange(next);
                        }} /> : null}
                    {!task.publication ? <TaskRunnerFields runner={task.runner} options={options}
                        localOnly={task.input_processing === 'saved_record_report' ||
                            Boolean(structuredNode && enclosingFlowLoopControls(workflow, structuredNode.id).length)}
                        onChange={(runner) => onChange({ ...task, runner })} /> : null}
                    <TaskApprovalFields
                        task={task}
                        durableExecution={durableExecution}
                        onNeedsDurable={onNeedsDurable}
                        onChange={onChange}
                    />
                    {!task.publication ? <DocumentActionFields scope={scope} task={task} onChange={onChange}
                        changedFileTargets={workflowFileSyncProvidesAnalyzeTargets(workflow, scope)}
                        loops={structuredNode ? enclosingFlowLoops(workflow, structuredNode.id).filter((loop) => loop.iterable.kind !== 'input') : []} /> : null}
                    {structuredNode ? (
                        <WorkflowFlowInputs workflow={workflow} nodeId={structuredNode.id}
                            bindings={(task.inputs ?? []).filter(isFlowBinding)} label={`${task.name} inputs`}
                            recordsOnly={task.publication?.source_kind === 'saved_output'}
                            onChange={(inputs) => onChange({ ...task, inputs })} />
                    ) : <TaskInputs task={task} previousTasks={previousTasks} onChange={onChange} />}
                    {structuredNode && Boolean(options.supported_input_processing_modes?.length) || task.input_processing !== undefined ? <TaskInputProcessingFields task={task}
                        workflow={workflow} options={options} onChange={onChange} /> : null}
                    <TaskReferences task={task} workflow={workflow} onChange={onChange} />
                    <label className="text-sm text-text-2">
                        Output contract
                        <select
                            className={`${inputClass} mt-1`}
                            aria-label={`Output contract for ${task.name || `Task ${index + 1}`}`}
                            value={task.output_contract?.kind ?? ''}
                            onChange={(event) => {
                                const kind = event.target.value as WorkflowOutputKind | '';
                                if (!kind) {
                                    const next = { ...task };
                                    delete next.output_contract;
                                    drafts.clear(draftOwner, ['output']);
                                    onChange(next);
                                } else {
                                    onChange({
                                        ...task,
                                        output_contract: task.output_contract
                                            ? { ...task.output_contract, kind }
                                            : defaultOutputContract(kind),
                                    });
                                }
                            }}
                        >
                            <option value="">Any / unconfigured</option>
                            {WORKFLOW_OUTPUT_KINDS.map((kind) => (
                                <option key={kind} value={kind}>{kind.replace(/_/g, ' ')}</option>
                            ))}
                        </select>
                    </label>
                    {task.output_contract ? (
                        <>
                        {structuredNode ? <WorkflowDecisionFields draftOwner={draftOwner} contract={task.output_contract}
                            onChange={(contract) => {
                                drafts.clear(draftOwner, ['output', 'schema']);
                                onChange({ ...task, output_contract: contract });
                            }} /> : null}
                        <OutputContractFields
                            owner={draftOwner}
                            contract={task.output_contract}
                            onChange={(contract) => {
                                onChange({ ...task, output_contract: contract });
                            }}
                        />
                        </>
                    ) : (
                        <p className="text-xs text-text-3">
                            No output contract is configured. The backend treats this as any
                            shape and does not opt into partial acceptance.
                        </p>
                    )}
                </div>
            </details>
        </GlassPanel>
        </div>
    );
}

function TaskPublicationFields({ task, options, durableExecution, onChange }: {
    task: WorkflowTask;
    options: WorkflowEditorOptions;
    durableExecution: boolean;
    onChange: (task: WorkflowTask) => void;
}) {
    const publication = task.publication;
    const supportedPolicies = options.supported_publication_completion_policies ?? [];
    const savedFormats = savedOutputPublicationFormats(options);
    const savedOutputAvailable = durableExecution && savedFormats.length > 0;
    const savedOutput = publication?.source_kind === 'saved_output';
    const update = (value: WorkflowPublication) => onChange({ ...task, publication: value });
    if (publication !== undefined && (!isRecord(publication) ||
        Object.hasOwn(publication, 'source_kind') && !isWorkflowPublicationSourceKind(publication.source_kind) ||
        (savedOutput ? publication.artifact_format !== 'json' : !['md', 'csv', 'json'].includes(publication.artifact_format)))) {
        return <p className="text-xs text-warn">The saved publication source or format is unsupported. Its original configuration is preserved and read-only.</p>;
    }
    if (publication && Object.hasOwn(publication, 'completion_policy') &&
        !isWorkflowPublicationCompletionPolicy(publication.completion_policy)) {
        return <p className="text-xs text-warn">The saved publication completion policy is unsupported. Its original configuration is preserved and read-only.</p>;
    }
    return (
        <div className="space-y-3">
            <Toggle label={savedFormats.length || savedOutput ? 'Publish a workflow file' : 'Publish an existing analysis artifact'}
                checked={publication !== undefined}
                description={savedFormats.length || savedOutput
                    ? 'Choose an existing Analyze file or export one explicitly bound saved records output. No model reruns the analysis.'
                    : 'Reuse one explicitly bound native Analyze result. No model creates another copy of its content.'}
                onChange={(checked) => {
                    if (checked) onChange({
                        ...task, publication: {
                            artifact_format: 'md', workspace_scope: 'personal',
                            ...(durableExecution && supportedPolicies.includes('submitted') ? { completion_policy: 'submitted' } : {}),
                        },
                        runner: { type: 'inherit' }, document_action: { type: 'none' },
                        output_contract: { kind: 'json', require_complete_coverage: false, allow_partial: false },
                    });
                    else {
                        const next = { ...task };
                        delete next.publication;
                        onChange(next);
                    }
                }} />
            {publication ? (
                <fieldset className="grid min-w-0 gap-3 rounded-xl border border-edge p-3 sm:grid-cols-2">
                    <legend className="px-1 text-sm text-text-1">Publication source and destination</legend>
                    <label className="min-w-0 text-xs text-text-2 sm:col-span-2">
                        Publication source
                        <select className={`${inputClass} mt-1`} aria-label={`Publication source for ${task.name}`}
                            value={publication.source_kind ?? 'native_analysis'}
                            onChange={(event) => {
                                const sourceKind = event.target.value;
                                if (!isWorkflowPublicationSourceKind(sourceKind) ||
                                    sourceKind === 'saved_output' && !savedOutputAvailable) return;
                                update({
                                    ...publication, source_kind: sourceKind,
                                    artifact_format: sourceKind === 'saved_output' ? 'json' : publication.artifact_format,
                                });
                            }}>
                            <option value="native_analysis">Existing Analyze file</option>
                            <option value="saved_output" disabled={!savedOutputAvailable}>Saved workflow output</option>
                        </select>
                        <span className="mt-1 block text-text-3">
                            {savedOutput
                                ? 'Create a file export of every saved record object, including nested values and provenance, without rerunning analysis. This is not a qualitative report or a task-data handoff.'
                                : 'Publish the existing file from one explicitly bound native Analyze result.'}
                            {!savedFormats.length
                                ? ' This server does not advertise saved workflow output publication. Existing Analyze files remain available.'
                                : !durableExecution ? ' Saved workflow output requires durable execution.' : ''}
                        </span>
                    </label>
                    <label className="text-xs text-text-2">
                        {savedOutput ? 'File export format' : 'Existing artifact format'}
                        <select className={`${inputClass} mt-1`} aria-label={`Publication format for ${task.name}`}
                            value={publication.artifact_format} onChange={(event) => {
                                const format = event.target.value;
                                if (!['md', 'csv', 'json'].includes(format) ||
                                    savedOutput && !savedFormats.some((supported) => supported === format)) return;
                                update({ ...publication, artifact_format: format as WorkflowPublication['artifact_format'] });
                            }}>
                            <option value="md" disabled={savedOutput}>Markdown</option>
                            <option value="csv" disabled={savedOutput}>CSV</option>
                            {savedOutput ? savedFormats.map((format) => (
                                <option key={format} value={format}>JSON - exact saved records</option>
                            )) : <option value="json">JSON</option>}
                            {savedOutput && !savedFormats.length ? (
                                <option value="json" disabled>JSON - exact saved records (not advertised)</option>
                            ) : null}
                        </select>
                        {savedOutput ? <span className="mt-1 block text-text-3">
                            Only JSON exact saved records is available for this source. No format fallback or content reconstruction.
                        </span> : null}
                    </label>
                    <label className="text-xs text-text-2">
                        Destination scope
                        <select className={`${inputClass} mt-1`} aria-label={`Publication scope for ${task.name}`}
                            value={publication.workspace_scope} onChange={(event) => {
                                const scope = event.target.value as WorkflowPublication['workspace_scope'];
                                const next = { ...publication, workspace_scope: scope };
                                if (scope !== 'group') delete next.group_id;
                                if (scope !== 'public') delete next.public_workspace_id;
                                if (scope === 'group') next.group_id ??= '';
                                if (scope === 'public') next.public_workspace_id ??= '';
                                update(next);
                            }}>
                            <option value="personal">Personal workspace</option><option value="group">Group workspace</option>
                            <option value="public">Public workspace</option>
                        </select>
                    </label>
                    {publication.workspace_scope !== 'personal' ? (
                        <label className="text-xs text-text-2 sm:col-span-2">
                            Destination workspace ID
                            <input className={`${inputClass} mt-1`} aria-label={`Publication workspace ID for ${task.name}`}
                                value={publication.workspace_scope === 'group' ? publication.group_id ?? '' : publication.public_workspace_id ?? ''}
                                onChange={(event) => update({
                                    ...publication,
                                    ...(publication.workspace_scope === 'group' ? { group_id: event.target.value } : { public_workspace_id: event.target.value }),
                                })} />
                        </label>
                    ) : null}
                    <label className="text-xs text-text-2 sm:col-span-2">
                        Complete publication when
                        <select className={`${inputClass} mt-1`} aria-label={`Complete publication when for ${task.name}`}
                            value={publication.completion_policy ?? ''}
                            disabled={!durableExecution || !Object.keys(WORKFLOW_PUBLICATION_COMPLETION_LABELS).some((policy) => supportedPolicies.includes(policy))}
                            onChange={(event) => {
                                const policy = event.target.value;
                                const next = { ...publication };
                                if (policy === '') delete next.completion_policy;
                                else if (isWorkflowPublicationCompletionPolicy(policy) && supportedPolicies.includes(policy)) {
                                    next.completion_policy = policy;
                                } else return;
                                update(next);
                            }}>
                            <option value="">Existing behavior (no completion policy)</option>
                            {Object.entries(WORKFLOW_PUBLICATION_COMPLETION_LABELS).map(([policy, label]) => (
                                <option key={policy} value={policy} disabled={!supportedPolicies.includes(policy)}>{label}</option>
                            ))}
                        </select>
                        <span className="mt-1 block text-text-3">
                            {publication.completion_policy === 'submitted'
                                ? 'Confirm submission and the required handoff, without waiting for approval or indexing.'
                                : publication.completion_policy === 'approved'
                                    ? publication.workspace_scope === 'personal'
                                        ? 'Personal workspace approval is not required. Complete after confirmed submission.'
                                        : 'Wait for the existing destination workspace approval, not workflow task approval.'
                                    : publication.completion_policy === 'indexed_ready'
                                        ? 'Wait for approval where required, completed processing, screening clearance, and search visibility.'
                                        : 'Preserve the existing behavior until you explicitly choose a supported completion policy.'}
                        </span>
                    </label>
                    <p className="text-xs text-text-3 sm:col-span-2">
                        {savedOutput
                            ? 'Bind exactly one required records output from an earlier task, Collect, or explicit join below. '
                            : 'Bind exactly one earlier native Analyze output below. '}
                        The destination is explicit, not your active workspace.
                        Group/public approval and processing remain separate; queued does not mean indexed and ready.
                    </p>
                </fieldset>
            ) : null}
        </div>
    );
}
