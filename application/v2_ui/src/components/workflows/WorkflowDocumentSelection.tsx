// WorkflowDocumentSelection.tsx
// Guided rolling document selection owned by one task, with advisory server preview.

import { useEffect, useRef, useState } from 'react';
import { fetchWorkflowScopeTags, previewTaskDocuments, type TaskDocumentPreview } from '../../lib/endpoints';
import {
    DOCUMENT_FILE_TYPES, WINDOW_UNITS, defaultDocumentSelection, documentFilterCount, documentFilterSummary,
    documentScopeKey, documentSelectionErrors, documentWindowUnit, isTaskDocumentSelection,
    type DocumentFilter, type DocumentFilterField, type DocumentFilterOperator, type DocumentFilterPredicate,
    type DocumentScope, type WindowUnit,
} from '../../lib/workflowDocumentSelection';
import type { WorkflowDocumentAction, WorkflowEditorOptions, WorkflowScope } from '../../lib/workflowEditor';

const inputClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none';
const buttonClass = 'rounded-lg border border-edge px-3 py-2 text-sm text-text-1 hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50';
const fieldLabels: Record<DocumentFilterField, string> = {
    filename: 'File name', tags: 'Tags', file_type: 'File type', classification: 'Classification',
    author: 'Author', keywords: 'Keywords',
};
const operatorLabels: Record<DocumentFilterOperator, string> = {
    equals: 'Equals', starts_with: 'Starts with', contains: 'Contains', regex: 'Matches regular expression',
    has_any: 'Has any selected value', has_all: 'Has every selected value',
};
const help: Record<DocumentFilterField, string> = {
    filename: 'Match the file name, including its extension. For example, Starts with “Tim” includes Tim-notes.pdf.',
    tags: 'Pick workspace tags to find related documents. Use any for alternatives, or every to require all the tags.',
    file_type: 'Choose extensions such as PDF or CSV. This checks the file name, not its content.',
    classification: 'Match the classification recorded on the document, such as Confidential.',
    author: 'Match an author recorded in document metadata. This is not necessarily the person who uploaded it.',
    keywords: 'Match a keyword recorded in document metadata, such as budget.',
};
const newPredicate = (): DocumentFilterPredicate => ({ field: 'filename', operator: 'starts_with', value: '', match_case: false });

function ValueChoices({ label, options, values, onChange }: {
    label: string; options: string[]; values: string[]; onChange: (values: string[]) => void;
}) {
    const [query, setQuery] = useState('');
    const all = [...new Set([...values, ...options])].sort();
    const filtered = all.filter((item) => item.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
    return <div className="space-y-2">
        <label className="block text-sm text-text-2">Find {label}
            <input className={`${inputClass} mt-1`} value={query} placeholder={`Search ${label}`}
                onChange={(event) => setQuery(event.target.value)} />
        </label>
        <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto" role="group" aria-label={`Choose ${label}`}>
            {filtered.map((item) => <label key={item} className="flex items-center gap-2 rounded-lg border border-edge px-3 py-2 text-sm text-text-1">
                <input type="checkbox" checked={values.includes(item)} onChange={(event) =>
                    onChange(event.target.checked ? [...values, item] : values.filter((value) => value !== item))} />
                {label === 'file types' ? item.toUpperCase() : item}
            </label>)}
        </div>
        {!filtered.length ? <p className="text-sm text-text-2">No matching {label} in these workspaces.</p> : null}
        {label === 'tags' && query.trim() && !all.includes(query.trim()) ? <button type="button" className={buttonClass}
            onClick={() => { onChange([...values, query.trim()]); setQuery(''); }}>
            Use exact tag “{query.trim()}”
        </button> : null}
    </div>;
}

function FilterEditor({ node, onChange, tags, depth = 1, total }: {
    node: DocumentFilter; onChange: (node: DocumentFilter) => void; tags: string[]; depth?: number; total: number;
}) {
    if ('conditions' in node) {
        const update = (index: number, child: DocumentFilter) => onChange({
            ...node, conditions: node.conditions.map((item, position) => position === index ? child : item),
        });
        return <fieldset className="min-w-0 space-y-3 rounded-lg border border-edge p-3">
            <legend className="px-1 text-sm font-medium text-text-1">{depth === 1 ? 'Metadata filters' : 'Filter group'}</legend>
            <label className="block text-sm text-text-2">Combine conditions
                <select className={`${inputClass} mt-1`} aria-label="Combine conditions" value={node.operator}
                    onChange={(event) => onChange({ ...node, operator: event.target.value === 'or' ? 'or' : 'and' })}>
                    <option value="and">Match all (AND)</option><option value="or">Match any (OR)</option>
                </select>
            </label>
            {!node.conditions.length ? <p className="text-sm leading-relaxed text-text-2">
                No extra metadata restriction. Add a filter to narrow this task’s recent documents.
            </p> : null}
            {node.conditions.map((child, index) => <div key={index} className="min-w-0 space-y-2">
                <FilterEditor node={child} tags={tags} depth={depth + 1} total={total} onChange={(next) => update(index, next)} />
                <button type="button" className={buttonClass} aria-label={`Remove condition ${index + 1}`}
                    onClick={() => onChange({ ...node, conditions: node.conditions.filter((_, position) => position !== index) })}>
                    Remove {'conditions' in child ? 'group' : 'filter'}
                </button>
            </div>)}
            <div className="flex flex-wrap gap-2">
                <button type="button" className={buttonClass} disabled={total >= 32 || depth >= 4}
                    onClick={() => onChange({ ...node, conditions: [...node.conditions, newPredicate()] })}>Add filter</button>
                <button type="button" className={buttonClass} disabled={total >= 31 || depth >= 3}
                    onClick={() => onChange({ ...node, conditions: [...node.conditions, { operator: 'or', conditions: [newPredicate()] }] })}>
                    Add AND / OR group
                </button>
            </div>
        </fieldset>;
    }
    const arrayField = node.field === 'tags' || node.field === 'file_type';
    const operators: DocumentFilterOperator[] = node.field === 'file_type' ? ['has_any'] : arrayField ? ['has_any', 'has_all']
        : node.field === 'filename' ? ['starts_with', 'contains', 'equals', 'regex'] : ['equals', 'contains', 'starts_with'];
    return <fieldset className="min-w-0 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm text-text-2">Filter by
                <select className={`${inputClass} mt-1`} aria-label="Filter by" value={node.field} onChange={(event) => {
                    const field = event.target.value as DocumentFilterField;
                    const multiple = field === 'tags' || field === 'file_type';
                    onChange({ field, operator: multiple ? 'has_any' : field === 'filename' ? 'starts_with' : 'equals',
                        value: multiple ? [] : '', match_case: false });
                }}>
                    {Object.entries(fieldLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
            </label>
            <label className="block text-sm text-text-2">Match rule
                <select className={`${inputClass} mt-1`} aria-label="Match rule" value={node.operator}
                    onChange={(event) => onChange({ ...node, operator: event.target.value as DocumentFilterOperator })}>
                    {operators.map((operator) => <option key={operator} value={operator}>{operatorLabels[operator]}</option>)}
                </select>
            </label>
        </div>
        <p className="max-w-[72ch] text-sm leading-relaxed text-text-2">{help[node.field]}</p>
        {arrayField ? <ValueChoices label={node.field === 'tags' ? 'tags' : 'file types'}
            options={node.field === 'tags' ? tags : [...DOCUMENT_FILE_TYPES]}
            values={Array.isArray(node.value) ? node.value : []} onChange={(value) => onChange({ ...node, value })} />
            : <label className="block text-sm text-text-2">{node.operator === 'regex' ? 'Filename regular expression' : `${fieldLabels[node.field]} value`}
                <input className={`${inputClass} mt-1`} maxLength={256} value={typeof node.value === 'string' ? node.value : ''}
                    placeholder={node.operator === 'regex' ? '^Tim.*\\.pdf$' : node.field === 'filename' ? 'Tim' : `Enter ${fieldLabels[node.field].toLowerCase()}`}
                    onChange={(event) => onChange({ ...node, value: event.target.value })} />
            </label>}
        {node.operator === 'regex' ? <p className="text-sm text-text-2">
            Checked only on the server, with a time limit. Use Preview to check syntax and matches.
        </p> : null}
        {node.field !== 'file_type' ? <label className="flex items-center gap-2 text-sm text-text-2">
            <input type="checkbox" checked={node.match_case === true}
                onChange={(event) => onChange({ ...node, match_case: event.target.checked })} />
            Match case
        </label> : null}
    </fieldset>;
}

interface SelectionProps {
    scope: WorkflowScope; action: WorkflowDocumentAction; options: WorkflowEditorOptions;
    onChange: (action: WorkflowDocumentAction) => void;
}

export function WorkflowDocumentSelection(props: SelectionProps) {
    if (props.action.document_selection && !isTaskDocumentSelection(props.action.document_selection)) {
        const workspace: DocumentScope = props.scope.type === 'group'
            ? { scope_type: 'group', scope_id: props.scope.groupId } : { scope_type: 'personal' };
        return <div role="alert" className="space-y-2 text-sm text-danger">
            <p>This saved document selection has an unsupported structure. Reset it or choose another document action before saving.</p>
            <button type="button" className={buttonClass} onClick={() => props.onChange({
                ...props.action, document_selection: defaultDocumentSelection(workspace), recent_window_minutes: 60,
            })}>Reset document filters and workspaces</button>
        </div>;
    }
    return <DocumentSelectionFields {...props} />;
}

function DocumentSelectionFields({ scope, action, options, onChange }: SelectionProps) {
    const ownScope: DocumentScope = scope.type === 'group' ? { scope_type: 'group', scope_id: scope.groupId } : { scope_type: 'personal' };
    const selection = action.document_selection ?? defaultDocumentSelection(ownScope);
    const workspaces = options.document_workspaces ?? [{ ...ownScope, name: scope.type === 'group' ? 'This group' : 'My workspace' }];
    const minutes = action.recent_window_minutes ?? 60;
    const [unit, setUnit] = useState<WindowUnit>(() => documentWindowUnit(minutes));
    const [tags, setTags] = useState<string[]>([]);
    const [tagError, setTagError] = useState('');
    const [preview, setPreview] = useState<TaskDocumentPreview | null>(null);
    const [previewError, setPreviewError] = useState('');
    const [loading, setLoading] = useState(false);
    const request = useRef<AbortController | null>(null);
    const availableScopes = selection.scopes.filter((item) => workspaces.some(
        (workspace) => documentScopeKey(item) === documentScopeKey(workspace),
    ));
    const scopeKey = JSON.stringify(availableScopes);
    const configKey = JSON.stringify({ scope, action });
    const currentKey = useRef(configKey);
    currentKey.current = configKey;
    const errors = documentSelectionErrors(selection, minutes);

    useEffect(() => {
        if (minutes > 0 && minutes % WINDOW_UNITS[unit] !== 0) setUnit(documentWindowUnit(minutes));
    }, [minutes, unit]);
    useEffect(() => {
        request.current?.abort();
        setLoading(false);
        setPreview(null);
        setPreviewError('');
        return () => request.current?.abort();
    }, [configKey]);
    useEffect(() => {
        const controller = new AbortController();
        setTags([]);
        setTagError('');
        void Promise.all(availableScopes.map((workspace) => fetchWorkflowScopeTags(workspace, controller.signal)))
            .then((results) => {
                if (!controller.signal.aborted) setTags([...new Set(results.flatMap((result) => (result.tags ?? []).map((tag) => tag.name)))]);
            }).catch((error: unknown) => {
                if (!controller.signal.aborted) setTagError(error instanceof Error ? error.message : 'Could not load workspace tags.');
            });
        return () => controller.abort();
        // The serialized scope list changes only when the source workspaces change.
    }, [scopeKey]);
    const changeSelection = (next: typeof selection) => {
        const kinds = [...new Set(next.scopes.map((workspace) => workspace.scope_type))];
        onChange({ ...action, document_selection: next, doc_scope: kinds.length === 1 ? kinds[0] : 'all',
            active_group_ids: next.scopes.filter((workspace) => workspace.scope_type === 'group').map((workspace) => workspace.scope_id ?? ''),
            active_public_workspace_id: next.scopes.filter((workspace) => workspace.scope_type === 'public').map((workspace) => workspace.scope_id ?? '') });
    };
    const runPreview = async () => {
        const controller = new AbortController();
        request.current?.abort();
        request.current = controller;
        setLoading(true);
        setPreviewError('');
        try {
            const result = await previewTaskDocuments(scope, { type: action.type, recent_window_minutes: minutes,
                document_selection: selection, ...(action.type === 'merge' ? { merge_kind: action.merge_kind } : {}) }, controller.signal);
            if (!controller.signal.aborted && currentKey.current === configKey) setPreview(result);
        } catch (error: unknown) {
            if (!controller.signal.aborted && currentKey.current === configKey) {
                setPreview(null);
                setPreviewError(error instanceof Error ? error.message : 'Selection could not be completed. Try again.');
            }
        } finally {
            if (!controller.signal.aborted && currentKey.current === configKey) setLoading(false);
        }
    };
    return <div className="min-w-0 space-y-4" data-workflow-document-selection>
        <div>
            <h4 className="text-sm font-semibold text-text-1">Documents for this task</h4>
            <p className="mt-1 max-w-[72ch] text-sm leading-relaxed text-text-2">
                Select new or updated documents at the start of each run. Each task has its own selection;
                a retry keeps the same captured documents. Updates include metadata changes.
            </p>
        </div>
        <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium text-text-1">Source workspaces</legend>
            {workspaces.map((workspace) => <label key={documentScopeKey(workspace)} className="flex items-center gap-2 text-sm text-text-2">
                <input type="checkbox" checked={selection.scopes.some((item) => documentScopeKey(item) === documentScopeKey(workspace))}
                    onChange={(event) => changeSelection({ ...selection, scopes: event.target.checked
                        ? [...selection.scopes, { scope_type: workspace.scope_type, ...(workspace.scope_id ? { scope_id: workspace.scope_id } : {}) }]
                        : selection.scopes.filter((item) => documentScopeKey(item) !== documentScopeKey(workspace)) })} />
                {workspace.name}
            </label>)}
            {selection.scopes.filter((item) => !workspaces.some((workspace) => documentScopeKey(item) === documentScopeKey(workspace))).map((item) =>
                <div key={documentScopeKey(item)} className="space-y-2">
                    <p role="alert" className="text-sm text-danger">A selected workspace is unavailable. Remove it or restore access before running.</p>
                    <button type="button" className={buttonClass} onClick={() => changeSelection({
                        ...selection, scopes: selection.scopes.filter((workspace) => documentScopeKey(workspace) !== documentScopeKey(item)),
                    })}>Remove unavailable workspace</button>
                </div>)}
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-sm text-text-2">Within the last
                <input className={`${inputClass} mt-1`} type="number" min={1} step={1} value={minutes / WINDOW_UNITS[unit]}
                    onChange={(event) => onChange({ ...action, recent_window_minutes: Number(event.target.value) * WINDOW_UNITS[unit] })} />
            </label>
            <label className="block text-sm text-text-2">Time unit
                <select className={`${inputClass} mt-1`} aria-label="Time unit" value={unit} onChange={(event) => {
                    const next = event.target.value as WindowUnit;
                    onChange({ ...action, recent_window_minutes: minutes / WINDOW_UNITS[unit] * WINDOW_UNITS[next] });
                    setUnit(next);
                }}>{Object.keys(WINDOW_UNITS).map((value) => <option key={value} value={value}>{value}</option>)}</select>
            </label>
        </div>
        <p className="max-w-[72ch] text-sm leading-relaxed text-text-2">
            The window rolls forward for a new run, up to 365 days. Workspace and time boundaries always apply, even with OR filters.
        </p>
        {tagError ? <p role="alert" className="text-sm text-danger">{tagError} Existing tag choices were not loaded; retry by reselecting the workspace.</p> : null}
        <FilterEditor node={selection.filters} tags={tags} total={documentFilterCount(selection.filters)}
            onChange={(filters) => changeSelection({ ...selection, filters })} />
        <label className="block text-sm text-text-2">When no documents match
            <select className={`${inputClass} mt-1`} aria-label="When no documents match" value={selection.on_empty}
                onChange={(event) => changeSelection({ ...selection, on_empty: event.target.value === 'error' ? 'error' : 'report' })}>
                <option value="report">Report no recent documents (no processing model call)</option>
                <option value="error">Fail this task</option>
            </select>
        </label>
        <p className="break-words text-sm leading-relaxed text-text-1" aria-label="Document selection summary">
            In {selection.scopes.map((item) => workspaces.find((workspace) => documentScopeKey(item) === documentScopeKey(workspace))?.name ?? 'unavailable workspace').join(', ') || 'no workspace'},
            {' '}within the last {minutes / WINDOW_UNITS[unit]} {unit}, matching {documentFilterSummary(selection.filters)}.
        </p>
        {errors.length ? <ul role="alert" className="space-y-1 text-sm text-danger">{errors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
        <button type="button" className={buttonClass} disabled={loading || errors.length > 0} onClick={() => void runPreview()}>
            {loading ? 'Checking documents…' : 'Preview matching documents'}
        </button>
        <div aria-live="polite" aria-busy={loading} className="space-y-2 text-sm text-text-2">
            {previewError ? <p role="alert" className="text-danger">{previewError} No complete selection was accepted.</p> : null}
            {preview ? <>
                <p>{preview.count === 0 ? 'No recent documents found for these conditions.' : `${preview.count} matching documents (limit ${preview.limit}).`}</p>
                <p>Preview only, from {new Date(preview.cutoff_ts * 1000).toLocaleString()} onward. A new run checks again; this does not save or run the workflow.</p>
                <ul className="space-y-1" aria-label="Matching documents">{preview.items.map((item) =>
                    <li className="break-words" key={`${item.scope_type}:${item.scope_id}:${item.document_id}`}>{item.file_name}</li>)}</ul>
                {preview.count > preview.items.length ? <p>Showing the first {preview.items.length} matches.</p> : null}
            </> : null}
        </div>
    </div>;
}
