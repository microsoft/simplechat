// WorkspaceDocumentPicker.tsx
// The main composer's directory and results share a query, not selection state.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { ChevronDown, FileText, FolderOpen, Loader2, Search, Tag, X } from 'lucide-react';
import { fetchDocumentSources, type DocumentSourcesPage, type DocumentSourceWorkspace } from '../../lib/endpoints';
import { contextKey, type ContextScopeRef } from '../../lib/chatContext';
import type { ContextCandidate } from '../../lib/contextMentions';
import { documentDisplayName } from '../../lib/documentExplorer';
import { isScreeningAvailable } from '../../lib/contentScreening';
import { ScreeningStatusBadge } from '../screening/ScreeningStatusBadge';

export function WorkspaceDocumentPicker({
    searchAll, selectedKeys, onToggleSearchAll, onToggle, onClear, onClose, conversationId,
    placement = 'up', disabled = false,
}: {
    searchAll: boolean;
    selectedKeys: ReadonlySet<string>;
    onToggleSearchAll?: () => void;
    onToggle: (candidate: ContextCandidate) => void;
    onClear: () => void;
    onClose: () => void;
    conversationId?: string | null;
    placement?: 'up' | 'down';
    disabled?: boolean;
}) {
    const [query, setQuery] = useState('');
    const [workspace, setWorkspace] = useState<string>();
    const [expanded, setExpanded] = useState(false);
    const [page, setPage] = useState<DocumentSourcesPage | null>(null);
    const [loading, setLoading] = useState(true);
    const [paging, setPaging] = useState(false);
    const [error, setError] = useState<string>();
    const [revision, setRevision] = useState(0);
    const holder = useRef<HTMLDivElement>(null);
    const anchor = useRef<HTMLSpanElement>(null);
    const [position, setPosition] = useState({ top: 16, left: 16, width: 320, height: 480 });
    const search = useRef<HTMLInputElement>(null);
    const generation = useRef(0);
    const pageController = useRef<AbortController>();
    const directory = useRef<{ query: string; page: DocumentSourcesPage }>();

    useLayoutEffect(() => {
        const owner = anchor.current?.parentElement;
        if (!owner) return;
        const measure = () => {
            const rect = owner.getBoundingClientRect();
            const viewport = window.visualViewport;
            const viewportHeight = viewport?.height ?? window.innerHeight;
            const viewportWidth = viewport?.width ?? window.innerWidth;
            const top = viewport?.offsetTop ?? 0;
            const left = viewport?.offsetLeft ?? 0;
            const height = Math.min(544, viewportHeight - 32, Math.max(360, viewportHeight * 0.65));
            const width = Math.min(768, rect.width, viewportWidth - 32);
            setPosition({
                top: Math.max(top + 16, Math.min(
                    placement === 'up' ? rect.top - height - 8 : rect.bottom + 8,
                    top + viewportHeight - height - 16,
                )),
                left: Math.max(left + 16, Math.min(rect.left, left + viewportWidth - width - 16)),
                width, height,
            });
        };
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(owner);
        window.addEventListener('resize', measure);
        window.addEventListener('scroll', measure, true);
        window.visualViewport?.addEventListener('resize', measure);
        window.visualViewport?.addEventListener('scroll', measure);
        return () => {
            observer.disconnect();
            window.removeEventListener('resize', measure);
            window.removeEventListener('scroll', measure, true);
            window.visualViewport?.removeEventListener('resize', measure);
            window.visualViewport?.removeEventListener('scroll', measure);
        };
    }, [placement]);

    useEffect(() => {
        search.current?.focus();
        const pointer = (event: MouseEvent) => {
            if (!holder.current?.contains(event.target as Node)) onClose();
        };
        const key = (event: KeyboardEvent) => {
            if (event.key === 'Escape') { event.stopPropagation(); onClose(); }
        };
        document.addEventListener('mousedown', pointer);
        document.addEventListener('keydown', key);
        return () => {
            document.removeEventListener('mousedown', pointer);
            document.removeEventListener('keydown', key);
            pageController.current?.abort();
        };
    }, [onClose]);

    useEffect(() => {
        const controller = new AbortController();
        generation.current += 1;
        pageController.current?.abort();
        setPaging(false);
        setLoading(true);
        setError(undefined);
        setPage(null);
        const timer = window.setTimeout(() => {
            fetchDocumentSources({ query, workspace, conversation_id: conversationId ?? undefined }, controller.signal)
                .then((result) => {
                    if (!controller.signal.aborted) {
                        const previous = directory.current;
                        if (previous?.query === query && previous.page.workspaces.length > result.workspaces.length) {
                            result = { ...result, workspaces: previous.page.workspaces, workspace_next: previous.page.workspace_next };
                        }
                        directory.current = { query, page: result };
                        setPage(result);
                        setLoading(false);
                    }
                })
                .catch(() => {
                    if (!controller.signal.aborted) { setError('Could not load document sources. Please retry.'); setLoading(false); }
                });
        }, 250);
        return () => { controller.abort(); window.clearTimeout(timer); };
    }, [query, workspace, revision, conversationId]);

    const loadMore = async (directory: boolean) => {
        if (!page || paging) return;
        const next = directory ? page.workspace_next : page.source_next;
        if (next === null) return;
        const currentGeneration = generation.current;
        const controller = new AbortController();
        pageController.current = controller;
        setPaging(true);
        setError(undefined);
        try {
            const result = await fetchDocumentSources({
                query, workspace, conversation_id: conversationId ?? undefined,
                ...(directory ? { workspace_offset: next } : { source_offset: next }),
            }, controller.signal);
            if (controller.signal.aborted || generation.current !== currentGeneration) return;
            setPage((current) => current && (directory
                ? { ...current, workspaces: [...current.workspaces, ...result.workspaces], workspace_next: result.workspace_next }
                : { ...current, documents: [...current.documents, ...result.documents], source_next: result.source_next }));
        } catch {
            if (!controller.signal.aborted && generation.current === currentGeneration) {
                setError('Could not load more sources. Use the load more button to retry.');
            }
        } finally {
            if (generation.current === currentGeneration) setPaging(false);
        }
    };
    const choose = (candidate: ContextCandidate) => {
        if (searchAll) onToggleSearchAll?.();
        onToggle(candidate);
    };
    const asScope = (item: DocumentSourceWorkspace): ContextScopeRef => ({ kind: item.kind, id: item.id, name: item.name });
    useEffect(() => { if (page) directory.current = { query, page }; }, [page, query]);
    const selectedWorkspace = page?.browsed_workspace;
    const sourceRow = (candidate: ContextCandidate, available = true) => (
        <button key={`${candidate.key}:${candidate.scope.kind}:${candidate.scope.id ?? ''}`} type="button" disabled={!available}
            aria-pressed={selectedKeys.has(candidate.key)}
            onClick={() => choose(candidate)}
            className={clsx('flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-sm disabled:opacity-50',
                selectedKeys.has(candidate.key) ? 'bg-accent-soft text-accent' : 'text-text-1 hover:bg-surface-2')}>
            <input type="checkbox" checked={selectedKeys.has(candidate.key)} readOnly tabIndex={-1}
                aria-hidden="true" className="pointer-events-none mt-1 shrink-0" />
            {candidate.kind === 'document' ? <FileText size={16} className="mt-0.5 shrink-0" />
                : candidate.kind === 'tag' ? <Tag size={16} className="mt-0.5 shrink-0" />
                    : <FolderOpen size={16} className="mt-0.5 shrink-0" />}
            <span className="min-w-0 flex-1">
                <span className="block break-words">{candidate.label}</span>
                <span className="block text-xs text-text-3">{candidate.subtitle ?? candidate.scope.name}</span>
                {candidate.document?.content_screening && <ScreeningStatusBadge summary={candidate.document.content_screening} />}
            </span>
        </button>
    );
    return <><span ref={anchor} className="contents" />{createPortal(
        <div ref={holder} data-context-picker="" role="region" aria-label="Document sources"
            style={position}
            className="glass-modal fixed z-50 flex flex-col overflow-x-hidden overflow-y-auto rounded-xl border border-edge">
            <fieldset disabled={disabled} className="contents">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-edge p-3">
                <div>
                    <h2 className="font-semibold text-text-1">Document sources</h2>
                    <p className="text-xs text-text-3">Search across workspaces or choose specific sources.</p>
                </div>
                <button type="button" aria-label="Close document sources" onClick={onClose} className="rounded-lg p-2 text-text-2 hover:bg-surface-2"><X size={16} /></button>
            </div>
            <div className="shrink-0 space-y-3 border-b border-edge p-3">
                <div className="flex flex-wrap gap-2" aria-label="Document search mode">
                    <button type="button" aria-pressed={searchAll} onClick={() => { if (!searchAll) onToggleSearchAll?.(); }}
                        className={clsx('rounded-lg border px-3 py-2 text-sm', searchAll ? 'border-accent bg-accent-soft text-accent' : 'border-edge text-text-2')}>
                        Search all documents
                    </button>
                    <button type="button" aria-pressed={!searchAll} onClick={() => { if (searchAll) onToggleSearchAll?.(); }}
                        className={clsx('rounded-lg border px-3 py-2 text-sm', !searchAll ? 'border-accent bg-accent-soft text-accent' : 'border-edge text-text-2')}>
                        Choose sources
                    </button>
                </div>
                <p className="text-xs text-text-3">{searchAll
                    ? 'Searches every accessible personal, group and public workspace.'
                    : 'Selected workspaces, documents and tags are combined. Browsing does not select.'}</p>
                <label className="flex items-center gap-2 rounded-lg border border-edge bg-surface-1 px-2.5">
                    <Search size={16} aria-hidden="true" className="shrink-0 text-text-3" />
                    <input ref={search} type="search" value={query} aria-label="Search documents"
                        placeholder="Search documents, tags and workspaces"
                        onChange={(event) => { setQuery(event.target.value); setWorkspace(undefined); }}
                        onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); } }}
                        className="min-w-0 flex-1 bg-transparent py-2 text-sm text-text-1 outline-none placeholder:text-text-3" />
                </label>
            </div>
            {error && <div role="alert" className="px-3 py-2 text-sm text-danger">
                {error} {!page && <button type="button" onClick={() => setRevision((value) => value + 1)} className="ml-2 underline">Retry sources</button>}
            </div>}
            {loading ? <div role="status" className="flex flex-1 items-center gap-2 p-4 text-sm text-text-3"><Loader2 size={16} className="animate-spin" />Loading sources</div> : page && (
                <div className="flex min-h-24 flex-1 flex-col md:flex-row">
                    <nav aria-label="Workspaces" className="max-h-[45%] shrink-0 overflow-y-auto border-b border-edge md:max-h-none md:w-52 md:border-r md:border-b-0">
                        <button type="button" className="flex w-full items-center justify-between p-3 text-sm text-text-2 md:hidden"
                            aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
                            {selectedWorkspace?.name ?? 'All workspaces'} <ChevronDown size={16} />
                        </button>
                        <div className={clsx('max-h-44 overflow-y-auto p-2 md:max-h-none md:overflow-visible', !expanded && 'hidden md:block')}>
                            <button type="button" aria-pressed={!workspace} onClick={() => { setWorkspace(undefined); setExpanded(false); }}
                                className={clsx('w-full rounded-lg px-2 py-2 text-left text-sm', !workspace ? 'bg-accent-soft text-accent' : 'text-text-2 hover:bg-surface-2')}>
                                All workspaces <span className="text-xs">({page.matching_workspace_count}/{page.eligible_workspace_count})</span>
                            </button>
                            {(['personal', 'group', 'public'] as const).map((kind) => {
                                const scopes = page.workspaces.filter((item) => item.kind === kind);
                                return scopes.length > 0 && <div key={kind}>
                                    <h3 className="px-2 pt-3 pb-1 text-xs font-medium text-text-3">{kind === 'personal' ? 'Personal' : kind === 'group' ? 'Group' : 'Public'}</h3>
                                    {scopes.map((item) => <button key={item.key} type="button" aria-pressed={workspace === item.key}
                                        onClick={() => { setWorkspace(item.key); setExpanded(false); }}
                                        className={clsx('block w-full rounded-lg px-2 py-2 text-left text-sm', workspace === item.key ? 'bg-accent-soft text-accent' : 'text-text-2 hover:bg-surface-2')}>
                                        <span className="block break-words">{item.name}</span>
                                        <span className="block text-xs text-text-3">{item.document_count} documents{item.match_reason ? ` · ${item.match_reason}` : ''}</span>
                                    </button>)}
                                </div>;
                            })}
                            {page.workspace_next !== null && <button type="button" disabled={paging} onClick={() => void loadMore(true)} className="p-2 text-sm text-accent">Load more workspaces</button>}
                        </div>
                    </nav>
                    <div className="min-h-0 min-w-0 flex-1 overflow-y-auto p-2" aria-label="Available sources">
                        <p role="status" className="px-2 py-1 text-xs text-text-3">{page.source_total} documents{workspace ? ' in this workspace' : ' across matching workspaces'}</p>
                        {(workspace ? selectedWorkspace ? [selectedWorkspace] : [] : page.workspaces).map((item) => sourceRow({
                            key: contextKey('scope', item.id ?? 'personal', asScope(item)), kind: 'scope',
                            label: item.name, subtitle: 'Select whole workspace', scope: asScope(item),
                        }))}
                        {selectedWorkspace && page.tags.map((tag) => sourceRow({
                            key: contextKey('tag', tag, asScope(selectedWorkspace)), kind: 'tag',
                            label: tag, scope: asScope(selectedWorkspace),
                        }))}
                        {page.documents.map(({ scope, document }) => sourceRow({
                            key: contextKey('document', String(document.id), asScope(scope)), kind: 'document',
                            label: documentDisplayName(document).primary, scope: asScope(scope), document,
                        }, isScreeningAvailable(document)))}
                        {page.matching_workspace_count === 0 && <p className="p-3 text-sm text-text-3">No matching workspaces or documents. Try a different name or tag.</p>}
                        {workspace && page.source_total === 0 && <p className="p-3 text-sm text-text-3">No documents in this workspace match your search.</p>}
                        {page.source_next !== null && <button type="button" disabled={paging} onClick={() => void loadMore(false)} className="p-2 text-sm text-accent">Load more documents</button>}
                    </div>
                </div>
            )}
            <div className="flex shrink-0 items-center justify-between gap-2 border-t border-edge p-3">
                <span role="status" className="text-xs text-text-3">{searchAll ? 'All accessible documents' : `${selectedKeys.size} sources selected`}</span>
                <div className="flex gap-2">
                    <button type="button" onClick={() => { onClear(); if (searchAll) onToggleSearchAll?.(); }} className="rounded-lg px-2 py-2 text-sm text-text-2">Turn off / clear</button>
                    <button type="button" onClick={onClose} className="rounded-lg bg-accent px-3 py-2 text-sm text-white">Done</button>
                </div>
            </div>
            </fieldset>
        </div>, document.body,
    )}</>;
}
