// useWorkflowResource.ts
// Scoped workflow reads: retain the workbench while polling, never overlap polls, and stop on errors.

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../lib/apiClient';

const POLL_INTERVAL_MS = 2500;
const READ_TIMEOUT_MS = 30000;

interface WorkflowResourceState<T> {
    key: string;
    items: T[];
    loading: boolean;
    error: string | null;
    loadFailed: boolean;
}

export function useWorkflowResource<T>(
    key: string,
    load: (signal: AbortSignal) => Promise<T[]>,
    failureMessage: string,
    shouldPoll: (items: T[]) => boolean,
    onLoaded?: (items: T[]) => void,
) {
    const [state, setState] = useState<WorkflowResourceState<T>>({
        key, items: [], loading: true, error: null, loadFailed: false,
    });
    const callbacks = useRef({ load, shouldPoll, onLoaded });
    callbacks.current = { load, shouldPoll, onLoaded };
    const resource = useRef<{ key: string; refresh: () => Promise<void> } | null>(null);

    useEffect(() => {
        let disposed = false;
        let controller: AbortController | null = null;
        let timer: number | undefined;
        let timeout: number | undefined;
        let loaded = false;
        let polling = false;
        let inFlight = false;
        // Capture this scope's loader; a later render must never redirect an old request.
        const read = callbacks.current.load;
        setState({ key, items: [], loading: true, error: null, loadFailed: false });

        const schedule = () => {
            window.clearTimeout(timer);
            if (!disposed && !inFlight && polling && !document.hidden) {
                timer = window.setTimeout(() => void refresh(), POLL_INTERVAL_MS);
            }
        };
        const refresh = async () => {
            if (disposed) return;
            window.clearTimeout(timer);
            window.clearTimeout(timeout);
            controller?.abort();
            const request = new AbortController();
            controller = request;
            inFlight = true;
            setState((current) => ({ ...current, loading: !loaded }));
            const isCurrent = () => !disposed && controller === request && !request.signal.aborted;
            const fail = (accessLost = false) => {
                polling = false;
                setState((current) => ({
                    ...current, items: accessLost ? [] : current.items,
                    loading: false, error: failureMessage, loadFailed: true,
                }));
            };
            timeout = window.setTimeout(() => {
                if (!isCurrent()) return;
                inFlight = false;
                fail();
                request.abort();
            }, READ_TIMEOUT_MS);
            try {
                const items = await read(request.signal);
                if (!isCurrent()) return;
                loaded = true;
                polling = callbacks.current.shouldPoll(items);
                setState({ key, items, loading: false, error: null, loadFailed: false });
                callbacks.current.onLoaded?.(items);
            } catch (cause) {
                if (isCurrent()) fail(cause instanceof ApiError && [401, 403, 404].includes(cause.status));
            } finally {
                if (isCurrent()) {
                    inFlight = false;
                    window.clearTimeout(timeout);
                    schedule();
                }
            }
        };
        resource.current = { key, refresh };
        const onVisibilityChange = () => {
            if (document.hidden) window.clearTimeout(timer);
            else schedule();
        };
        document.addEventListener('visibilitychange', onVisibilityChange);
        void refresh();
        return () => {
            disposed = true;
            controller?.abort();
            window.clearTimeout(timer);
            window.clearTimeout(timeout);
            document.removeEventListener('visibilitychange', onVisibilityChange);
            resource.current = null;
        };
    }, [key, failureMessage]);

    const refresh = useCallback(async () => {
        if (resource.current?.key === key) await resource.current.refresh();
    }, [key]);
    const setItems = useCallback((update: (items: T[]) => T[]) => {
        setState((current) => current.key === key ? { ...current, items: update(current.items) } : current);
    }, [key]);
    const setError = useCallback((error: string | null) => {
        setState((current) => current.key === key ? { ...current, error } : current);
    }, [key]);

    // Do not render the previous workspace even for the frame before effect cleanup.
    const current = state.key === key ? state : { items: [] as T[], loading: true, error: null, loadFailed: false };
    return { ...current, refresh, setItems, setError };
}
