// WorkflowRepeatFields.tsx
// Explicit typed state and per-batch limits for post-body Repeat until.

import { useEffect, useRef } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { WorkflowDecisionFields, WorkflowFlowSourcePicker } from './WorkflowConditionEditor';
import { useWorkflowFieldDrafts, type WorkflowFieldDraftOwner } from './WorkflowFieldDrafts';
import {
    analyzeWorkflowFlow,
    enclosingFlowRepeats,
    flowProducers,
    flowSourceOutput,
    MAX_REPEAT_ITERATIONS,
    REPEAT_STATE_KINDS,
    repeatIterationErrors,
    workflowRepeatLimit,
    type WorkflowRepeatState,
    type WorkflowRepeatUntilNode,
} from '../../lib/workflowFlow';
import type { WorkflowDefinition, WorkflowEditorOptions } from '../../lib/workflowEditor';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

export function WorkflowRepeatFields({ node, workflow, options, onChange }: {
    node: WorkflowRepeatUntilNode;
    workflow: WorkflowDefinition;
    options: WorkflowEditorOptions;
    onChange: (node: WorkflowRepeatUntilNode) => void;
}) {
    const drafts = useWorkflowFieldDrafts();
    const draftOwner: WorkflowFieldDraftOwner = ['node', node.id];
    const stateRowIds = drafts.repeatStateRowIds(draftOwner, node.state.length);
    const maximumRef = useRef<HTMLInputElement>(null);
    const initialMaximumUnset = useRef(!Number.isFinite(node.max_iterations));
    const lastStateRef = useRef<HTMLInputElement>(null);
    const stateCount = useRef(node.state.length);
    const ceiling = workflowRepeatLimit(options);
    const errors = repeatIterationErrors(node, ceiling);
    const available = analyzeWorkflowFlow(workflow).available.get(node.id) ?? new Set<string>();
    const producers = flowProducers(workflow).filter((producer) => available.has(producer.id));
    const repeats = enclosingFlowRepeats(workflow, node.id);
    const update = (index: number, slot: WorkflowRepeatState) =>
        onChange({ ...node, state: node.state.map((item, position) => position === index ? slot : item) });

    useEffect(() => {
        if (initialMaximumUnset.current) maximumRef.current?.focus();
    }, []);
    useEffect(() => {
        if (node.state.length > stateCount.current) lastStateRef.current?.focus();
        stateCount.current = node.state.length;
    }, [node.state.length]);

    return <>
        <label className="block text-sm font-medium text-text-1">
            Maximum rounds before manual continuation
            <input ref={maximumRef} className={inputClass} type="number" min={1} max={MAX_REPEAT_ITERATIONS} step={1}
                aria-label="Maximum rounds before manual continuation" aria-required="true"
                value={Number.isFinite(node.max_iterations) ? node.max_iterations : ''}
                placeholder="Choose an explicit maximum"
                onChange={(event) => onChange({ ...node, max_iterations: event.currentTarget.valueAsNumber })} />
        </label>
        <p className="text-xs text-text-3">
            Administrator ceiling: {ceiling ?? 'unavailable'} rounds per automatic batch. Technical ceiling: 1,000.
            The body runs at least once. If the condition is still false at the maximum, the run pauses for an authorized person's explicit continuation.
        </p>
        <p className="rounded-lg bg-warn-soft p-3 text-xs text-warn">
            Another batch never resets lifetime rounds, execution admissions, or the elapsed deadline, including time spent waiting.
            The run's separate limits (at most 5,000 admissions and 86,400 seconds) may stop it sooner.
        </p>
        {errors.length ? <div role="alert" className="rounded-lg bg-danger-soft p-3 text-xs text-danger">
            {errors.map((error) => <p key={error}>{error}</p>)}
        </div> : null}
        <fieldset className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
            <legend className="px-1 text-sm font-semibold text-text-1">Repeat state</legend>
            <p className="text-xs text-text-3">
                Initialize each named slot from an earlier saved output or an enclosing Repeat's current state, never a literal or latest-result lookup.
                All next slots are validated and saved together after the body. To leave a slot unchanged, explicitly pass its current state through a body output.
            </p>
            {node.state.map((slot, index) => {
                const label = `State ${index + 1}`;
                const contract = slot.output_contract;
                const initialOutput = flowSourceOutput(workflow, slot.initial);
                const typedProducers = producers.map((producer) => ({
                    ...producer, outputs: producer.outputs.filter((output) =>
                        (output.kinds ?? [output.kind]).every((kind) => kind === contract.kind)),
                })).filter((producer) => producer.outputs.length);
                const schemaType = typeof contract.schema?.type === 'string' ? contract.schema.type : '';
                return <fieldset key={stateRowIds[index]} className="min-w-0 space-y-3 rounded-lg bg-surface-sunken p-3">
                    <legend className="px-1 text-xs font-semibold text-text-2">{label}</legend>
                    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                        <label className="text-xs text-text-2">
                            State name
                            <input ref={index === node.state.length - 1 ? lastStateRef : undefined}
                                className={inputClass} aria-label={`${label} name`} value={slot.name} maxLength={64}
                                onChange={(event) => update(index, { ...slot, name: event.target.value })} />
                        </label>
                        <label className="text-xs text-text-2">
                            State kind
                            <select className={inputClass} aria-label={`${label} kind`} value={contract.kind}
                                onChange={(event) => {
                                    const kind = REPEAT_STATE_KINDS.find((value) => value === event.target.value);
                                    if (kind) update(index, { ...slot, output_contract: { ...contract, kind } });
                                }}>
                                {REPEAT_STATE_KINDS.map((kind) => <option key={kind} value={kind}>{kind.replaceAll('_', ' ')}</option>)}
                            </select>
                        </label>
                        <WorkflowFlowSourcePicker source={slot.initial} producers={typedProducers} repeats={repeats}
                            label={`${label} initial`}
                            onChange={(source) => {
                                if (source.kind !== 'loop_item') update(index, { ...slot, initial: source });
                            }} />
                        <label className="text-xs text-text-2">
                            Next state after the body
                            <select className={inputClass} aria-label={`${label} next body output`} value={slot.next}
                                onChange={(event) => update(index, { ...slot, next: event.target.value })}>
                                {!node.body.outputs.some((binding) => binding.name === slot.next) ? <option value={slot.next}>
                                    {slot.next ? `Unavailable: ${slot.next}` : 'Choose a required body output'}
                                </option> : null}
                                {node.body.outputs.map((binding, position) => <option key={position} value={binding.name}>
                                    {binding.name || '(name required)'} ({binding.expected_kind})
                                </option>)}
                            </select>
                        </label>
                    </div>
                    {contract.kind === 'json' ? <label className="block text-xs text-text-2">
                        JSON shape
                        <select className={inputClass} aria-label={`${label} JSON shape`} value={schemaType}
                            onChange={(event) => update(index, { ...slot, output_contract: { ...contract, schema: { type: event.target.value } } })}>
                            {!['object', 'boolean', 'number', 'integer', 'string', 'null'].includes(schemaType) ? <option value={schemaType}>
                                {contract.schema ? 'Preserved saved schema' : 'Choose a validated shape or add decision fields'}
                            </option> : null}
                            <option value="object">Object with typed decision fields</option>
                            <option value="boolean">Boolean</option><option value="number">Number</option>
                            <option value="integer">Integer</option><option value="string">Text</option><option value="null">Null</option>
                        </select>
                    </label> : null}
                    {initialOutput?.schema && initialOutput.kind === contract.kind ? <GlassButton size="sm"
                        aria-label={`${label} use initial schema`} onClick={() => update(index, {
                            ...slot, output_contract: { ...contract, schema: structuredClone(initialOutput.schema) },
                        })}>Use initial output's declared schema</GlassButton> : null}
                    <WorkflowDecisionFields draftOwner={draftOwner} draftPath={['state', stateRowIds[index], 'decision']} contract={{
                        ...contract, allow_partial: contract.allow_partial === true,
                        require_complete_coverage: contract.require_complete_coverage === true,
                    }} onChange={(next) => update(index, { ...slot, output_contract: { ...next, kind: contract.kind } })} />
                    {contract.kind !== 'text' ? <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                        <label className="text-xs text-text-2">
                            Expected count (optional)
                            <input className={inputClass} type="number" min={0} step={1} aria-label={`${label} expected count`}
                                value={contract.expected_count !== undefined && Number.isFinite(contract.expected_count) ? contract.expected_count : ''}
                                onChange={(event) => {
                                    const next = { ...contract };
                                    if (!event.target.value) delete next.expected_count;
                                    else next.expected_count = event.currentTarget.valueAsNumber;
                                    update(index, { ...slot, output_contract: next });
                                }} />
                        </label>
                        {contract.kind === 'records' ? <label className="text-xs text-text-2">
                            Record identity field (optional)
                            <input className={inputClass} aria-label={`${label} identity field`} value={contract.identity_field ?? ''}
                                onChange={(event) => {
                                    const next = { ...contract };
                                    if (!event.target.value) delete next.identity_field;
                                    else next.identity_field = event.target.value;
                                    update(index, { ...slot, output_contract: next });
                                }} />
                        </label> : null}
                    </div> : null}
                    <label className="flex items-center gap-2 text-xs text-text-2">
                        <input type="checkbox" aria-label={`${label} require complete coverage`} checked={contract.require_complete_coverage === true}
                            onChange={(event) => update(index, { ...slot, output_contract: { ...contract, require_complete_coverage: event.target.checked } })} />
                        Require complete coverage
                    </label>
                    <label className="flex items-center gap-2 text-xs text-text-2">
                        <input type="checkbox" aria-label={`${label} allow partial`} checked={contract.allow_partial === true}
                            onChange={(event) => update(index, { ...slot, output_contract: { ...contract, allow_partial: event.target.checked } })} />
                        Accept eligible completed partial state
                    </label>
                    <p className={`text-xs ${contract.allow_partial ? 'text-warn' : 'text-text-3'}`}>
                        {contract.allow_partial
                            ? 'Partial coverage and limitations stay attached in later rounds and final output. Producers and consuming bindings must also explicitly accept partial data. Invalid or unauthorized data is never eligible.'
                            : 'Partial data is rejected by default. Manual continuation cannot bypass validation or authorize missing data.'}
                    </p>
                    <GlassButton size="sm" variant="danger" aria-label={`Remove ${label.toLowerCase()}`}
                        onClick={() => {
                            drafts.removeRepeatStateRow(draftOwner, stateRowIds[index]);
                            onChange({ ...node, state: node.state.filter((_, position) => position !== index) });
                        }}>
                        <Trash2 size={14} /> Remove state
                    </GlassButton>
                </fieldset>;
            })}
            <GlassButton size="sm" disabled={node.state.length >= 100} onClick={() => {
                let name = 'state';
                let number = 2;
                while (node.state.some((slot) => slot.name === name)) name = `state${number++}`;
                onChange({ ...node, state: [...node.state, {
                    name, initial: { kind: 'node_output', node_id: '', output: '', scope: 'current' }, next: '',
                    output_contract: { kind: 'text', allow_partial: false, require_complete_coverage: false },
                }] });
            }}><Plus size={14} /> Add state slot</GlassButton>
        </fieldset>
    </>;
}

export function WorkflowRepeatExports({ node, onChange }: {
    node: WorkflowRepeatUntilNode;
    onChange: (node: WorkflowRepeatUntilNode) => void;
}) {
    return <fieldset className="min-w-0 space-y-3 rounded-xl border border-edge p-3">
        <legend className="px-1 text-sm font-semibold text-text-1">Repeat final exports</legend>
        <p className="text-xs text-text-3">These named outputs become available only after the stop condition is true. A batch-limit pause does not publish final outputs.</p>
        {node.exports.map((item, index) => <div key={index} className="grid min-w-0 gap-3 rounded-lg bg-surface-sunken p-3 sm:grid-cols-2">
            <label className="text-xs text-text-2">
                Final export name
                <input className={inputClass} aria-label={`Repeat export ${index + 1} name`} value={item.name} maxLength={64}
                    onChange={(event) => onChange({ ...node, exports: node.exports.map((value, position) =>
                        position === index ? { ...value, name: event.target.value } : value) })} />
            </label>
            <label className="text-xs text-text-2">
                Body output
                <select className={inputClass} aria-label={`Repeat export ${index + 1} output`} value={item.output}
                    onChange={(event) => onChange({ ...node, exports: node.exports.map((value, position) =>
                        position === index ? { ...value, output: event.target.value } : value) })}>
                    {!node.body.outputs.some((binding) => binding.name === item.output) ? <option value={item.output}>
                        {item.output ? `Unavailable: ${item.output}` : 'Choose a body output'}
                    </option> : null}
                    {node.body.outputs.map((binding, position) => <option key={position} value={binding.name}>{binding.name || '(name required)'}</option>)}
                </select>
            </label>
            <GlassButton size="sm" variant="danger" aria-label={`Remove Repeat export ${index + 1}`}
                onClick={() => onChange({ ...node, exports: node.exports.filter((_, position) => position !== index) })}>
                <Trash2 size={14} /> Remove export
            </GlassButton>
        </div>)}
        <GlassButton size="sm" disabled={node.exports.length >= 100} onClick={() => {
            let name = 'report';
            let number = 2;
            while (node.exports.some((item) => item.name === name)) name = `report${number++}`;
            onChange({ ...node, exports: [...node.exports, { name, output: '' }] });
        }}><Plus size={14} /> Add Repeat export</GlassButton>
    </fieldset>;
}
