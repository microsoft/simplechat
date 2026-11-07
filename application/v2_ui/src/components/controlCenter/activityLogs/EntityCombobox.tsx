// EntityCombobox.tsx
// A searchable list for picking a person or workspace by name instead of pasting an ID.
// Implements the ARIA combobox-with-listbox pattern: the input owns focus and the active
// option is announced through aria-activedescendant.

import { useEffect, useId, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Search } from 'lucide-react';
import { api } from '../../../lib/apiClient';

export interface EntityOption {
    key: string;
    primary: string;
    secondary?: string;
    badge?: string;
    /** An option that applies the typed text as an ID rather than a search match. */
    raw?: boolean;
}

export interface EntityResult {
    option: EntityOption;
    value: unknown;
}

const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 250;

export function EntityCombobox<Result>({
    label,
    placeholder,
    endpoint,
    toOptions,
    onSelect,
    emptyText,
    footer,
}: {
    label: string;
    placeholder: string;
    endpoint: string;
    /** Options for a response. Recomputed on every render, so they follow the caller's state. */
    toOptions: (response: Result, term: string) => EntityResult[];
    onSelect: (value: unknown, option: EntityOption) => void;
    emptyText: string;
    footer?: ReactNode;
}) {
    const id = useId();
    const listId = `${id}-list`;
    const [query, setQuery] = useState('');
    const [response, setResponse] = useState<{ data: Result; term: string } | null>(null);
    const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
    const [active, setActive] = useState(0);
    const [attempt, setAttempt] = useState(0);
    const term = query.trim();

    useEffect(() => {
        if (term.length < MIN_QUERY_LENGTH) {
            setResponse(null);
            setState('idle');
            return undefined;
        }
        const controller = new AbortController();
        setState('loading');
        const timer = window.setTimeout(() => {
            api.get<Result>(`${endpoint}?q=${encodeURIComponent(term)}`, controller.signal)
                .then((data) => {
                    if (controller.signal.aborted) return;
                    setResponse({ data, term });
                    setActive(0);
                    setState('ready');
                })
                .catch(() => {
                    if (!controller.signal.aborted) setState('error');
                });
        }, SEARCH_DEBOUNCE_MS);
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [endpoint, term, attempt]);

    const results = state === 'ready' && response ? toOptions(response.data, response.term) : [];
    const matches = results.filter((result) => !result.option.raw).length;
    const expanded = results.length > 0;
    const activeIndex = Math.min(active, Math.max(0, results.length - 1));
    const choose = (index: number) => {
        const result = results[index];
        if (result) onSelect(result.value, result.option);
    };

    return (
        <div className="space-y-2">
            <label htmlFor={`${id}-input`} className="block text-xs font-medium text-text-2">{label}</label>
            <div className="relative">
                <Search size={14} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3" />
                <input
                    id={`${id}-input`}
                    data-autofocus
                    type="text"
                    role="combobox"
                    autoComplete="off"
                    aria-autocomplete="list"
                    aria-expanded={expanded}
                    aria-controls={listId}
                    aria-activedescendant={expanded ? `${id}-option-${activeIndex}` : undefined}
                    value={query}
                    maxLength={200}
                    placeholder={placeholder}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                        if (!expanded) return;
                        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                            event.preventDefault();
                            const step = event.key === 'ArrowDown' ? 1 : -1;
                            setActive((activeIndex + step + results.length) % results.length);
                        } else if (event.key === 'Home' || event.key === 'End') {
                            event.preventDefault();
                            setActive(event.key === 'Home' ? 0 : results.length - 1);
                        } else if (event.key === 'Enter') {
                            event.preventDefault();
                            choose(activeIndex);
                        }
                    }}
                    className="h-9 w-full rounded-lg border border-edge bg-surface-1 pr-2 pl-8 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none"
                />
            </div>
            <ul id={listId} role="listbox" aria-label={label} className={clsx('max-h-64 overflow-y-auto', !expanded && 'hidden')}>
                {results.map((result, index) => (
                    <li
                        key={result.option.key}
                        id={`${id}-option-${index}`}
                        role="option"
                        aria-selected={index === activeIndex}
                        onMouseEnter={() => setActive(index)}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => choose(index)}
                        className={clsx(
                            'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm',
                            index === activeIndex ? 'bg-accent-soft text-text-1' : 'text-text-2',
                            result.option.raw && 'border-t border-edge',
                        )}
                    >
                        <span className="min-w-0 flex-1">
                            <span className={clsx('block truncate', result.option.raw ? 'text-text-1' : 'font-medium text-text-1')}>
                                {result.option.primary}
                            </span>
                            {result.option.secondary ? (
                                <span className="block truncate text-xs text-text-3">{result.option.secondary}</span>
                            ) : null}
                        </span>
                        {result.option.badge ? (
                            <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-text-2">
                                {result.option.badge}
                            </span>
                        ) : null}
                    </li>
                ))}
            </ul>
            <p role="status" aria-live="polite" className="text-xs text-text-3">
                {state === 'idle' ? `Type at least ${MIN_QUERY_LENGTH} characters of a name, email or ID.`
                    : state === 'loading' ? 'Searching…'
                        : state === 'error' ? null
                            : matches === 0 ? emptyText
                                : `${matches} ${matches === 1 ? 'match' : 'matches'}. Use the arrow keys, then Enter.`}
            </p>
            {state === 'error' ? (
                <p role="alert" className="text-xs text-danger">
                    Search failed.{' '}
                    <button type="button" className="font-medium underline" onClick={() => setAttempt((value) => value + 1)}>
                        Retry
                    </button>
                </p>
            ) : null}
            {footer}
        </div>
    );
}
