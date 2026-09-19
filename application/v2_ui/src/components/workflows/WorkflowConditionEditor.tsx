// WorkflowConditionEditor.tsx
// Typed input and condition controls; predicates are never evaluated in the browser.

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import {
    analyzeWorkflowFlow,
    defaultFlowPredicate,
    enclosingFlowLoops,
    enclosingFlowRepeats,
    flowBinding,
    flowBindingSchema,
    flowProducers,
    isRecordsFlowOutput,
    loopItemBinding,
    repeatStateBinding,
    FLOW_ALIAS_PATTERN,
    FLOW_COMPARISONS,
    FLOW_MAX_PREDICATE_DEPTH,
    FLOW_OUTPUT_KINDS,
    predicateSummary,
    scalarSchemaFields,
    type WorkflowFlowBinding,
    type WorkflowFlowSource,
    type WorkflowForEachNode,
    type WorkflowRepeatUntilNode,
    type FlowProducer,
    type WorkflowOperand,
    type WorkflowPredicate,
    type WorkflowScalar,
} from '../../lib/workflowFlow';
import type { WorkflowDefinition, WorkflowOutputContract, WorkflowOutputKind } from '../../lib/workflowEditor';
import { isRecord } from '../../lib/workspaceAuthoring';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

export function WorkflowFlowSourcePicker({ source, producers, loops = [], repeats = [], label, recordsOnly = false, onChange }: {
    source: WorkflowFlowSource;
    producers: FlowProducer[];
    loops?: WorkflowForEachNode[];
    repeats?: WorkflowRepeatUntilNode[];
    label: string;
    recordsOnly?: boolean;
    onChange: (source: WorkflowFlowSource, kind: WorkflowOutputKind) => void;
}) {
    const producer = source.kind === 'node_output' ? producers.find((item) => item.id === source.node_id) : undefined;
    const repeat = source.kind === 'repeat_state' ? repeats.find((item) => item.id === source.loop_id) : undefined;
    const setRepeat = (loop: WorkflowRepeatUntilNode | undefined, stateName?: string) => {
        const slot = stateName === undefined ? loop?.state[0] : loop?.state.find((item) => item.name === stateName);
        onChange({ kind: 'repeat_state', loop_id: loop?.id ?? '', state_name: stateName ?? slot?.name ?? '', scope: 'current' },
            slot?.output_contract.kind ?? 'any');
    };
    return <>
        {loops.length || repeats.length || source.kind !== 'node_output' ? <label className="min-w-0 text-xs text-text-2">
            Source
            <select className={inputClass} aria-label={`${label} source`} value={source.kind}
                onChange={(event) => {
                    if (event.target.value === 'loop_item') onChange({
                        kind: 'loop_item', loop_id: loops.at(-1)?.id ?? '', scope: 'current',
                    }, 'json');
                    else if (event.target.value === 'repeat_state') setRepeat(repeats.at(-1));
                    else onChange({
                        kind: 'node_output', node_id: producers[0]?.id ?? '', output: producers[0]?.outputs[0]?.name ?? '', scope: 'current',
                    }, producers[0]?.outputs[0]?.kind ?? 'any');
                }}>
                <option value="node_output">Saved node output</option>
                {loops.length || source.kind === 'loop_item' ? <option value="loop_item" disabled={!loops.length || recordsOnly}>Current loop item, key and index</option> : null}
                {repeats.length || source.kind === 'repeat_state' ? <option value="repeat_state" disabled={!repeats.length || recordsOnly}>Current Repeat state</option> : null}
            </select>
        </label> : null}
        {source.kind === 'node_output' ? <>
            <label className="min-w-0 text-xs text-text-2">
                Producer
                <select className={inputClass} aria-label={`${label} producer`} value={source.node_id}
                    onChange={(event) => {
                        const selected = producers.find((item) => item.id === event.target.value);
                        if (selected) onChange({ ...source, node_id: selected.id, output: selected.outputs[0]?.name ?? '' },
                            selected.outputs[0]?.kind ?? 'any');
                    }}>
                    {!producer ? <option value={source.node_id} disabled={recordsOnly}>Unavailable: {source.node_id || 'choose a producer'}</option> : null}
                    {producers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
            </label>
            <label className="min-w-0 text-xs text-text-2">
                Final output
                <select className={inputClass} aria-label={`${label} output`} value={source.output}
                    onChange={(event) => onChange({ ...source, output: event.target.value },
                        producer?.outputs.find((item) => item.name === event.target.value)?.kind ?? 'any')}>
                    {!producer?.outputs.some((item) => item.name === source.output) ? <option value={source.output} disabled={recordsOnly}>Unavailable: {source.output || 'choose an output'}</option> : null}
                    {producer?.outputs.map((output) => <option key={output.name} value={output.name}>{output.name}</option>)}
                </select>
            </label>
        </> : source.kind === 'loop_item' ? <label className="min-w-0 text-xs text-text-2">
            Current item from loop
            <select className={inputClass} aria-label={`${label} loop`} value={source.loop_id}
                onChange={(event) => onChange({ ...source, loop_id: event.target.value }, 'json')}>
                {!loops.some((loop) => loop.id === source.loop_id) ? <option value={source.loop_id}>Unavailable: {source.loop_id}</option> : null}
                {loops.map((loop) => <option key={loop.id} value={loop.id}>{loop.id}</option>)}
            </select>
            <span className="mt-1 block">JSON fields: value, key, index (zero-based). Only this visit or an enclosing loop's current item is available.</span>
        </label> : <>
            <label className="min-w-0 text-xs text-text-2">
                Enclosing Repeat
                <select className={inputClass} aria-label={`${label} Repeat`} value={source.loop_id}
                    onChange={(event) => setRepeat(repeats.find((item) => item.id === event.target.value))}>
                    {!repeat ? <option value={source.loop_id}>Unavailable: {source.loop_id || 'choose a Repeat'}</option> : null}
                    {repeats.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
                </select>
            </label>
            <label className="min-w-0 text-xs text-text-2">
                Current state slot
                <select className={inputClass} aria-label={`${label} state`} value={source.state_name}
                    onChange={(event) => setRepeat(repeat, event.target.value)}>
                    {!repeat?.state.some((slot) => slot.name === source.state_name) ? <option value={source.state_name}>Unavailable: {source.state_name || 'choose a state slot'}</option> : null}
                    {repeat?.state.map((slot, index) => <option key={index} value={slot.name}>{slot.name || '(name required)'} ({slot.output_contract.kind})</option>)}
                </select>
                <span className="mt-1 block">The saved state at the start of this round. It stays unchanged for the whole body, including nested blocks.</span>
            </label>
        </>}
    </>;
}

export function WorkflowFlowInputs({
    workflow,
    nodeId,
    bindings,
    onChange,
    label = 'Named inputs',
    availableIds,
    allowLoopItems = true,
    allowRepeatState = true,
    recordsOnly = false,
}: {
    workflow: WorkflowDefinition;
    nodeId: string;
    bindings: WorkflowFlowBinding[];
    onChange: (bindings: WorkflowFlowBinding[]) => void;
    label?: string;
    availableIds?: Set<string>;
    allowLoopItems?: boolean;
    allowRepeatState?: boolean;
    recordsOnly?: boolean;
}) {
    const available = availableIds ?? analyzeWorkflowFlow(workflow).available.get(nodeId) ?? new Set<string>();
    const producers = flowProducers(workflow).filter((producer) => available.has(producer.id))
        .map((producer) => recordsOnly ? { ...producer, outputs: producer.outputs.filter(isRecordsFlowOutput) } : producer)
        .filter((producer) => !recordsOnly || producer.outputs.length > 0);
    const loops = allowLoopItems && !recordsOnly ? enclosingFlowLoops(workflow, nodeId) : [];
    const repeats = allowRepeatState && !recordsOnly ? enclosingFlowRepeats(workflow, nodeId).filter((node) => node.state.length) : [];
    const update = (index: number, binding: WorkflowFlowBinding) =>
        onChange(bindings.map((current, position) => position === index ? binding : current));
    const add = () => {
        const producer = producers[0];
        const repeat = repeats.at(-1);
        if (!producer && !loops.length && !repeat) return;
        let number = 1;
        while (bindings.some((binding) => binding.name === `input${number}`)) number++;
        const next = producer ? {
            ...flowBinding(`input${number}`, producer.id, producer.outputs[0]?.name ?? 'authoritative'),
            expected_kind: producer.outputs[0]?.kind ?? 'any',
        } : loops.length ? loopItemBinding(`input${number}`, loops[loops.length - 1].id)
            : repeat ? repeatStateBinding(`input${number}`, repeat.id, repeat.state[0]) : undefined;
        if (next) onChange([...bindings, next]);
    };
    return (
        <fieldset className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <legend className="px-1 text-sm font-medium text-text-1">{label}</legend>
            <p className="text-xs text-text-3">
                Only these named saved values are consumed. A skipped producer never falls back to another task.
                {recordsOnly ? ' File export requires exactly one required records output. Partial output still needs this binding’s explicit acceptance and an eligible producer.' : ''}
            </p>
            {bindings.map((binding, index) => {
                const source = binding.source;
                return (
                    <div key={index} className="grid min-w-0 gap-3 rounded-lg bg-surface-sunken p-3 sm:grid-cols-2">
                        <label className="min-w-0 text-xs text-text-2">
                            Input name
                            <input className={inputClass} aria-label={`${label} input ${index + 1} name`}
                                value={binding.name} maxLength={64}
                                onChange={(event) => update(index, { ...binding, name: event.target.value })} />
                        </label>
                        <WorkflowFlowSourcePicker source={source} producers={producers} loops={loops} repeats={repeats}
                            label={`${label} input ${index + 1}`} recordsOnly={recordsOnly}
                            onChange={(nextSource, kind) => update(index, {
                                ...binding, source: nextSource, expected_kind: kind,
                                allow_partial: nextSource.kind === 'loop_item' ? false : binding.allow_partial,
                            })} />
                        <label className="text-xs text-text-2">
                            Expected kind
                            <select className={inputClass} aria-label={`${label} input ${index + 1} kind`}
                                value={binding.expected_kind} disabled={source.kind === 'loop_item'}
                                onChange={(event) => update(index, { ...binding, expected_kind: event.target.value as WorkflowOutputKind })}>
                                {FLOW_OUTPUT_KINDS.map((kind) => <option key={kind} value={kind}
                                    disabled={recordsOnly && kind !== 'records'}>{kind.replaceAll('_', ' ')}</option>)}
                            </select>
                        </label>
                        <label className="flex items-center gap-2 text-xs text-text-2">
                            <input type="checkbox" checked={binding.required}
                                aria-label={`${label} input ${index + 1} required`}
                                onChange={(event) => update(index, { ...binding, required: event.target.checked })} />
                            Required on every reaching path
                        </label>
                        <label className="flex items-center gap-2 text-xs text-text-2">
                            <input type="checkbox" checked={binding.allow_partial} disabled={source.kind === 'loop_item'}
                                aria-label={`${label} input ${index + 1} allow partial`}
                                onChange={(event) => update(index, { ...binding, allow_partial: event.target.checked })} />
                            Accept eligible completed partial output
                        </label>
                        <GlassButton size="sm" variant="danger" aria-label={`${label} remove input ${index + 1}`}
                            onClick={() => onChange(bindings.filter((_, position) => position !== index))}>
                            <Trash2 size={14} /> Remove input
                        </GlassButton>
                    </div>
                );
            })}
            <GlassButton size="sm" disabled={(!producers.length && !loops.length && !repeats.length) || bindings.length >= (recordsOnly ? 1 : 100)} onClick={add}
                aria-label={`Add ${label.toLowerCase()} input`}>
                <Plus size={14} /> Add input
            </GlassButton>
            {!producers.length && !loops.length && !repeats.length ? <p className="text-xs text-text-3">
                {recordsOnly
                    ? 'No reachable saved records output is available. Declare records on an earlier task, Collect, or explicit join; text, scalar JSON, and document results are not file-export sources.'
                    : 'Add a reachable producer before this node to bind its output.'}
            </p> : null}
        </fieldset>
    );
}

function OperandEditor({
    value,
    bindings,
    workflow,
    onChange,
    label,
    inputOnly = false,
}: {
    value: WorkflowOperand;
    bindings: WorkflowFlowBinding[];
    workflow: WorkflowDefinition;
    onChange: (value: WorkflowOperand) => void;
    label: string;
    inputOnly?: boolean;
}) {
    const mode = 'input' in value ? 'input' : 'literal';
    const binding = 'input' in value ? bindings.find((item) => item.name === value.input) : undefined;
    const schema = flowBindingSchema(workflow, binding);
    const fields = scalarSchemaFields(schema);
    if (inputOnly && schema && !fields.some((field) => field.path === '')) {
        fields.unshift({ path: '', type: String(schema.type ?? 'value') });
    }
    const firstField = (name: string): WorkflowOperand => {
        const selected = bindings.find((item) => item.name === name);
        return { input: name, path: scalarSchemaFields(flowBindingSchema(workflow, selected))[0]?.path ?? '' };
    };
    const literalType = 'literal' in value ? value.literal === null ? 'null' : typeof value.literal : 'boolean';
    return (
        <fieldset className="min-w-0 space-y-2 rounded-lg border border-edge p-3">
            <legend className="px-1 text-xs text-text-2">{label}</legend>
            {!inputOnly ? (
                <label className="block text-xs text-text-2">
                    Value source
                    <select className={inputClass} aria-label={`${label} value source`} value={mode}
                        onChange={(event) => onChange(event.target.value === 'input'
                            ? firstField(bindings[0]?.name ?? '') : { literal: true })}>
                        <option value="input">Named input field</option>
                        <option value="literal">Typed value</option>
                    </select>
                </label>
            ) : null}
            {'input' in value ? (
                <>
                    <label className="block text-xs text-text-2">
                        Named input
                        <select className={inputClass} aria-label={`${label} input`} value={value.input}
                            onChange={(event) => onChange(firstField(event.target.value))}>
                            {!bindings.some((item) => item.name === value.input) ? <option value={value.input}>Choose input</option> : null}
                            {bindings.map((item, index) => <option key={index} value={item.name}>{item.name || '(name required)'}</option>)}
                        </select>
                    </label>
                    <label className="block text-xs text-text-2">
                        Validated field
                        <select className={inputClass} aria-label={`${label} field`} value={value.path}
                            onChange={(event) => onChange({ ...value, path: event.target.value })}>
                            {!fields.some((field) => field.path === value.path) ? (
                                <option value={value.path}>{value.path ? `Saved field: ${value.path}` : 'Choose field'}</option>
                            ) : null}
                            {fields.map((field) => <option key={field.path} value={field.path}>{field.path || '(whole value)'} ({field.type})</option>)}
                        </select>
                    </label>
                    {!fields.length ? (
                        <p className="text-xs text-warn">Declare typed decision fields in the producer's JSON output contract first.</p>
                    ) : null}
                </>
            ) : (
                <>
                    <label className="block text-xs text-text-2">
                        Value type
                        <select className={inputClass} aria-label={`${label} type`} value={literalType}
                            onChange={(event) => {
                                const defaults: Record<string, WorkflowScalar> = { boolean: true, number: 0, string: '', null: null };
                                onChange({ literal: defaults[event.target.value] });
                            }}>
                            <option value="boolean">Boolean</option>
                            <option value="number">Number</option>
                            <option value="string">Text / enum value</option>
                            <option value="null">Null (present but empty)</option>
                        </select>
                    </label>
                    {typeof value.literal === 'boolean' ? (
                        <label className="block text-xs text-text-2">
                            Boolean value
                            <select className={inputClass} aria-label={`${label} value`} value={String(value.literal)}
                                onChange={(event) => onChange({ literal: event.target.value === 'true' })}>
                                <option value="true">true</option><option value="false">false</option>
                            </select>
                        </label>
                    ) : typeof value.literal === 'number' ? (
                        <label className="block text-xs text-text-2">
                            Number
                            <input className={inputClass} type="number" step="any" aria-label={`${label} value`}
                                value={Number.isFinite(value.literal) ? value.literal : ''}
                                onChange={(event) => onChange({ literal: event.currentTarget.valueAsNumber })} />
                        </label>
                    ) : typeof value.literal === 'string' ? (
                        <label className="block text-xs text-text-2">
                            Text value (case-sensitive)
                            <input className={inputClass} aria-label={`${label} value`} value={value.literal}
                                onChange={(event) => onChange({ literal: event.target.value })} />
                        </label>
                    ) : <p className="text-xs text-text-3">Null is different from a missing field. Use Exists to handle absence.</p>}
                </>
            )}
        </fieldset>
    );
}

export function WorkflowConditionEditor({
    value,
    bindings,
    workflow,
    onChange,
    label = 'Condition',
    depth = 1,
}: {
    value: WorkflowPredicate;
    bindings: WorkflowFlowBinding[];
    workflow: WorkflowDefinition;
    onChange: (condition: WorkflowPredicate) => void;
    label?: string;
    depth?: number;
}) {
    const operation = (op: string) => {
        const left: WorkflowOperand = 'left' in value ? value.left : value.op === 'exists'
            ? value.value : { input: bindings[0]?.name ?? '', path: '' };
        if (op === 'all' || op === 'any') {
            onChange({ op, conditions: value.op === 'all' || value.op === 'any' ? value.conditions : [value] });
        } else if (op === 'not') {
            onChange({ op, condition: value });
        } else if (op === 'exists') {
            onChange({ op, value: 'input' in left ? left : { input: bindings[0]?.name ?? '', path: '' } });
        } else {
            const comparison = FLOW_COMPARISONS.find((item) => item === op);
            if (comparison) onChange({ op: comparison, left, right: 'right' in value ? value.right : { literal: true } });
        }
    };
    return (
        <div className="min-w-0 space-y-3 rounded-xl border border-edge p-3" aria-label={label}>
            <label className="block text-sm font-medium text-text-1">
                {label}
                <select className={inputClass} aria-label={`${label} operation`} value={value.op}
                    onChange={(event) => operation(event.target.value)}>
                    <option value="eq">Equals</option><option value="ne">Does not equal</option>
                    <option value="lt">Less than</option><option value="lte">Less than or equal</option>
                    <option value="gt">Greater than</option><option value="gte">Greater than or equal</option>
                    <option value="exists">Exists</option>
                    <option value="all" disabled={depth >= FLOW_MAX_PREDICATE_DEPTH}>All conditions (AND)</option>
                    <option value="any" disabled={depth >= FLOW_MAX_PREDICATE_DEPTH}>Any condition (OR)</option>
                    <option value="not" disabled={depth >= FLOW_MAX_PREDICATE_DEPTH}>Not</option>
                </select>
            </label>
            {value.op === 'all' || value.op === 'any' ? (
                <div className="space-y-3 border-l border-edge pl-2 sm:pl-3">
                    {value.conditions.map((condition, index) => (
                        <div key={index} className="space-y-2">
                            <WorkflowConditionEditor value={condition} bindings={bindings} workflow={workflow}
                                label={`${label} rule ${index + 1}`} depth={depth + 1}
                                onChange={(next) => onChange({ ...value, conditions: value.conditions.map((item, position) => position === index ? next : item) })} />
                            <GlassButton size="sm" variant="danger" disabled={value.conditions.length <= 1}
                                onClick={() => onChange({ ...value, conditions: value.conditions.filter((_, position) => position !== index) })}
                                aria-label={`Remove ${label} rule ${index + 1}`}><Trash2 size={14} /> Remove rule</GlassButton>
                        </div>
                    ))}
                    <GlassButton size="sm" disabled={depth >= FLOW_MAX_PREDICATE_DEPTH}
                        onClick={() => onChange({ ...value, conditions: [...value.conditions, defaultFlowPredicate(bindings[0]?.name)] })}
                        aria-label={`Add ${label} rule`}><Plus size={14} /> Add condition</GlassButton>
                </div>
            ) : value.op === 'not' ? (
                <WorkflowConditionEditor value={value.condition} bindings={bindings} workflow={workflow} depth={depth + 1}
                    label={`${label} negated`} onChange={(condition) => onChange({ ...value, condition })} />
            ) : value.op === 'exists' ? (
                <OperandEditor value={value.value} bindings={bindings} workflow={workflow} inputOnly
                    label={`${label} field`} onChange={(field) => onChange({ ...value, value: field })} />
            ) : 'left' in value ? (
                <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                    <OperandEditor value={value.left} bindings={bindings} workflow={workflow}
                        label={`${label} left`} onChange={(left) => onChange({ ...value, left })} />
                    <OperandEditor value={value.right} bindings={bindings} workflow={workflow}
                        label={`${label} right`} onChange={(right) => onChange({ ...value, right })} />
                </div>
            ) : null}
            {depth === 1 ? (
                <>
                    <p className="break-words text-xs text-text-2">{predicateSummary(value)}</p>
                    <p className="text-xs text-text-3">
                        Evaluated by the server from validated data. Missing values need an Exists guard; null, false, and zero are distinct values.
                    </p>
                </>
            ) : null}
        </div>
    );
}

export function WorkflowDecisionFields({
    contract,
    onChange,
}: {
    contract: WorkflowOutputContract;
    onChange: (contract: WorkflowOutputContract) => void;
}) {
    const [name, setName] = useState('');
    const [type, setType] = useState('boolean');
    const [enumText, setEnumText] = useState('');
    const collection = ['records', 'document_results'].includes(contract.kind);
    const schema = collection
        ? isRecord(contract.schema?.items) ? contract.schema.items : { type: 'object' }
        : contract.schema ?? { type: 'object' };
    if ((!collection && contract.kind !== 'json') || (schema.type !== undefined && schema.type !== 'object') ||
        collection && contract.schema?.type !== undefined && contract.schema.type !== 'array') return null;
    const fieldLabel = collection ? 'Record' : 'Decision';
    const updateSchema = (next: Record<string, unknown>) => onChange({
        ...contract, schema: collection ? { ...contract.schema, type: 'array', items: next } : next,
    });
    const properties = isRecord(schema.properties) ? schema.properties : {};
    const required = Array.isArray(schema.required) ? schema.required.filter((item): item is string => typeof item === 'string') : [];
    const enumValues = enumText.split('\n').map((item) => item.trim()).filter(Boolean);
    const validName = FLOW_ALIAS_PATTERN.test(name) && !Object.hasOwn(properties, name);
    const validEnum = type !== 'enum' || (enumValues.length > 0 && new Set(enumValues).size === enumValues.length);
    return (
        <fieldset className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <legend className="px-1 text-sm font-medium text-text-1">{collection ? 'Record schema fields' : 'Structured decision fields'}</legend>
            <p className="text-xs text-text-3">
                {collection ? 'Declare the fields of each record without writing JSON. These validate the complete saved collection and expose typed current-item fields inside a record loop.'
                    : 'Declare Boolean, numeric, or enum fields for If/else, Run when, and Repeat stop conditions. The saved JSON value must contain these fields.'}
            </p>
            {Object.entries(properties).map(([fieldName, field]) => (
                <div key={fieldName} className="flex flex-wrap items-center gap-3 text-xs text-text-2">
                    <span className="min-w-0 flex-1 break-all">{fieldName} ({isRecord(field) ? String(field.type ?? 'custom schema') : 'custom schema'})</span>
                    <label className="flex items-center gap-2">
                        <input type="checkbox" aria-label={`Require ${fieldLabel.toLowerCase()} field ${fieldName}`} checked={required.includes(fieldName)}
                            onChange={(event) => updateSchema({
                                ...schema, required: event.target.checked ? [...required, fieldName] : required.filter((item) => item !== fieldName),
                            })} />
                        Required
                    </label>
                    <GlassButton size="sm" variant="danger" aria-label={`Remove ${fieldLabel.toLowerCase()} field ${fieldName}`} onClick={() => {
                        const next = { ...properties };
                        delete next[fieldName];
                        updateSchema({ ...schema, properties: next, required: required.filter((item) => item !== fieldName) });
                    }}><Trash2 size={14} /></GlassButton>
                </div>
            ))}
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <label className="text-xs text-text-2">
                    New field name
                    <input className={inputClass} aria-label={`${fieldLabel} field name`} value={name} maxLength={64}
                        placeholder="pass" onChange={(event) => setName(event.target.value)} />
                </label>
                <label className="text-xs text-text-2">
                    Field type
                    <select className={inputClass} aria-label={`${fieldLabel} field type`} value={type} onChange={(event) => setType(event.target.value)}>
                        <option value="boolean">Boolean</option><option value="number">Number</option>
                        <option value="integer">Integer</option><option value="string">Text</option><option value="enum">Enum (text choices)</option>
                    </select>
                </label>
            </div>
            {type === 'enum' ? (
                <label className="block text-xs text-text-2">
                    Allowed values, one per line
                    <textarea className={inputClass} aria-label={`${fieldLabel} enum values`} value={enumText}
                        onChange={(event) => setEnumText(event.target.value)} />
                </label>
            ) : null}
            <GlassButton size="sm" disabled={!validName || !validEnum} onClick={() => {
                updateSchema({
                    ...schema, type: 'object',
                    properties: { ...properties, [name]: type === 'enum' ? { type: 'string', enum: enumValues } : { type } },
                    required: [...required, name],
                });
                setName('');
                setEnumText('');
            }}><Plus size={14} /> Add {fieldLabel.toLowerCase()} field</GlassButton>
            {name && !validName ? <p role="status" className="text-xs text-warn">Use a unique field name starting with a letter.</p> : null}
            {!validEnum ? <p role="status" className="text-xs text-warn">Add at least one unique enum value.</p> : null}
        </fieldset>
    );
}
