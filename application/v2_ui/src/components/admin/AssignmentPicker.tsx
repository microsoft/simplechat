// AssignmentPicker.tsx
// Editor for an `id_list` field: the set of groups or public workspaces a policy applies to.
//
// The value is a list of opaque record ids, and there is no endpoint that turns an id back
// into a name in bulk. The server-rendered admin page has the same constraint and answers
// it by summarising the selection as a count and resolving names only through search; this
// does the same rather than inventing a lookup the API cannot serve.
//
// Edits are reported upward into the page draft like any other field, so a change here is
// saved by the same Save button and is discarded by the same Cancel.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Loader2, Search, Users } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import { asStringArray, type AdminField } from '../../lib/adminFields';
import { AdminModal } from './AdminModal';
import { GlassButton } from '../ui/primitives';

/** One record the search endpoint offered. Only these three fields are relied on. */
interface AssignableRecord {
    id: string;
    name?: string;
    description?: string;
}

/** Pull the result array out of a response whose property name the schema declares. */
function readResults(payload: unknown, resultsKey: string): AssignableRecord[] {
    if (!payload || typeof payload !== 'object') {
        return [];
    }
    const candidate = (payload as Record<string, unknown>)[resultsKey];
    if (!Array.isArray(candidate)) {
        return [];
    }
    return candidate
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map((item) => ({
            id: String(item.id ?? ''),
            name: typeof item.name === 'string' ? item.name : undefined,
            description: typeof item.description === 'string' ? item.description : undefined,
        }))
        .filter((item) => item.id);
}

function buildSearchUrl(field: AdminField, term: string): string {
    const params = new URLSearchParams({ ...(field.search_extra ?? {}) });
    params.set(field.search_param ?? 'q', term);
    return `${field.search_endpoint}?${params.toString()}`;
}

function summarise(count: number, field: AdminField): string {
    const singular = field.item_noun ?? 'item';
    const plural = field.item_noun_plural ?? `${singular}s`;
    if (count === 0) {
        return `No ${plural} assigned.`;
    }
    return `${count} ${count === 1 ? singular : plural} assigned.`;
}

function PickerModal({
    field,
    selected,
    onToggle,
    onClose,
}: {
    field: AdminField;
    selected: string[];
    onToggle: (id: string, checked: boolean) => void;
    onClose: () => void;
}) {
    const [term, setTerm] = useState('');
    const [results, setResults] = useState<AssignableRecord[]>([]);
    const [status, setStatus] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [searching, setSearching] = useState(false);
    const searchRef = useRef<HTMLInputElement>(null);

    const runSearch = useCallback(
        async (query: string) => {
            if (!field.search_endpoint) {
                return;
            }
            setSearching(true);
            setError(null);
            try {
                const payload = await api.get<unknown>(buildSearchUrl(field, query));
                const records = readResults(payload, field.results_key ?? 'results');
                setResults(records);
                setStatus(
                    records.length
                        ? null
                        : query
                          ? `No ${field.item_noun_plural ?? 'records'} matched that search.`
                          : // Not every endpoint answers an empty term with a full list --
                            // the public workspace search requires two characters -- so an
                            // empty result for an empty term means "type something", not
                            // "nothing exists".
                            `Search to find ${field.item_noun_plural ?? 'records'} to assign.`,
                );
            } catch (searchError) {
                setResults([]);
                setStatus(null);
                setError(
                    searchError instanceof ApiError && searchError.status === 403
                        ? 'You do not have permission to search here, or the feature this search depends on is disabled.'
                        : searchError instanceof Error
                          ? searchError.message
                          : 'The search failed.',
                );
            } finally {
                setSearching(false);
            }
        },
        [field],
    );

    // Open with the unfiltered list where the endpoint returns one. The public workspace
    // search requires two characters and answers an empty term with nothing, so the status
    // line below tells the reader to type rather than leaving a bare empty list.
    useEffect(() => {
        void runSearch('');
        searchRef.current?.focus();
    }, [runSearch]);

    const plural = field.item_noun_plural ?? 'records';

    return (
        <AdminModal
            title={field.label}
            description={`Choose which ${plural} this policy applies to.`}
            size="lg"
            onClose={onClose}
            footer={
                <GlassButton variant="subtle" size="sm" onClick={onClose}>
                    Done
                </GlassButton>
            }
        >
            <form
                className="mb-3 flex items-center gap-2"
                onSubmit={(event) => {
                    event.preventDefault();
                    void runSearch(term.trim());
                }}
            >
                <div className="relative min-w-0 flex-1">
                    <Search
                        size={15}
                        className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                    />
                    <input
                        ref={searchRef}
                        type="search"
                        value={term}
                        onChange={(event) => setTerm(event.target.value)}
                        placeholder={`Search ${plural} by name or description`}
                        aria-label={`Search ${plural}`}
                        className={clsx(
                            'w-full rounded-lg border border-edge bg-surface-1 py-2 pr-3 pl-9',
                            'text-sm text-text-1 placeholder:text-text-3',
                            'focus:border-accent focus:outline-none',
                        )}
                    />
                </div>
                <GlassButton type="submit" variant="subtle" size="sm" disabled={searching}>
                    {searching ? <Loader2 size={14} className="animate-spin" /> : 'Search'}
                </GlassButton>
            </form>

            {error ? (
                <p
                    role="alert"
                    className="mb-3 flex items-start gap-1.5 rounded-lg bg-danger-soft px-3 py-2 text-xs text-danger"
                >
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}

            <p className="mb-2 text-xs text-text-3">
                {summarise(selected.length, field)} Assignments are kept even while a record
                is outside the current results, so searching never clears a selection.
            </p>

            {status ? <p className="py-6 text-center text-sm text-text-3">{status}</p> : null}

            <ul className="space-y-1">
                {results.map((record) => {
                    const checked = selected.includes(record.id);
                    const id = `assignment-${field.key}-${record.id}`;
                    return (
                        <li key={record.id}>
                            <label
                                htmlFor={id}
                                className={clsx(
                                    'flex cursor-pointer items-start gap-3 rounded-lg border border-edge px-3 py-2',
                                    checked ? 'bg-accent-soft' : 'hover:bg-surface-2',
                                )}
                            >
                                <input
                                    id={id}
                                    type="checkbox"
                                    className="mt-0.5 accent-[var(--accent)]"
                                    checked={checked}
                                    onChange={(event) =>
                                        onToggle(record.id, event.target.checked)
                                    }
                                />
                                <span className="min-w-0">
                                    <span className="block truncate text-sm text-text-1">
                                        {record.name || 'Unnamed'}
                                    </span>
                                    {record.description ? (
                                        <span className="block truncate text-xs text-text-3">
                                            {record.description}
                                        </span>
                                    ) : null}
                                </span>
                            </label>
                        </li>
                    );
                })}
            </ul>
        </AdminModal>
    );
}

export function AssignmentPicker({
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
    const [open, setOpen] = useState(false);
    const selected = asStringArray(value);

    const onToggle = (id: string, checked: boolean) => {
        onChange(checked ? [...selected, id] : selected.filter((item) => item !== id));
    };

    return (
        <div className="py-3">
            <p className="mb-1.5 text-sm font-medium text-text-1">{field.label}</p>

            <div className="flex flex-wrap items-center gap-2">
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    disabled={disabled}
                    onClick={() => setOpen(true)}
                >
                    <Users size={14} />
                    Manage
                </GlassButton>
                <span className="text-xs text-text-3">{summarise(selected.length, field)}</span>
            </div>

            {field.help ? (
                <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {error ? (
                <p
                    role="alert"
                    className="mt-1.5 flex items-start gap-1.5 text-xs text-danger"
                >
                    <AlertCircle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </p>
            ) : null}

            {open ? (
                <PickerModal
                    field={field}
                    selected={selected}
                    onToggle={onToggle}
                    onClose={() => setOpen(false)}
                />
            ) : null}
        </div>
    );
}
