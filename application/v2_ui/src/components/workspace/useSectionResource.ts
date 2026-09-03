// useSectionResource.ts
// Loading, refreshing and error state for a workspace section's collection.
//
// Each section otherwise repeats the same twenty lines, and they tend to repeat them
// slightly differently: the interesting parts are the two that are easy to get wrong.
// A request in flight when the section changes is aborted, and a response that arrives
// after a newer request started is discarded, so switching sections quickly cannot leave
// one section showing another's rows.

import { useCallback, useEffect, useRef, useState } from 'react';

/** Turn anything thrown into something worth showing a user. */
export function errorMessage(error: unknown, fallback: string): string {
    if (error instanceof Error && error.message) {
        return error.message;
    }
    return fallback;
}

export interface SectionResource<T> {
    items: T[];
    loading: boolean;
    error: string | null;
    /** Refetch from the server. */
    refresh: () => Promise<void>;
    /** Apply a local change, for optimistic updates that a failure can roll back. */
    setItems: (next: T[]) => void;
    setError: (message: string | null) => void;
}

export function useSectionResource<T>(
    load: (signal: AbortSignal) => Promise<T[]>,
    failureMessage: string,
): SectionResource<T> {
    const [items, setItems] = useState<T[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Identifies the newest request. A response whose token no longer matches belongs to a
    // superseded request and is dropped rather than rendered.
    const requestToken = useRef(0);
    const abortRef = useRef<AbortController | null>(null);
    const loadRef = useRef(load);
    loadRef.current = load;

    const refresh = useCallback(async () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;

        requestToken.current += 1;
        const token = requestToken.current;

        setLoading(true);
        setError(null);
        try {
            const next = await loadRef.current(controller.signal);
            if (token === requestToken.current) {
                setItems(next);
            }
        } catch (loadError) {
            if (controller.signal.aborted || token !== requestToken.current) {
                return;
            }
            setError(errorMessage(loadError, failureMessage));
        } finally {
            if (token === requestToken.current) {
                setLoading(false);
            }
        }
    }, [failureMessage]);

    useEffect(() => {
        void refresh();
        return () => abortRef.current?.abort();
    }, [refresh]);

    return { items, loading, error, refresh, setItems, setError };
}
