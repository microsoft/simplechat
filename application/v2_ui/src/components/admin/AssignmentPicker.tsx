// AssignmentPicker.tsx
// Search-and-assign editor for an `id_list` field.
//
// Some settings hold a list of opaque identifiers -- which groups may use File Sync,
// which public workspaces may use it. An identifier is not something an administrator
// can type from memory, so the control searches a declared endpoint and stores the id
// while showing the name.
//
// The server-rendered pane keeps these lists in hidden textareas and ships assignment
// modals whose JavaScript was never written, so the values are currently unreachable
// from that interface. This is the first control that can actually edit them.
//
// Nothing here knows about File Sync. The endpoint and the response shape are read from
// the field definition, so a second assignment list needs a schema entry and no code.

import { useCallback, useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Search, X } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { asString, type AdminField } from '../../lib/adminFields';
import { FieldShell } from './fields';

/** One search result, after the declared field names have been resolved. */
interface AssignmentOption {
    id: string;
    title: string;
    subtitle?: string;
}

/**
 * Minimum query length before a search is issued.
 *
 * Matches the server, which returns an empty list below two characters rather than
 * scanning the directory for every keystroke.
 */
const MIN_QUERY_LENGTH = 2;

const SEARCH_DEBOUNCE_MS = 300;

function readField(record: Record<string, unknown>, name: string | undefined): string {
    return name ? asString(record[name]) : '';
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
    const assigned = Array.isArray(value)
        ? value.filter((item): item is string => typeof item === 'string')
        : [];

    const [query, setQuery] = useState('');
    const [results, setResults] = useState<AssignmentOption[]>([]);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);

    /**
     * Names for ids that are already assigned.
     *
     * An id saved previously has no name until something looks it up, and the settings
     * document stores only the id. Names discovered through search are remembered here
     * so an assigned entry stops reading as a bare GUID once it has been seen.
     */
    const [labels, setLabels] = useState<Record<string, string>>({});

    const searchEndpoint = field.search_endpoint;
    const resultsKey = field.results_key ?? 'results';

    const runSearch = useCallback(
        async (candidate: string, signal: AbortSignal) => {
            if (!searchEndpoint || candidate.trim().length < MIN_QUERY_LENGTH) {
                setResults([]);
                setSearchError(null);
                return;
            }

            setSearching(true);
            setSearchError(null);
            try {
                const separator = searchEndpoint.includes('?') ? '&' : '?';
                const response = await api.get<Record<string, unknown>>(
                    `${searchEndpoint}${separator}q=${encodeURIComponent(candidate.trim())}`,
                    signal,
                );

                const rows = Array.isArray(response[resultsKey])
                    ? (response[resultsKey] as Record<string, unknown>[])
                    : [];

                const options = rows
                    .map((row) => ({
                        id: readField(row, field.value_field ?? 'id'),
                        title:
                            readField(row, field.title_field ?? 'name') ||
                            readField(row, field.value_field ?? 'id'),
                        subtitle: readField(row, field.subtitle_field),
                    }))
                    .filter((option) => option.id);

                setResults(options);
                setLabels((current) => {
                    const next = { ...current };
                    for (const option of options) {
                        next[option.id] = option.title;
                    }
                    return next;
                });
            } catch (caught) {
                // An aborted request is the previous keystroke being superseded, not a
                // failure worth showing.
                if (signal.aborted) {
                    return;
                }
                setSearchError(caught instanceof Error ? caught.message : 'Search failed.');
                setResults([]);
            } finally {
                if (!signal.aborted) {
                    setSearching(false);
                }
            }
        },
        [searchEndpoint, resultsKey, field.value_field, field.title_field, field.subtitle_field],
    );

    const controllerRef = useRef<AbortController | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        controllerRef.current?.abort();
        controllerRef.current = controller;

        const timer = window.setTimeout(() => {
            void runSearch(query, controller.signal);
        }, SEARCH_DEBOUNCE_MS);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [query, runSearch]);

    const assign = (option: AssignmentOption) => {
        if (assigned.includes(option.id)) {
            return;
        }
        onChange([...assigned, option.id]);
        setQuery('');
        setResults([]);
    };

    return (
        <FieldShell
            field={field}
            error={error ?? searchError ?? undefined}
            trailing={
                <span className="text-xs tabular-nums text-text-3">
                    {assigned.length} assigned
                </span>
            }
        >
            <div className="relative">
                <Search
                    size={14}
                    className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                />
                <input
                    type="search"
                    className={clsx(
                        'w-full rounded-lg border border-edge bg-surface-1 py-2 pr-8 pl-9',
                        'text-sm text-text-1 placeholder:text-text-3',
                        'focus:border-accent focus:outline-none',
                        'disabled:cursor-not-allowed disabled:opacity-60',
                    )}
                    value={query}
                    placeholder={field.placeholder ?? 'Search by name'}
                    disabled={disabled}
                    onChange={(event) => setQuery(event.target.value)}
                />
                {searching ? (
                    <Loader2
                        size={14}
                        className="absolute top-1/2 right-3 -translate-y-1/2 animate-spin text-text-3"
                    />
                ) : null}
            </div>

            {query.trim().length >= MIN_QUERY_LENGTH && !searching && !results.length ? (
                <p className="mt-2 text-xs text-text-3">No matches.</p>
            ) : null}

            {results.length ? (
                <ul className="mt-2 max-h-52 overflow-y-auto rounded-lg border border-edge">
                    {results.map((option) => {
                        const already = assigned.includes(option.id);
                        return (
                            <li key={option.id}>
                                <button
                                    type="button"
                                    className={clsx(
                                        'flex w-full flex-col items-start gap-0.5 border-b border-edge px-3 py-2 text-left last:border-b-0',
                                        already
                                            ? 'cursor-default opacity-50'
                                            : 'hover:bg-surface-2',
                                    )}
                                    disabled={disabled || already}
                                    onClick={() => assign(option)}
                                >
                                    <span className="text-sm text-text-1">{option.title}</span>
                                    {option.subtitle ? (
                                        <span className="text-xs text-text-3">
                                            {option.subtitle}
                                        </span>
                                    ) : null}
                                    {already ? (
                                        <span className="text-xs text-text-3">
                                            Already assigned
                                        </span>
                                    ) : null}
                                </button>
                            </li>
                        );
                    })}
                </ul>
            ) : null}

            {assigned.length ? (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                    {assigned.map((id) => (
                        <li
                            key={id}
                            className="flex items-center gap-1.5 rounded-full border border-edge bg-surface-1 py-1 pr-1 pl-3 text-xs text-text-2"
                        >
                            {/* Falls back to the id when the name has never been
                                fetched, which is honest about what is stored. */}
                            <span>{labels[id] ?? id}</span>
                            <button
                                type="button"
                                aria-label={`Remove ${labels[id] ?? id}`}
                                className="rounded-full p-0.5 text-text-3 hover:bg-surface-2 hover:text-danger disabled:cursor-not-allowed"
                                disabled={disabled}
                                onClick={() => onChange(assigned.filter((item) => item !== id))}
                            >
                                <X size={12} />
                            </button>
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="mt-2 text-xs text-text-3">Nothing assigned yet.</p>
            )}
        </FieldShell>
    );
}
