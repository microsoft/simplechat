// WorkflowLoopFields.tsx
// Serial loop sources and exact Collect controls over the saved region tree.

import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { WorkflowDocumentPicker } from './WorkflowDocumentPicker';
import { WorkflowLoopSelectionDetails } from './WorkflowLoopSelectionDetails';
import { WorkflowDecisionFields } from './WorkflowConditionEditor';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    analyzeWorkflowFlow,
    enclosingFlowLoopControls,
    enclosingFlowRepeats,
    flowBinding,
    flowLoops,
    flowProducers,
    loopSelectionErrors,
    repeatStateBinding,
    MAX_LOOP_ITEMS,
    workflowLoopLimit,
    type WorkflowCollectNode,
    type WorkflowForEachNode,
    type WorkflowLoopScope,
    type WorkflowQueryIterable,
} from '../../lib/workflowFlow';
import {
    previewWorkflowLoopInput,
    workflowErrorMessage,
    workflowScopeKey,
    type WorkflowDefinition,
    type WorkflowEditorOptions,
    type WorkflowLoopPreview,
    type WorkflowScope,
} from '../../lib/workflowEditor';

const inputClass = 'mt-1 w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

function scopeKey(scope: WorkflowLoopScope): string {
    return `${scope.scope_type}:${scope.scope_id ?? ''}`;
}

function QueryFields({ value, scope, limit, onChange }: {
    value: WorkflowQueryIterable;
    scope: WorkflowScope;
    limit: number;
    onChange: (value: WorkflowQueryIterable) => void;
}) {
    const [tagsText, setTagsText] = useState(() => (value.filters.tags ?? []).join(', '));
    const groups = useBootstrapStore((state) => state.data?.scope?.groups ?? []);
    const publicWorkspaces = useBootstrapStore((state) => state.data?.scope?.public_workspaces ?? []);
    const sources: { label: string; scope: WorkflowLoopScope }[] = scope.type === 'group'
        ? [{ label: 'This group workspace', scope: { scope_type: 'group', scope_id: scope.groupId } }]
        : [
            { label: 'Personal documents', scope: { scope_type: 'personal' } },
            ...groups.map((group) => ({ label: `Group: ${group.name}`, scope: { scope_type: 'group' as const, scope_id: group.id } })),
            ...publicWorkspaces.map((workspace) => ({ label: `Public: ${workspace.name}`, scope: { scope_type: 'public' as const, scope_id: workspace.id } })),
        ];
    const selected = new Set(value.scopes.map(scopeKey));
    const missing = value.scopes.filter((source) => !sources.some((item) => scopeKey(item.scope) === scopeKey(source)));
    const setContentMode = (mode: string) => {
        if (mode === 'metadata') {
            const next: WorkflowQueryIterable = { ...value, selection: { mode: 'all_matches' } };
            delete next.content;
            onChange(next);
        } else {
            onChange({
                ...value,
                content: { mode: mode === 'hybrid' ? 'hybrid' : 'keyword', query: value.content?.query ?? '' },
                selection: mode === 'hybrid' && value.selection.mode === 'all_matches'
                    ? { mode: 'best_n', count: Math.min(50, limit) } : value.selection,
            });
        }
    };
    return (
        <div className="min-w-0 space-y-3">
            <fieldset className="space-y-2 rounded-lg border border-edge p-3">
                <legend className="px-1 text-xs font-medium text-text-2">Query workspaces</legend>
                {sources.map((source) => (
                    <label key={scopeKey(source.scope)} className="flex items-center gap-2 text-xs text-text-2">
                        <input type="checkbox" checked={selected.has(scopeKey(source.scope))}
                            onChange={(event) => onChange({
                                ...value,
                                scopes: event.target.checked ? [...value.scopes, source.scope]
                                    : value.scopes.filter((item) => scopeKey(item) !== scopeKey(source.scope)),
                            })} />
                        {source.label}
                    </label>
                ))}
                {missing.map((source) => <p key={scopeKey(source)} role="alert" className="break-all text-xs text-danger">
                    Unavailable saved scope: {scopeKey(source)}. <GlassButton size="sm" onClick={() =>
                        onChange({ ...value, scopes: value.scopes.filter((item) => scopeKey(item) !== scopeKey(source)) })}>Remove unavailable scope</GlassButton>
                </p>)}
            </fieldset>
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                {(['search', 'classification', 'author', 'keywords', 'abstract'] as const).map((field) => (
                    <label key={field} className="min-w-0 text-xs capitalize text-text-2">
                        {field === 'search' ? 'Name / title search' : field}
                        <input className={inputClass} aria-label={`Query ${field}`} value={value.filters[field] ?? ''} maxLength={1000}
                            onChange={(event) => {
                                const filters = { ...value.filters };
                                if (event.target.value) filters[field] = event.target.value;
                                else delete filters[field];
                                onChange({ ...value, filters });
                            }} />
                    </label>
                ))}
                <label className="min-w-0 text-xs text-text-2">
                    Tags (comma-separated)
                    <input className={inputClass} aria-label="Query tags" value={tagsText} maxLength={25600}
                        onChange={(event) => {
                            setTagsText(event.target.value);
                            onChange({ ...value, filters: {
                                ...value.filters, tags: event.target.value.split(',').map((tag) => tag.trim()).filter(Boolean),
                            } });
                        }} />
                </label>
                <label className="min-w-0 text-xs text-text-2">
                    Content matching
                    <select className={inputClass} aria-label="Query content mode" value={value.content?.mode ?? 'metadata'}
                        onChange={(event) => setContentMode(event.target.value)}>
                        <option value="metadata">Metadata only</option>
                        <option value="keyword">Keyword content</option>
                        <option value="hybrid">Semantic / hybrid ranking</option>
                    </select>
                </label>
                {value.content ? <label className="min-w-0 text-xs text-text-2">
                    Content query
                    <input className={inputClass} aria-label="Query content" value={value.content.query} maxLength={4000}
                        onChange={(event) => onChange({ ...value, content: { mode: value.content?.mode ?? 'keyword', query: event.target.value } })} />
                </label> : null}
                <label className="min-w-0 text-xs text-text-2">
                    Selection
                    <select className={inputClass} aria-label="Query selection" value={value.selection.mode}
                        onChange={(event) => onChange({ ...value,
                            ...(event.target.value === 'best_n' && !value.content ? { content: { mode: 'keyword', query: '' } } : {}),
                            selection: event.target.value === 'best_n'
                                ? { mode: 'best_n', count: Math.min(50, limit) } : { mode: 'all_matches' } })}>
                        <option value="all_matches" disabled={value.content?.mode === 'hybrid'}>All matches</option>
                        <option value="best_n">Best N documents</option>
                    </select>
                </label>
                {value.selection.mode === 'best_n' ? <label className="min-w-0 text-xs text-text-2">
                    Number of documents
                    <input className={inputClass} type="number" min={1} max={limit} aria-label="Best N documents"
                        value={Number.isFinite(value.selection.count) ? value.selection.count : ''}
                        onChange={(event) => onChange({ ...value, selection: { mode: 'best_n', count: event.currentTarget.valueAsNumber } })} />
                </label> : null}
            </div>
            <p className="text-xs text-text-3">
                {value.selection.mode === 'all_matches'
                    ? 'All matches exhaustively enumerates eligible metadata or searchable keyword matches. Unindexed content is not claimed as searched.'
                    : 'Best N is an intentionally limited document selection, not exhaustive corpus coverage. Semantic / hybrid relevance cannot use All matches.'}
                {' '}Metadata-only queries use All matches; Best N requires a content query. The authorized result is evaluated again and frozen when this loop first starts; this is not a transactional snapshot of the entire workspace.
            </p>
        </div>
    );
}

export function WorkflowForEachFields({ node, workflow, scope, options, onChange }: {
    node: WorkflowForEachNode;
    workflow: WorkflowDefinition;
    scope: WorkflowScope;
    options: WorkflowEditorOptions;
    onChange: (node: WorkflowForEachNode) => void;
}) {
    const userId = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const [preview, setPreview] = useState<WorkflowLoopPreview | null>(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const requestToken = useRef(0);
    const selectionKey = JSON.stringify([workflowScopeKey(scope), node.iterable, node.max_items]);
    useEffect(() => {
        abortRef.current?.abort();
        requestToken.current++;
        setPreview(null);
        setError('');
        setLoading(false);
        return () => abortRef.current?.abort();
    }, [selectionKey]);
    const ceiling = workflowLoopLimit(options);
    const limit = Math.min(ceiling, node.max_items);
    const errors = loopSelectionErrors(node, ceiling);
    const available = analyzeWorkflowFlow(workflow).available.get(node.id) ?? new Set<string>();
    const collections = [
        ...flowProducers(workflow).filter((producer) => available.has(producer.id)).flatMap((producer) =>
            producer.outputs.filter((output) => ['records', 'document_results'].includes(output.kind)).map((output) => ({
                key: JSON.stringify([producer.id, output.name]),
                label: `${producer.label} / ${output.name} (${output.kind.replaceAll('_', ' ')})`,
                binding: { ...flowBinding('', producer.id, output.name), expected_kind: output.kind },
            }))),
        ...enclosingFlowRepeats(workflow, node.id).flatMap((repeat) =>
            repeat.state.filter((slot) => ['records', 'document_results'].includes(slot.output_contract.kind)).map((slot) => ({
                key: JSON.stringify(['repeat_state', repeat.id, slot.name]),
                label: `Current Repeat ${repeat.id} state ${slot.name} (${slot.output_contract.kind.replaceAll('_', ' ')})`,
                binding: repeatStateBinding('', repeat.id, slot),
            }))),
    ];
    const iterable = node.iterable;
    const inputName = iterable.kind === 'input' ? iterable.name : '';
    const binding = node.inputs.find((item) => item.name === inputName);
    const selectedCollection = binding?.source.kind === 'node_output'
        ? JSON.stringify([binding.source.node_id, binding.source.output])
        : binding?.source.kind === 'repeat_state'
            ? JSON.stringify(['repeat_state', binding.source.loop_id, binding.source.state_name]) : '';
    const previewSelection = async () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        const token = ++requestToken.current;
        setLoading(true);
        setPreview(null);
        setError('');
        try {
            const response = await previewWorkflowLoopInput(scope, iterable, node.max_items, controller.signal);
            if (!controller.signal.aborted && token === requestToken.current) setPreview(response);
        } catch (cause: unknown) {
            if (!controller.signal.aborted && token === requestToken.current) setError(workflowErrorMessage(cause, 'Could not preview the loop source. No items have been admitted.'));
        } finally {
            if (!controller.signal.aborted && token === requestToken.current) setLoading(false);
        }
    };
    return (
        <div className="min-w-0 space-y-3">
            <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <label className="min-w-0 text-xs text-text-2">
                    Item source
                    <select className={inputClass} aria-label="For each source" value={iterable.kind}
                        onChange={(event) => onChange({ ...node, iterable: event.target.value === 'input'
                            ? { kind: 'input', name: node.inputs[0]?.name ?? 'rows' }
                            : event.target.value === 'workspace_query'
                                ? { kind: 'workspace_query', scopes: [scope.type === 'group'
                                    ? { scope_type: 'group', scope_id: scope.groupId } : { scope_type: 'personal' }],
                                    filters: {}, selection: { mode: 'all_matches' } }
                                : { kind: 'documents', documents: [] } })}>
                        <option value="documents" disabled={!options.supported_iterable_kinds?.includes('documents')}>Selected documents</option>
                        <option value="input" disabled={!options.supported_iterable_kinds?.includes('input')}>Saved record collection</option>
                        <option value="workspace_query" disabled={!options.supported_iterable_kinds?.includes('workspace_query')}>Workspace query</option>
                    </select>
                </label>
                <label className="min-w-0 text-xs text-text-2">
                    Author maximum items
                    <input className={inputClass} aria-label="For each maximum items" type="number" min={1} max={MAX_LOOP_ITEMS}
                        value={Number.isFinite(node.max_items) ? node.max_items : ''}
                        onChange={(event) => onChange({ ...node, max_items: event.currentTarget.valueAsNumber })} />
                </label>
            </div>
            <p className="text-xs text-text-2" role="status">
                Administrator ceiling: {ceiling} actual loop visits. Effective ceiling: {Number.isFinite(limit) ? limit : 'choose a valid maximum'}.
                {' '}{iterable.kind === 'documents' ? `Selected count: ${iterable.documents.length}.`
                    : iterable.kind === 'input' ? 'Selected count is known only when the saved collection is read at run time.' : 'Preview the query to check its selected count.'}
            </p>
            <p className="text-xs text-text-3">The ceiling counts actual visits, not searchable corpus size. Lower this loop's maximum to narrow its admission. Admin changes affect new runs only; existing runs retain their frozen policy. The body runs serially.</p>
            {iterable.kind === 'documents' ? <WorkflowDocumentPicker
                scope={scope}
                references={iterable.documents.map((document) => ({
                    ...document, scope_id: document.scope_type === 'personal' ? userId : document.scope_id ?? '',
                    id: `${scopeKey(document)}:${document.document_id}`, name: document.document_id,
                }))}
                onChange={(documents) => onChange({ ...node, iterable: { kind: 'documents', documents: documents.map((document) => ({
                    document_id: document.document_id, scope_type: document.scope_type,
                    ...(document.scope_type !== 'personal' ? { scope_id: document.scope_id } : {}),
                })) } })}
                title="Loop documents" selectedLabel="Selected loop documents" availableLabel="Available loop documents"
                hideAliasFields retainRequestedGroupScope emptyDescription="An empty selection runs no body tasks."
                description="Select explicit authorized source documents. Each document becomes one current item; shared references remain separate."
            /> : null}
            {iterable.kind === 'input' ? <fieldset className="space-y-3 rounded-lg border border-edge p-3">
                <legend className="px-1 text-xs text-text-2">Complete saved collection</legend>
                <label className="block text-xs text-text-2">Input alias
                    <input className={inputClass} aria-label="Collection input name" value={inputName} maxLength={64}
                        onChange={(event) => onChange({ ...node, iterable: { ...iterable, name: event.target.value },
                            inputs: node.inputs.map((item) => item.name === inputName ? { ...item, name: event.target.value } : item) })} />
                </label>
                <label className="block text-xs text-text-2">Saved collection output
                    <select className={inputClass} aria-label="Saved collection output" value={selectedCollection}
                        onChange={(event) => {
                            const selected = collections.find((item) => item.key === event.target.value);
                            if (!selected) return;
                            const next = { ...selected.binding, name: inputName };
                            onChange({ ...node, inputs: binding
                                ? node.inputs.map((item) => item.name === inputName ? next : item) : [...node.inputs, next] });
                        }}>
                        {!collections.some((item) => item.key === selectedCollection)
                            ? <option value={selectedCollection}>{selectedCollection ? 'Unavailable saved producer (retained)' : 'Choose an earlier typed collection'}</option> : null}
                        {collections.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                    </select>
                </label>
                <p className="text-xs text-text-3">Reads the complete immutable records or document results in saved order, not a byte excerpt. Equal-looking records remain distinct. A document ID in model-generated JSON does not grant document access.</p>
                {binding?.source.kind === 'repeat_state' ? <p className="text-xs text-text-3">Uses the named state saved at the start of this Repeat round. This For each instance freezes its membership from that state and requires complete eligible output.</p> : null}
            </fieldset> : null}
            {iterable.kind === 'workspace_query' ? <QueryFields key={`${node.id}:${iterable.kind}`} value={iterable} scope={scope} limit={limit}
                onChange={(next) => onChange({ ...node, iterable: next })} /> : null}
            {errors.map((message) => <p key={message} role="alert" className="rounded-lg bg-danger-soft p-3 text-xs text-danger">{message}</p>)}
            {iterable.kind !== 'input' ? <GlassButton size="sm" disabled={loading || errors.length > 0} onClick={() => void previewSelection()}>
                {loading ? <Loader2 size={14} className="animate-spin" /> : null} Preview loop selection
            </GlassButton> : null}
            {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
            {preview ? <div className="space-y-2 rounded-lg border border-edge p-3">
                <p role={preview.within_limit ? 'status' : 'alert'} className={`text-xs ${preview.within_limit ? 'text-text-2' : 'text-danger'}`}>
                    {preview.error_message ? <span className="mb-1 block">{preview.error_message}</span> : null}
                    {preview.count_exact ? 'Selected count' : 'Selected count (lower bound)'}: {preview.count_exact ? '' : 'at least '}{preview.count}.
                    {' '}Effective ceiling: {preview.limit}.
                    {preview.within_limit ? ' Within the limit.' : ` Narrow the query or select ${preview.limit} or fewer documents before starting a new run. No body tasks will run for an over-limit selection.`}
                </p>
                <p className="text-xs text-text-3">Advisory preview only; membership and access are checked again at loop entry. Up to 50 safe document labels are shown.</p>
                <WorkflowLoopSelectionDetails selection={preview.selection} />
                <ul className="max-h-48 space-y-1 overflow-auto text-xs text-text-3" aria-label="Loop preview documents">
                    {preview.items.map((item, index) => <li key={index} className="break-words">{String(item.title ?? item.file_name ?? item.name ?? item.document_id ?? `Document ${index + 1}`)}</li>)}
                </ul>
            </div> : null}
        </div>
    );
}

export function WorkflowCollectFields({ node, workflow, onChange }: {
    node: WorkflowCollectNode;
    workflow: WorkflowDefinition;
    onChange: (node: WorkflowCollectNode) => void;
}) {
    const available = analyzeWorkflowFlow(workflow).available.get(node.id) ?? new Set<string>();
    const parentIds = JSON.stringify(enclosingFlowLoopControls(workflow, node.id).map((loop) => loop.id));
    const loops = flowLoops(workflow).filter((loop) => available.has(loop.node.id) &&
        JSON.stringify(enclosingFlowLoopControls(workflow, loop.node.id).map((parent) => parent.id)) === parentIds);
    const selectedLoop = loops.find((loop) => loop.node.id === node.source.loop_id)?.node;
    const producers = flowProducers(workflow);
    const outputs = selectedLoop?.body.outputs.flatMap((item) => {
        const source = item.source;
        const representation = source.kind === 'node_output' ? producers.find((producer) => producer.id === source.node_id)?.outputs
            .find((output) => output.name === source.output) : undefined;
        return representation && ['records', 'document_results'].includes(representation.kind)
            ? [{ ...item, kind: representation.kind }] : [];
    }) ?? [];
    return (
        <fieldset className="min-w-0 space-y-3 rounded-lg border border-edge p-3">
            <legend className="px-1 text-sm font-medium text-text-1">Exact Collect</legend>
            <p className="text-xs text-text-3">Only declared body outputs cross a loop boundary. Collect retains every record in frozen item and producer-record order; it never deduplicates equal-looking records or runs a model.</p>
            <label className="block text-xs text-text-2">Source loop
                <select className={inputClass} aria-label="Collect source loop" value={node.source.loop_id}
                    onChange={(event) => onChange({ ...node, source: { loop_id: event.target.value, output: '' } })}>
                    {!selectedLoop ? <option value={node.source.loop_id}>{node.source.loop_id ? `Unavailable: ${node.source.loop_id}` : 'Choose a preceding loop'}</option> : null}
                    {loops.map((loop) => <option key={loop.node.id} value={loop.node.id}>{loop.node.id}</option>)}
                </select>
            </label>
            <label className="block text-xs text-text-2">Declared body output
                <select className={inputClass} aria-label="Collect body output" value={node.source.output}
                    onChange={(event) => {
                        const output = outputs.find((item) => item.name === event.target.value);
                        onChange({ ...node, source: { ...node.source, output: event.target.value },
                            output_contract: { ...node.output_contract, kind: output?.kind === 'document_results' ? 'document_results' : 'records' } });
                    }}>
                    {!outputs.some((item) => item.name === node.source.output) ? <option value={node.source.output}>{node.source.output ? `Unavailable: ${node.source.output}` : 'Choose a records or document-results export'}</option> : null}
                    {outputs.map((output) => <option key={output.name} value={output.name}>{output.name} ({output.kind.replaceAll('_', ' ')})</option>)}
                </select>
            </label>
            <p className="text-xs text-text-2">Preserved output kind: {node.output_contract.kind.replaceAll('_', ' ')}</p>
            <WorkflowDecisionFields contract={node.output_contract} onChange={(contract) =>
                onChange({ ...node, output_contract: { ...contract, kind: node.output_contract.kind } })} />
            <label className="block text-xs text-text-2">Expected total record count (optional)
                <input className={inputClass} type="number" min={0} aria-label="Collect expected count" value={node.output_contract.expected_count ?? ''}
                    onChange={(event) => {
                        const contract = { ...node.output_contract };
                        if (event.target.value === '') delete contract.expected_count;
                        else contract.expected_count = event.currentTarget.valueAsNumber;
                        onChange({ ...node, output_contract: contract });
                    }} />
            </label>
            {node.output_contract.kind === 'records' || node.output_contract.identity_field ? <label className="block text-xs text-text-2">Unique business-key field (optional)
                <input className={inputClass} aria-label="Collect identity field" value={node.output_contract.identity_field ?? ''}
                    onChange={(event) => {
                        const contract = { ...node.output_contract };
                        if (event.target.value) contract.identity_field = event.target.value;
                        else delete contract.identity_field;
                        onChange({ ...node, output_contract: contract });
                    }} />
                <span className="mt-1 block">{node.output_contract.kind === 'records'
                    ? 'Duplicate business keys invalidate the result; they never remove records.'
                    : 'Business-key uniqueness requires records output. Clear this retained field to collect document results.'}</span>
            </label> : null}
            <label className="flex items-center gap-2 text-xs text-text-2">
                <input type="checkbox" aria-label="Collect require complete coverage" checked={node.output_contract.require_complete_coverage}
                    onChange={(event) => onChange({ ...node, output_contract: { ...node.output_contract, require_complete_coverage: event.target.checked } })} />
                Require complete item coverage
            </label>
            <label className="flex items-center gap-2 text-xs text-text-2">
                <input type="checkbox" aria-label="Collect allow partial" checked={node.output_contract.allow_partial}
                    onChange={(event) => onChange({ ...node, output_contract: { ...node.output_contract, allow_partial: event.target.checked } })} />
                Explicitly accept eligible partial output with its coverage limitations
            </label>
        </fieldset>
    );
}
