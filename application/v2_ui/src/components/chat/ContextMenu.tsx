// ContextMenu.tsx
// The `#` autocomplete for choosing documents, tags and workspaces.
//
// Third of the composer's three token menus, after `@` (people and models) and `/` (saved
// prompts), and deliberately built to the same shape: a debounced search behind a keyboard-
// navigable list that opens upward over the message box.
//
// The rows are typed rather than uniform because the three kinds mean genuinely different
// things to the request that follows -- a document is an id, a tag is a filter, a workspace is
// a scope -- and a list that hid that distinction would make "everything in Marketing" look
// like just another file.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { FileText, FolderOpen, Loader2, Tag as TagIcon } from 'lucide-react';
import {
    searchContextCandidates,
    type ContextCandidate,
} from '../../lib/contextMentions';
import type { ContextKind } from '../../lib/chatContext';
import type { WorkspaceRef } from '../../lib/types';

/** How long to wait after a keystroke before asking the server for candidates. */
const SEARCH_DEBOUNCE_MS = 250;

const ROW_ICON: Record<ContextKind, typeof FileText> = {
    document: FileText,
    tag: TagIcon,
    scope: FolderOpen,
};

const GROUP_LABEL: Record<ContextKind, string> = {
    document: 'Documents',
    tag: 'Tags',
    scope: 'Workspaces',
};

export interface ContextSearchScope {
    groups: WorkspaceRef[];
    publicWorkspaces: WorkspaceRef[];
    groupsEnabled: boolean;
    publicEnabled: boolean;
}

/**
 * Candidates for the query under the caret.
 *
 * Returns `loading` separately from an empty list so the menu can tell "still looking" from
 * "nothing matches". Collapsing the two makes a slow group workspace look like an empty one.
 */
export function useContextSuggestions(
    query: string | null,
    scope: ContextSearchScope,
): { candidates: ContextCandidate[]; loading: boolean } {
    const [candidates, setCandidates] = useState<ContextCandidate[]>([]);
    const [loading, setLoading] = useState(false);

    const groupIds = scope.groups.map((group) => group.id).join(',');
    const publicIds = scope.publicWorkspaces.map((workspace) => workspace.id).join(',');

    // The scope arrays are rebuilt on every bootstrap read, so the effect keys on their ids
    // rather than the arrays themselves; keying on identity would restart the search on every
    // unrelated render and the menu would never settle.
    const scopeRef = useRef(scope);
    scopeRef.current = scope;

    useEffect(() => {
        if (query === null) {
            setCandidates([]);
            setLoading(false);
            return;
        }

        const controller = new AbortController();
        setLoading(true);

        const timer = window.setTimeout(() => {
            searchContextCandidates({
                query,
                groups: scopeRef.current.groups,
                publicWorkspaces: scopeRef.current.publicWorkspaces,
                groupsEnabled: scopeRef.current.groupsEnabled,
                publicEnabled: scopeRef.current.publicEnabled,
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
                        // Every individual request is already settled independently, so
                        // reaching here means the fan-out itself failed. Offering nothing is
                        // better than an error banner over the message box.
                        setCandidates([]);
                        setLoading(false);
                    }
                });
        }, SEARCH_DEBOUNCE_MS);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [query, groupIds, publicIds, scope.groupsEnabled, scope.publicEnabled]);

    return { candidates, loading };
}

export function ContextMenu({
    candidates,
    loading,
    activeIndex,
    selectedKeys,
    onSelect,
}: {
    candidates: ContextCandidate[];
    loading: boolean;
    activeIndex: number;
    /** Keys already on the chip row, so a second pick reads as already-added. */
    selectedKeys: ReadonlySet<string>;
    onSelect: (candidate: ContextCandidate) => void;
}) {
    if (!loading && candidates.length === 0) {
        return null;
    }

    let lastKind: ContextKind | null = null;

    return (
        <div
            role="listbox"
            aria-label="Context suggestions"
            className="glass-modal absolute bottom-full left-2 z-50 mb-2 max-h-72 w-80 overflow-y-auto rounded-xl p-1"
        >
            {loading && candidates.length === 0 && (
                <div className="flex items-center gap-2 px-2.5 py-2 text-xs text-text-3">
                    <Loader2 size={13} className="animate-spin" />
                    Searching your workspaces…
                </div>
            )}

            {candidates.map((candidate, index) => {
                const Icon = ROW_ICON[candidate.kind];
                const heading = candidate.kind !== lastKind ? GROUP_LABEL[candidate.kind] : null;
                lastKind = candidate.kind;
                const already = selectedKeys.has(candidate.key);

                return (
                    <div key={candidate.key}>
                        {heading && (
                            <div className="px-2.5 pb-0.5 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-text-3">
                                {heading}
                            </div>
                        )}
                        <button
                            type="button"
                            role="option"
                            aria-selected={index === activeIndex}
                            // Pointer-down rather than click: the textarea loses focus on
                            // mouse-up, and the blur handler that closes the menu would remove
                            // the button before the click ever landed.
                            onMouseDown={(event) => {
                                event.preventDefault();
                                onSelect(candidate);
                            }}
                            className={clsx(
                                'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm',
                                index === activeIndex
                                    ? 'bg-accent-soft text-accent'
                                    : 'text-text-1 hover:bg-surface-2',
                            )}
                        >
                            <span className="shrink-0 text-text-3">
                                <Icon size={14} />
                            </span>
                            <span className="min-w-0 flex-1">
                                <span className="block truncate">{candidate.label}</span>
                                {candidate.subtitle && (
                                    <span className="block truncate text-[11px] text-text-3">
                                        {candidate.subtitle}
                                    </span>
                                )}
                            </span>
                            {already && (
                                <span className="shrink-0 text-[10px] text-text-3">Added</span>
                            )}
                        </button>
                    </div>
                );
            })}
        </div>
    );
}
