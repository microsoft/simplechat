// GroupAssignmentField.tsx
// Picker for a settings value that stores a list of SimpleChat group ids.
//
// The server-rendered form puts this behind a modal that can only report "3 groups
// assigned": it searches the member-facing directory, keeps the result in a hidden JSON
// textarea, and never resolves an assigned id back to a name. An administrator therefore
// cannot tell which groups hold the capability without assigning them again.
//
// Here the assignment is visible. Saved ids are resolved to names through the admin
// directory endpoint and shown as removable chips, an id that no longer resolves is
// called out as stale rather than left to rot, and search is inline instead of modal.
//
// Edits are reported upward and buffered into the page's draft like any other field, so
// the assignment saves with the same save bar as the toggle that gates it. That matters:
// requiring assignment and choosing the assigned groups are one decision, and saving them
// apart would leave every group locked out in between.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Loader2, Search, Users, X } from 'lucide-react';
import { asStringArray, type AdminField } from '../../lib/adminFields';
import {
    resolveAdminGroups,
    searchAdminGroups,
    type AdminGroup,
} from '../../lib/adminGroups';
import { FieldNotice } from './fields';
import { GlassButton } from '../ui/primitives';

const SEARCH_DEBOUNCE_MS = 300;

function errorMessage(error: unknown, fallback: string): string {
    return error instanceof Error ? error.message : fallback;
}

export function GroupAssignmentField({
    field,
    value,
    error,
    disabled,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    disabled?: boolean;
    onChange: (next: string[]) => void;
}) {
    const endpoint = field.search_endpoint ?? '/api/v2/admin/groups';
    const assignedIds = useMemo(() => asStringArray(value), [value]);

    // Names accumulate across resolves and searches. Keeping them keyed by id means a
    // group stays labelled after the search that named it has been cleared.
    const [knownGroups, setKnownGroups] = useState<Record<string, AdminGroup>>({});
    // Ids already looked up, so a lookup is attempted once rather than on every render,
    // and the subset the directory confirmed do not exist. The two are separate because
    // "we asked and it is gone" and "the request failed" must not read the same on screen.
    const [attemptedIds, setAttemptedIds] = useState<ReadonlySet<string>>(new Set());
    const [missingIds, setMissingIds] = useState<ReadonlySet<string>>(new Set());
    const [resolveError, setResolveError] = useState<string | null>(null);

    const [query, setQuery] = useState('');
    const [browsing, setBrowsing] = useState(false);
    const [results, setResults] = useState<AdminGroup[] | null>(null);
    const [truncated, setTruncated] = useState(false);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);

    const learn = useCallback((groups: AdminGroup[]) => {
        if (!groups.length) {
            return;
        }
        setKnownGroups((current) => {
            const next = { ...current };
            for (const group of groups) {
                next[group.id] = group;
            }
            return next;
        });
    }, []);

    const unresolvedIds = useMemo(
        () => assignedIds.filter((id) => !knownGroups[id] && !attemptedIds.has(id)),
        [assignedIds, knownGroups, attemptedIds],
    );
    const unresolvedKey = unresolvedIds.join(',');

    useEffect(() => {
        if (!unresolvedKey) {
            return;
        }
        const pending = unresolvedKey.split(',');
        const controller = new AbortController();

        void (async () => {
            try {
                const groups = await resolveAdminGroups(endpoint, pending, controller.signal);
                if (controller.signal.aborted) {
                    return;
                }
                learn(groups);
                const found = new Set(groups.map((group) => group.id));
                // Whatever the directory did not return no longer exists. Recording that
                // is what lets a stale assignment be pointed out instead of silently
                // rendering as a bare id.
                setMissingIds((current) => {
                    const next = new Set(current);
                    for (const id of pending) {
                        if (!found.has(id)) {
                            next.add(id);
                        }
                    }
                    return next;
                });
                setResolveError(null);
            } catch (fetchError) {
                if (!controller.signal.aborted) {
                    // Deliberately not recorded as missing: a failed request is not a
                    // deleted group, and mislabelling it would invite an administrator to
                    // remove an assignment that is actually live.
                    setResolveError(
                        errorMessage(fetchError, 'Assigned groups could not be loaded.'),
                    );
                }
            } finally {
                if (!controller.signal.aborted) {
                    // Marked attempted either way, so a failure does not retry forever.
                    setAttemptedIds((current) => {
                        const next = new Set(current);
                        for (const id of pending) {
                            next.add(id);
                        }
                        return next;
                    });
                }
            }
        })();

        return () => controller.abort();
    }, [unresolvedKey, endpoint, learn]);

    useEffect(() => {
        if (!browsing) {
            return;
        }

        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            setSearching(true);
            void (async () => {
                try {
                    const page = await searchAdminGroups(endpoint, query, controller.signal);
                    if (!controller.signal.aborted) {
                        learn(page.groups);
                        setResults(page.groups);
                        setTruncated(page.truncated);
                        setSearchError(null);
                    }
                } catch (fetchError) {
                    if (!controller.signal.aborted) {
                        setResults([]);
                        setTruncated(false);
                        setSearchError(errorMessage(fetchError, 'Groups could not be loaded.'));
                    }
                } finally {
                    if (!controller.signal.aborted) {
                        setSearching(false);
                    }
                }
            })();
        }, SEARCH_DEBOUNCE_MS);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [browsing, query, endpoint, learn]);

    const assign = (id: string) => {
        if (assignedIds.includes(id)) {
            return;
        }
        onChange([...assignedIds, id]);
    };

    const unassign = (id: string) => {
        onChange(assignedIds.filter((assigned) => assigned !== id));
    };

    const describe = (id: string) => knownGroups[id];

    return (
        <div className="py-3">
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-text-1">{field.label}</span>
                <span className="text-xs text-text-3">
                    {assignedIds.length} group{assignedIds.length === 1 ? '' : 's'} assigned
                </span>
            </div>

            {assignedIds.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    <Users size={15} aria-hidden="true" />
                    No groups assigned, so no group can use this capability yet.
                </div>
            ) : (
                <ul className="flex flex-wrap gap-1.5">
                    {assignedIds.map((id) => {
                        const group = describe(id);
                        // Not knowing a name yet and knowing there is no group are
                        // different states, and only the second is a problem.
                        const stale = missingIds.has(id);
                        return (
                            <li key={id}>
                                <span
                                    className={clsx(
                                        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
                                        stale
                                            ? 'border-warn/40 bg-warn-soft text-warn'
                                            : 'border-edge bg-surface-2 text-text-1',
                                    )}
                                >
                                    {stale ? (
                                        <AlertCircle size={12} className="shrink-0" />
                                    ) : null}
                                    <span
                                        className={clsx(!group && 'font-mono text-[11px]')}
                                        title={group ? id : undefined}
                                    >
                                        {group?.name || id}
                                    </span>
                                    {stale ? (
                                        <span className="text-[10px] tracking-wide uppercase">
                                            Not found
                                        </span>
                                    ) : group ? (
                                        <span className="text-text-3">
                                            {group.member_count}
                                        </span>
                                    ) : null}
                                    <button
                                        type="button"
                                        aria-label={`Remove ${group?.name || id}`}
                                        title="Remove assignment"
                                        disabled={disabled}
                                        onClick={() => unassign(id)}
                                        className="-mr-1 rounded-full p-0.5 text-text-3 transition-colors hover:bg-danger-soft hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                                    >
                                        <X size={12} />
                                    </button>
                                </span>
                            </li>
                        );
                    })}
                </ul>
            )}

            {resolveError ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-warn">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {resolveError} The assignment is shown by id and still saves correctly.
                </p>
            ) : null}

            {browsing ? (
                <div className="mt-2 rounded-lg border border-edge bg-surface-1 p-2">
                    <div className="relative">
                        <Search
                            size={14}
                            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3"
                        />
                        <input
                            type="search"
                            autoFocus
                            value={query}
                            disabled={disabled}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search by group name, description or id…"
                            aria-label="Search groups to assign"
                            className={clsx(
                                'w-full rounded-lg border border-edge bg-surface-2 py-1.5 pr-2.5 pl-8',
                                'text-sm text-text-1 placeholder:text-text-3',
                                'focus:border-accent focus:outline-none',
                                'disabled:cursor-not-allowed disabled:opacity-60',
                            )}
                        />
                    </div>

                    {searchError ? (
                        <p
                            role="alert"
                            className="mt-2 flex items-start gap-1.5 text-xs text-danger"
                        >
                            <AlertCircle size={13} className="mt-0.5 shrink-0" />
                            {searchError}
                        </p>
                    ) : null}

                    {searching && results === null ? (
                        <p className="mt-2 flex items-center gap-2 py-2 text-xs text-text-3">
                            <Loader2 size={13} className="animate-spin" />
                            Loading groups…
                        </p>
                    ) : null}

                    {results !== null && results.length === 0 && !searchError ? (
                        <p className="mt-2 py-2 text-xs text-text-3">
                            {query.trim()
                                ? `No groups match “${query.trim()}”.`
                                : 'No groups exist yet.'}
                        </p>
                    ) : null}

                    {results !== null && results.length > 0 ? (
                        <ul className="mt-2 max-h-64 divide-y divide-edge overflow-y-auto">
                            {results.map((group) => {
                                const isAssigned = assignedIds.includes(group.id);
                                return (
                                    <li
                                        key={group.id}
                                        className="flex items-center gap-2 py-1.5"
                                    >
                                        <div className="min-w-0 flex-1">
                                            <p className="truncate text-sm text-text-1">
                                                {group.name || 'Unnamed group'}
                                            </p>
                                            <p className="truncate text-xs text-text-3">
                                                {group.description ||
                                                    `${group.member_count} member${
                                                        group.member_count === 1 ? '' : 's'
                                                    }`}
                                            </p>
                                        </div>
                                        <GlassButton
                                            type="button"
                                            variant={isAssigned ? 'ghost' : 'subtle'}
                                            size="sm"
                                            disabled={disabled}
                                            onClick={() =>
                                                isAssigned
                                                    ? unassign(group.id)
                                                    : assign(group.id)
                                            }
                                        >
                                            {isAssigned ? 'Remove' : 'Assign'}
                                        </GlassButton>
                                    </li>
                                );
                            })}
                        </ul>
                    ) : null}

                    {truncated ? (
                        <p className="mt-2 text-xs text-text-3">
                            More groups matched than are shown. Narrow the search to reach
                            the rest.
                        </p>
                    ) : null}
                </div>
            ) : null}

            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                className="mt-2"
                disabled={disabled}
                onClick={() => setBrowsing((current) => !current)}
            >
                <Search size={14} />
                {browsing ? 'Done' : 'Find groups'}
            </GlassButton>

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            <FieldNotice field={field} />

            {error ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}
