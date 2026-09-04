// DocumentPickerPopover.tsx
// The Documents button's menu.
//
// V2 shipped Documents as a plain on/off mapped to `hybrid_search`, with no way to say which
// documents. This replaces it with a picker, and keeps the original switch inside as the
// "search everything" case it always was -- the two are the server's `relevance` and
// `selected` selection modes, which is why they belong in one control rather than two.
//
// It opens upward. The composer sits at the bottom of the window, so a menu dropping downward
// is either clipped or covers the message being written. The classic interface drops its
// document dropdown down for the same reason V1's toolbar is above the input; V2's is below.
//
// It has a search box, which the classic dropdowns have and V2's do not. A workspace of any
// size is unusable without one.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, FileText, FolderOpen, Loader2, Search, Tag as TagIcon } from 'lucide-react';
import {
    searchContextCandidates,
    type ContextCandidate,
} from '../../lib/contextMentions';
import type { ContextSearchScope } from './ContextMenu';

const SEARCH_DEBOUNCE_MS = 250;

export function DocumentPickerPopover({
    scope,
    searchAll,
    selectedKeys,
    onToggleSearchAll,
    onToggle,
    onClear,
    onClose,
}: {
    scope: ContextSearchScope;
    /** The original Documents boolean: search everything by relevance. */
    searchAll: boolean;
    selectedKeys: ReadonlySet<string>;
    onToggleSearchAll: () => void;
    onToggle: (candidate: ContextCandidate) => void;
    onClear: () => void;
    onClose: () => void;
}) {
    const [query, setQuery] = useState('');
    const [candidates, setCandidates] = useState<ContextCandidate[]>([]);
    const [loading, setLoading] = useState(true);
    const holder = useRef<HTMLDivElement>(null);
    const searchRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        searchRef.current?.focus();
    }, []);

    useEffect(() => {
        const onPointerDown = (event: MouseEvent) => {
            if (!holder.current?.contains(event.target as Node)) {
                onClose();
            }
        };
        const onEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.stopPropagation();
                onClose();
            }
        };
        document.addEventListener('mousedown', onPointerDown);
        document.addEventListener('keydown', onEscape);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onEscape);
        };
    }, [onClose]);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);

        const timer = window.setTimeout(() => {
            searchContextCandidates({
                query,
                groups: scope.groups,
                publicWorkspaces: scope.publicWorkspaces,
                groupsEnabled: scope.groupsEnabled,
                publicEnabled: scope.publicEnabled,
                signal: controller.signal,
            })
                .then((found) => {
                    if (!controller.signal.aborted) {
                        setCandidates(found);
                        setLoading(false);
                    }
                })
                .catch(() => {
                    if (!controller.signal.aborted) {
                        setCandidates([]);
                        setLoading(false);
                    }
                });
        }, SEARCH_DEBOUNCE_MS);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
        // The scope arrays are rebuilt on every bootstrap read, so this keys on the flags and
        // the query rather than on array identity.
    }, [query, scope.groupsEnabled, scope.publicEnabled]);

    // Grouped by workspace, which is how the chip row groups them too: a reader scanning for
    // "the contract in Marketing" is looking for the workspace first.
    const byScope = new Map<string, { name: string; items: ContextCandidate[] }>();
    for (const candidate of candidates) {
        const key = `${candidate.scope.kind}:${candidate.scope.id ?? ''}`;
        const bucket = byScope.get(key);
        if (bucket) {
            bucket.items.push(candidate);
        } else {
            byScope.set(key, { name: candidate.scope.name, items: [candidate] });
        }
    }

    return (
        <div
            ref={holder}
            className="glass-modal absolute bottom-full left-2 z-50 mb-2 flex max-h-[26rem] w-96 flex-col rounded-xl p-1.5"
        >
            <div className="relative shrink-0 px-0.5 pb-1.5">
                <Search
                    size={13}
                    className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-3"
                    aria-hidden="true"
                />
                <input
                    ref={searchRef}
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search documents, tags and workspaces…"
                    aria-label="Search documents"
                    className={clsx(
                        'w-full rounded-lg border border-edge bg-surface-1 py-1.5 pl-7 pr-2',
                        'text-sm text-text-1 placeholder:text-text-3',
                        'focus:border-accent-ring focus:outline-none',
                    )}
                />
            </div>

            <button
                type="button"
                onClick={onToggleSearchAll}
                className={clsx(
                    'flex shrink-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm',
                    searchAll ? 'bg-accent-soft text-accent' : 'text-text-1 hover:bg-surface-2',
                )}
            >
                <span
                    className={clsx(
                        'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                        searchAll ? 'border-accent bg-accent text-white' : 'border-edge-strong',
                    )}
                >
                    {searchAll && <Check size={11} />}
                </span>
                <span className="min-w-0 flex-1">
                    <span className="block">Search all my documents</span>
                    <span className="block text-[11px] text-text-3">
                        Finds whatever is most relevant, rather than a fixed list
                    </span>
                </span>
            </button>

            <div className="my-1 h-px shrink-0 bg-edge-strong" aria-hidden="true" />

            <div className="min-h-0 flex-1 overflow-y-auto">
                {loading && candidates.length === 0 && (
                    <div className="flex items-center gap-2 px-2 py-3 text-xs text-text-3">
                        <Loader2 size={13} className="animate-spin" />
                        Searching your workspaces…
                    </div>
                )}

                {!loading && candidates.length === 0 && (
                    <p className="px-2 py-3 text-xs text-text-3">
                        {query.trim()
                            ? 'Nothing matches that.'
                            : 'No documents in your workspaces yet.'}
                    </p>
                )}

                {[...byScope.entries()].map(([key, bucket]) => (
                    <div key={key}>
                        <div className="px-2 pb-0.5 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-text-3">
                            {bucket.name}
                        </div>
                        {bucket.items.map((candidate) => {
                            const picked = selectedKeys.has(candidate.key);
                            const Icon =
                                candidate.kind === 'tag'
                                    ? TagIcon
                                    : candidate.kind === 'scope'
                                      ? FolderOpen
                                      : FileText;

                            return (
                                <button
                                    key={candidate.key}
                                    type="button"
                                    onClick={() => onToggle(candidate)}
                                    aria-pressed={picked}
                                    className={clsx(
                                        'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm',
                                        picked
                                            ? 'bg-accent-soft text-accent'
                                            : 'text-text-1 hover:bg-surface-2',
                                    )}
                                >
                                    <span
                                        className={clsx(
                                            'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                                            picked
                                                ? 'border-accent bg-accent text-white'
                                                : 'border-edge-strong',
                                        )}
                                    >
                                        {picked && <Check size={11} />}
                                    </span>
                                    <Icon size={13} className="shrink-0 text-text-3" />
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate">{candidate.label}</span>
                                        {candidate.subtitle && (
                                            <span className="block truncate text-[11px] text-text-3">
                                                {candidate.subtitle}
                                            </span>
                                        )}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                ))}
            </div>

            <div className="mt-1 flex shrink-0 items-center justify-between gap-2 border-t border-edge-strong px-1.5 pt-1.5">
                <span className="text-[11px] text-text-3">
                    Tip: type <span className="font-medium text-text-2">#</span> in your message
                </span>
                <div className="flex items-center gap-1">
                    {selectedKeys.size > 0 && (
                        <button
                            type="button"
                            onClick={onClear}
                            className="rounded-lg px-1.5 py-0.5 text-[11px] text-text-3 hover:bg-surface-2 hover:text-text-1"
                        >
                            Clear
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-lg px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft"
                    >
                        Done
                    </button>
                </div>
            </div>
        </div>
    );
}
