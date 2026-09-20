// WorkflowDefinitionInspector.tsx
// Bounded configuration inspection shared by diagram and textual structure selection.

import { useEffect, useState } from 'react';
import { ApiError } from '../../lib/apiClient';
import {
    fetchWorkflowInspectionDetails, INSPECTION_SECTIONS, inspectionSourceKey, workflowInspectionBindings,
    type InspectionJson, type WorkflowFlowProjection, type WorkflowInspectionDetails,
    type WorkflowInspectionNode, type WorkflowInspectionSection, type WorkflowInspectionTarget,
} from '../../lib/workflowInspection';
import { isFlowBinding, isFlowPredicate, predicateSummary } from '../../lib/workflowFlow';
import { workflowErrorMessage, workflowScopeKey, type WorkflowScope } from '../../lib/workflowEditor';
import { GlassButton } from '../ui/primitives';

const sectionLabels: Record<WorkflowInspectionSection, string> = {
    configuration: 'Configuration', inputs: 'Typed inputs', condition: 'Condition',
    outputs: 'Declared outputs', state: 'Authored Repeat state', selection: 'Source selection',
};

function DetailValue({ value, onSelectNode }: { value: InspectionJson; onSelectNode: (id: string) => void }) {
    if (isFlowBinding(value)) {
        const source = value.source;
        const producerId = source.kind === 'node_output' ? source.node_id : source.loop_id;
        const output = source.kind === 'node_output' ? source.output
            : source.kind === 'repeat_state' ? `current state ${source.state_name}` : 'current frozen item';
        return <div className="space-y-1">
            <p>{value.name}: {value.expected_kind}. {value.required ? 'Required' : 'Optional'}.
                {' '}{value.allow_partial ? 'Explicitly accepts partial data.' : 'Does not accept partial output.'}</p>
            <GlassButton size="sm" onClick={() => onSelectNode(producerId)}>Inspect producer {producerId}</GlassButton>
            <p>Source: {source.kind}; output: {output}; scope: current instance.</p>
        </div>;
    }
    if (isFlowPredicate(value)) return <div className="space-y-2">
        <p className="break-words">{predicateSummary(value)}</p>
        <details>
            <summary className="cursor-pointer text-xs">Exact normalized condition</summary>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(value, null, 2)}</pre>
        </details>
    </div>;
    if (typeof value === 'string') return <p className="whitespace-pre-wrap break-words">{value || '(empty text)'}</p>;
    return <pre className="max-h-80 max-w-full overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-sunken p-2 text-xs">
        {JSON.stringify(value, null, 2)}
    </pre>;
}

export function WorkflowDefinitionInspector({
    scope, target, projection, node, onSelectNode, onDetailsChange, onUnavailable,
}: {
    scope: WorkflowScope;
    target: WorkflowInspectionTarget;
    projection: WorkflowFlowProjection;
    node: WorkflowInspectionNode;
    onSelectNode: (id: string) => void;
    onDetailsChange: (details: WorkflowInspectionDetails | null) => void;
    onUnavailable: (status: number) => void;
}) {
    const [section, setSection] = useState<WorkflowInspectionSection>('configuration');
    const [cursor, setCursor] = useState<string | null>(null);
    const [previousCursors, setPreviousCursors] = useState<(string | null)[]>([]);
    const [refresh, setRefresh] = useState(0);
    const [details, setDetails] = useState<WorkflowInspectionDetails | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const sourceKey = inspectionSourceKey(projection.source);
    const scopeKey = workflowScopeKey(scope);

    useEffect(() => {
        const controller = new AbortController();
        setDetails(null);
        onDetailsChange(null);
        setLoading(true);
        setError('');
        void fetchWorkflowInspectionDetails(scope, target, projection.source, node.id, section, cursor, controller.signal)
            .then((page) => {
                if (controller.signal.aborted) return;
                if (workflowInspectionBindings(node, page).some((binding) => !projection.nodes.some((producer) => producer.id === binding.sourceId))) {
                    throw new Error('This detail refers to a producer outside the selected compiled definition.');
                }
                setDetails(page);
                onDetailsChange(page);
                setLoading(false);
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return;
                setDetails(null);
                onDetailsChange(null);
                setLoading(false);
                setError(workflowErrorMessage(cause, 'Could not read this node configuration.'));
                if (cause instanceof ApiError && [401, 403, 404, 409].includes(cause.status)) onUnavailable(cause.status);
            });
        return () => controller.abort();
    }, [scopeKey, target, sourceKey, node.id, section, cursor, refresh, onDetailsChange, onUnavailable]);

    const sections = INSPECTION_SECTIONS.filter((item) =>
        item === 'configuration' || item === 'inputs' && node.inputs_count > 0 ||
        item === 'outputs' && node.outputs_count > 0 || item === 'condition' && node.has_condition ||
        item === 'state' && node.kind === 'repeat_until' ||
        item === 'selection' && (['for_each', 'task'].includes(node.kind) || node.id === projection.root_region_id));
    const related = projection.edges.filter((edge) => edge.source === node.id || edge.target === node.id);
    const records = new Map(projection.nodes.map((item) => [item.id, item]));
    const bindings = workflowInspectionBindings(node, details);

    return <div className="min-w-0 space-y-3" aria-label="Read-only node configuration">
        <p className="break-all text-xs text-text-3">Canonical node: {node.id}{node.task_id ? `; task: ${node.task_id}` : ''}</p>
        <label className="block text-sm text-text-2">
            Inspection section
            <select aria-label="Inspection section" value={section}
                className="mt-1 w-full rounded-lg border border-edge bg-surface-1 p-2 text-sm"
                onChange={(event) => {
                    const next = sections.find((item) => item === event.target.value);
                    if (next) {
                        setSection(next);
                        setCursor(null);
                        setPreviousCursors([]);
                        setDetails(null);
                        onDetailsChange(null);
                    }
                }}>
                {sections.map((item) => <option key={item} value={item}>{sectionLabels[item]}</option>)}
            </select>
        </label>
        <div className="flex flex-wrap gap-2">
            <GlassButton size="sm" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>Refresh node details</GlassButton>
            <GlassButton size="sm" disabled={loading || previousCursors.length === 0} onClick={() => {
                setCursor(previousCursors.at(-1) ?? null);
                setPreviousCursors((pages) => pages.slice(0, -1));
            }}>Previous details page</GlassButton>
            <GlassButton size="sm" disabled={loading || !details?.next_cursor} onClick={() => {
                if (details?.next_cursor) {
                    setPreviousCursors((pages) => [...pages, cursor]);
                    setCursor(details.next_cursor);
                }
            }}>Next details page</GlassButton>
        </div>
        {loading ? <p role="status" className="text-sm text-text-3">Loading selected configuration...</p> : null}
        {error ? <p role="alert" className="rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p> : null}
        {details ? <>
            <p className="text-xs text-text-3">Showing {details.items.length} of {details.total_count} {sectionLabels[section].toLowerCase()} entries.
                {details.next_cursor ? ' More entries are available on the next page.' : ''}</p>
            <dl className="min-w-0 space-y-3">
                {details.items.map((item, index) => <div key={`${cursor}:${index}`} className="min-w-0 rounded-lg border border-edge p-3">
                    <dt className="mb-1 break-words text-sm font-semibold text-text-1">{item.label}</dt>
                    <dd className="min-w-0 text-sm text-text-2"><DetailValue value={item.value} onSelectNode={onSelectNode} /></dd>
                </div>)}
            </dl>
            {!details.items.length ? <p className="text-sm text-text-3">No entries are declared in this section.</p> : null}
            {bindings.length ? <div className="space-y-2">
                <p className="text-xs text-text-3">Declared data connections on this page: {bindings.length}. These are not runtime result values.</p>
                <ul aria-label="Declared data connections" className="space-y-2 text-xs text-text-2">
                    {bindings.map((binding, index) => <li key={index} className="flex flex-wrap items-center gap-2">
                        <span>{binding.label}</span>
                        <GlassButton size="sm" onClick={() => onSelectNode(binding.sourceId)}>
                            Inspect source {records.get(binding.sourceId)?.label ?? binding.sourceId}
                        </GlassButton>
                    </li>)}
                </ul>
            </div> : null}
        </> : null}
        {related.length ? <details className="rounded-lg border border-edge p-3">
            <summary className="cursor-pointer text-sm font-medium text-text-1">Control-flow relationships ({related.length})</summary>
            <ul aria-label="Control-flow relationships" className="mt-2 space-y-2 text-xs text-text-2">
                {related.map((edge) => {
                    const destination = edge.source === node.id ? edge.target : edge.source;
                    return <li key={edge.id} className="flex flex-wrap items-center gap-2">
                        <span>{edge.source === node.id ? 'To' : 'From'}: {edge.label || edge.kind}.</span>
                        <GlassButton size="sm" onClick={() => onSelectNode(destination)}>{records.get(destination)?.label ?? destination}</GlassButton>
                    </li>;
                })}
            </ul>
        </details> : null}
    </div>;
}
