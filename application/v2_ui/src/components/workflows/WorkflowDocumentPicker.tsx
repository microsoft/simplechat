// WorkflowDocumentPicker.tsx
// Paged shared-reference document picker for native workflow authoring.

import { useEffect, useMemo, useState } from 'react';
import { FileText, Plus, Search, Trash2 } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { Pill, RowAction } from '../workspace/primitives';
import {
    documentId,
    documentTitle,
    normalizeDocumentPage,
    safeWorkflowAlias,
    scopedDocumentQuery,
    workflowDocumentScopeId,
    type WorkflowReferenceInput,
    type WorkflowReferenceScope,
    type WorkflowScope,
} from '../../lib/workflowEditor';
import {
    fetchGroupDocuments,
    fetchPersonalDocuments,
    fetchPublicWorkspaceDocuments,
} from '../../lib/endpoints';
import type { WorkspaceDocument } from '../../lib/types';
import { useBootstrapStore } from '../../stores/bootstrapStore';

const inputClass = 'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none';

interface DocumentSource {
    key: string;
    label: string;
    scopeType: WorkflowReferenceScope;
    scopeId: string;
    groupId?: string;
}

function referenceKey(reference: WorkflowReferenceInput): string {
    return `${reference.scope_type}:${reference.scope_id}:${reference.document_id}`;
}

function documentReference(
    document: WorkspaceDocument,
    source: DocumentSource,
): WorkflowReferenceInput | null {
    const id = documentId(document);
    if (!id) {
        return null;
    }
    const scopeId = workflowDocumentScopeId(document, source.scopeType, source.scopeId);
    return {
        id: `${source.scopeType}:${scopeId}:${id}`,
        name: safeWorkflowAlias(documentTitle(document), `ref_${id}`),
        document_id: id,
        scope_type: source.scopeType,
        scope_id: scopeId,
    };
}

export function WorkflowDocumentPicker({
    scope,
    references,
    onChange,
    readOnly = false,
    title = 'Shared reference documents',
    description,
    selectedLabel = 'Selected shared references',
    availableLabel = 'Available documents',
    emptyDescription,
    hideAliasFields = false,
}: {
    scope: WorkflowScope;
    references: WorkflowReferenceInput[];
    onChange: (references: WorkflowReferenceInput[]) => void;
    readOnly?: boolean;
    title?: string;
    description?: string;
    selectedLabel?: string;
    availableLabel?: string;
    emptyDescription?: string;
    hideAliasFields?: boolean;
}) {
    const userId = useBootstrapStore((state) => state.data?.user?.id ?? '');
    const groups = useBootstrapStore((state) => state.data?.scope?.groups ?? []);
    const publicWorkspaces = useBootstrapStore((state) => state.data?.scope?.public_workspaces ?? []);
    const sources = useMemo<DocumentSource[]>(() => {
        if (scope.type === 'group') {
            return [{
                key: `group:${scope.groupId}`,
                label: 'This group workspace',
                scopeType: 'group',
                scopeId: scope.groupId,
                groupId: scope.groupId,
            }];
        }
        return [
            { key: 'personal', label: 'Personal documents', scopeType: 'personal', scopeId: userId },
            ...groups.map((group) => ({
                key: `group:${group.id}`,
                label: `Group: ${group.name}`,
                scopeType: 'group' as const,
                scopeId: group.id,
                groupId: group.id,
            })),
            ...publicWorkspaces.map((workspace) => ({
                key: `public:${workspace.id}`,
                label: `Public: ${workspace.name}`,
                scopeType: 'public' as const,
                scopeId: workspace.id,
            })),
        ];
    }, [groups, publicWorkspaces, scope, userId]);
    const [sourceKey, setSourceKey] = useState(sources[0]?.key ?? 'personal');
    const [query, setQuery] = useState('');
    const [page, setPage] = useState(1);
    const [documents, setDocuments] = useState<WorkspaceDocument[]>([]);
    const [totalCount, setTotalCount] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const source = sources.find((item) => item.key === sourceKey) ?? sources[0];

    useEffect(() => {
        if (!source) {
            return;
        }
        const controller = new AbortController();
        setLoading(true);
        setError('');
        const documentQuery = scopedDocumentQuery(query, page);
        const request = source.scopeType === 'personal'
            ? fetchPersonalDocuments(documentQuery, controller.signal)
            : source.scopeType === 'public'
                ? fetchPublicWorkspaceDocuments(documentQuery, controller.signal)
                : fetchGroupDocuments([source.groupId ?? source.scopeId], documentQuery, controller.signal);
        void request.then((response) => {
            if (controller.signal.aborted) {
                return;
            }
            const normalized = normalizeDocumentPage(response);
            setDocuments(normalized.documents);
            setTotalCount(normalized.totalCount);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) {
                setError(cause instanceof Error ? cause.message : 'Could not load documents.');
                setDocuments([]);
                setTotalCount(0);
            }
        }).finally(() => {
            if (!controller.signal.aborted) {
                setLoading(false);
            }
        });
        return () => controller.abort();
    }, [page, query, source]);

    if (!source) {
        return <p className="text-sm text-text-3">No authorized document sources are available.</p>;
    }

    const selected = new Set(references.map(referenceKey));
    const canGoNext = page * 10 < totalCount;
    const addReference = (document: WorkspaceDocument) => {
        const reference = documentReference(document, source);
        if (!reference || selected.has(referenceKey(reference))) {
            return;
        }
        onChange([...references, reference]);
    };

    return (
        <div className="space-y-3">
            <div>
                <p className="text-sm font-medium text-text-1">{title}</p>
                <p className="text-xs text-text-3">
                    {description ?? (
                        <>
                            These are shared evidence sources for the whole workflow. Each task can use
                            all, none, or a subset without changing previous-task result bindings.
                            Reference names are stable aliases using letters, numbers, underscores or
                            dashes.
                        </>
                    )}
                </p>
            </div>
            {references.length ? (
                <ul className="space-y-2" aria-label={selectedLabel}>
                    {references.map((reference) => (
                        <li key={reference.id}>
                            <GlassPanel elevation="flat" className="flex flex-wrap items-center gap-2 p-2">
                                <FileText size={15} className="shrink-0 text-text-3" />
                                {hideAliasFields ? (
                                    <span className="min-w-44 flex-1 text-sm text-text-1">{reference.name}</span>
                                ) : (
                                    <label className="min-w-44 flex-1 text-xs text-text-2">
                                        Reference alias
                                        <input
                                            className={`${inputClass} mt-1`}
                                            aria-label={`Reference alias for ${reference.document_id}`}
                                            pattern="[A-Za-z][A-Za-z0-9_-]{0,63}"
                                            value={reference.name}
                                            disabled={readOnly}
                                            onChange={(event) => onChange(references.map((item) =>
                                                item.id === reference.id
                                                    ? { ...item, name: safeWorkflowAlias(event.target.value, item.name || 'reference') }
                                                    : item))}
                                        />
                                    </label>
                                )}
                                <Pill>{reference.scope_type}</Pill>
                                {!readOnly ? (
                                    <RowAction
                                        icon={<Trash2 size={15} />}
                                        label={`Remove ${reference.name}`}
                                        onClick={() => onChange(references.filter((item) => item.id !== reference.id))}
                                    />
                                ) : null}
                            </GlassPanel>
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="rounded-xl border border-edge p-3 text-sm text-text-3">
                    {emptyDescription ?? 'No shared references selected. Tasks default to all shared references only after documents are added here.'}
                </p>
            )}
            {!readOnly ? (
                <div className="space-y-3 rounded-xl border border-edge p-3">
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                        <label className="text-sm text-text-2">
                            Source
                            <select
                                className={`${inputClass} mt-1`}
                                aria-label="Source"
                                value={source.key}
                                onChange={(event) => {
                                    setSourceKey(event.target.value);
                                    setPage(1);
                                }}
                            >
                                {sources.map((item) => (
                                    <option key={item.key} value={item.key}>{item.label}</option>
                                ))}
                            </select>
                        </label>
                        <label className="text-sm text-text-2">
                            Search documents
                            <span className="relative mt-1 block">
                                <Search
                                    size={14}
                                    className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                                />
                                <input
                                    className={`${inputClass} pl-8`}
                                    aria-label="Search documents"
                                    value={query}
                                    onChange={(event) => {
                                        setQuery(event.target.value);
                                        setPage(1);
                                    }}
                                />
                            </span>
                        </label>
                    </div>
                    {loading ? <p role="status" className="text-sm text-text-3">Loading documents…</p> : null}
                    {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
                    {!loading && !error && !documents.length ? (
                        <p role="status" className="text-sm text-text-3">No documents match this source and search.</p>
                    ) : null}
                    {documents.length ? (
                        <ul className="max-h-64 space-y-2 overflow-y-auto" aria-label={availableLabel}>
                            {documents.map((document) => {
                                const reference = documentReference(document, source);
                                const chosen = Boolean(reference && selected.has(referenceKey(reference)));
                                const title = documentTitle(document);
                                return (
                                    <li
                                        key={`${source.key}:${documentId(document)}`}
                                        className="flex items-center justify-between gap-2 rounded-xl border border-edge p-2"
                                    >
                                        <div className="min-w-0">
                                            <p className="truncate text-sm text-text-1">{title}</p>
                                            <p className="truncate text-xs text-text-3">
                                                {document.file_name ? String(document.file_name) : documentId(document)}
                                            </p>
                                        </div>
                                        <GlassButton
                                            size="sm"
                                            disabled={!reference || chosen}
                                            onClick={() => addReference(document)}
                                        >
                                            <Plus size={14} />
                                            {chosen ? 'Added' : 'Add'}
                                        </GlassButton>
                                    </li>
                                );
                            })}
                        </ul>
                    ) : null}
                    <div className="flex items-center gap-2">
                        <GlassButton size="sm" disabled={page === 1 || loading} onClick={() => setPage((value) => value - 1)}>
                            Previous documents
                        </GlassButton>
                        <span className="text-xs text-text-3">Page {page}</span>
                        <GlassButton size="sm" disabled={!canGoNext || loading} onClick={() => setPage((value) => value + 1)}>
                            Next documents
                        </GlassButton>
                    </div>
                </div>
            ) : null}
        </div>
    );
}
