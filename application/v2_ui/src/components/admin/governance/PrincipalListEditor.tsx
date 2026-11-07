// PrincipalListEditor.tsx
// Edits one list of governance principals: the people or the groups a policy allows or blocks.
//
// The classic page kept these lists in hidden comma-separated inputs behind a modal with its
// own paging, and named an entry only after an extra lookup per id. Here the list is visible
// where it is decided: each entry is a chip with its resolved name, search is inline, and
// pasting ids (the classic CSV import) merges into or replaces the list in place.
//
// Groups cover both group workspaces and public workspaces, because a person's governance
// groups are resolved from both memberships. The list is a cohort for governance only; being
// in one grants nothing inside that workspace.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, ClipboardPaste, Loader2, Search, X } from 'lucide-react';
import {
    applyPrincipalImport,
    searchPrincipals,
    type PrincipalEntry,
    type PrincipalKind,
} from '../../../lib/governance';
import { GlassButton } from '../../ui/primitives';
import { usePrincipalLabels } from './usePrincipalLabels';

const SEARCH_DEBOUNCE_MS = 300;
/** Chips shown before the list collapses behind "Show all". */
const COLLAPSED_CHIP_LIMIT = 24;

const NOUNS: Record<PrincipalKind, { one: string; many: string; search: string }> = {
    users: { one: 'person', many: 'people', search: 'Search people by name or email' },
    groups: { one: 'group', many: 'groups', search: 'Search group or public workspaces by name or ID' },
};

function countText(kind: PrincipalKind, count: number): string {
    const nouns = NOUNS[kind];
    return `${count} ${count === 1 ? nouns.one : nouns.many}`;
}

export interface PrincipalListEditorProps {
    kind: PrincipalKind;
    /** Heading for the list, such as "Allowed people". */
    title: string;
    ids: string[];
    onChange: (next: string[]) => void;
    tone: 'allow' | 'block';
    emptyText: string;
    /** Unique prefix for element ids, since several lists share one dialog. */
    idPrefix: string;
    disabled?: boolean;
}

export function PrincipalListEditor({
    kind,
    title,
    ids,
    onChange,
    tone,
    emptyText,
    idPrefix,
    disabled = false,
}: PrincipalListEditorProps) {
    const nouns = NOUNS[kind];
    const [showAll, setShowAll] = useState(false);
    const [filter, setFilter] = useState('');
    const [panel, setPanel] = useState<'search' | 'paste' | null>(null);

    const [query, setQuery] = useState('');
    const [results, setResults] = useState<PrincipalEntry[] | null>(null);
    const [truncated, setTruncated] = useState(false);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);
    const [pasteText, setPasteText] = useState('');

    const filtered = useMemo(() => {
        const needle = filter.trim().toLowerCase();
        return needle ? ids.filter((id) => id.toLowerCase().includes(needle)) : ids;
    }, [ids, filter]);
    const visible = showAll || filter ? filtered : filtered.slice(0, COLLAPSED_CHIP_LIMIT);
    const labels = usePrincipalLabels(kind, visible);

    // A filter that also matches names needs the names, so it reads them from the cache
    // once they are known rather than only matching the raw id.
    const matchesFilter = (id: string) => {
        const needle = filter.trim().toLowerCase();
        if (!needle) {
            return true;
        }
        const lookup = labels.lookup(id);
        const name = lookup?.status === 'found' ? `${lookup.entry.name} ${lookup.entry.detail ?? ''}` : '';
        return `${id} ${name}`.toLowerCase().includes(needle);
    };
    const shown = filter ? ids.filter(matchesFilter) : visible;

    useEffect(() => {
        if (panel !== 'search') {
            return;
        }
        // People search needs a term; groups can be browsed before typing.
        if (kind === 'users' && !query.trim()) {
            setResults(null);
            setSearchError(null);
            return;
        }
        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            setSearching(true);
            void searchPrincipals(kind, query, controller.signal)
                .then((page) => {
                    if (!controller.signal.aborted) {
                        setResults(page.entries);
                        setTruncated(page.truncated);
                        setSearchError(null);
                    }
                })
                .catch((error: unknown) => {
                    if (!controller.signal.aborted) {
                        setResults([]);
                        setTruncated(false);
                        setSearchError(
                            error instanceof Error && error.message
                                ? error.message
                                : `${nouns.many[0].toUpperCase()}${nouns.many.slice(1)} could not be searched.`,
                        );
                    }
                })
                .finally(() => {
                    if (!controller.signal.aborted) {
                        setSearching(false);
                    }
                });
        }, SEARCH_DEBOUNCE_MS);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [panel, query, kind, nouns.many]);

    const add = (id: string) => {
        if (!ids.includes(id)) {
            onChange([...ids, id]);
        }
    };
    const remove = (id: string) => onChange(ids.filter((entry) => entry !== id));

    const applyPaste = (mode: 'merge' | 'replace') => {
        onChange(applyPrincipalImport(ids, pasteText, mode));
        setPasteText('');
        setPanel(null);
    };

    const chipTone = tone === 'block'
        ? 'border-danger/30 bg-danger-soft text-text-1'
        : 'border-edge bg-surface-2 text-text-1';

    return (
        <div className="min-w-0" role="group" aria-labelledby={`${idPrefix}-title`}>
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                <span id={`${idPrefix}-title`} className="text-sm font-medium text-text-1">{title}</span>
                <span className="text-xs text-text-3">{countText(kind, ids.length)}</span>
            </div>

            {ids.length > COLLAPSED_CHIP_LIMIT ? (
                <div className="relative mb-2">
                    <Search size={13} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3" />
                    <input
                        type="search"
                        value={filter}
                        onChange={(event) => setFilter(event.target.value)}
                        placeholder={`Find in these ${nouns.many}`}
                        aria-label={`Find in ${title.toLowerCase()}`}
                        className="w-full rounded-lg border border-edge bg-surface-1 py-1.5 pr-2.5 pl-8 text-xs text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                    />
                </div>
            ) : null}

            {ids.length === 0 ? (
                <p className="rounded-lg border border-dashed border-edge px-3 py-3 text-xs text-text-3">{emptyText}</p>
            ) : (
                <ul className="flex flex-wrap gap-1.5" aria-label={title}>
                    {shown.map((id) => {
                        const lookup = labels.lookup(id);
                        const entry = lookup?.status === 'found' ? lookup.entry : undefined;
                        const missing = lookup?.status === 'missing';
                        const name = entry?.name || id;
                        return (
                            <li key={id}>
                                <span
                                    className={clsx(
                                        'inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
                                        missing ? 'border-warn/40 bg-warn-soft text-warn' : chipTone,
                                    )}
                                    title={entry?.detail ? `${entry.detail} · ${id}` : id}
                                >
                                    {missing ? <AlertCircle size={12} aria-hidden="true" className="shrink-0" /> : null}
                                    <span className={clsx('truncate', !entry?.name && 'font-mono text-[11px]')}>{name}</span>
                                    {entry?.kind === 'public_workspace' ? (
                                        <span className="shrink-0 rounded-full bg-surface-sunken px-1.5 text-[10px] text-text-3">Public</span>
                                    ) : null}
                                    {missing ? (
                                        <span className="shrink-0 text-[10px] tracking-wide uppercase">
                                            {kind === 'groups' ? 'Not found' : 'Unresolved'}
                                        </span>
                                    ) : null}
                                    <button
                                        type="button"
                                        aria-label={`Remove ${name}`}
                                        title="Remove"
                                        disabled={disabled}
                                        onClick={() => remove(id)}
                                        className="-mr-1 shrink-0 rounded-full p-0.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                        <X size={12} />
                                    </button>
                                </span>
                            </li>
                        );
                    })}
                </ul>
            )}

            {!filter && !showAll && ids.length > COLLAPSED_CHIP_LIMIT ? (
                <button type="button" onClick={() => setShowAll(true)} className="mt-1.5 text-xs text-accent hover:underline">
                    Show all {countText(kind, ids.length)}
                </button>
            ) : null}
            {labels.failed ? (
                <p role="status" className="mt-1.5 text-xs text-warn">
                    Some names could not be loaded. Entries are shown by ID and still save correctly.
                </p>
            ) : null}
            {labels.resolving ? (
                <p className="mt-1.5 flex items-center gap-1.5 text-xs text-text-3">
                    <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                    Looking up names…
                </p>
            ) : null}

            {panel === 'search' ? (
                <div className="mt-2 rounded-lg border border-edge bg-surface-1 p-2">
                    <div className="relative">
                        <Search size={14} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3" />
                        <input
                            type="search"
                            autoFocus
                            value={query}
                            disabled={disabled}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder={nouns.search}
                            aria-label={nouns.search}
                            className="w-full rounded-lg border border-edge bg-surface-2 py-1.5 pr-2.5 pl-8 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none disabled:opacity-60"
                        />
                    </div>
                    {searchError ? (
                        <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-danger">
                            <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                            {searchError}
                        </p>
                    ) : null}
                    {searching && results === null ? (
                        <p className="mt-2 flex items-center gap-2 py-1 text-xs text-text-3">
                            <Loader2 size={13} className="animate-spin" aria-hidden="true" />
                            Searching…
                        </p>
                    ) : null}
                    {kind === 'users' && !query.trim() ? (
                        <p className="mt-2 py-1 text-xs text-text-3">Type a name or email address to search the directory.</p>
                    ) : null}
                    {results !== null && results.length === 0 && !searchError && query.trim() ? (
                        <p className="mt-2 py-1 text-xs text-text-3">No {nouns.many} match “{query.trim()}”.</p>
                    ) : null}
                    {results !== null && results.length > 0 ? (
                        <ul className="mt-2 max-h-56 divide-y divide-edge overflow-y-auto" aria-label={`Matching ${nouns.many}`}>
                            {results.map((entry) => {
                                const added = ids.includes(entry.id);
                                return (
                                    <li key={entry.id} className="flex items-center gap-2 py-1.5">
                                        <div className="min-w-0 flex-1">
                                            <p className="flex items-center gap-1.5 truncate text-sm text-text-1">
                                                <span className="truncate">{entry.name || entry.id}</span>
                                                {entry.kind === 'public_workspace' ? (
                                                    <span className="shrink-0 rounded-full bg-surface-sunken px-1.5 text-[10px] text-text-3">Public workspace</span>
                                                ) : null}
                                            </p>
                                            <p className="truncate text-xs text-text-3">{entry.detail || entry.id}</p>
                                        </div>
                                        <GlassButton
                                            type="button"
                                            size="sm"
                                            variant={added ? 'ghost' : 'subtle'}
                                            disabled={disabled}
                                            aria-label={`${added ? 'Remove' : 'Add'} ${entry.name || entry.id}`}
                                            onClick={() => (added ? remove(entry.id) : add(entry.id))}
                                        >
                                            {added ? 'Remove' : 'Add'}
                                        </GlassButton>
                                    </li>
                                );
                            })}
                        </ul>
                    ) : null}
                    {truncated ? (
                        <p className="mt-2 text-xs text-text-3">More matched than are shown. Narrow the search to reach the rest.</p>
                    ) : null}
                </div>
            ) : null}

            {panel === 'paste' ? (
                <div className="mt-2 rounded-lg border border-edge bg-surface-1 p-2">
                    <label htmlFor={`${idPrefix}-paste`} className="mb-1 block text-xs text-text-2">
                        Paste {nouns.one} IDs, one per line or separated by commas
                    </label>
                    <textarea
                        id={`${idPrefix}-paste`}
                        rows={3}
                        value={pasteText}
                        disabled={disabled}
                        onChange={(event) => setPasteText(event.target.value)}
                        className="w-full resize-y rounded-lg border border-edge bg-surface-2 px-2.5 py-1.5 font-mono text-xs text-text-1 focus:border-accent focus:outline-none"
                    />
                    <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
                        <GlassButton type="button" size="sm" variant="ghost" onClick={() => { setPasteText(''); setPanel(null); }}>
                            Cancel
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="subtle" disabled={disabled || !pasteText.trim()} onClick={() => applyPaste('replace')}>
                            Replace list
                        </GlassButton>
                        <GlassButton type="button" size="sm" variant="primary" disabled={disabled || !pasteText.trim()} onClick={() => applyPaste('merge')}>
                            Add to list
                        </GlassButton>
                    </div>
                </div>
            ) : null}

            <div className="mt-2 flex flex-wrap gap-1.5">
                <GlassButton
                    type="button"
                    size="sm"
                    variant="subtle"
                    disabled={disabled}
                    aria-expanded={panel === 'search'}
                    onClick={() => setPanel((current) => (current === 'search' ? null : 'search'))}
                >
                    <Search size={14} aria-hidden="true" />
                    {panel === 'search' ? 'Done' : `Find ${nouns.many}`}
                </GlassButton>
                <GlassButton
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={disabled}
                    aria-expanded={panel === 'paste'}
                    onClick={() => setPanel((current) => (current === 'paste' ? null : 'paste'))}
                >
                    <ClipboardPaste size={14} aria-hidden="true" />
                    Paste IDs
                </GlassButton>
                {ids.length ? (
                    <GlassButton type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange([])}>
                        Clear
                    </GlassButton>
                ) : null}
            </div>
        </div>
    );
}
