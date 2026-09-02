// WorkspaceListTab.tsx
// Shared list for the Groups and Public workspace settings tabs.
//
// Paging and search are server-side, so the search box is debounced rather than filtering a
// local array: the list may be longer than the page in hand, and filtering only what has
// been fetched would quietly hide matches.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Check, Loader2, Search } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import type { WorkspaceKind, WorkspaceSummary } from '../../lib/workspaces';
import { GlassPanel, Skeleton } from '../ui/primitives';

const PAGE_SIZE = 10;
const SEARCH_DEBOUNCE_MS = 300;

function RoleBadge({ role }: { role?: string }) {
    if (!role) {
        return null;
    }
    return (
        <span className="rounded-full border border-edge px-2 py-0.5 text-[11px] text-text-3">
            {role}
        </span>
    );
}

export function WorkspaceListTab({ kind }: { kind: WorkspaceKind }) {
    const [items, setItems] = useState<WorkspaceSummary[]>([]);
    const [page, setPage] = useState(1);
    const [totalCount, setTotalCount] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [search, setSearch] = useState('');
    const [activating, setActivating] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);

    const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [effectiveSearch, setEffectiveSearch] = useState('');

    const load = useCallback(
        async (targetPage: number, term: string) => {
            setLoading(true);
            setError(null);
            try {
                const result = await kind.list(targetPage, PAGE_SIZE, term);
                setItems(result.items);
                setTotalCount(result.totalCount);
                setPage(result.page);
            } catch (caught) {
                setError(
                    caught instanceof Error
                        ? caught.message
                        : `Failed to load your ${kind.pluralNoun}.`,
                );
            } finally {
                setLoading(false);
            }
        },
        [kind],
    );

    useEffect(() => {
        void load(1, effectiveSearch);
    }, [load, effectiveSearch]);

    const onSearchChange = (value: string) => {
        setSearch(value);
        if (searchTimer.current !== null) {
            clearTimeout(searchTimer.current);
        }
        searchTimer.current = setTimeout(() => setEffectiveSearch(value), SEARCH_DEBOUNCE_MS);
    };

    const activate = async (workspace: WorkspaceSummary) => {
        setActivating(workspace.id);
        setActionError(null);
        try {
            await kind.setActive(workspace.id);
            // Re-read rather than patching locally: which one is active is resolved
            // server-side against the caller's membership, so the server is authoritative.
            await load(page, effectiveSearch);
        } catch (caught) {
            setActionError(
                caught instanceof ApiError
                    ? caught.message
                    : `Could not switch to that ${kind.noun}.`,
            );
        } finally {
            setActivating(null);
        }
    };

    const lastPage = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

    return (
        <div className="space-y-3">
            <label className="relative block">
                <Search
                    size={15}
                    className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                />
                <input
                    value={search}
                    onChange={(event) => onSearchChange(event.target.value)}
                    placeholder={`Search ${kind.pluralNoun}`}
                    className="w-full rounded-xl border border-edge bg-surface-solid py-2 pr-3 pl-9 text-sm text-text-1 outline-none focus:border-accent"
                />
            </label>

            {actionError && (
                <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-2 text-xs text-danger">
                    {actionError}
                </p>
            )}

            {error ? (
                <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
                    {error}
                </p>
            ) : loading ? (
                <div className="space-y-2">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                </div>
            ) : items.length === 0 ? (
                <GlassPanel className="p-6 text-center">
                    <p className="text-sm text-text-2">
                        {effectiveSearch
                            ? `No ${kind.pluralNoun} match “${effectiveSearch}”.`
                            : `You are not a member of any ${kind.pluralNoun} yet.`}
                    </p>
                </GlassPanel>
            ) : (
                <ul className="space-y-2">
                    {items.map((workspace) => (
                        <li key={workspace.id}>
                            <GlassPanel className="flex items-center gap-3 p-3">
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-2">
                                        <span className="truncate text-sm font-medium text-text-1">
                                            {workspace.name || 'Untitled'}
                                        </span>
                                        <RoleBadge role={workspace.userRole} />
                                        {workspace.status && workspace.status !== 'active' && (
                                            <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] text-warn">
                                                {workspace.status}
                                            </span>
                                        )}
                                    </div>
                                    {workspace.description && (
                                        <p className="mt-0.5 truncate text-xs text-text-3">
                                            {workspace.description}
                                        </p>
                                    )}
                                </div>

                                {workspace.isActive ? (
                                    <span className="flex shrink-0 items-center gap-1.5 rounded-lg bg-ok-soft px-2.5 py-1.5 text-xs font-medium text-ok">
                                        <Check size={13} /> Active
                                    </span>
                                ) : (
                                    <button
                                        type="button"
                                        onClick={() => void activate(workspace)}
                                        disabled={activating !== null}
                                        className={clsx(
                                            'shrink-0 rounded-lg border border-edge px-2.5 py-1.5 text-xs font-medium text-text-1',
                                            'hover:bg-surface-2 disabled:opacity-60',
                                        )}
                                    >
                                        {activating === workspace.id ? (
                                            <Loader2 size={13} className="animate-spin" />
                                        ) : (
                                            'Set active'
                                        )}
                                    </button>
                                )}
                            </GlassPanel>
                        </li>
                    ))}
                </ul>
            )}

            {totalCount > PAGE_SIZE && (
                <div className="flex items-center justify-between text-xs text-text-3">
                    <span>
                        Page {page} of {lastPage} · {totalCount} {kind.pluralNoun}
                    </span>
                    <div className="flex gap-1.5">
                        <button
                            type="button"
                            disabled={page <= 1 || loading}
                            onClick={() => void load(page - 1, effectiveSearch)}
                            className="rounded-lg border border-edge px-2.5 py-1 text-text-1 hover:bg-surface-2 disabled:opacity-50"
                        >
                            Previous
                        </button>
                        <button
                            type="button"
                            disabled={page >= lastPage || loading}
                            onClick={() => void load(page + 1, effectiveSearch)}
                            className="rounded-lg border border-edge px-2.5 py-1 text-text-1 hover:bg-surface-2 disabled:opacity-50"
                        >
                            Next
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
